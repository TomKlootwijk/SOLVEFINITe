"""DP8 Wv2 source-bound lifecycle capture; full mode requires actual GPU work.

Raw IGNITE bytes may use the host codec. GPU owner words and generated geometry
may not. Archive reads here are evidence instrumentation, not public W methods.
"""
import argparse
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from examples import welip_conformance as legacy
from solvefinite.f8 import IndexBinding
from solvefinite.runtime import write_json
from solvefinite.welip import WelipConfig, validate_record
from solvefinite.welip_session import WelipSession


ROOT = Path(__file__).resolve().parents[1]
FORMAL_COMMIT = "1979e66634c10fc8ede019fd677434bb1dba4a7d"
REFERENCE_PATH = ROOT / "docs/evidence/directional-v1/formal-reference.json"
REFERENCE_SHA = "06bea44766da9d10f404c74750c5a7e1696fd54d67e5a2b0927e40d19c91200d"
LIFECYCLES = ("w_v2_lifecycle", "w_v2_mirrored_lifecycle", "w_v2_capacity8_lifecycle")
FORBIDDEN_TAPER_PRODUCERS = (
    "solvefinite.taper.interpret_cpu", "solvefinite.taper.occupancy_cpu",
    "solvefinite.taper.union_signs_cpu", "solvefinite.taper.signs_from_occupancy_cpu",
    "solvefinite.taper.regenerate",
    "solvefinite.taper.evaluate_field", "solvefinite.taper.TaperFieldRecipe.field_manifest",
    "solvefinite.tomigidt.regenerate_taper",
)


def check(condition, label):
    if type(condition) is not bool or not condition:
        raise ValueError("Taper Wv2 conformance failed: " + label)
    return True


def reference():
    raw = REFERENCE_PATH.read_bytes().replace(b"\r\n", b"\n")
    check(legacy.sha(raw) == REFERENCE_SHA, "frozen formal-first reference identity")
    return json.loads(raw)


def no_cpu_state_producers():
    stack = ExitStack()
    stack.enter_context(legacy.no_cpu_state_producers())
    for name in FORBIDDEN_TAPER_PRODUCERS:
        stack.enter_context(patch(name, side_effect=AssertionError("Forbidden CPU producer: " + name)))
    return stack


def lifecycle(directory, label, literal, backend):
    state = directory / (label + ".json")
    config = WelipConfig.from_dict(literal["config"])
    guard = no_cpu_state_producers() if backend == "gpu" else nullcontext()
    with guard, WelipSession(state, config, backend=backend,
                            index_binding=IndexBinding(31, -1, 173)) as session:
        check(session.ready() == literal["ready"], label + " initial READY")
        seed_guard = patch("solvefinite.field_agent_gpu.GpuFieldAgentExecutor.seed",
                           side_effect=AssertionError("Host reseed after initial ownership")) if backend == "gpu" else nullcontext()
        with seed_guard:
            for index, row in enumerate(literal["operations"]):
                reply = session.handle(deepcopy(row["request"]))
                check(reply == literal["results"][index], label + " full frozen response")
                saved = legacy.read_archive(state)
                check(saved["operations"] == literal["operations"][:index + 1], label + " exact saved prefix")
                for record in reply["records"]:
                    validate_record(record, config, expected_pair=int(row["agent_pair"], 16),
                                    expected_energy=row["energy"])
                if backend == "gpu":
                    executor = session._agent._gpu
                    check(executor.snapshot() == (session._agent.agent_pair, session._agent.energy),
                          label + " actual persistent owner pair and energy")
                    check(executor._ticks == literal["executor_action_tick_expectations"][index]["executor_action_ticks"],
                          label + " original executor action count")
                before = state.read_bytes(), session._agent.archive(), session._cache()
                with patch.object(session._agent, "step", side_effect=AssertionError("retry action")), \
                        patch.object(session._agent, "emit_welip_state", side_effect=AssertionError("retry emission")), \
                        patch("solvefinite.welip_session.write_json", side_effect=AssertionError("retry save")):
                    retry = session.handle(deepcopy(row["request"]))
                check(retry == literal["latest_retry_receipts"][index], label + " latest-only retry")
                check((state.read_bytes(), session._agent.archive(), session._cache()) == before,
                      label + " retry preserves all owned state")
        archive = legacy.read_archive(state)
        check(archive["format"] == literal["session_format"], label + " archive version")
        check(archive["expected"] == literal["expected"], label + " final clock/cache")
        check(legacy.canonical_hash(archive["operations"]) == literal["operation_transcript_sha256"],
              label + " literal operation transcript digest")
        check((len(archive["operations"]), sum(len(r["records"]) for r in archive["operations"]),
               sum(x["fragment_count"] for r in archive["operations"] for x in r["records"])) == (19, 20, 41),
              label + " complete 19-operation,20-record,41-word lifecycle")
        check(session._agent.status == "COMPLETE" and session._agent.cycle == 11,
              label + " same finite individual completes after 11 cycles")
        execution = session._agent.execution_info
    return {"archive": archive, "record_count": 20, "fragment_count": 41,
            "execution_info": execution, **legacy.saved_identity(archive)}


def fresh_processes(directory, literal, expected_archive, cpu_only):
    state, config = directory / "fresh.json", directory / "fresh-config.json"
    write_json(config, literal["config"])
    captures = []
    for index, (start, stop, backend) in enumerate(((0, 7, "cpu" if cpu_only else "gpu"),
                                                   (7, 13, "cpu"),
                                                   (13, 19, "cpu" if cpu_only else "gpu"))):
        requests, expected = [], []
        if start:
            requests.append(literal["operations"][start - 1]["request"])
            expected.append(literal["latest_retry_receipts"][start - 1])
        for ordinal in range(start, stop):
            requests.append(literal["operations"][ordinal]["request"])
            expected.append(literal["results"][ordinal])
        requests.append(literal["operations"][stop - 1]["request"])
        expected.append(literal["latest_retry_receipts"][stop - 1])
        command = [sys.executable, "-m", "examples.taper_welip_conformance", "--guarded-cli",
                   "--state", str(state), "--backend", backend, "--index-epoch", str(10 + index),
                   "--index-sign", "-1", "--index-phase-origin", str(47 * index)]
        if index == 0:
            command += ["--config", str(config)]
        process = subprocess.run(command, cwd=ROOT, input="".join(json.dumps(r) + "\n" for r in requests),
                                 text=True, encoding="utf-8", capture_output=True, timeout=180,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            raise RuntimeError(f"Fresh Wv2 endpoint failed: {process.stderr}\n{process.stdout}")
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        check(replies[1:] == expected, "fresh process complete responses and boundary retries")
        if start == 0:
            ready = literal["ready"]
        else:
            ready = {key: literal["results"][start - 1][key]
                     for key in ("protocol", "producer", "producer_epoch", "head", "next")}
            ready.update(type="READY", restored=True)
        check(replies[0] == ready, "private reconstruction emits only current READY")
        archive = legacy.read_archive(state)
        check(archive["operations"] == literal["operations"][:stop], "fresh process exact original ledger")
        captures.append({"backend": backend, "command": command, "requests": requests,
                         "responses": replies, "stderr": process.stderr, **legacy.saved_identity(archive)})
    check(legacy.read_archive(state) == expected_archive, "backend/index changes preserve complete archive")
    return {"captures": captures, "final_archive_sha256": legacy.canonical_hash(expected_archive)}


def identity_scope(directory, literal, archive, vector):
    v1, v2 = (WelipConfig.from_dict(vector[key]) for key in ("v1_config", "v2_config"))
    check(v1 != v2 and v1.protocol != v2.protocol, "distinct retained namespace")
    check(v1.manifest.world.baseline_id == v2.manifest.world.baseline_id, "baseline remains a label")
    validate_record(vector["identical_state_record"], v1)
    validate_record(vector["identical_state_record"], v2)
    state = directory / "identity.json"
    write_json(state, archive)
    saved = state.read_bytes()
    with patch("solvefinite.welip_session.Tomigidt") as allocate:
        try:
            with WelipSession(state, v1):
                raise AssertionError("Cross-profile owner opened")
        except ValueError:
            pass
        check(not allocate.called, "cross-profile configuration rejects before owner allocation")
    check(state.read_bytes() == saved, "identity rejection preserves saved history")
    old = legacy.lifecycle(directory, "legacy-v1", legacy.reference()["main_lifecycle"], "cpu")
    check(old["agent_archive_sha256"] == legacy.OG_ARCHIVE_SHA, "historical OG archive identity")
    check(old["welip_archive_sha256"] == "9dd6e452c43b37482d6b780786b76f40a80e41846d67feb8c9af6a2e10b8b9c1",
          "historical Wv1 archive identity")
    return {"bare_initial_record_equal": True, "cross_profile_rejected_before_allocation": True,
            "config_sha256": {"v1": legacy.canonical_hash(v1.to_dict()), "v2": legacy.canonical_hash(v2.to_dict())},
            "legacy_v1": legacy.saved_identity(old["archive"])}


def demonstrate(cpu_only=False):
    if type(cpu_only) is not bool:
        raise ValueError("cpu_only must be a Boolean")
    started = perf_counter()
    expected = reference()
    captures, checks = {}, {}
    with TemporaryDirectory(prefix="taper-welip-conformance-") as temporary:
        directory = Path(temporary)
        for name in LIFECYCLES:
            literal = expected[name]
            cpu = lifecycle(directory, name + "-cpu", literal, "cpu")
            group = {"cpu": cpu}
            checks[name + "_cpu"] = True
            if not cpu_only:
                gpu = lifecycle(directory, name + "-gpu", literal, "gpu")
                check(gpu["archive"] == cpu["archive"], name + " CPU/GPU exact canonical history")
                group["gpu"] = gpu
                checks[name + "_gpu"] = True
            captures[name] = group
        main = captures[LIFECYCLES[0]]["cpu"]
        fresh = fresh_processes(directory, expected[LIFECYCLES[0]], main["archive"], cpu_only)
        checks["fresh_process_continuation"] = True
        identities = identity_scope(directory, expected[LIFECYCLES[0]], main["archive"], expected["cross_profile_identity_vector"])
        checks["namespace_and_legacy_identity"] = True
    adapter = None if cpu_only else captures[LIFECYCLES[0]]["gpu"]["execution_info"]["adapter"]
    if not cpu_only:
        check(adapter["adapter_type"] in ("DiscreteGPU", "IntegratedGPU"), "actual hardware adapter required")
    report = {"format": "taper-welip-conformance-v1", "formal_binding_commit": FORMAL_COMMIT,
            "reference_sha256_lf": REFERENCE_SHA, "partial": cpu_only, "actual_GPU_capture": not cpu_only,
            "adapter": adapter,
            "scope": "Exact DP8 Wv2 field-agent continuation; no physical actuation or performance claim.",
            "checks": checks, "checks_passed": len(checks),
            "CPU": {"lifecycles": {key: value["cpu"] for key, value in captures.items()}},
            "fresh_process_recovery": fresh, "identity_scope": identities,
            "canonical_agent_archive_sha256": main["agent_archive_sha256"],
            "welip_archive_sha256": main["welip_archive_sha256"],
            "forbidden_cpu_producers": list(FORBIDDEN_TAPER_PRODUCERS) + ["solvefinite.welip.encode_state"]
                + list(legacy.FORBIDDEN_OG_PRODUCERS) + list(legacy.FORBIDDEN_CPU_COMPILERS),
            "elapsed_seconds": round(perf_counter() - started, 3)}
    if not cpu_only:
        report["GPU"] = {"lifecycles": {key: value["gpu"] for key, value in captures.items()}}
    return report


def main():
    if "--guarded-cli" in sys.argv:
        from solvefinite.__main__ import main as agent_main
        arguments = sys.argv[sys.argv.index("--guarded-cli") + 1:]
        guard = no_cpu_state_producers() if "gpu" in arguments else nullcontext()
        with guard:
            return agent_main(["agent", "welip", *arguments])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-only", action="store_true", help="Partial development evidence without GPU")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = demonstrate(args.cpu_only)
    if args.output is not None:
        write_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("format", "partial", "checks_passed",
                                                   "canonical_agent_archive_sha256", "welip_archive_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
