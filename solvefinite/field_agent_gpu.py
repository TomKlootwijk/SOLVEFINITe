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
from .hadamard import HadamardBinding, RoutingModel
from .motion import EnergyExhausted
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer
from .sdf_gpu import GpuFieldExecutor, _tag_device_uncertainty


MAX_ENERGY = (1 << 31) - 1
MAX_FORECAST_HOPS = 255


def _serialized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            try:
                return method(self, *args, **kwargs)
            except BaseException:
                if (method.__name__ != "close" and getattr(self, "_routing", None) is not None
                        and getattr(self, "_failed", False)):
                    try:
                        self.close()
                    except Exception:
                        pass
                raise
    return locked


class CommittedIndexCleanupError(RuntimeError):
    """A replacement was admitted, but retiring its predecessor failed."""

    committed = True


class _IndexBundle:
    def __init__(self):
        self.buffers = []
        self.texture = None
        self.index = None
        self.routing_model = None
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

    def __init__(self, recipe, index_binding=None, *, routing=None):
        from .field_world import KleinFieldRecipe
        from .organogram import GeneratedFieldRecipe

        if type(recipe) not in (KleinFieldRecipe, GeneratedFieldRecipe):
            raise ValueError("recipe must be a supported field recipe")
        if index_binding is None:
            index_binding = IndexBinding()
        if type(index_binding) is not IndexBinding:
            raise ValueError("index_binding must be an IndexBinding")
        if routing is not None and type(routing) is not HadamardBinding:
            raise ValueError("routing must be a HadamardBinding")
        generated = type(recipe) is GeneratedFieldRecipe
        if generated and routing != recipe.routing:
            raise ValueError("Generated recipe requires its original routing binding")
        self._lock = RLock()
        self._routing = routing
        self._initial_binding = index_binding
        self._recipe = recipe
        self._manifest = recipe.base.field_manifest() if generated else recipe.field_manifest()
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
        self._peak_rebuild_host_routing_payload_bytes = 0
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
            if generated:
                from .organogram_gpu import GpuOrganogramGeometry
                self._geometry = GpuOrganogramGeometry(recipe)
                self._manifest = self._geometry.manifest
            else:
                self._geometry = GpuFieldExecutor(self._manifest)
            self._device = self._geometry._device
            self._wgpu = self._geometry._wgpu
            self._initialize()
            del self._initial_binding
        except BaseException as exc:
            # A composed field constructor can fail before _geometry receives
            # its return value. Preserve its uncertainty and exception type.
            _tag_device_uncertainty(exc, self._failed)
            try:
                self.close()
            except BaseException:
                _tag_device_uncertainty(exc, True)
            raise

    @property
    def recipe(self):
        return self._recipe

    @property
    def fields(self) -> tuple[int, ...]:
        return self._geometry.fields

    @property
    def manifest(self):
        return self._manifest

    @property
    def certificate(self):
        return getattr(self._geometry, "certificate", None)

    @property
    def last_derivation(self):
        return None if self.certificate is None else self.certificate.last_derivation

    @property
    def stage_digests(self):
        return () if self.certificate is None else self.certificate.stage_digests

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
    def routing_model(self) -> RoutingModel | None:
        return self._bundle.routing_model

    @property
    @_serialized
    def allocation_info(self) -> dict:
        buffers = sum(buffer.size for buffer in
                      self._buffers + self._geometry._buffers + self._bundle.buffers)
        textures = ((384 if self._routing is not None else 48) * len(self._nodes)
                    + 12 * len(self._nodes) + getattr(self._geometry, "extra_texture_bytes", 0))
        index_payload = 64 * len(self._nodes) + 16
        result = {
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
        if self._routing is not None:
            result.update(
                routing_atlas_bytes=384 * len(self._nodes),
                device_routing_table_payload_bytes=68 * len(self._nodes),
                host_routing_table_payload_bytes=68 * len(self._nodes),
                host_routing_geometry_payload_bytes=16 * len(self._nodes),
                device_routing_gains_payload_bytes=32,
                host_routing_gains_payload_bytes=32,
                peak_rebuild_host_routing_payload_bytes=self._peak_rebuild_host_routing_payload_bytes,
                peak_rebuild_host_routing_geometry_payload_bytes=(
                    16 * len(self._nodes) * (2 if self._peak_rebuild_host_routing_payload_bytes
                                            > 68 * len(self._nodes) else 1)),
                routing_binding=self._routing.to_dict(),
            )
        if self.certificate is not None:
            result["organogram"] = self._geometry.allocation_info
        return result

    def _buffer(self, size, data=None, *, bundle=None):
        usage = self._wgpu.BufferUsage
        buffer = self._device.create_buffer(
            size=size, usage=usage.STORAGE | usage.COPY_SRC | usage.COPY_DST)
        (self._buffers if bundle is None else bundle.buffers).append(buffer)
        if data is not None:
            try:
                self._device.queue.write_buffer(buffer, 0, data)
            except BaseException as exc:
                _tag_device_uncertainty(exc, True)
                raise
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
        seam_edges = frozenset(self._manifest.seams)
        seam_flags = tuple(sum(1 << slot for slot, neighbor in enumerate(adjacent)
                               if tuple(sorted((source, neighbor))) in seam_edges)
                           for source, adjacent in enumerate(self._neighbors))
        words = tuple(word for node in range(count) for word in (
            *self._neighbors[node], *geometry.directions[node],
            geometry.parents[node], geometry.distances[node], seam_flags[node], 0))
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
        entries = ("build_keys", "build_tree", "compile_neighbors", "lookup_node",
                   "derive_node", "forecast", "advance_to", "repair", "admit_growth", "admit_generated")
        if self._routing is not None:
            entries += ("compile_hadamard", "export_routing")
        self._pipelines = {
            entry: self._device.create_compute_pipeline(
                layout="auto", compute={"module": shader, "entry_point": entry})
            for entry in entries
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
            if self._routing is not None:
                candidate.gains = self._buffer(32, bundle=candidate)
                candidate.routing_table = self._buffer(68 * count, bundle=candidate)
            atlas_bytes = (384 if self._routing is not None else 48) * count
            candidate.texture = self._device.create_texture(
                size=(24, 4 * count, 1) if self._routing is not None else (12, count, 1), format="r32uint",
                usage=(self._wgpu.TextureUsage.STORAGE_BINDING | self._wgpu.TextureUsage.TEXTURE_BINDING
                       | self._wgpu.TextureUsage.COPY_DST | self._wgpu.TextureUsage.COPY_SRC))
            self._bind_bundle(candidate)
            base = sum(buffer.size for buffer in self._buffers + self._geometry._buffers)
            payload = (base + 12 * count + getattr(self._geometry, "extra_texture_bytes", 0)
                       + sum(buffer.size for buffer in candidate.buffers) + atlas_bytes)
            host_payload = 64 * count + 16
            routing_payload = 68 * count if self._routing is not None else 0
            if self._bundle is not None:
                payload += sum(buffer.size for buffer in self._bundle.buffers) + atlas_bytes
                host_payload *= 2
                routing_payload *= 2
            self._peak_rebuild_device_payload_bytes = max(self._peak_rebuild_device_payload_bytes, payload)
            self._peak_rebuild_host_index_payload_bytes = max(
                self._peak_rebuild_host_index_payload_bytes, host_payload)
            self._peak_rebuild_host_routing_payload_bytes = max(
                self._peak_rebuild_host_routing_payload_bytes, routing_payload)
            device_work = self._failed = True
            if self._routing is not None:
                self._device.queue.write_buffer(candidate.gains, 0, struct.pack(
                    "<8i", *(value for gain in self._routing.gains for value in gain)))
            self._device.queue.write_buffer(candidate.config, 0, struct.pack(
                "<12I", count, 0, 0, 0, *self.recipe.turns, int(self._routing is not None),
                binding.psi_sign & 0xffffffff, binding.phase_origin, count.bit_length(), self.recipe.center))
            for entry in ("build_keys", "build_tree"):
                self._dispatch(self._pipelines[entry], candidate.groups[entry], (count + 63) // 64)
            record_bytes = self._device.queue.read_buffer(candidate.records)
            row_bytes = self._device.queue.read_buffer(candidate.tree)
            if len(record_bytes) != 32 * count or len(row_bytes) != 32 * count:
                raise ValueError("GPU returned incomplete candidate index metadata")
            records = tuple(struct.iter_unpack("<8I", record_bytes))
            rows = tuple(struct.iter_unpack("<8I", row_bytes))
            # This is an independent admission certificate, never a compiler.
            device_work = self._failed = False
            certificate_options = {} if self.certificate is None else {"certificate": self.certificate}
            candidate.index = F8Index.certified(self.recipe, binding, records, rows, self.fields,
                                               **certificate_options)
            device_work = self._failed = True
            compiler = "compile_neighbors" if self._routing is None else "compile_hadamard"
            self._dispatch(self._pipelines[compiler], candidate.groups[compiler],
                           (count + 63) // 64)
            if self._routing is not None:
                self._dispatch(self._pipelines["export_routing"], candidate.groups["export_routing"],
                               (count + 63) // 64)
            status = struct.unpack(f"<{count}I", self._device.queue.read_buffer(candidate.status))
            tables = None
            if self._routing is not None:
                tables = struct.unpack(f"<{17 * count}I", self._device.queue.read_buffer(candidate.routing_table))
            # A complete result is known: any following rejection is pure.
            device_work = self._failed = False
            if any(status):
                raise ValueError("GPU index or routing atlas rejected an operator texture row")
            if tables is not None:
                candidate.routing_model = RoutingModel.certified(
                    self.recipe, self._routing, tables[:16 * count], tables[16 * count:], self.fields,
                    **certificate_options)
                if self._bundle is not None:
                    if candidate.routing_model != self._bundle.routing_model:
                        raise ValueError("Index replacement changed the semantic routing model")
                    # A retained cursor and the current owner share one immutable model.
                    candidate.routing_model = self._bundle.routing_model
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
            # Eight storage buffers, reusing independent job and state arenas.
            "admit_growth": self._group(self._pipelines["admit_growth"], {
                **index, 6: resource(self._jobs),
                7: resource(self._canonical), 8: output,
            }),
            "admit_generated": self._group(self._pipelines["admit_generated"], {
                **index, 6: resource(self._jobs),
                7: resource(self._canonical), 8: output,
            }),
        }
        if self._routing is not None:
            gains = resource(bundle.gains)
            bundle.groups.update({
                "compile_hadamard": self._group(self._pipelines["compile_hadamard"], {
                    **index, 3: resource(self._seams), 4: view, 13: resource(bundle.status), 14: gains}),
                "export_routing": self._group(self._pipelines["export_routing"], {
                    **index, 5: view, 13: resource(bundle.status), 14: gains,
                    15: resource(bundle.routing_table)}),
            })

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

    @_serialized
    def admit_generated(self, source, cost, *, organogram, prefix_sha256):
        """OG7: admit one exact historical extension without host state seeding."""
        from .field_world import KleinFieldRecipe
        from .organogram import GeneratedFieldRecipe, OrganogramBinding
        self._check_open()
        if self._seeded or type(self.recipe) is not GeneratedFieldRecipe:
            raise ValueError("Generated admission requires an unseeded generated candidate")
        if type(source) is not GpuFieldAgentExecutor or source is self:
            raise ValueError("Generated admission requires a distinct source executor")
        if type(organogram) is not OrganogramBinding or organogram != self.recipe.organogram:
            raise ValueError("Candidate grammar differs from the owner's immutable binding")
        _integer(cost, 1, 127, "organogram cost")
        if cost != organogram.cost:
            raise ValueError("Generated admission cost must equal its immutable binding")
        if (type(prefix_sha256) is not str or len(prefix_sha256) != 64
                or any(c not in "0123456789abcdef" for c in prefix_sha256)):
            raise ValueError("prefix_sha256 must be a lowercase SHA256 digest")
        new, old = self.recipe, source.recipe
        if source._routing != self._routing or self._routing != new.routing:
            raise ValueError("Generated admission requires identical routing")
        if type(old) is KleinFieldRecipe:
            valid = new.base == old and len(new.stages) == 1
        elif type(old) is GeneratedFieldRecipe:
            valid = (new.base == old.base and new.organogram == old.organogram
                     and new.routing == old.routing and new.stages[:-1] == old.stages
                     and len(new.stages) == len(old.stages) + 1)
        else:
            valid = False
        if not valid or new.stages[-1].prefix_sha256 != prefix_sha256:
            raise ValueError("Generated recipe does not extend the owner's exact original context")
        source._check_open()
        if not source._seeded or not source._terminal:
            raise ValueError("Generated admission requires a repaired EMIT source")
        old_pair, old_energy = source.snapshot()
        if f"{old_pair:016X}" != new.stages[-1].start_pair:
            raise ValueError("Generated stage does not begin at the actual old device state")
        left, right, phase, node, metadata = source._live_pair(old_pair, Opcode.EMIT)
        if cost > old_energy:
            raise EnergyExhausted("Insufficient separate energy for generated admission")
        expected = pair(pack(phase, node, self.fields[node], int(Opcode.STEP) | (metadata & 16)))
        remaining = old_energy - cost
        payload = struct.pack("<8I", left, right, old_energy, cost, len(source.fields),
                              source.fields[node] & 0xffffffff, 0, 0)
        try:
            self._failed = True
            self._device.queue.write_buffer(self._jobs, 0, payload)
            self._dispatch(self._pipelines["admit_generated"], self._groups["admit_generated"])
            row = self._read_outputs(1)[0]
            canonical = struct.unpack("<4I", self._device.queue.read_buffer(self._canonical))
            self._failed = False
            actual = self._pair_from_result(row)
            self._live_pair(actual)
            if (actual, row[2], row[3], row[5:]) != (expected, cost, remaining, (0, 0, 0)):
                raise ValueError("Device generated admission disagrees with its state mapping")
            if canonical != (*unpair(expected), remaining, 0):
                raise ValueError("Canonical generated state differs from the admitted output")
        except BaseException as exc:
            _tag_device_uncertainty(exc, self._failed)
            if not self._failed:
                try:
                    self.close()
                except BaseException:
                    _tag_device_uncertainty(exc, True)
            raise
        self._pair, self._energy = actual, remaining
        self._ticks, self._seeded, self._terminal = 0, True, False
        return actual, remaining

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
        if self.certificate is not None:
            raise ValueError("Generated canonical state requires admitted continuation, not a host seed")
        left, right, _, _, _ = self._live_pair(agent_pair)
        _integer(energy, 0, MAX_ENERGY, "energy")
        self._failed = True
        self._device.queue.write_buffer(self._canonical, 0, struct.pack("<4I", left, right, energy, 0))
        self._pair, self._energy = agent_pair, energy
        self._seeded = True
        self._failed = False

    @_serialized
    def admit_growth(self, source: GpuFieldAgentExecutor, cost: int) -> tuple[int, int]:
        """GD5: map an actual repaired source into this unseeded dyadic world.

        Only this candidate's buffers are written. The source remains an
        independent, completed owner until Tomigidt commits the whole epoch.
        Complete readbacks precede pure admission checks; uncertain device
        results are tagged so an owning agent can conservatively close itself.
        """
        self._check_open()
        if self._seeded:
            raise ValueError("Canonical GPU state may only be admitted once")
        if type(source) is not GpuFieldAgentExecutor or source is self:
            raise ValueError("Growth requires a distinct source GPU executor")
        from .field_world import KleinFieldRecipe
        if type(source.recipe) is not KleinFieldRecipe or type(self.recipe) is not KleinFieldRecipe:
            raise ValueError("Dyadic admission requires original Klein field recipes")
        _integer(cost, 1, 127, "growth cost")
        if self._routing is None or source._routing != self._routing:
            raise ValueError("Growth requires the same Hadamard routing binding")
        old, new = source.recipe, self.recipe
        u, v = divmod(old.center, old.height)
        if (new.width, new.height, new.center, new.radius, new.turns,
                new.baseline_id, new.version) != (
                2 * old.width, 2 * old.height, 2 * u * new.height + 2 * v,
                2 * old.radius, old.turns, old.baseline_id, old.version):
            raise ValueError("Growth candidate must be the exact dyadic recipe")
        source._check_open()
        if not source._seeded or not source._terminal:
            raise ValueError("Growth requires a completed source EMIT state")
        # The actual old canonical state, not a caller's packed-state claim.
        old_pair, old_energy = source.snapshot()
        left, right, phase, node, metadata = source._live_pair(old_pair, Opcode.EMIT)
        if cost > old_energy:
            raise EnergyExhausted("Insufficient separate energy for growth")
        old_field = source.fields[node]
        u, v = divmod(node, old.height)
        mapped = 2 * u * new.height + 2 * v
        expected = pair(pack(phase, mapped, self.fields[mapped],
                             int(Opcode.STEP) | (metadata & 16)))
        expected_energy = old_energy - cost
        # jobs: pair, energy/height, count/cost, signed old-field/new-height.
        payload = struct.pack("<8I", left, right, old_energy, old.height,
                              len(source.fields), cost, old_field & 0xffffffff, new.height)
        try:
            self._failed = True
            self._device.queue.write_buffer(self._jobs, 0, payload)
            self._dispatch(self._pipelines["admit_growth"], self._groups["admit_growth"])
            rows = self._read_outputs(1)
            canonical = struct.unpack("<4I", self._device.queue.read_buffer(self._canonical))
            # Both complete results are known. Later rejection changes no
            # admitted owner and is not an uncertain device operation.
            self._failed = False
            row = rows[0]
            actual = self._pair_from_result(row)
            self._live_pair(actual)
            if (actual, row[2], row[3], row[5:]) != (
                    expected, cost, expected_energy, (0, 0, 0)):
                raise ValueError("GPU growth disagrees with its dyadic state mapping")
            if canonical != (*unpair(expected), expected_energy, 0):
                raise ValueError("Canonical GPU growth state disagrees with its admitted result")
        except BaseException as exc:
            _tag_device_uncertainty(exc, self._failed)
            # A complete but rejected candidate is disposable, not seedable
            # again. It must never be mistaken for a usable admitted state.
            if not self._failed:
                try:
                    self.close()
                except BaseException:
                    _tag_device_uncertainty(exc, True)
            raise
        self._pair, self._energy = actual, expected_energy
        self._ticks = 0
        self._seeded = True
        self._terminal = False
        return actual, expected_energy

    @_serialized
    def forecast(self, agent_pair: int, route, hazards) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Forecast a caller-internal route; neither canonical pair nor energy changes."""
        self._check_open()
        left, right, phase, source, metadata = self._live_pair(agent_pair)
        intrinsic = (-phase if metadata & 16 else phase) & 255
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
            cost = 1 + abs(self.fields[destination]) + hazard
            if self.routing_model is not None:
                cost += self.routing_model.penalty(source, intrinsic, destination)
                intrinsic = self.routing_model.next_phase(source, intrinsic)
            costs.append(cost)
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
        _, _, phase, source, metadata = self._live_pair(self._pair)
        node = self._index(destination)
        _integer(hazard, 0, 127, "hazard")
        if node not in self._neighbors[source]:
            raise ValueError("Movement must follow an edge between distinct nodes")
        cost = 1 + abs(self.fields[node]) + hazard
        if self.routing_model is not None:
            intrinsic = (-phase if metadata & 16 else phase) & 255
            cost += self.routing_model.penalty(source, intrinsic, node)
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
