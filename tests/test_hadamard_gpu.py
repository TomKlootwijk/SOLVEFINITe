"""HP5-HP8 actual-device atlas, bank selection, admission and ownership."""

from contextlib import ExitStack
import importlib.util
import json
from math import gcd
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch

from solvefinite.f8 import IndexBinding
from solvefinite.field_agent_gpu import CommittedIndexCleanupError, GpuFieldAgentExecutor
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.hadamard import HadamardBinding, RoutingModel
from solvefinite.motion import EnergyExhausted
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from tests.test_f8 import independent as field_oracle
from tests.test_f8_gpu import forbid_cpu_compilers


DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def oracle(recipe, binding):
    """Separate quotient arithmetic and normalized integer products."""
    fields = field_oracle(recipe)[3]

    def adjacent(source, direction):
        u, v = divmod(source, recipe.height)
        du, dv = direction
        wraps, u = divmod(u + du, recipe.width)
        return u * recipe.height + ((-v - dv if wraps % 2 else v + dv) % recipe.height), wraps % 2

    neighbors, penalties, increments, edges = [], [], [], {}
    for source in range(len(fields)):
        directional = tuple(adjacent(source, direction)[0] for direction in DIRECTIONS)
        gu, gv = fields[directional[0]] - fields[directional[1]], fields[directional[2]] - fields[directional[3]]
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        row = tuple(sorted(directional))
        neighbors.append(row)
        for bank, (au, av) in enumerate(binding.gains):
            qu, qv = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
            maximum = max(abs(qu), abs(qv))
            for destination in row:
                direction = DIRECTIONS[directional.index(destination)]
                penalty = maximum - qu * direction[0] - qv * direction[1]
                penalties.append(penalty)
                edges[source, destination] = adjacent(source, direction)[1]
        increments.append(recipe.turns[(fields[source] > 0) - (fields[source] < 0) + 1])
    return fields, tuple(neighbors), tuple(penalties), tuple(increments), edges


def initial(fields, source=0, t=250, eta=0):
    return pair(pack((-t if eta else t) % 256, source, fields[source], int(Opcode.STEP) | eta << 4))


def predict(recipe, binding, value, destinations, hazards):
    fields, neighbors, penalties, increments, edges = oracle(recipe, binding)
    phase, source, _, metadata = unpack(unpair(value)[0])
    eta = metadata >> 4
    outputs, costs = [], []
    for destination, hazard in zip(destinations, hazards):
        t = (-phase if eta else phase) % 256
        costs.append(1 + abs(fields[destination]) + hazard
                     + penalties[16 * source + 4 * (t // 64) + neighbors[source].index(destination)])
        phase = (phase + (-1 if eta else 1) * increments[source]) % 256
        tau = edges[source, destination]
        phase = (-phase if tau else phase) % 256
        eta ^= tau
        source = destination
        outputs.append(pair(pack(phase, source, fields[source], int(Opcode.STEP) | eta << 4)))
    return tuple(outputs), tuple(costs)


def no_cpu_routing():
    stack = ExitStack()
    stack.enter_context(forbid_cpu_compilers())
    for name in ("solvefinite.hadamard.RoutingModel.build", "solvefinite.hadamard._compile_model",
                 "solvefinite.hadamard.evaluate_field"):
        stack.enter_context(patch(name, side_effect=AssertionError("CPU fallback: " + name)))
    return stack


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class HadamardGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe(), routing=HadamardBinding())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def executor(self, recipe=None, binding=None, index=None):
        owner = GpuFieldAgentExecutor(recipe or KleinFieldRecipe(), index,
                                      routing=binding or HadamardBinding())
        self.addCleanup(owner.close)
        return owner

    @staticmethod
    def write_texel(owner, bundle, x, y, word):
        owner._device.queue.write_texture(
            {"texture": bundle.texture, "origin": (x, y, 0)}, struct.pack("<I", word),
            {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))

    def candidate_injection(self, owner, corrupt):
        """Mutate the actual candidate atlas after its device compilation."""
        stack = ExitStack()
        bind, dispatch = owner._bind_bundle, owner._dispatch
        candidates = []

        def capture(bundle):
            candidates.append(bundle)
            return bind(bundle)

        def after_compile(pipeline, group, workgroups=1):
            dispatch(pipeline, group, workgroups)
            if pipeline is owner._pipelines["compile_hadamard"]:
                corrupt(candidates[-1])

        stack.enter_context(patch.object(owner, "_bind_bundle", side_effect=capture))
        stack.enter_context(patch.object(owner, "_dispatch", side_effect=after_compile))
        return stack

    def test_complete_atlas_payloads_and_export_for_default_boundary_and_maximum_domain(self):
        cases = ((KleinFieldRecipe(), HadamardBinding()),
                 (KleinFieldRecipe(width=3, height=3, center=8, radius=1, turns=(0, 128, 255)),
                  HadamardBinding(((4, -4), (-4, 4), (0, 4), (-4, 0)))),
                 (KleinFieldRecipe(width=16, height=16, center=255), HadamardBinding()))
        for recipe, binding in cases:
            with self.subTest(size=(recipe.width, recipe.height)):
                fields, neighbors, penalties, increments, seams = oracle(recipe, binding)
                with no_cpu_routing():
                    owner = self.executor(recipe, binding)
                model, count = owner.routing_model, len(fields)
                self.assertEqual((model.neighbors, model.penalties, model.increments),
                                 (neighbors, penalties, increments))
                self.assertEqual(owner.fields, fields)
                data = owner._device.queue.read_texture(
                    {"texture": owner._texture, "origin": (0, 0, 0)},
                    {"offset": 0, "bytes_per_row": 256, "rows_per_image": 4 * count}, (24, 4 * count, 1))
                for source in range(count):
                    row = owner.index.resolve(source)
                    for bank in range(4):
                        for slot, destination in enumerate(neighbors[source]):
                            penalty = penalties[16 * source + 4 * bank + slot]
                            for column in range(3):
                                offset = 256 * (bank * count + row) + 4 * (6 * slot + 2 * column)
                                movement, cost_word = struct.unpack_from("<2I", data, offset)
                                self.assertEqual(unpack(movement),
                                                 (recipe.turns[column], destination, fields[destination],
                                                  int(Opcode.STEP) | seams[source, destination] << 6))
                                self.assertEqual(unpack(cost_word), (bank, source, penalty, int(Opcode.DATA)))
                self.assertFalse(hasattr(model, "fields"))

    def test_scratch_bank_selection_all_boundaries_and_mirrored_frames(self):
        owner = self.executor()
        recipe, binding = owner.recipe, owner.routing_model.binding
        fields, neighbors, *_ = oracle(recipe, binding)
        owner.seed(initial(fields), 100)
        for source in (7, 16):
            for t in (0, 1, 63, 64, 65, 127, 128, 191, 192, 255):
                for eta in (0, 1):
                    for destination in neighbors[source]:
                        seed = initial(fields, source, t, eta)
                        expected = predict(recipe, binding, seed, (destination,), (127,))
                        path = owner._nodes[destination]
                        self.assertEqual(owner.forecast(seed, (path,), (127,)), expected)
        self.assertEqual(owner.snapshot(), (initial(fields), 100))

    def test_actual_persistent_actions_and_evolving_scratch_cross_banks_and_seams(self):
        recipe = KleinFieldRecipe(turns=(63, 64, 65))
        binding = HadamardBinding(((4, -4), (-4, 4), (-3, -2), (2, 3)))
        # Repeated seam moves and reversals cross bank boundaries in the history.
        destinations = (15, 0, 4, 16, 17, 18, 19, 15, 0)
        hazards = (0, 1, 7, 127, 3, 0, 9, 2, 0)
        fields = oracle(recipe, binding)[0]
        for eta in (0, 1):
            seed = initial(fields, t=63, eta=eta)
            expected = predict(recipe, binding, seed, destinations, hazards)
            with no_cpu_routing():
                owner = self.executor(recipe, binding)
                owner.seed(seed, 10000)
                paths = tuple(owner._nodes[node] for node in destinations)
                self.assertEqual(owner.forecast(seed, paths, hazards), expected)
                energy = 10000
                for path, hazard, value, cost in zip(paths, hazards, *expected):
                    energy -= cost
                    self.assertEqual(owner.advance_to(path, hazard), (value, cost, energy))
                    self.assertEqual(owner.snapshot(), (value, energy))
                emitted, remaining = owner.repair(5)
                self.assertEqual(unpack(unpair(emitted)[0])[:3], unpack(unpair(expected[0][-1])[0])[:3])
                self.assertEqual(remaining, energy - 5)

    def test_literal_reference_actions_preserve_full_pairs_and_hp_energy(self):
        reference = json.loads((Path(__file__).resolve().parents[1] /
                                "docs/evidence/hadamard-v1/formal-reference.json").read_text())
        owner = self.executor()
        mission = reference["mission"]
        owner.seed(int(mission["initial"]["pair"], 16), mission["initial"]["energy"])
        for event in mission["events"]:
            if event["kind"] == "MOVE":
                path = owner._nodes[event["route"][0]]
                value, cost, energy = owner.advance_to(path, event["input"][path])
                self.assertEqual(cost, event["action"]["cost"])
            else:
                value, energy = owner.repair(5)
            self.assertEqual((f"{value:016X}", energy), (event["pair"], event["energy"]))
        self.assertEqual(energy, 86)

    def test_zero_gain_matches_v1_and_index_rebuild_retains_shared_model(self):
        recipe = KleinFieldRecipe()
        owner = self.executor(recipe, HadamardBinding(((0, 0),) * 4))
        old = GpuFieldAgentExecutor(recipe)
        self.addCleanup(old.close)
        seed = initial(owner.fields)
        route, hazards = ("k:0:4", "k:3:1", "k:3:2"), (0, 0, 0)
        owner.seed(seed, 100)
        old.seed(seed, 100)
        model = owner.routing_model
        expected = old.forecast(seed, route, hazards)
        for sign, origin in ((-1, 255), (1, 42), (-1, 64)):
            with no_cpu_routing():
                owner.reindex(psi_sign=sign, phase_origin=origin)
                self.assertIs(owner.routing_model, model)
                self.assertEqual(owner.forecast(seed, route, hazards), expected)
                self.assertEqual(owner.snapshot(), (seed, 100))
        for path in route:
            self.assertEqual(owner.advance_to(path, 0), old.advance_to(path, 0))
        self.assertEqual(owner.repair(5), old.repair(5))

    def test_every_unselected_bank_neighbor_and_class_copy_is_certified(self):
        owner = self.executor()
        seed = initial(owner.fields)
        owner.seed(seed, 100)
        old, model, count = owner._bundle, owner.routing_model, len(owner.fields)
        source = 7  # Not the seeded node; every atlas location still participates.
        for movement in (False, True):
            for bank in range(4):
                for slot in range(4):
                    for column in range(3):
                        with self.subTest(movement=movement, bank=bank, slot=slot, column=column):
                            def corrupt(bundle):
                                x = 6 * slot + 2 * column
                                y = bank * count + bundle.index.resolve(source)
                                destination = model.neighbors[source][slot]
                                if movement:
                                    tau = oracle(owner.recipe, model.binding)[4][source, destination]
                                    word = pack(owner.recipe.turns[column] ^ 1, destination,
                                                owner.fields[destination], 1 | tau << 6)
                                else:
                                    penalty = model.penalties[16 * source + 4 * bank + slot]
                                    word = pack(bank, source, penalty + 1, Opcode.DATA)
                                    x += 1
                                self.write_texel(owner, bundle, x, y, word)
                            with self.candidate_injection(owner, corrupt):
                                with self.assertRaisesRegex(ValueError, "atlas rejected"):
                                    owner.reindex(psi_sign=-1)
                            self.assertIs(owner._bundle, old)
                            self.assertIs(owner.routing_model, model)
                            self.assertFalse(owner.failed)
                            self.assertFalse(owner._closed)
        self.assertEqual(owner.snapshot(), (seed, 100))
        self.assertEqual(owner.forecast(seed, ("k:0:1",), (0,)),
                         predict(owner.recipe, model.binding, seed, (1,), (0,)))

    def test_full_cost_and_movement_payloads_and_parity_are_decoded(self):
        owner = self.executor()
        old = owner._bundle
        source, bank, slot, column = 16, 3, 2, 2
        model = owner.routing_model
        destination = model.neighbors[source][slot]
        tau = oracle(owner.recipe, model.binding)[4][source, destination]
        cost = (bank, source, model.penalties[16 * source + 4 * bank + slot], 0)
        movement = (owner.recipe.turns[column], destination, owner.fields[destination], 1 | tau << 6)
        changes = []
        for kind, lanes in (("cost", cost), ("movement", movement)):
            for lane in range(4):
                changed = list(lanes)
                changed[lane] = changed[lane] ^ 1
                changes.append((kind, pack(*changed)))
            changes.append((kind, pack(*lanes) ^ (1 << 31)))
        changes += [("cost", pack(bank, source, -1, 0)), ("cost", pack(bank, source, 81, 0))]
        for kind, word in changes:
            with self.subTest(kind=kind, word=word):
                def corrupt(bundle):
                    self.write_texel(owner, bundle, 6 * slot + 2 * column + (kind == "cost"),
                                     bank * len(owner.fields) + bundle.index.resolve(source), word)
                with self.candidate_injection(owner, corrupt), self.assertRaises(ValueError):
                    owner.reindex()
                self.assertIs(owner._bundle, old)
                self.assertFalse(owner.failed)
                self.assertFalse(owner._closed)

    def test_host_certificate_rejects_corrupt_export_and_compiled_wrong_gains(self):
        owner = self.executor()
        old = owner._bundle
        original_read = owner._device.queue.read_buffer
        for component in ("penalty", "increment"):
            def corrupt_export(buffer, *args, **kwargs):
                result = original_read(buffer, *args, **kwargs)
                if buffer.size == 68 * len(owner.fields):
                    result = bytearray(result)
                    index = 0 if component == "penalty" else 16 * len(owner.fields)
                    struct.pack_into("<I", result, 4 * index,
                                     struct.unpack_from("<I", result, 4 * index)[0] ^ 1)
                return result
            with patch.object(owner._device.queue, "read_buffer", side_effect=corrupt_export), \
                    self.assertRaises(ValueError):
                owner.reindex()
            self.assertIs(owner._bundle, old)
            self.assertFalse(owner.failed)
        write = owner._device.queue.write_buffer
        def wrong_gains(buffer, offset, data, *args, **kwargs):
            if buffer.size == 32:
                data = struct.pack("<8i", 0, 0, 0, 0, 0, 0, 0, 0)
            return write(buffer, offset, data, *args, **kwargs)
        with patch.object(owner._device.queue, "write_buffer", side_effect=wrong_gains), \
                self.assertRaisesRegex(ValueError, "penalty"):
            owner.reindex()
        self.assertIs(owner._bundle, old)
        self.assertFalse(owner.failed)
        self.assertEqual(owner.lookup_node(0), owner.index.resolve(0))

    def test_invalid_input_and_energy_rejection_precede_any_device_write(self):
        with patch("solvefinite.field_agent_gpu.GpuFieldExecutor", side_effect=AssertionError("allocation")):
            for routing in ({}, True, IndexBinding()):
                with self.assertRaises(ValueError):
                    GpuFieldAgentExecutor(KleinFieldRecipe(), routing=routing)
        owner = self.executor()
        seed = initial(owner.fields, source=7, t=0)
        owner.seed(seed, 0)
        with patch.object(owner._device.queue, "write_buffer", side_effect=AssertionError("write")):
            with self.assertRaises(EnergyExhausted):
                owner.advance_to(owner._nodes[owner.routing_model.neighbors[7][0]], 0)
            for operation in (lambda: owner.reindex(psi_sign=True),
                              lambda: owner.forecast(seed, ("k:0:0",), (0,)),
                              lambda: owner.advance_to("k:1:2", True)):
                with self.assertRaises(ValueError):
                    operation()
        self.assertFalse(owner.failed)
        self.assertEqual(owner.snapshot(), (seed, 0))

    def test_uncertain_dispatch_and_each_candidate_readback_close_without_admission(self):
        for fault in ("dispatch", "records", "rows", "status", "table", "short_index", "short_table"):
            with self.subTest(fault=fault):
                owner = self.executor()
                old = owner._bundle
                seed = initial(owner.fields)
                owner.seed(seed, 100)
                read = owner._device.queue.read_buffer
                calls = []
                def fail_read(buffer, *args, **kwargs):
                    calls.append(buffer)
                    index = {"records": 1, "rows": 2, "status": 3, "table": 4,
                             "short_index": 1, "short_table": 4}.get(fault)
                    if len(calls) == index:
                        if fault.startswith("short"):
                            return bytes(buffer.size - (32 if fault == "short_index" else 4))
                        raise RuntimeError("uncertain read")
                    return read(buffer, *args, **kwargs)
                target = patch.object(owner, "_dispatch", side_effect=RuntimeError("uncertain dispatch")) \
                    if fault == "dispatch" else patch.object(owner._device.queue, "read_buffer", side_effect=fail_read)
                with target, self.assertRaises((RuntimeError, ValueError, struct.error)):
                    owner.reindex(phase_origin=42)
                self.assertIs(owner._bundle, old)
                self.assertTrue(owner.failed)
                self.assertTrue(owner._closed)
                self.assertTrue(owner._geometry._closed)
                self.assertEqual((owner._pair, owner._energy, owner._ticks), (seed, 100, 0))

    def test_partial_gains_or_export_table_allocation_destroys_candidate_and_keeps_old_usable(self):
        owner = self.executor()
        seed = initial(owner.fields)
        owner.seed(seed, 100)
        old, model = owner._bundle, owner.routing_model
        create = owner._device.create_buffer
        # config, records, tree, status, gains, exported table are allocated in order.
        for failed_allocation in (5, 6):
            with self.subTest(failed_allocation=failed_allocation):
                allocated = []

                def fail_resource(**kwargs):
                    if len(allocated) + 1 == failed_allocation:
                        raise RuntimeError("routing candidate allocation")
                    resource = create(**kwargs)
                    resource.destroy = Mock(wraps=resource.destroy)
                    allocated.append(resource)
                    return resource

                with patch.object(owner._device, "create_buffer", side_effect=fail_resource), \
                        patch.object(owner._device.queue, "write_buffer", side_effect=AssertionError("premature write")), \
                        self.assertRaisesRegex(RuntimeError, "routing candidate allocation"):
                    owner.reindex(psi_sign=-1)
                self.assertEqual(len(allocated), failed_allocation - 1)
                for resource in allocated:
                    resource.destroy.assert_called_once_with()
                self.assertIs(owner._bundle, old)
                self.assertIs(owner.routing_model, model)
                self.assertFalse(owner.failed)
                self.assertFalse(owner._closed)
                self.assertFalse(old.closed)
                self.assertEqual(owner.snapshot(), (seed, 100))
                self.assertEqual(owner.lookup_node(0), old.index.resolve(0))
        value, cost, energy = owner.advance_to("k:0:4", 0)
        expected, costs = predict(owner.recipe, model.binding, seed, (4,), (0,))
        self.assertEqual((value, cost, energy), (expected[0], costs[0], 100 - costs[0]))

    def test_uncertain_actual_result_closes_without_admitting_host_state(self):
        owner = self.executor()
        seed = initial(owner.fields)
        owner.seed(seed, 100)
        with patch.object(owner._device.queue, "read_buffer", side_effect=RuntimeError("actual readback")), \
                self.assertRaisesRegex(RuntimeError, "actual readback"):
            owner.advance_to("k:0:4", 0)
        self.assertTrue(owner.failed)
        self.assertTrue(owner._closed)
        self.assertEqual((owner._pair, owner._energy, owner._ticks), (seed, 100, 0))

    def test_valid_parity_wrong_live_cost_closes_without_admitting_host_state(self):
        owner = self.executor()
        source, t = 7, 64
        seed = initial(owner.fields, source, t)
        owner.seed(seed, 100)
        destination = owner.routing_model.neighbors[source][0]
        column = (owner.fields[source] > 0) - (owner.fields[source] < 0) + 1
        penalty = owner.routing_model.penalty(source, t, destination)
        self.write_texel(owner, owner._bundle, 2 * column + 1,
                         len(owner.fields) + owner.index.resolve(source), pack(1, source, penalty + 1, 0))
        with self.assertRaisesRegex(ValueError, "movement disagrees"):
            owner.advance_to(owner._nodes[destination], 0)
        self.assertTrue(owner.failed)
        self.assertTrue(owner._closed)
        self.assertEqual((owner._pair, owner._energy, owner._ticks), (seed, 100, 0))

    def test_post_swap_cleanup_reports_committed_and_attempts_all_routing_resources(self):
        owner = self.executor()
        old, model = owner._bundle, owner.routing_model
        destroy = old.gains.destroy
        old.gains.destroy = Mock(side_effect=RuntimeError("retired gains"))
        for resource in (old.routing_table, old.texture):
            resource.destroy = Mock(wraps=resource.destroy)
        try:
            with self.assertRaises(CommittedIndexCleanupError) as caught:
                owner.reindex(phase_origin=12)
            self.assertTrue(caught.exception.committed)
            self.assertEqual(owner.index.binding.epoch, 1)
            self.assertIs(owner.routing_model, model)
            self.assertIsNot(owner._bundle, old)
            self.assertTrue(owner._closed)
            self.assertTrue(owner.failed)
            self.assertTrue(owner._bundle.closed)
            for resource in (old.routing_table, old.texture):
                resource.destroy.assert_called_once_with()
        finally:
            destroy()

    def test_complete_live_and_old_plus_candidate_payload_accounting(self):
        owner = self.executor()
        count = len(owner.fields)
        before = owner.allocation_info
        self.assertEqual(before["routing_atlas_bytes"], 384 * count)
        self.assertEqual(before["device_texture_bytes"], 396 * count)
        self.assertEqual(before["device_routing_table_payload_bytes"], 68 * count)
        self.assertEqual(before["host_routing_table_payload_bytes"], 68 * count)
        self.assertEqual(before["device_routing_gains_payload_bytes"], 32)
        self.assertEqual(before["device_payload_bytes"], before["peak_rebuild_device_payload_bytes"])
        bundle_payload = sum(buffer.size for buffer in owner._bundle.buffers) + 384 * count
        model = owner.routing_model
        owner.reindex(psi_sign=-1)
        after = owner.allocation_info
        self.assertEqual(after["device_payload_bytes"], before["device_payload_bytes"])
        self.assertEqual(after["peak_rebuild_device_payload_bytes"], before["device_payload_bytes"] + bundle_payload)
        self.assertEqual(after["peak_rebuild_host_routing_payload_bytes"], 136 * count)
        self.assertEqual(after["peak_rebuild_host_index_payload_bytes"], 2 * (64 * count + 16))
        self.assertIs(owner.routing_model, model)


if __name__ == "__main__":
    unittest.main()
