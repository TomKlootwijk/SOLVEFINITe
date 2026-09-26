"""Recipe-derived Klein SDF nodes and their disposable FIFO working set.

The agent's B lane is always a certified scalar distance. Energy belongs to
the owning agent, outside these pairs. CPU derivation reconstructs distances
on demand; only active node pairs are cached. Immutable expanded geometry and
GPU scalar/operator storage are separate from that bounded pair cache. The
eviction ledger is diagnostic history and is not capacity bounded.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import wraps
from threading import RLock

from .field import FieldManifest, evaluate_field
from .f8 import F8Index, IndexBinding
from .hadamard import HadamardBinding, RoutingModel
from .klein import KleinDomain
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _keys
from .world import _capacity


WORLD_VERSION = "klein-ball-world-v1"
_RECIPE_KEYS = {"format", "width", "height", "center", "radius", "turns", "baseline_id"}


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._operation:
            return method(self, *args, **kwargs)
    return call


@dataclass(frozen=True, slots=True)
class KleinFieldRecipe:
    """Complete immutable inputs for a finite Klein intrinsic-ball field."""

    width: int = 4
    height: int = 5
    center: int = 0
    radius: int = 2
    turns: tuple[int, int, int] = (11, 53, 137)
    baseline_id: str = "klein-field-world-v1"
    version: str = WORLD_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not str or self.version != WORLD_VERSION:
            raise ValueError("Unsupported field-world recipe format")
        if type(self.baseline_id) is not str or not self.baseline_id.strip():
            raise ValueError("baseline_id must be a nonempty string")
        if type(self.turns) is not tuple or len(self.turns) != 3:
            raise ValueError("turns must be an immutable triple")
        for turn in self.turns:
            _integer(turn, 0, 255, "turn")
        # The generated quotient enforces strict W,H and the 256-node bound;
        # the boundary generator enforces center and intrinsic radius bounds.
        self.domain().ball_signs(self.center, self.radius)

    def domain(self) -> KleinDomain:
        return KleinDomain(self.width, self.height)

    def field_manifest(self) -> FieldManifest:
        """Regenerate the exact v2 geometry, ball signs, and class increments."""
        return self.domain().field_manifest(center=self.center, radius=self.radius,
                                            turns=self.turns)

    def graph(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """All quotient adjacencies, with deterministic canonical-name order."""
        domain = self.domain()
        neighbors = {name: [] for name in domain.nodes}
        for source, destination, _ in domain.edges:
            neighbors[domain.nodes[source]].append(domain.nodes[destination])
            neighbors[domain.nodes[destination]].append(domain.nodes[source])
        return tuple((name, tuple(sorted(adjacent)))
                     for name, adjacent in sorted(neighbors.items()))

    def index(self, path: str) -> int:
        """Resolve one canonical name; chart aliases are not node identifiers."""
        if type(path) is not str or len(path) > 128:
            raise ValueError("Field path must be a canonical k:u:v name")
        parts = path.split(":")
        if len(parts) != 3 or parts[0] != "k":
            raise ValueError("Field path must be a canonical k:u:v name")
        try:
            u, v = int(parts[1]), int(parts[2])
        except ValueError as exc:
            raise ValueError("Field path must be a canonical k:u:v name") from exc
        if not (0 <= u < self.width and 0 <= v < self.height) or path != f"k:{u}:{v}":
            raise ValueError("Field path must be a canonical in-range k:u:v name")
        return u * self.height + v

    def to_dict(self) -> dict:
        return {"format": self.version, "width": self.width, "height": self.height,
                "center": self.center, "radius": self.radius, "turns": list(self.turns),
                "baseline_id": self.baseline_id}

    @classmethod
    def from_dict(cls, value: object) -> KleinFieldRecipe:
        _keys(value, _RECIPE_KEYS, "Klein field recipe")
        if type(value["turns"]) is not list:
            raise ValueError("Recipe turns must be a JSON array")
        return cls(width=value["width"], height=value["height"], center=value["center"],
                   radius=value["radius"], turns=tuple(value["turns"]),
                   baseline_id=value["baseline_id"], version=value["format"])


def require_field_recipe(value):
    """Admit only the two versioned recipe types, never arbitrary lookalikes."""
    from .organogram import GeneratedFieldRecipe
    if type(value) not in (KleinFieldRecipe, GeneratedFieldRecipe):
        raise ValueError("recipe must be a registered Klein field recipe")


def field_recipe_from_dict(value):
    from .organogram import GeneratedFieldRecipe
    if type(value) is not dict:
        raise ValueError("Field recipe must be an object")
    if value.get("format") == WORLD_VERSION:
        return KleinFieldRecipe.from_dict(value)
    return GeneratedFieldRecipe.from_dict(value)


def resolve_field_certificate(recipe, fields=None, certificate=None):
    """Validate generated-field provenance without invoking its CPU producer.

    A missing certificate requests CPU reconstruction. Explicit device callers
    provide the certificate made from their actual ordered stage outputs.
    Legacy recipes retain their original manifest and certificate semantics.
    """
    from .organogram import GeneratedFieldRecipe, GeneratedFieldCertificate, regenerate
    require_field_recipe(recipe)
    if type(recipe) is not GeneratedFieldRecipe:
        if certificate is not None:
            raise ValueError("A generated-field certificate requires its generated recipe")
        return None
    if certificate is None:
        certificate = regenerate(recipe)
    if type(certificate) is not GeneratedFieldCertificate or certificate.recipe != recipe:
        raise ValueError("Generated certificate belongs to a different recipe")
    if fields is not None:
        if type(fields) not in (tuple, list) or len(fields) != len(certificate.fields):
            raise ValueError("Generated certificate differs from the supplied field")
        for value in fields:
            _integer(value, -127, 127, "supplied generated field")
        if tuple(fields) != certificate.fields:
            raise ValueError("Generated certificate differs from the supplied field")
    if certificate.manifest != recipe.field_manifest_from_signs(certificate.manifest.signs):
        raise ValueError("Generated manifest differs from its fixed geometry and bindings")
    from .field import certify_field
    certify_field(certificate.manifest, certificate.fields)
    return certificate


@dataclass(frozen=True, slots=True)
class FieldNode:
    """A canonical node and its atomic DATA pair; no embedding is implied."""

    path: str
    pair: int


class FieldWorld:
    """Pure field reconstruction plus FIFO storage of materialized node pairs.

    A supplied executor is borrowed from the owning agent. It must implement
    the same recipe and provide GPU derivation and hypothetical forecasting;
    this world neither closes it nor changes its canonical live state.
    """

    def __init__(self, recipe: KleinFieldRecipe, capacity: int, executor=None, *,
                 index_binding: IndexBinding | None = None,
                 routing: HadamardBinding | None = None, certificate=None):
        require_field_recipe(recipe)
        capacity = _capacity(capacity)
        if index_binding is not None and type(index_binding) is not IndexBinding:
            raise ValueError("index_binding must be an IndexBinding")
        if routing is not None and type(routing) is not HadamardBinding:
            raise ValueError("routing must be a HadamardBinding")
        if executor is not None and (
                getattr(executor, "recipe", None) != recipe
                or not callable(getattr(executor, "derive_node", None))
                or not callable(getattr(executor, "forecast", None))
                or type(getattr(executor, "index", None)) is not F8Index
                or executor.index.recipe != recipe
                or (index_binding is not None and executor.index.binding != index_binding)):
            raise ValueError("Executor must derive and forecast the same field recipe")
        if executor is not None:
            model = getattr(executor, "routing_model", None)
            if ((routing is None and model is not None) or
                    (routing is not None and (type(model) is not RoutingModel or
                     model.recipe != recipe or model.binding != routing))):
                raise ValueError("Executor must implement the same routing binding")
        self._operation = RLock()
        self._config = recipe
        self._capacity = capacity
        self._executor = executor
        supplied = certificate if executor is None else getattr(executor, "certificate", None)
        if executor is not None and certificate is not None and certificate != supplied:
            raise ValueError("Field world and device certificates differ")
        if executor is not None and type(recipe) is not KleinFieldRecipe and supplied is None:
            raise ValueError("Generated device execution requires its field certificate")
        certificate = resolve_field_certificate(
            recipe, None if executor is None else executor.fields, supplied)
        self._manifest = certificate.manifest if certificate is not None else recipe.field_manifest()
        options = ({"fields": certificate.fields, "certificate": certificate}
                   if certificate is not None else {})
        self._index = F8Index.build(recipe, index_binding, **options) if executor is None else None
        self._routing_model = (RoutingModel.build(recipe, routing, **options)
                               if executor is None and routing is not None else None)
        self._peak_index_payload = 64 * len(self._manifest.nodes) + 16
        neighbors = [set() for _ in self._manifest.nodes]
        for source, destination, _ in self._manifest.edges:
            neighbors[source].add(destination)
            neighbors[destination].add(source)
        self._neighbors = tuple(frozenset(adjacent) for adjacent in neighbors)
        self._active: OrderedDict[str, FieldNode] = OrderedDict()
        self._evicted: list[str] = []
        self._hits = 0
        self._regenerations = 0

    @property
    def config(self) -> KleinFieldRecipe:
        return self._config

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def active_paths(self) -> tuple[str, ...]:
        return tuple(self._active)

    @property
    def evicted_paths(self) -> tuple[str, ...]:
        return tuple(self._evicted)

    @property
    def hit_count(self) -> int:
        return self._hits

    @property
    def regeneration_count(self) -> int:
        return self._regenerations

    @property
    def index(self) -> F8Index:
        """One immutable version; GPU worlds borrow the owner's current bundle."""
        return self._index if self._executor is None else self._executor.index

    @property
    def routing_model(self) -> RoutingModel | None:
        return (self._routing_model if self._executor is None else
                getattr(self._executor, "routing_model", None))

    @property
    def routing_info(self) -> dict | None:
        model = self.routing_model
        if model is None:
            return None
        count = len(self._manifest.nodes)
        return {"binding": model.binding.to_dict(), "phase_source": "live intrinsic phase",
                "host_routing_table_payload_bytes": 68 * count,
                "host_routing_geometry_payload_bytes": 16 * count,
                "peak_rebuild_host_routing_table_payload_bytes": (
                    68 * count if self._executor is None else self._executor.allocation_info[
                        "peak_rebuild_host_routing_payload_bytes"]),
                "gains_payload_bytes": 32,
                "retained_cpu_scalar_field_count": 0,
                "accounting": "Logical 16N penalties and N increments, plus eight gains. "
                              "Geometry, search labels/routes, weights, Python objects and "
                              "GPU field/table copies are separate."}

    @property
    def index_info(self) -> dict:
        index = self.index
        count = len(index.records)
        return {"version": {"recipe": self.config.to_dict(), "binding": index.binding.to_dict()},
                "descriptor_count": count, "maximum_lookup_visits": count.bit_length(),
                "host_record_payload_bytes": 32 * count,
                "host_tree_payload_bytes": 32 * count,
                "host_binding_payload_bytes": 16,
                "host_index_payload_bytes": 64 * count + 16,
                "peak_rebuild_host_index_payload_bytes": (
                    self._peak_index_payload if self._executor is None else
                    self._executor.allocation_info["peak_rebuild_host_index_payload_bytes"]),
                "retained_world_node_pair_count": 0,
                "accounting": "Logical u32 record/tree payload outside the sample FIFO. "
                              "Peak counts complete old and candidate index bundles. "
                              "Recipe, expanded geometry, temporary compiler work, Python objects "
                              "and device copies are additional; "
                              "CPU index stores no scalar field tuple or complete sample pairs."}

    @_serialized
    def reindex(self, *, psi_sign: int | None = None,
                phase_origin: int | None = None) -> F8Index:
        """Install a certified new storage version without changing working state."""
        if self._executor is not None:
            return self._executor.reindex(psi_sign=psi_sign, phase_origin=phase_origin)
        candidate = self.index.rebuild(psi_sign=psi_sign, phase_origin=phase_origin)
        self._peak_index_payload = max(self._peak_index_payload,
                                       64 * (len(self.index.records) + len(candidate.records)) + 32)
        self._index = candidate
        return candidate

    @_serialized
    def derive(self, path: str) -> FieldNode:
        """Reconstruct a DATA pair without reading or changing the FIFO cache."""
        requested = self.config.index(path)
        version = self.index
        row = version.resolve(requested)
        index = version.rows[row][4]
        if index != requested:
            raise ValueError("Index lookup changed the requested geometric identity")
        if self._executor is None:
            # No field tuple or packed copy survives this call outside the
            # returned node. A later miss genuinely regenerates its scalar.
            signed = evaluate_field(self._manifest)[index]
            value = pair(pack(0, index, signed, Opcode.DATA))
        else:
            value = self._executor.derive_node(index)
            r, g, b, metadata = unpack(unpair(value)[0])
            if (r, g, b, metadata) != (0, index, self._executor.fields[index], int(Opcode.DATA)):
                raise ValueError("GPU derivation disagrees with the certified field node")
        return FieldNode(path, value)

    @_serialized
    def get(self, path: str) -> FieldNode:
        self.config.index(path)
        if path in self._active:
            self._hits += 1
            return self._active[path]
        node = self.derive(path)
        if path in self._evicted:
            self._regenerations += 1
        self._active[path] = node
        self._evict_overflow()
        return node

    @_serialized
    def resize(self, capacity: int) -> None:
        self._capacity = _capacity(capacity)
        self._evict_overflow()

    @_serialized
    def invalidate(self, paths: list[str]) -> list[str]:
        """Discard an admitted active selector atomically, in original FIFO order.

        Only complete cached DATA pairs are removed. Their recipes and index
        remain available for later reconstruction; removal itself is neither
        a cache hit nor a regeneration.
        """
        if type(paths) is not list or not 1 <= len(paths) <= 256:
            raise ValueError("Invalidation paths must be a list of 1..256 active paths")
        for path in paths:
            self.config.index(path)
        if paths != sorted(set(paths)):
            raise ValueError("Invalidation paths must be sorted and unique")
        if any(path not in self._active for path in paths):
            raise ValueError("Every invalidation path must be currently active")
        selected = set(paths)
        removed = [path for path in self._active if path in selected]
        for path in removed:
            del self._active[path]
        self._evicted.extend(removed)
        return removed

    def _evict_overflow(self) -> None:
        while len(self._active) > self.capacity:
            path, _ = self._active.popitem(last=False)
            self._evicted.append(path)

    @_serialized
    def entry_cost(self, path: str, hazard: int) -> int:
        """Declared resource cost, separate from unit intrinsic edge length."""
        _integer(hazard, 0, 127, "hazard")
        signed = unpack(unpair(self.derive(path).pair)[0])[2]
        return 1 + abs(signed) + hazard

    @_serialized
    def forecast(self, agent_pair: int, route: tuple[str, ...],
                 hazards: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Predict adjacent SDF transitions without spending energy or caching.

        Every destination belongs to a route chosen by the owning planner.
        Phase increments use the departure field class; seam transport follows
        K8 and replaces B with the certified destination scalar. Energy
        feasibility is the owner's separate responsibility.
        """
        if type(route) is not tuple or not 0 <= len(route) <= 255:
            raise ValueError("Forecast route must be an immutable tuple of at most 255 nodes")
        if type(hazards) is not tuple or len(hazards) != len(route):
            raise ValueError("Forecast hazards must be one immutable value per route node")
        for hazard in hazards:
            _integer(hazard, 0, 127, "hazard")
        _integer(agent_pair, 0, (1 << 64) - 1, "agent_pair")
        r, source, signed, metadata = unpack(unpair(agent_pair)[0])
        if source >= len(self._manifest.nodes):
            raise ValueError("Agent state names an unknown field node")
        if metadata not in (int(Opcode.STEP), int(Opcode.STEP) | 16):
            raise ValueError("SDF agent state requires STEP and only optional orientation")
        version = self.index
        version.resolve(source)
        indices = tuple(version.rows[version.resolve(self.config.index(path))][4]
                        for path in route)
        previous = source
        for destination in indices:
            if destination not in self._neighbors[previous]:
                raise ValueError("Every forecast hop must follow a declared quotient edge")
            previous = destination
        if self._executor is not None:
            if signed != self._executor.fields[source]:
                raise ValueError("Agent B disagrees with its certified scalar field")
            return self._executor.forecast(agent_pair, route, hazards)

        # One ephemeral exact field is sufficient for this entire hypothetical
        # route. It is not retained as a CPU scalar or packed-node arena.
        fields = evaluate_field(self._manifest)
        if signed != fields[source]:
            raise ValueError("Agent B disagrees with its certified scalar field")
        eta = (metadata >> 4) & 1
        outputs, costs = [], []
        for destination, hazard in zip(indices, hazards):
            phase = (-r if eta else r) & 255
            penalty = (0 if self.routing_model is None else
                       self.routing_model.penalty(source, phase, destination))
            column = 0 if fields[source] < 0 else 1 if fields[source] == 0 else 2
            delta = self._manifest.turns[source][column]
            tau = self._manifest.seam(source, destination)
            r = (r + (-1 if eta else 1) * delta) % 256
            r = (-r if tau else r) % 256
            eta ^= tau
            outputs.append(pair(pack(r, destination, fields[destination],
                                     int(Opcode.STEP) | (eta << 4))))
            costs.append(1 + abs(fields[destination]) + hazard + penalty)
            source = destination
        return tuple(outputs), tuple(costs)
