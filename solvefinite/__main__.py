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
    field_parser = commands.add_parser("field", help="Execute intrinsic signed-distance operators")
    field_commands = field_parser.add_subparsers(dest="field_command", required=True)
    field_run = field_commands.add_parser("run", help="Advance one persistent field machine")
    field_run.add_argument("--state", type=Path, default=Path("output/field/session.json"))
    field_run.add_argument("--steps", type=int, default=32)
    field_run.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    field_run.add_argument("--manifest", type=Path)
    field_inspect = field_commands.add_parser("inspect", help="Reconstruct and verify a field archive")
    field_inspect.add_argument("state", type=Path)
    field_inspect.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    field_manifest = field_commands.add_parser("manifest", help="Export the default intrinsic waveguide")
    field_manifest.add_argument("--output", type=Path, required=True)
    field_klein = field_commands.add_parser("klein", help="Generate and audit a Klein field manifest")
    field_klein.add_argument("--output", type=Path, required=True)
    field_klein.add_argument("--width", type=int, default=8)
    field_klein.add_argument("--height", type=int, default=8)
    field_klein.add_argument("--center", type=int, default=0, help="Intrinsic ball center node index")
    field_klein.add_argument("--radius", type=int, default=2, help="Intrinsic ball radius in edge steps")
    field_klein.add_argument("--initial-node", type=int, default=0)
    field_klein.add_argument("--initial-phase", type=int, default=250)
    field_klein.add_argument("--initial-orientation", type=int, default=0)
    field_klein.add_argument("--max-ticks", type=int, default=65536)
    agent_parser = commands.add_parser("agent", help="Operate the persistent TOMIGIDt single agent")
    agent_commands = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_run = agent_commands.add_parser("run", help="Sense, plan and act; resume the existing state if present")
    agent_run.add_argument("--state", type=Path, default=Path("output/tomigidt/session.json"))
    agent_run.add_argument("--steps", type=int, default=64, help="Maximum autonomous cycles for this invocation")
    agent_run.add_argument("--capacity", type=int, default=2, help="Active world cache capacity in pairs")
    agent_run.add_argument("--scenario", type=Path, help="Versioned simulated environment; must match on resume")
    agent_run.add_argument("--backend", choices=("cpu", "gpu"), default="cpu",
                           help="Execution adapter; GPU requires the optional wgpu dependency")
    agent_inspect = agent_commands.add_parser("inspect", help="Replay and inspect a retained agent session")
    agent_inspect.add_argument("state", type=Path)
    agent_inspect.add_argument("--capacity", type=int, default=2)
    agent_inspect.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    agent_scenario = agent_commands.add_parser("scenario", help="Write the default simulated environment")
    agent_scenario.add_argument("--output", type=Path, required=True)
    agent_scenario.add_argument("--profile", choices=("binary", "field", "hadamard", "growth", "organogram"), default="binary")
    agent_serve = agent_commands.add_parser("serve", help="Keep one agent ready for live JSON-line sensor input")
    agent_serve.add_argument("--state", type=Path, default=Path("output/tomigidt/live.json"))
    agent_serve.add_argument("--capacity", type=int, default=2)
    agent_serve.add_argument("--config", type=Path, help="Live sensor identity and agent configuration; must match on resume")
    agent_serve.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    agent_live_config = agent_commands.add_parser("live-config", help="Write the default live agent configuration")
    agent_live_config.add_argument("--output", type=Path, required=True)
    agent_live_config.add_argument("--profile", choices=("binary", "field", "hadamard", "growth", "organogram"), default="binary")
    agent_live_inspect = agent_commands.add_parser("live-inspect", help="Replay and inspect a retained live agent session")
    agent_live_inspect.add_argument("state", type=Path)
    agent_live_inspect.add_argument("--capacity", type=int, default=2)
    agent_live_inspect.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    agent_welip = agent_commands.add_parser("welip", help="Own one forward-only W field-agent JSONL endpoint")
    agent_welip.add_argument("--state", type=Path, default=Path("output/welip/session.json"))
    agent_welip.add_argument("--config", type=Path, help="Immutable W configuration; must match on resume")
    agent_welip.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    agent_welip_config = agent_commands.add_parser("welip-config", help="Write a W field-agent configuration")
    agent_welip_config.add_argument("--output", type=Path, required=True)
    agent_welip_config.add_argument("--profile", choices=("field", "hadamard", "growth", "organogram"),
                                    default="organogram")
    agent_welip_config.add_argument("--producer", default="sensor")
    agent_welip_config.add_argument("--producer-epoch", type=int, default=0)
    agent_welip_config.add_argument("--clock-origin", type=int, default=0)
    agent_welip_config.add_argument("--max-events", type=int, default=1000000)
    agent_welip_config.add_argument("--initial-capacity", type=int, default=2)
    for deployment in (agent_run, agent_inspect, agent_serve, agent_live_inspect, agent_welip):
        deployment.add_argument("--index-epoch", type=int, help="Field index version epoch; semantic history is unchanged")
        deployment.add_argument("--index-sign", type=int, choices=(-1, 1), help="Field index eigenvector sign")
        deployment.add_argument("--index-phase-origin", type=int, help="Field index derivation phase in 0..255")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = demo(args.output)
        elif args.command == "replay":
            result = replay(args.journal, args.capacity, args.resume, args.output)
        elif args.command == "field":
            from .field_cli import inspect_field, run_field_session
            from .field import FieldManifest
            if args.field_command == "run":
                result = run_field_session(args.state, steps=args.steps, backend=args.backend,
                                           manifest_path=args.manifest)
            elif args.field_command == "inspect":
                result = inspect_field(args.state, backend=args.backend)
            elif args.field_command == "klein":
                from .klein import KleinDomain
                domain = KleinDomain(args.width, args.height)
                manifest = domain.field_manifest(
                    center=args.center, radius=args.radius, initial_node=args.initial_node,
                    initial_phase=args.initial_phase, initial_orientation=args.initial_orientation,
                    max_ticks=args.max_ticks)
                audit = domain.audit()
                write_json(args.output, manifest.to_dict())
                result = {"manifest": str(args.output.resolve()), "profile": manifest.profile,
                          "topology_audit": audit}
            else:
                manifest = FieldManifest()
                write_json(args.output, manifest.to_dict())
                result = {"manifest": str(args.output.resolve()), "profile": manifest.profile}
        else:
            from .session import Scenario, load_session, run_session
            from .field_agent import FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY
            options = {"backend": getattr(args, "backend", "cpu")}
            index_values = tuple(getattr(args, name, None) for name in
                                 ("index_epoch", "index_sign", "index_phase_origin"))
            if any(value is not None for value in index_values):
                from .f8 import IndexBinding
                epoch, sign, origin = index_values
                options["index_binding"] = IndexBinding(
                    epoch=0 if epoch is None else epoch,
                    psi_sign=1 if sign is None else sign,
                    phase_origin=0 if origin is None else origin)
            if args.agent_command == "run":
                result = run_session(args.state, steps=args.steps, capacity=args.capacity,
                                     scenario_path=args.scenario, **options)
            elif args.agent_command == "inspect":
                _, agent = load_session(args.state, capacity=args.capacity, **options)
                try:
                    result = {"verified": True, "state": agent.snapshot(),
                              "state_path": str(args.state.resolve()), "event_count": len(agent.events)}
                    if args.backend == "gpu" or agent.manifest.policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
                        result["execution_info"] = agent.execution_info
                finally:
                    agent.close()
            elif args.agent_command == "scenario":
                if args.profile in ("field", "hadamard", "growth", "organogram"):
                    from .field_agent import FieldAgentManifest
                    policy = {"field": FIELD_POLICY, "hadamard": HADAMARD_POLICY,
                              "growth": GROWTH_POLICY, "organogram": ORGANOGRAM_POLICY}[args.profile]
                    scenario = Scenario(FieldAgentManifest(policy=policy), changes=((2, "k:0:3", 70),))
                else:
                    scenario = Scenario()
                write_json(args.output, scenario.to_dict())
                result = {"scenario": str(args.output.resolve()), "identity": scenario.manifest.identity}
            elif args.agent_command == "serve":
                from .live import serve
                serve(args.state, capacity=args.capacity, config_path=args.config, **options)
                return 0
            elif args.agent_command == "welip":
                from .welip_session import serve
                serve(args.state, config_path=args.config, **options)
                return 0
            elif args.agent_command == "welip-config":
                from .field_agent import FieldAgentManifest
                from .welip import WelipConfig
                policy = {"field": FIELD_POLICY, "hadamard": HADAMARD_POLICY,
                          "growth": GROWTH_POLICY, "organogram": ORGANOGRAM_POLICY}[args.profile]
                config = WelipConfig(
                    manifest=FieldAgentManifest(policy=policy), producer=args.producer,
                    producer_epoch=args.producer_epoch, clock_origin=args.clock_origin,
                    max_events=args.max_events, initial_capacity=args.initial_capacity)
                write_json(args.output, config.to_dict())
                result = {"config": str(args.output.resolve()), "identity": config.manifest.identity}
            elif args.agent_command == "live-config":
                from .live import LiveConfig
                if args.profile in ("field", "hadamard", "growth", "organogram"):
                    from .field_agent import FieldAgentManifest
                    policy = {"field": FIELD_POLICY, "hadamard": HADAMARD_POLICY,
                              "growth": GROWTH_POLICY, "organogram": ORGANOGRAM_POLICY}[args.profile]
                    config = LiveConfig(FieldAgentManifest(policy=policy))
                else:
                    config = LiveConfig()
                write_json(args.output, config.to_dict())
                result = {"config": str(args.output.resolve()), "identity": config.manifest.identity}
            else:
                from .live import load_live
                config, agent = load_live(args.state, capacity=args.capacity, **options)
                try:
                    result = {"verified": True, "state": agent.snapshot(),
                              "state_path": str(args.state.resolve()),
                              "event_count": len(agent.events),
                              "producer": config.producer, "epoch": config.epoch}
                    if args.backend == "gpu" or agent.manifest.policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
                        result["execution_info"] = agent.execution_info
                finally:
                    agent.close()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"solvefinite: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
