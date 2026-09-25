"""Optional integer-texture execution of the existing RP32 application profile.

GPU lanes derive nodes of one world, not separate agents. The immutable packed
operator texture and resident world table survive dispatches. Python still
admits observations, searches routes and journals the selected transition.
"""

from __future__ import annotations

from pathlib import Path
import struct
from time import perf_counter

from .motion import EnergyExhausted
from .rp32 import Opcode, pack, unpack, unpair
from .world import Node, World, WorldConfig, _path


class GpuUnavailable(ValueError):
    """The explicitly requested hardware GPU backend cannot be initialized."""


class GpuExecutor:
    """A finite resident world arena and one agent's sequential forecasts.

    This synchronous object has one owner, just like Tomigidt. ``nodes`` is a
    host witness of GPU-derived results, separate from the bounded World FIFO.
    No CPU computation substitutes for a failed GPU dispatch.
    """

    def __init__(self, config: WorldConfig, paths):
        if type(config) is not WorldConfig:
            raise ValueError("config must be a WorldConfig")
        if isinstance(paths, (str, bytes)):
            raise ValueError("paths must be a sequence of binary paths")
        try:
            paths = tuple(paths)
        except TypeError as exc:
            raise ValueError("paths must be an iterable of binary paths") from exc
        if not 1 <= len(paths) <= 1_048_576:
            raise ValueError("GPU world arena requires 1..1048576 paths")
        for path in paths:
            _path(path, config.max_depth)
        if len(set(paths)) != len(paths):
            raise ValueError("GPU world paths must be unique")
        try:
            import wgpu
        except ImportError as exc:
            raise GpuUnavailable("GPU backend requires: python -m pip install -r requirements-gpu.txt") from exc
        self._wgpu = wgpu
        self.config = config
        self.paths = paths
        self._indices = {path: index for index, path in enumerate(paths)}
        self._device = None
        self._buffers = []
        self._texture = None
        self._closed = False
        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            if adapter is None or adapter.info.get("adapter_type") not in ("DiscreteGPU", "IntegratedGPU"):
                raise GpuUnavailable("A hardware GPU is required; software adapters are not accepted")
            self.adapter_info = dict(adapter.info)
            self._device = adapter.request_device_sync()
        except Exception as exc:
            if isinstance(exc, GpuUnavailable):
                raise
            raise GpuUnavailable(f"Unable to initialize a hardware GPU: {exc}") from exc
        try:
            self._initialize()
        except BaseException:
            self.close()
            raise

    def _buffer(self, size, usage, data=None):
        buffer = self._device.create_buffer(size=size, usage=usage)
        self._buffers.append(buffer)
        if data is not None:
            self._device.queue.write_buffer(buffer, 0, data)
        return buffer

    def _initialize(self):
        wgpu, device = self._wgpu, self._device
        usage = wgpu.BufferUsage
        shared = usage.STORAGE | usage.COPY_DST | usage.COPY_SRC
        self._texture = device.create_texture(
            size=(2, 4, 1), format="r32uint",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        operators = [pack(delta, branch + 1, 0, Opcode.GROW)
                     for row in self.config.phase_turns for branch, delta in enumerate(row)]
        device.queue.write_texture(
            {"texture": self._texture}, struct.pack("<8I", *operators),
            {"bytes_per_row": 8, "rows_per_image": 4}, (2, 4, 1))
        field0, field1 = (max(-255, min(255, value)) for value in self.config.field_changes)
        config_data = struct.pack("<IiiI", pack(*self.config.seed), field0, field1, len(self.paths))
        self._derive_config = self._buffer(16, shared, config_data)
        self._forecast_config = self._buffer(16, shared, config_data)
        descriptors = bytearray(16 * len(self.paths))
        for index, path in enumerate(self.paths):
            struct.pack_into("<4I", descriptors, 16 * index, int(path or "0", 2), len(path), 0, 0)
        self._derive_jobs = self._buffer(len(descriptors), shared, descriptors)
        self._forecast_jobs = self._buffer(32 * 16, shared)
        self._resident_nodes = self._buffer(16 * len(self.paths), shared)
        self._output = self._buffer(32 * 16, shared)
        self._state = self._buffer(16, shared)
        self._canonical = self._buffer(8, shared)
        shader = device.create_shader_module(code=Path(__file__).with_name("shaders").joinpath("packed.wgsl").read_text(encoding="utf-8"))
        entries = [{"binding": 0, "visibility": wgpu.ShaderStage.COMPUTE,
                    "texture": {"sample_type": "uint", "view_dimension": "2d"}}]
        for binding in range(1, 6):
            entries.append({"binding": binding, "visibility": wgpu.ShaderStage.COMPUTE,
                            "buffer": {"type": "read-only-storage" if binding < 3 else "storage"}})
        layout = device.create_bind_group_layout(entries=entries)
        pipeline_layout = device.create_pipeline_layout(bind_group_layouts=[layout])
        self._derive_pipeline = device.create_compute_pipeline(
            layout=pipeline_layout, compute={"module": shader, "entry_point": "derive"})
        self._forecast_pipeline = device.create_compute_pipeline(
            layout=pipeline_layout, compute={"module": shader, "entry_point": "forecast"})
        texture_view = self._texture.create_view()

        def group(config, jobs):
            buffers = (config, jobs, self._resident_nodes, self._output, self._state)
            return device.create_bind_group(layout=layout, entries=[
                {"binding": 0, "resource": texture_view},
                *({"binding": binding, "resource": {"buffer": buffer, "offset": 0, "size": buffer.size}}
                  for binding, buffer in enumerate(buffers, 1))])

        self._derive_group = group(self._derive_config, self._derive_jobs)
        self._forecast_group = group(self._forecast_config, self._forecast_jobs)
        self._dispatch(self._derive_pipeline, self._derive_group, (len(self.paths) + 63) // 64)
        raw = device.queue.read_buffer(self._resident_nodes)
        nodes = []
        for path, (left, right, _, _) in zip(self.paths, struct.iter_unpack("<4I", raw)):
            paired = left | (right << 32)
            unpair(paired)
            nodes.append(Node(path, paired, len(path)))
        self.nodes = tuple(nodes)

    def _check_open(self):
        if self._closed:
            raise ValueError("GPU executor is closed")

    def _dispatch(self, pipeline, group, count):
        self._check_open()
        encoder = self._device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(pipeline)
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups(count)
        compute.end()
        self._device.queue.submit([encoder.finish()])

    def commit_pair(self, agent_pair: int):
        """Keep a device copy of the single admitted pair, separate from forecasts."""
        self._check_open()
        left, right = unpair(agent_pair)
        self._device.queue.write_buffer(self._canonical, 0, struct.pack("<2I", left, right))

    def forecast(self, agent_pair: int, paths, hazards):
        self._check_open()
        left, right = unpair(agent_pair)
        if unpack(left)[2] < 0:
            raise EnergyExhausted("Agent energy is negative")
        if isinstance(paths, (str, bytes)) or isinstance(hazards, (str, bytes)):
            raise ValueError("Forecast paths and hazards must be sequences")
        try:
            paths, hazards = tuple(paths), tuple(hazards)
        except TypeError as exc:
            raise ValueError("Forecast paths and hazards must be iterable") from exc
        if len(paths) != len(hazards) or len(paths) > 32:
            raise ValueError("Forecast requires matching paths and hazards with at most 32 steps")
        jobs = bytearray(16 * len(paths))
        for index, (path, hazard) in enumerate(zip(paths, hazards)):
            _path(path, self.config.max_depth)
            if path not in self._indices:
                raise ValueError("Forecast path is outside the resident world arena")
            if type(hazard) is not int or not 0 <= hazard <= 127:
                raise ValueError("hazard must be an integer in [0, 127]")
            struct.pack_into("<4I", jobs, index * 16, self._indices[path], int(path[-1]) if path else 0, hazard, 0)
        if not paths:
            return (), ()
        queue = self._device.queue
        queue.write_buffer(self._forecast_config, 12, struct.pack("<I", len(paths)))
        queue.write_buffer(self._forecast_jobs, 0, jobs)
        queue.write_buffer(self._state, 0, struct.pack("<4I", left, right, 0, 0))
        self._dispatch(self._forecast_pipeline, self._forecast_group, 1)
        raw = queue.read_buffer(self._output, 0, 16 * len(paths))
        pairs, costs = [], []
        for path, (low, high, cost, status) in zip(paths, struct.iter_unpack("<4I", raw)):
            if status == 1:
                raise EnergyExhausted(f"Insufficient energy to enter waypoint {path!r}")
            if status != 0:
                raise ValueError("GPU returned an unknown transition status")
            paired = low | (high << 32)
            unpair(paired)
            pairs.append(paired)
            costs.append(cost)
        return tuple(pairs), tuple(costs)

    def benchmark(self, repeats: int = 20) -> dict:
        """Repeat the resident derivation workload; include submit and readback time.

        Inputs are uploaded during construction and reused for every dispatch.
        This is a substrate benchmark, not an autonomous-agent throughput test.
        """
        self._check_open()
        if type(repeats) is not int or not 1 <= repeats <= 1000:
            raise ValueError("repeats must be an integer in [1, 1000]")
        start = perf_counter()
        for _ in range(repeats):
            self._dispatch(self._derive_pipeline, self._derive_group, (len(self.paths) + 63) // 64)
        raw = self._device.queue.read_buffer(self._resident_nodes)
        seconds = perf_counter() - start
        same = all(low | (high << 32) == node.pair
                   for node, (low, high, _, _) in zip(self.nodes, struct.iter_unpack("<4I", raw)))
        if not same:
            raise ValueError("Repeated GPU derivation changed packed results")
        transitions = repeats * sum(map(len, self.paths))
        return {
            "adapter": self.adapter_info, "world_nodes": len(self.paths),
            "repeats": repeats, "packed_transitions": transitions,
            "wall_seconds_submit_and_readback": seconds,
            "packed_transitions_per_wall_second": transitions / seconds,
            "timing_scope": "Resident-input dispatch submissions plus final full readback; excludes setup, compilation and initial upload.",
            "timed_upload_bytes": 0, "timed_readback_bytes": len(raw),
            "explicit_device_payload_bytes": sum(buffer.size for buffer in self._buffers) + 32,
            "repeat_words_identical": same,
            "texture_cache_residency_measured": False, "gpu_saturation_measured": False,
        }

    def close(self):
        if self._closed:
            return
        self._closed = True
        for buffer in self._buffers:
            buffer.destroy()
        if self._texture is not None:
            self._texture.destroy()
        if self._device is not None:
            self._device.destroy()

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *_):
        self.close()


class GpuWorld(World):
    """World FIFO over a separately accounted, GPU-derived graph arena."""

    def __init__(self, config, capacity, executor):
        super().__init__(config, capacity)
        self._executor = executor
        self._nodes = {node.path: node for node in executor.nodes}

    def derive(self, path):
        _path(path, self.config.max_depth)
        if path in self._nodes:
            return self._nodes[path]
        # Preserve World's pure arbitrary-path API without a hidden CPU fallback.
        with GpuExecutor(self.config, (path,)) as extra:
            return extra.nodes[0]
