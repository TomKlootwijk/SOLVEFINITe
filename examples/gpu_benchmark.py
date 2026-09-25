"""Measure a resident packed world and compare every derived node with the CPU.

Run from the repository root: python -m examples.gpu_benchmark --depth 16
This is one world's derivation workload, not a population of autonomous agents.
"""

import argparse
import json
from time import perf_counter

from solvefinite.gpu import GpuExecutor
from solvefinite.runtime import write_json
from solvefinite.world import World, WorldConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=16, choices=range(1, 21))
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", default="output/gpu/benchmark.json")
    args = parser.parse_args()
    config = WorldConfig(max_depth=args.depth)
    paths = tuple(format(index, f"0{args.depth}b") for index in range(1 << args.depth))
    with GpuExecutor(config, paths) as gpu:
        report = gpu.benchmark(args.repeats)
        oracle = World(config, 1)
        started = perf_counter()
        identical = all(oracle.derive(path) == node for path, node in zip(paths, gpu.nodes))
        report.update({
            "profile": "binary-organogram-v1", "depth": args.depth,
            "cpu_all_nodes_bit_exact": identical,
            "cpu_single_sweep_validation_wall_seconds": perf_counter() - started,
            "scope": "Packed world derivation only; CPU validation is not an optimized native CPU performance baseline.",
        })
        if not identical:
            raise ValueError("GPU world differs from the CPU oracle")
    write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
