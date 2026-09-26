"""HP policy integration against the independently committed literal missions."""

from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.field_agent import FIELD_POLICY, HADAMARD_POLICY, FieldAgentManifest
from solvefinite.f8 import IndexBinding
from solvefinite.hadamard import HadamardBinding
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL
from solvefinite.session import Scenario, run_session
from solvefinite.tomigidt import AgentManifest, Tomigidt


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / 'docs/evidence/hadamard-v1/formal-reference.json').read_text())


def manifest(**kwargs):
    return FieldAgentManifest(policy=HADAMARD_POLICY, **kwargs)


def zero_frame(agent):
    return dict.fromkeys(agent.visible_paths, 0)


def cache(world):
    return (world.active_paths, world.evicted_paths, world.hit_count, world.regeneration_count)


def mission(agent):
    scenario = Scenario(agent.manifest, changes=((2, 'k:0:3', 70),))
    for _ in range(1000):
        if agent.status == 'COMPLETE':
            return agent.archive()
        agent.step(scenario.observe(agent.position, agent.cycle + 1))
    raise AssertionError('Finite HP mission failed to complete')


def request(ready, observations=None):
    next_frame = ready['next']
    return {'protocol': PROTOCOL, 'type': 'observe',
            'producer': ready['producer'], 'epoch': ready['epoch'],
            'seq': next_frame['seq'], 'position': next_frame['position'],
            'observations': dict.fromkeys(next_frame['paths'], 0) if observations is None else observations}


class HadamardManifestTests(unittest.TestCase):
    def test_strict_new_policy_schema_and_legacy_shape(self):
        new = manifest()
        encoded = new.to_dict()
        old = FieldAgentManifest().to_dict()
        self.assertEqual(set(encoded), set(old) | {'routing'})
        self.assertEqual(encoded['routing'], REFERENCE['binding'])
        self.assertEqual(AgentManifest.from_dict(encoded), new)
        self.assertEqual(FieldAgentManifest.from_dict(old).to_dict(), old)
        self.assertNotIn('routing', old)
        bad = []
        without = deepcopy(encoded); without.pop('routing'); bad.append(without)
        extra = deepcopy(old); extra['routing'] = encoded['routing']; bad.append(extra)
        for value in (None, {}, {'format': 'wrong', 'gains': [[1, 1]] * 4},
                      {'format': 'hadamard-klein-routing-v1', 'gains': [[True, 1]] * 4},
                      {'format': 'hadamard-klein-routing-v1', 'gains': [[5, 1]] * 4}):
            damaged = deepcopy(encoded); damaged['routing'] = value; bad.append(damaged)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                AgentManifest.from_dict(value)
        with self.assertRaises(ValueError):
            FieldAgentManifest(routing=HadamardBinding())
        self.assertEqual(LiveConfig.from_dict(LiveConfig(new).to_dict()).manifest, new)
        self.assertEqual(Scenario.from_dict(Scenario(new, changes=()).to_dict()).manifest, new)


class HadamardAgentTests(unittest.TestCase):
    backend = 'cpu'

    def agent(self, spec=None, **kwargs):
        agent = Tomigidt(manifest() if spec is None else spec, backend=self.backend, **kwargs)
        self.addCleanup(agent.close)
        return agent

    def assert_reference(self, agent, reference):
        self.assertEqual(f'{agent.agent_pair:016X}', reference['initial']['pair'])
        for expected in reference['events']:
            decision = agent.step(expected['input'])
            route = [agent.manifest.world.index(path) for path in decision.route]
            self.assertEqual((decision.kind, route, decision.cost),
                             (expected['kind'], expected['route'], expected['cost']))
            self.assertEqual((f'{agent.agent_pair:016X}', agent.energy),
                             (expected['pair'], expected['energy']))
            if decision.kind == 'MOVE':
                self.assertEqual(decision.expansions, expected['expansions'])
                self.assertEqual([f'{word:016X}' for word in decision.forecast], expected['forecast'])
            if agent._gpu is not None:
                self.assertEqual(agent._gpu.snapshot(), (agent.agent_pair, agent.energy))
        self.assertEqual(agent.status, 'COMPLETE')

    def test_literal_default_phase_and_zero_gain_missions(self):
        self.assert_reference(self.agent(), REFERENCE['mission'])
        for phase, expected in REFERENCE['phase_ablations'].items():
            with self.subTest(phase=phase):
                self.assert_reference(self.agent(manifest(initial_phase=int(phase))), expected)
        self.assert_reference(self.agent(manifest(routing=HadamardBinding(gains=((0, 0),) * 4))),
                              REFERENCE['zero_gain_ablation'])

    def test_complete_mirror_preserves_routes_costs_expansions_and_energy(self):
        left = self.agent(capacity=1)
        right = self.agent(manifest(initial_phase=6, initial_orientation=1), capacity=32,
                           index_binding=IndexBinding(psi_sign=-1, phase_origin=111))
        swap = lambda word: word >> 32 | (word & 0xffffffff) << 32
        self.assertEqual(right.agent_pair, swap(left.agent_pair))
        for expected in REFERENCE['mission']['events']:
            a, b = left.step(expected['input']), right.step(expected['input'])
            self.assertEqual((a.kind, a.route, a.cost, a.expansions),
                             (b.kind, b.route, b.cost, b.expansions))
            self.assertEqual(tuple(map(swap, a.forecast)), b.forecast)
            self.assertEqual((right.agent_pair, right.energy), (swap(left.agent_pair), left.energy))

    def test_reindex_preserves_exact_pending_search_fifo_archive_and_continuation(self):
        agent = self.agent(manifest(max_search_expansions=1), capacity=1)
        control = self.agent(agent.manifest, capacity=32)
        self.assertEqual(agent.step(zero_frame(agent)).kind, 'DEFER')
        control.step(zero_frame(control))
        pending = agent._planning
        model = agent.world.routing_model
        before = agent.archive(), cache(agent.world)
        agent.reindex(psi_sign=-1, phase_origin=192)
        self.assertIs(agent._planning, pending)
        self.assertIs(agent.world.routing_model, model)
        self.assertEqual((agent.archive(), cache(agent.world)), before)
        for _ in range(200):
            a, b = agent.step(zero_frame(agent)), control.step(zero_frame(control))
            self.assertEqual(a, b)
            self.assertEqual(agent.archive(), control.archive())
            if agent.status == 'COMPLETE':
                break
        else:
            self.fail('Retained search did not complete')
        self.assertGreater(agent.world.regeneration_count, 0)

    def test_hazard_change_invalidates_cursor_but_invalid_frame_does_not(self):
        agent = self.agent(manifest(max_search_expansions=1), capacity=1)
        agent.step(zero_frame(agent)); agent.step(zero_frame(agent))
        pending = agent._planning
        before = agent.archive(), cache(agent.world)
        for bad in ({'route': []}, {'k:0:4': True}, {'k:3:2': 1}):
            with self.assertRaises(ValueError):
                agent.step(bad)
            self.assertIs(agent._planning, pending)
            self.assertEqual((agent.archive(), cache(agent.world)), before)
        self.assertEqual(agent.step({}).kind, 'WAIT')
        self.assertIs(agent._planning, pending)
        self.assertEqual(agent.step({'k:0:4': 70}).kind, 'WAIT')
        self.assertFalse(agent.pending_search)
        frame = zero_frame(agent); frame['k:0:4'] = 70
        decision = agent.step(frame)
        self.assertEqual((decision.kind, decision.expansions), ('DEFER', 1))
        self.assertEqual(agent.snapshot()['planning']['weights']['k:0:4'], 72)

    def test_full_route_reserve_and_fresh_observation_gate(self):
        agent = self.agent(manifest(initial_energy=11))
        initial = agent.agent_pair
        self.assertEqual(agent.step({agent.position: 0}).kind, 'WAIT')
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, decision.cost), ('INSUFFICIENT_ENERGY', 7))
        self.assertEqual((agent.agent_pair, agent.energy), (initial, 11))
        exact = self.agent(manifest(initial_energy=12))
        values = []
        for _ in range(20):
            if exact.status == 'COMPLETE':
                break
            result = exact.step(zero_frame(exact))
            values.append(result.cost)
        self.assertEqual((exact.status, exact.energy), ('COMPLETE', 0))
        self.assertTrue(all(a > b for a, b in zip(values[:-2], values[1:-1])))

    def test_semantic_routing_changes_and_cost_tampering_reject_replay(self):
        agent = self.agent()
        original = mission(agent)
        for change in ('gains', 'phase', 'cost', 'energy', 'policy'):
            damaged = deepcopy(original)
            if change == 'gains':
                damaged['manifest']['routing']['gains'] = [[0, 0]] * 4
            elif change == 'phase':
                damaged['manifest']['initial_phase'] = 192
            elif change == 'policy':
                damaged['manifest']['policy'] = FIELD_POLICY
                damaged['manifest'].pop('routing')
            elif change == 'cost':
                damaged['events'][1]['decision']['cost'] -= 1
            else:
                damaged['events'][1]['energy'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged, backend=self.backend)

    def test_fresh_process_replays_defer_and_reversing_seam(self):
        for quantum, steps in ((1, 2), (4096, 2)):
            agent = self.agent(manifest(max_search_expansions=quantum))
            scenario = Scenario(agent.manifest, changes=((2, 'k:0:3', 70),))
            for _ in range(steps):
                agent.step(scenario.observe(agent.position, agent.cycle + 1))
            paused = agent.archive()
            final = mission(agent)
            script = ("import json,sys\nfrom solvefinite.tomigidt import Tomigidt\n"
                      "from solvefinite.session import Scenario\nfrom solvefinite.f8 import IndexBinding\n"
                      "a=Tomigidt.from_archive(json.load(sys.stdin),capacity=1,backend='cpu',"
                      "index_binding=IndexBinding(psi_sign=-1,phase_origin=99))\n"
                      "s=Scenario(a.manifest,changes=((2,'k:0:3',70),))\n"
                      "while a.status!='COMPLETE': a.step(s.observe(a.position,a.cycle+1))\n"
                      "json.dump(a.archive(),sys.stdout,sort_keys=True)\na.close()\n")
            completed = subprocess.run([sys.executable, '-c', script], input=json.dumps(paused),
                                       capture_output=True, text=True, cwd=ROOT, timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout), final)


class HadamardPersistenceTests(unittest.TestCase):
    def test_live_reindex_defer_durable_retry_and_cpu_session(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'live.json'
            config = LiveConfig(manifest(max_search_expansions=1))
            with LiveSession(path, config=config, capacity=1) as live:
                sent = request(live.ready())
                result = live.handle(sent)
                before = path.read_bytes()
                live.reindex(psi_sign=-1, phase_origin=255)
                self.assertEqual(path.read_bytes(), before)
                self.assertTrue(live.handle(sent)['duplicate'])
                self.assertEqual(live.ready()['state'], result['state'])
            with LiveSession(path, capacity=32) as live:
                self.assertEqual(live.ready()['state'], result['state'])
                self.assertTrue(live.handle(sent)['duplicate'])
            scenario = Scenario(manifest(), changes=((2, 'k:0:3', 70),))
            scenario_path = Path(directory) / 'scenario.json'
            scenario_path.write_text(json.dumps(scenario.to_dict()))
            state = Path(directory) / 'state.json'
            run_session(state, steps=2, scenario_path=scenario_path)
            result = run_session(state, steps=10, capacity=1)
            self.assertEqual((result['status'], result['state']['energy']), ('COMPLETE', 86))

    def test_cli_exports_real_hadamard_profiles_and_replays(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            scenario, state, live = (directory / name for name in ('scenario.json', 'state.json', 'live.json'))
            commands = [
                ['scenario', '--profile', 'hadamard', '--output', str(scenario)],
                ['live-config', '--profile', 'hadamard', '--output', str(live)],
                ['run', '--scenario', str(scenario), '--state', str(state), '--steps', '2'],
                ['run', '--state', str(state), '--steps', '10', '--index-sign', '-1'],
                ['inspect', str(state), '--index-phase-origin', '64'],
            ]
            for command in commands:
                result = subprocess.run([sys.executable, '-m', 'solvefinite', 'agent', *command],
                                        capture_output=True, text=True, cwd=ROOT, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            inspected = json.loads(result.stdout)
            self.assertEqual(inspected['state']['energy'], 86)
            self.assertEqual(inspected['execution_info']['routing']['binding'], REFERENCE['binding'])
            self.assertEqual(json.loads(live.read_text())['agent']['policy'], HADAMARD_POLICY)


@unittest.skipUnless(importlib.util.find_spec('wgpu') is not None, 'Optional wgpu is not installed')
class RealHadamardAgentTests(HadamardAgentTests):
    """Run the same complete policy obligations on persistent actual GPU state."""

    backend = 'gpu'

    @classmethod
    def setUpClass(cls):
        from solvefinite.gpu import GpuUnavailable
        try:
            probe = Tomigidt(manifest(), backend='gpu')
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        probe.close()


if __name__ == '__main__':
    unittest.main()
