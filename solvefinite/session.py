"""Persistent execution of one TOMIGIDt agent in a declared synthetic world.

The scenario provides local sensor frames, never actions or routes. Each
accepted cycle is atomically archived under an OS-held advisory state lock.
The lock file remains on disk; ownership is the live OS lock, not its presence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from .rp32 import unpack
from .runtime import _integer, _keys, write_json
from .tomigidt import AgentManifest, Tomigidt


SCENARIO_FORMAT = "tomigidt-simulation-v1"
SESSION_FORMAT = "tomigidt-session-v1"


def _unique_object(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def _read_json(path: str | Path) -> object:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)


@dataclass(frozen=True)
class Scenario:
    manifest: AgentManifest = field(default_factory=AgentManifest)
    hazards: tuple[tuple[str, int], ...] = ()
    changes: tuple[tuple[int, str, int], ...] = ((2, "00", 70),)

    def __post_init__(self) -> None:
        if type(self.manifest) is not AgentManifest:
            raise ValueError("scenario manifest must be an AgentManifest")
        graph = dict(self.manifest.graph)
        if type(self.hazards) is not tuple or any(
            type(item) is not tuple or len(item) != 2 for item in self.hazards
        ):
            raise ValueError("hazards must be an immutable tuple of path/hazard tuples")
        seen_paths = set()
        for path, hazard in self.hazards:
            if type(path) is not str or path not in graph:
                raise ValueError("hazard paths must be declared graph nodes")
            _integer(hazard, 0, 127, "hazard")
            if path in seen_paths:
                raise ValueError("hazards contain duplicate paths")
            seen_paths.add(path)
        if type(self.changes) is not tuple or any(
            type(item) is not tuple or len(item) != 3 for item in self.changes
        ):
            raise ValueError("changes must be an immutable tuple of cycle/path/hazard tuples")
        seen_changes = set()
        for cycle, path, hazard in self.changes:
            _integer(cycle, 1, self.manifest.max_cycles, "change cycle")
            if type(path) is not str or path not in graph:
                raise ValueError("change paths must be declared graph nodes")
            _integer(hazard, 0, 127, "hazard")
            if (cycle, path) in seen_changes:
                raise ValueError("changes contain duplicate cycle/path entries")
            seen_changes.add((cycle, path))
        object.__setattr__(self, "hazards", tuple(sorted(self.hazards)))
        object.__setattr__(self, "changes", tuple(sorted(self.changes)))

    def to_dict(self) -> dict:
        return {
            "format": SCENARIO_FORMAT,
            "agent": self.manifest.to_dict(),
            "hazards": dict(self.hazards),
            "changes": [{"cycle": cycle, "path": path, "hazard": hazard}
                        for cycle, path, hazard in self.changes],
        }

    @classmethod
    def from_dict(cls, value: object) -> Scenario:
        _keys(value, {"format", "agent", "hazards", "changes"}, "Scenario")
        if value["format"] != SCENARIO_FORMAT:
            raise ValueError("Unsupported scenario format")
        if type(value["hazards"]) is not dict or type(value["changes"]) is not list:
            raise ValueError("Scenario hazards and changes require their declared JSON shapes")
        changes = []
        for item in value["changes"]:
            _keys(item, {"cycle", "path", "hazard"}, "Scenario change")
            changes.append((item["cycle"], item["path"], item["hazard"]))
        return cls(AgentManifest.from_dict(value["agent"]),
                   tuple(value["hazards"].items()), tuple(changes))

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        return cls.from_dict(_read_json(path))

    def observe(self, position: str, cycle: int) -> dict[str, int]:
        """Fresh full local frame; changes apply starting at their named cycle."""
        graph = dict(self.manifest.graph)
        if type(position) is not str or position not in graph:
            raise ValueError("observer position must be a declared graph node")
        _integer(cycle, 1, self.manifest.max_cycles, "observation cycle")
        hazards = dict(self.hazards)
        for effective_cycle, path, hazard in self.changes:
            if effective_cycle > cycle:
                break
            hazards[path] = hazard
        return {path: hazards.get(path, 0)
                for path in sorted({position, *graph[position]})}


class AgentBusy(ValueError):
    """Another live holder owns this state's advisory OS lock."""


class StateLock:
    """Hold the canonical state path's sibling ``.lock`` until context exit.

    Windows uses a nonblocking one-byte msvcrt lock; POSIX uses nonblocking
    flock. Neither process age nor lock-file contents determine ownership.
    Abrupt process termination releases the lock through the operating system.
    """

    def __init__(self, path: str | Path):
        self.state_path = Path(path).resolve()
        self.lock_path = Path(str(self.state_path) + ".lock")
        self._stream = None

    def __enter__(self) -> StateLock:
        if self._stream is not None:
            raise AgentBusy("This lock context already owns the state")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise AgentBusy(f"A live runner already owns {self.state_path}") from exc
            # The lock is acquired before initialization. Opening an existing
            # lock never truncates or writes through another process's lock.
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
            self._stream = stream
            return self
        except BaseException:
            stream.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def load_session(path: str | Path, capacity: int = 2) -> tuple[Scenario, Tomigidt]:
    """Read and verify a retained session without changing it or acquiring a lock."""
    value = _read_json(path)
    _keys(value, {"format", "scenario", "agent"}, "Session")
    if value["format"] != SESSION_FORMAT:
        raise ValueError("Unsupported session format")
    scenario = Scenario.from_dict(value["scenario"])
    agent = Tomigidt.from_archive(value["agent"], capacity)
    if agent.manifest != scenario.manifest:
        raise ValueError("Session scenario and agent manifests disagree")
    position = ""
    for event in agent.events:
        recorded = {path: unpack(int(word, 16))[2]
                    for path, word in event["input"].items()}
        if recorded != scenario.observe(position, event["seq"]):
            raise ValueError("Retained sensor input disagrees with the scenario timeline")
        if event["decision"]["kind"] == "MOVE":
            position = event["decision"]["route"][0]
    return scenario, agent


def run_session(
    state_path: str | Path,
    steps: int = 64,
    capacity: int = 2,
    scenario_path: str | Path | None = None,
) -> dict:
    """Create or resume one agent, atomically saving each accepted local cycle.

    A resumed incomplete agent may sample again after a deferred or infeasible
    outcome. Each invocation stops as soon as a new outcome is non-ACTIVE, so
    retries cannot spin through a whole budget without returning control.
    Completed sessions and exhausted cycle budgets remain read-only no-ops.
    """
    _integer(steps, 1, 1_000_000, "steps")
    if type(capacity) is not int or capacity < 1:
        raise ValueError("capacity must be a positive integer (not bool)")
    path = Path(state_path).resolve()
    decisions = []
    with StateLock(path):
        supplied = None if scenario_path is None else Scenario.load(scenario_path)
        restored = path.exists()
        if restored:
            scenario, agent = load_session(path, capacity)
            if supplied is not None and supplied != scenario:
                raise ValueError("The supplied scenario differs from the retained session")
        else:
            scenario = Scenario() if supplied is None else supplied
            agent = Tomigidt(scenario.manifest, capacity)
            write_json(path, {"format": SESSION_FORMAT,
                              "scenario": scenario.to_dict(), "agent": agent.archive()})
        for _ in range(steps):
            if agent.status == "COMPLETE" or agent.cycle >= agent.manifest.max_cycles:
                break
            decision = agent.step(scenario.observe(agent.position, agent.cycle + 1))
            write_json(path, {"format": SESSION_FORMAT,
                              "scenario": scenario.to_dict(), "agent": agent.archive()})
            decisions.append(decision.to_dict())
            if agent.status != "ACTIVE":
                break
        if agent.status == "COMPLETE":
            stop_reason = "COMPLETE"
        elif agent.cycle >= agent.manifest.max_cycles:
            stop_reason = "CYCLE_BUDGET_EXHAUSTED"
        elif agent.status != "ACTIVE":
            stop_reason = agent.status
        else:
            stop_reason = "STEP_BUDGET_EXHAUSTED"
        return {
            "identity": agent.identity,
            "status": agent.status,
            "cycle": agent.cycle,
            "executed_cycles": len(decisions),
            "restored": restored,
            "state": agent.snapshot(),
            "state_path": str(path),
            "capacity_pairs": agent.world.capacity,
            "decisions": decisions,
            "stop_reason": stop_reason,
        }
