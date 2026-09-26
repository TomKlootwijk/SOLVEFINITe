"""Reproduce HP1-HP8 with the existing Tomigidt and an actual hardware GPU.

Run: python -m examples.hadamard_conformance
All missions are bounded by 64 admitted cycles. Device absence is an error,
not a skipped check or permission to substitute the CPU compiler.
"""

import argparse
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from math import gcd
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from examples.psi_f8_conformance import _independent_geometry
from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import HADAMARD_POLICY, FieldAgentManifest
from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.hadamard import HadamardBinding, RoutingModel
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL, load_live
from solvefinite.runtime import write_json
from solvefinite.session import SESSION_FORMAT, Scenario
from solvefinite.tomigidt import Tomigidt


ROOT = Path(__file__).resolve().parents[1]
FORMAL_REFERENCE = ROOT / "docs/evidence/hadamard-v1/formal-reference.json"
MAX_CYCLES = 64
FORBIDDEN_CPU_COMPILERS = (
    "solvefinite.f8.F8Index.build", "solvefinite.f8._compile_records",
    "solvefinite.f8._compile_rows", "solvefinite.f8.evaluate_field",
    "solvefinite.field.evaluate_field", "solvefinite.field_world.evaluate_field",
    "solvefinite.psi.field_axes", "solvefinite.psi.axis_from_gradient",
    "solvefinite.hadamard.RoutingModel.build", "solvefinite.hadamard._compile_model",
    "solvefinite.hadamard.evaluate_field",
)


def _check(condition, label):
    if not condition:
        raise ValueError(f"Hadamard conformance failed: {label}")
    return True


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def no_cpu_compilers():
    """Leave independent admission certificates enabled, forbid construction."""
    stack = ExitStack()
    for name in FORBIDDEN_CPU_COMPILERS:
        stack.enter_context(patch(name, side_effect=AssertionError(f"Forbidden CPU fallback: {name}")))
    return stack


def _fifo(world):
    return {"capacity": world.capacity, "active": list(world.active_paths),
            "evicted": list(world.evicted_paths), "hits": world.hit_count,
            "regenerations": world.regeneration_count}


def _rebuild(agent):
    before, fifo, search = agent.archive(), _fifo(agent.world), agent._planning
    old_index, model = agent.world.index, agent.world.routing_model
    device = None if agent._gpu is None else agent._gpu.snapshot()
    agent.reindex(psi_sign=-old_index.binding.psi_sign,
                  phase_origin=(old_index.binding.phase_origin + 37) % 256)
    checks = {
        "archive_unchanged": before == agent.archive(),
        "FIFO_and_counters_unchanged": fifo == _fifo(agent.world),
        "same_retained_search_object": search is agent._planning,
        "same_certified_semantic_model_object": model is agent.world.routing_model,
        "index_version_advanced_once": agent.world.index.binding.epoch == old_index.binding.epoch + 1,
        "keys_changed": agent.world.index.records != old_index.records,
        "actual_device_unchanged": device == (None if agent._gpu is None else agent._gpu.snapshot()),
    }
    _check(all(checks.values()), "atomic index/model rebuild")
    return {"cycle": agent.cycle, "search_pending": search is not None,
            "before": old_index.binding.to_dict(), "after": agent.world.index.binding.to_dict(),
            "checks": checks, "FIFO": fifo}


def _mission(scenario, backend, *, rebuild=False, capacity=1, binding=None):
    agent = Tomigidt(scenario.manifest, capacity=capacity, backend=backend, index_binding=binding)
    try:
        snapshots, device, rebuilds, checkpoints = [], [], [], {}
        while True:
            state = agent.snapshot()
            snapshots.append(state)
            if agent._gpu is not None:
                actual_pair, actual_energy = agent._gpu.snapshot()
                _check((f"{actual_pair:016X}", actual_energy) == (state["agent_pair"], state["energy"]),
                       "persistent device pair/energy after every admitted event")
                device.append({"cycle": agent.cycle, "pair": f"{actual_pair:016X}", "energy": actual_energy})
            if agent.cycle in (1, 2):
                checkpoints[agent.cycle] = agent.archive()
            if agent.status == "COMPLETE":
                break
            _check(agent.cycle < MAX_CYCLES, "bounded mission")
            if rebuild:
                rebuilds.append(_rebuild(agent))
            agent.step(scenario.observe(agent.position, agent.cycle + 1))
        return {"archive": agent.archive(), "snapshots": snapshots, "device_states": device,
                "rebuilds": rebuilds, "execution_info": agent.execution_info,
                "FIFO": _fifo(agent.world), "archive_sha256": _sha(agent.archive())}, checkpoints
    finally:
        agent.close()


def _literal(result, reference):
    _check(result["snapshots"][0]["agent_pair"] == reference["initial"]["pair"], "literal initial pair")
    events = result["archive"]["events"]
    _check(len(events) == len(reference["events"]), "literal event count")
    for actual, expected in zip(events, reference["events"]):
        decision = actual["decision"]
        _check((decision["kind"], decision["cost"], actual["output"], actual["energy"])
               == (expected["kind"], expected["cost"], expected["pair"], expected["energy"]),
               "literal decision, pair and energy")
        _check(decision["route"] == expected.get("paths", []), "literal geometric route")
        if expected["kind"] == "MOVE":
            _check(decision["expansions"] == expected["expansions"]
                   and decision["forecast"] == expected["forecast"], "literal expansions and complete forecast")
    return True


def _oracle_table(recipe, binding):
    """Independent quotient/BFS fields and direct lane arithmetic, no model."""
    directions, _, _, fields = _independent_geometry(recipe)
    vectors = ((1, 0), (-1, 0), (0, 1), (0, -1))
    penalties, increments = [], []
    for source, (up, um, vp, vm) in enumerate(directions):
        gu, gv = fields[up] - fields[um], fields[vp] - fields[vm]
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        neighbors = sorted(zip(directions[source], vectors))
        for au, av in binding.gains:
            qu, qv = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
            maximum = max(abs(qu), abs(qv))
            penalties.extend(maximum - qu * eu - qv * ev for _, (eu, ev) in neighbors)
        increments.append(recipe.turns[0 if fields[source] < 0 else 1 if fields[source] == 0 else 2])
    return tuple(penalties), tuple(increments), fields


def _domain_cases():
    return (
        (KleinFieldRecipe(), HadamardBinding()),
        (KleinFieldRecipe(3, 3, 8, 1), HadamardBinding(gains=((0, 0),) * 4)),
        (KleinFieldRecipe(5, 7, 11, 3), HadamardBinding(gains=((4, -4), (-4, 4), (3, -2), (0, 1)))),
        (KleinFieldRecipe(3, 85, 127, 31), HadamardBinding()),
        (KleinFieldRecipe(85, 3, 254, 20), HadamardBinding(gains=((-4, -4),) * 4)),
        (KleinFieldRecipe(16, 16, 255, 8), HadamardBinding()),
    )


def cpu_conformance():
    reference = json.loads(FORMAL_REFERENCE.read_text(encoding="utf-8"))
    scenario = Scenario(FieldAgentManifest(policy=HADAMARD_POLICY), changes=((2, "k:0:3", 70),))
    baseline, checkpoints = _mission(scenario, "cpu")
    rebuilt, _ = _mission(scenario, "cpu", rebuild=True, capacity=32,
                           binding=IndexBinding(9, -1, 221))
    checks = {"CPU_default_literal_mission": _literal(baseline, reference["mission"]),
              "CPU_rebuild_capacity_and_index_settings_preserve_archive": _check(
                  baseline["archive"] == rebuilt["archive"], "CPU semantic invariance")}
    ablations = {}
    for phase, literal in reference["phase_ablations"].items():
        current = replace(scenario, manifest=replace(scenario.manifest, initial_phase=int(phase)))
        result, _ = _mission(current, "cpu")
        _literal(result, literal)
        ablations[phase] = result
    zero_scenario = replace(scenario, manifest=replace(scenario.manifest,
                                                      routing=HadamardBinding(gains=((0, 0),) * 4)))
    zero, _ = _mission(zero_scenario, "cpu")
    checks["all_four_phase_banks_and_zero_gain_literals"] = _literal(zero, reference["zero_gain_ablation"])
    checks["packed_phase_changes_executed_route"] = _check(
        baseline["archive"]["events"][0]["decision"]["route"]
        != ablations["192"]["archive"]["events"][0]["decision"]["route"], "phase-selected action")
    domains = []
    for recipe, binding in _domain_cases():
        penalties, increments, fields = _oracle_table(recipe, binding)
        model = RoutingModel.build(recipe, binding)
        _check((model.penalties, model.increments) == (penalties, increments), "independent CPU routing table")
        domains.append({"recipe": recipe.to_dict(), "binding": binding.to_dict(),
                        "nodes": len(fields), "penalty_count": len(penalties),
                        "model_sha256": _sha([penalties, increments])})
    checks["CPU_models_match_independent_fields_and_all_banks"] = True
    deferred = replace(scenario, manifest=replace(scenario.manifest, max_search_expansions=1))
    deferred_cpu, deferred_points = _mission(deferred, "cpu", rebuild=True)
    deferred_control, _ = _mission(deferred, "cpu", capacity=32)
    checks["CPU_DEFER_cursor_rebuild_and_capacity_invariance"] = _check(
        deferred_cpu["archive"] == deferred_control["archive"]
        and any(row["search_pending"] for row in deferred_cpu["rebuilds"]), "CPU retained lifted search")
    return {"checks": checks, "scenario": scenario.to_dict(), "baseline": baseline,
            "rebuilt": rebuilt, "checkpoints": checkpoints, "phase_ablations": ablations,
            "zero_gains": zero, "domains": domains, "deferred": deferred_cpu,
            "deferred_checkpoints": deferred_points,
            "formal_reference_sha256_lf": hashlib.sha256(
                FORMAL_REFERENCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def _gpu_domains():
    results = []
    for ordinal, (recipe, routing) in enumerate(_domain_cases()):
        penalties, increments, fields = _oracle_table(recipe, routing)
        with no_cpu_compilers(), GpuFieldAgentExecutor(
                recipe, IndexBinding(ordinal, -1 if ordinal % 2 else 1, ordinal * 41), routing=routing) as executor:
            model = executor.routing_model
            _check((model.penalties, model.increments) == (penalties, increments), "GPU exported table exact")
            _check(tuple(executor.fields) == fields, "GPU fields against independent BFS")
            checks = 0
            for node in range(len(fields)):
                row = executor.lookup_node(node)
                _check(executor.index.rows[row][4] == node, "GPU canonical lookup with routing atlas")
                for phase in (0, 63, 64, 127, 128, 191, 192, 255):
                    for slot, destination in enumerate(model.neighbors[node]):
                        _check(model.penalty(node, phase, destination) == penalties[node * 16 + (phase // 64) * 4 + slot],
                               "GPU bank-boundary planning table")
                        checks += 1
            results.append({"recipe": recipe.to_dict(), "binding": routing.to_dict(),
                            "nodes": len(fields), "penalty_checks": checks,
                            "model_sha256": _sha([model.penalties, model.increments]),
                            "adapter": executor.adapter_info, "allocation_info": executor.allocation_info})
    return results


def _fresh_replay(directory, label, scenario, archive, backend):
    path = directory / f"{label}.json"
    write_json(path, {"format": SESSION_FORMAT, "scenario": scenario.to_dict(), "agent": archive})
    script = """
import json,sys
from contextlib import nullcontext
from examples.hadamard_conformance import no_cpu_compilers
from solvefinite.f8 import IndexBinding
from solvefinite.session import run_session
with no_cpu_compilers() if sys.argv[2]=='gpu' else nullcontext():
    result=run_session(sys.argv[1],steps=64,capacity=7,backend=sys.argv[2],
                       index_binding=IndexBinding(epoch=31,psi_sign=-1,phase_origin=239))
with open(sys.argv[1],encoding='utf-8') as stream: retained=json.load(stream)
result.pop('state_path',None)
print(json.dumps({'archive':retained['agent'],'result':result,'envelope_keys':sorted(retained),
                  'CPU_compilers_disabled':sys.argv[2]=='gpu'}))
"""
    completed = subprocess.run([sys.executable, "-c", script, str(path), backend], cwd=ROOT,
                               text=True, capture_output=True, timeout=90)
    if completed.returncode:
        raise RuntimeError(f"Fresh-process {label} failed: {completed.stderr}")
    return json.loads(completed.stdout)


def _request(config, scenario, context):
    return {"protocol": PROTOCOL, "type": "observe", "producer": config.producer,
            "epoch": config.epoch, "seq": context["seq"], "position": context["position"],
            "observations": scenario.observe(context["position"], context["seq"])}


def _live_probe(path, scenario):
    config = LiveConfig(scenario.manifest, producer="hadamard-conformance", epoch=7)
    with LiveSession(path, capacity=1, config=config, backend="cpu") as session:
        request = _request(config, scenario, session.ready()["next"])
        first = session.handle(request)
        before = path.read_bytes()
        session.reindex(psi_sign=-1, phase_origin=128)
        _check(path.read_bytes() == before, "CPU live reindex leaves durable bytes unchanged")
    with no_cpu_compilers(), LiveSession(path, capacity=8, backend="gpu",
                                         index_binding=IndexBinding(44, -1, 17)) as session:
        before_file, before_state = path.read_bytes(), session.ready()["state"]
        before_device = session._agent._gpu.snapshot()
        session.reindex(psi_sign=1, phase_origin=222)
        retry = session.handle(request)
        checks = {"retry_is_duplicate": retry["duplicate"] and not first["duplicate"],
                  "same_admitted_event": retry["event"] == first["event"],
                  "retry_preserves_state": session.ready()["state"] == before_state,
                  "retry_and_rebuild_preserve_device": session._agent._gpu.snapshot() == before_device,
                  "retry_and_rebuild_leave_file_bytes": path.read_bytes() == before_file}
        _check(all(checks.values()), "live durable duplicate with new backend/index")
        while session.ready()["next"] is not None:
            context = session.ready()["next"]
            _check(context["seq"] <= MAX_CYCLES, "bounded live mission")
            session.reindex(psi_sign=-session._agent.world.index.binding.psi_sign)
            session.handle(_request(config, scenario, context))
            state = session.ready()["state"]
            actual_pair, energy = session._agent._gpu.snapshot()
            _check((f"{actual_pair:016X}", energy) == (state["agent_pair"], state["energy"]), "live device state")
        info = session.execution_info
    _, restored = load_live(path, capacity=3)
    try:
        return {"checks": checks, "first_response": first, "retry_response": retry,
                "execution_info": info, "archive": restored.archive(),
                "retained_envelope_keys": sorted(json.loads(path.read_text(encoding="utf-8")))}
    finally:
        restored.close()


def demonstrate():
    started = perf_counter()
    reference = json.loads(FORMAL_REFERENCE.read_text(encoding="utf-8"))
    cpu = cpu_conformance()
    checks = dict(cpu["checks"])
    scenario = Scenario.from_dict(cpu["scenario"])
    domains = _gpu_domains()
    checks["GPU_exports_all_banks_without_CPU_compiler_fallback"] = True
    with no_cpu_compilers():
        gpu, checkpoints = _mission(scenario, "gpu", rebuild=True)
        _literal(gpu, reference["mission"])
        checks["GPU_full_mission_and_actual_persistent_states_match_CPU"] = _check(
            gpu["archive"] == cpu["baseline"]["archive"], "complete GPU/CPU admitted history")
        ablations = {}
        for phase, expected in reference["phase_ablations"].items():
            current = replace(scenario, manifest=replace(scenario.manifest, initial_phase=int(phase)))
            result, _ = _mission(current, "gpu", rebuild=True)
            _literal(result, expected)
            _check(result["archive"] == cpu["phase_ablations"][phase]["archive"], "phase ablation full GPU history")
            ablations[phase] = result
        current = replace(scenario, manifest=replace(scenario.manifest,
                                                     routing=HadamardBinding(gains=((0, 0),) * 4)))
        zero, _ = _mission(current, "gpu", rebuild=True)
        _check(zero["archive"] == cpu["zero_gains"]["archive"], "zero-gain full GPU history")
        checks["GPU_phase_and_zero_gain_ablations_match_literal_forecasts"] = True
        deferred_scenario = replace(scenario, manifest=replace(scenario.manifest, max_search_expansions=1))
        deferred, deferred_points = _mission(deferred_scenario, "gpu", rebuild=True)
        checks["GPU_DEFER_search_survives_every_index_rebuild"] = _check(
            deferred["archive"] == cpu["deferred"]["archive"]
            and any(row["search_pending"] for row in deferred["rebuilds"]), "GPU retained phase search")
    checks["GPU_build_plan_action_rebuild_replay_forbid_CPU_compilers"] = True
    resources = gpu["execution_info"]["allocation_info"]
    checks["routing_atlas_model_and_rebuild_peak_accounted_separately"] = _check(
        resources["routing_atlas_bytes"] == 384 * 20
        and resources["device_routing_table_payload_bytes"] == 68 * 20
        and resources["host_routing_table_payload_bytes"] == 68 * 20
        and resources["peak_rebuild_host_routing_payload_bytes"] == 2 * 68 * 20
        and resources["peak_rebuild_device_payload_bytes"] > resources["device_payload_bytes"]
        and resources["retained_world_node_pair_count"] == 0
        and gpu["execution_info"]["active_pair_payload_capacity_bytes"] == 8,
        "separate routing/index/FIFO accounting")
    checks["actual_FIFO_eviction_and_reconstruction"] = _check(
        gpu["FIFO"]["regenerations"] > 0 and cpu["baseline"]["FIFO"]["regenerations"] > 0,
        "materialized world reconstruction")
    replays = {}
    with TemporaryDirectory(prefix="hadamard-conformance-") as temporary:
        directory = Path(temporary)
        for prefix, replay_scenario, source_cpu, source_gpu, expected in (
                ("after-reversing-seam", scenario, cpu["checkpoints"], checkpoints, cpu["baseline"]["archive"]),
                ("during-DEFER", deferred_scenario, cpu["deferred_checkpoints"], deferred_points,
                 cpu["deferred"]["archive"])):
            for source, target, checkpoint in (("cpu", "gpu", source_cpu[2]), ("gpu", "cpu", source_gpu[2])):
                label = f"{prefix}-{source}-to-{target}"
                result = _fresh_replay(directory, label, replay_scenario, checkpoint, target)
                _check(result["archive"] == expected, label)
                _check(result["envelope_keys"] == ["agent", "format", "scenario"], "session envelope")
                replays[label] = {"source_backend": source, "target_backend": target,
                                  "checkpoint_cycle": 2, **result}
        live = _live_probe(directory / "live.json", deferred_scenario)
    checks["fresh_process_CPU_GPU_both_directions_after_seam_and_DEFER"] = len(replays) == 4
    checks["durable_live_retry_rebuild_and_GPU_continuation"] = _check(
        all(live["checks"].values()) and live["archive"] == cpu["deferred"]["archive"], "live full history")
    _check(all(checks.values()), "all recorded checks")
    return {"format": "hadamard-conformance-v1", "formal_binding": "TK-LPLUT-2.0 revision5 HP1-HP8",
            "formal_commit": "0c862c310a13b0baef82065efc2464f14c280f9d", "checks": checks,
            "mission_cycle_bound": MAX_CYCLES, "CPU": cpu, "GPU": gpu,
            "GPU_domains": domains, "GPU_phase_ablations": ablations, "GPU_zero_gains": zero,
            "GPU_deferred": deferred, "fresh_process_replays": replays, "live": live,
            "disabled_CPU_compilers": list(FORBIDDEN_CPU_COMPILERS),
            "canonical_archive_sha256": _sha(cpu["baseline"]["archive"]),
            "elapsed_seconds": round(perf_counter() - started, 3),
            "scope": "Finite phase-selected, typed Hadamard routing inside the same Tomigidt. "
                     "Actual GPU atlas construction, exported planning model and persistent actions "
                     "are independently checked. This does not establish global Psi, geometric growth, "
                     "physical calibration, continuing semantic epochs or comparative performance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/hadamard-conformance.json")
    args = parser.parse_args()
    report = demonstrate()
    write_json(args.output, report)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "checks_passed": sum(report["checks"].values()),
                      "GPU_domains": len(report["GPU_domains"]),
                      "GPU_nodes": sum(row["nodes"] for row in report["GPU_domains"]),
                      "GPU_penalty_checks": sum(row["penalty_checks"] for row in report["GPU_domains"]),
                      "DEFER_cycles": report["GPU_deferred"]["archive"]["expected"]["cycle"],
                      "elapsed_seconds": report["elapsed_seconds"],
                      "canonical_archive_sha256": report["canonical_archive_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
