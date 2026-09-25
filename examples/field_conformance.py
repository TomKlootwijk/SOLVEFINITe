"""Reproduce exact intrinsic fields, GPU transitions, and cross-adapter replay.

Run from the repository root: python -m examples.field_conformance
"""

import argparse
import json

from solvefinite.field import FieldMachine, FieldManifest, certify_field
from solvefinite.runtime import write_json


def demonstrate():
    owners = []

    def own(machine):
        owners.append(machine)
        return machine

    try:
        cpu = own(FieldMachine())
        gpu = own(FieldMachine(backend="gpu"))
        certify_field(cpu.manifest, gpu.fields)
        cpu_trace = cpu.advance(64)
        gpu_trace = gpu.advance(64)
        split = own(FieldMachine(backend="gpu"))
        split.advance(17)
        split.advance(47)
        replay = own(FieldMachine.from_archive(gpu.archive(), backend="cpu"))
        altered = FieldManifest().to_dict()
        altered["signs"] = [-1, -1, -1, -1, 0, 1, 1]
        shifted_cpu = own(FieldMachine(FieldManifest.from_dict(altered)))
        shifted_gpu = own(FieldMachine(FieldManifest.from_dict(altered), backend="gpu"))
        shifted_cpu.advance(64)
        shifted_gpu.advance(64)
        checks = {
            "default_exact_field": cpu.fields == (-6, -4, -3, 0, 2, 3, 5),
            "cpu_gpu_field_equal": cpu.fields == gpu.fields,
            "cpu_gpu_tick_trace_equal": cpu_trace == gpu_trace,
            "split_gpu_batches_equal": split.archive() == gpu.archive(),
            "gpu_archive_replayed_by_cpu": replay.archive() == gpu.archive(),
            "shifted_boundary_changes_field": shifted_cpu.fields == (-8, -6, -5, -2, 0, 1, 3),
            "shifted_boundary_changes_execution": shifted_cpu.agent_pair != cpu.agent_pair,
            "shifted_boundary_cpu_gpu_equal": shifted_cpu.archive() == shifted_gpu.archive(),
        }
        if not all(checks.values()):
            raise ValueError(f"Field conformance failed: {checks}")
        return {"profile": "relational-sdf-v1", "checks": checks,
                "ticks_per_trace": 64, "field": list(cpu.fields),
                "shifted_field": list(shifted_cpu.fields),
                "state": gpu.snapshot(), "execution_info": gpu.execution_info,
                "scope": "Exact finite intrinsic graph fields and packed execution; no hardware performance or continuous-geometry claim."}
    finally:
        for machine in reversed(owners):
            machine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/field/conformance.json")
    args = parser.parse_args()
    report = demonstrate()
    write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
