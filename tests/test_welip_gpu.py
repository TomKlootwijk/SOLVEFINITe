"""W7 actual-owner emission, retained completion and uncertainty admission."""

from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from solvefinite.field_agent import (
    FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, FieldAgentManifest,
)
from solvefinite.field_agent_gpu import GpuFieldAgentExecutor, MalformedWelipEmissionError
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.hadamard import HadamardBinding
from solvefinite.rp32 import Opcode, pack, pair, unpair
from solvefinite.tomigidt import AgentManifest, Tomigidt
from tests.test_organogram_gpu import forbid_organogram_producers


REFERENCE = json.loads((Path(__file__).resolve().parents[1] /
    "docs/evidence/welip-v1/formal-reference.json").read_text(encoding="utf-8"))
POLICIES = (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY)


def expected_words(value, tick):
    """Separate byte-layout arithmetic, independent of the W implementation."""
    payload = struct.pack("<Q", value)
    phase, _, _, metadata = struct.unpack("<BBbB", payload[:4])
    intrinsic = (-phase if metadata & 16 else phase) % 256
    prefix = struct.pack(">HH", tick, intrinsic * 256).hex().upper()
    return intrinsic * 256, [prefix + payload[i:i+4][::-1].hex().upper() for i in (0, 4)]


def no_cpu_state_producers():
    stack = ExitStack()
    stack.enter_context(forbid_organogram_producers())
    for name in ("solvefinite.welip.encode_state", "solvefinite.tomigidt.regenerate"):
        stack.enter_context(patch(name, side_effect=AssertionError("CPU fallback: " + name)))
    return stack


def cache(owner):
    world = owner.world
    return (world.capacity, world.active_paths, world.evicted_paths,
            world.hit_count, world.regeneration_count)


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class WelipGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.addClassCleanup(cls.probe.close)

    def executor(self, routing=None, *, seed=True):
        executor = GpuFieldAgentExecutor(KleinFieldRecipe(), routing=routing)
        self.addCleanup(executor.close)
        if seed:
            executor.seed(pair(pack(250, 0, executor.fields[0], Opcode.STEP)), 100)
        return executor

    def owner(self, manifest=None, *, backend="gpu", capacity=3):
        owner = Tomigidt(manifest or FieldAgentManifest(), backend=backend, capacity=capacity)
        self.addCleanup(owner.close)
        return owner

    def test_all_four_policies_emit_through_growth_and_retained_completion(self):
        for policy in POLICIES:
            with self.subTest(policy=policy):
                manifest = FieldAgentManifest(policy=policy)
                cpu = self.owner(manifest, backend="cpu")
                frames, states = [], []
                while cpu.status != "COMPLETE":
                    self.assertLess(cpu.cycle, 40)
                    frame = {path: (70 if path == "k:0:3" and cpu.geometry_epoch == 0 else 0)
                             for path in cpu.visible_paths}
                    frames.append(frame)
                    cpu.step(frame)
                    states.append((cpu.agent_pair, cpu.energy, cpu.geometry_epoch, cpu.archive()))
                with no_cpu_state_producers():
                    gpu = self.owner(manifest)
                    self.assertEqual(gpu.emit_welip_state(65535), expected_words(gpu.agent_pair, 65535))
                    with patch.object(GpuFieldAgentExecutor, "seed", side_effect=AssertionError("host reseed")):
                        for index, (frame, state) in enumerate(zip(frames, states)):
                            before_epoch = gpu.geometry_epoch
                            gpu.step(frame)
                            self.assertEqual((gpu.agent_pair, gpu.energy, gpu.geometry_epoch, gpu.archive()), state)
                            before = gpu.archive(), cache(gpu), gpu._gpu._ticks
                            self.assertEqual(gpu.emit_welip_state(index), expected_words(state[0], index))
                            self.assertEqual((gpu.archive(), cache(gpu), gpu._gpu._ticks), before)
                            if gpu.geometry_epoch != before_epoch:
                                self.assertEqual(gpu._gpu._ticks, 0)
                    self.assertEqual(gpu.status, "COMPLETE")
                    self.assertTrue(gpu._gpu._terminal)
                    self.assertEqual(gpu.emit_welip_state(0), expected_words(gpu.agent_pair, 0))
                    self.assertEqual(gpu._gpu.snapshot(), (gpu.agent_pair, gpu.energy))
                    gpu.close()
                cpu.close()

    def test_frozen_17_operation_carriers_and_cache_controls_are_actual_gpu(self):
        for key in ("main_lifecycle", "mirrored_lifecycle", "capacity8_lifecycle"):
            literal = REFERENCE[key]
            with self.subTest(key=key), no_cpu_state_producers():
                owner = self.owner(AgentManifest.from_dict(literal["config"]["agent"]))
                with patch.object(GpuFieldAgentExecutor, "seed", side_effect=AssertionError("host reseed")):
                    for row, action in zip(literal["operations"], literal["executor_action_tick_expectations"]):
                        request = row["request"]
                        removed = []
                        if request["op"] == "ADVANCE":
                            owner.step(request["observations"])
                        elif request["op"] == "RESIZE":
                            removed = owner.resize_welip_cache(request["capacity"])
                        elif request["op"] == "INVALIDATE":
                            removed = owner.invalidate_welip_cache(request["paths"])
                        frozen = owner.archive(), cache(owner)
                        record = row["records"][-1]
                        self.assertEqual(owner.emit_welip_state(request["tick16"]),
                                         (record["phase16"], record["words"]))
                        self.assertEqual((owner.archive(), cache(owner)), frozen)
                        self.assertEqual(owner._gpu._ticks, action["executor_action_ticks"])
                        self.assertEqual(f"{owner.agent_pair:016X}", row["agent_pair"])
                        self.assertEqual(owner.energy, row["energy"])
                        expected = row["cache"]
                        self.assertEqual((owner.world.capacity, owner.world.active_paths,
                            owner.world.hit_count, owner.world.regeneration_count),
                            (expected["capacity"], tuple(expected["active_paths"]),
                             expected["hit_count"], expected["regeneration_count"]))
                        self.assertEqual(len(owner.world.evicted_paths), expected["evicted_count"])
                        self.assertEqual(removed, expected["removed"])
                owner.close()

    def test_upload_is_only_clock_and_reserved_zero_and_no_canonical_write(self):
        executor = self.executor()
        before = bytes(executor._device.queue.read_buffer(executor._canonical))
        queue = executor._device.queue
        with patch.object(queue, "write_buffer", wraps=queue.write_buffer) as writes:
            result = executor.emit_welip(65535)
        self.assertEqual(result, expected_words(executor._pair, 65535))
        writes.assert_called_once_with(executor._jobs, 0, struct.pack("<2I", 65535, 0))
        self.assertEqual(bytes(queue.read_buffer(executor._canonical)), before)

    def test_strict_clock_unseeded_and_closed_reject_before_dispatch(self):
        executor = self.executor(seed=False)
        with patch.object(executor, "_dispatch", side_effect=AssertionError("unexpected dispatch")):
            with self.assertRaisesRegex(ValueError, "seeded"):
                executor.emit_welip(0)
            executor.seed(pair(pack(250, 0, executor.fields[0], Opcode.STEP)), 100)
            for tick in (True, -1, 65536, 1.0, "1", None):
                with self.subTest(tick=tick), self.assertRaises(ValueError):
                    executor.emit_welip(tick)
            self.assertFalse(executor.failed)
            executor.close()
            with self.assertRaisesRegex(ValueError, "closed"):
                executor.emit_welip(0)

    def test_complete_corruption_of_each_output_lane_is_pure_and_retryable(self):
        owner = self.owner()
        executor = owner._gpu
        reader = executor._read_outputs
        before = owner.archive(), cache(owner), executor.snapshot(), executor._ticks
        for lane in range(8):
            def damaged(count, lane=lane):
                row = list(reader(count)[0]); row[lane] ^= 1
                return (tuple(row),)
            with self.subTest(lane=lane), patch.object(executor, "_read_outputs", side_effect=damaged):
                with self.assertRaises(MalformedWelipEmissionError) as caught:
                    owner.emit_welip_state(9)
                self.assertFalse(caught.exception.device_uncertain)
            self.assertFalse(owner.closed)
            self.assertFalse(executor.failed)
            self.assertEqual((owner.archive(), cache(owner), executor.snapshot(), executor._ticks), before)
            self.assertEqual(owner.emit_welip_state(9), expected_words(owner.agent_pair, 9))

    def test_dispatch_and_incomplete_reads_close_field_and_hadamard_owners(self):
        for policy in (FIELD_POLICY, HADAMARD_POLICY):
            for failure in ("dispatch", "output", "canonical", "read"):
                with self.subTest(policy=policy, failure=failure):
                    owner = self.owner(FieldAgentManifest(policy=policy))
                    executor = owner._gpu
                    queue = executor._device.queue
                    original = queue.read_buffer
                    def read(buffer, *args, **kwargs):
                        if failure == "read":
                            raise RuntimeError("uncertain read")
                        data = original(buffer, *args, **kwargs)
                        if buffer is (executor._output if failure == "output" else executor._canonical):
                            return data[:-1]
                        return data
                    if failure == "dispatch":
                        guard = patch.object(executor, "_dispatch", side_effect=RuntimeError("uncertain dispatch"))
                    else:
                        guard = patch.object(queue, "read_buffer", side_effect=read)
                    with guard, self.assertRaises((ValueError, RuntimeError, struct.error)) as caught:
                        owner.emit_welip_state(9)
                    self.assertTrue(caught.exception.device_uncertain)
                    self.assertTrue(executor.failed)
                    self.assertTrue(executor._closed)
                    self.assertTrue(owner.closed)

    def test_shader_rejects_parity_mirror_node_field_metadata_and_energy_corruption(self):
        for damage in ("parity", "mirror", "node", "field", "metadata", "energy", "ticks"):
            with self.subTest(damage=damage):
                executor = self.executor()
                left, right = unpair(executor._pair)
                energy, ticks = 100, 0
                if damage == "parity": left ^= 1
                elif damage == "mirror": right = pack(7, 0, executor.fields[0], 17)
                elif damage == "node": left, right = unpair(pair(pack(250, 255, 0, Opcode.STEP)))
                elif damage == "field": left, right = unpair(pair(pack(250, 0, 1, Opcode.STEP)))
                elif damage == "metadata": left, right = unpair(pair(pack(250, 0, executor.fields[0], Opcode.DATA)))
                elif damage == "energy": energy = 1 << 31
                elif damage == "ticks": ticks = 1
                queue = executor._device.queue
                queue.write_buffer(executor._canonical, 0, struct.pack("<4I", left, right, energy, ticks))
                queue.write_buffer(executor._jobs, 0, struct.pack("<2I", 3, 0))
                executor._dispatch(executor._pipelines["emit_welip"], executor._groups["emit_welip"])
                row, = executor._read_outputs(1)
                self.assertEqual(row[6], 1 if damage == "ticks" else 0)
                with self.assertRaises(ValueError) as caught:
                    executor.emit_welip(3)
                self.assertTrue(caught.exception.device_uncertain)
                self.assertTrue(executor.failed)
                self.assertTrue(executor._closed)

    def test_owner_and_executor_disagreement_closes_without_replacing_device_state(self):
        owner = self.owner()
        owner._energy -= 1
        with patch.object(owner._gpu, "emit_welip", side_effect=AssertionError("must reject owner mismatch")):
            with self.assertRaisesRegex(ValueError, "owning individual"):
                owner.emit_welip_state(1)
        self.assertTrue(owner.closed)
        self.assertTrue(owner._gpu._closed)

    def test_cpu_wrapper_uses_codec_and_field_only_controls_preserve_history(self):
        owner = self.owner(backend="cpu")
        before = owner.archive()
        with patch("solvefinite.welip.encode_state", return_value=(123, ["sentinel"])) as codec:
            self.assertEqual(owner.emit_welip_state(7), (123, ["sentinel"]))
        codec.assert_called_once_with(owner.agent_pair, 7)
        for path in ("k:0:0", "k:0:1", "k:0:2"):
            owner.world.get(path)
        self.assertEqual(owner.resize_welip_cache(2), ["k:0:0"])
        self.assertEqual(owner.invalidate_welip_cache(["k:0:2"]), ["k:0:2"])
        self.assertEqual(owner.archive(), before)
        for capacity in (True, 0, 257):
            with self.assertRaises(ValueError): owner.resize_welip_cache(capacity)
        binary = self.owner(AgentManifest(), backend="cpu")
        for method, argument in ((binary.emit_welip_state, 0), (binary.resize_welip_cache, 1),
                                 (binary.invalidate_welip_cache, ["0"])):
            with self.assertRaises(ValueError): method(argument)


if __name__ == "__main__":
    unittest.main()
