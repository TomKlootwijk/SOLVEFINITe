"""DP8-DP10 independent one-owner missions, context identity and candidate failures."""

from copy import deepcopy
from dataclasses import replace
import importlib.util
import unittest
from unittest.mock import patch

from examples.taper_conformance import (
    REFERENCE, assert_stage, canonical_hash, expected_stage, fields, fifo,
    literal, mission, scenario_for,
)
from solvefinite.field_agent import (
    FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY, FieldAgentManifest,
)
from solvefinite.f8 import IndexBinding
from solvefinite.taper import TaperBinding
from solvefinite.tomigidt import AgentManifest, CommittedGrowthCleanupError, Tomigidt


def frame(agent):
    return dict.fromkeys(agent.visible_paths, 0)


def empty_boundary_manifest():
    value = deepcopy(REFERENCE["binding"])
    value.update(axiom=[{"symbol":"R","args":[127]}, {"symbol":"S","args":[]}],
                 generations=0, rules=[])
    return scenario_for(taper=TaperBinding.from_dict(value)).manifest


class TaperManifestTests(unittest.TestCase):
    def test_exact_new_manifest_and_preserved_legacy_shapes(self):
        manifest = scenario_for().manifest
        value = manifest.to_dict()
        self.assertEqual(set(value), set(FieldAgentManifest().to_dict()) | {"routing", "taper"})
        self.assertEqual(AgentManifest.from_dict(value), manifest)
        for key in ("routing", "taper"):
            damaged = deepcopy(value); del damaged[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                AgentManifest.from_dict(damaged)
        for key, extra in (("growth", {"format":"klein-dyadic-growth-v1","max_epochs":1,"cost":1}),
                           ("future_epoch", 1)):
            damaged = deepcopy(value); damaged[key] = extra
            with self.subTest(key=key), self.assertRaises(ValueError):
                AgentManifest.from_dict(damaged)
        for policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            previous = FieldAgentManifest(policy=policy).to_dict()
            self.assertNotIn("taper", previous)
            self.assertEqual(AgentManifest.from_dict(previous).to_dict(), previous)
            with self.assertRaises(ValueError):
                FieldAgentManifest(policy=policy, taper=manifest.taper)

    def test_binding_is_retained_and_not_shared_mutable_json(self):
        value = scenario_for().manifest.to_dict()
        manifest = AgentManifest.from_dict(value)
        expected = deepcopy(value)
        value["taper"]["rules"][0]["rhs"][0]["symbol"] = "S"
        value["taper"]["limits"]["max_steps"] = 1
        self.assertEqual(manifest.to_dict(), expected)


class TaperAgentTests(unittest.TestCase):
    backend = "cpu"

    def agent(self, manifest=None, **options):
        agent = Tomigidt(scenario_for().manifest if manifest is None else manifest,
                         backend=self.backend, **options)
        self.addCleanup(agent.close)
        return agent

    def to_pending(self, agent):
        for event in REFERENCE["default_mission"]["events"][:4]:
            agent.step(event["input"])
        self.assertEqual((agent.cycle, agent.status), (4, "GROWTH_PENDING"))

    def test_four_complete_independent_missions_and_stage_transcripts(self):
        for name in ("default_mission", "mirrored_default_mission", "two_epoch_mission", "zero_epoch_mission"):
            with self.subTest(name=name):
                reference = REFERENCE[name]
                result = mission(scenario_for(reference), self.backend, reference=reference)
                self.assertEqual(result["archive"]["expected"]["energy"], reference["final"]["energy"])
                self.assertNotIn("scale_exponent", result["archive"]["expected"])

    def test_owner_is_preserved_while_hypothetical_branch_cursor_changes(self):
        unbranched = deepcopy(REFERENCE["binding"])
        unbranched.update(axiom=[{"symbol":"F","args":[1]}, {"symbol":"S","args":[]}],
                          generations=0, rules=[])
        for name, binding in (("nested", REFERENCE["binding"]), ("unbranched", unbranched)):
            with self.subTest(grammar=name):
                manifest = scenario_for(taper=TaperBinding.from_dict(binding)).manifest
                agent = self.agent(manifest,capacity=1)
                try:
                    self.to_pending(agent)
                    old = agent.current_recipe, agent.agent_pair, agent.manifest.to_dict(), agent.position
                    expected = expected_stage(agent, fields(agent))
                    if name == "unbranched":
                        # This witness distinguishes actual owner preservation
                        # from incorrectly admitting the final grammar cursor.
                        final_cursor = int(expected["document"]["final_context"]["pair"],16)
                        self.assertNotEqual((final_cursor >> 8) & 255, (old[1] >> 8) & 255)
                    self.assertEqual(agent.step(frame(agent)).kind, "GROW")
                    assert_stage(agent, expected, old[0], old[1])
                    self.assertEqual((agent.manifest.to_dict(), agent.position), (old[2], old[3]))
                    self.assertEqual((agent.current_recipe.width, agent.current_recipe.height), (4,5))
                    self.assertEqual(agent.world.active_paths, ())
                    self.assertFalse(agent.pending_search)
                    self.assertEqual(agent.snapshot()["observations"], {})
                    self.assertEqual(agent.events[-1]["growth"]["recipe"]["stages"][0]["prefix_sha256"],
                                     canonical_hash(agent.events[:-1]))
                finally:
                    agent.close()

    def test_historical_original_prefix_survives_eviction_reindex_and_later_input(self):
        agent = self.agent(capacity=1)
        initial = agent.derive_epoch(0, "k:0:2")
        with self.assertRaises(ValueError):
            agent.derive_epoch(1, "k:0:2")
        self.to_pending(agent); agent.step(frame(agent))
        generated = agent.derive_epoch(1, "k:0:2")
        self.assertNotEqual(initial.pair, generated.pair)
        self.assertEqual((generated.origin_sequence, generated.prefix_sha256),
                         (5, canonical_hash(agent.events)))
        for path in ("k:0:0","k:0:1","k:0:2"):
            agent.world.get(path)
        agent.step(frame(agent))
        agent.reindex(psi_sign=-1, phase_origin=91)
        before = agent.archive(), fifo(agent.world)
        self.assertEqual(agent.derive_epoch(0, "k:0:2"), initial)
        self.assertEqual(agent.derive_epoch(1, "k:0:2"), generated)
        self.assertEqual((agent.archive(), fifo(agent.world)), before)
        clone = Tomigidt.from_archive(agent.archive(), backend=self.backend, capacity=1)
        self.addCleanup(clone.close)
        self.assertEqual(clone.derive_epoch(1,"k:0:2"), generated)
        for invalid in (True,-1,2,1.0,"1"):
            with self.subTest(epoch=invalid), self.assertRaises(ValueError):
                agent.recipe_at_epoch(invalid)

    def test_wait_changes_original_tick_and_production_without_resetting_history(self):
        agent = self.agent(replace(scenario_for().manifest,max_cycles=6))
        self.to_pending(agent)
        old_pair = agent.agent_pair
        self.assertEqual(agent.step({}).kind, "WAIT")
        self.assertEqual((agent.geometry_epoch, agent.agent_pair, agent.energy), (0,old_pair,86))
        expected = expected_stage(agent, fields(agent))
        self.assertEqual(expected["document"]["context"]["tick"],6)
        self.assertNotEqual(expected["document"]["tape"],REFERENCE["default_mission"]["stages"][0]["result"]["document"]["tape"])
        previous = agent.current_recipe
        self.assertEqual(agent.step(frame(agent)).kind,"GROW")
        assert_stage(agent,expected,previous,old_pair)
        self.assertEqual((agent.cycle,agent.geometry_epoch,agent.energy),(6,1,85))
        with self.assertRaisesRegex(ValueError,"cycle budget"):
            agent.step(frame(agent))

    def test_pure_empty_boundary_rejection_keeps_exact_usable_owner(self):
        agent = self.agent(empty_boundary_manifest(),capacity=1)
        self.to_pending(agent)
        agent.world.get("k:0:0"); agent.world.get("k:0:1")
        old_world, old_gpu = agent.world, agent._gpu
        before = agent.archive(),fifo(agent.world)
        device = old_gpu.snapshot() if old_gpu is not None else None
        # Radius 127 exceeds this entire quotient, so every site is occupied
        # and there is no boundary. No fault injection is needed.
        for _ in range(2):
            with self.assertRaises(ValueError):
                agent.step(frame(agent))
            self.assertFalse(agent.closed)
            self.assertIs(agent.world,old_world)
            self.assertIs(agent._gpu,old_gpu)
            self.assertEqual((agent.archive(),fifo(agent.world)),before)
            self.assertEqual(old_gpu.snapshot() if old_gpu is not None else None,device)

    def test_rejected_complete_candidate_preserves_owner_and_records_resource_peak(self):
        agent=self.agent(capacity=1);self.to_pending(agent)
        before=agent.archive(),fifo(agent.world);old_world=agent.world
        with patch("solvefinite.tomigidt.select_taper_target",
                   side_effect=ValueError("rejected complete target certificate")):
            with self.assertRaisesRegex(ValueError,"target certificate"):
                agent.step(frame(agent))
        self.assertEqual((agent.archive(),fifo(agent.world)),before)
        self.assertIs(agent.world,old_world)
        self.assertFalse(agent.closed)
        peak=agent.execution_info["growth"]["peak_preparation_payload"]
        self.assertGreaterEqual(peak["host_index_bytes"],64*(20+20)+32)
        self.assertGreaterEqual(peak["host_routing_table_bytes"],68*(20+20))
        if agent._gpu is not None:
            self.assertGreater(peak["device_payload_bytes"],agent._gpu.allocation_info["device_payload_bytes"])
        self.assertEqual(agent.step(frame(agent)).kind,"GROW")

    def test_strict_replay_rejects_context_rule_and_receipt_substitution(self):
        agent = self.agent(); self.to_pending(agent); agent.step(frame(agent))
        base = agent.archive()
        changes = (
            lambda a:a["events"][4]["growth"]["recipe"]["stages"][0].update(tick=6),
            lambda a:a["events"][4]["growth"]["recipe"]["stages"][0].update(prefix_sha256="0"*64),
            lambda a:a["events"][4]["growth"].update(derivation_sha256="0"*64),
            lambda a:a["events"][4]["growth"]["recipe"]["taper"]["rules"][0]["guards"][0].update(value=5),
            lambda a:a["events"][4].update(geometry_epoch=1),
            lambda a:a["expected"].update(scale_exponent=0),
        )
        for number,change in enumerate(changes):
            damaged=deepcopy(base);change(damaged)
            with self.subTest(mutation=number),self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged,backend=self.backend)
        self.assertEqual(agent.archive(),base)

    def test_replay_before_and_after_growth_uses_its_original_context(self):
        scenario=scenario_for();agent=self.agent()
        for event in REFERENCE["default_mission"]["events"][:5]:
            agent.step(event["input"])
            if agent.cycle not in (4,5):continue
            clone=Tomigidt.from_archive(agent.archive(),backend=self.backend,capacity=7,
                                       index_binding=IndexBinding(12,-1,63))
            try:
                self.assertEqual(clone.archive(),agent.archive())
                while clone.status!="COMPLETE":
                    clone.step(scenario.observe(clone.position,clone.cycle+1,geometry_epoch=clone.geometry_epoch))
                self.assertEqual((clone.cycle,clone.energy,f"{clone.agent_pair:016X}"),
                                 (11,69,"16000534060005CC"))
            finally:clone.close()

    def test_same_quantum_defer_survives_each_reindex_and_cache_capacity(self):
        scenario=scenario_for(max_search_expansions=7)
        a=mission(scenario,self.backend,rebuild=True,capacity=1)
        b=mission(scenario,self.backend,capacity=32)
        self.assertEqual(a["archive"],b["archive"])
        self.assertIn("DEFER_after_growth",a["checkpoints"])
        self.assertTrue(any(value["search_pending"] for value in a["rebuilds"]))
        self.assertNotEqual(a["stages"][0]["context"]["tick"],5)
        self.assertNotEqual(a["stages"][0]["expected_derivation"]["tape"],
                            REFERENCE["default_mission"]["stages"][0]["result"]["document"]["tape"])

    def test_future_growth_and_repair_costs_are_reserved_before_first_repair(self):
        low=self.agent(scenario_for(target="k:0:0",initial_energy=10).manifest)
        before=low.agent_pair
        self.assertEqual(low.step(frame(low)).kind,"INSUFFICIENT_ENERGY")
        self.assertEqual((low.agent_pair,low.energy,low.geometry_epoch),(before,10,0))
        enough=self.agent(scenario_for(target="k:0:0",initial_energy=11).manifest)
        self.assertEqual(enough.step(frame(enough)).kind,"REPAIR")
        self.assertEqual((enough.energy,enough.status),(6,"GROWTH_PENDING"))


class TaperOwnerFailureTests(unittest.TestCase):
    def test_uncertain_candidate_tag_closes_owner_without_admitting_prefix(self):
        agent=Tomigidt(scenario_for().manifest)
        self.addCleanup(agent.close)
        for event in REFERENCE["default_mission"]["events"][:4]:agent.step(event["input"])
        before=agent.archive()
        failure=RuntimeError("uncertain detached candidate");failure.device_uncertain=True
        with patch.object(agent,"_organogram_recipe",side_effect=failure):
            with self.assertRaisesRegex(RuntimeError,"uncertain detached"):
                agent.step(frame(agent))
        self.assertTrue(agent.closed)
        self.assertEqual(agent.archive(),before)


@unittest.skipUnless(importlib.util.find_spec("wgpu") is not None,"Optional wgpu is not installed")
class RealTaperAgentTests(TaperAgentTests):
    backend="gpu"

    @classmethod
    def setUpClass(cls):
        from solvefinite.gpu import GpuUnavailable
        try:probe=Tomigidt(scenario_for().manifest,backend="gpu")
        except GpuUnavailable as exc:raise unittest.SkipTest(str(exc)) from exc
        probe.close()

    def test_uncertain_generated_admission_closes_owner_without_event(self):
        agent=self.agent();self.to_pending(agent);before=agent.archive()
        failure=RuntimeError("uncertain generated dispatch");failure.device_uncertain=True
        with patch("solvefinite.field_agent_gpu.GpuFieldAgentExecutor.admit_generated",side_effect=failure):
            with self.assertRaisesRegex(RuntimeError,"uncertain generated"):
                agent.step(frame(agent))
        self.assertTrue(agent.closed)
        self.assertEqual(agent.archive(),before)

    def test_rejected_complete_device_result_keeps_original_owner(self):
        agent=self.agent();self.to_pending(agent)
        before=agent.archive(),fifo(agent.world);old_gpu=agent._gpu
        from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
        original=GpuFieldAgentExecutor.admit_generated
        def wrong_energy(executor,*args,**kwargs):
            pair,energy=original(executor,*args,**kwargs)
            return pair,energy-1
        with patch.object(GpuFieldAgentExecutor,"admit_generated",wrong_energy):
            with self.assertRaises(ValueError):agent.step(frame(agent))
        self.assertEqual((agent.archive(),fifo(agent.world)),before)
        self.assertIs(agent._gpu,old_gpu)
        self.assertFalse(agent.closed)
        self.assertEqual(old_gpu.snapshot(),(agent.agent_pair,agent.energy))
        self.assertEqual(agent.step(frame(agent)).kind,"GROW")

    def test_committed_cleanup_failure_retains_generated_prefix_and_closes(self):
        agent=self.agent();self.to_pending(agent);old_gpu=agent._gpu
        self.addCleanup(old_gpu.close)
        with patch.object(old_gpu,"close",side_effect=RuntimeError("old cleanup failure")):
            with self.assertRaises(CommittedGrowthCleanupError) as caught:agent.step(frame(agent))
        self.assertTrue(caught.exception.committed)
        self.assertTrue(agent.closed)
        self.assertEqual((agent.cycle,agent.geometry_epoch,agent.events[-1]["decision"]["kind"]),(5,1,"GROW"))
        restored=Tomigidt.from_archive(agent.archive(),backend="cpu")
        try:self.assertEqual(restored.archive(),agent.archive())
        finally:restored.close()


if __name__=="__main__":
    unittest.main()
