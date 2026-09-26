"""One persistent observer with an autonomous, replayable decision loop.

TOMIGIDt is one individual and its internally represented world, following
the author's clarification. Movement and repair remain a declared application
profile of the underlying packed-state paradigm.
"""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
from threading import RLock
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

from .motion import move, movement_cost
from .navigation import NoRoute, RouteSearch, SearchBudgetExceeded, normalize_graph, shortest_route
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _json, _keys, write_json
from .world import World, WorldConfig, _capacity
from .field_agent import (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY,
                          FIELD_WORD_PROFILE, FieldAgentManifest)
from .growth import EpochFieldNode, grow_recipe, map_node, select_target
from .hadamard_navigation import HadamardRouteSearch
from .field_world import FieldWorld, KleinFieldRecipe
from .hadamard import HadamardBinding
from .f8 import F8Index, IndexBinding
from .organogram import (OrganogramBinding, StageContext, GeneratedFieldRecipe,
                         regenerate, select_target as select_organogram_target)


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._operation:
            return method(self, *args, **kwargs)
    return call


FORMAT = "tomigidt-agent-v1"
LEGACY_POLICY = "tomigidt-observe-plan-act-v1"
POLICY = "tomigidt-observe-plan-act-v2"
PERSPECTIVE = "local-observation-v1"
DEFAULT_GRAPH = (
    ("", ("0", "1")), ("0", ("", "00")), ("00", ("0", "11")),
    ("1", ("", "10")), ("10", ("1", "11")), ("11", ("00", "10")),
)


class CommittedGrowthCleanupError(RuntimeError):
    """The new epoch and event were admitted, but retiring its predecessor failed."""

    committed = True


@dataclass(frozen=True, slots=True)
class OrganogramFieldNode:
    """An admitted historical DATA sample with its complete original grammar."""

    geometry_epoch: int
    origin_sequence: int
    initial_recipe: KleinFieldRecipe
    organogram: OrganogramBinding
    routing: HadamardBinding
    stages: tuple[StageContext, ...]
    path: str
    pair: int
    prefix_sha256: str

    def __post_init__(self):
        if (type(self.initial_recipe) is not KleinFieldRecipe or
                type(self.organogram) is not OrganogramBinding or type(self.routing) is not HadamardBinding):
            raise ValueError("Historical grammar sample requires its exact immutable bindings")
        _integer(self.geometry_epoch, 0, self.organogram.max_epochs, "geometry_epoch")
        _integer(self.origin_sequence, 0, 1_000_000, "origin_sequence")
        if ((self.geometry_epoch == 0) != (self.origin_sequence == 0) or
                type(self.stages) is not tuple or len(self.stages) != self.geometry_epoch):
            raise ValueError("Historical grammar sample has an inconsistent original generation")
        if self.stages:
            GeneratedFieldRecipe(self.initial_recipe, self.organogram, self.routing, self.stages)
            if self.stages[-1].tick != self.origin_sequence:
                raise ValueError("Historical grammar sample has a different original tick")
        if (type(self.prefix_sha256) is not str or len(self.prefix_sha256) != 64 or
                any(c not in '0123456789abcdef' for c in self.prefix_sha256)):
            raise ValueError("Historical sample requires a lowercase original-prefix SHA256")
        _integer(self.pair, 0, (1 << 64) - 1, "pair")
        r, node, _, metadata = unpack(unpair(self.pair)[0])
        if (r, node, metadata) != (0, self.initial_recipe.index(self.path), int(Opcode.DATA)):
            raise ValueError("Historical sample requires a canonical DATA pair for its path")

    def to_dict(self):
        return {"geometry_epoch": self.geometry_epoch, "origin_sequence": self.origin_sequence,
                "initial_recipe": self.initial_recipe.to_dict(), "organogram": self.organogram.to_dict(),
                "routing": self.routing.to_dict(), "stages": [stage.to_dict() for stage in self.stages],
                "path": self.path, "pair": f"{self.pair:016X}", "prefix_sha256": self.prefix_sha256}


@dataclass(frozen=True)
class AgentManifest:
    identity: str = "TOMIGIDt"
    target: str = "11"
    world: WorldConfig = field(default_factory=WorldConfig)
    agent_seed: tuple[int, int, int, int] = (250, 3, 100, 1)
    repair_cost: int = 5
    graph: tuple[tuple[str, tuple[str, ...]], ...] = DEFAULT_GRAPH
    max_search_expansions: int = 4096
    max_cycles: int = 10_000
    policy: str = POLICY

    def __post_init__(self) -> None:
        if type(self.policy) is not str or self.policy not in (LEGACY_POLICY, POLICY):
            raise ValueError("Unsupported agent policy")
        if type(self.identity) is not str or not self.identity.strip() or len(self.identity) > 128:
            raise ValueError("identity must be a nonempty name of at most 128 characters")
        if type(self.world) is not WorldConfig:
            raise ValueError("world must be a WorldConfig")
        if type(self.agent_seed) is not tuple or len(self.agent_seed) != 4:
            raise ValueError("agent_seed must be four immutable RP32 fields")
        pack(*self.agent_seed)
        if self.agent_seed[2] < 0 or self.agent_seed[3] & 7 != Opcode.STEP:
            raise ValueError("Agent seed requires nonnegative energy and STEP opcode")
        _integer(self.repair_cost, 1, 127, "repair_cost")
        _integer(self.max_search_expansions, 1, 65536, "max_search_expansions")
        _integer(self.max_cycles, 1, 1_000_000, "max_cycles")
        if type(self.graph) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or type(item[1]) is not tuple
            for item in self.graph
        ):
            raise ValueError("graph must be an immutable tuple of node/neighbor tuples")
        if any(type(item[0]) is not str for item in self.graph):
            raise ValueError("graph node names must be strings")
        graph = normalize_graph(dict(self.graph))
        if len(graph) != len(self.graph):
            raise ValueError("graph contains duplicate node definitions")
        if "" not in graph or type(self.target) is not str or self.target not in graph:
            raise ValueError("graph must contain the root start and declared target")
        world = World(self.world, 1)
        for path in graph:
            world.derive(path)
        object.__setattr__(self, "graph", tuple(graph.items()))

    def to_dict(self) -> dict:
        return {
            "identity": self.identity, "policy": self.policy, "perspective": PERSPECTIVE,
            "word_profile": "RP32-v1", "target": self.target,
            "world": self.world.to_dict(), "agent_seed": list(self.agent_seed),
            "repair_cost": self.repair_cost,
            "graph": {node: list(neighbors) for node, neighbors in self.graph},
            "max_search_expansions": self.max_search_expansions,
            "max_cycles": self.max_cycles,
        }

    @property
    def start(self) -> str:
        return ""

    @classmethod
    def from_dict(cls, value: object) -> AgentManifest | FieldAgentManifest:
        if type(value) is dict and value.get("policy") in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            return FieldAgentManifest.from_dict(value)
        _keys(value, {
            "identity", "policy", "perspective", "word_profile", "target", "world",
            "agent_seed", "repair_cost", "graph", "max_search_expansions", "max_cycles",
        }, "Agent manifest")
        if (value["policy"] not in (LEGACY_POLICY, POLICY) or value["perspective"] != PERSPECTIVE
                or value["word_profile"] != "RP32-v1"):
            raise ValueError("Unsupported agent policy, perspective or word profile")
        if type(value["agent_seed"]) is not list or type(value["graph"]) is not dict:
            raise ValueError("Agent seed and graph must have their declared JSON shapes")
        if any(type(neighbors) is not list for neighbors in value["graph"].values()):
            raise ValueError("Graph neighbor lists must be JSON arrays")
        return cls(
            identity=value["identity"], target=value["target"],
            world=WorldConfig.from_dict(value["world"]), agent_seed=tuple(value["agent_seed"]),
            repair_cost=value["repair_cost"],
            graph=tuple((node, tuple(neighbors)) for node, neighbors in value["graph"].items()),
            max_search_expansions=value["max_search_expansions"], max_cycles=value["max_cycles"],
            policy=value["policy"],
        )


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    route: tuple[str, ...] = ()
    cost: int = 0
    expected_pair: int | None = None
    expansions: int = 0
    forecast: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "reason": self.reason, "route": list(self.route),
            "cost": self.cost,
            "expected_pair": None if self.expected_pair is None else f"{self.expected_pair:016X}",
            "expansions": self.expansions,
            "forecast": [f"{value:016X}" for value in self.forecast],
        }


@dataclass(frozen=True)
class _Planning:
    position: str
    agent_pair: int
    weights: tuple[tuple[str, int], ...]
    cursor: RouteSearch | HadamardRouteSearch
    energy: int | None = None

    def matches(self, position: str, agent_pair: int, weights: tuple[tuple[str, int], ...],
                energy: int | None = None) -> bool:
        # Target and graph stay fixed while this cursor exists. Growth clears it.
        return (self.position, self.agent_pair, self.weights, self.energy) == (
            position, agent_pair, weights, energy)


class Tomigidt:
    """A single decision maker; the mirrored half is a representation check.

    The agent owns its identity, goal, observations, decisions and packed state.
    Sensors supply observations only. They cannot supply a route or action.
    """

    def __init__(self, manifest: AgentManifest | FieldAgentManifest | None = None,
                 capacity: int = 2, *, backend: str = "cpu",
                 index_binding: IndexBinding | None = None):
        self._operation = RLock()
        self._manifest = AgentManifest() if manifest is None else manifest
        if type(self._manifest) not in (AgentManifest, FieldAgentManifest):
            raise ValueError("manifest must be an AgentManifest or FieldAgentManifest")
        self._is_field = type(self._manifest) is FieldAgentManifest
        self._is_organogram = self._manifest.policy == ORGANOGRAM_POLICY
        self._is_growth = self._manifest.policy in (GROWTH_POLICY, ORGANOGRAM_POLICY)
        self._growth_binding = self._manifest.growth_binding if self._is_growth else None
        self._is_hadamard = self._manifest.policy in (HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY)
        self._geometry_epoch = 0
        self._target = self._manifest.target
        self._growth_peak: dict = {}
        if index_binding is not None and (not self._is_field or type(index_binding) is not IndexBinding):
            raise ValueError("An IndexBinding requires a field-agent manifest")
        self._graph = dict(self._manifest.graph)
        if type(backend) is not str or backend not in ("cpu", "gpu"):
            raise ValueError("backend must be cpu or gpu")
        self._gpu = None
        self._closed = False
        if self._is_field:
            _capacity(capacity)
            try:
                if backend == "gpu":
                    from .field_agent_gpu import GpuFieldAgentExecutor
                    routing_options = {"routing": self._manifest.routing} if self._is_hadamard else {}
                    self._gpu = GpuFieldAgentExecutor(self._manifest.world, index_binding=index_binding,
                                                       **routing_options)
                    self.world = FieldWorld(self._manifest.world, capacity, executor=self._gpu,
                                            index_binding=index_binding, routing=self._manifest.routing)
                else:
                    self.world = FieldWorld(self._manifest.world, capacity, index_binding=index_binding,
                                            routing=self._manifest.routing)
                _, node, signed, _ = unpack(unpair(self.world.derive(self._manifest.start).pair)[0])
                self._pair = pair(pack(self._manifest.initial_phase, node, signed,
                                       int(Opcode.STEP) | (self._manifest.initial_orientation << 4)))
                self._energy = self._manifest.initial_energy
                if self._gpu is not None:
                    self._gpu.seed(self._pair, self._energy)
            except BaseException:
                self.close()
                raise
        else:
            self.world = World(self._manifest.world, capacity)
            self._pair = pair(pack(*self._manifest.agent_seed))
        if backend == "gpu" and not self._is_field:
            from .gpu import GpuExecutor, GpuWorld
            self._gpu = GpuExecutor(self._manifest.world, tuple(self._graph))
            try:
                self.world = GpuWorld(self._manifest.world, capacity, self._gpu)
                self._gpu.commit_pair(self._pair)
            except BaseException:
                self._gpu.close()
                raise
        self._position = self._manifest.start
        self._cycle = 0
        self._status = "ACTIVE"
        self._observations: dict[str, int] = {}
        self._last_decision: Decision | None = None
        self._planning: _Planning | None = None
        self._events: list[dict] = []
        self._closed = False

    @property
    @_serialized
    def execution_info(self) -> dict:
        """Deployment diagnostics; adapter choice does not change journal semantics."""
        if self._is_field:
            result = {"backend": "cpu" if self._gpu is None else "gpu",
                      "word_profile": FIELD_WORD_PROFILE,
                      "index": self.world.index_info,
                      "active_pair_payload_capacity_bytes": 8 * self.world.capacity,
                      "accounting": "Active pair payload only; recipe, geometry, search, observations, "
                                    "journal and runtime overhead are separate."}
            if self._gpu is not None:
                result.update(adapter=dict(self._gpu.adapter_info),
                              allocation_info=self._gpu.allocation_info,
                              gpu_stages=["certified-field-construction", "psi-key-construction",
                                          "canonical-tree-construction", "tree-lookup", "sample-materialization",
                                          "edge-operator-compilation", "route-forecast", "actual-action"],
                              host_stages=["geometric-certificate", "psi-index-certificate", "observation-admission",
                                           "route-search", "action-admission", "journal"])
            if self._is_hadamard:
                result["routing"] = self.world.routing_info
                result["search_state"] = "canonical node, intrinsic phase, hop count"
                if self._gpu is not None:
                    result["gpu_stages"].extend(["hadamard-atlas-compilation", "routing-table-export"])
                    result["host_stages"].append("independent-routing-certificate")
            if self._is_growth:
                result["growth"] = {"binding": self._growth_binding.to_dict(),
                                    "geometry_epoch": self.geometry_epoch,
                                    "current_recipe": self.current_recipe.to_dict(),
                                    "scale_exponent": self.geometry_epoch,
                                    "peak_preparation_payload": deepcopy(self._growth_peak),
                                    "accounting": "Old and candidate payloads coexist. Expanded topology, "
                                                  "manifests, temporary compiler work, search, observations, "
                                                  "history, Python objects and driver allocations are additional."}
                if self._gpu is not None:
                    result["gpu_stages"].append("organogram-field-admission" if self.is_organogram else "dyadic-growth-mapping")
                    result["host_stages"].extend(["growth-admission", "derived-target-selection"])
                if self.is_organogram:
                    del result["growth"]["scale_exponent"]
                    if self._gpu is not None:
                        result["gpu_stages"].extend(["integer-instruction-texture", "branch-interpreter",
                                                     "generated-ball-signs", "generated-field-distances"])
                        result["host_stages"].extend(["parameterized-parallel-rewrite", "tape-preflight",
                                                      "independent-stage-certificate"])
            return result
        return {"backend": "cpu"} if self._gpu is None else {
            "backend": "gpu", "adapter": dict(self._gpu.adapter_info),
            "gpu_stages": ["packed-world-derivation", "packed-route-forecast"],
            "host_stages": ["observation-admission", "route-search", "action-admission", "journal"],
        }

    @_serialized
    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._gpu is not None:
                self._gpu.close()

    @_serialized
    def emit_welip_state(self, tick16: int) -> tuple[int, list[str]]:
        """Emit this same field owner under W time, including after completion."""
        if self._closed:
            raise ValueError("This agent is closed")
        if not self._is_field:
            raise ValueError("WElip emission requires a field-agent manifest")
        _integer(tick16, 0, 65535, "tick16")
        if self._gpu is None:
            from .welip import encode_state
            return encode_state(self.agent_pair, tick16)
        try:
            with self._gpu._lock:
                if (self._gpu._pair, self._gpu._energy) != (self.agent_pair, self.energy):
                    self._gpu._failed = True
                    raise ValueError("WElip executor differs from its owning individual")
                return self._gpu.emit_welip(tick16)
        except BaseException as exc:
            if (self._gpu.failed or self._gpu._closed
                    or getattr(exc, "device_uncertain", False)):
                self.close()
            raise

    @_serialized
    def resize_welip_cache(self, capacity: int) -> list[str]:
        """Resize only the current field FIFO and report removals in FIFO order."""
        if self._closed:
            raise ValueError("This agent is closed")
        if not self._is_field:
            raise ValueError("WElip cache controls require a field-agent manifest")
        _integer(capacity, 1, 256, "capacity")
        with self.world._operation:
            before = len(self.world.evicted_paths)
            self.world.resize(capacity)
            return list(self.world.evicted_paths[before:])

    @_serialized
    def invalidate_welip_cache(self, paths: list[str]) -> list[str]:
        """Release complete current DATA pairs without changing the individual."""
        if self._closed:
            raise ValueError("This agent is closed")
        if not self._is_field:
            raise ValueError("WElip cache controls require a field-agent manifest")
        return self.world.invalidate(paths)

    @_serialized
    def reindex(self, *, psi_sign: int | None = None,
                phase_origin: int | None = None) -> F8Index:
        """Change only indexed storage; preserve the complete admitted history."""
        if self._closed:
            raise ValueError("This agent is closed")
        if not self._is_field:
            raise ValueError("Reindex requires a field-agent manifest")
        try:
            return self.world.reindex(psi_sign=psi_sign, phase_origin=phase_origin)
        except BaseException:
            if self._gpu is not None and self._gpu.failed:
                self.close()
            raise

    @property
    def manifest(self) -> AgentManifest | FieldAgentManifest:
        return self._manifest

    @property
    def identity(self) -> str:
        return self.manifest.identity

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def is_growth(self) -> bool:
        return self._is_growth

    @property
    def is_organogram(self) -> bool:
        return self._is_organogram

    @property
    def geometry_epoch(self) -> int:
        return self._geometry_epoch

    @property
    def current_recipe(self):
        return self.world.config

    @property
    def target(self) -> str:
        return self._target

    @_serialized
    def recipe_at_epoch(self, epoch: int):
        """Reconstruct an already admitted geometry from its original production prefix."""
        if not self.is_growth:
            raise ValueError("Historical geometry requires the growth policy")
        _integer(epoch, 0, self.geometry_epoch, "geometry_epoch")
        recipe = self.manifest.world
        count = 0
        for index, event in enumerate(self._events):
            if count == epoch:
                break
            if event["growth"] is not None:
                receipt = event["growth"]
                if self.is_organogram:
                    if index == 0:
                        raise ValueError("A grammar stage requires an original repaired state")
                    recipe = self._organogram_recipe(recipe, event["seq"],
                                                      self._events[index - 1]["output"],
                                                      self._events[:index])
                else:
                    recipe = grow_recipe(recipe)
                count += 1
                if (receipt["from_epoch"], receipt["to_epoch"], receipt["recipe"]) != (
                        count - 1, count, recipe.to_dict()):
                    raise ValueError("Retained production disagrees with its original grammar")
        if count != epoch:
            raise ValueError("Geometry epoch has no admitted production prefix")
        return recipe

    def _organogram_recipe(self, previous, tick, start_pair, prefix):
        """Bind the next generation to original inputs without evaluating it."""
        stages = previous.stages if type(previous) is GeneratedFieldRecipe else ()
        fingerprint = hashlib.sha256(json.dumps(
            prefix, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
            allow_nan=False).encode('utf-8')).hexdigest()
        context = StageContext(epoch=len(stages) + 1, tick=tick,
                               start_pair=start_pair, prefix_sha256=fingerprint)
        return GeneratedFieldRecipe(base=self.manifest.world, organogram=self.manifest.organogram,
                                    routing=self.manifest.routing, stages=(*stages, context))

    @_serialized
    def derive_epoch(self, epoch: int, path: str) -> EpochFieldNode | OrganogramFieldNode:
        """Regenerate a qualified sample without changing the live state or FIFO."""
        if self.closed:
            raise ValueError("This agent is closed")
        recipe = self.recipe_at_epoch(epoch)
        recipe.index(path)
        origin = 0 if epoch == 0 else next(
            event["seq"] for event in self._events
            if event["growth"] is not None and event["growth"]["to_epoch"] == epoch)
        prefix_digest = hashlib.sha256(json.dumps(
            self._events[:origin], sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
        owner = None
        try:
            if epoch == self.geometry_epoch:
                sample = self.world.derive(path)
            else:
                if self._gpu is not None:
                    from .field_agent_gpu import GpuFieldAgentExecutor
                    owner = GpuFieldAgentExecutor(recipe, index_binding=self.world.index.binding,
                                                  routing=self.manifest.routing)
                historical = FieldWorld(recipe, 1, executor=owner,
                                        index_binding=self.world.index.binding, routing=self.manifest.routing)
                sample = historical.derive(path)
            if self.is_organogram:
                return OrganogramFieldNode(
                    geometry_epoch=epoch, origin_sequence=origin, initial_recipe=self.manifest.world,
                    organogram=self.manifest.organogram, routing=self.manifest.routing,
                    stages=recipe.stages if type(recipe) is GeneratedFieldRecipe else (),
                    prefix_sha256=prefix_digest, path=path, pair=sample.pair)
            return EpochFieldNode(geometry_epoch=epoch, origin_sequence=origin,
                                  initial_recipe=self.manifest.world, growth=self.manifest.growth,
                                  prefix_sha256=prefix_digest, path=path, pair=sample.pair)
        except BaseException:
            if self._gpu is not None and self._gpu.failed:
                self.close()
            raise
        finally:
            if owner is not None:
                owner.close()

    @property
    def position(self) -> str:
        return self._position

    @property
    def agent_pair(self) -> int:
        return self._pair

    @property
    def energy(self) -> int:
        """The field policy keeps energy outside its signed-distance B lane."""
        return self._energy if self._is_field else unpack(unpair(self.agent_pair)[0])[2]

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def status(self) -> str:
        return self._status

    @property
    def visible_paths(self) -> tuple[str, ...]:
        return tuple(sorted({self.position, *self._graph[self.position]}))

    @property
    def events(self) -> list[dict]:
        return deepcopy(self._events)

    def recorded_event(self, sequence: int) -> dict:
        """Copy one admitted event without copying the entire retained history."""
        _integer(sequence, 1, self.cycle, "sequence")
        return deepcopy(self._events[sequence - 1])

    @property
    def pending_search(self) -> bool:
        """Whether another planning quantum can continue retained work."""
        return self._planning is not None

    def _encode_frame(self, observations: object) -> dict[str, int]:
        if type(observations) is not dict:
            raise ValueError("Observations must be a path-to-hazard object")
        if any(type(path) is not str or path not in self.visible_paths for path in observations):
            raise ValueError("Observation lies outside this agent's local view")
        for hazard in observations.values():
            _integer(hazard, 0, 127, "hazard")
        encoded = {}
        for path, hazard in sorted(observations.items()):
            r, g, _, _ = unpack(unpair(self.world.derive(path).pair)[0])
            encoded[path] = pack(r, g, hazard, Opcode.DATA)
        return encoded

    def _entry_cost(self, path: str, hazard: int) -> int:
        if self._is_field:
            return self.world.entry_cost(path, hazard)
        return movement_cost(self.world.derive(path).pair, hazard)

    @property
    def _planning_energy(self) -> int | None:
        return self.energy if self._is_field else None

    def _model_weights(self, known: dict[str, int]) -> tuple[tuple[str, int], ...]:
        # Compare effective costs: observing a previously unknown zero hazard
        # confirms the baseline hypothesis without invalidating pending work.
        return tuple((path, self._entry_cost(path, unpack(known[path])[2] if path in known else 0))
                     for path in self._graph)

    def _reserve(self, epoch: int | None = None) -> int:
        if not self.is_growth:
            return self.manifest.repair_cost
        remaining = self._growth_binding.max_epochs - (self.geometry_epoch if epoch is None else epoch)
        return self.manifest.repair_cost + remaining * (self._growth_binding.cost + self.manifest.repair_cost)

    def _decide(self, frame: dict[str, int], known: dict[str, int]) -> tuple[Decision, _Planning | None]:
        if set(frame) != set(self.visible_paths):
            planning = self._planning
            if planning is not None and not planning.matches(
                self.position, self.agent_pair, self._model_weights(known), self._planning_energy
            ):
                planning = None
            return (Decision("WAIT", "Fresh observations of the current node and every outgoing neighbor are required"),
                    planning)
        energy = self.energy
        if self.is_growth and unpack(unpair(self.agent_pair)[0])[3] & 7 == Opcode.EMIT:
            if self.geometry_epoch >= self._growth_binding.max_epochs:
                raise ValueError("Completed final geometry cannot grow")
            if energy < self._growth_binding.cost + self._reserve(self.geometry_epoch + 1):
                return Decision("INSUFFICIENT_ENERGY", "Insufficient energy for growth and remaining repairs"), None
            return Decision("GROW", "Generate the next geometry and derive its target",
                            cost=self._growth_binding.cost), None
        if self.position == self.target:
            if energy < self._reserve():
                return Decision("INSUFFICIENT_ENERGY", "Insufficient energy for the target repair"), None
            r, g, b, a = unpack(unpair(self.agent_pair)[0])
            result = pair(pack(r, g, b if self._is_field else b - self.manifest.repair_cost,
                               (a & ~7) | Opcode.EMIT))
            return (Decision("REPAIR", "Observed target reached", cost=self.manifest.repair_cost,
                             expected_pair=result), None)

        def entry_cost(path: str) -> int:
            # Unseen farther nodes have the declared baseline hazard hypothesis.
            # A fresh local measurement is mandatory before entering any node.
            hazard = unpack(known[path])[2] if path in known else 0
            return self._entry_cost(path, hazard)

        try:
            if self.manifest.policy == LEGACY_POLICY:
                route = shortest_route(
                    self._graph, self.position, self.target, entry_cost,
                    max_hops=32, max_expansions=self.manifest.max_search_expansions,
                )
            else:
                weights = self._model_weights(known)
                planning = self._planning
                if planning is None or not planning.matches(
                        self.position, self.agent_pair, weights, self._planning_energy):
                    if self._is_hadamard:
                        r, _, _, metadata = unpack(unpair(self.agent_pair)[0])
                        phase = (-r if metadata & 16 else r) & 255
                        cursor = HadamardRouteSearch.start(
                            self.world.routing_model, self.position, self.target,
                            dict(weights).__getitem__, self.manifest.max_hops, initial_phase=phase)
                    else:
                        cursor = RouteSearch.start(self._graph, self.position, self.target,
                                                   dict(weights).__getitem__,
                                                   max_hops=self.manifest.max_hops if self._is_field else 32,
                                                   node_profile="relational-node-v1" if self._is_field
                                                   else "binary-path-v1")
                else:
                    cursor = planning.cursor
                cursor, route = cursor.advance(self.manifest.max_search_expansions)
                if route is None:
                    return (Decision("DEFER", "Retained unfinished route search for the next cycle",
                                     expansions=cursor.expansions),
                            _Planning(self.position, self.agent_pair, weights, cursor, self._planning_energy))
        except NoRoute:
            return Decision("UNREACHABLE", "The declared movement graph has no route to the target"), None
        except SearchBudgetExceeded as exc:
            return (Decision("DEFER", "The finite route-search budget did not establish a route",
                             expansions=exc.expansions), None)
        if route.cost + self._reserve() > energy:
            return (Decision("INSUFFICIENT_ENERGY", "The least-cost known route cannot preserve repair energy",
                             route=route.route, cost=route.cost, expansions=route.expansions), None)
        next_path = route.route[0]
        if next_path not in frame or next_path not in self._graph[self.position]:
            raise ValueError("Planner proposed movement without observed adjacency")
        hazards = tuple(unpack(known[path])[2] if path in known else 0 for path in route.route)
        if self._gpu is not None:
            forecast, costs = self._gpu.forecast(self.agent_pair, route.route, hazards)
            forecast_cost = sum(costs)
        elif self._is_field:
            forecast, costs = self.world.forecast(self.agent_pair, route.route, hazards)
            forecast_cost = sum(costs)
        else:
            imagined = self.agent_pair
            forecast = []
            forecast_cost = 0
            for path, hazard in zip(route.route, hazards):
                imagined, cost = move(imagined, path, self.world, hazard)
                forecast.append(imagined)
                forecast_cost += cost
        if forecast_cost != route.cost:
            raise ValueError("Route search and packed imagination disagree on cost")
        return (Decision("MOVE", "Follow the least-cost route in the current internal model",
                         route.route, route.cost, forecast[0], route.expansions, tuple(forecast)), None)

    @_serialized
    def step(self, observations: object) -> Decision:
        try:
            return self._step(observations)
        except BaseException:
            if self._is_field and self._gpu is not None and self._gpu.failed:
                self.close()
            raise

    def _growth_payload(self, candidate_recipe, candidate_gpu, certificate=None) -> dict:
        """Logical payload coexistence, separately from unmeasured object/driver overhead."""
        old_n = self.current_recipe.width * self.current_recipe.height
        new_n = candidate_recipe.width * candidate_recipe.height
        payload = {
            "host_index_bytes": 64 * (old_n + new_n) + 32,
            "host_routing_table_bytes": 68 * (old_n + new_n),
            "host_routing_geometry_bytes": 16 * (old_n + new_n),
            "host_routing_gains_bytes": 64,
            "active_fifo_pair_bytes": 8 * len(self.world.active_paths),
        }
        if candidate_gpu is None:
            payload["temporary_candidate_field_bytes"] = 4 * new_n
        if candidate_gpu is not None:
            old, new = self._gpu.allocation_info, candidate_gpu.allocation_info
            for key in ("device_buffer_bytes", "device_texture_bytes", "device_payload_bytes",
                        "host_field_code_payload_bytes", "host_geometry_payload_bytes"):
                payload[key] = old[key] + new[key]
        if self.is_organogram:
            payload["recipe_json_bytes"] = sum(len(json.dumps(value.to_dict(), sort_keys=True,
                separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8'))
                for value in (self.current_recipe, candidate_recipe))
            if certificate is not None:
                payload["candidate_derivation_json_bytes"] = len(json.dumps(
                    certificate.last_derivation, sort_keys=True, separators=(',', ':'),
                    ensure_ascii=True, allow_nan=False).encode('utf-8'))
            if candidate_gpu is not None:
                old_grammar = old.get("organogram", {})
                new_grammar = new["organogram"]
                for key in ("instruction_texture_bytes", "grammar_movement_texture_bytes",
                            "grammar_scratch_buffer_bytes", "grammar_private_stack_payload_bytes",
                            "peak_grammar_host_stage_payload_bytes", "peak_grammar_host_tape_metadata_bytes",
                            "peak_grammar_host_tape_word_bytes", "grammar_retained_transcript_bytes",
                            "grammar_retained_recipe_bytes"):
                    # These break down covered device/host payloads; they are
                    # not additional bytes to add to device_payload_bytes.
                    payload[key] = old_grammar.get(key, 0) + new_grammar[key]
        return {key: max(value, self._growth_peak.get(key, 0)) for key, value in payload.items()}

    def _grow(self, frame: dict[str, int]) -> Decision:
        """Prepare a whole independent epoch, then admit exactly one indivisible event."""
        old_gpu = self._gpu
        candidate_gpu = None
        certificate = None
        try:
            r, old_node, old_b, metadata = unpack(unpair(self.agent_pair)[0])
            if (metadata not in (int(Opcode.EMIT), int(Opcode.EMIT) | 16)
                    or old_node != self.current_recipe.index(self.position)
                    or self.position != self.target):
                raise ValueError("Growth requires the completed current subgoal")
            if unpack(unpair(self.world.derive(self.position).pair)[0])[2] != old_b:
                raise ValueError("Growth source pair disagrees with its original field")
            recipe = (self._organogram_recipe(self.current_recipe, self.cycle + 1,
                       f"{self.agent_pair:016X}", self._events)
                      if self.is_organogram else grow_recipe(self.current_recipe))
            binding = self.world.index.binding
            if old_gpu is not None:
                from .field_agent_gpu import GpuFieldAgentExecutor
                candidate_gpu = GpuFieldAgentExecutor(recipe, index_binding=binding,
                                                      routing=self.manifest.routing)
                certificate = candidate_gpu.certificate if self.is_organogram else None
                self._growth_peak = self._growth_payload(recipe, candidate_gpu, certificate)
            elif self.is_organogram:
                certificate = regenerate(recipe)
            certificate_options = {"certificate": certificate} if certificate is not None else {}
            candidate_world = FieldWorld(recipe, self.world.capacity, executor=candidate_gpu,
                                         index_binding=binding, routing=self.manifest.routing, **certificate_options)
            if candidate_gpu is None:
                self._growth_peak = self._growth_payload(recipe, None, certificate)
                from .field import evaluate_field
                fields = certificate.fields if certificate is not None else evaluate_field(recipe.field_manifest())
            else:
                fields = candidate_gpu.fields
            mapped = old_node if self.is_organogram else map_node(self.current_recipe, old_node)
            phase = (-r if metadata & 16 else r) & 255
            target_node = (select_organogram_target(recipe, fields, mapped, phase, certificate=certificate)
                           if self.is_organogram else select_target(recipe, fields, mapped, phase))
            position = f"k:{mapped // recipe.height}:{mapped % recipe.height}"
            target = f"k:{target_node // recipe.height}:{target_node % recipe.height}"
            expected = pair(pack(r, mapped, fields[mapped], int(Opcode.STEP) | (metadata & 16)))
            energy = self.energy - self._growth_binding.cost
            if candidate_gpu is not None:
                if self.is_organogram:
                    actual = candidate_gpu.admit_generated(
                        old_gpu, self._growth_binding.cost, organogram=self.manifest.organogram,
                        prefix_sha256=recipe.stages[-1].prefix_sha256)
                else:
                    actual = candidate_gpu.admit_growth(old_gpu, self._growth_binding.cost)
                if actual != (expected, energy):
                    raise ValueError("Actual GPU growth differs from independent admission")
            next_epoch = self.geometry_epoch + 1
            receipt = {"format": "klein-organogram-growth-v1" if self.is_organogram else self.manifest.growth.format,
                       "from_epoch": self.geometry_epoch, "to_epoch": next_epoch,
                       "mapped_node": position, "target": target, "recipe": recipe.to_dict()}
            if self.is_organogram:
                receipt["derivation_sha256"] = hashlib.sha256(json.dumps(
                    certificate.last_derivation, sort_keys=True, separators=(',', ':'),
                    ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
            decision = Decision("GROW", "Generate a branching field and derive its target" if self.is_organogram
                                else "Generate the next geometry and derive its target",
                                cost=self._growth_binding.cost, expected_pair=expected)
            event = {"seq": self.cycle + 1,
                     "input": {path: f"{word:08X}" for path, word in frame.items()},
                     "decision": decision.to_dict(), "output": f"{expected:016X}",
                     "energy": energy, "geometry_epoch": self.geometry_epoch, "growth": receipt}
            events = [*self._events, event]
            graph = dict(recipe.graph())
        except BaseException as exc:
            uncertain = (getattr(exc, "device_uncertain", False)
                         or getattr(exc, "candidate_failed", False)
                         or (candidate_gpu is not None and candidate_gpu.failed)
                         or (old_gpu is not None and old_gpu.failed))
            if candidate_gpu is not None:
                try:
                    candidate_gpu.close()
                except BaseException:
                    uncertain = True
            if uncertain:
                try:
                    self.close()
                except BaseException:
                    pass
            raise
        # Everything that can reject the candidate precedes these owner assignments.
        self.world, self._gpu, self._graph = candidate_world, candidate_gpu, graph
        self._pair, self._energy = expected, energy
        self._position, self._target = position, target
        self._geometry_epoch = next_epoch
        self._observations, self._planning = {}, None
        self._status = "ACTIVE"
        self._cycle += 1
        self._last_decision, self._events = decision, events
        if old_gpu is not None:
            try:
                old_gpu.close()
            except BaseException as exc:
                try:
                    self.close()
                except BaseException:
                    pass
                raise CommittedGrowthCleanupError(
                    f"Geometry epoch {next_epoch} committed; retiring the old world failed") from exc
        return decision

    def _step(self, observations: object) -> Decision:
        if self._closed:
            raise ValueError("This agent is closed")
        if self.status == "COMPLETE":
            raise ValueError("This agent's declared objective is complete")
        if self.cycle >= self.manifest.max_cycles:
            raise ValueError("The declared agent cycle budget is exhausted")
        frame = self._encode_frame(observations)
        known = {**self._observations, **frame}
        decision, planning = self._decide(frame, known)
        if decision.kind == "GROW":
            return self._grow(frame)
        if decision.expected_pair is not None:
            unpair(decision.expected_pair)
            if self._gpu is not None and not self._is_field:
                self._gpu.commit_pair(decision.expected_pair)
        next_energy = self.energy
        action_cost = 0
        if self._is_field and decision.kind == "MOVE":
            next_path = decision.route[0]
            action_cost = self._entry_cost(next_path, unpack(frame[next_path])[2])
            if self._is_hadamard:
                r, source, _, metadata = unpack(unpair(self.agent_pair)[0])
                phase = (-r if metadata & 16 else r) & 255
                action_cost += self.world.routing_model.penalty(
                    source, phase, self.current_recipe.index(next_path))
            next_energy -= action_cost
        elif self._is_field and decision.kind == "REPAIR":
            action_cost = self.manifest.repair_cost
            next_energy -= action_cost
        # Validation and hypothetical execution finish before live mutation.
        for path in frame:
            self.world.get(path)
        if self._is_field and self._gpu is not None and decision.expected_pair is not None:
            try:
                if decision.kind == "MOVE":
                    actual, device_cost, device_energy = self._gpu.advance_to(
                        decision.route[0], unpack(frame[decision.route[0]])[2])
                    if device_cost != action_cost:
                        raise ValueError("Actual GPU movement disagrees with the admitted cost")
                else:
                    actual, device_energy = self._gpu.repair(action_cost)
                if (actual, device_energy) != (decision.expected_pair, next_energy):
                    raise ValueError("Actual GPU action disagrees with the admitted prediction")
            except BaseException:
                self.close()
                raise
        if self._is_field:
            self._energy = next_energy
        self._observations = known
        self._planning = planning
        if decision.kind == "MOVE":
            self._position = decision.route[0]
            self._pair = decision.expected_pair
        elif decision.kind == "REPAIR":
            self._pair = decision.expected_pair
        self._status = {
            "MOVE": "ACTIVE", "REPAIR": "COMPLETE", "WAIT": "WAITING",
            "UNREACHABLE": "UNREACHABLE", "INSUFFICIENT_ENERGY": "INSUFFICIENT_ENERGY",
            "DEFER": "SEARCH_DEFERRED",
        }[decision.kind]
        if (self.is_growth and decision.kind == "REPAIR"
                and self.geometry_epoch < self._growth_binding.max_epochs):
            self._status = "GROWTH_PENDING"
        self._cycle += 1
        self._last_decision = decision
        self._events.append({
            "seq": self.cycle, "input": {path: f"{word:08X}" for path, word in frame.items()},
            "decision": decision.to_dict(), "output": f"{self.agent_pair:016X}",
        })
        if self._is_field:
            self._events[-1]["energy"] = self.energy
        if self.is_growth:
            self._events[-1].update(geometry_epoch=self.geometry_epoch, growth=None)
        return decision

    @_serialized
    def snapshot(self) -> dict:
        snapshot = {
            "identity": self.identity, "cycle": self.cycle, "status": self.status,
            "position": self.position, "target": self.target,
            "agent_pair": f"{self.agent_pair:016X}",
            "footprint": {
                "profile": FORMAT, "baseline": self.manifest.world.baseline_id,
                "agent": self.identity, "epoch": self.geometry_epoch, "sequence": self.cycle,
                "derivation": self.position,
            },
            "observations": {path: f"{word:08X}" for path, word in sorted(self._observations.items())},
            "last_decision": None if self._last_decision is None else self._last_decision.to_dict(),
        }
        if self._is_field:
            snapshot.update(energy=self.energy, word_profile=FIELD_WORD_PROFILE)
        if self.is_growth:
            snapshot.update(geometry_epoch=self.geometry_epoch, current_recipe=self.current_recipe.to_dict())
            if not self.is_organogram:
                snapshot["scale_exponent"] = self.geometry_epoch
        if self.manifest.policy in (POLICY, FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            planning = self._planning
            snapshot["planning"] = None if planning is None else {
                "position": planning.position, "target": self.target,
                "agent_pair": f"{planning.agent_pair:016X}", "weights": dict(planning.weights),
                "expansions": planning.cursor.expansions,
                "pending_states": planning.cursor.pending_states,
            }
            if self._is_field and planning is not None:
                snapshot["planning"]["energy"] = planning.energy
            if self.is_growth and planning is not None:
                snapshot["planning"]["geometry_epoch"] = self.geometry_epoch
        return snapshot

    @_serialized
    def archive(self) -> dict:
        return {"format": FORMAT, "manifest": self.manifest.to_dict(),
                "events": self.events, "expected": self.snapshot()}

    @classmethod
    def from_archive(cls, archive: object, capacity: int = 2, *, backend: str = "cpu",
                     index_binding: IndexBinding | None = None) -> Tomigidt:
        _keys(archive, {"format", "manifest", "events", "expected"}, "Agent archive")
        if archive["format"] != FORMAT or type(archive["events"]) is not list:
            raise ValueError("Unsupported agent archive format or event array")
        options = {"backend": backend}
        if index_binding is not None:
            options["index_binding"] = index_binding
        agent = cls(AgentManifest.from_dict(archive["manifest"]), capacity, **options)
        try:
            agent._restore_events(archive)
        except BaseException:
            agent.close()
            raise
        return agent

    def _restore_events(self, archive: dict) -> None:
        agent = self
        if len(archive["events"]) > agent.manifest.max_cycles:
            raise ValueError("Archive exceeds its declared cycle budget")
        for event in archive["events"]:
            _keys(event, {"seq", "input", "decision", "output"}
                  | ({"energy"} if agent._is_field else set())
                  | ({"geometry_epoch", "growth"} if agent.is_growth else set()), "Agent event")
            if agent.is_growth:
                if _integer(event["geometry_epoch"], 0, agent._growth_binding.max_epochs,
                            "geometry_epoch") != agent.geometry_epoch:
                    raise ValueError("Event geometry epoch differs from its original context")
            if agent._is_field:
                _integer(event["energy"], 0, (1 << 31) - 1, "event energy")
            if _integer(event["seq"], 1, agent.manifest.max_cycles, "seq") != agent.cycle + 1:
                raise ValueError("Agent events must retain consecutive original sequence numbers")
            if type(event["input"]) is not dict:
                raise ValueError("Agent input must be a packet object")
            observations = {}
            for path, encoded in event["input"].items():
                if (type(encoded) is not str or len(encoded) != 8
                        or any(char not in "0123456789ABCDEF" for char in encoded)):
                    raise ValueError("Observation packets require eight uppercase hex digits")
                word = int(encoded, 16)
                _, _, hazard, _ = unpack(word)
                observations[path] = hazard
            agent.step(observations)
            if _json(agent._events[-1]) != _json(event):
                raise ValueError("Replayed observation, decision or output differs from its recorded event")
        if _json(agent.snapshot()) != _json(archive["expected"]):
            raise ValueError("Replayed agent disagrees with the retained expected state")

    def save(self, path: str | Path) -> None:
        write_json(path, self.archive())

    @classmethod
    def load(cls, path: str | Path, capacity: int = 2, *, backend: str = "cpu",
             index_binding: IndexBinding | None = None) -> Tomigidt:
        def unique_object(items: list[tuple[str, object]]) -> dict:
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError(f"Duplicate JSON key: {key}")
                value[key] = item
            return value

        with Path(path).open(encoding="utf-8") as stream:
            archive = json.load(stream, object_pairs_hook=unique_object)
        return cls.from_archive(archive, capacity, backend=backend, index_binding=index_binding)
