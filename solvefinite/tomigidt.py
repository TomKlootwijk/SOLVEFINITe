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
import json
from pathlib import Path

from .motion import move, movement_cost
from .navigation import NoRoute, RouteSearch, SearchBudgetExceeded, normalize_graph, shortest_route
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _json, _keys, write_json
from .world import World, WorldConfig, _capacity
from .field_agent import FIELD_POLICY, HADAMARD_POLICY, FIELD_WORD_PROFILE, FieldAgentManifest
from .hadamard_navigation import HadamardRouteSearch
from .field_world import FieldWorld
from .f8 import F8Index, IndexBinding


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
        if type(value) is dict and value.get("policy") in (FIELD_POLICY, HADAMARD_POLICY):
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
        # Target, graph and generation rules belong to the immutable manifest.
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
        self._is_hadamard = self._manifest.policy == HADAMARD_POLICY
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
        if self.position == self.manifest.target:
            if energy < self.manifest.repair_cost:
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
                    self._graph, self.position, self.manifest.target, entry_cost,
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
                            self.world.routing_model, self.position, self.manifest.target,
                            dict(weights).__getitem__, self.manifest.max_hops, initial_phase=phase)
                    else:
                        cursor = RouteSearch.start(self._graph, self.position, self.manifest.target,
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
        if route.cost + self.manifest.repair_cost > energy:
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
                    source, phase, self.manifest.world.index(next_path))
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
        self._cycle += 1
        self._last_decision = decision
        self._events.append({
            "seq": self.cycle, "input": {path: f"{word:08X}" for path, word in frame.items()},
            "decision": decision.to_dict(), "output": f"{self.agent_pair:016X}",
        })
        if self._is_field:
            self._events[-1]["energy"] = self.energy
        return decision

    @_serialized
    def snapshot(self) -> dict:
        snapshot = {
            "identity": self.identity, "cycle": self.cycle, "status": self.status,
            "position": self.position, "target": self.manifest.target,
            "agent_pair": f"{self.agent_pair:016X}",
            "footprint": {
                "profile": FORMAT, "baseline": self.manifest.world.baseline_id,
                "agent": self.identity, "epoch": 0, "sequence": self.cycle,
                "derivation": self.position,
            },
            "observations": {path: f"{word:08X}" for path, word in sorted(self._observations.items())},
            "last_decision": None if self._last_decision is None else self._last_decision.to_dict(),
        }
        if self._is_field:
            snapshot.update(energy=self.energy, word_profile=FIELD_WORD_PROFILE)
        if self.manifest.policy in (POLICY, FIELD_POLICY, HADAMARD_POLICY):
            planning = self._planning
            snapshot["planning"] = None if planning is None else {
                "position": planning.position, "target": self.manifest.target,
                "agent_pair": f"{planning.agent_pair:016X}", "weights": dict(planning.weights),
                "expansions": planning.cursor.expansions,
                "pending_states": planning.cursor.pending_states,
            }
            if self._is_field and planning is not None:
                snapshot["planning"]["energy"] = planning.energy
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
                  | ({"energy"} if agent._is_field else set()), "Agent event")
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
