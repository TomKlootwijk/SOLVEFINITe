"""Run the colony experiment or reconstruct a saved journal in a fresh process."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .rp32 import unpack, unpair
from .runtime import Runtime, write_json


def cache_report(runtime: Runtime) -> dict:
    return {
        "capacity_pairs": runtime.world.capacity,
        "active_paths": list(runtime.world.active_paths),
        "active_pair_payload_bytes": 8 * len(runtime.world.active_paths),
        "pair_payload_capacity_bytes": 8 * runtime.world.capacity,
        "evictions": len(runtime.world.evicted_paths),
        "regenerations_after_eviction": runtime.world.regeneration_count,
        "accounting": "Pair payload only; excludes Python objects, path keys, rules, journal and diagnostic history.",
    }


def replay(journal: Path, capacity: int, resume: bool, output: Path | None) -> dict:
    runtime = Runtime.load(journal, capacity=capacity)
    restored = runtime.snapshot()
    if resume:
        runtime.finish()
    if output is not None:
        runtime.save(output)
    return {
        "process_id": os.getpid(), "replay_verified": True,
        "restored": restored, "final": runtime.snapshot(), "cache": cache_report(runtime),
    }


def demo(output: Path) -> dict:
    output = output.resolve()
    runtime = Runtime(capacity=2)
    candidates = (("0", "00", "000"), ("1", "10", "100"))

    # These are retained synthetic observations, not purported measurements of
    # a real planet. An observation changes planning cost at a waypoint.
    for path, hazard in (("0", 40), ("1", 2), ("10", 1), ("100", 1)):
        runtime.observe(path, hazard)
    alternatives = [runtime.evaluate(route) for route in candidates]
    chosen = runtime.select_plan(candidates)

    # Materialize and then actually evict a node, retaining only its descriptor
    # for the next get. The first copy below is solely a verification witness.
    original_node = runtime.world.get("000")
    runtime.world.get("110")
    runtime.world.get("111")
    was_evicted = "000" not in runtime.world.active_paths
    regenerated_node = runtime.world.get("000")
    regeneration_matches = was_evicted and original_node == regenerated_node

    runtime.advance()
    if runtime.agent_pair != chosen.states[0]:
        raise ValueError("First actual transition differs from its imagined result")
    checkpoint = output / "checkpoint.json"
    recovered_file = output / "recovered.json"
    runtime.save(checkpoint)
    interrupted_state = runtime.snapshot()

    # The worker receives only the archive filename. It cannot access this
    # process's live objects or cache. The parent continues as a control run.
    completed = subprocess.run(
        [sys.executable, "-m", "solvefinite", "replay", str(checkpoint),
         "--capacity", "1", "--resume", "--output", str(recovered_file)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if completed.returncode:
        raise ValueError(f"Recovery worker failed: {completed.stderr.strip()}")
    worker = json.loads(completed.stdout)

    for expected_pair in chosen.states[1:]:
        runtime.advance()
        if runtime.agent_pair != expected_pair:
            raise ValueError("Actual transition differs from its imagined result")
    runtime.repair()
    reconstructed = Runtime.load(recovered_file, capacity=8)
    control_matches = reconstructed.archive() == runtime.archive()
    initial_replay_matches = worker["restored"] == interrupted_state
    separate_process = worker["process_id"] != os.getpid()
    if not all((regeneration_matches, control_matches, initial_replay_matches, separate_process)):
        raise ValueError("The demonstration failed a reconstruction invariant")

    report = {
        "experiment": "regenerating-colony-agent-v1",
        "story": "An interrupted agent reconstructs its state in a fresh process and finishes a selected repair plan.",
        "checks": {
            "evicted_node_reconstructed_exactly": regeneration_matches,
            "imagined_and_executed_movement_match": True,
            "fresh_process_replayed_checkpoint_exactly": initial_replay_matches,
            "resumed_and_uninterrupted_journals_match": control_matches,
            "worker_is_a_separate_process": separate_process,
        },
        "candidate_plans": [plan.to_dict() for plan in alternatives],
        "chosen_route": list(chosen.route),
        "checkpoint": interrupted_state,
        "completed": runtime.snapshot(),
        "remaining_energy": unpack(unpair(runtime.agent_pair)[0])[2],
        "control_cache": cache_report(runtime),
        "recovered_cache": worker["cache"],
        "retained_checkpoint_bytes": checkpoint.stat().st_size,
        "retained_completed_journal_bytes": recovered_file.stat().st_size,
        "artifacts": {"checkpoint": str(checkpoint), "recovered": str(recovered_file),
                      "report": str(output / "report.json")},
        "scope": "Synthetic routes and observations; fresh-process recovery, not a hardware replacement or performance benchmark.",
    }
    write_json(output / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="Compare plans, evict state, interrupt and resume an agent")
    demo_parser.add_argument("--output", type=Path, default=Path("output/demo"))
    replay_parser = commands.add_parser("replay", help="Rebuild a journal from its original rules and events")
    replay_parser.add_argument("journal", type=Path)
    replay_parser.add_argument("--capacity", type=int, default=2)
    replay_parser.add_argument("--resume", action="store_true", help="Finish the retained plan after replay")
    replay_parser.add_argument("--output", type=Path, help="Save the resulting journal")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = demo(args.output)
        else:
            result = replay(args.journal, args.capacity, args.resume, args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"solvefinite: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
