"""Reproduce PX1-PX8 on the CPU and a supported hardware GPU.

Run: python -m examples.psi_f8_conformance
The 702 finite CPU domains and every agent mission are explicitly bounded.
The default run requires actual GPU construction, lookup, rebuild and action;
it does not silently skip unavailable hardware or replace device work.
"""

import argparse
from collections import deque
from contextlib import ExitStack
from copy import deepcopy
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

from solvefinite.f8 import F8Index, IndexBinding, NULL
from solvefinite.field_agent import FieldAgentManifest
from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
from solvefinite.field_world import FieldWorld, KleinFieldRecipe
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL, load_live
from solvefinite.psi import axis_from_gradient
from solvefinite.rp32 import unpack, unpair
from solvefinite.runtime import write_json
from solvefinite.session import SESSION_FORMAT, Scenario
from solvefinite.tomigidt import Tomigidt


ROOT = Path(__file__).resolve().parents[1]
MAX_CYCLES = 64
FORMAL_REFERENCE = ROOT / "docs/evidence/psi-f8-v1/formal-reference.json"
PRIOR_CONFORMANCE = ROOT / "docs/evidence/field-agent-v1/conformance.json"
FI8_PAIRS = ("91FE000601FE00FA", "11FF04FB01FF0405", "81001010910010F0",
             "81011145910111BB", "06011145160111BB")
FI8_ENERGY = (100, 98, 97, 95, 90)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check(condition, label):
    if not condition:
        raise ValueError(f"Psi/f8 conformance failed: {label}")
    return True


def _cover_node(width, height, u, v):
    wrap, column = divmod(u, width)
    return column * height + ((-v if wrap % 2 else v) % height)


def _independent_geometry(recipe):
    width, height = recipe.width, recipe.height
    directions = []
    for node in range(width * height):
        u, v = divmod(node, height)
        directions.append(tuple(_cover_node(width, height, a, b)
                                for a, b in ((u + 1, v), (u - 1, v),
                                             (u, v + 1), (u, v - 1))))

    def bfs(sources):
        distances = [-1] * len(directions)
        pending = deque(sources)
        for source in sources:
            distances[source] = 0
        while pending:
            source = pending.popleft()
            for target in directions[source]:
                if distances[target] < 0:
                    distances[target] = distances[source] + 1
                    pending.append(target)
        return tuple(distances)

    depths = bfs((recipe.center,))
    signs = tuple((distance > recipe.radius) - (distance < recipe.radius) for distance in depths)
    boundary_distance = bfs(tuple(node for node, sign in enumerate(signs) if sign == 0))
    fields = tuple(sign * distance for sign, distance in zip(signs, boundary_distance))
    parents = tuple(recipe.center if node == recipe.center else
                    min(neighbor for neighbor in adjacent if depths[neighbor] == depths[node] - 1)
                    for node, adjacent in enumerate(directions))
    return tuple(directions), depths, parents, fields


def _independent_index(recipe, binding):
    """Cover/BFS oracle, direct equations and an iterative interval tree."""
    directions, depths, parents, fields = _independent_geometry(recipe)
    records = []
    for node, (up, um, vp, vm) in enumerate(directions):
        gu, gv = fields[up] - fields[um], fields[vp] - fields[vm]
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        pu, pv = binding.psi_sign * pu, binding.psi_sign * pv
        path, cursor = [], node
        while cursor != recipe.center:
            path.append(cursor)
            cursor = parents[cursor]
        phase, orientation, source = binding.phase_origin, 0, recipe.center
        for destination in reversed(path):
            column = 0 if fields[source] < 0 else 1 if fields[source] == 0 else 2
            phase = (phase + (1 - 2 * orientation) * recipe.turns[column]) % 256
            # Only horizontal rectangle gluing changes local orientation.
            seam = abs(source // recipe.height - destination // recipe.height) == recipe.width - 1
            if seam:
                phase = -phase % 256
                orientation ^= 1
            source = destination
        canonical_phase = (-phase if orientation else phase) % 256
        records.append((pu + 2, pv + 2, (depths[node] + 1).bit_length() - 1,
                        canonical_phase, node, gu * gu + gv * gv, gu + 2, gv + 2))
    ordered = sorted(record[:5] for record in records)
    rows, pending = [], [(0, len(ordered), None, None)]
    while pending:
        low, high, parent_row, child_column = pending.pop()
        middle = (low + high - 1) // 2
        row = len(rows)
        rows.append([*ordered[middle], NULL, NULL, 0])
        if parent_row is not None:
            rows[parent_row][child_column] = row
        if middle + 1 < high:
            pending.append((middle + 1, high, row, 6))
        if low < middle:
            pending.append((low, middle, row, 5))
    return tuple(records), tuple(tuple(row) for row in rows), fields


def cpu_conformance():
    """Run the independently checkable finite-domain portion without a GPU."""
    started = perf_counter()
    recipe, binding = KleinFieldRecipe(), IndexBinding()
    reference = json.loads(FORMAL_REFERENCE.read_text(encoding="utf-8"))
    expected_records = tuple((*row["key"], row["eigenvalue"], row["g"][0] + 2, row["g"][1] + 2)
                             for row in reference["records"])
    expected_rows = tuple((*reference["records"][row["node"]]["key"], row["left"], row["right"], 0)
                          for row in reference["rows"])
    oracle_records, oracle_rows, fields = _independent_index(recipe, binding)
    index = F8Index.build(recipe, binding)
    checks = {
        "default_literal_records_and_full_rows": _check(
            index.records == expected_records == oracle_records
            and index.rows == expected_rows == oracle_rows, "literal default keys and rows"),
        "physical_root_is_not_G": _check(index.rows[0][4] == 1 and index.resolve(0) == 10,
                                          "physical row differs from geometric G"),
        "tree_edge_1_to_16_is_not_geometric": _check(
            index.rows[index.rows[0][5]][4] == 16
            and 16 not in _independent_geometry(recipe)[0][1], "tree edge is not movement"),
    }
    gradients = []
    for gu in range(-2, 3):
        for gv in range(-2, 3):
            for sign in (-1, 1):
                axis = axis_from_gradient(gu, gv, sign)
                for orientation in (0, 1):
                    actual = axis.transport(orientation)
                    pu, pv = actual.vector
                    a, b, c, d = actual.tensor
                    value = actual.eigenvalue
                    _check((a * pu + b * pv, c * pu + d * pv) == (value * pu, value * pv)
                           and a + d == value and a * d - b * c == 0 and value >= 0
                           and gcd(abs(pu), abs(pv)) == 1,
                           f"eigen certificate {(gu, gv, sign, orientation)}")
                    _check(actual.gradient == (gu, (1 - 2 * orientation) * gv)
                           and actual.degenerate == ((gu, gv) == (0, 0))
                           and actual.transport(orientation) == axis, "frame and degeneracy")
                    gradients.append({"g": [gu, gv], "sign": sign, "orientation": orientation,
                                      "psi": list(actual.vector), "lambda": value})
    checks["all_25_gradients_both_signs_and_frames"] = len(gradients) == 100

    domains, total_nodes = [], 0
    for width in range(3, 86):
        for height in range(3, 86):
            if width * height > 256:
                continue
            current_recipe = KleinFieldRecipe(width=width, height=height, radius=2)
            records, rows, scalar = _independent_index(current_recipe, binding)
            current = F8Index.build(current_recipe, binding, scalar)
            _check(current.records == records and current.rows == rows, f"independent domain {width}x{height}")
            _check(all(current.rows[current.resolve(node)][4] == node for node in range(width * height)),
                   f"complete lookup {width}x{height}")
            total_nodes += width * height
            domains.append({"width": width, "height": height, "nodes": width * height,
                            "root_node": rows[0][4], "record_tree_sha256": _sha([records, rows])})
    checks["all_702_supported_domains_cover_bfs_index_and_lookup"] = _check(len(domains) == 702, "domain count")

    aliases = []
    for u, v in ((0, 0), (4, 0), (7, -1), (-1, 1), (-17, -26), (4003, -5001)):
        node = _cover_node(4, 5, u, v)
        row = index.lookup_chart(u, v)
        _check(index.rows[row][4] == node, "canonical quotient alias")
        aliases.append({"chart": [u, v], "node": node, "row": row})
    checks["negative_and_large_quotient_aliases"] = True
    checks["valid_absent_key_is_miss"] = _check(index.lookup((0, 0, 0, 0, (1 << 32) - 1)) is None,
                                               "absent key")
    checks["snapshot_round_trip"] = _check(F8Index.from_snapshot(index.snapshot()) == index,
                                           "snapshot round trip")
    rejected = []
    for label, edit in (
            ("key", lambda value: value["records"][0].__setitem__(0, 4)),
            ("gradient", lambda value: value["records"][6].__setitem__(6, 2)),
            ("eigenvalue", lambda value: value["records"][7].__setitem__(5, 4)),
            ("phase", lambda value: value["records"][16].__setitem__(3, 255)),
            ("row_cycle", lambda value: value["rows"][0].__setitem__(5, 0)),
            ("reserved_word", lambda value: value["rows"][0].__setitem__(7, 1)),
            ("Boolean_epoch", lambda value: value["binding"].__setitem__("epoch", True)),
            ("unknown_key", lambda value: value.__setitem__("extra", 0))):
        changed = deepcopy(index.snapshot())
        edit(changed)
        try:
            F8Index.from_snapshot(changed)
        except ValueError as exc:
            rejected.append({"case": label, "reason": str(exc)})
        else:
            raise ValueError(f"Corrupted index snapshot accepted: {label}")
    checks["corrupted_snapshots_rejected"] = len(rejected) == 8
    return {"checks": checks, "default_index": index.snapshot(), "default_field": fields,
            "formal_reference_sha256": hashlib.sha256(FORMAL_REFERENCE.read_bytes()).hexdigest(),
            "literal_reference": reference, "gradient_certificates": gradients,
            "domains": domains, "domain_count": len(domains), "node_count": total_nodes,
            "aliases": aliases, "rejected_snapshots": rejected,
            "elapsed_seconds": round(perf_counter() - started, 3)}


def _fifo(world):
    return {"capacity": world.capacity, "active": list(world.active_paths),
            "evicted": list(world.evicted_paths), "hits": world.hit_count,
            "regenerations": world.regeneration_count}


def _rebuild(agent):
    before_archive, before_fifo = agent.archive(), _fifo(agent.world)
    planning, original = agent._planning, agent.world.index
    before_device = None if agent._gpu is None else agent._gpu.snapshot()
    replacement = agent.reindex(psi_sign=-original.binding.psi_sign,
                                 phase_origin=(original.binding.phase_origin + 37) % 256)
    after_device = None if agent._gpu is None else agent._gpu.snapshot()
    checks = {"archive_unchanged": agent.archive() == before_archive,
              "FIFO_and_counters_unchanged": _fifo(agent.world) == before_fifo,
              "same_search_object": agent._planning is planning,
              "actual_device_unchanged": before_device == after_device,
              "epoch_increments_once": replacement.binding.epoch == original.binding.epoch + 1,
              "old_immutable_index_retained": original.binding != replacement.binding,
              "keys_rebuilt": original.records != replacement.records}
    _check(all(checks.values()), "atomic rebuild invariants")
    return {"cycle": agent.cycle, "search_pending": planning is not None,
            "before": original.binding.to_dict(), "after": replacement.binding.to_dict(),
            "checks": checks, "archive_sha256": _sha(before_archive), "FIFO": before_fifo,
            "execution_info": agent.execution_info}


def _mission(scenario, backend, rebuild=False, binding=None):
    agent = Tomigidt(scenario.manifest, capacity=1, backend=backend, index_binding=binding)
    try:
        snapshots, device, rebuilds, checkpoints = [], [], [], {}
        while True:
            state = agent.snapshot()
            snapshots.append(state)
            if agent._gpu is not None:
                actual_pair, actual_energy = agent._gpu.snapshot()
                _check((f"{actual_pair:016X}", actual_energy) == (state["agent_pair"], state["energy"]),
                       "canonical GPU pair and energy")
                device.append({"cycle": agent.cycle, "pair": f"{actual_pair:016X}", "energy": actual_energy})
            if agent.cycle in (1, 2):
                checkpoints[agent.cycle] = agent.archive()
            if agent.status == "COMPLETE":
                break
            _check(agent.cycle < MAX_CYCLES, "bounded 64-cycle mission")
            if rebuild:
                rebuilds.append(_rebuild(agent))
            agent.step(scenario.observe(agent.position, agent.cycle + 1))
        return {"archive": agent.archive(), "snapshots": snapshots, "device_states": device,
                "rebuilds": rebuilds, "execution_info": agent.execution_info,
                "FIFO": _fifo(agent.world)}, checkpoints
    finally:
        agent.close()


def _fifo_rebuild_probe(backend):
    agent = Tomigidt(FieldAgentManifest(), capacity=2, backend=backend)
    try:
        original = agent.world.get("k:0:0")
        agent.world.get("k:0:1")
        hit = agent.world.get("k:0:0")
        unchanged_hit_order = agent.world.active_paths == ("k:0:0", "k:0:1")
        agent.world.get("k:0:2")
        reconstruction_before = _fifo(agent.world)
        rebuild = _rebuild(agent)
        reconstructed = agent.world.get("k:0:0")
        cold = FieldWorld(KleinFieldRecipe(), 1,
                          index_binding=IndexBinding(epoch=9, psi_sign=-1, phase_origin=221)).derive("k:0:0")
        checks = {"hit_keeps_insertion_order": unchanged_hit_order and hit is original,
                  "original_was_evicted": reconstruction_before["evicted"] == ["k:0:0"],
                  "reconstructed_under_new_index": reconstructed == original and reconstructed is not original,
                  "cold_new_version_equal": cold == original,
                  "real_regeneration_count": agent.world.regeneration_count == 1}
        _check(all(checks.values()), "FIFO regeneration across rebuild")
        return {"checks": checks, "rebuild": rebuild, "before": reconstruction_before,
                "after": _fifo(agent.world), "pair": f"{original.pair:016X}"}
    finally:
        agent.close()


def _fresh_replay(directory, label, scenario, archive, backend):
    path = directory / f"{label}.json"
    write_json(path, {"format": SESSION_FORMAT, "scenario": scenario.to_dict(), "agent": archive})
    script = """
import json,sys
from solvefinite.f8 import IndexBinding
from solvefinite.session import run_session
result=run_session(sys.argv[1],steps=64,capacity=7,backend=sys.argv[2],
                   index_binding=IndexBinding(epoch=31,psi_sign=-1,phase_origin=239))
with open(sys.argv[1],encoding='utf-8') as stream: retained=json.load(stream)
result.pop('state_path',None)
print(json.dumps({'archive':retained['agent'],'result':result,'envelope_keys':sorted(retained)}))
"""
    completed = subprocess.run([sys.executable, "-c", script, str(path), backend], cwd=ROOT,
                               text=True, capture_output=True, timeout=60)
    if completed.returncode:
        raise RuntimeError(f"Fresh-process {label} failed: {completed.stderr}")
    return json.loads(completed.stdout)


def _request(config, scenario, context):
    return {"protocol": PROTOCOL, "type": "observe", "producer": config.producer,
            "epoch": config.epoch, "seq": context["seq"], "position": context["position"],
            "observations": scenario.observe(context["position"], context["seq"])}


def _live_probe(path, scenario):
    config = LiveConfig(scenario.manifest, producer="psi-f8-conformance", epoch=7)
    with LiveSession(path, capacity=1, config=config, backend="cpu",
                     index_binding=IndexBinding(epoch=4, phase_origin=63)) as session:
        request = _request(config, scenario, session.ready()["next"])
        first = session.handle(request)
        before = path.read_bytes()
        session.reindex(psi_sign=-1, phase_origin=128)
        _check(path.read_bytes() == before, "live reindex does not rewrite retained state")
        first_index = session.execution_info["index"]
    with LiveSession(path, capacity=8, backend="gpu",
                     index_binding=IndexBinding(epoch=44, psi_sign=-1, phase_origin=17)) as session:
        before_file = path.read_bytes()
        before_state = session.ready()["state"]
        before_device = session._agent._gpu.snapshot()
        session.reindex(psi_sign=1, phase_origin=222)
        retry = session.handle(request)
        checks = {"retry_is_duplicate": retry["duplicate"] and not first["duplicate"],
                  "same_admitted_event": retry["event"] == first["event"],
                  "retry_preserves_cycle_and_state": session.ready()["state"] == before_state,
                  "retry_and_rebuild_preserve_device": session._agent._gpu.snapshot() == before_device,
                  "retry_and_rebuild_leave_file_bytes": path.read_bytes() == before_file}
        _check(all(checks.values()), "live duplicate across backend and index versions")
        while session.ready()["next"] is not None:
            context = session.ready()["next"]
            _check(context["seq"] <= MAX_CYCLES, "bounded live mission")
            session.reindex(psi_sign=-session._agent.world.index.binding.psi_sign)
            session.handle(_request(config, scenario, context))
            state = session.ready()["state"]
            actual_pair, actual_energy = session._agent._gpu.snapshot()
            _check((f"{actual_pair:016X}", actual_energy) == (state["agent_pair"], state["energy"]),
                   "live actual device state")
        execution_info = session.execution_info
    _, restored = load_live(path, capacity=3, index_binding=IndexBinding(epoch=91, phase_origin=1))
    try:
        return {"checks": checks, "first_response": first, "retry_response": retry,
                "first_index": first_index, "execution_info": execution_info,
                "archive": restored.archive(),
                "retained_envelope_keys": sorted(json.loads(path.read_text(encoding="utf-8")))}
    finally:
        restored.close()


def _gpu_domains():
    results = []
    for recipe, binding in (
            (KleinFieldRecipe(), IndexBinding()),
            (KleinFieldRecipe(width=3, height=3, center=8, radius=1), IndexBinding(1, -1, 255)),
            (KleinFieldRecipe(width=5, height=7, center=11, radius=3), IndexBinding(2, 1, 137)),
            (KleinFieldRecipe(width=3, height=85, center=127, radius=31), IndexBinding(3, -1, 19)),
            (KleinFieldRecipe(width=85, height=3, center=254, radius=20), IndexBinding(4, 1, 233)),
            (KleinFieldRecipe(width=16, height=16, center=255, radius=8), IndexBinding(5, -1, 128))):
        expected_records, expected_rows, fields = _independent_index(recipe, binding)
        cpu = F8Index.build(recipe, binding, fields)
        with GpuFieldAgentExecutor(recipe, index_binding=binding) as executor:
            actual = executor.index
            _check(actual.records == cpu.records == expected_records
                   and actual.rows == cpu.rows == expected_rows, "GPU records and full rows")
            _check(tuple(executor.fields) == fields, "GPU scalar field against BFS")
            lookups = []
            for node in range(recipe.width * recipe.height):
                row = executor.lookup_node(node)
                _check(row == cpu.resolve(node) and actual.rows[row][4] == node, "actual GPU lookup")
                materialized = executor.derive_node(node)
                _, decoded_node, decoded_field, _ = unpack(unpair(materialized)[0])
                _check((decoded_node, decoded_field) == (node, fields[node]),
                       "GPU sample preserves geometric G through physical row lookup")
                lookups.append({"node": node, "row": row, "decoded_G": decoded_node,
                                "DATA_pair": f"{materialized:016X}"})
            results.append({"recipe": recipe.to_dict(), "binding": binding.to_dict(),
                            "records": actual.records, "rows": actual.rows, "lookups": lookups,
                            "adapter": executor.adapter_info, "allocation_info": executor.allocation_info})
    return results


def _no_cpu_compiler_mission(scenario):
    forbidden = ("solvefinite.f8.F8Index.build", "solvefinite.f8._compile_records",
                 "solvefinite.f8._compile_rows", "solvefinite.f8.evaluate_field",
                 "solvefinite.field.evaluate_field", "solvefinite.field_world.evaluate_field",
                 "solvefinite.psi.field_axes", "solvefinite.psi.axis_from_gradient")
    with ExitStack() as patches:
        for name in forbidden:
            patches.enter_context(patch(name, side_effect=AssertionError(f"Forbidden CPU fallback: {name}")))
        result, _ = _mission(scenario, "gpu", rebuild=True,
                              binding=IndexBinding(epoch=8, psi_sign=-1, phase_origin=71))
    return {"disabled_compilers": list(forbidden), **result}


def demonstrate():
    started = perf_counter()
    cpu = cpu_conformance()
    checks = dict(cpu["checks"])
    gpu_domains = _gpu_domains()
    checks["GPU_key_records_full_rows_and_real_tree_lookups"] = True
    scenario = Scenario(FieldAgentManifest(), changes=((2, "k:0:3", 70),))
    baseline, baseline_checkpoints = _mission(scenario, "cpu")
    rebuilt_cpu, _ = _mission(scenario, "cpu", rebuild=True)
    rebuilt_gpu, gpu_checkpoints = _mission(scenario, "gpu", rebuild=True)
    prior = json.loads(PRIOR_CONFORMANCE.read_text(encoding="utf-8"))
    archive = baseline["archive"]
    checks["FI8_full_history_unchanged_from_c8_evidence"] = _check(
        archive == rebuilt_cpu["archive"] == rebuilt_gpu["archive"] == prior["reference_cpu"]["archive"],
        "unchanged full FI8 admitted history")
    checks["literal_FI8_pairs_and_energy"] = _check(
        tuple(state["agent_pair"] for state in rebuilt_gpu["snapshots"]) == FI8_PAIRS
        and tuple(state["energy"] for state in rebuilt_gpu["snapshots"]) == FI8_ENERGY, "FI8 literals")
    checks["CPU_GPU_rebuild_preserves_FIFO_search_and_actual_state"] = _check(
        all(all(event["checks"].values()) for result in (rebuilt_cpu, rebuilt_gpu)
            for event in result["rebuilds"]), "rebuild unchanged state")
    resources = rebuilt_gpu["execution_info"]["allocation_info"]
    checks["peak_rebuild_and_auxiliary_storage_accounted_outside_FIFO"] = _check(
        resources["peak_rebuild_device_payload_bytes"] > resources["device_payload_bytes"]
        and resources["peak_rebuild_host_index_payload_bytes"] > resources["host_index_payload_bytes"]
        and resources["retained_world_node_pair_count"] == 0
        and rebuilt_gpu["execution_info"]["active_pair_payload_capacity_bytes"] == 8,
        "rebuild peaks and separated FIFO accounting")
    deferred_scenario = replace(scenario, manifest=replace(scenario.manifest, max_search_expansions=1))
    deferred_baseline, deferred_cpu_points = _mission(deferred_scenario, "cpu")
    deferred_cpu, _ = _mission(deferred_scenario, "cpu", rebuild=True)
    deferred_gpu, deferred_gpu_points = _mission(deferred_scenario, "gpu", rebuild=True)
    checks["DEFER_cursor_survives_rebuild_and_preserves_full_history"] = _check(
        deferred_baseline["archive"] == deferred_cpu["archive"] == deferred_gpu["archive"]
        and any(row["search_pending"] for row in deferred_gpu["rebuilds"])
        and deferred_cpu_points[2]["expected"]["status"] == "SEARCH_DEFERRED", "deferred search")
    fifo = {backend: _fifo_rebuild_probe(backend) for backend in ("cpu", "gpu")}
    checks["FIFO_eviction_regenerates_across_index_versions"] = _check(
        all(all(result["checks"].values()) for result in fifo.values()), "FIFO across versions")
    fallback = _no_cpu_compiler_mission(scenario)
    checks["GPU_constructor_rebuild_actions_without_CPU_compilers"] = _check(
        fallback["archive"] == archive, "GPU execution without CPU compilation")

    replays = {}
    with TemporaryDirectory(prefix="psi-f8-conformance-") as temporary:
        directory = Path(temporary)
        for prefix, replay_scenario, source_cpu, source_gpu, cycle, expected in (
                ("before-seam", scenario, baseline_checkpoints, gpu_checkpoints, 1, archive),
                ("deferred-search", deferred_scenario, deferred_cpu_points, deferred_gpu_points,
                 2, deferred_baseline["archive"])):
            for source, target, checkpoint in (("cpu", "gpu", source_cpu[cycle]),
                                               ("gpu", "cpu", source_gpu[cycle])):
                label = f"{prefix}-{source}-to-{target}"
                result = _fresh_replay(directory, label, replay_scenario, checkpoint, target)
                _check(result["archive"] == expected, label)
                _check(result["envelope_keys"] == ["agent", "format", "scenario"], "unchanged session schema")
                replays[label] = {"source_backend": source, "target_backend": target,
                                  "checkpoint_cycle": cycle, **result}
        live = _live_probe(directory / "live.json", scenario)
    checks["fresh_process_cross_backend_replay_pre_seam_and_DEFER"] = len(replays) == 4
    checks["live_retry_new_index_and_backend_admits_no_duplicate_action"] = _check(
        all(live["checks"].values()) and live["archive"] == archive, "live replay equality")
    checks["index_versions_remain_deployment_metadata"] = _check(
        set(archive) == set(prior["reference_cpu"]["archive"])
        and all("index" not in event and "index_binding" not in event for event in archive["events"])
        and live["retained_envelope_keys"] == ["agent", "config", "format"], "canonical schema")
    _check(all(checks.values()), "all recorded checks")
    return {"format": "psi-f8-conformance-v1", "formal_binding": "TK-LPLUT-2.0 revision 3, PX1-PX8",
            "checks": checks, "mission_cycle_bound": MAX_CYCLES, "cpu_index": cpu,
            "elapsed_seconds": round(perf_counter() - started, 3),
            "gpu_domains": gpu_domains, "scenario": scenario.to_dict(), "baseline": baseline,
            "rebuilt_cpu": rebuilt_cpu, "rebuilt_gpu": rebuilt_gpu,
            "deferred_search": {"baseline": deferred_baseline, "cpu": deferred_cpu, "gpu": deferred_gpu},
            "fifo": fifo, "no_CPU_compiler_mission": fallback,
            "fresh_process_replays": replays, "live": live, "canonical_archive_sha256": _sha(archive),
            "prior_conformance_sha256": hashlib.sha256(PRIOR_CONFORMANCE.read_bytes()).hexdigest(),
            "scope": "Exact local SDF eigen-axes and canonical finite f8 storage for the same field agent. "
                     "Index keys, tree rows and versions do not change physical adjacency or admitted history. "
                     "No global eigenmode, Hadamard routing, geometry growth, indefinite epochs, physical "
                     "adapter or hardware performance improvement is established."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/psi-f8/conformance.json")
    args = parser.parse_args()
    report = demonstrate()
    write_json(args.output, report)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "checks_passed": sum(report["checks"].values()),
                      "CPU_domains": report["cpu_index"]["domain_count"],
                      "GPU_domains": len(report["gpu_domains"]),
                      "GPU_lookup_materializations": sum(len(row["lookups"]) for row in report["gpu_domains"]),
                      "elapsed_seconds": report["elapsed_seconds"],
                      "canonical_archive_sha256": report["canonical_archive_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
