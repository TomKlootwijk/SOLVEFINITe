"""GD1, GD2, GD4 and GD7: finite dyadic geometry and qualified samples.

Growth changes the intrinsic quotient, field and planning context. It is
separate from an interchangeable storage index. These pure helpers neither
admit an event nor advance an agent; the owner serializes that transition.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .field import certify_field
from .field_world import KleinFieldRecipe
from .rp32 import Opcode, unpack, unpair
from .runtime import _integer, _keys


PROFILE = "klein-dyadic-growth-v1"


def _recipe(value: object) -> None:
    if type(value) is not KleinFieldRecipe:
        raise ValueError("recipe must be a KleinFieldRecipe")


@dataclass(frozen=True, slots=True)
class GrowthBinding:
    """Immutable semantic grammar and its finite mission obligations."""

    max_epochs: int = 1
    cost: int = 1
    format: str = PROFILE

    def __post_init__(self) -> None:
        if type(self.format) is not str or self.format != PROFILE:
            raise ValueError("Unsupported growth format")
        _integer(self.max_epochs, 0, 2, "max_epochs")
        _integer(self.cost, 1, 127, "growth cost")

    def validate_recipe(self, recipe: KleinFieldRecipe) -> None:
        """Reject an impossible full mission before allocating a candidate."""
        validate_growth_budget(recipe, self)

    def to_dict(self) -> dict:
        return {"format": self.format, "max_epochs": self.max_epochs, "cost": self.cost}

    @classmethod
    def from_dict(cls, value: object) -> GrowthBinding:
        _keys(value, {"format", "max_epochs", "cost"}, "Growth binding")
        return cls(value["max_epochs"], value["cost"], value["format"])


def validate_growth_budget(recipe: KleinFieldRecipe, binding: GrowthBinding) -> None:
    """Check the complete declared depth using integers and no graph allocation."""
    _recipe(recipe)
    if type(binding) is not GrowthBinding:
        raise ValueError("growth must be a GrowthBinding")
    if recipe.width * recipe.height * (4 ** binding.max_epochs) > 256:
        raise ValueError("Initial node count times 4**max_epochs must not exceed 256")


def map_node(recipe: KleinFieldRecipe, node: int) -> int:
    """Embed an old canonical vertex into one dyadic generation.

    There is no rounding projection for new odd-coordinate vertices. Such a
    projection would not commute with the quotient's reversing seam.
    """
    _recipe(recipe)
    count = recipe.width * recipe.height
    _integer(node, 0, count - 1, "node")
    if count * 4 > 256:
        raise ValueError("A dyadic generation must contain at most 256 nodes")
    u, v = divmod(node, recipe.height)
    return (2 * u) * (2 * recipe.height) + 2 * v


def grow_recipe(recipe: KleinFieldRecipe) -> KleinFieldRecipe:
    """Produce one larger unit-edge quotient, preserving the retained grammar."""
    _recipe(recipe)
    center = map_node(recipe, recipe.center)
    return KleinFieldRecipe(
        width=2 * recipe.width, height=2 * recipe.height,
        center=center, radius=2 * recipe.radius, turns=recipe.turns,
        baseline_id=recipe.baseline_id, version=recipe.version,
    )


def recipe_at_epoch(initial_recipe: KleinFieldRecipe, growth: GrowthBinding,
                    geometry_epoch: int) -> KleinFieldRecipe:
    """Derive a configured generation; the agent separately checks admission.

    This helper cannot decide whether a historical GROW event was admitted.
    Callers exposing history must enforce their retained event-prefix bound.
    """
    validate_growth_budget(initial_recipe, growth)
    _integer(geometry_epoch, 0, growth.max_epochs, "geometry_epoch")
    result = initial_recipe
    for _ in range(geometry_epoch):
        result = grow_recipe(result)
    return result


def select_target(recipe: KleinFieldRecipe, certified_fields: tuple[int, ...],
                  mapped_node: int, intrinsic_phase: int) -> int:
    """Select GD4's generated near-boundary, farthest-hop target.

    Admit the supplied field independently, without invoking a CPU field or
    operator compiler. This allows a GPU-produced field to remain the actual
    source. Numeric G order resolves the final phase-selected tie.
    """
    _recipe(recipe)
    count = recipe.width * recipe.height
    _integer(mapped_node, 0, count - 1, "mapped_node")
    _integer(intrinsic_phase, 0, 255, "intrinsic_phase")
    if type(certified_fields) is not tuple or len(certified_fields) != count:
        raise ValueError("certified_fields must be an immutable tuple with one entry per node")
    # GD4 is defined on a produced dyadic quotient and the embedded current
    # vertex. Reject applying its odd-coordinate test to an unrelated chart.
    if recipe.width % 2 or recipe.height % 2 or min(recipe.width, recipe.height) < 6:
        raise ValueError("Target selection requires a dyadically produced Klein quotient")
    u, v = divmod(mapped_node, recipe.height)
    if u % 2 or v % 2:
        raise ValueError("mapped_node must be the even-coordinate image of an old vertex")
    certify_field(recipe.field_manifest(), certified_fields)
    domain = recipe.domain()
    neighbors = [[] for _ in domain.nodes]
    for source, destination, _ in domain.edges:
        neighbors[source].append(destination)
        neighbors[destination].append(source)
    distances = [-1] * count
    distances[mapped_node] = 0
    pending = deque((mapped_node,))
    while pending:
        source = pending.popleft()
        for destination in neighbors[source]:
            if distances[destination] == -1:
                distances[destination] = distances[source] + 1
                pending.append(destination)
    generated = tuple(index for index in range(count)
                      if any(coordinate % 2 for coordinate in divmod(index, recipe.height)))
    minimum = min(abs(certified_fields[index]) for index in generated)
    near = tuple(index for index in generated if abs(certified_fields[index]) == minimum)
    maximum = max(distances[index] for index in near)
    tied = tuple(index for index in near if distances[index] == maximum)
    return tied[intrinsic_phase % len(tied)]


@dataclass(frozen=True, slots=True)
class EpochFieldNode:
    """A DATA sample with its original semantic generation and derivation.

    The owner supplies a certified field pair and hashes the complete original
    admission prefix. This value validates the context, digest shape and packed identity;
    it stores neither a field arena nor a current-world cache reference.
    """

    geometry_epoch: int
    origin_sequence: int
    initial_recipe: KleinFieldRecipe
    growth: GrowthBinding
    path: str
    pair: int
    prefix_sha256: str

    def __post_init__(self) -> None:
        if (type(self.prefix_sha256) is not str or len(self.prefix_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.prefix_sha256)):
            raise ValueError("prefix_sha256 must contain exactly 64 lowercase hexadecimal digits")
        recipe = recipe_at_epoch(self.initial_recipe, self.growth, self.geometry_epoch)
        _integer(self.origin_sequence, 0, 1_000_000, "origin_sequence")
        if (self.geometry_epoch == 0) != (self.origin_sequence == 0):
            raise ValueError("Only the initial generation has origin_sequence zero")
        index = recipe.index(self.path)
        _integer(self.pair, 0, (1 << 64) - 1, "pair")
        phase, node, _field, metadata = unpack(unpair(self.pair)[0])
        if (phase, node, metadata) != (0, index, int(Opcode.DATA)):
            raise ValueError("Historical sample requires a canonical DATA pair for its path")

    def to_dict(self) -> dict:
        return {"geometry_epoch": self.geometry_epoch, "origin_sequence": self.origin_sequence,
                "initial_recipe": self.initial_recipe.to_dict(), "growth": self.growth.to_dict(),
                "path": self.path, "pair": f"{self.pair:016X}", "prefix_sha256": self.prefix_sha256}
