"""One persistent individual across independently specified semantic generations."""

from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.field_agent import FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, FieldAgentManifest
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.f8 import IndexBinding
from solvefinite.growth import GrowthBinding
from solvefinite.rp32 import Opcode, unpack, unpair
from solvefinite.tomigidt import AgentManifest, CommittedGrowthCleanupError, Tomigidt


REFERENCE = json.loads((Path(__file__).resolve().parents[1] /
                        'docs/evidence/growth-v1/formal-reference.json').read_text())


def spec(reference=None, **changes):
    if reference is None:
        return FieldAgentManifest(policy=GROWTH_POLICY, **changes)
    initial = reference['initial']
    values = dict(policy=GROWTH_POLICY, world=KleinFieldRecipe(
        **{**reference['initial_recipe'], 'turns': tuple(reference['initial_recipe']['turns'])}),
        growth=GrowthBinding.from_dict(reference['growth']),
        target=reference['worlds'][0]['target_path'], initial_phase=initial['phase'],
        initial_orientation=initial['orientation'], initial_energy=initial['energy'])
    values.update(changes)
    return FieldAgentManifest(**values)


def frame(agent):
    return dict.fromkeys(agent.visible_paths, 0)


def cache(world):
    return world.active_paths, world.evicted_paths, world.hit_count, world.regeneration_count


class GrowthManifestTests(unittest.TestCase):
    def test_strict_new_schema_and_all_legacy_schemas(self):
        value = spec().to_dict()
        self.assertEqual(AgentManifest.from_dict(value), spec())
        old = FieldAgentManifest().to_dict()
        self.assertEqual(set(value), set(old) | {'routing', 'growth'})
        for key in ('growth', 'routing'):
            broken = deepcopy(value); del broken[key]
            with self.assertRaises(ValueError):
                AgentManifest.from_dict(broken)
        for policy in (FIELD_POLICY, HADAMARD_POLICY):
            with self.assertRaises(ValueError):
                FieldAgentManifest(policy=policy, growth=GrowthBinding())
            legacy = FieldAgentManifest(policy=policy).to_dict()
            self.assertNotIn('growth', legacy)
            self.assertEqual(AgentManifest.from_dict(legacy).to_dict(), legacy)

    def test_mission_bound_rejected_before_any_candidate_allocation(self):
        large = KleinFieldRecipe(8, 10, 0, 4)
        with patch.object(KleinFieldRecipe, 'graph', side_effect=AssertionError('allocated')):
            with self.assertRaisesRegex(ValueError, '256'):
                spec(world=large)
            with self.assertRaisesRegex(ValueError, '256'):
                spec(growth=GrowthBinding(max_epochs=2))


class GrowthAgentTests(unittest.TestCase):
    backend = 'cpu'

    def agent(self, manifest=None, **options):
        value = Tomigidt(spec() if manifest is None else manifest, backend=self.backend, **options)
        self.addCleanup(value.close)
        return value

    def reference(self, agent, reference, start=0):
        for expected in reference['events'][start:]:
            previous_recipe = agent.current_recipe
            self.assertEqual(agent.geometry_epoch, expected['input_geometry_epoch'])
            decision = agent.step(expected['input'])
            self.assertEqual((decision.kind, decision.cost, decision.route),
                             (expected['kind'], expected['cost'], tuple(expected.get('paths', ()))))
            self.assertEqual((f'{agent.agent_pair:016X}', agent.energy, agent.geometry_epoch,
                              agent.status, agent.target),
                             (expected['state']['pair'], expected['state']['energy'],
                              expected['geometry_epoch'],
                              'ACTIVE' if expected['status'] == 'RUNNING' else expected['status'],
                              reference['worlds'][expected['geometry_epoch']]['target_path']))
            if decision.kind == 'MOVE':
                self.assertEqual(decision.expansions, expected['expansions'])
                self.assertEqual([f'{value:016X}' for value in decision.forecast], expected['forecast'])
            if decision.kind == 'GROW':
                self.assertNotEqual(agent.current_recipe, previous_recipe)
                self.assertEqual(agent.world.active_paths, ())
                self.assertFalse(agent.pending_search)
                self.assertEqual(agent.snapshot()['observations'], {})
                self.assertEqual(agent.events[-1]['geometry_epoch'], agent.geometry_epoch - 1)
                self.assertEqual(agent.events[-1]['growth']['target'], agent.target)
            if agent._gpu is not None:
                self.assertEqual(agent._gpu.snapshot(), (agent.agent_pair, agent.energy))
        self.assertEqual(agent.status, 'COMPLETE')

    def test_independent_default_mirror_two_epoch_and_zero_epoch_missions(self):
        for key in ('default_mission', 'mirrored_default_mission', 'two_epoch_mission', 'zero_epoch_mission'):
            with self.subTest(mission=key):
                reference = REFERENCE[key]
                self.reference(self.agent(spec(reference)), reference)

    def test_original_manifest_history_and_qualified_samples_survive_growth(self):
        reference = REFERENCE['default_mission']
        agent = self.agent(capacity=1)
        original = agent.manifest.to_dict()
        early = agent.derive_epoch(0, 'k:0:0')
        with self.assertRaises(ValueError):
            agent.derive_epoch(1, 'k:0:0')
        self.reference(agent, reference)
        before = agent.archive(), cache(agent.world)
        restored = agent.derive_epoch(0, 'k:0:0')
        current = agent.derive_epoch(1, 'k:0:0')
        self.assertEqual(early, restored)
        self.assertNotEqual(early.pair, current.pair)
        self.assertEqual((restored.origin_sequence, current.origin_sequence), (0, 5))
        self.assertEqual((agent.archive(), cache(agent.world)), before)
        self.assertEqual(agent.manifest.to_dict(), original)
        self.assertEqual(agent.snapshot()['footprint']['epoch'], 1)
        self.assertEqual(unpack(unpair(restored.pair)[0])[3], int(Opcode.DATA))
        with self.assertRaises(ValueError):
            agent.recipe_at_epoch(True)
        with self.assertRaises(ValueError):
            agent.recipe_at_epoch(2)

    def test_qualified_samples_bind_the_actual_original_prefix(self):
        samples = []
        for phase in (0, 1):
            agent = self.agent(spec(target='k:0:0', initial_phase=phase))
            for _ in range(2):
                agent.step(frame(agent))
            sample = agent.derive_epoch(1, 'k:0:0')
            expected = hashlib.sha256(json.dumps(agent.events, sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
            self.assertEqual(sample.prefix_sha256, expected)
            self.assertEqual(sample.origin_sequence, 2)
            # Later events, residency and a storage rebuild cannot alter an original prefix.
            agent.step(frame(agent))
            agent.reindex(psi_sign=-1, phase_origin=91)
            self.assertEqual(agent.derive_epoch(1, 'k:0:0'), sample)
            restored = Tomigidt.from_archive(agent.archive(), backend=self.backend, capacity=1)
            self.addCleanup(restored.close)
            self.assertEqual(restored.derive_epoch(1, 'k:0:0'), sample)
            samples.append(sample)
        self.assertEqual(samples[0].pair, samples[1].pair)
        self.assertNotEqual(samples[0].prefix_sha256, samples[1].prefix_sha256)
        self.assertNotEqual(samples[0], samples[1])

    def test_replay_at_both_sides_of_production_and_strict_tampering(self):
        reference = REFERENCE['default_mission']
        agent = self.agent()
        for expected in reference['events'][:5]:
            agent.step(expected['input'])
            if agent.cycle in (4, 5):
                clone = Tomigidt.from_archive(agent.archive(), capacity=1, backend=self.backend,
                                             index_binding=IndexBinding(7, -1, 127))
                self.addCleanup(clone.close)
                self.assertEqual(clone.archive(), agent.archive())
                self.reference(clone, reference, start=agent.cycle)
        for mutation in ('epoch', 'receipt', 'snapshot', 'missing'):
            damaged = deepcopy(agent.archive())
            if mutation == 'epoch':
                damaged['events'][4]['geometry_epoch'] = 1
            elif mutation == 'receipt':
                damaged['events'][4]['growth']['recipe']['radius'] = 3
            elif mutation == 'snapshot':
                damaged['expected']['target'] = 'k:0:0'
            else:
                del damaged['events'][0]['growth']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged, backend=self.backend)

    def test_pending_growth_survives_wait_requires_new_frame_and_keeps_cycle_budget(self):
        agent = self.agent(spec(max_cycles=6))
        for event in REFERENCE['default_mission']['events'][:4]:
            agent.step(event['input'])
        self.assertEqual(agent.status, 'GROWTH_PENDING')
        self.assertEqual(agent.step({}).kind, 'WAIT')
        self.assertEqual(agent.geometry_epoch, 0)
        self.assertEqual(agent.step(frame(agent)).kind, 'GROW')
        self.assertEqual((agent.cycle, agent.geometry_epoch), (6, 1))
        with self.assertRaisesRegex(ValueError, 'cycle budget'):
            agent.step(frame(agent))

    def test_zero_route_still_reserves_growth_and_later_repair_energy(self):
        agent = self.agent(spec(target='k:0:0', initial_energy=10))
        before = agent.agent_pair
        self.assertEqual(agent.step(frame(agent)).kind, 'INSUFFICIENT_ENERGY')
        self.assertEqual((agent.agent_pair, agent.energy, agent.geometry_epoch), (before, 10, 0))
        enough = self.agent(spec(target='k:0:0', initial_energy=11))
        self.assertEqual(enough.step(frame(enough)).kind, 'REPAIR')
        self.assertEqual(enough.energy, 6)
        self.assertEqual(enough.step(frame(enough)).kind, 'GROW')
        self.assertEqual(enough.energy, 5)
        self.assertEqual(enough.step(frame(enough)).kind, 'INSUFFICIENT_ENERGY')

    def test_pure_candidate_rejection_preserves_old_archive_fifo_and_owner(self):
        agent = self.agent()
        for event in REFERENCE['default_mission']['events'][:4]:
            agent.step(event['input'])
        before = agent.archive(), cache(agent.world)
        old_world = agent.world
        with patch('solvefinite.tomigidt.grow_recipe', side_effect=ValueError('pure candidate rejection')):
            with self.assertRaisesRegex(ValueError, 'pure candidate'):
                agent.step(frame(agent))
        self.assertIs(agent.world, old_world)
        self.assertFalse(agent.closed)
        self.assertEqual((agent.archive(), cache(agent.world)), before)
        self.assertEqual(agent.step(frame(agent)).kind, 'GROW')

    def test_complete_rejected_candidate_still_counts_preparation_payload(self):
        agent = self.agent()
        for event in REFERENCE['default_mission']['events'][:4]:
            agent.step(event['input'])
        before = agent.archive(), cache(agent.world)
        with patch('solvefinite.tomigidt.select_target', side_effect=ValueError('rejected target certificate')):
            with self.assertRaisesRegex(ValueError, 'target certificate'):
                agent.step(frame(agent))
        self.assertEqual((agent.archive(), cache(agent.world)), before)
        self.assertFalse(agent.closed)
        payload = agent.execution_info['growth']['peak_preparation_payload']
        self.assertEqual(payload['host_index_bytes'], 64 * (20 + 80) + 32)
        if agent._gpu is not None:
            self.assertGreater(payload['device_payload_bytes'], agent._gpu.allocation_info['device_payload_bytes'])
        self.assertEqual(agent.step(frame(agent)).kind, 'GROW')

    def test_reindex_and_capacity_preserve_search_and_history_in_new_epoch(self):
        manifest = spec(target='k:0:0', max_search_expansions=16)
        agent = self.agent(manifest, capacity=1)
        control = self.agent(manifest, capacity=32)
        for _ in range(2):
            self.assertEqual(agent.step(frame(agent)), control.step(frame(control)))
        self.assertEqual(agent.geometry_epoch, 1)
        seen_defer = False
        for _ in range(500):
            self.assertEqual(agent.step(frame(agent)), control.step(frame(control)))
            self.assertEqual(agent.archive(), control.archive())
            if agent.pending_search:
                seen_defer = True
                planning = agent._planning
                before = agent.archive(), cache(agent.world)
                agent.reindex(psi_sign=-agent.world.index.binding.psi_sign, phase_origin=agent.cycle % 256)
                self.assertIs(agent._planning, planning)
                self.assertEqual((agent.archive(), cache(agent.world)), before)
            if agent.status == 'COMPLETE':
                break
        self.assertTrue(seen_defer)
        self.assertEqual(agent.status, 'COMPLETE')


class GrowthOwnerFailureTests(unittest.TestCase):
    def test_uncertain_candidate_tag_closes_owner_without_admitting_event(self):
        agent = Tomigidt(spec())
        self.addCleanup(agent.close)
        for event in REFERENCE['default_mission']['events'][:4]:
            agent.step(event['input'])
        before = agent.archive()
        error = RuntimeError('uncertain candidate')
        error.device_uncertain = True
        with patch('solvefinite.tomigidt.grow_recipe', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'uncertain candidate'):
                agent.step(frame(agent))
        self.assertTrue(agent.closed)
        self.assertEqual(agent.archive(), before)


@unittest.skipUnless(importlib.util.find_spec('wgpu') is not None, 'Optional wgpu is not installed')
class RealGrowthAgentTests(GrowthAgentTests):
    backend = 'gpu'

    @classmethod
    def setUpClass(cls):
        from solvefinite.gpu import GpuUnavailable
        try:
            probe = Tomigidt(spec(), backend='gpu')
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        probe.close()

    def test_committed_cleanup_failure_retains_new_history_and_closes_owner(self):
        agent = self.agent()
        for event in REFERENCE['default_mission']['events'][:4]:
            agent.step(event['input'])
        old_gpu = agent._gpu
        self.addCleanup(old_gpu.close)
        with patch.object(old_gpu, 'close', side_effect=RuntimeError('old cleanup')):
            with self.assertRaises(CommittedGrowthCleanupError) as caught:
                agent.step(frame(agent))
        self.assertTrue(caught.exception.committed)
        self.assertTrue(agent.closed)
        self.assertEqual((agent.cycle, agent.geometry_epoch), (5, 1))
        self.assertEqual(agent.events[-1]['decision']['kind'], 'GROW')
        restored = Tomigidt.from_archive(agent.archive())
        self.addCleanup(restored.close)
        self.assertEqual(restored.archive(), agent.archive())
        peak = agent.execution_info['growth']['peak_preparation_payload']
        self.assertGreater(peak['device_payload_bytes'], agent._gpu.allocation_info['device_payload_bytes'])


if __name__ == '__main__':
    unittest.main()
