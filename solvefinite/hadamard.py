"""HP1, HP2 and HP6: exact, certified phase-directed routing tables.

The diagonal gains act on decoded gradient/eigen-axis components. Packed
metadata is never an arithmetic vector. A model retains 17 integers per
node, alongside its recipe and geometry; it retains no scalar-field arena.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

from .field import certify_field, evaluate_field
from .runtime import _integer, _keys

if TYPE_CHECKING:
    from .field_world import KleinFieldRecipe


PROFILE = "hadamard-klein-routing-v1"
DEFAULT_GAINS = ((1, 1), (-1, 1), (-1, -1), (1, -1))
_DIRECTIONS = (("u+", (1, 0)), ("u-", (-1, 0)),
               ("v+", (0, 1)), ("v-", (0, -1)))


@dataclass(frozen=True, slots=True)
class HadamardBinding:
    """Semantic gains, distinct from interchangeable f8 index metadata."""

    gains: tuple[tuple[int, int], ...] = DEFAULT_GAINS
    format: str = PROFILE

    def __post_init__(self):
        if type(self.format) is not str or self.format != PROFILE:
            raise ValueError("Unsupported Hadamard routing format")
        if type(self.gains) is not tuple or len(self.gains) != 4:
            raise ValueError("Hadamard gains require an immutable four-bank table")
        for bank in self.gains:
            if type(bank) is not tuple or len(bank) != 2:
                raise ValueError("Each Hadamard gain bank requires two immutable lanes")
            for gain in bank:
                _integer(gain, -4, 4, "Hadamard gain")

    def to_dict(self) -> dict:
        return {"format": self.format, "gains": [list(bank) for bank in self.gains]}

    @classmethod
    def from_dict(cls, value: object) -> HadamardBinding:
        _keys(value, {"format", "gains"}, "Hadamard binding")
        gains = value["gains"]
        if type(gains) is not list or any(type(bank) is not list for bank in gains):
            raise ValueError("Hadamard gains require a JSON array of arrays")
        return cls(tuple(tuple(bank) for bank in gains), value["format"])


def _inputs(recipe, binding):
    # FieldWorld imports routing; importing its recipe here avoids a cycle.
    from .field_world import KleinFieldRecipe
    if type(recipe) is not KleinFieldRecipe:
        raise ValueError("recipe must be a KleinFieldRecipe")
    if type(binding) is not HadamardBinding:
        raise ValueError("binding must be a HadamardBinding")


def _table(value, count, upper, label):
    if type(value) not in (tuple, list) or len(value) != count:
        raise ValueError(f"{label} requires exactly {count} integer entries")
    result = tuple(value)
    for item in result:
        _integer(item, 0, upper, label)
    return result


def _fields(recipe, value):
    if type(value) not in (tuple, list):
        raise ValueError("Routing fields require a tuple or list")
    fields = tuple(value)
    certify_field(recipe.field_manifest(), fields)
    return fields


def _compile_model(recipe, binding, fields):
    """CPU construction; independent admission below does not call this."""
    from .psi import field_axes
    domain = recipe.domain()
    axes = field_axes(domain, fields)
    penalties, increments = [], []
    for source, axis in enumerate(axes):
        geometric = sorted((domain.step(source, name)[0], direction)
                           for name, direction in _DIRECTIONS)
        pu, pv = axis.vector
        gu, gv = axis.gradient
        for au, av in binding.gains:
            qu = au * (1 + pu * pu) * gu
            qv = av * (1 + pv * pv) * gv
            maximum = max(abs(qu), abs(qv))
            penalties.extend(maximum - qu * eu - qv * ev
                             for _, (eu, ev) in geometric)
        column = 0 if fields[source] < 0 else 1 if fields[source] == 0 else 2
        increments.append(recipe.turns[column])
    return tuple(penalties), tuple(increments)


def _certify_model(recipe, binding, penalties, increments, fields):
    """Derive expected lanes and edges without CPU compiler/Psi helpers.

    The quotient reduction is written directly so this certificate also
    checks the compiler's directional-neighbor construction independently.
    The primitive axis is recovered from the exact signed field stencil;
    its arbitrary overall sign disappears in the squared gain components.
    """
    width, height = recipe.width, recipe.height

    def canonical(u, v):
        crossings, column = divmod(u, width)
        return column * height + ((-v if crossings % 2 else v) % height)

    neighbors = []
    for source in range(width * height):
        u, v = divmod(source, height)
        directional = ((canonical(u + 1, v), (1, 0)),
                       (canonical(u - 1, v), (-1, 0)),
                       (canonical(u, v + 1), (0, 1)),
                       (canonical(u, v - 1), (0, -1)))
        geometric = sorted(directional)
        neighbors.append(tuple(target for target, _ in geometric))
        gu = fields[directional[0][0]] - fields[directional[1][0]]
        gv = fields[directional[2][0]] - fields[directional[3][0]]
        _integer(gu, -2, 2, "certified routing gradient u")
        _integer(gv, -2, 2, "certified routing gradient v")
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        for bank, (au, av) in enumerate(binding.gains):
            qu, qv = au * (1 + pu ** 2) * gu, av * (1 + pv ** 2) * gv
            maximum = max(abs(qu), abs(qv))
            for slot, (_, (eu, ev)) in enumerate(geometric):
                expected = maximum - (qu * eu + qv * ev)
                if penalties[16 * source + 4 * bank + slot] != expected:
                    raise ValueError("Routing penalty disagrees with the certified field and gains")
        expected_increment = recipe.turns[(fields[source] > 0) - (fields[source] < 0) + 1]
        if increments[source] != expected_increment:
            raise ValueError("Routing increment disagrees with the departure field class")
    return tuple(neighbors)


@dataclass(frozen=True, slots=True, init=False)
class RoutingModel:
    """One immutable admitted HP table in canonical geometric node order."""

    recipe: KleinFieldRecipe
    binding: HadamardBinding
    neighbors: tuple[tuple[int, int, int, int], ...]
    penalties: tuple[int, ...]
    increments: tuple[int, ...]

    def __init__(self, *args, **kwargs):
        raise ValueError("Use RoutingModel.build or RoutingModel.certified")

    @classmethod
    def build(cls, recipe: KleinFieldRecipe, binding: HadamardBinding,
              fields=None) -> RoutingModel:
        _inputs(recipe, binding)
        if fields is None:
            fields = evaluate_field(recipe.field_manifest())
        fields = _fields(recipe, fields)
        penalties, increments = _compile_model(recipe, binding, fields)
        return cls.certified(recipe, binding, penalties, increments, fields)

    @classmethod
    def certified(cls, recipe: KleinFieldRecipe, binding: HadamardBinding,
                  penalties, increments, fields) -> RoutingModel:
        _inputs(recipe, binding)
        count = recipe.width * recipe.height
        penalties = _table(penalties, 16 * count, 80, "Routing penalties")
        increments = _table(increments, count, 255, "Routing increments")
        fields = _fields(recipe, fields)
        neighbors = _certify_model(recipe, binding, penalties, increments, fields)
        model = object.__new__(cls)
        for name, value in (("recipe", recipe), ("binding", binding),
                            ("neighbors", neighbors), ("penalties", penalties),
                            ("increments", increments)):
            object.__setattr__(model, name, value)
        return model

    def penalty(self, source: int, t: int, destination: int) -> int:
        _integer(source, 0, len(self.neighbors) - 1, "Routing source")
        _integer(t, 0, 255, "Intrinsic routing phase")
        _integer(destination, 0, len(self.neighbors) - 1, "Routing destination")
        try:
            slot = self.neighbors[source].index(destination)
        except ValueError as exc:
            raise ValueError("Routing requires a geometric quotient edge") from exc
        return self.penalties[16 * source + 4 * (t // 64) + slot]

    def next_phase(self, source: int, t: int) -> int:
        _integer(source, 0, len(self.neighbors) - 1, "Routing source")
        _integer(t, 0, 255, "Intrinsic routing phase")
        return (t + self.increments[source]) % 256
