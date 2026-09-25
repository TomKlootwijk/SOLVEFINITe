"""One persistent observer with an autonomous, replayable decision loop.

TOMIGIDt is a new application profile. Its local-observation interpretation is
an explicit implementation assumption, not a definition of philosophical
solipsism or a claim found in the source specification.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path

from .motion import move, movement_cost
from .navigation import NoRoute, RouteSearch, SearchBudgetExceeded, normalize_graph, shortest_route
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _json, _keys, write_json
from .world import World, WorldConfig


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

    @classmethod
    def from_dict(cls, value: object) -> AgentManifest:
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
    cursor: RouteSearch

    def matches(self, position: str, agent_pair: int, weights: tuple[tuple[str, int], ...]) -> bool:
        # Target, graph and generation rules belong to the immutable manifest.
        return (self.position, self.agent_pair, self.weights) == (position, agent_pair, weights)


class Tomigidt:
    """A single decision maker; the mirrored half is a representation check.

    The agent owns its identity, goal, observations, decisions and packed state.
    Sensors supply observations only. They cannot supply a route or action.
    """

    def __init__(self, manifest: AgentManifest | None = None, capacity: int = 2):
        self._manifest = AgentManifest() if manifest is None else manifest
        if type(self._manifest) is not AgentManifest:
            raise ValueError("manifest must be an AgentManifest")
        self.world = World(self._manifest.world, capacity)
        self._graph = dict(self._manifest.graph)
        self._pair = pair(pack(*self._manifest.agent_seed))
        self._position = ""
        self._cycle = 0
        self._status = "ACTIVE"
        self._observations: dict[str, int] = {}
        self._last_decision: Decision | None = None
        self._planning: _Planning | None = None
        self._events: list[dict] = []

    @property
    def manifest(self) -> AgentManifest:
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
        encoded = {}
        for path, hazard in sorted(observations.items()):
            _integer(hazard, 0, 127, "hazard")
            r, g, _, _ = unpack(unpair(self.world.derive(path).pair)[0])
            encoded[path] = pack(r, g, hazard, Opcode.DATA)
        return encoded

    def _model_weights(self, known: dict[str, int]) -> tuple[tuple[str, int], ...]:
        # Compare effective costs: observing a previously unknown zero hazard
        # confirms the baseline hypothesis without invalidating pending work.
        return tuple((path, movement_cost(self.world.derive(path).pair,
                                         unpack(known[path])[2] if path in known else 0))
                     for path in self._graph)

    def _decide(self, frame: dict[str, int], known: dict[str, int]) -> tuple[Decision, _Planning | None]:
        if set(frame) != set(self.visible_paths):
            planning = self._planning
            if planning is not None and not planning.matches(
                self.position, self.agent_pair, self._model_weights(known)
            ):
                planning = None
            return (Decision("WAIT", "Fresh observations of the current node and every outgoing neighbor are required"),
                    planning)
        energy = unpack(unpair(self.agent_pair)[0])[2]
        if self.position == self.manifest.target:
            if energy < self.manifest.repair_cost:
                return Decision("INSUFFICIENT_ENERGY", "Insufficient energy for the target repair"), None
            r, g, b, a = unpack(unpair(self.agent_pair)[0])
            result = pair(pack(r, g, b - self.manifest.repair_cost, (a & ~7) | Opcode.EMIT))
            return (Decision("REPAIR", "Observed target reached", cost=self.manifest.repair_cost,
                             expected_pair=result), None)

        def entry_cost(path: str) -> int:
            # Unseen farther nodes have the declared baseline hazard hypothesis.
            # A fresh local measurement is mandatory before entering any node.
            hazard = unpack(known[path])[2] if path in known else 0
            return movement_cost(self.world.derive(path).pair, hazard)

        try:
            if self.manifest.policy == LEGACY_POLICY:
                route = shortest_route(
                    self._graph, self.position, self.manifest.target, entry_cost,
                    max_hops=32, max_expansions=self.manifest.max_search_expansions,
                )
            else:
                weights = self._model_weights(known)
                planning = self._planning
                if planning is None or not planning.matches(self.position, self.agent_pair, weights):
                    cursor = RouteSearch.start(self._graph, self.position, self.manifest.target,
                                               dict(weights).__getitem__, max_hops=32)
                else:
                    cursor = planning.cursor
                cursor, route = cursor.advance(self.manifest.max_search_expansions)
                if route is None:
                    return (Decision("DEFER", "Retained unfinished route search for the next cycle",
                                     expansions=cursor.expansions),
                            _Planning(self.position, self.agent_pair, weights, cursor))
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
        imagined = self.agent_pair
        forecast = []
        forecast_cost = 0
        for path in route.route:
            hazard = unpack(known[path])[2] if path in known else 0
            imagined, cost = move(imagined, path, self.world, hazard)
            forecast.append(imagined)
            forecast_cost += cost
        if forecast_cost != route.cost:
            raise ValueError("Route search and packed imagination disagree on cost")
        return (Decision("MOVE", "Follow the least-cost route in the current internal model",
                         route.route, route.cost, forecast[0], route.expansions, tuple(forecast)), None)

    def step(self, observations: object) -> Decision:
        if self.status == "COMPLETE":
            raise ValueError("This agent's declared objective is complete")
        if self.cycle >= self.manifest.max_cycles:
            raise ValueError("The declared agent cycle budget is exhausted")
        frame = self._encode_frame(observations)
        known = {**self._observations, **frame}
        decision, planning = self._decide(frame, known)
        if decision.expected_pair is not None:
            unpair(decision.expected_pair)
        # Validation and hypothetical execution finish before live mutation.
        for path in frame:
            self.world.get(path)
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
        return decision

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
        if self.manifest.policy == POLICY:
            planning = self._planning
            snapshot["planning"] = None if planning is None else {
                "position": planning.position, "target": self.manifest.target,
                "agent_pair": f"{planning.agent_pair:016X}", "weights": dict(planning.weights),
                "expansions": planning.cursor.expansions,
                "pending_states": planning.cursor.pending_states,
            }
        return snapshot

    def archive(self) -> dict:
        return {"format": FORMAT, "manifest": self.manifest.to_dict(),
                "events": self.events, "expected": self.snapshot()}

    @classmethod
    def from_archive(cls, archive: object, capacity: int = 2) -> Tomigidt:
        _keys(archive, {"format", "manifest", "events", "expected"}, "Agent archive")
        if archive["format"] != FORMAT or type(archive["events"]) is not list:
            raise ValueError("Unsupported agent archive format or event array")
        agent = cls(AgentManifest.from_dict(archive["manifest"]), capacity)
        if len(archive["events"]) > agent.manifest.max_cycles:
            raise ValueError("Archive exceeds its declared cycle budget")
        for event in archive["events"]:
            _keys(event, {"seq", "input", "decision", "output"}, "Agent event")
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
        return agent

    def save(self, path: str | Path) -> None:
        write_json(path, self.archive())

    @classmethod
    def load(cls, path: str | Path, capacity: int = 2) -> Tomigidt:
        def unique_object(items: list[tuple[str, object]]) -> dict:
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError(f"Duplicate JSON key: {key}")
                value[key] = item
            return value

        with Path(path).open(encoding="utf-8") as stream:
            archive = json.load(stream, object_pairs_hook=unique_object)
        return cls.from_archive(archive, capacity)
