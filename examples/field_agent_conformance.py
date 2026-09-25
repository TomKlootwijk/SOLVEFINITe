"""Reproduce FI1-FI8 through the existing Tomigidt, Scenario and LiveSession.

Run: python -m examples.field_agent_conformance
Requires the pinned GPU dependency and a supported hardware GPU. Each mission
is bounded to 64 observation cycles. Canonical archives retain all events;
device allocation and disposable FIFO diagnostics are reported separately.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from solvefinite.field import evaluate_field
from solvefinite.field_agent import FIELD_POLICY, FIELD_WORD_PROFILE, FieldAgentManifest
from solvefinite.field_world import FieldWorld, KleinFieldRecipe
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL, load_live
from solvefinite.rp32 import pack, pair, unpack, unpair
from solvefinite.runtime import write_json
from solvefinite.session import SCENARIO_FORMAT, SESSION_FORMAT, Scenario
from solvefinite.tomigidt import FORMAT, Tomigidt


ROOT = Path(__file__).resolve().parents[1]
MAX_CYCLES = 64
# Literal RP32 pairs for FI8's declared initial state and four action vectors.
FI8_PAIRS = ("91FE000601FE00FA", "11FF04FB01FF0405", "81001010910010F0",
             "81011145910111BB", "06011145160111BB")
FI8_ENERGY = (100, 98, 97, 95, 90)


def _fifo_state(world):
    return {"capacity": world.capacity, "active_paths": list(world.active_paths),
            "evicted_paths": list(world.evicted_paths), "hits": world.hit_count,
            "regenerations": world.regeneration_count}


def _run(agent, scenario, checkpoint_cycles=(), resize=False):
    snapshots, device_states, cache_history, checkpoints = [], [], [], {}

    def sample():
        snapshots.append(agent.snapshot())
        cache_history.append(_fifo_state(agent.world))
        if agent._gpu is not None:
            actual_pair, actual_energy = agent._gpu.snapshot()
            device_states.append({"cycle": agent.cycle, "pair": f"{actual_pair:016X}",
                                  "energy": actual_energy})
        if agent.cycle in checkpoint_cycles:
            checkpoints[agent.cycle] = agent.archive()

    sample()
    while agent.status != "COMPLETE":
        if agent.cycle >= MAX_CYCLES:
            raise ValueError("Conformance mission exceeded its 64-cycle bound")
        if resize:
            agent.world.resize((1, 32, 2, 1)[agent.cycle % 4])
        agent.step(scenario.observe(agent.position, agent.cycle + 1))
        sample()
    return {"archive": agent.archive(), "snapshots": snapshots,
            "device_states": device_states, "cache_history": cache_history,
            "execution_info": agent.execution_info}, checkpoints


def _device_matches(run):
    return len(run["device_states"]) == len(run["snapshots"]) and all(
        (device["cycle"], device["pair"], device["energy"]) ==
        (host["cycle"], host["agent_pair"], host["energy"])
        for device, host in zip(run["device_states"], run["snapshots"]))


def _fifo_probe(recipe, executor=None):
    world = FieldWorld(recipe, 2, executor)
    before = None if executor is None else executor.snapshot()
    calls = (patch("solvefinite.field_world.evaluate_field", wraps=evaluate_field)
             if executor is None else patch.object(executor, "derive_node", wraps=executor.derive_node))
    operations = ("k:0:0", "k:0:1", "k:0:0", "k:0:2", "k:0:0")
    history, nodes = [], []
    with calls as derive:
        for name in operations:
            node = world.get(name)
            nodes.append(node)
            history.append({"requested": name, "pair": f"{node.pair:016X}",
                            "derivation_calls": derive.call_count, **_fifo_state(world)})
    cold_recipe = KleinFieldRecipe.from_dict(json.loads(json.dumps(recipe.to_dict())))
    cold = FieldWorld(cold_recipe, 1).derive(operations[0])
    after = None if executor is None else executor.snapshot()
    checks = {
        "hit_does_not_refresh_fifo": history[2]["active_paths"] == ["k:0:0", "k:0:1"],
        "oldest_insertion_evicted": history[3]["evicted_paths"] == ["k:0:0"],
        "real_derivation_on_each_miss": [row["derivation_calls"] for row in history] == [1, 2, 2, 3, 4],
        "hit_reuses_active_node": nodes[2] is nodes[0],
        "evicted_node_reconstructed_exactly": nodes[4] == nodes[0] and nodes[4] is not nodes[0],
        "regeneration_counter_counts_returning_miss": world.regeneration_count == 1,
        "cold_recipe_rebuild_equal": cold == nodes[0],
    }
    if executor is not None:
        checks["derivation_preserves_canonical_device_state"] = before == after
    return {"checks": checks, "operations": history, "cold_pair": f"{cold.pair:016X}",
            "device_before": None if before is None else [f"{before[0]:016X}", before[1]],
            "device_after": None if after is None else [f"{after[0]:016X}", after[1]]}


def _fresh_session_replay(directory, label, scenario, checkpoint, backend):
    path = directory / f"{label}.json"
    write_json(path, {"format": SESSION_FORMAT, "scenario": scenario.to_dict(),
                      "agent": checkpoint})
    code = """
import json, sys
from solvefinite.session import run_session
result = run_session(sys.argv[1], steps=64, capacity=32, backend=sys.argv[2])
with open(sys.argv[1], encoding='utf-8') as stream:
    retained = json.load(stream)
print(json.dumps({'archive': retained['agent'], 'result': result}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(path), backend], cwd=ROOT,
        text=True, capture_output=True, timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(f"Fresh-process replay {label} failed: {completed.stderr}")
    result = json.loads(completed.stdout)
    # Temporary paths are not part of the canonical evidence.
    result["result"].pop("state_path", None)
    return result


def _live_probe(path, scenario):
    config = LiveConfig(scenario.manifest, producer="field-conformance", epoch=1)
    with LiveSession(path, capacity=1, config=config, backend="cpu") as session:
        ready = session.ready()
        next_frame = ready["next"]
        request = {"protocol": PROTOCOL, "type": "observe", "producer": config.producer,
                   "epoch": config.epoch, "seq": next_frame["seq"],
                   "position": next_frame["position"],
                   "observations": scenario.observe(next_frame["position"], next_frame["seq"])}
        first = session.handle(request)
    with LiveSession(path, capacity=32, backend="gpu") as session:
        retry = session.handle(request)
        responses = [retry]
        while session.ready()["next"] is not None:
            context = session.ready()["next"]
            if context["seq"] > MAX_CYCLES:
                raise ValueError("Live conformance mission exceeded its cycle bound")
            responses.append(session.handle({
                "protocol": PROTOCOL, "type": "observe", "producer": config.producer,
                "epoch": config.epoch, "seq": context["seq"], "position": context["position"],
                "observations": scenario.observe(context["position"], context["seq"]),
            }))
    retained, agent = load_live(path, capacity=2)
    try:
        return {"config": retained.to_dict(), "initial_response": first,
                "resumed_responses": responses, "archive": agent.archive(),
                "retry_reuses_original_event": bool(retry["duplicate"])
                    and not first["duplicate"] and retry["event"] == first["event"]}
    finally:
        agent.close()


def _rejects(archive, backend):
    try:
        restored = Tomigidt.from_archive(archive, backend=backend)
    except ValueError as exc:
        return {"rejected": True, "reason": str(exc)}
    restored.close()
    return {"rejected": False, "reason": "Altered archive was accepted"}


def _sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def demonstrate():
    with ExitStack() as owners, TemporaryDirectory(prefix="field-agent-conformance-") as temporary:
        directory = Path(temporary)

        def own(manifest, capacity=2, backend="cpu"):
            agent = Tomigidt(manifest, capacity=capacity, backend=backend)
            owners.callback(agent.close)
            return agent

        manifest = FieldAgentManifest()
        scenario = Scenario(manifest, changes=((2, "k:0:3", 70),))
        cpu = own(manifest, capacity=32)
        gpu = own(manifest, capacity=1, backend="gpu")
        cpu_run, cpu_checkpoints = _run(cpu, scenario, (1,))
        gpu_run, gpu_checkpoints = _run(gpu, scenario, (1,))
        fields = tuple(gpu._gpu.fields)
        cpu_fifo = _fifo_probe(manifest.world)
        gpu_fifo = _fifo_probe(manifest.world, gpu._gpu)
        small_run, _ = _run(own(manifest, capacity=1), scenario)
        resized_run, _ = _run(own(manifest, capacity=32), scenario, resize=True)

        changed_manifest = replace(manifest, world=replace(manifest.world, center=4))
        changed_scenario = replace(scenario, manifest=changed_manifest)
        ablated_cpu, _ = _run(own(changed_manifest), changed_scenario)
        ablated_gpu, _ = _run(own(changed_manifest, backend="gpu"), changed_scenario)

        deferred_manifest = replace(manifest, max_search_expansions=1)
        deferred_scenario = replace(scenario, manifest=deferred_manifest)
        deferred_cpu, deferred_cpu_checkpoints = _run(own(deferred_manifest), deferred_scenario, (2,))
        deferred_gpu, deferred_gpu_checkpoints = _run(
            own(deferred_manifest, backend="gpu"), deferred_scenario, (2,))
        replays = {}
        for prefix, replay_scenario, source_cpu, source_gpu, cycle in (
                ("before-seam", scenario, cpu_checkpoints, gpu_checkpoints, 1),
                ("deferred-search", deferred_scenario,
                 deferred_cpu_checkpoints, deferred_gpu_checkpoints, 2)):
            for source, target, checkpoint in (("cpu", "gpu", source_cpu[cycle]),
                                                ("gpu", "cpu", source_gpu[cycle])):
                label = f"{prefix}-{source}-to-{target}"
                replays[label] = {"source_backend": source, "replay_backend": target,
                                  "checkpoint": checkpoint,
                                  **_fresh_session_replay(directory, label, replay_scenario,
                                                          checkpoint, target)}
        live = _live_probe(directory / "live.json", scenario)

        archive = cpu_run["archive"]
        tampered_energy = deepcopy(archive)
        tampered_energy["events"][0]["energy"] += 1
        tampered_recipe = deepcopy(archive)
        tampered_recipe["manifest"]["world"]["center"] = 4
        tampered_forecast = deepcopy(archive)
        old = int(tampered_forecast["events"][0]["decision"]["forecast"][0], 16)
        r, g, b, a = unpack(unpair(old)[0])
        valid_but_wrong = pair(pack((r + 1) % 256, g, b, a))
        unpair(valid_but_wrong)
        tampered_forecast["events"][0]["decision"]["forecast"][0] = f"{valid_but_wrong:016X}"
        rejection = {f"{name}-{backend}": _rejects(value, backend)
                     for name, value in (("energy", tampered_energy), ("recipe", tampered_recipe),
                                         ("valid-parity-forecast", tampered_forecast))
                     for backend in ("cpu", "gpu")}

        initial = gpu_run["snapshots"][0]
        observed_pairs = tuple(snapshot["agent_pair"] for snapshot in gpu_run["snapshots"])
        observed_energy = tuple(snapshot["energy"] for snapshot in gpu_run["snapshots"])
        seam_events = []
        previous = initial
        seams = set(manifest.world.domain().seams)
        for state, event in zip(gpu_run["snapshots"][1:], gpu_run["archive"]["events"]):
            r, source, signed, metadata = unpack(unpair(int(previous["agent_pair"], 16))[0])
            next_r, destination, next_signed, next_metadata = unpack(unpair(int(state["agent_pair"], 16))[0])
            if event["decision"]["kind"] == "MOVE" and tuple(sorted((source, destination))) in seams:
                eta = (metadata >> 4) & 1
                delta = manifest.world.turns[0 if signed < 0 else 1 if signed == 0 else 2]
                seam_events.append({"cycle": state["cycle"], "source": source, "destination": destination,
                                    "phase_before": r, "delta": delta,
                                    "phase_before_transport": (r + (-1 if eta else 1) * delta) % 256,
                                    "phase_after": next_r, "orientation_before": eta,
                                    "orientation_after": (next_metadata >> 4) & 1,
                                    "field_after": next_signed, "energy_after": state["energy"]})
            previous = state

        checks = {
            "reference_cpu_gpu_full_archives_equal": cpu_run["archive"] == gpu_run["archive"],
            "reference_literal_FI8_pairs": observed_pairs == FI8_PAIRS,
            "reference_literal_FI8_energy": observed_energy == FI8_ENERGY,
            "actual_device_state_matches_every_reference_cycle": _device_matches(gpu_run),
            "live_B_is_certified_scalar": all(
                unpack(unpair(int(value, 16))[0])[2] == fields[unpack(unpair(int(value, 16))[0])[1]]
                for value in observed_pairs),
            "energy_is_separate_from_B": all(
                energy != unpack(unpair(int(value, 16))[0])[2]
                for value, energy in zip(observed_pairs, observed_energy)),
            "fresh_hazard_changes_planned_next_hop": (
                archive["events"][0]["decision"]["route"][1]
                != archive["events"][1]["decision"]["route"][0]),
            "seam_reflects_phase_and_orientation": bool(seam_events) and all(
                row["phase_after"] == -row["phase_before_transport"] % 256
                and row["orientation_after"] == row["orientation_before"] ^ 1 for row in seam_events),
            "center_ablation_changes_first_route": (
                ablated_cpu["archive"]["events"][0]["decision"]["route"]
                != archive["events"][0]["decision"]["route"]),
            "ablated_cpu_gpu_full_archives_equal": ablated_cpu["archive"] == ablated_gpu["archive"],
            "actual_device_state_matches_ablated_cycles": _device_matches(ablated_gpu),
            "cpu_fifo_regenerates_exactly": all(cpu_fifo["checks"].values()),
            "gpu_fifo_regenerates_exactly": all(gpu_fifo["checks"].values()),
            "cache_capacity_and_resize_preserve_history": archive == small_run["archive"] == resized_run["archive"],
            "deferred_checkpoint_retains_search": (
                deferred_cpu_checkpoints[2]["expected"]["planning"] is not None
                and deferred_cpu_checkpoints[2]["expected"]["status"] == "SEARCH_DEFERRED"),
            "deferred_cpu_gpu_full_archives_equal": deferred_cpu["archive"] == deferred_gpu["archive"],
            "actual_device_state_matches_deferred_cycles": _device_matches(deferred_gpu),
            "fresh_process_both_directions_replay_before_seam": all(
                value["archive"] == archive for label, value in replays.items() if label.startswith("before-seam")),
            "fresh_process_both_directions_replay_deferred_search": all(
                value["archive"] == deferred_cpu["archive"] for label, value in replays.items()
                if label.startswith("deferred-search")),
            "live_cross_backend_retry_is_idempotent": live["retry_reuses_original_event"],
            "live_wrapper_preserves_full_agent_history": live["archive"] == archive,
            "tampered_energy_recipe_forecast_rejected": all(row["rejected"] for row in rejection.values()),
            "gpu_retains_no_world_pair_arena": gpu.execution_info["allocation_info"]["retained_world_node_pair_count"] == 0,
        }
        if not all(checks.values()):
            raise ValueError(f"Field-agent conformance failed: {checks}")
        return {
            "format": "tomigidt-field-agent-conformance-v1", "checks": checks,
            "formal_binding": "TK-LPLUT-2.0 revision 1, FI1-FI8",
            "source_profiles": {"agent_archive": FORMAT, "policy": FIELD_POLICY,
                                "word_profile": FIELD_WORD_PROFILE, "world_recipe": manifest.world.version,
                                "field_manifest": manifest.world.field_manifest().profile,
                                "scenario": SCENARIO_FORMAT, "session": SESSION_FORMAT, "live": PROTOCOL},
            "mission_cycle_bound": MAX_CYCLES, "scenario": scenario.to_dict(),
            "literal_FI8_pairs": list(FI8_PAIRS), "literal_FI8_energy": list(FI8_ENERGY),
            "certified_gpu_field": list(fields), "reference_cpu": cpu_run, "reference_gpu": gpu_run,
            "seam_events": seam_events, "fifo_cpu": cpu_fifo, "fifo_gpu": gpu_fifo,
            "capacity_one": small_run, "resized_cache": resized_run,
            "center_ablation": {"scenario": changed_scenario.to_dict(), "cpu": ablated_cpu, "gpu": ablated_gpu},
            "deferred_search": {"cpu": deferred_cpu, "gpu": deferred_gpu},
            "fresh_process_replays": replays, "live_session": live, "tamper_rejections": rejection,
            "canonical_archive_sha256": _sha256(archive),
            "array_separation": {
                "canonical": "One packed agent pair, separate energy, original observations, decisions and recipe.",
                "disposable_fifo": "Only materialized DATA pairs, ordered by insertion; histories and counters are diagnostic.",
                "gpu_auxiliary": gpu.execution_info["allocation_info"],
                "forecast": "Device forecast scratch is separate from actual canonical pair and energy.",
            },
            "scope": "One existing Tomigidt with finite recipe-derived Klein SDF geometry, local observations, "
                     "autonomous route search, actual GPU actions and replay. No performance claim, physical actuator, "
                     "Psi eigenstructure, full f8, geometry-changing growth or indefinite continuation is established.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/field-agent/conformance.json")
    args = parser.parse_args()
    report = demonstrate()
    write_json(args.output, report)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "checks_passed": sum(report["checks"].values()),
                      "final_state": report["reference_gpu"]["archive"]["expected"],
                      "canonical_archive_sha256": report["canonical_archive_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
