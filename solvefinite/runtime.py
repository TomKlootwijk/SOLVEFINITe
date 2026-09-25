"""A versioned, replayable colony-agent experiment built on RP32.

This module supplies demo-specific planning, energy and event semantics. They
are explicit implementation choices, not additional claims about the source
paradigm. Journal envelopes retain paths and rules that cannot fit in one word.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile

from .rp32 import Opcode, pack, pair, step, unpack, unpair
from .world import World, WorldConfig


FORMAT = "solvefinite-journal-v1"
VERSION = "colony-runtime-v1"
PROFILE = "RP32-v1"
PLANNER = "min-energy-then-lexicographic-v1"
MAX_CANDIDATES = 32
MAX_ROUTE_LENGTH = 32
MAX_EVENTS = 10_000


def _keys(value: object, names: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != names:
        raise ValueError(f"{label} must contain exactly {sorted(names)}")


def _integer(value: object, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in [{low}, {high}]")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        raise ValueError("Archive contains unsupported JSON values") from exc


def write_json(path: str | Path, value: object) -> None:
    """Replace a generated artifact atomically within its target directory."""
    destination = Path(path)
    data = _json(value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
            prefix=destination.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class Manifest:
    world: WorldConfig = field(default_factory=WorldConfig)
    agent_seed: tuple[int, int, int, int] = (250, 3, 100, 1)
    repair_cost: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.world, WorldConfig):
            raise ValueError("world must be a WorldConfig")
        if type(self.agent_seed) is not tuple or len(self.agent_seed) != 4:
            raise ValueError("agent_seed must be a four-field tuple")
        pack(*self.agent_seed)
        if self.agent_seed[2] < 0 or self.agent_seed[3] & 7 != Opcode.STEP:
            raise ValueError("Agent seed must have nonnegative energy and STEP opcode")
        _integer(self.repair_cost, 1, 127, "repair_cost")

    def to_dict(self) -> dict:
        return {
            "version": VERSION, "word_profile": PROFILE, "planner": PLANNER,
            "world": self.world.to_dict(), "agent_seed": list(self.agent_seed),
            "repair_cost": self.repair_cost,
            "max_candidates": MAX_CANDIDATES, "max_route_length": MAX_ROUTE_LENGTH,
            "max_events": MAX_EVENTS,
        }

    @classmethod
    def from_dict(cls, value: object) -> Manifest:
        _keys(value, {
            "version", "word_profile", "planner", "world", "agent_seed",
            "repair_cost", "max_candidates", "max_route_length", "max_events",
        }, "Manifest")
        fixed = {
            "version": VERSION, "word_profile": PROFILE, "planner": PLANNER,
            "max_candidates": MAX_CANDIDATES, "max_route_length": MAX_ROUTE_LENGTH,
            "max_events": MAX_EVENTS,
        }
        for name, expected in fixed.items():
            if type(value[name]) is not type(expected) or value[name] != expected:
                raise ValueError(f"Unsupported manifest binding: {name}")
        if type(value["agent_seed"]) is not list:
            raise ValueError("agent_seed must be a JSON array")
        return cls(WorldConfig.from_dict(value["world"]),
                   tuple(value["agent_seed"]), value["repair_cost"])


class InfeasiblePlan(ValueError):
    """A simulated route cannot leave enough energy to finish the repair."""


@dataclass(frozen=True)
class Plan:
    route: tuple[str, ...]
    cost: int
    states: tuple[int, ...]

    @property
    def final_pair(self) -> int:
        return self.states[-1]

    def to_dict(self) -> dict:
        return {"route": list(self.route), "movement_cost": self.cost,
                "states": [f"{state:016X}" for state in self.states]}


class Runtime:
    """Live state is rebuilt from genesis plus admitted events, never a snapshot."""

    def __init__(self, manifest: Manifest | None = None, capacity: int = 2):
        self.manifest = Manifest() if manifest is None else manifest
        if not isinstance(self.manifest, Manifest):
            raise ValueError("manifest must be a Manifest")
        self.world = World(self.manifest.world, capacity)
        self.tick = 0
        self.agent_pair = pair(pack(*self.manifest.agent_seed))
        self.position = ""
        self.plan: tuple[str, ...] = ()
        self.cursor = 0
        self.repaired = False
        self._observations: dict[str, int] = {}
        self._events: list[dict] = []

    @property
    def events(self) -> list[dict]:
        return deepcopy(self._events)

    def _route(self, value: object) -> tuple[str, ...]:
        if type(value) not in (list, tuple) or not 1 <= len(value) <= MAX_ROUTE_LENGTH:
            raise ValueError(f"A route must contain 1..{MAX_ROUTE_LENGTH} waypoints")
        route = tuple(value)
        for path in route:
            self.world.derive(path)
        return route

    def _move(self, agent: int, path: str) -> tuple[int, int]:
        """Shared imagination/action kernel; no mutation or cache access."""
        left, _ = unpair(agent)
        r, g, energy, a = unpack(left)
        node_left, _ = unpair(self.world.derive(path).pair)
        _, node_g, terrain, _ = unpack(node_left)
        hazard = unpack(self._observations[path])[2] if path in self._observations else 0
        cost = 1 + abs(terrain) // 8 + hazard
        if energy < cost:
            raise InfeasiblePlan(f"Insufficient energy to enter waypoint {path!r}")
        row = (g ^ node_g ^ (r >> 6)) & 3
        branch = int(path[-1]) if path else 0
        delta = self.manifest.world.phase_turns[row][branch]
        next_r, _, _, _ = unpack(step(left, delta))
        return pair(pack(next_r, node_g, energy - cost, (a & ~7) | Opcode.STEP)), cost

    def evaluate(self, route: object) -> Plan:
        paths = self._route(route)
        agent = self.agent_pair
        states = []
        total = 0
        for path in paths:
            agent, cost = self._move(agent, path)
            states.append(agent)
            total += cost
        energy = unpack(unpair(agent)[0])[2]
        if energy < self.manifest.repair_cost:
            raise InfeasiblePlan("Route would leave insufficient energy for repair")
        return Plan(paths, total, tuple(states))

    def _choose(self, candidates: object) -> Plan:
        if type(candidates) not in (list, tuple) or not 1 <= len(candidates) <= MAX_CANDIDATES:
            raise ValueError(f"Expected 1..{MAX_CANDIDATES} candidate routes")
        # Validate every route before filtering for feasibility. Invalid input is
        # an admission error, not a candidate to silently ignore.
        routes = [self._route(route) for route in candidates]
        feasible = []
        for route in routes:
            try:
                feasible.append(self.evaluate(route))
            except InfeasiblePlan:
                continue
        if not feasible:
            raise InfeasiblePlan("No candidate route can complete the repair")
        return min(feasible, key=lambda plan: (plan.cost, plan.route))

    def _new(self, kind: str, word: int, **payload: object) -> None:
        self._apply({"seq": self.tick + 1, "tick": self.tick + 1,
                     "kind": kind, "word": f"{word:08X}", **payload})

    def observe(self, path: str, hazard: int) -> None:
        _integer(hazard, 0, 127, "hazard")
        r, g, _, _ = unpack(unpair(self.world.derive(path).pair)[0])
        self._new("OBSERVE", pack(r, g, hazard, Opcode.DATA), path=path)

    def select_plan(self, candidates: object) -> Plan:
        chosen = self._choose(candidates)
        self._new("PLAN", pack(0, 0, 0, Opcode.BRANCH),
                  candidates=[list(route) for route in candidates])
        return chosen

    def advance(self) -> None:
        self._new("ADVANCE", pack(0, 0, 0, Opcode.STEP))

    def repair(self) -> None:
        self._new("REPAIR", pack(0, 0, self.manifest.repair_cost, Opcode.CONTROL))

    def finish(self) -> None:
        if self.repaired:
            return
        if not self.plan:
            raise ValueError("A plan must be selected before finishing")
        while self.cursor < len(self.plan):
            self.advance()
        self.repair()

    def _apply(self, event: object) -> None:
        if self.repaired:
            raise ValueError("This completed mission admits no further events")
        if len(self._events) >= MAX_EVENTS:
            raise ValueError("Demo journal event budget exhausted")
        if type(event) is not dict:
            raise ValueError("Event must be an object")
        kind = event.get("kind")
        extras = {"OBSERVE": {"path"}, "PLAN": {"candidates"},
                  "ADVANCE": set(), "REPAIR": set()}
        if type(kind) is not str or kind not in extras:
            raise ValueError("Unsupported event kind")
        _keys(event, {"seq", "tick", "kind", "word"} | extras[kind], "Event")
        for key in ("seq", "tick"):
            if _integer(event[key], 1, MAX_EVENTS, key) != self.tick + 1:
                raise ValueError("Events must have consecutive original ticks and sequence numbers")
        encoded = event["word"]
        if (type(encoded) is not str or len(encoded) != 8
                or any(c not in "0123456789ABCDEF" for c in encoded)):
            raise ValueError("Event word must be eight uppercase hexadecimal digits")
        word = int(encoded, 16)
        r, g, b, a = unpack(word)
        if kind == "OBSERVE":
            node = self.world.derive(event["path"])
            nr, ng, _, _ = unpack(unpair(node.pair)[0])
            if not 0 <= b <= 127 or word != pack(nr, ng, b, Opcode.DATA):
                raise ValueError("Observation word does not match its waypoint or DATA profile")
            # Only validated, accepted events can affect the active cache.
            self.world.get(event["path"])
            self._observations[event["path"]] = word
            self.plan, self.cursor = (), 0
        elif kind == "PLAN":
            if word != pack(0, 0, 0, Opcode.BRANCH):
                raise ValueError("PLAN requires the declared BRANCH command word")
            if type(event["candidates"]) is not list or any(
                type(route) is not list for route in event["candidates"]
            ):
                raise ValueError("PLAN candidates must be JSON arrays")
            chosen = self._choose(event["candidates"])
            self.plan, self.cursor = chosen.route, 0
        elif kind == "ADVANCE":
            if word != pack(0, 0, 0, Opcode.STEP):
                raise ValueError("ADVANCE requires the declared STEP command word")
            if not self.plan or self.cursor >= len(self.plan):
                raise ValueError("No unfinished selected route")
            path = self.plan[self.cursor]
            agent, _ = self._move(self.agent_pair, path)
            self.world.get(path)
            self.agent_pair, self.position = agent, path
            self.cursor += 1
        else:
            if word != pack(0, 0, self.manifest.repair_cost, Opcode.CONTROL):
                raise ValueError("REPAIR requires the declared CONTROL command word")
            if not self.plan or self.cursor != len(self.plan):
                raise ValueError("Repair requires a completed route")
            ar, ag, energy, aa = unpack(unpair(self.agent_pair)[0])
            if energy < self.manifest.repair_cost:
                raise InfeasiblePlan("Insufficient repair energy")
            self.agent_pair = pair(pack(ar, ag, energy - self.manifest.repair_cost,
                                        (aa & ~7) | Opcode.EMIT))
            self.repaired = True
        self.tick += 1
        self._events.append(deepcopy(event))

    def snapshot(self) -> dict:
        return {
            "tick": self.tick, "agent_pair": f"{self.agent_pair:016X}",
            "position": self.position, "plan": list(self.plan),
            "cursor": self.cursor, "repaired": self.repaired,
            "observations": {path: f"{word:08X}" for path, word in sorted(self._observations.items())},
        }

    def archive(self) -> dict:
        return {"format": FORMAT, "manifest": self.manifest.to_dict(),
                "events": self.events, "expected": self.snapshot()}

    @classmethod
    def from_archive(cls, archive: object, capacity: int = 2) -> Runtime:
        _keys(archive, {"format", "manifest", "events", "expected"}, "Archive")
        if archive["format"] != FORMAT:
            raise ValueError("Unsupported journal format")
        events = archive["events"]
        if type(events) is not list or len(events) > MAX_EVENTS:
            raise ValueError("Invalid journal event array or event budget")
        runtime = cls(Manifest.from_dict(archive["manifest"]), capacity)
        for event in events:
            runtime._apply(event)
        # The expected snapshot is only a witness; never loaded as live state.
        # Canonical JSON comparison also distinguishes bools from integers.
        if _json(runtime.snapshot()) != _json(archive["expected"]):
            raise ValueError("Replay disagrees with the retained expected state")
        return runtime

    def save(self, path: str | Path) -> None:
        write_json(path, self.archive())

    @classmethod
    def load(cls, path: str | Path, capacity: int = 2) -> Runtime:
        def unique_object(pairs: list[tuple[str, object]]) -> dict:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON key: {key}")
                result[key] = value
            return result

        with Path(path).open(encoding="utf-8") as stream:
            archive = json.load(stream, object_pairs_hook=unique_object)
        return cls.from_archive(archive, capacity)
