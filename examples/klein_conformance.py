"""Reproduce finite Klein geometry, seam transport, and actual GPU agreement.

Run from the repository root: python -m examples.klein_conformance
Requires the optional pinned GPU dependencies and a supported hardware GPU.
Every execution is bounded to 64 ticks; no CPU fallback substitutes for GPU
fields, operators, or transitions.
"""

import argparse
from collections import deque
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

from solvefinite.field import (
    FieldMachine, FieldManifest, build_operators, certify_field, evaluate_field,
)
from solvefinite.klein import KleinDomain
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
TICKS = 64
SPLIT = 17


def _distances(vertex_count, edges, sources):
    """Independent unit-edge BFS, including on the full orientation cover."""
    neighbors = [[] for _ in range(vertex_count)]
    for left, right, weight in edges:
        if weight != 1:
            raise ValueError("This evidence oracle requires unit edges")
        neighbors[left].append(right)
        neighbors[right].append(left)
    distances = [None] * vertex_count
    pending = deque(sources)
    for source in pending:
        distances[source] = 0
    while pending:
        source = pending.popleft()
        for destination in neighbors[source]:
            if distances[destination] is None:
                distances[destination] = distances[source] + 1
                pending.append(destination)
    if None in distances:
        raise ValueError("Evidence graph is disconnected")
    return tuple(distances)


def _gpu_operators(executor):
    """Read the actual integer operator texture through a diagnostic shader.

    The runtime texture intentionally lacks COPY_SRC usage. This read-only
    probe uses its existing texture binding and an owned temporary buffer;
    it neither recompiles operators nor changes the execution state.
    """
    device = executor._device
    count = len(executor.fields)
    usage = executor._wgpu.BufferUsage
    output = device.create_buffer(size=12 * count, usage=usage.STORAGE | usage.COPY_SRC)
    try:
        shader = device.create_shader_module(code="""
            @group(0) @binding(0) var operators: texture_2d<u32>;
            @group(0) @binding(1) var<storage, read_write> words: array<u32>;
            @compute @workgroup_size(64)
            fn read_operators(@builtin(global_invocation_id) invocation: vec3<u32>) {
                let size = textureDimensions(operators);
                let index = invocation.x;
                if (index >= size.x * size.y) { return; }
                words[index] = textureLoad(operators,
                    vec2<i32>(i32(index % size.x), i32(index / size.x)), 0).r;
            }
        """)
        pipeline = device.create_compute_pipeline(
            layout="auto", compute={"module": shader, "entry_point": "read_operators"},
        )
        group = device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": executor._texture.create_view()},
                     {"binding": 1, "resource": {"buffer": output, "offset": 0,
                                                 "size": output.size}}],
        )
        encoder = device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(pipeline)
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups((3 * count + 63) // 64)
        compute.end()
        device.queue.submit([encoder.finish()])
        words = struct.unpack(f"<{3 * count}I", device.queue.read_buffer(output))
        return tuple(tuple(words[index:index + 3]) for index in range(0, len(words), 3))
    finally:
        output.destroy()


def _transport_trace(manifest, fields, ticks):
    """Compute K8 directly from immutable rules and geometric seam membership."""
    node, phase, eta = manifest.initial_node, manifest.initial_phase, manifest.initial_orientation
    seams = set(manifest.seams)
    result = []
    for _ in range(ticks):
        signed = fields[node]
        column = 0 if signed < 0 else 1 if signed == 0 else 2
        destination = manifest.routes[node][column]
        tau = int((min(node, destination), max(node, destination)) in seams)
        phase = (phase + (-1 if eta else 1) * manifest.turns[node][column]) % 256
        phase = (-phase if tau else phase) % 256
        eta ^= tau
        result.append(pair(pack(phase, destination, fields[destination],
                                int(Opcode.STEP) | (eta << 4))))
        node = destination
    return tuple(result)


def _seam_events(manifest, initial, trace):
    events = []
    previous = initial
    seams = set(manifest.seams)
    for tick, current in enumerate(trace, 1):
        r, source, signed, metadata = unpack(unpair(previous)[0])
        next_r, destination, next_signed, next_metadata = unpack(unpair(current)[0])
        if (min(source, destination), max(source, destination)) in seams:
            column = 0 if signed < 0 else 1 if signed == 0 else 2
            turn = manifest.turns[source][column]
            eta = (metadata >> 4) & 1
            departure_phase = (r + (-1 if eta else 1) * turn) % 256
            events.append({
                "tick": tick, "source": source, "destination": destination,
                "source_name": manifest.nodes[source],
                "destination_name": manifest.nodes[destination],
                "phase_before": r, "turn": turn,
                "phase_before_transport": departure_phase, "phase_after": next_r,
                "orientation_before": eta, "orientation_after": (next_metadata >> 4) & 1,
                "field_before": signed, "field_after": next_signed,
                "pair": f"{current:016X}",
            })
        previous = current
    return events


def _fresh_replay(archive, backend, steps):
    code = """
import json, sys
from solvefinite.field import FieldMachine
machine = FieldMachine.from_archive(json.load(sys.stdin), backend=sys.argv[1])
try:
    machine.advance(int(sys.argv[2]))
    print(json.dumps({"archive": machine.archive(), "execution_info": machine.execution_info}))
finally:
    machine.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, backend, str(steps)], cwd=ROOT,
        input=json.dumps(archive), text=True, capture_output=True, timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(f"Fresh-process {backend} replay failed: {completed.stderr}")
    return json.loads(completed.stdout)


def _rejects_archive(archive):
    try:
        machine = FieldMachine.from_archive(archive)
    except ValueError:
        return True
    machine.close()
    return False


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def demonstrate():
    owners = []

    def own(machine):
        owners.append(machine)
        return machine

    try:
        sizes = tuple((width, height) for width in range(3, 86)
                      for height in range(3, 256 // width + 1))
        audits = [KleinDomain(width, height).audit() for width, height in sizes]
        representative_sizes = {(3, 3), (3, 4), (4, 3), (8, 5), (8, 8), (16, 16)}
        domain = KleinDomain()
        manifest = domain.field_manifest(max_ticks=TICKS)
        cpu = own(FieldMachine(manifest))
        gpu = own(FieldMachine(manifest, backend="gpu"))
        certify_field(manifest, gpu.fields)
        cpu_operators = build_operators(manifest, cpu.fields)
        gpu_operators = _gpu_operators(gpu._executor)
        boundary = tuple(node for node, sign in enumerate(manifest.signs) if sign == 0)
        base_distances = _distances(len(domain.nodes), domain.edges, boundary)
        expected_fields = tuple(sign * distance for sign, distance
                                in zip(manifest.signs, base_distances))
        cover_boundary = tuple(2 * node + eta for node in boundary for eta in (0, 1))
        cover_distances = _distances(2 * len(domain.nodes), domain.cover_edges, cover_boundary)
        cover_fields = tuple(manifest.signs[node // 2] * distance
                             for node, distance in enumerate(cover_distances))
        initial = gpu.agent_pair
        cpu_trace = cpu.advance(TICKS)
        gpu_trace = gpu.advance(TICKS)
        expected_trace = _transport_trace(manifest, expected_fields, TICKS)
        seam_events = _seam_events(manifest, initial, gpu_trace)

        mirrored_manifest = replace(
            manifest, initial_phase=(-manifest.initial_phase) % 256,
            initial_orientation=manifest.initial_orientation ^ 1,
        )
        mirrored_cpu = own(FieldMachine(mirrored_manifest))
        mirrored_gpu = own(FieldMachine(mirrored_manifest, backend="gpu"))
        mirror_initial = mirrored_gpu.agent_pair
        mirrored_cpu_trace = mirrored_cpu.advance(TICKS)
        mirrored_gpu_trace = mirrored_gpu.advance(TICKS)

        split_cpu = own(FieldMachine(manifest))
        split_gpu = own(FieldMachine(manifest, backend="gpu"))
        split_cpu.advance(SPLIT)
        split_gpu.advance(SPLIT)
        cpu_checkpoint, gpu_checkpoint = split_cpu.archive(), split_gpu.archive()
        split_cpu.advance(TICKS - SPLIT)
        split_gpu.advance(TICKS - SPLIT)
        cpu_from_gpu = own(FieldMachine.from_archive(gpu_checkpoint, backend="cpu"))
        gpu_from_cpu = own(FieldMachine.from_archive(cpu_checkpoint, backend="gpu"))
        cpu_from_gpu.advance(TICKS - SPLIT)
        gpu_from_cpu.advance(TICKS - SPLIT)
        fresh_cpu = _fresh_replay(gpu_checkpoint, "cpu", TICKS - SPLIT)
        fresh_gpu = _fresh_replay(cpu_checkpoint, "gpu", TICKS - SPLIT)

        retained = FieldManifest.from_dict(manifest.to_dict())
        regenerated = KleinDomain(*retained.topology)
        changed_edges = deepcopy(gpu_checkpoint)
        changed_edges["manifest"]["edges"][0][2] = 2
        changed_seams = deepcopy(gpu_checkpoint)
        changed_seams["manifest"]["seams"].pop()

        # A concrete case distinguishes exact boundary distance from d(c,v)-R.
        example_domain = KleinDomain(4, 3)
        example_manifest = example_domain.field_manifest(center=1, radius=3)
        example_fields = evaluate_field(example_manifest)
        radial = _distances(12, example_domain.edges, (1,))
        naive = tuple(distance - 3 for distance in radial)

        checks = {
            "audited_closed_nonorientable_bases": all(
                audit["base"]["closed"] and audit["base"]["connected"]
                and audit["base"]["vertex_links"] and not audit["base"]["orientable"]
                and audit["base"]["euler_characteristic"] == 0 for audit in audits),
            "audited_connected_orientable_covers": all(
                audit["cover"]["closed"] and audit["cover"]["connected"]
                and audit["cover"]["vertex_links"] and audit["cover"]["orientable"]
                and audit["cover"]["euler_characteristic"] == 0 for audit in audits),
            "complete_torus_edge_and_face_correspondence": all(
                audit["toroidal_cover_edges"] and audit["toroidal_cover_faces"]
                for audit in audits),
            "cocycle_and_loop_holonomy": all(
                audit["seam_cocycle"] and audit["holonomy"] == {
                    "horizontal": 1, "double_horizontal": 0, "vertical": 0}
                for audit in audits),
            "cpu_gpu_exact_scalar_fields": cpu.fields == gpu.fields == expected_fields,
            "scalar_pullback_matches_cover_boundary_distances": cover_fields == tuple(
                value for value in expected_fields for _ in (0, 1)),
            "exact_distance_differs_from_naive_radial_offset": example_fields != naive,
            "actual_gpu_operator_texture_matches_cpu": cpu_operators == gpu_operators,
            "cpu_gpu_trace_matches_direct_transport": cpu_trace == gpu_trace == expected_trace,
            "actual_reversing_seams_crossed": len(seam_events) == TICKS // domain.width,
            "seams_reflect_phase_and_flip_orientation": bool(seam_events) and all(
                event["phase_after"] == (-event["phase_before_transport"]) % 256
                and event["orientation_after"] == event["orientation_before"] ^ 1
                for event in seam_events),
            "mirrored_cpu_gpu_traces_equal": mirrored_cpu_trace == mirrored_gpu_trace,
            "complete_transition_commutes_with_mirror": all(
                unpair(reflected) == unpair(original)[::-1]
                for original, reflected in zip((initial, *gpu_trace),
                                               (mirror_initial, *mirrored_gpu_trace))),
            "split_cpu_batches_equal": split_cpu.archive() == cpu.archive(),
            "split_gpu_batches_equal": split_gpu.archive() == gpu.archive(),
            "gpu_checkpoint_resumed_on_cpu": cpu_from_gpu.archive() == cpu.archive(),
            "cpu_checkpoint_resumed_on_gpu": gpu_from_cpu.archive() == gpu.archive(),
            "fresh_process_gpu_to_cpu_replay": fresh_cpu["archive"] == cpu.archive(),
            "fresh_process_cpu_to_gpu_replay": fresh_gpu["archive"] == gpu.archive(),
            "retained_descriptor_regenerates_exact_geometry": (
                regenerated.nodes, regenerated.edges, regenerated.seams) == (
                    retained.nodes, retained.edges, retained.seams),
            "changed_quotient_edges_rejected_on_replay": _rejects_archive(changed_edges),
            "changed_quotient_seams_rejected_on_replay": _rejects_archive(changed_seams),
        }
        if not all(checks.values()):
            raise ValueError(f"Klein conformance failed: {checks}")
        return {
            "profile": manifest.profile, "checks": checks,
            "geometry_audit_coverage": {
                "constraints": "Strict integers W,H >= 3 and W*H <= 256",
                "admissible_dimension_pair_count": len(sizes),
                "audited_dimension_pair_count": len(audits),
                "audited_dimensions": [[audit["width"], audit["height"]] for audit in audits],
            },
            "geometry_audits": [audit for audit in audits
                                if (audit["width"], audit["height"]) in representative_sizes],
            "ticks_per_trace": TICKS, "batch_sizes": [SPLIT, TICKS - SPLIT],
            "manifest": manifest.to_dict(), "boundary_nodes": list(boundary),
            "cpu_field": list(cpu.fields), "gpu_field": list(gpu.fields),
            "cover_field": list(cover_fields),
            "boundary_distance_counterexample": {
                "width": 4, "height": 3, "center": 1, "radius": 3,
                "exact_field": list(example_fields), "radial_offset": list(naive),
            },
            "cpu_operators": [[f"{word:08X}" for word in row] for row in cpu_operators],
            "gpu_operators": [[f"{word:08X}" for word in row] for row in gpu_operators],
            "initial_pair": f"{initial:016X}",
            "cpu_trace": [f"{value:016X}" for value in cpu_trace],
            "gpu_trace": [f"{value:016X}" for value in gpu_trace],
            "mirrored_gpu_trace": [f"{value:016X}" for value in mirrored_gpu_trace],
            "seam_events": seam_events, "state": gpu.snapshot(),
            "archive_sha256": _digest(gpu.archive()),
            "execution_info": gpu.execution_info,
            "fresh_process_execution_info": {
                "gpu_to_cpu": fresh_cpu["execution_info"],
                "cpu_to_gpu": fresh_gpu["execution_info"],
            },
            "scope": "Finite quotient cells, intrinsic scalar distances, and packed CPU/GPU "
                     "execution. No physical hardware-performance, full Psi, f8, regenerative "
                     "field-world, continuous-surface, or immersion claim.",
        }
    finally:
        for machine in reversed(owners):
            machine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/klein/conformance.json")
    args = parser.parse_args()
    report = demonstrate()
    write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
