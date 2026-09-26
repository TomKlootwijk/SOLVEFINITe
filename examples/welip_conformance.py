"""Compare finite W1--W8 sessions with frozen arithmetic and actual GPU state.

Full capture requires hardware GPU execution. --cpu-only is explicitly partial.
Private archive reads below are evidence instrumentation, not public W methods.
"""

import argparse
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from examples.organogram_conformance import (
    FORBIDDEN_OG_PRODUCERS, no_cpu_compilers as no_og_cpu_compilers,
)
from examples.hadamard_conformance import FORBIDDEN_CPU_COMPILERS
from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import (
    FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, FieldAgentManifest,
)
from solvefinite.runtime import write_json
from solvefinite.welip import WelipConfig, PROTOCOL, validate_record
from solvefinite.welip_session import WelipSession, WelipProtocolError


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "docs/evidence/welip-v1/formal-reference.json"
REFERENCE_SHA = "0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210"
FORMAL_COMMIT = "74e00f4af54a341815c64e47f7f58334adda5709"
OG_ARCHIVE_SHA = "e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df"
LIFECYCLES = ("main_lifecycle", "mirrored_lifecycle", "capacity8_lifecycle")
POLICIES = {"field": FIELD_POLICY, "hadamard": HADAMARD_POLICY,
            "growth": GROWTH_POLICY, "organogram": ORGANOGRAM_POLICY}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8"))


def check(condition, label):
    if type(condition) is not bool or not condition:
        raise ValueError("WElip conformance failed: " + label)
    return True


def reference():
    raw = REFERENCE_PATH.read_bytes().replace(b"\r\n", b"\n")
    check(sha(raw) == REFERENCE_SHA, "frozen preimplementation reference hash")
    return json.loads(raw)


def no_cpu_state_producers():
    stack = ExitStack()
    stack.enter_context(no_og_cpu_compilers())
    stack.enter_context(patch("solvefinite.welip.encode_state",
        side_effect=AssertionError("GPU state carrier called CPU encode_state")))
    return stack


def request_for(context, operation, **extra):
    cursor = context["next"]
    check(cursor is not None, "next operation within finite budget")
    request = {"protocol": PROTOCOL, "op": operation, "producer": context["producer"],
               "producer_epoch": context["producer_epoch"]}
    request.update({key: cursor[key] for key in
                    ("seq", "clock_epoch", "tick16", "agent_cycle", "geometry_epoch")})
    if operation == "ADVANCE":
        request.update(position=cursor["position"], observations=dict.fromkeys(cursor["visible_paths"], 0))
    request.update(extra)
    return request


def read_archive(path):
    return json.loads(path.read_text(encoding="utf-8"))


def saved_identity(archive):
    return {"welip_archive_sha256": canonical_hash(archive),
            "agent_archive_sha256": canonical_hash(archive["agent"]),
            "operation_transcript_sha256": canonical_hash(archive["operations"])}


def lifecycle(directory, label, literal, backend):
    config = WelipConfig.from_dict(literal["config"])
    state = directory / (label + ".json")
    guard = no_cpu_state_producers() if backend == "gpu" else nullcontext()
    with guard, WelipSession(state, config, backend=backend,
                            index_binding=IndexBinding(23, -1, 139)) as session:
        check(session.ready() == literal["ready"], label + " initial public cursor")
        results, duplicates = [], []
        for index, row in enumerate(literal["operations"]):
            result = session.handle(row["request"])
            check(result == literal["results"][index], label + " complete response")
            saved = read_archive(state)
            check(saved["operations"] == literal["operations"][:index + 1], label + " complete durable prefix")
            for record in result["records"]:
                validate_record(record, config, expected_pair=int(row["agent_pair"], 16),
                                expected_energy=row["energy"])
            if backend == "gpu":
                executor = session._agent._gpu
                check(executor.snapshot() == (session._agent.agent_pair, session._agent.energy), label + " actual canonical owner")
                check(executor._ticks == literal["executor_action_tick_expectations"][index]["executor_action_ticks"],
                      label + " separate executor action clock")
            before = state.read_bytes(), session._agent.archive(), session._cache()
            with patch.object(session._agent, "emit_welip_state", side_effect=AssertionError("retry emission")), \
                    patch.object(session._agent, "step", side_effect=AssertionError("retry transition")):
                duplicate = session.handle(row["request"])
            check(duplicate == literal["latest_retry_receipts"][index], label + " latest-only retry")
            check((state.read_bytes(), session._agent.archive(), session._cache()) == before,
                  label + " retry preserves whole state and durable bytes")
            results.append(result)
            duplicates.append(duplicate)
        archive = read_archive(state)
        check(archive["expected"] == literal["expected"], label + " final clock and cache")
        check(canonical_hash(archive["operations"]) == literal["operation_transcript_sha256"], label + " frozen transcript digest")
        check(sum(len(row["records"]) for row in archive["operations"]) == 18, label + " 18 records")
        check(sum(record["fragment_count"] for row in archive["operations"] for record in row["records"]) == 37,
              label + " 37 words")
        execution = session._agent.execution_info
    return {"archive": archive, "results": results, "latest_retry_receipts": duplicates,
            "record_count": 18, "fragment_count": 37, "execution_info": execution,
            **saved_identity(archive)}


def policy_mission(directory, profile, backend):
    config = WelipConfig(manifest=FieldAgentManifest(policy=POLICIES[profile]),
                         producer="welip-policy-" + profile, clock_origin=65530, max_events=128,
                         initial_capacity=2)
    state = directory / (profile + "-" + backend + ".json")
    guard = no_cpu_state_producers() if backend == "gpu" else nullcontext()
    with guard, WelipSession(state, config, backend=backend) as session:
        response = session.handle(request_for(session.ready(), "IGNITE", payload=""))
        growths = 0
        while response["next"]["agent_status"] != "COMPLETE":
            check(response["next"]["agent_cycle"] < 40, profile + " finite mission completion")
            previous = response["next"]["geometry_epoch"]
            response = session.handle(request_for(response, "ADVANCE"))
            growths += int(response["next"]["geometry_epoch"] != previous)
            for record in response["records"]:
                validate_record(record, config, expected_pair=session._agent.agent_pair,
                                expected_energy=session._agent.energy)
        before = session._agent.archive(), session._cache()
        terminal = session.handle(request_for(response, "EMIT"))
        check((session._agent.archive(), session._cache()) == before, profile + " retained terminal emission")
        check(terminal["agent_status"] == "COMPLETE", profile + " terminal status")
        check(growths == int(profile in ("growth", "organogram")), profile + " unchanged growth policy")
        archive = read_archive(state)
        return {"archive": archive, "growth_count": growths, "terminal_response": terminal,
                "execution_info": session._agent.execution_info, **saved_identity(archive)}


def fresh_processes(directory, literal, expected_archive, *, cpu_only=False):
    """The actual JSONL CLI, guarded in separate Python processes before import."""
    config_path, state = directory / "config.json", directory / "session.json"
    write_json(config_path, literal["config"])
    backends = ("cpu", "cpu", "cpu") if cpu_only else ("gpu", "cpu", "gpu")
    segments = ((0, 5, ("--index-epoch", "7", "--index-sign", "-1")),
                (5, 10, ("--index-epoch", "12", "--index-phase-origin", "192")),
                (10, 17, ("--index-epoch", "20", "--index-sign", "-1", "--index-phase-origin", "41")))
    captures = []
    previous = []
    for number, ((start, stop, options), backend) in enumerate(zip(segments, backends)):
        requests, expected = [], []
        if start:
            requests.append(literal["operations"][start - 1]["request"])
            expected.append(literal["latest_retry_receipts"][start - 1])
        for index in range(start, stop):
            requests.append(literal["operations"][index]["request"])
            expected.append(literal["results"][index])
        requests.append(literal["operations"][stop - 1]["request"])
        expected.append(literal["latest_retry_receipts"][stop - 1])
        command = [sys.executable, "-m", "examples.welip_conformance", "--guarded-cli",
                   "--state", str(state), "--backend", backend, *options]
        if number == 0:
            command.extend(["--config", str(config_path)])
        process = subprocess.run(command, cwd=ROOT, input="".join(json.dumps(request) + "\n" for request in requests),
                                 text=True, encoding="utf-8", capture_output=True, timeout=180,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            raise RuntimeError(f"Fresh W endpoint failed: {command}\n{process.stdout}\n{process.stderr}")
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        check(len(responses) == len(expected) + 1, "fresh process exact output line count")
        check(responses[1:] == expected, "fresh process complete response equality")
        if start == 0:
            ready = literal["ready"]
        else:
            prior = literal["results"][start - 1]
            ready = {key: prior[key] for key in ("protocol", "producer", "producer_epoch", "head", "next")}
            ready.update(type="READY", restored=True)
        check(responses[0] == ready, "fresh process current READY without historical output")
        archive = read_archive(state)
        check(archive["operations"] == literal["operations"][:stop], "fresh process full private replay")
        check(archive["operations"][:start] == previous, "fresh process unchanged original ledger prefix")
        previous = deepcopy(archive["operations"])
        captures.append({"backend": backend, "index_arguments": list(options), "command": command,
                         "requests": requests, "responses": responses, "stderr": process.stderr,
                         "saved_bytes_sha256": sha(state.read_bytes()), **saved_identity(archive)})
    check(read_archive(state) == expected_archive, "cross-backend/index recovery preserves exact final archive")
    return {"captures": captures, "final_archive_sha256": canonical_hash(expected_archive),
            "scope": "Fresh JSONL processes; private full replay occurs before the single READY response."}


def _reject(session, request, code, fatal):
    try:
        session.handle(request)
    except WelipProtocolError as exc:
        check((exc.code, exc.fatal) == (code, fatal), "fault classification")
        return session.error(exc)
    raise ValueError("Expected W fault was admitted")


def _damaged_emitter(owner):
    emit, reader = owner.emit_welip_state, owner._gpu._read_outputs
    def read(count):
        row = list(reader(count)[0]); row[7] = 1
        return (tuple(row),)
    def damaged(tick):
        with patch.object(owner._gpu, "_read_outputs", side_effect=read):
            return emit(tick)
    return patch.object(owner, "emit_welip_state", side_effect=damaged)


def session_faults(directory, literal):
    """Fault the real emitter across the W transaction boundary, then recover."""
    config = WelipConfig.from_dict(literal["config"])
    reports = {}
    for label in ("complete_output_before_mutation", "complete_output_after_advance",
                  "uncertain_dispatch", "save_replaced_before_error"):
        state = directory / (label + ".json")
        with no_cpu_state_producers(), WelipSession(state, config, backend="gpu") as session:
            ignition = session.handle(literal["operations"][0]["request"])
            request = (literal["operations"][1]["request"] if label in
                       ("complete_output_after_advance", "save_replaced_before_error")
                       else request_for(ignition, "EMIT"))
            before = state.read_bytes(), session._agent.archive(), session._cache()
            if label.startswith("complete_output"):
                fault = _damaged_emitter(session._agent)
                pure = label == "complete_output_before_mutation"
                with fault:
                    error = _reject(session, request, "MALFORMED_EMISSION" if pure else "OWNER_FAILED", not pure)
                check(state.read_bytes() == before[0], label + " preserves durable prefix")
                if pure:
                    check((session._agent.archive(), session._cache()) == before[1:], label + " whole prestate unchanged")
                    admitted = session.handle(request)
                    check(admitted["type"] == "RESULT", label + " same live owner retry succeeds")
                else:
                    check(session._agent.closed, label + " mutated owner poisoned")
            elif label == "uncertain_dispatch":
                with patch.object(session._agent._gpu, "_dispatch", side_effect=RuntimeError("injected dispatch uncertainty")):
                    error = _reject(session, request, "OWNER_FAILED", True)
                check(session._agent.closed and state.read_bytes() == before[0], label + " close and preserve durable prefix")
            else:
                def replaced(path, value):
                    write_json(path, value)
                    raise OSError("injected error after atomic replacement")
                with patch("solvefinite.welip_session.write_json", side_effect=replaced):
                    error = _reject(session, request, "STORAGE_FAILED", True)
                check(session._agent.closed, label + " uncertain save closes owner")
                check(len(read_archive(state)["operations"]) == 2, label + " replacement exists despite missing acknowledgement")
        durable = state.read_bytes()
        with no_cpu_state_producers(), WelipSession(state, backend="gpu", index_binding=IndexBinding(31, -1, 47)) as restored:
            expected_duplicate = label in ("complete_output_before_mutation", "save_replaced_before_error")
            if expected_duplicate:
                with patch.object(restored._agent, "emit_welip_state", side_effect=AssertionError("recovery retry emitted")):
                    response = restored.handle(request)
                check(response["type"] == "DUPLICATE" and state.read_bytes() == durable, label + " durable latest identity")
            else:
                check(restored.ready()["head"]["seq"] == 1, label + " durable rollback reconstructed")
                response = restored.handle(request)
                check(response["type"] == "RESULT", label + " forward retry admitted once")
            reports[label] = {"error": error, "recovered_response": response,
                              "durable_prefix_sha256": sha(durable), **saved_identity(read_archive(state))}
    return reports


def demonstrate(cpu_only=False):
    started = perf_counter()
    frozen = reference()
    report = {"format": "welip-conformance-v1", "formal_binding": "TK-LPLUT-2.0 revision11 W1-W8",
              "formal_commit": FORMAL_COMMIT, "formal_reference_sha256_lf": REFERENCE_SHA,
              "actual_GPU_capture": False, "partial": bool(cpu_only), "checks": {}}
    with TemporaryDirectory(prefix="solvefinite-welip-") as temporary:
        directory = Path(temporary)
        for backend in (("cpu",) if cpu_only else ("cpu", "gpu")):
            cases = {key: lifecycle(directory, backend + "-" + key, frozen[key], backend) for key in LIFECYCLES}
            policies = {profile: policy_mission(directory, profile, backend) for profile in POLICIES}
            report[backend.upper()] = {"lifecycles": cases, "policies": policies}
            report["checks"][backend.upper() + "_three_complete_frozen_lifecycles"] = True
            report["checks"][backend.upper() + "_all_four_field_policies_terminal_emission"] = True
            report["checks"][backend.upper() + "_latest_retry_is_pure_after_every_operation"] = True
        cpu = report["CPU"]["lifecycles"]["main_lifecycle"]
        check(cpu["agent_archive_sha256"] == OG_ARCHIVE_SHA, "old OG canonical agent archive preserved")
        report["canonical_agent_archive_sha256"] = OG_ARCHIVE_SHA
        report["welip_archive_sha256"] = cpu["welip_archive_sha256"]
        report["checks"]["original_OG_archive_identity_preserved"] = True
        fresh_dir = directory / "fresh"
        fresh_dir.mkdir()
        report["fresh_process_recovery"] = fresh_processes(fresh_dir, frozen["main_lifecycle"], cpu["archive"], cpu_only=cpu_only)
        report["checks"]["three_fresh_CLI_processes_recover_original_ledger_and_index_independent_state"] = True
        if not cpu_only:
            for category in ("lifecycles", "policies"):
                for key, value in report["CPU"][category].items():
                    check(value["archive"] == report["GPU"][category][key]["archive"], "complete CPU/GPU archive " + key)
            report["session_faults"] = session_faults(directory, frozen["main_lifecycle"])
            adapter = report["GPU"]["lifecycles"]["main_lifecycle"]["execution_info"]["adapter"]
            check(adapter["adapter_type"] in ("DiscreteGPU", "IntegratedGPU"), "hardware adapter required")
            report.update(actual_GPU_capture=True, adapter=adapter,
                          disabled_legacy_CPU_compilers=list(FORBIDDEN_CPU_COMPILERS),
                          disabled_OG_CPU_producers=list(FORBIDDEN_OG_PRODUCERS),
                          disabled_state_producer="solvefinite.welip.encode_state")
            report["checks"].update({name: True for name in (
                "full_CPU_GPU_W_and_agent_archive_equality", "actual_GPU_words_without_CPU_state_producer",
                "GPU_CPU_GPU_fresh_private_recovery_with_changed_indexes", "GPU_complete_output_whole_operation_atomicity",
                "GPU_dispatch_uncertainty_closes_and_recovers", "uncertain_save_replacement_resolves_to_latest_duplicate")})
    check(all(value is True for value in report["checks"].values()), "every declared check")
    report.update(elapsed_seconds=round(perf_counter() - started, 3),
                  scope="Finite source-bound clock/carrier and same-owner W session correctness. "
                        "No global universality, texture-cache saturation, throughput or physical-energy claim.")
    return report


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--guarded-cli":
        arguments = sys.argv[2:]
        backend = arguments[arguments.index("--backend") + 1]
        sys.argv = ["solvefinite", "agent", "welip", *arguments]
        with no_cpu_state_producers() if backend == "gpu" else nullcontext():
            runpy.run_module("solvefinite", run_name="__main__")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/welip/conformance.json")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    report = demonstrate(args.cpu_only)
    write_json(args.output, report)
    print(json.dumps({"output": str(Path(args.output).resolve()), "checks_passed": len(report["checks"]),
                      "actual_GPU_capture": report["actual_GPU_capture"], "partial": report["partial"],
                      "canonical_agent_archive_sha256": report["canonical_agent_archive_sha256"],
                      "welip_archive_sha256": report["welip_archive_sha256"],
                      "elapsed_seconds": report["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
