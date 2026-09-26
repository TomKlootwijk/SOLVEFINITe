"""Reproduce GD1-GD8's finite autonomous growth on CPU and an actual GPU.

Run: python -m examples.growth_conformance --output output/growth-conformance.json
Device absence is a failed capture, never a skipped test or CPU substitution.
The optional --cpu-only mode produces an explicitly partial development report.
"""

import argparse
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from examples.hadamard_conformance import FORBIDDEN_CPU_COMPILERS
from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import FIELD_POLICY, GROWTH_POLICY, HADAMARD_POLICY, FieldAgentManifest
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.growth import GrowthBinding
from solvefinite.runtime import write_json
from solvefinite.session import Scenario
from solvefinite.tomigidt import Tomigidt


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "docs/evidence/growth-v1/formal-reference.json"
INITIAL_FORMAL_COMMIT = "ec1181e00f40c3663e73974885573ebfae784e08"
FORMAL_COMMIT = "00b0e64decd2d8202725b71c101480843b1af1e2"
MAX_CYCLES = 1024


def check(condition, label):
    """Never record a truthy integer, collection or skipped result as a check."""
    if type(condition) is not bool or not condition:
        raise ValueError(f"Growth conformance failed: {label}")
    return True


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def no_cpu_compilers():
    stack = ExitStack()
    for name in FORBIDDEN_CPU_COMPILERS:
        stack.enter_context(patch(name, side_effect=AssertionError(f"Forbidden CPU fallback: {name}")))
    # The owner currently imports evaluate_field locally from the patched
    # field module. Also forbid a retained module alias if a revision adds it.
    import solvefinite.tomigidt as owner
    if hasattr(owner, "evaluate_field"):
        stack.enter_context(patch.object(owner, "evaluate_field",
                                        side_effect=AssertionError("Forbidden CPU owner field alias")))
    return stack


def scenario_for(reference):
    world = reference["initial_recipe"]
    recipe = KleinFieldRecipe(**{**world, "turns": tuple(world["turns"])})
    manifest = FieldAgentManifest(
        policy=GROWTH_POLICY, world=recipe,
        target=f"k:{reference['initial_target'] // recipe.height}:{reference['initial_target'] % recipe.height}",
        initial_phase=reference["initial"]["phase"],
        initial_orientation=reference["initial"]["orientation"],
        initial_energy=reference["initial"]["energy"],
        growth=GrowthBinding.from_dict(reference["growth"]),
        repair_cost=reference["repair_cost"],
    )
    changes = ((2, "k:0:3", 70),) if reference["hazard_rule"].startswith("Node 3") else ()
    return Scenario(manifest, changes=changes)


def fifo(world):
    return {"capacity": world.capacity, "active": list(world.active_paths),
            "evicted": list(world.evicted_paths), "hits": world.hit_count,
            "regenerations": world.regeneration_count}


def reindex(agent):
    before, resident, planning = agent.archive(), fifo(agent.world), agent._planning
    model, binding = agent.world.routing_model, agent.world.index.binding
    device = agent._gpu.snapshot() if agent._gpu is not None else None
    agent.reindex(psi_sign=-binding.psi_sign, phase_origin=(binding.phase_origin + 37) % 256)
    checks = {
        "canonical_archive_preserved": before == agent.archive(),
        "FIFO_preserved": resident == fifo(agent.world),
        "planning_object_preserved": planning is agent._planning,
        "routing_model_object_preserved": model is agent.world.routing_model,
        "epoch_and_target_preserved": before["expected"]["geometry_epoch"] == agent.geometry_epoch
                                      and before["expected"]["target"] == agent.target,
        "index_version_advanced": agent.world.index.binding.epoch == binding.epoch + 1,
        "persistent_device_preserved": device == (agent._gpu.snapshot() if agent._gpu is not None else None),
    }
    check(all(type(value) is bool and value for value in checks.values()), "reindex transaction")
    return {"cycle": agent.cycle, "geometry_epoch": agent.geometry_epoch,
            "search_pending": planning is not None, "checks": checks}


def independent_data_pair(node, value):
    def word(metadata):
        result = (node << 8) | ((value & 255) << 16) | (metadata << 24)
        return result | ((result.bit_count() & 1) << 31)
    return f"{word(16):08X}{word(0):08X}"


def historical_samples(agent, reference):
    before, resident, planning = agent.archive(), fifo(agent.world), agent._planning
    device = agent._gpu.snapshot() if agent._gpu is not None else None
    samples = []
    for world in reference["worlds"]:
        epoch, recipe, fields = world["geometry_epoch"], world["recipe"], world["field"]
        origin = 0 if epoch == 0 else next(event["cycle"] for event in reference["events"]
                                          if event["kind"] == "GROW" and event["geometry_epoch"] == epoch)
        for node in sorted({0, world["target"], len(fields) - 1}):
            path = f"k:{node // recipe['height']}:{node % recipe['height']}"
            sample = agent.derive_epoch(epoch, path)
            check(sample.geometry_epoch == epoch and sample.origin_sequence == origin,
                  "historical generation and original sequence")
            check(f"{sample.pair:016X}" == independent_data_pair(node, fields[node]),
                  "historical exact DATA field pair")
            check(sample.initial_recipe == agent.manifest.world and sample.growth == agent.manifest.growth,
                  "historical retained baseline and grammar")
            check(sample.prefix_sha256 == canonical_hash(before["events"][:origin]),
                  "historical identity binds the complete original admitted event prefix")
            samples.append(sample.to_dict())
    checks = {"archive_preserved": agent.archive() == before, "FIFO_preserved": fifo(agent.world) == resident,
              "planning_preserved": agent._planning is planning,
              "device_preserved": device == (agent._gpu.snapshot() if agent._gpu is not None else None)}
    check(all(type(value) is bool and value for value in checks.values()), "historical derivation isolation")
    return {"samples": samples, "checks": checks}


def literal(result, reference):
    snapshots, events = result["snapshots"], result["archive"]["events"]
    check(snapshots[0]["agent_pair"] == reference["initial"]["pair"], "literal initial pair")
    check(len(events) == len(reference["events"]), "literal number of admitted events")
    for event, expected, state in zip(events, reference["events"], snapshots[1:]):
        decision = event["decision"]
        check((decision["kind"], decision["cost"], event["output"], event["energy"])
              == (expected["kind"], expected["cost"], expected["state"]["pair"], expected["state"]["energy"]),
              "literal decision, pair and energy")
        check(event["geometry_epoch"] == expected["input_geometry_epoch"], "pre-event epoch context")
        check(state["geometry_epoch"] == expected["geometry_epoch"]
              and state["scale_exponent"] == expected["geometry_epoch"], "literal generated epoch and scale")
        check(decision["route"] == expected.get("paths", []), "literal planned route")
        expected_status = "ACTIVE" if expected["status"] == "RUNNING" else expected["status"]
        check(state["status"] == expected_status, "literal lifecycle status")
        if expected["kind"] == "MOVE":
            check(decision["expansions"] == expected["expansions"]
                  and decision["forecast"] == expected["forecast"], "literal lifted search and forecast")
        if expected["kind"] == "GROW":
            receipt = event["growth"]
            check(receipt["mapped_node"] == expected["state"]["path"]
                  and receipt["target"] == expected["selection"]["target_path"], "literal mapped node and derived target")
            fields = {key: receipt["recipe"][key] for key in ("width", "height", "center", "radius", "turns")}
            check(fields == expected["next_recipe"], "literal produced recipe")
        else:
            check(event["growth"] is None, "nongrowth event has no growth receipt")
    return True


def mission(scenario, backend, *, reference=None, rebuild=False, capacity=1, binding=None):
    agent = Tomigidt(scenario.manifest, capacity, backend=backend, index_binding=binding)
    guards = ExitStack()
    try:
        if agent._gpu is not None:
            # The initial seed is allowed. Every subsequent geometry mapping
            # must execute the growth shader rather than seeding a host pair.
            guards.enter_context(patch("solvefinite.field_agent_gpu.GpuFieldAgentExecutor.seed",
                                       side_effect=AssertionError("Host seeding after initial GPU construction")))
        snapshots, device_states, rebuilds, transitions, checkpoints = [], [], [], [], {}
        while True:
            snapshot = agent.snapshot()
            snapshots.append(snapshot)
            if agent._gpu is not None:
                pair_value, energy = agent._gpu.snapshot()
                check((f"{pair_value:016X}", energy) == (snapshot["agent_pair"], snapshot["energy"]),
                      "actual persistent device state every cycle")
                device_states.append({"cycle": agent.cycle, "geometry_epoch": agent.geometry_epoch,
                                      "pair": f"{pair_value:016X}", "energy": energy})
            if agent.status == "GROWTH_PENDING":
                checkpoints[f"before_growth_{agent.geometry_epoch + 1}"] = agent.archive()
            if agent._planning is not None and agent.geometry_epoch > 0:
                checkpoints.setdefault("DEFER_after_growth", agent.archive())
            if agent.status == "COMPLETE":
                break
            check(agent.cycle < MAX_CYCLES, "bounded growth mission")
            if rebuild:
                rebuilds.append(reindex(agent))
            old_epoch, old_recipe = agent.geometry_epoch, agent.current_recipe
            old_info = agent.execution_info
            decision = agent.step(scenario.observe(agent.position, agent.cycle + 1,
                                                   geometry_epoch=agent.geometry_epoch))
            if decision.kind == "GROW":
                check(agent.geometry_epoch == old_epoch + 1, "one epoch per GROW")
                check(not agent.world.active_paths and not agent.snapshot()["observations"]
                      and agent._planning is None, "new epoch clears FIFO, observations and retained search")
                check(agent.current_recipe.width == 2 * old_recipe.width
                      and agent.current_recipe.height == 2 * old_recipe.height, "actual world dimensions grow")
                info = agent.execution_info
                peak = info["growth"]["peak_preparation_payload"]
                old_n = old_recipe.width * old_recipe.height
                new_n = agent.current_recipe.width * agent.current_recipe.height
                check(peak["host_index_bytes"] >= 64 * (old_n + new_n) + 32
                      and peak["host_routing_table_bytes"] >= 68 * (old_n + new_n),
                      "complete old and candidate host routing/index payload")
                if agent._gpu is not None:
                    for key in ("device_buffer_bytes", "device_texture_bytes", "device_payload_bytes",
                                "host_field_code_payload_bytes", "host_geometry_payload_bytes"):
                        check(peak[key] >= old_info["allocation_info"][key] + info["allocation_info"][key],
                              f"complete old and candidate {key}")
                transitions.append({"cycle": agent.cycle, "from_epoch": old_epoch,
                                    "to_epoch": agent.geometry_epoch, "receipt": agent.archive()["events"][-1]["growth"],
                                    "old_execution_info": old_info, "new_execution_info": info})
                checkpoints[f"after_growth_{agent.geometry_epoch}"] = agent.archive()
        history = historical_samples(agent, reference) if reference is not None else None
        result = {"archive": agent.archive(), "archive_sha256": canonical_hash(agent.archive()),
                  "snapshots": snapshots, "actual_device_states": device_states,
                  "rebuilds": rebuilds, "growth_transitions": transitions,
                  "historical_samples": history, "execution_info": agent.execution_info,
                  "FIFO": fifo(agent.world), "checkpoints": checkpoints}
        if reference is not None:
            literal(result, reference)
        return result
    finally:
        guards.close()
        agent.close()


def cpu_conformance(reference):
    cases = {}
    for label in ("default", "mirrored_default", "two_epoch", "zero_epoch"):
        expected = reference[label + "_mission"]
        scenario = scenario_for(expected)
        cases[label] = mission(scenario, "cpu", reference=expected)
    scenario = scenario_for(reference["default_mission"])
    rebuilt = mission(scenario, "cpu", rebuild=True, capacity=32, binding=IndexBinding(11, -1, 201))
    check(rebuilt["archive"] == cases["default"]["archive"], "CPU capacity/index transparency")
    deferred_scenario = replace(scenario, manifest=replace(scenario.manifest, max_search_expansions=7))
    deferred = mission(deferred_scenario, "cpu", rebuild=True)
    control = mission(deferred_scenario, "cpu", capacity=32)
    check(deferred["archive"] == control["archive"] and "DEFER_after_growth" in deferred["checkpoints"]
          and any(row["search_pending"] for row in deferred["rebuilds"]), "CPU retained search across reindexes")
    retained = json.loads((ROOT / "docs/evidence/hadamard-v1/verification.json").read_text(encoding="utf-8"))
    legacy = {}
    for policy, name, expected_hash in (
            (FIELD_POLICY, "field", retained["legacy_field_archive_sha256"]),
            (HADAMARD_POLICY, "hadamard", retained["canonical_archive_sha256"])):
        old_scenario = Scenario(FieldAgentManifest(policy=policy), changes=((2, "k:0:3", 70),))
        result = mission(old_scenario, "cpu")
        check(result["archive_sha256"] == expected_hash, f"historical {name} archive preserved")
        legacy[name] = result
    return {"cases": cases, "rebuilt": rebuilt, "deferred": deferred,
            "deferred_scenario": deferred_scenario.to_dict(), "legacy": legacy}


def fresh_replay(folder, label, scenario, archive, backend):
    path = folder / f"{label}.json"
    write_json(path, {"scenario": scenario.to_dict(), "agent": archive})
    script = """
from contextlib import nullcontext
import json,sys
from examples.growth_conformance import no_cpu_compilers,canonical_hash
from solvefinite.f8 import IndexBinding
from solvefinite.session import Scenario
from solvefinite.tomigidt import Tomigidt
with open(sys.argv[1],encoding='utf-8') as source: value=json.load(source)
scenario=Scenario.from_dict(value['scenario'])
with no_cpu_compilers() if sys.argv[2]=='gpu' else nullcontext():
    agent=Tomigidt.from_archive(value['agent'],capacity=7,backend=sys.argv[2],
                               index_binding=IndexBinding(71,-1,217))
    try:
        while agent.status!='COMPLETE':
            if agent.cycle>=1024: raise ValueError('Bounded fresh continuation exceeded')
            agent.step(scenario.observe(agent.position,agent.cycle+1,geometry_epoch=agent.geometry_epoch))
        result={'archive':agent.archive(),'execution_info':agent.execution_info,
                'archive_sha256':canonical_hash(agent.archive()),'CPU_compilers_disabled':sys.argv[2]=='gpu'}
        if agent._gpu is not None:
            pair_value,energy=agent._gpu.snapshot()
            if (pair_value,energy)!=(agent.agent_pair,agent.energy): raise ValueError('Device continuation mismatch')
    finally: agent.close()
print(json.dumps(result))
"""
    process = subprocess.run([sys.executable, "-c", script, str(path), backend], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(f"Fresh {label} failed: {process.stderr}")
    return json.loads(process.stdout)


def demonstrate(cpu_only=False):
    started = perf_counter()
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    cpu = cpu_conformance(reference)
    checks = {
        "CPU_four_literal_missions": True,
        "CPU_capacity_and_storage_index_transparency": True,
        "CPU_DEFER_search_retained_across_storage_rebuilds": True,
        "CPU_geometry_changes_and_postgrowth_continuation": True,
        "CPU_original_epoch_samples_match_independent_fields": True,
        "legacy_field_and_Hadamard_canonical_hashes_preserved": True,
    }
    report = {"format": "growth-conformance-v1", "formal_binding": "TK-LPLUT-2.0 revision7 GD1-GD8",
              "formal_commit": FORMAL_COMMIT, "initial_formal_commit": INITIAL_FORMAL_COMMIT,
              "CPU": cpu, "checks": checks,
              "mission_cycle_bound": MAX_CYCLES, "actual_GPU_capture": False,
              "formal_reference_sha256_lf": hashlib.sha256(REFERENCE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
    if not cpu_only:
        gpu = {}
        with no_cpu_compilers():
            for label in ("default", "mirrored_default", "two_epoch", "zero_epoch"):
                expected = reference[label + "_mission"]
                gpu[label] = mission(scenario_for(expected), "gpu", reference=expected, rebuild=True,
                                     capacity=5, binding=IndexBinding(23, -1, 139))
                check(gpu[label]["archive"] == cpu["cases"][label]["archive"], f"complete GPU/CPU {label} history")
            deferred_scenario = Scenario.from_dict(cpu["deferred_scenario"])
            deferred = mission(deferred_scenario, "gpu", rebuild=True, capacity=3)
            check(deferred["archive"] == cpu["deferred"]["archive"], "GPU/CPU deferred history")
            legacy_gpu = {}
            for name, policy in (("field", FIELD_POLICY), ("hadamard", HADAMARD_POLICY)):
                old_scenario = Scenario(FieldAgentManifest(policy=policy), changes=((2, "k:0:3", 70),))
                legacy_gpu[name] = mission(old_scenario, "gpu")
                check(legacy_gpu[name]["archive"] == cpu["legacy"][name]["archive"],
                      f"legacy GPU {name} complete history")
        replays = {}
        with TemporaryDirectory(prefix="solvefinite-growth-") as temporary:
            folder = Path(temporary)
            scenario = scenario_for(reference["default_mission"])
            for cut in ("before_growth_1", "after_growth_1"):
                for source, backend in ((cpu["cases"]["default"], "gpu"), (gpu["default"], "cpu")):
                    label = f"{cut}_to_{backend}"
                    value = fresh_replay(folder, label, scenario, source["checkpoints"][cut], backend)
                    check(value["archive"] == cpu["cases"]["default"]["archive"], f"fresh {label} complete history")
                    replays[label] = value
            for source, backend in ((cpu["deferred"], "gpu"), (deferred, "cpu")):
                label = f"DEFER_after_growth_to_{backend}"
                value = fresh_replay(folder, label, deferred_scenario,
                                     source["checkpoints"]["DEFER_after_growth"], backend)
                check(value["archive"] == cpu["deferred"]["archive"], f"fresh {label} retained search")
                replays[label] = value
        checks.update({
            "GPU_four_literal_missions_match_CPU": True,
            "GPU_persistent_device_pair_and_energy_every_cycle": True,
            "GPU_generated_fields_and_mapping_have_no_CPU_compiler_fallback": True,
            "GPU_growth_forbids_host_seed_after_initial_construction": True,
            "GPU_original_epoch_samples_without_CPU_compiler_fallback": True,
            "GPU_capacity_and_index_transparency_in_every_geometry": True,
            "GPU_DEFER_search_survives_reindex_in_generated_geometry": True,
            "complete_old_and_candidate_growth_payload_accounted": True,
            "fresh_process_replay_before_after_GROW_and_generated_DEFER": True,
            "legacy_GPU_field_and_Hadamard_histories_preserved": True,
        })
        report.update(GPU=gpu, GPU_deferred=deferred, GPU_legacy=legacy_gpu, fresh_process_replays=replays,
                      actual_GPU_capture=True, disabled_CPU_compilers=list(FORBIDDEN_CPU_COMPILERS),
                      owner_CPU_evaluator_alias_guard=True)
    check(all(type(value) is bool and value for value in checks.values()), "all strict Boolean checks")
    report.update(canonical_archive_sha256=cpu["cases"]["default"]["archive_sha256"],
                  legacy_archive_sha256={name: value["archive_sha256"] for name, value in cpu["legacy"].items()},
                  elapsed_seconds=round(perf_counter() - started, 3),
                  scope="Finite internally triggered dyadic geometry growth, regenerated field and target, "
                        "and continuation within one Tomigidt history. Logical payload accounting is separate "
                        "from Python/driver overhead. No indefinite growth, physical calibration or comparative "
                        "performance claim. Atomic failure and live durability cases are covered by the separately retained test capture.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/growth-conformance.json")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    report = demonstrate(args.cpu_only)
    write_json(args.output, report)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "checks_passed": len(report["checks"]), "actual_GPU_capture": report["actual_GPU_capture"],
                      "default_cycles": report["CPU"]["cases"]["default"]["archive"]["expected"]["cycle"],
                      "two_epoch_cycles": report["CPU"]["cases"]["two_epoch"]["archive"]["expected"]["cycle"],
                      "DEFER_cycles": report["CPU"]["deferred"]["archive"]["expected"]["cycle"],
                      "canonical_archive_sha256": report["canonical_archive_sha256"],
                      "elapsed_seconds": report["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
