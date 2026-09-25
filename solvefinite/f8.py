"""PX1-PX8: a certified finite index of Klein scalar-node descriptors.

Keys and preorder storage rows are separate from geometric node identities.
The immutable index retains neither scalar field values nor packed samples.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

from .field import certify_field, evaluate_field
from .runtime import _integer, _keys

if TYPE_CHECKING:
    from .field_world import KleinFieldRecipe


PROFILE = "f8-klein-sdf-v1"
SNAPSHOT_FORMAT = "f8-klein-index-snapshot-v1"
MAX_EPOCH = (1 << 31) - 1
NULL = 256
_U32 = (1 << 32) - 1


@dataclass(frozen=True, slots=True)
class IndexBinding:
    epoch: int = 0
    psi_sign: int = 1
    phase_origin: int = 0
    format: str = PROFILE

    def __post_init__(self):
        if type(self.format) is not str or self.format != PROFILE:
            raise ValueError("Unsupported f8 index format")
        _integer(self.epoch, 0, MAX_EPOCH, "index epoch")
        if type(self.psi_sign) is not int or self.psi_sign not in (-1, 1):
            raise ValueError("psi_sign must be -1 or +1")
        _integer(self.phase_origin, 0, 255, "index phase_origin")

    def to_dict(self) -> dict:
        return {"format": self.format, "epoch": self.epoch,
                "psi_sign": self.psi_sign, "phase_origin": self.phase_origin}

    @classmethod
    def from_dict(cls, value: object) -> IndexBinding:
        _keys(value, {"format", "epoch", "psi_sign", "phase_origin"}, "Index binding")
        return cls(**value)

    def next(self, *, psi_sign=None, phase_origin=None) -> IndexBinding:
        """Prepare one new version; never modify this binding."""
        if self.epoch == MAX_EPOCH:
            raise ValueError("Index epoch exhausted")
        return IndexBinding(self.epoch + 1,
                            self.psi_sign if psi_sign is None else psi_sign,
                            self.phase_origin if phase_origin is None else phase_origin)


def _recipe(value):
    # FieldWorld uses this module; defer this import to avoid a module cycle.
    from .field_world import KleinFieldRecipe
    if type(value) is not KleinFieldRecipe:
        raise ValueError("recipe must be a KleinFieldRecipe")


def _binding(value):
    if type(value) is not IndexBinding:
        raise ValueError("binding must be an IndexBinding")


@dataclass(frozen=True, slots=True)
class IndexGeometry:
    directions: tuple[tuple[int, int, int, int], ...]
    distances: tuple[int, ...]
    parents: tuple[int, ...]


def build_geometry(recipe: KleinFieldRecipe) -> IndexGeometry:
    """Derive directional neighbors, exact depths and numeric parent ties."""
    _recipe(recipe)
    domain = recipe.domain()
    directions = tuple(tuple(domain.step(node, direction)[0]
                             for direction in ("u+", "u-", "v+", "v-"))
                       for node in range(len(domain.nodes)))
    distances = [-1] * len(directions)
    distances[recipe.center] = 0
    pending = deque([recipe.center])
    while pending:
        node = pending.popleft()
        for neighbor in directions[node]:
            if distances[neighbor] == -1:
                distances[neighbor] = distances[node] + 1
                pending.append(neighbor)
    parents = tuple(recipe.center if node == recipe.center else
                    min(neighbor for neighbor in adjacent
                        if distances[neighbor] == distances[node] - 1)
                    for node, adjacent in enumerate(directions))
    return IndexGeometry(directions, tuple(distances), parents)


def _compile_records(recipe, binding, fields, geometry):
    from .psi import field_axes
    axes = field_axes(recipe.domain(), fields, binding.psi_sign)
    phases = [0] * len(fields)
    phases[recipe.center] = binding.phase_origin
    for node in sorted(range(len(fields)), key=lambda item: (geometry.distances[item], item)):
        if node != recipe.center:
            parent = geometry.parents[node]
            column = 0 if fields[parent] < 0 else 1 if fields[parent] == 0 else 2
            phases[node] = (phases[parent] + recipe.turns[column]) % 256
    return tuple((axis.vector[0] + 2, axis.vector[1] + 2,
                  (geometry.distances[node] + 1).bit_length() - 1,
                  phases[node], node, axis.eigenvalue,
                  axis.gradient[0] + 2, axis.gradient[1] + 2)
                 for node, axis in enumerate(axes))


def _compile_rows(records):
    ordered = sorted(record[:5] for record in records)
    rows = []

    def emit(lo, hi):
        if lo == hi:
            return NULL
        middle = (lo + hi - 1) // 2
        row = len(rows)
        rows.append(None)
        left, right = emit(lo, middle), emit(middle + 1, hi)
        rows[row] = (*ordered[middle], left, right, 0)
        return row

    emit(0, len(ordered))
    return tuple(rows)


def _matrix(value, count, label):
    if type(value) not in (tuple, list) or len(value) != count:
        raise ValueError(f"{label} requires one eight-word row per node")
    result = []
    for row in value:
        if type(row) not in (tuple, list) or len(row) != 8:
            raise ValueError(f"{label} requires eight-word rows")
        for word in row:
            _integer(word, 0, _U32, label)
        result.append(tuple(row))
    return tuple(result)


def _certify_records(recipe, binding, records, fields, geometry):
    """Check equations and witnesses independently of the CPU compilers."""
    domain = recipe.domain()
    seam_edges = frozenset(domain.seams)
    depths, parents = geometry.distances, geometry.parents
    # Validate every decreasing parent witness before following any path.
    # Together with the edge bounds and unique zero root, these witnesses
    # certify exact shortest depths rather than merely plausible labels.
    for node, adjacent in enumerate(geometry.directions):
        if node == recipe.center:
            if depths[node] != 0 or parents[node] != node:
                raise ValueError("Index root depth or parent is inconsistent")
        else:
            predecessors = tuple(neighbor for neighbor in adjacent
                                 if depths[neighbor] == depths[node] - 1)
            if (depths[node] <= 0 or not predecessors
                    or parents[node] != min(predecessors)):
                raise ValueError("Index parent violates depth or numeric tie rule")
        if any(abs(depths[node] - depths[neighbor]) > 1 for neighbor in adjacent):
            raise ValueError("Index depth violates a geometric edge")

    for node, (record, adjacent) in enumerate(zip(records, geometry.directions)):
        gu = fields[adjacent[0]] - fields[adjacent[1]]
        gv = fields[adjacent[2]] - fields[adjacent[3]]
        if not (-2 <= gu <= 2 and -2 <= gv <= 2):
            raise ValueError("Field gradient exceeds the PX2 bound")
        common = gcd(abs(gu), abs(gv))
        pu, pv = (gu // common, gv // common) if common else (1, 0)
        pu, pv = binding.psi_sign * pu, binding.psi_sign * pv
        eigenvalue = gu * gu + gv * gv
        if (record[0], record[1], record[4], record[5], record[6], record[7]) != (
                pu + 2, pv + 2, node, eigenvalue, gu + 2, gv + 2):
            raise ValueError("Index record disagrees with its field-derived Psi")
        if ((gu * gu * pu + gu * gv * pv, gu * gv * pu + gv * gv * pv)
                != (eigenvalue * pu, eigenvalue * pv)
                or gcd(abs(pu), abs(pv)) != 1):
            raise ValueError("Index axis fails the primitive eigen-equation")
        if record[2] != (depths[node] + 1).bit_length() - 1:
            raise ValueError("Index radius code disagrees with its intrinsic depth")

        # The compiler uses the scalar recurrence. Independently transport the
        # complete K8 phase/orientation along the unique parent path here.
        path, cursor = [], node
        while cursor != recipe.center:
            path.append(cursor)
            cursor = parents[cursor]
        phase, orientation, source = binding.phase_origin, 0, recipe.center
        for destination in reversed(path):
            column = 0 if fields[source] < 0 else 1 if fields[source] == 0 else 2
            phase = (phase + (-1 if orientation else 1) * recipe.turns[column]) % 256
            seam = int((min(source, destination), max(source, destination)) in seam_edges)
            phase = (-phase if seam else phase) % 256
            orientation ^= seam
            source = destination
        theta = (-phase if orientation else phase) % 256
        if record[3] != theta:
            raise ValueError("Index phase disagrees with K8 parent-path transport")


def _certify_tree(records, rows):
    """Validate the submitted tree without constructing a replacement tree."""
    count = len(records)
    seen_rows, seen_nodes, preorder = set(), set(), []

    def visit(row, lower=None, upper=None):
        if row == NULL:
            return 0
        if not 0 <= row < count or row in seen_rows:
            raise ValueError("Index tree has an invalid, repeated or cyclic child")
        seen_rows.add(row)
        preorder.append(row)
        stored = rows[row]
        key, node = stored[:5], stored[4]
        if (node >= count or node in seen_nodes or key != records[node][:5]
                or stored[7] != 0):
            raise ValueError("Index tree has a wrong, repeated or malformed identity")
        if (lower is not None and key <= lower) or (upper is not None and key >= upper):
            raise ValueError("Index tree violates its strict key order")
        seen_nodes.add(node)
        left_size = visit(stored[5], lower, key)
        right_size = visit(stored[6], key, upper)
        total = 1 + left_size + right_size
        if left_size != (total - 1) // 2:
            raise ValueError("Index tree violates the exact lower-median rule")
        return total

    if visit(0) != count or seen_nodes != set(range(count)):
        raise ValueError("Index tree does not cover every canonical node")
    if preorder != list(range(count)):
        raise ValueError("Index rows are not in canonical preorder")


@dataclass(frozen=True, slots=True, init=False)
class F8Index:
    _recipe: KleinFieldRecipe
    _binding: IndexBinding
    _records: tuple[tuple[int, ...], ...]
    _rows: tuple[tuple[int, ...], ...]

    def __init__(self, *args, **kwargs):
        raise TypeError("Construct an F8Index with build or certified")

    @classmethod
    def build(cls, recipe, binding=None, fields=None) -> F8Index:
        _recipe(recipe)
        binding = IndexBinding() if binding is None else binding
        _binding(binding)
        manifest = recipe.field_manifest()
        fields = evaluate_field(manifest) if fields is None else fields
        certify_field(manifest, fields)
        geometry = build_geometry(recipe)
        records = _compile_records(recipe, binding, fields, geometry)
        rows = _compile_rows(records)
        return cls.certified(recipe, binding, records, rows, fields)

    @classmethod
    def certified(cls, recipe, binding, records, rows, fields) -> F8Index:
        """Admit device/other results with no CPU key, tree or Psi compilation."""
        _recipe(recipe)
        _binding(binding)
        manifest = recipe.field_manifest()
        certify_field(manifest, fields)
        count = recipe.width * recipe.height
        records = _matrix(records, count, "Index records")
        rows = _matrix(rows, count, "Index rows")
        geometry = build_geometry(recipe)
        _certify_records(recipe, binding, records, fields, geometry)
        _certify_tree(records, rows)
        result = object.__new__(cls)
        object.__setattr__(result, "_recipe", recipe)
        object.__setattr__(result, "_binding", binding)
        object.__setattr__(result, "_records", records)
        object.__setattr__(result, "_rows", rows)
        return result

    @property
    def recipe(self):
        return self._recipe

    @property
    def binding(self):
        return self._binding

    @property
    def records(self):
        return self._records

    @property
    def rows(self):
        return self._rows

    def key(self, node: int) -> tuple[int, ...]:
        _integer(node, 0, len(self.records) - 1, "index node")
        return self.records[node][:5]

    def lookup(self, key) -> int | None:
        """Walk at most bit_length(N) rows; a valid absent u32 key is a MISS."""
        if type(key) not in (tuple, list) or len(key) != 5:
            raise ValueError("An index query requires five u32 components")
        for component in key:
            _integer(component, 0, _U32, "query key component")
        key = tuple(key)
        row, count = 0, len(self.rows)
        lower = upper = None
        for _ in range(count.bit_length()):
            if row == NULL:
                return None
            if not 0 <= row < count:
                raise ValueError("Index lookup reached an invalid row")
            stored = self.rows[row]
            current, node = stored[:5], stored[4]
            if (not 0 <= node < count or current != self.records[node][:5]
                    or stored[7] != 0
                    or (lower is not None and current <= lower)
                    or (upper is not None and current >= upper)):
                raise ValueError("Index lookup reached a malformed key or identity")
            if key == current:
                return row
            if key < current:
                row, upper = stored[5], current
            else:
                row, lower = stored[6], current
        if row == NULL:
            return None
        raise ValueError("Index lookup exceeded its certified depth bound")

    def resolve(self, node: int) -> int:
        row = self.lookup(self.key(node))
        if row is None or self.rows[row][4] != node:
            raise ValueError("Index failed to resolve its canonical node")
        return row

    def lookup_chart(self, u: int, v: int) -> int:
        return self.resolve(self.recipe.domain().node(u, v))

    def rebuild(self, *, psi_sign=None, phase_origin=None, fields=None) -> F8Index:
        binding = self.binding.next(psi_sign=psi_sign, phase_origin=phase_origin)
        return type(self).build(self.recipe, binding, fields)

    def snapshot(self) -> dict:
        return {"format": SNAPSHOT_FORMAT, "recipe": self.recipe.to_dict(),
                "binding": self.binding.to_dict(),
                "records": [list(record) for record in self.records],
                "rows": [list(row) for row in self.rows]}

    @classmethod
    def from_snapshot(cls, value: object) -> F8Index:
        from .field_world import KleinFieldRecipe
        _keys(value, {"format", "recipe", "binding", "records", "rows"}, "Index snapshot")
        if type(value["format"]) is not str or value["format"] != SNAPSHOT_FORMAT:
            raise ValueError("Unsupported index snapshot format")
        for label in ("records", "rows"):
            if type(value[label]) is not list or any(type(row) is not list for row in value[label]):
                raise ValueError("Index snapshot records and rows must be JSON arrays")
        recipe = KleinFieldRecipe.from_dict(value["recipe"])
        binding = IndexBinding.from_dict(value["binding"])
        fields = evaluate_field(recipe.field_manifest())
        return cls.certified(recipe, binding, value["records"], value["rows"], fields)
