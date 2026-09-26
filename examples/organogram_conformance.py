"""Capture OG1-OG8 against the frozen independent reference and an actual GPU.

Run ``python -m examples.organogram_conformance --output output/organogram.json``.
GPU absence fails a full capture. --cpu-only is explicitly partial development.
The independent reference's mathematical prefixes are replaced by the actual
retained runtime prefix before comparing a complete derivation document.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from examples.growth_conformance import (
    canonical_hash, fifo, independent_data_pair, reindex,
    no_cpu_compilers as no_legacy_cpu_compilers,
    mission as legacy_mission,
)
from examples.hadamard_conformance import FORBIDDEN_CPU_COMPILERS
from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import (
    FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, FieldAgentManifest,
)
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.organogram import OrganogramBinding
from solvefinite.rp32 import unpack, unpair
from solvefinite.runtime import write_json
from solvefinite.session import Scenario
from solvefinite.tomigidt import Tomigidt


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "docs/evidence/organogram-v1/formal-reference.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
FORMAL_COMMIT = "5c76f2cec3a1cec8fd2d16eeeac2021c45b0aea9"
MAX_CYCLES = 2048
FORBIDDEN_OG_PRODUCERS = (
    "solvefinite.organogram.interpret_cpu", "solvefinite.organogram.regenerate",
    "solvefinite.organogram.union_signs_cpu", "solvefinite.organogram.evaluate_field",
    "solvefinite.organogram.GeneratedFieldRecipe.field_manifest",
    "solvefinite.tomigidt.regenerate",
)
_ORACLE = None


def check(condition, label):
    if type(condition) is not bool or not condition:
        raise ValueError(f"Organogram conformance failed: {label}")
    return True


def oracle():
    global _ORACLE
    if _ORACLE is None:
        spec = importlib.util.spec_from_file_location(
            "independent_OG_conformance_oracle", REFERENCE_PATH.with_name("reference-builder.py"))
        _ORACLE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ORACLE)
    return _ORACLE


def scenario_for(reference=None, **changes):
    reference = REFERENCE["default_mission"] if reference is None else reference
    initial = reference["initial"]
    recipe = KleinFieldRecipe(**{**reference["initial_recipe"],
                                "turns": tuple(reference["initial_recipe"]["turns"])})
    values = dict(policy=ORGANOGRAM_POLICY, world=recipe,
                  organogram=OrganogramBinding.from_dict(reference["binding"]),
                  initial_node=initial["path"], initial_phase=initial["phase"],
                  initial_orientation=initial["orientation"], initial_energy=initial["energy"],
                  target=f"k:{reference['initial_target']//recipe.height}:{reference['initial_target']%recipe.height}")
    values.update(changes)
    return Scenario(FieldAgentManifest(**values), changes=((2, "k:0:3", 70),))


def no_cpu_compilers():
    """Forbid producers while leaving independent certificates enabled."""
    stack = ExitStack()
    stack.enter_context(no_legacy_cpu_compilers())
    # The independent oracle lives in docs/evidence and imports no runtime.
    for name in FORBIDDEN_OG_PRODUCERS:
        stack.enter_context(patch(name,
            side_effect=AssertionError(f"Forbidden CPU organogram producer: {name}")))
    return stack


def fields(agent):
    count = agent.current_recipe.width * agent.current_recipe.height
    if agent._gpu is not None:
        return tuple(agent._gpu.fields)
    return tuple(unpack(unpair(agent.world.derive(
        f"k:{node//agent.current_recipe.height}:{node%agent.current_recipe.height}").pair)[0])[2]
        for node in range(count))


def expected_stage(agent, prior_fields):
    """Independent full trajectory using the actual original journal prefix."""
    base = agent.manifest.world
    context = {"epoch": agent.geometry_epoch + 1, "tick": agent.cycle + 1,
               "start_pair": f"{agent.agent_pair:016X}",
               "prefix_sha256": canonical_hash(agent.events)}
    world = oracle().Field(base.width, base.height, base.center, base.radius, values=prior_fields)
    return oracle().interpret(world, agent.manifest.organogram.to_dict(), context)


def assert_stage(agent, expected, old_recipe, old_pair):
    event = agent.events[-1]
    receipt = event["growth"]
    context = expected["document"]["context"]
    check(set(receipt) == {"format", "from_epoch", "to_epoch", "mapped_node", "target",
                          "recipe", "derivation_sha256"}, "exact receipt schema")
    check(receipt["format"] == "klein-organogram-growth-v1", "receipt profile")
    check(receipt["derivation_sha256"] == expected["derivation_sha256"],
          "complete independently interpreted trajectory digest")
    if agent._gpu is not None:
        check(agent._gpu.last_derivation == expected["document"], "actual complete device trajectory")
        check(agent._gpu.stage_digests[-1] == expected["derivation_sha256"], "actual device stage digest")
    recipe = agent.current_recipe.to_dict()
    check(recipe["stages"][-1] == context, "original actual stage context")
    check(recipe["base"] == agent.manifest.world.to_dict()
          and recipe["organogram"] == agent.manifest.organogram.to_dict()
          and recipe["routing"] == agent.manifest.routing.to_dict(), "immutable retained source")
    previous_stages = old_recipe.to_dict().get("stages", [])
    check(recipe["stages"][:-1] == previous_stages, "exactly one context extension")
    check(tuple(fields(agent)) == tuple(expected["union"]["field"]), "actual entire new field")
    old_r, old_g, _, old_a = unpack(unpair(old_pair)[0])
    r, g, b, a = unpack(unpair(agent.agent_pair)[0])
    check((r, g, a & 16) == (old_r, old_g, old_a & 16)
          and b == expected["union"]["field"][g] and (a & 7) == 1,
          "owner retained instead of hypothetical final cursor")
    check(receipt["mapped_node"] == agent.position, "owner position unchanged")
    next_world = oracle().Field(agent.current_recipe.width, agent.current_recipe.height,
                               values=expected["union"]["field"])
    target = oracle().target_selection(next_world, g, (-r if a & 16 else r) & 255)
    check(agent.target == target["target_path"] == receipt["target"], "independent OG target")
    check("scale_exponent" not in agent.snapshot(), "mixed branch scales are not a global scale")
    return {"context": context, "expected_derivation": expected["document"],
            "derivation_sha256": expected["derivation_sha256"],
            "field": expected["union"]["field"], "target_selection": target}


def literal(archive, snapshots, reference):
    check(len(archive["events"]) == len(reference["events"]), "literal mission length")
    check(snapshots[0]["agent_pair"] == reference["initial"]["pair"], "literal initial pair")
    for actual, state, expected in zip(archive["events"], snapshots[1:], reference["events"]):
        decision = actual["decision"]
        check((decision["kind"], decision["cost"], decision["route"], actual["output"], actual["energy"])
              == (expected["kind"], expected["cost"], expected.get("paths", []),
                  expected["state"]["pair"], expected["state"]["energy"]), "literal decision and state")
        check(actual["geometry_epoch"] == expected["input_epoch"]
              and state["geometry_epoch"] == expected["epoch"]
              and state["status"] == expected["status"], "literal stage lifecycle")
        if decision["kind"] == "MOVE":
            check((decision["expansions"], decision["forecast"])
                  == (expected["expansions"], expected["forecast"]), "independent lifted route forecast")
        if decision["kind"] != "GROW":
            check(actual["growth"] is None, "no fabricated non-growth receipt")
    return True


def historical_samples(agent, world_fields):
    before, resident, planning = agent.archive(), fifo(agent.world), agent._planning
    device = agent._gpu.snapshot() if agent._gpu is not None else None
    samples = []
    for epoch, values in enumerate(world_fields):
        origin = 0 if epoch == 0 else next(event["seq"] for event in agent.events
            if event["growth"] is not None and event["growth"]["to_epoch"] == epoch)
        for node in sorted({0, len(values)//2, len(values)-1}):
            path = f"k:{node//agent.current_recipe.height}:{node%agent.current_recipe.height}"
            sample = agent.derive_epoch(epoch, path)
            check((sample.geometry_epoch, sample.origin_sequence, sample.prefix_sha256)
                  == (epoch, origin, canonical_hash(before["events"][:origin])), "original sample prefix")
            check(f"{sample.pair:016X}" == independent_data_pair(node, values[node]), "historical DATA sample")
            samples.append(sample.to_dict())
    check((agent.archive(), fifo(agent.world), agent._planning) == (before, resident, planning),
          "historical regeneration preserves current owner and FIFO")
    check(device == (agent._gpu.snapshot() if agent._gpu is not None else None), "historical device isolation")
    return samples


def mission(scenario, backend, *, reference=None, rebuild=False, capacity=1, binding=None):
    agent = Tomigidt(scenario.manifest, capacity, backend=backend, index_binding=binding)
    guards = ExitStack()
    try:
        if backend == "gpu":
            guards.enter_context(patch("solvefinite.field_agent_gpu.GpuFieldAgentExecutor.seed",
                side_effect=AssertionError("Host seed after initial construction")))
        snapshots, device_states, rebuilds, stages, checkpoints = [], [], [], [], {}
        world_fields = [list(fields(agent))]
        while True:
            snapshot = agent.snapshot(); snapshots.append(snapshot)
            if agent._gpu is not None:
                pair, energy = agent._gpu.snapshot()
                check((pair, energy) == (agent.agent_pair, agent.energy), "persistent actual device owner")
                device_states.append({"cycle": agent.cycle, "pair": f"{pair:016X}", "energy": energy})
            if agent.status == "GROWTH_PENDING":
                checkpoints[f"before_growth_{agent.geometry_epoch+1}"] = agent.archive()
            if agent._planning is not None:
                checkpoints.setdefault("DEFER_after_growth" if agent.geometry_epoch else "DEFER_before_growth",
                                       agent.archive())
            if agent.status == "COMPLETE":
                break
            check(agent.cycle < MAX_CYCLES, "bounded mission")
            if rebuild:
                rebuilds.append(reindex(agent))
            old_recipe, old_pair, old_info = agent.current_recipe, agent.agent_pair, agent.execution_info
            expected = expected_stage(agent, world_fields[-1]) if agent.status == "GROWTH_PENDING" else None
            decision = agent.step(scenario.observe(agent.position, agent.cycle+1, geometry_epoch=agent.geometry_epoch))
            if decision.kind == "GROW":
                stages.append(assert_stage(agent, expected, old_recipe, old_pair))
                world_fields.append(list(expected["union"]["field"]))
                check(agent.world.active_paths == () and agent.snapshot()["observations"] == {}
                      and agent._planning is None, "semantic context cleared")
                check(agent.current_recipe.width == old_recipe.width
                      and agent.current_recipe.height == old_recipe.height, "topology dimensions preserved")
                checkpoints[f"after_growth_{agent.geometry_epoch}"] = agent.archive()
                # Actual payload accounting is retained, not interpreted as a
                # claim about Python objects or a physical energy measurement.
                stages[-1]["old_execution_info"] = old_info
                stages[-1]["new_execution_info"] = agent.execution_info
        archive = agent.archive()
        if reference is not None:
            literal(archive, snapshots, reference)
            check(world_fields == [world["field"] for world in reference["worlds"]], "all literal world fields")
        history = historical_samples(agent, world_fields)
        return {"archive": archive, "archive_sha256": canonical_hash(archive), "snapshots": snapshots,
                "actual_device_states": device_states, "rebuilds": rebuilds, "stages": stages,
                "world_fields": world_fields, "historical_samples": history, "checkpoints": checkpoints,
                "execution_info": agent.execution_info, "FIFO": fifo(agent.world)}
    finally:
        guards.close(); agent.close()


def cpu_conformance():
    cases = {label: mission(scenario_for(REFERENCE[label+"_mission"]), "cpu",
                           reference=REFERENCE[label+"_mission"])
             for label in ("default", "mirrored_default", "two_epoch", "zero_epoch")}
    scenario = scenario_for()
    rebuilt = mission(scenario, "cpu", rebuild=True, capacity=32, binding=IndexBinding(11, -1, 201))
    check(rebuilt["archive"] == cases["default"]["archive"], "CPU cache and index transparency")
    deferred_scenario = replace(scenario, manifest=replace(scenario.manifest, max_search_expansions=7))
    deferred = mission(deferred_scenario, "cpu", rebuild=True)
    control = mission(deferred_scenario, "cpu", capacity=32)
    check(deferred["archive"] == control["archive"] and "DEFER_after_growth" in deferred["checkpoints"],
          "same quantum retained search and replay")
    check(deferred["stages"][0]["context"]["tick"] != cases["default"]["stages"][0]["context"]["tick"],
          "planning quantum is retained semantic time input")
    check(deferred["stages"][0]["expected_derivation"]["tape"]
          != cases["default"]["stages"][0]["expected_derivation"]["tape"], "time-sensitive production exercised")
    retained = json.loads((ROOT / "docs/evidence/growth-v1/verification.json").read_text())
    hp = json.loads((ROOT / "docs/evidence/hadamard-v1/verification.json").read_text())
    legacy = {}
    for policy, name, digest in ((FIELD_POLICY, "field", hp["legacy_field_archive_sha256"]),
                                (HADAMARD_POLICY, "hadamard", hp["canonical_archive_sha256"]),
                                (GROWTH_POLICY, "growth", retained["canonical_archive_sha256"])):
        value = legacy_mission(Scenario(FieldAgentManifest(policy=policy), changes=((2,"k:0:3",70),)), "cpu")
        check(value["archive_sha256"] == digest, f"legacy {name} canonical archive")
        legacy[name] = {"archive": value["archive"], "archive_sha256": digest}
    return {"cases": cases, "rebuilt": rebuilt, "deferred": deferred,
            "deferred_scenario": deferred_scenario.to_dict(), "legacy": legacy}


def fresh_replay(folder, label, scenario, archive, backend):
    path = folder / f"{label}.json"
    write_json(path, {"scenario": scenario.to_dict(), "agent": archive})
    script = '''
from contextlib import nullcontext
import json,sys
from examples.organogram_conformance import no_cpu_compilers,canonical_hash,MAX_CYCLES
from solvefinite.f8 import IndexBinding
from solvefinite.session import Scenario
from solvefinite.tomigidt import Tomigidt
with open(sys.argv[1],encoding='utf-8') as source: value=json.load(source)
scenario=Scenario.from_dict(value['scenario'])
with no_cpu_compilers() if sys.argv[2]=='gpu' else nullcontext():
    agent=Tomigidt.from_archive(value['agent'],capacity=7,backend=sys.argv[2],index_binding=IndexBinding(71,-1,217))
    try:
        while agent.status!='COMPLETE':
            if agent.cycle>=MAX_CYCLES: raise ValueError('Fresh continuation bound')
            agent.step(scenario.observe(agent.position,agent.cycle+1,geometry_epoch=agent.geometry_epoch))
        result={'archive':agent.archive(),'execution_info':agent.execution_info,
                'archive_sha256':canonical_hash(agent.archive()),'CPU_producers_disabled':sys.argv[2]=='gpu'}
        if agent._gpu is not None and agent._gpu.snapshot()!=(agent.agent_pair,agent.energy):
            raise ValueError('Actual device continuation mismatch')
    finally: agent.close()
print(json.dumps(result))
'''
    process = subprocess.run([sys.executable, "-c", script, str(path), backend], cwd=ROOT,
                             capture_output=True, text=True, timeout=180)
    if process.returncode:
        raise RuntimeError(f"Fresh {label} failed: {process.stderr}")
    return json.loads(process.stdout)


def demonstrate(cpu_only=False):
    started = perf_counter(); cpu = cpu_conformance()
    checks = {name: True for name in (
        "CPU_four_independent_literal_missions", "CPU_full_independent_grammar_transcripts",
        "CPU_same_owner_field_target_and_energy_transition", "CPU_original_prefix_historical_regeneration",
        "CPU_cache_index_and_same_quantum_DEFER_transparency", "original_tick_changes_selected_production",
        "legacy_FI_HP_GD_archives_preserved")}
    report = {"format": "organogram-conformance-v1", "formal_binding": "TK-LPLUT-2.0 revision9 OG1-OG8",
              "formal_commit": FORMAL_COMMIT, "CPU": cpu, "checks": checks,
              "actual_GPU_capture": False, "mission_cycle_bound": MAX_CYCLES,
              "formal_reference_sha256_lf": hashlib.sha256(REFERENCE_PATH.read_bytes().replace(b"\r\n",b"\n")).hexdigest()}
    if not cpu_only:
        gpu = {}
        with no_cpu_compilers():
            for label in ("default", "mirrored_default", "two_epoch", "zero_epoch"):
                expected = REFERENCE[label+"_mission"]
                gpu[label] = mission(scenario_for(expected), "gpu", reference=expected, rebuild=True,
                                     capacity=3, binding=IndexBinding(23,-1,139))
                check(gpu[label]["archive"] == cpu["cases"][label]["archive"], f"complete CPU/GPU {label}")
            deferred_scenario = Scenario.from_dict(cpu["deferred_scenario"])
            deferred = mission(deferred_scenario, "gpu", rebuild=True)
            check(deferred["archive"] == cpu["deferred"]["archive"], "complete deferred GPU history")
        replays = {}
        with TemporaryDirectory(prefix="solvefinite-organogram-") as temporary:
            for cut in ("before_growth_1", "after_growth_1"):
                for source, backend in ((cpu["cases"]["default"],"gpu"),(gpu["default"],"cpu")):
                    label = f"{cut}_to_{backend}"
                    value = fresh_replay(Path(temporary), label, scenario_for(), source["checkpoints"][cut], backend)
                    check(value["archive"] == cpu["cases"]["default"]["archive"], f"fresh {label}")
                    replays[label] = value
            for source, backend in ((cpu["deferred"],"gpu"),(deferred,"cpu")):
                label = f"DEFER_after_growth_to_{backend}"
                value = fresh_replay(Path(temporary), label, deferred_scenario,
                                     source["checkpoints"]["DEFER_after_growth"], backend)
                check(value["archive"] == cpu["deferred"]["archive"], f"fresh {label}")
                replays[label] = value
        checks.update({name: True for name in (
            "GPU_four_literal_missions_match_complete_CPU_history", "GPU_full_independent_transcript_digests",
            "GPU_actual_owner_state_every_cycle", "GPU_generated_fields_without_CPU_producer_fallback",
            "GPU_owner_never_host_reseeded", "GPU_cache_reindex_and_time_sensitive_DEFER",
            "GPU_original_context_historical_samples", "six_fresh_process_cross_backend_continuations")})
        report.update(GPU=gpu, GPU_deferred=deferred, fresh_process_replays=replays, actual_GPU_capture=True,
                      disabled_legacy_CPU_compilers=list(FORBIDDEN_CPU_COMPILERS),
                      disabled_OG_CPU_producers=list(FORBIDDEN_OG_PRODUCERS))
    check(all(type(value) is bool and value for value in checks.values()), "all strict checks")
    report.update(canonical_archive_sha256=cpu["cases"]["default"]["archive_sha256"],
                  elapsed_seconds=round(perf_counter()-started,3),
                  scope="Finite parameterized organograms, exact intrinsic union fields and autonomous continuation. "
                        "Time-dependent rules retain original GROW sequence; cross-quantum mission equivalence is not claimed. "
                        "No physical energy, global universality, cache saturation or comparative performance claim.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/organogram-conformance.json")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args(); report = demonstrate(args.cpu_only); write_json(args.output, report)
    print(json.dumps({"output":str(Path(args.output).resolve()),"checks_passed":len(report["checks"]),
                      "actual_GPU_capture":report["actual_GPU_capture"],
                      "canonical_archive_sha256":report["canonical_archive_sha256"],
                      "elapsed_seconds":report["elapsed_seconds"]},indent=2))


if __name__ == "__main__":
    main()
