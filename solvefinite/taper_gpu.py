"""DP9 device taper interpretation, projected occupancy and exact redistance.

Only grammar structure is compiled on the host. Cursor states, primitive
centres, signs and distance codes are actual device outputs. Each retained
stage is independently checked before its field becomes the next waveguide.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct

from .rp32 import unpair
from .sdf_gpu import GpuFieldExecutor, _tag_device_uncertainty


class GpuTaperGeometry:
    """Detached candidate geometry; the owning agent admits its state separately."""

    def __init__(self, recipe):
        from .taper import (TaperFieldRecipe, compile_tape, preflight,
                            encode_tape, certify_stage)
        if type(recipe) is not TaperFieldRecipe:
            raise ValueError("recipe must be a TaperFieldRecipe")
        # All structure/argument/work rejection precedes any GPU allocation.
        tapes = tuple(compile_tape(recipe.taper, stage) for stage in recipe.stages)
        budgets = tuple(preflight(tape, recipe.taper, recipe) for tape in tapes)
        encoded = tuple(encode_tape(tape) for tape in tapes)
        self._base = None
        self._extra_buffers = []
        self._textures = []
        self._closed = False
        self._uncertain = False
        self.certificate = None
        self.recipe = recipe
        self._logical_capacity = max(map(len, tapes))
        self._tape_capacity = max(map(len, encoded))
        self._step_capacity = max(1, max(b.effective_steps for b in budgets))
        self._primitive_capacity = max(b.primitives for b in budgets)
        self._primitive_site_capacity = max(b.primitive_sites for b in budgets)
        self._peak_host_stage_payload_bytes = 0
        self._host_tape_metadata_bytes = sum(len(json.dumps(
            [instruction.to_dict() for instruction in tape], sort_keys=True,
            separators=(',', ':'), ensure_ascii=True).encode('utf-8')) for tape in tapes)
        self._host_tape_word_bytes = sum(4 * len(words) for words in encoded)
        try:
            self._base = GpuFieldExecutor(recipe.base.field_manifest())
            self._device, self._wgpu = self._base._device, self._base._wgpu
            self._field_buffer = self._base._field_buffer
            self.adapter_info = dict(self._base.adapter_info)
            self._fields = self._base.fields
            self._allocate()
            for index, (context, tape, budget, words) in enumerate(zip(recipe.stages, tapes, budgets, encoded)):
                prior = self._fields
                document, signs, fields = self._stage(context, tape, budget, words)
                prefix = replace(recipe, stages=recipe.stages[:index + 1])
                old_transcript_bytes = (0 if self.certificate is None else
                                        len(self._canonical_document_bytes()))
                transcript_bytes = len(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=True, allow_nan=False).encode('utf-8'))
                certificate = certify_stage(prefix, prior, document, signs, fields,
                                            prior_certificate=self.certificate)
                self.certificate = certificate
                self._fields = certificate.fields
                self._manifest = certificate.manifest
                self._peak_host_stage_payload_bytes = max(
                    self._peak_host_stage_payload_bytes,
                    4 * (len(prior) + len(signs) + len(fields))
                    + 32 * (len(tape) + max(1, budget.effective_steps)) + 48 * budget.primitives + 64
                    + self._host_tape_word_bytes + self._host_tape_metadata_bytes
                    + old_transcript_bytes + 2 * transcript_bytes)
            # Keep the composed field engine internally consistent, including
            # its unused fixed-route operator atlas. Agent state lives elsewhere.
            self._compile_final_operators()
        except BaseException as exc:
            _tag_device_uncertainty(exc, self._uncertain)
            try:
                self.close()
            except BaseException:
                _tag_device_uncertainty(exc, True)
            raise

    @property
    def _buffers(self):
        return ([] if self._base is None else self._base._buffers) + self._extra_buffers

    @property
    def fields(self):
        return self._fields

    @property
    def manifest(self):
        return self._manifest

    @property
    def last_derivation(self):
        return self.certificate.last_derivation

    @property
    def stage_digests(self):
        return self.certificate.stage_digests

    @property
    def extra_texture_bytes(self):
        return 4 * self._tape_capacity + 16 * len(self.fields)

    @property
    def allocation_info(self):
        return {"instruction_texture_bytes": 4 * self._tape_capacity,
                "grammar_movement_texture_bytes": 16 * len(self.fields),
                "grammar_scratch_buffer_bytes": sum(x.size for x in self._extra_buffers),
                "grammar_private_stack_payload_bytes": 32 * 20,
                "primitive_record_buffer_bytes": 48 * self._primitive_capacity,
                "occupancy_buffer_bytes": 4 * len(self.fields),
                "maximum_primitive_sites": self._primitive_site_capacity,
                "maximum_logical_instructions": self._logical_capacity,
                "maximum_instruction_texels": self._tape_capacity,
                "peak_grammar_host_stage_payload_bytes": self._peak_host_stage_payload_bytes,
                "peak_grammar_host_tape_metadata_bytes": self._host_tape_metadata_bytes,
                "peak_grammar_host_tape_word_bytes": self._host_tape_word_bytes,
                "grammar_retained_transcript_bytes": len(self._canonical_document_bytes()),
                "grammar_retained_recipe_bytes": len(json.dumps(self.recipe.to_dict(), sort_keys=True,
                    separators=(',', ':'), ensure_ascii=True).encode('utf-8')),
                "grammar_stage_count": len(self.recipe.stages),
                "accounting": "Logical buffer, packed stack and canonical JSON payloads. "
                    "Host stage peak includes all expanded tapes, raw output rows, prior/current "
                    "fields and old/current transcript bytes. Python containers, validation "
                    "temporaries and driver/compiler overhead are separate."}

    def _canonical_document_bytes(self):
        return json.dumps(self.last_derivation, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')

    def _buffer(self, size, data=None):
        usage = self._wgpu.BufferUsage
        result = self._device.create_buffer(size=size, usage=usage.STORAGE | usage.COPY_SRC | usage.COPY_DST)
        self._extra_buffers.append(result)
        if data is not None:
            self._uncertain = True
            self._device.queue.write_buffer(result, 0, data)
        return result

    def _group(self, pipeline, entries):
        return self._device.create_bind_group(layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": key, "resource": value} for key, value in entries.items()])

    def _allocate(self):
        count = len(self.fields)
        self._config = self._buffer(96)
        self._traces = self._buffer(32 * self._logical_capacity)
        self._segments = self._buffer(32 * self._step_capacity)
        self._primitives = self._buffer(48 * self._primitive_capacity)
        self._status = self._buffer(64)
        self._occupancy = self._buffer(4 * count)
        self._signs = self._buffer(4 * count)
        self._distances = (self._buffer(4 * count), self._buffer(4 * count))
        lengths = [0] * (count * count)
        for a, b, weight in self.recipe.base.domain().edges:
            lengths[a * count + b] = lengths[b * count + a] = weight
        self._weights = self._buffer(4 * count * count, struct.pack(f"<{count * count}I", *lengths))
        usage = self._wgpu.TextureUsage
        self._tape = self._device.create_texture(size=(self._tape_capacity, 1, 1), format="r32uint",
                                                usage=usage.TEXTURE_BINDING | usage.COPY_DST)
        self._textures.append(self._tape)
        self._movements = self._device.create_texture(size=(4, count, 1), format="r32uint",
                                        usage=usage.TEXTURE_BINDING | usage.STORAGE_BINDING)
        self._textures.append(self._movements)
        path = Path(__file__).with_name("shaders")
        shader = self._device.create_shader_module(code=(path / "taper.wgsl").read_text(encoding="utf-8"))
        self._pipelines = {entry: self._device.create_compute_pipeline(
            layout="auto", compute={"module": shader, "entry_point": entry})
            for entry in ("compile_movements", "interpret", "clear_occupancy", "generate_occupancy", "generate_signs")}
        r = GpuFieldExecutor._resource
        common = {0: r(self._config), 1: r(self._field_buffer)}
        self._groups = {
            "compile_movements": self._group(self._pipelines["compile_movements"],
                              {**common, 4: self._movements.create_view()}),
            "interpret": self._group(self._pipelines["interpret"], {
                **common, 2: self._tape.create_view(), 3: self._movements.create_view(),
                5: r(self._traces), 6: r(self._segments), 7: r(self._primitives), 8: r(self._status)}),
            "clear_occupancy": self._group(self._pipelines["clear_occupancy"], {
                0: r(self._config), 10: r(self._occupancy)}),
            "generate_occupancy": self._group(self._pipelines["generate_occupancy"], {
                0: r(self._config), 7: r(self._primitives), 8: r(self._status), 10: r(self._occupancy)}),
            "generate_signs": self._group(self._pipelines["generate_signs"], {
                0: r(self._config), 9: r(self._signs), 10: r(self._occupancy)})}
        field_shader = self._device.create_shader_module(code=(path / "field.wgsl").read_text(encoding="utf-8"))
        self._field_pipelines = {entry: self._device.create_compute_pipeline(
            layout="auto", compute={"module": field_shader, "entry_point": entry})
            for entry in ("initialize_distances", "relax_distances", "write_fields", "compile_operators")}
        self._field_config = self._buffer(16, struct.pack("<4I", count, 0, 65536, 0))
        p = self._field_pipelines
        self._distance_init = self._group(p["initialize_distances"], {
            0: r(self._field_config), 1: r(self._signs), 4: r(self._distances[0])})
        self._distance_relax = tuple(self._group(p["relax_distances"], {
            0: r(self._field_config), 2: r(self._weights), 3: r(self._distances[i]),
            4: r(self._distances[1 - i])}) for i in (0, 1))
        self._distance_finish = self._group(p["write_fields"], {
            0: r(self._field_config), 1: r(self._signs),
            3: r(self._distances[(count - 1) % 2]), 5: r(self._field_buffer)})

    def _dispatch(self, entry, groups=1):
        encoder = self._device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(self._pipelines[entry])
        compute.set_bind_group(0, self._groups[entry])
        compute.dispatch_workgroups(*(groups if isinstance(groups, tuple) else (groups,)))
        compute.end()
        self._device.queue.submit([encoder.finish()])

    def _stage(self, context, tape, budget, words):
        count = len(self.fields)
        left, right = unpair(int(context.start_pair, 16))
        workgroups = (budget.primitive_sites + 63) // 64
        groups_x = min(workgroups, 65535)
        groups_y = (workgroups + groups_x - 1) // groups_x
        values = (count, self.recipe.width, self.recipe.height, len(tape),
                  budget.effective_steps, budget.primitives, budget.stack_high_water, left, right,
                  *self.recipe.turns, *(gain & 0xffffffff for row in self.recipe.routing.gains for gain in row),
                  len(words), self.recipe.taper.limits["max_primitive_sites"],
                  budget.primitive_sites, groups_x * 64)
        self._uncertain = True
        self._device.queue.write_buffer(self._config, 0, struct.pack("<24I", *values))
        row_bytes = ((4 * len(words) + 255) // 256) * 256
        data = struct.pack(f"<{len(words)}I", *words) + bytes(row_bytes - 4 * len(words))
        self._device.queue.write_texture({"texture": self._tape}, data,
            {"offset": 0, "bytes_per_row": row_bytes, "rows_per_image": 1}, (len(words), 1, 1))
        self._dispatch("compile_movements", (4 * count + 63) // 64)
        self._dispatch("interpret")
        status = struct.unpack("<16I", self._device.queue.read_buffer(self._status))
        trace_raw = bytes(self._device.queue.read_buffer(self._traces, 0, 32 * len(tape)))
        segment_raw = bytes(self._device.queue.read_buffer(self._segments, 0, 32 * max(1, budget.effective_steps)))
        primitive_raw = bytes(self._device.queue.read_buffer(self._primitives, 0, 48 * budget.primitives))
        self._uncertain = False
        if (status[0] or status[1:4] != (len(tape), budget.effective_steps, budget.primitives)
                or status[10:12] != (budget.primitive_sites, len(words))):
            raise ValueError(f"Device grammar rejected instruction/state or output counts: {status[:4]}")
        document = self._document(context, tape, status, trace_raw, segment_raw, primitive_raw)
        self._uncertain = True
        self._dispatch("clear_occupancy", (count + 63) // 64)
        self._dispatch("generate_occupancy", (groups_x, groups_y))
        self._dispatch("generate_signs", (count + 63) // 64)
        signs = tuple(struct.unpack(f"<{count}i", self._device.queue.read_buffer(self._signs)))
        self._uncertain = False
        if 0 not in signs or any(sign not in (-1, 0, 1) for sign in signs):
            raise ValueError("Generated device boundary must be nonempty with legal signs")
        self._uncertain = True
        encoder = self._device.create_command_encoder()
        p = self._field_pipelines
        groups = (count + 63) // 64
        GpuFieldExecutor._pass(encoder, p["initialize_distances"], self._distance_init, groups)
        for i in range(count - 1):
            GpuFieldExecutor._pass(encoder, p["relax_distances"], self._distance_relax[i % 2], groups)
        GpuFieldExecutor._pass(encoder, p["write_fields"], self._distance_finish, groups)
        self._device.queue.submit([encoder.finish()])
        fields = tuple(struct.unpack(f"<{count}i", self._device.queue.read_buffer(self._field_buffer)))
        self._uncertain = False
        return document, signs, fields

    @staticmethod
    def _document(context, tape, status, trace_raw, segment_raw, primitive_raw):
        # Addresses are static source metadata. The device reports its actual
        # enclosing PUSH and depth; both must match that lexical branch frame.
        branches = {0xffffffff: ()}
        stack = []
        for pc, instruction in enumerate(tape):
            if instruction.symbol == "[":
                stack.append(instruction.address)
                branches[pc] = tuple(stack)
            elif instruction.symbol == "]":
                stack.pop()
        def branch(top, depth):
            if top not in branches or len(branches[top]) != depth:
                raise ValueError("Device branch identity disagrees with its tape")
            return [list(address) for address in branches[top]]
        def pair_hex(left, right):
            value = left | right << 32
            unpair(value)
            return f"{value:016X}"
        traces, segments, primitives = [], [], []
        for row in struct.iter_unpack("<8I", trace_raw):
            pc, top, depth, left, right, radius, scale, reserved = row
            if pc != len(traces) or pc >= len(tape) or reserved:
                raise ValueError("Device terminal trace order or reserved lane is invalid")
            traces.append({"address": list(tape[pc].address), "branch_path": branch(top, depth),
                           "pair": pair_hex(left, right), "radius": radius, "scale": scale})
        for row in tuple(struct.iter_unpack("<8I", segment_raw))[:status[2]]:
            pc, step, top, depth, left, right, a, b = row
            if pc >= len(tape) or a or b:
                raise ValueError("Device segment address or reserved lane is invalid")
            segments.append({"address": list(tape[pc].address), "branch_path": branch(top, depth),
                             "step": step, "pair": pair_hex(left, right)})
        previous_offset = -1
        for row in struct.iter_unpack("<12I", primitive_raw):
            kind, pc, top, depth, node, extent, numerator, denominator, shaft, left, right, offset = row
            if pc >= len(tape) or not previous_offset < offset < status[10]:
                raise ValueError("Device primitive address or work offset is invalid")
            previous_offset = offset
            common = {"address": list(tape[pc].address), "branch_path": branch(top, depth),
                      "pair": pair_hex(left, right)}
            if kind == 0 and numerator == denominator == shaft == 0:
                primitives.append({"kind": "ball", **common, "center": node, "radius": extent})
            elif kind == 1:
                primitives.append({"kind": "taper", **common, "apex": node, "height": extent,
                                   "numerator": numerator, "denominator": denominator, "shaft": shaft})
            else:
                raise ValueError("Device primitive kind or reserved arguments are invalid")
        if status[12:] != (0, 0, 0, 0):
            raise ValueError("Device final reserved state must be zero")
        return {"format": "klein-taper-derivation-v1", "context": context.to_dict(),
                "tape": [instruction.to_dict() for instruction in tape], "trace": traces,
                "segments": segments, "primitives": primitives,
                "final_context": {"branch_path": branch(status[9], status[8]),
                                  "pair": pair_hex(status[4], status[5]),
                                  "radius": status[6], "scale": status[7]}}

    def _compile_final_operators(self):
        count = len(self.fields)
        r = GpuFieldExecutor._resource
        rules = tuple(value for node in range(count) for column in range(3)
                      for value in (self.manifest.routes[node][column], self.manifest.turns[node][column]))
        rule_buffer = self._buffer(4 * len(rules), struct.pack(f"<{len(rules)}I", *rules))
        stride = (count + 31) // 32
        seam_words = [0] * (count * stride)
        for a, b in self.manifest.seams:
            seam_words[a * stride + b // 32] |= 1 << (b % 32)
            seam_words[b * stride + a // 32] |= 1 << (a % 32)
        seams = self._buffer(4 * len(seam_words), struct.pack(f"<{len(seam_words)}I", *seam_words))
        pipeline = self._field_pipelines["compile_operators"]
        group = self._group(pipeline, {0: r(self._field_config), 5: r(self._field_buffer),
            6: r(rule_buffer), 7: self._base._texture.create_view(), 11: r(seams)})
        self._uncertain = True
        encoder = self._device.create_command_encoder()
        GpuFieldExecutor._pass(encoder, pipeline, group, (3 * count + 63) // 64)
        self._device.queue.submit([encoder.finish()])
        # Fence construction before publishing this fully certified candidate.
        actual = tuple(struct.unpack(f"<{count}i", self._device.queue.read_buffer(self._field_buffer)))
        self._uncertain = False
        if actual != self.fields:
            raise ValueError("Generated field changed during final operator compilation")
        self._base._fields, self._base._manifest = self.fields, self.manifest

    def close(self):
        if self._closed:
            return
        self._closed = True
        first = None
        for resource in [*self._extra_buffers, *self._textures]:
            try:
                resource.destroy()
            except BaseException as exc:
                first = first or exc
        if self._base is not None:
            try:
                self._base.close()
            except BaseException as exc:
                first = first or exc
        if first is not None:
            raise first
