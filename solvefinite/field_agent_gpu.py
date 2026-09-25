"""Device field samples, forecasts and admitted moves for the FI1-FI8 policy.

The persistent individual has a certified SDF in B and a separate energy
integer. Forecast scratch and regenerated DATA samples cannot advance it.
Standalone field-machine and binary-world execution retain their own APIs.
"""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
from pathlib import Path
import struct
from threading import RLock

from .f8 import F8Index, IndexBinding, build_geometry
from .motion import EnergyExhausted
from .rp32 import Opcode, unpack, unpair
from .runtime import _integer
from .sdf_gpu import GpuFieldExecutor


MAX_ENERGY = (1 << 31) - 1
MAX_FORECAST_HOPS = 255


def _serialized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return locked


class CommittedIndexCleanupError(RuntimeError):
    """A replacement was admitted, but retiring its predecessor failed."""

    committed = True


class _IndexBundle:
    def __init__(self):
        self.buffers = []
        self.texture = None
        self.index = None
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        first_error = None
        for resource in [*self.buffers, self.texture]:
            if resource is not None:
                try:
                    resource.destroy()
                except Exception as exc:
                    first_error = first_error or exc
        if first_error is not None:
            raise first_error


class GpuFieldAgentExecutor:
    """One device owner with independent forecast scratch and canonical state.

    ``seed`` is a one-time admission of the initial STEP pair and energy.
    ``failed`` records an uncertain device outcome; such an executor may only
    be closed. Invalid public inputs are rejected before any device write.
    """

    def __init__(self, recipe, index_binding=None):
        from .field_world import KleinFieldRecipe

        if type(recipe) is not KleinFieldRecipe:
            raise ValueError("recipe must be a KleinFieldRecipe")
        if index_binding is None:
            index_binding = IndexBinding()
        if type(index_binding) is not IndexBinding:
            raise ValueError("index_binding must be an IndexBinding")
        self._lock = RLock()
        self._initial_binding = index_binding
        self._recipe = recipe
        self._manifest = recipe.field_manifest()
        self._nodes = self._manifest.nodes
        self._indices = {name: index for index, name in enumerate(self._nodes)}
        neighbors = [set() for _ in self._nodes]
        for left, right, _ in self._manifest.edges:
            neighbors[left].add(right)
            neighbors[right].add(left)
        self._neighbors = tuple(tuple(sorted(row)) for row in neighbors)
        if any(len(row) != 4 for row in self._neighbors):
            raise ValueError("The field-agent operator arena requires four distinct neighbors")
        self._geometry = None
        self._device = None
        self._buffers = []
        self._texture = None
        self._bundle = None
        self._peak_rebuild_device_payload_bytes = 0
        self._peak_rebuild_host_index_payload_bytes = 0
        self._closed = False
        self._failed = False
        self._seeded = False
        self._pair = None
        self._energy = None
        self._ticks = 0
        self._terminal = False
        try:
            # Reuse the actual-device distance construction and independent
            # certificate. Its fixed-route tick engine is never advanced here.
            self._geometry = GpuFieldExecutor(self._manifest)
            self._device = self._geometry._device
            self._wgpu = self._geometry._wgpu
            self._initialize()
            del self._initial_binding
        except BaseException:
            self.close()
            raise

    @property
    def recipe(self):
        return self._recipe

    @property
    def fields(self) -> tuple[int, ...]:
        return self._geometry.fields

    @property
    def adapter_info(self) -> dict:
        return deepcopy(self._geometry.adapter_info)

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    @_serialized
    def index(self) -> F8Index:
        # Keep the committed version diagnosable even after cleanup failure.
        return self._bundle.index

    @property
    @_serialized
    def allocation_info(self) -> dict:
        buffers = sum(buffer.size for buffer in
                      self._buffers + self._geometry._buffers + self._bundle.buffers)
        textures = (12 + 3) * len(self._nodes) * 4
        index_payload = 64 * len(self._nodes) + 16
        return {
            "device_buffer_bytes": buffers,
            "device_texture_bytes": textures,
            "device_payload_bytes": buffers + textures,
            "host_field_code_payload_bytes": 4 * len(self.fields),
            "host_index_payload_bytes": index_payload,
            "host_geometry_payload_bytes": 16 * len(self._nodes),
            "peak_rebuild_device_payload_bytes": self._peak_rebuild_device_payload_bytes,
            "peak_rebuild_host_index_payload_bytes": self._peak_rebuild_host_index_payload_bytes,
            "index_version": {"recipe": self.recipe.to_dict(),
                              "binding": self.index.binding.to_dict()},
            "retained_world_node_pair_count": 0,
            "accounting": (
                "Explicit scalar/table/state/scratch buffers and integer textures, including "
                "the composed field engine, are outside the observed FIFO. Host field codes "
                "and index/geometry metadata are logical integer payload; Python objects and "
                "driver allocations are excluded. Rebuild peaks include both complete bundles. "
                "No complete packed world-node arena is retained."
            ),
        }

    def _buffer(self, size, data=None, *, bundle=None):
        usage = self._wgpu.BufferUsage
        buffer = self._device.create_buffer(
            size=size, usage=usage.STORAGE | usage.COPY_SRC | usage.COPY_DST)
        (self._buffers if bundle is None else bundle.buffers).append(buffer)
        if data is not None:
            self._device.queue.write_buffer(buffer, 0, data)
        return buffer

    def _group(self, pipeline, resources):
        return self._device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": binding, "resource": resource}
                     for binding, resource in resources.items()],
        )

    def _dispatch(self, pipeline, group, workgroups=1):
        encoder = self._device.create_command_encoder()
        GpuFieldExecutor._pass(encoder, pipeline, group, workgroups)
        self._device.queue.submit([encoder.finish()])

    def _initialize(self):
        count = len(self._nodes)
        geometry = build_geometry(self.recipe)
        words = tuple(word for node in range(count) for word in (
            *self._neighbors[node], *geometry.directions[node],
            geometry.parents[node], geometry.distances[node], 0, 0))
        self._index_geometry = self._buffer(48 * count, struct.pack(f"<{len(words)}I", *words))
        stride = (count + 31) // 32
        words = [0] * (count * stride)
        for left, right in self._manifest.seams:
            words[left * stride + right // 32] |= 1 << (right % 32)
            words[right * stride + left // 32] |= 1 << (left % 32)
        self._seams = self._buffer(4 * len(words), struct.pack(f"<{len(words)}I", *words))
        self._jobs = self._buffer(8 * MAX_FORECAST_HOPS)
        self._scratch = self._buffer(16)
        self._canonical = self._buffer(16)
        self._output = self._buffer(32 * MAX_FORECAST_HOPS)
        shader = self._device.create_shader_module(code=Path(__file__).with_name(
            "shaders").joinpath("field_agent.wgsl").read_text(encoding="utf-8"))
        self._pipelines = {
            entry: self._device.create_compute_pipeline(
                layout="auto", compute={"module": shader, "entry_point": entry})
            for entry in ("build_keys", "build_tree", "compile_neighbors", "lookup_node",
                          "derive_node", "forecast", "advance_to", "repair")
        }
        self._adopt_bundle(self._prepare_bundle(self._initial_binding))

    def _adopt_bundle(self, bundle):
        self._bundle = bundle
        self._config, self._texture, self._groups = bundle.config, bundle.texture, bundle.groups

    def _prepare_bundle(self, binding):
        """Allocate independently; certify device construction before admission."""
        count = len(self._nodes)
        candidate = _IndexBundle()
        device_work = False
        try:
            candidate.config = self._buffer(48, bundle=candidate)
            candidate.records = self._buffer(32 * count, bundle=candidate)
            candidate.tree = self._buffer(32 * count, bundle=candidate)
            candidate.status = self._buffer(4 * count, bundle=candidate)
            candidate.texture = self._device.create_texture(
                size=(12, count, 1), format="r32uint",
                usage=self._wgpu.TextureUsage.STORAGE_BINDING | self._wgpu.TextureUsage.TEXTURE_BINDING)
            self._bind_bundle(candidate)
            base = sum(buffer.size for buffer in self._buffers + self._geometry._buffers)
            payload = base + 12 * count + sum(buffer.size for buffer in candidate.buffers) + 48 * count
            host_payload = 64 * count + 16
            if self._bundle is not None:
                payload += sum(buffer.size for buffer in self._bundle.buffers) + 48 * count
                host_payload *= 2
            self._peak_rebuild_device_payload_bytes = max(self._peak_rebuild_device_payload_bytes, payload)
            self._peak_rebuild_host_index_payload_bytes = max(
                self._peak_rebuild_host_index_payload_bytes, host_payload)
            device_work = self._failed = True
            self._device.queue.write_buffer(candidate.config, 0, struct.pack(
                "<12I", count, 0, 0, 0, *self.recipe.turns, 0,
                binding.psi_sign & 0xffffffff, binding.phase_origin, count.bit_length(), self.recipe.center))
            for entry in ("build_keys", "build_tree"):
                self._dispatch(self._pipelines[entry], candidate.groups[entry], (count + 63) // 64)
            records = tuple(struct.iter_unpack("<8I", self._device.queue.read_buffer(candidate.records)))
            rows = tuple(struct.iter_unpack("<8I", self._device.queue.read_buffer(candidate.tree)))
            # This is an independent admission certificate, never a compiler.
            device_work = self._failed = False
            candidate.index = F8Index.certified(self.recipe, binding, records, rows, self.fields)
            device_work = self._failed = True
            self._dispatch(self._pipelines["compile_neighbors"], candidate.groups["compile_neighbors"],
                           (count + 63) // 64)
            status = struct.unpack(f"<{count}I", self._device.queue.read_buffer(candidate.status))
            if any(status):
                raise ValueError("GPU index rejected an operator texture row")
            device_work = self._failed = False
            return candidate
        except BaseException:
            try:
                candidate.close()
            except Exception:
                device_work = self._failed = True
            if device_work:
                self._failed = True
                try:
                    self.close()
                except Exception:
                    pass
            raise

    def _bind_bundle(self, bundle):
        resource = GpuFieldExecutor._resource
        view = bundle.texture.create_view()
        field = resource(self._geometry._field_buffer)
        config = resource(bundle.config)
        output = resource(self._output)
        geometry = resource(self._index_geometry)
        index = {0: config, 1: field, 2: geometry, 11: resource(bundle.records), 12: resource(bundle.tree)}
        bundle.groups = {
            "build_keys": self._group(self._pipelines["build_keys"], {
                0: config, 1: field, 2: geometry, 11: resource(bundle.records)}),
            "build_tree": self._group(self._pipelines["build_tree"], {
                0: config, 11: resource(bundle.records), 12: resource(bundle.tree)}),
            "compile_neighbors": self._group(self._pipelines["compile_neighbors"], {
                **index, 3: resource(self._seams), 4: view, 13: resource(bundle.status)}),
            "lookup_node": self._group(self._pipelines["lookup_node"], {**index, 8: output}),
            "derive_node": self._group(self._pipelines["derive_node"], {
                **index, 8: output,
            }),
            "forecast": self._group(self._pipelines["forecast"], {
                **index, 5: view, 6: resource(self._jobs),
                7: resource(self._scratch), 8: output,
            }),
            "advance_to": self._group(self._pipelines["advance_to"], {
                **index, 5: view,
                7: resource(self._canonical), 8: output,
            }),
            "repair": self._group(self._pipelines["repair"], {
                0: config, 7: resource(self._canonical), 8: output,
            }),
        }

    @_serialized
    def reindex(self, *, psi_sign=None, phase_origin=None) -> F8Index:
        self._check_open()
        binding = self.index.binding.next(psi_sign=psi_sign, phase_origin=phase_origin)
        candidate = self._prepare_bundle(binding)
        old = self._bundle
        self._adopt_bundle(candidate)
        try:
            old.close()
        except Exception as exc:
            self._failed = True
            try:
                self.close()
            except Exception:
                pass
            raise CommittedIndexCleanupError(
                f"Index epoch {binding.epoch} committed; retiring the previous bundle failed") from exc
        return candidate.index

    @_serialized
    def lookup_node(self, index: int) -> int:
        """Resolve a canonical G through the device tree used by actual moves."""
        self._check_open()
        _integer(index, 0, len(self.fields) - 1, "node index")
        self._failed = True
        self._device.queue.write_buffer(self._config, 8, struct.pack("<I", index))
        self._dispatch(self._pipelines["lookup_node"], self._groups["lookup_node"])
        row = self._read_outputs(1)[0]
        if row[4] or row[0] >= len(self._nodes) or self.index.rows[row[0]][4] != index:
            raise ValueError("GPU index lookup rejected a malformed key or tree")
        self._failed = False
        return row[0]

    def _check_open(self):
        if self._closed:
            raise ValueError("GPU field-agent executor is closed")
        if self._failed:
            raise ValueError("GPU field-agent executor failed; reconstruct before continuing")

    def _live_pair(self, value, opcode=Opcode.STEP):
        _integer(value, 0, (1 << 64) - 1, "agent_pair")
        left, right = unpair(value)
        phase, node, field, metadata = unpack(left)
        if node >= len(self.fields) or field != self.fields[node]:
            raise ValueError("Agent state must contain its node's certified field")
        if metadata not in (int(opcode), int(opcode) | 16):
            raise ValueError("Agent state requires the declared opcode and only orientation metadata")
        return left, right, phase, node, metadata

    def _index(self, path):
        if type(path) is not str or path not in self._indices:
            raise ValueError("Destination must name a canonical node of this recipe")
        return self._indices[path]

    def _ready(self):
        self._check_open()
        if not self._seeded:
            raise ValueError("Canonical GPU state has not been seeded")
        if self._terminal:
            raise ValueError("The field agent is already complete")

    def _read_outputs(self, count):
        raw = self._device.queue.read_buffer(self._output, 0, 32 * count)
        if len(raw) != 32 * count:
            raise ValueError("GPU returned an incomplete field-agent result")
        return tuple(struct.iter_unpack("<8I", raw))

    @staticmethod
    def _pair_from_result(row):
        if row[4] != 0:
            raise ValueError(f"GPU field-agent transition returned status {row[4]}")
        return row[0] | (row[1] << 32)

    @_serialized
    def derive_node(self, index: int) -> int:
        """Regenerate one DATA sample on the device, without a packed-node cache."""
        self._check_open()
        _integer(index, 0, len(self.fields) - 1, "node index")
        self._failed = True
        self._device.queue.write_buffer(self._config, 8, struct.pack("<I", index))
        self._dispatch(self._pipelines["derive_node"], self._groups["derive_node"])
        value = self._pair_from_result(self._read_outputs(1)[0])
        _, _, phase, node, metadata = self._live_pair(value, Opcode.DATA)
        if phase != 0 or node != index or metadata != int(Opcode.DATA):
            raise ValueError("GPU sample disagrees with its canonical geometric descriptor")
        self._failed = False
        return value

    @_serialized
    def seed(self, agent_pair: int, energy: int) -> None:
        """Admit the initial pair and separate energy exactly once."""
        self._check_open()
        if self._seeded:
            raise ValueError("Canonical GPU state may only be seeded once")
        left, right, _, _, _ = self._live_pair(agent_pair)
        _integer(energy, 0, MAX_ENERGY, "energy")
        self._failed = True
        self._device.queue.write_buffer(self._canonical, 0, struct.pack("<4I", left, right, energy, 0))
        self._pair, self._energy = agent_pair, energy
        self._seeded = True
        self._failed = False

    @_serialized
    def forecast(self, agent_pair: int, route, hazards) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Forecast a caller-internal route; neither canonical pair nor energy changes."""
        self._check_open()
        left, right, _, source, _ = self._live_pair(agent_pair)
        if type(route) is not tuple or type(hazards) is not tuple:
            raise ValueError("Forecast route and hazards must be immutable tuples")
        if len(route) != len(hazards) or len(route) > MAX_FORECAST_HOPS:
            raise ValueError("Forecast requires matching route and hazards with at most 255 hops")
        destinations, costs = [], []
        for path, hazard in zip(route, hazards):
            destination = self._index(path)
            _integer(hazard, 0, 127, "hazard")
            if destination not in self._neighbors[source]:
                raise ValueError("Every forecast hop must follow an edge between distinct nodes")
            destinations.append(destination)
            costs.append(1 + abs(self.fields[destination]) + hazard)
            source = destination
        if not destinations:
            return (), ()
        jobs = b"".join(struct.pack("<2I", destination, hazard)
                        for destination, hazard in zip(destinations, hazards))
        self._failed = True
        queue = self._device.queue
        queue.write_buffer(self._config, 4, struct.pack("<I", len(destinations)))
        queue.write_buffer(self._jobs, 0, jobs)
        queue.write_buffer(self._scratch, 0, struct.pack("<4I", left, right, 0, 0))
        self._dispatch(self._pipelines["forecast"], self._groups["forecast"])
        pairs, actual_costs = [], []
        for row, destination, expected_cost in zip(self._read_outputs(len(destinations)), destinations, costs):
            value = self._pair_from_result(row)
            _, _, _, node, _ = self._live_pair(value)
            if node != destination or row[2] != expected_cost or row[3] != 0:
                raise ValueError("GPU forecast disagrees with admitted destination or cost")
            pairs.append(value)
            actual_costs.append(row[2])
        self._failed = False
        return tuple(pairs), tuple(actual_costs)

    @_serialized
    def advance_to(self, destination: str, hazard: int) -> tuple[int, int, int]:
        """Execute one neighboring move from the persistent device pair and energy."""
        self._ready()
        _, _, _, source, _ = self._live_pair(self._pair)
        node = self._index(destination)
        _integer(hazard, 0, 127, "hazard")
        if node not in self._neighbors[source]:
            raise ValueError("Movement must follow an edge between distinct nodes")
        cost = 1 + abs(self.fields[node]) + hazard
        if cost > self._energy:
            raise EnergyExhausted("Insufficient separate energy for the field move")
        self._failed = True
        self._device.queue.write_buffer(self._config, 8, struct.pack("<2I", node, hazard))
        self._dispatch(self._pipelines["advance_to"], self._groups["advance_to"])
        row = self._read_outputs(1)[0]
        value = self._pair_from_result(row)
        _, _, _, actual_node, _ = self._live_pair(value)
        expected_energy = self._energy - cost
        if actual_node != node or row[2] != cost or row[3] != expected_energy:
            raise ValueError("GPU movement disagrees with admitted geometry, cost or energy")
        actual_cost, energy = row[2], row[3]
        self._pair, self._energy = value, energy
        self._ticks += 1
        self._failed = False
        return value, actual_cost, energy

    @_serialized
    def repair(self, cost: int) -> tuple[int, int]:
        """Debit separate energy and emit completion without changing R/G/B/eta."""
        self._ready()
        _integer(cost, 1, 127, "repair cost")
        if cost > self._energy:
            raise EnergyExhausted("Insufficient separate energy for repair")
        _, _, phase, node, metadata = self._live_pair(self._pair)
        self._failed = True
        self._device.queue.write_buffer(self._config, 12, struct.pack("<I", cost))
        self._dispatch(self._pipelines["repair"], self._groups["repair"])
        row = self._read_outputs(1)[0]
        value = self._pair_from_result(row)
        _, _, actual_phase, actual_node, actual_metadata = self._live_pair(value, Opcode.EMIT)
        expected_energy = self._energy - cost
        if ((actual_phase, actual_node, actual_metadata) !=
                (phase, node, int(Opcode.EMIT) | (metadata & 16))
                or row[2] != cost or row[3] != expected_energy):
            raise ValueError("GPU repair changed a geometric lane or separate energy incorrectly")
        energy = row[3]
        self._pair, self._energy = value, energy
        self._ticks += 1
        self._terminal = True
        self._failed = False
        return value, energy

    @_serialized
    def snapshot(self) -> tuple[int, int]:
        """Read and certify the actual canonical device state, including completion."""
        self._check_open()
        if not self._seeded:
            raise ValueError("Canonical GPU state has not been seeded")
        self._failed = True
        left, right, energy, ticks = struct.unpack("<4I", self._device.queue.read_buffer(self._canonical))
        value = left | (right << 32)
        self._live_pair(value, Opcode.EMIT if self._terminal else Opcode.STEP)
        if (value, energy, ticks) != (self._pair, self._energy, self._ticks):
            raise ValueError("Canonical GPU state disagrees with its last admitted result")
        self._failed = False
        return value, energy

    @_serialized
    def close(self) -> None:
        """Release own resources and the composed geometry owner, even after failure."""
        if self._closed:
            return
        self._closed = True
        first_error = None
        for resource in self._buffers:
            if resource is not None:
                try:
                    resource.destroy()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if self._bundle is not None:
            try:
                self._bundle.close()
            except Exception as exc:
                first_error = first_error or exc
        if self._geometry is not None:
            try:
                self._geometry.close()
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
