"""Exact intrinsic signed fields and one field-governed RP32 state sequence.

The numerical contracts are TK-LPLUT-SDF-1.0, ``relational-sdf-v1``.
The boundary and metric are declared graph data, not inferred physical space.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from heapq import heappop, heappush
from math import gcd

from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _keys


PROFILE = "relational-sdf-v1"
FORMAT = "relational-sdf-machine-v1"
DEFAULT_NODES = tuple(f"n{i}" for i in range(7))
DEFAULT_EDGES = tuple((i, i + 1, weight)
                      for i, weight in enumerate((2, 1, 3, 2, 1, 2)))
DEFAULT_ROUTES = tuple((min(i + 1, 6), min(i + 1, 6), max(i - 1, 0))
                       for i in range(7))
_MANIFEST_KEYS = {
    "format", "identity", "nodes", "edges", "signs", "routes", "turns",
    "unit_num", "unit_den", "initial_node", "initial_phase",
    "initial_orientation", "max_ticks",
}


def _name(value: object, label: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise ValueError(f"{label} must be a nonempty string of at most 128 characters")


def _manifest(value: object) -> None:
    if type(value) is not FieldManifest:
        raise ValueError("manifest must be a FieldManifest")


@dataclass(frozen=True)
class FieldManifest:
    """Immutable metric, separating boundary and complete operator program."""

    identity: str = "TOMIGIDt"
    nodes: tuple[str, ...] = DEFAULT_NODES
    edges: tuple[tuple[int, int, int], ...] = DEFAULT_EDGES
    signs: tuple[int, ...] = (-1, -1, -1, 0, 1, 1, 1)
    routes: tuple[tuple[int, int, int], ...] = DEFAULT_ROUTES
    turns: tuple[tuple[int, int, int], ...] = ((11, 53, 137),) * 7
    unit_num: int = 1
    unit_den: int = 1
    initial_node: int = 0
    initial_phase: int = 250
    initial_orientation: int = 0
    max_ticks: int = 65536

    def __post_init__(self) -> None:
        _name(self.identity, "identity")
        if type(self.nodes) is not tuple or not 1 <= len(self.nodes) <= 256:
            raise ValueError("nodes must be an immutable tuple of 1..256 names")
        for node in self.nodes:
            _name(node, "node")
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("nodes must have unique names")
        count = len(self.nodes)
        if type(self.signs) is not tuple or len(self.signs) != count:
            raise ValueError("signs must be an immutable tuple with one entry per node")
        for sign in self.signs:
            _integer(sign, -1, 1, "sign")
        if 0 not in self.signs:
            raise ValueError("The declared boundary must be nonempty")
        if type(self.edges) is not tuple:
            raise ValueError("edges must be an immutable tuple")
        neighbors = [set() for _ in self.nodes]
        previous = None
        for edge in self.edges:
            if type(edge) is not tuple or len(edge) != 3:
                raise ValueError("Each edge must be an immutable (u,v,weight) tuple")
            u, v, weight = edge
            _integer(u, 0, count - 1, "edge source")
            _integer(v, 0, count - 1, "edge destination")
            _integer(weight, 1, 127, "edge length")
            if u >= v:
                raise ValueError("Edges require canonical endpoints u < v")
            if previous is not None and (u, v) <= previous:
                raise ValueError("Edges must be lexicographically ordered with no duplicate pair")
            previous = (u, v)
            if self.signs[u] * self.signs[v] == -1:
                raise ValueError("An edge cannot join opposite sides without a boundary node")
            neighbors[u].add(v)
            neighbors[v].add(u)
        seen, pending = {0}, [0]
        while pending:
            for neighbor in neighbors[pending.pop()]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        if len(seen) != count:
            raise ValueError("The metric graph must be connected")
        for name, rows in (("routes", self.routes), ("turns", self.turns)):
            if type(rows) is not tuple or len(rows) != count:
                raise ValueError(f"{name} must have one immutable row per node")
            for index, row in enumerate(rows):
                if type(row) is not tuple or len(row) != 3:
                    raise ValueError(f"Each {name} row must be an immutable triple")
                for item in row:
                    _integer(item, 0, count - 1 if name == "routes" else 255, name)
                    if name == "routes" and item != index and item not in neighbors[index]:
                        raise ValueError("Every route must stay at its node or follow an edge")
        _integer(self.unit_num, 1, 1_000_000, "unit_num")
        _integer(self.unit_den, 1, 1_000_000, "unit_den")
        if gcd(self.unit_num, self.unit_den) != 1:
            raise ValueError("Distance unit must be in lowest terms")
        _integer(self.initial_node, 0, count - 1, "initial_node")
        _integer(self.initial_phase, 0, 255, "initial_phase")
        _integer(self.initial_orientation, 0, 1, "initial_orientation")
        _integer(self.max_ticks, 1, 65536, "max_ticks")

    def to_dict(self) -> dict:
        return {
            "format": PROFILE, "identity": self.identity, "nodes": list(self.nodes),
            "edges": [list(edge) for edge in self.edges], "signs": list(self.signs),
            "routes": [list(row) for row in self.routes],
            "turns": [list(row) for row in self.turns],
            "unit_num": self.unit_num, "unit_den": self.unit_den,
            "initial_node": self.initial_node, "initial_phase": self.initial_phase,
            "initial_orientation": self.initial_orientation, "max_ticks": self.max_ticks,
        }

    @classmethod
    def from_dict(cls, value: object) -> FieldManifest:
        _keys(value, _MANIFEST_KEYS, "Field manifest")
        if type(value["format"]) is not str or value["format"] != PROFILE:
            raise ValueError("Unsupported field manifest format")
        for name in ("nodes", "edges", "signs", "routes", "turns"):
            if type(value[name]) is not list:
                raise ValueError(f"{name} must be a JSON array")
        for name in ("edges", "routes", "turns"):
            if any(type(row) is not list for row in value[name]):
                raise ValueError(f"{name} rows must be JSON arrays")
        return cls(
            identity=value["identity"], nodes=tuple(value["nodes"]),
            edges=tuple(tuple(edge) for edge in value["edges"]), signs=tuple(value["signs"]),
            routes=tuple(tuple(row) for row in value["routes"]),
            turns=tuple(tuple(row) for row in value["turns"]),
            unit_num=value["unit_num"], unit_den=value["unit_den"],
            initial_node=value["initial_node"], initial_phase=value["initial_phase"],
            initial_orientation=value["initial_orientation"], max_ticks=value["max_ticks"],
        )


def _adjacency(manifest: FieldManifest) -> list[list[tuple[int, int]]]:
    result = [[] for _ in manifest.nodes]
    for u, v, weight in manifest.edges:
        result[u].append((v, weight))
        result[v].append((u, weight))
    return result


def evaluate_field(manifest: FieldManifest) -> tuple[int, ...]:
    """Compute exact signed distances with widened, multi-source Dijkstra."""
    _manifest(manifest)
    neighbors = _adjacency(manifest)
    infinity = 1 + 127 * len(manifest.nodes)
    distances = [0 if sign == 0 else infinity for sign in manifest.signs]
    pending = [(0, i) for i, sign in enumerate(manifest.signs) if sign == 0]
    # All initial priorities are equal; ascending node order is already a heap.
    while pending:
        distance, node = heappop(pending)
        if distance != distances[node]:
            continue
        for neighbor, weight in neighbors[node]:
            candidate = distance + weight
            if candidate < distances[neighbor]:
                distances[neighbor] = candidate
                heappush(pending, (candidate, neighbor))
    fields = tuple(sign * distance for sign, distance in zip(manifest.signs, distances))
    certify_field(manifest, fields)
    return fields


def certify_field(manifest: FieldManifest, values: object) -> None:
    """Certify exactness through signs, edge bounds and decreasing witnesses.

    This check does not invoke the field evaluation algorithm, so it can admit
    GPU results without a hidden CPU shortest-path computation.
    """
    _manifest(manifest)
    if type(values) not in (tuple, list) or len(values) != len(manifest.nodes):
        raise ValueError("Field values require one integer code per node")
    for sign, value in zip(manifest.signs, values):
        _integer(value, -127, 127, "signed distance")
        actual_sign = (value > 0) - (value < 0)
        if actual_sign != sign:
            raise ValueError("Field sign or zero set disagrees with the declared boundary")
    distances = tuple(abs(value) for value in values)
    for u, v, weight in manifest.edges:
        if abs(distances[u] - distances[v]) > weight:
            raise ValueError("Field violates an edge distance bound")
    neighbors = _adjacency(manifest)
    for node, sign in enumerate(manifest.signs):
        if sign != 0 and not any(distances[node] == weight + distances[neighbor]
                                 for neighbor, weight in neighbors[node]):
            raise ValueError("Field lacks a decreasing shortest-path witness")


def build_operators(manifest: FieldManifest, fields: object) -> tuple[tuple[int, int, int], ...]:
    """Compile the three field-class operators for every manifest node."""
    certify_field(manifest, fields)
    return tuple(tuple(pack(turn, destination, fields[destination], Opcode.STEP)
                       for turn, destination in zip(turns, routes))
                 for turns, routes in zip(manifest.turns, manifest.routes))


def _state_fields(value: int, manifest: FieldManifest,
                  fields: tuple[int, ...]) -> tuple[int, int, int, int]:
    left, _ = unpair(value)
    phase, node, signed, metadata = unpack(left)
    if node >= len(manifest.nodes):
        raise ValueError("Packed field state names an unknown node")
    if metadata not in (int(Opcode.STEP), int(Opcode.STEP) | 16):
        raise ValueError("Packed field state requires STEP and an optional orientation bit")
    if signed != fields[node]:
        raise ValueError("Packed field state disagrees with its node's certified distance")
    return phase, node, signed, metadata


def _hex_pair(value: object, label: str) -> int:
    if (type(value) is not str or len(value) != 16
            or any(char not in "0123456789ABCDEF" for char in value)):
        raise ValueError(f"{label} requires sixteen uppercase hexadecimal digits")
    result = int(value, 16)
    unpair(result)
    return result


class FieldMachine:
    """One finite packed individual whose current field selects its next operator."""

    def __init__(self, manifest: FieldManifest | None = None, backend: str = "cpu"):
        self._manifest = FieldManifest() if manifest is None else manifest
        _manifest(self._manifest)
        if type(backend) is not str or backend not in ("cpu", "gpu"):
            raise ValueError("backend must be cpu or gpu")
        self._backend = backend
        self._executor = None
        self._closed = False
        self._tick = 0
        self._trace: list[int] = []
        self._adapter_info = None
        try:
            if backend == "gpu":
                from .sdf_gpu import GpuFieldExecutor
                self._executor = GpuFieldExecutor(self.manifest)
                self._fields = tuple(self._executor.fields)
                certify_field(self.manifest, self._fields)
                self._operators = None
                self._adapter_info = deepcopy(self._executor.adapter_info)
            else:
                self._fields = evaluate_field(self.manifest)
                self._operators = build_operators(self.manifest, self.fields)
            seed = self.manifest
            self._pair = pair(pack(seed.initial_phase, seed.initial_node,
                                   self.fields[seed.initial_node],
                                   int(Opcode.STEP) | (seed.initial_orientation << 4)))
            if self._executor is not None:
                self._executor.reset(self._pair)
        except BaseException:
            self.close()
            raise

    @property
    def manifest(self) -> FieldManifest:
        return self._manifest

    @property
    def fields(self) -> tuple[int, ...]:
        return self._fields

    @property
    def agent_pair(self) -> int:
        return self._pair

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def execution_info(self) -> dict:
        result = {"backend": self._backend}
        if self._adapter_info is not None:
            result["adapter"] = deepcopy(self._adapter_info)
        return result

    def advance(self, steps: int) -> tuple[int, ...]:
        if self._closed:
            raise ValueError("Field machine is closed")
        _integer(steps, 1, 4096, "steps")
        if steps > self.manifest.max_ticks - self.tick:
            raise ValueError("Advance exceeds the remaining tick budget")
        _state_fields(self.agent_pair, self.manifest, self.fields)
        if self._executor is not None:
            try:
                outputs = tuple(self._executor.advance(steps))
                if len(outputs) != steps:
                    raise ValueError("GPU advance returned an incorrect number of tick outputs")
                for value in outputs:
                    _state_fields(value, self.manifest, self.fields)
            except BaseException:
                # Device progress after a failed batch is uncertain. Refuse reuse;
                # the caller can reconstruct the last admitted canonical archive.
                self.close()
                raise
        else:
            state = self.agent_pair
            generated = []
            for _ in range(steps):
                phase, node, signed, metadata = _state_fields(state, self.manifest, self.fields)
                column = 0 if signed < 0 else 1 if signed == 0 else 2
                turn, destination, field, _ = unpack(self._operators[node][column])
                direction = -1 if metadata & 16 else 1
                state = pair(pack((phase + direction * turn) % 256,
                                  destination, field, metadata))
                generated.append(state)
            outputs = tuple(generated)
        self._pair = outputs[-1]
        self._tick += steps
        self._trace.extend(outputs)
        return outputs

    def snapshot(self) -> dict:
        _, node, _, _ = _state_fields(self.agent_pair, self.manifest, self.fields)
        return {"identity": self.manifest.identity, "tick": self.tick,
                "node": self.manifest.nodes[node], "agent_pair": f"{self.agent_pair:016X}"}

    def archive(self) -> dict:
        return {"format": FORMAT, "manifest": self.manifest.to_dict(),
                "trace": [f"{value:016X}" for value in self._trace],
                "expected": self.snapshot()}

    @classmethod
    def from_archive(cls, value: object, backend: str = "cpu") -> FieldMachine:
        _keys(value, {"format", "manifest", "trace", "expected"}, "Field machine archive")
        if type(value["format"]) is not str or value["format"] != FORMAT:
            raise ValueError("Unsupported field machine archive format")
        manifest = FieldManifest.from_dict(value["manifest"])
        if type(value["trace"]) is not list or len(value["trace"]) > manifest.max_ticks:
            raise ValueError("Trace must be a JSON array within the declared tick budget")
        trace = tuple(_hex_pair(encoded, "Trace pair") for encoded in value["trace"])
        expected = value["expected"]
        _keys(expected, {"identity", "tick", "node", "agent_pair"}, "Expected field state")
        _name(expected["identity"], "Expected identity")
        _integer(expected["tick"], 0, manifest.max_ticks, "Expected tick")
        if type(expected["node"]) is not str or expected["node"] not in manifest.nodes:
            raise ValueError("Expected node must name a manifest node")
        _hex_pair(expected["agent_pair"], "Expected pair")
        machine = cls(manifest, backend=backend)
        try:
            for start in range(0, len(trace), 4096):
                batch = trace[start:start + 4096]
                if machine.advance(len(batch)) != batch:
                    raise ValueError("Replayed field outputs disagree with the retained trace")
            if machine.snapshot() != expected:
                raise ValueError("Replayed field state disagrees with the retained expected state")
            return machine
        except BaseException:
            machine.close()
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._executor is not None:
                self._executor.close()
