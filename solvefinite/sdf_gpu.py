"""Optional actual-GPU execution of the relational-sdf-v1/v2 field profiles.

The device constructs graph distances, compiles their packed operators into an
integer texture, and retains one individual's current pair across tick batches.
CPU code certifies the resulting field; it never supplies replacement distances
or a precomputed action trace. See docs/specification/relational-sdf-v1.md.
"""

from __future__ import annotations

from pathlib import Path
import struct

from .gpu import GpuUnavailable
from .rp32 import Opcode, pack, pair, unpack, unpair


class GpuFieldExecutor:
    """Single-owner, synchronous GPU field and persistent packed execution.

    ``reset`` starts a new tick budget from a certified field state. Invalid
    input is rejected before any device write. A device execution failure
    prevents further use until the executor is closed and reconstructed.
    """

    def __init__(self, manifest):
        # FieldMachine imports this optional adapter lazily. Keeping these
        # imports local also lets field.py remain usable without wgpu installed.
        from .field import FieldManifest

        if type(manifest) is not FieldManifest:
            raise ValueError("manifest must be a FieldManifest")
        try:
            import wgpu
        except ImportError as exc:
            raise GpuUnavailable(
                "GPU backend requires: python -m pip install -r requirements-gpu.txt"
            ) from exc
        self._manifest = manifest
        self._wgpu = wgpu
        self._device = None
        self._buffers = []
        self._texture = None
        self._closed = False
        self._failed = False
        self._ticks = 0
        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            if adapter is None or adapter.info.get("adapter_type") not in (
                "DiscreteGPU", "IntegratedGPU"
            ):
                raise GpuUnavailable(
                    "A hardware GPU is required; software adapters are not accepted"
                )
            self.adapter_info = dict(adapter.info)
            self._device = adapter.request_device_sync()
        except Exception as exc:
            if isinstance(exc, GpuUnavailable):
                raise
            raise GpuUnavailable(f"Unable to initialize a hardware GPU: {exc}") from exc
        try:
            self._initialize()
            initial = pair(pack(
                manifest.initial_phase, manifest.initial_node,
                self.fields[manifest.initial_node],
                int(Opcode.STEP) | (manifest.initial_orientation << 4),
            ))
            self.reset(initial)
        except BaseException:
            self.close()
            raise

    @property
    def fields(self) -> tuple[int, ...]:
        """Independently certified signed codes computed by the GPU."""
        return self._fields

    def _buffer(self, size, data=None):
        usage = self._wgpu.BufferUsage
        buffer = self._device.create_buffer(
            size=size, usage=usage.STORAGE | usage.COPY_DST | usage.COPY_SRC
        )
        self._buffers.append(buffer)
        if data is not None:
            self._device.queue.write_buffer(buffer, 0, data)
        return buffer

    @staticmethod
    def _resource(buffer):
        return {"buffer": buffer, "offset": 0, "size": buffer.size}

    def _group(self, pipeline, resources):
        return self._device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": binding, "resource": resource}
                     for binding, resource in resources.items()],
        )

    @staticmethod
    def _pass(encoder, pipeline, group, workgroups):
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(pipeline)
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups(workgroups)
        compute.end()

    def _initialize(self):
        from .field import certify_field

        manifest, device = self._manifest, self._device
        count = len(manifest.nodes)
        self._config = self._buffer(16, struct.pack("<4I", count, 0, manifest.max_ticks, 0))
        signs = self._buffer(4 * count, struct.pack(f"<{count}i", *manifest.signs))
        lengths = [0] * (count * count)
        for left, right, length in manifest.edges:
            lengths[left * count + right] = length
            lengths[right * count + left] = length
        weights = self._buffer(4 * count * count,
                               struct.pack(f"<{count * count}I", *lengths))
        # Upload edge geometry independently of the route program. The shader
        # derives each operator's transport bit from this authoritative seam
        # adjacency, rather than accepting host-compiled per-route actions.
        # A compact row bitset needs at most 8 KiB at the 256-node limit.
        seam_stride = (count + 31) // 32
        seam_words = [0] * (count * seam_stride)
        for left, right in manifest.seams:
            seam_words[left * seam_stride + right // 32] |= 1 << (right % 32)
            seam_words[right * seam_stride + left // 32] |= 1 << (left % 32)
        seams = self._buffer(4 * len(seam_words),
                             struct.pack(f"<{len(seam_words)}I", *seam_words))
        distances = (self._buffer(4 * count), self._buffer(4 * count))
        self._field_buffer = self._buffer(4 * count)
        rules_data = bytearray(3 * count * 8)
        for node in range(count):
            for column in range(3):
                struct.pack_into("<2I", rules_data, (3 * node + column) * 8,
                                 manifest.routes[node][column], manifest.turns[node][column])
        rules = self._buffer(len(rules_data), rules_data)
        self._state = self._buffer(16)
        self._output = self._buffer(4096 * 8)
        self._texture = device.create_texture(
            size=(3, count, 1), format="r32uint",
            usage=self._wgpu.TextureUsage.STORAGE_BINDING | self._wgpu.TextureUsage.TEXTURE_BINDING,
        )
        shader = device.create_shader_module(
            code=Path(__file__).with_name("shaders").joinpath("field.wgsl").read_text(encoding="utf-8")
        )
        pipelines = {
            entry: device.create_compute_pipeline(
                layout="auto", compute={"module": shader, "entry_point": entry}
            )
            for entry in ("initialize_distances", "relax_distances", "write_fields",
                          "compile_operators", "advance_ticks")
        }
        resource = self._resource
        init = self._group(pipelines["initialize_distances"], {
            0: resource(self._config), 1: resource(signs), 4: resource(distances[0]),
        })
        relax = tuple(self._group(pipelines["relax_distances"], {
            0: resource(self._config), 2: resource(weights),
            3: resource(distances[index]), 4: resource(distances[1 - index]),
        }) for index in (0, 1))
        final_index = (count - 1) % 2
        finish = self._group(pipelines["write_fields"], {
            0: resource(self._config), 1: resource(signs),
            3: resource(distances[final_index]), 5: resource(self._field_buffer),
        })
        encoder = device.create_command_encoder()
        groups = (count + 63) // 64
        self._pass(encoder, pipelines["initialize_distances"], init, groups)
        for round_index in range(count - 1):
            self._pass(encoder, pipelines["relax_distances"], relax[round_index % 2], groups)
        self._pass(encoder, pipelines["write_fields"], finish, groups)
        device.queue.submit([encoder.finish()])
        raw = device.queue.read_buffer(self._field_buffer)
        self._fields = tuple(struct.unpack(f"<{count}i", raw))
        certify_field(manifest, self._fields)

        # Compile only after certification, so an unrepresentable magnitude can
        # never be masked into a superficially valid signed-byte operator.
        view = self._texture.create_view()
        compile_group = self._group(pipelines["compile_operators"], {
            0: resource(self._config), 5: resource(self._field_buffer),
            6: resource(rules), 7: view, 11: resource(seams),
        })
        encoder = device.create_command_encoder()
        self._pass(encoder, pipelines["compile_operators"], compile_group,
                   (3 * count + 63) // 64)
        device.queue.submit([encoder.finish()])
        self._advance_pipeline = pipelines["advance_ticks"]
        self._advance_group = self._group(self._advance_pipeline, {
            0: resource(self._config), 8: view,
            9: resource(self._state), 10: resource(self._output),
        })

    def _check_open(self):
        if self._closed:
            raise ValueError("GPU field executor is closed")
        if self._failed:
            raise ValueError("GPU field executor failed; reconstruct before continuing")

    def _validate_pair(self, value):
        left, right = unpair(value)
        _, node, field, metadata = unpack(left)
        if node >= len(self.fields):
            raise ValueError("Field state node is outside the manifest")
        if metadata not in (int(Opcode.STEP), int(Opcode.STEP) | 16):
            raise ValueError("Field state requires STEP and only the orientation metadata bit")
        if field != self.fields[node]:
            raise ValueError("Field state B must equal the certified field at G")
        return left, right

    def reset(self, agent_pair: int):
        """Admit a complete geometric state and restart this executor's budget."""
        self._check_open()
        left, right = self._validate_pair(agent_pair)
        self._failed = True
        self._device.queue.write_buffer(self._state, 0, struct.pack("<4I", left, right, 0, 0))
        self._ticks = 0
        self._failed = False

    def advance(self, steps: int) -> tuple[int, ...]:
        """Run a bounded closed lookup chain, preserving its GPU state afterward."""
        self._check_open()
        if type(steps) is not int or not 1 <= steps <= 4096:
            raise ValueError("steps must be an integer in [1, 4096]")
        if self._ticks + steps > self._manifest.max_ticks:
            raise ValueError("Field tick budget would be exceeded")
        self._failed = True
        queue = self._device.queue
        queue.write_buffer(self._config, 4, struct.pack("<I", steps))
        encoder = self._device.create_command_encoder()
        self._pass(encoder, self._advance_pipeline, self._advance_group, 1)
        queue.submit([encoder.finish()])
        raw = queue.read_buffer(self._output, 0, steps * 8)
        result = tuple(left | (right << 32) for left, right in struct.iter_unpack("<2I", raw))
        for value in result:
            self._validate_pair(value)
        self._ticks += steps
        self._failed = False
        return result

    def close(self):
        """Release all device resources, including after partial construction."""
        if self._closed:
            return
        self._closed = True
        first_error = None
        resources = [*self._buffers, self._texture, self._device]
        for resource in resources:
            if resource is not None:
                try:
                    resource.destroy()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *_):
        self.close()
