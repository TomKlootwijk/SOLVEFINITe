"""One durable TOMIGIDt owner accepting new observations over a JSONL channel.

The producer supplies sensor data, never a route or action. Sequence numbers
identify admitted cycles so a retry can recover a committed result without
executing it twice. Emitted decisions describe the existing simulated action
profile; this module does not perform or acknowledge physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
import json
from pathlib import Path
import sys
from threading import RLock
from typing import TextIO

from .rp32 import unpack
from .runtime import _integer, _keys, write_json
from .session import AgentBusy, StateLock, _read_json, _reject_constant, _unique_object
from .tomigidt import AgentManifest, Tomigidt


PROTOCOL = "tomigidt-live-v1"
CONFIG_FORMAT = "tomigidt-live-config-v1"
LIVE_FORMAT = "tomigidt-live-session-v1"
MAX_REQUEST_CHARS = 65_536
MAX_EPOCH = (1 << 63) - 1


@dataclass(frozen=True)
class LiveConfig:
    manifest: AgentManifest = field(default_factory=AgentManifest)
    producer: str = "sensor"
    epoch: int = 0

    def __post_init__(self) -> None:
        if type(self.manifest) is not AgentManifest:
            raise ValueError("Live manifest must be an AgentManifest")
        if type(self.producer) is not str or not self.producer.strip() or len(self.producer) > 128:
            raise ValueError("Producer must be a nonempty name of at most 128 characters")
        _integer(self.epoch, 0, MAX_EPOCH, "epoch")

    def to_dict(self) -> dict:
        return {"format": CONFIG_FORMAT, "agent": self.manifest.to_dict(),
                "producer": self.producer, "epoch": self.epoch}

    @classmethod
    def from_dict(cls, value: object) -> LiveConfig:
        _keys(value, {"format", "agent", "producer", "epoch"}, "Live configuration")
        if value["format"] != CONFIG_FORMAT:
            raise ValueError("Unsupported live configuration format")
        return cls(AgentManifest.from_dict(value["agent"]), value["producer"], value["epoch"])

    @classmethod
    def load(cls, path: str | Path) -> LiveConfig:
        return cls.from_dict(_read_json(path))


def load_live(path: str | Path, capacity: int = 2, *,
              backend: str = "cpu") -> tuple[LiveConfig, Tomigidt]:
    """Replay without a lock; the caller owns and closes the returned agent."""
    value = _read_json(path)
    _keys(value, {"format", "config", "agent"}, "Live session")
    if value["format"] != LIVE_FORMAT:
        raise ValueError("Unsupported live session format")
    config = LiveConfig.from_dict(value["config"])
    agent = Tomigidt.from_archive(value["agent"], capacity, backend=backend)
    if agent.manifest != config.manifest:
        agent.close()
        raise ValueError("Live configuration and retained agent manifests disagree")
    return config, agent


class LiveProtocolError(ValueError):
    """A rejected request; no new agent cycle has been admitted."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _request_keys(value: object, expected: set[str]) -> None:
    try:
        _keys(value, expected, "Live request")
    except ValueError as exc:
        raise LiveProtocolError("INVALID_REQUEST", str(exc)) from exc


def _serialized(method):
    """Keep embedded callers inside the same admission/commit boundary."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._operation:
            return method(self, *args, **kwargs)
    return call


class LiveSession:
    """Hold one live state lock until EOF or context exit, including while waiting.

    A storage failure is fatal to this owner: no result is acknowledged, and
    further access is refused until the context closes and a new owner replays
    the durable archive. This also handles a failure after atomic replacement:
    the next owner inspects what actually committed before admitting new work.
    """

    def __init__(self, state_path: str | Path, capacity: int = 2,
                 config: LiveConfig | None = None, *, backend: str = "cpu"):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer (not bool)")
        if config is not None and type(config) is not LiveConfig:
            raise ValueError("config must be a LiveConfig")
        if type(backend) is not str or backend not in ("cpu", "gpu"):
            raise ValueError("backend must be cpu or gpu")
        self._path = Path(state_path).resolve()
        self._capacity = capacity
        self._backend = backend
        self._supplied = config
        self._lock: StateLock | None = None
        self._agent: Tomigidt | None = None
        self._config: LiveConfig | None = None
        self._positions: list[str] = []
        self._restored = False
        self._failed = False
        self._operation = RLock()

    @property
    def path(self) -> Path:
        """The fixed archive path protected by this owner's lock."""
        return self._path

    @_serialized
    def __enter__(self) -> LiveSession:
        if self._lock is not None:
            raise AgentBusy("This live session already owns the state")
        lock = StateLock(self.path)
        lock.__enter__()
        agent = None
        try:
            restored = self.path.exists()
            if restored:
                config, agent = load_live(self.path, self._capacity, backend=self._backend)
                if self._supplied is not None and self._supplied != config:
                    raise ValueError("The supplied live configuration differs from the retained session")
            else:
                config = LiveConfig() if self._supplied is None else self._supplied
                agent = Tomigidt(config.manifest, self._capacity, backend=self._backend)
                write_json(self.path, {"format": LIVE_FORMAT, "config": config.to_dict(),
                                       "agent": agent.archive()})
            position = ""
            positions = []
            for event in agent.events:
                positions.append(position)
                if event["decision"]["kind"] == "MOVE":
                    position = event["decision"]["route"][0]
            self._config, self._agent = config, agent
            self._positions = positions
            self._restored = restored
            self._failed = False
            self._lock = lock
            return self
        except BaseException:
            failure = sys.exc_info()
            try:
                if agent is not None:
                    agent.close()
            finally:
                lock.__exit__(*failure)
            raise

    @_serialized
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        lock = self._lock
        agent = self._agent
        self._lock = None
        self._agent = None
        self._config = None
        self._positions = []
        try:
            if agent is not None:
                agent.close()
        finally:
            if lock is not None:
                lock.__exit__(exc_type, exc_value, traceback)

    def _require_open(self) -> None:
        if self._lock is None or self._agent is None or self._config is None:
            raise RuntimeError("Live session must be used inside its ownership context")
        if self._failed:
            raise RuntimeError("Live session storage failed; close and reopen to recover durable state")

    def _context(self) -> dict:
        self._require_open()
        agent, config = self._agent, self._config
        terminal = agent.status == "COMPLETE" or agent.cycle >= config.manifest.max_cycles
        return {
            "protocol": PROTOCOL, "producer": config.producer, "epoch": config.epoch,
            "state": agent.snapshot(),
            "next": None if terminal else {"seq": agent.cycle + 1, "position": agent.position,
                                           "paths": list(agent.visible_paths)},
        }

    @_serialized
    def ready(self) -> dict:
        return {**self._context(), "type": "ready", "restored": self._restored}

    @_serialized
    def error(self, failure: LiveProtocolError) -> dict:
        return {**self._context(), "type": "error", "code": failure.code, "message": str(failure)}

    @_serialized
    def handle(self, request: object) -> dict:
        self._require_open()
        if type(request) is not dict:
            raise LiveProtocolError("INVALID_REQUEST", "Live request must be an object")
        if request.get("protocol") != PROTOCOL:
            raise LiveProtocolError("PROTOCOL", "Unsupported live protocol")
        if request.get("type") == "status":
            _request_keys(request, {"protocol", "type"})
            return {**self._context(), "type": "status"}
        if request.get("type") != "observe":
            raise LiveProtocolError("INVALID_REQUEST", "Live request type must be observe or status")
        _request_keys(request, {"protocol", "type", "producer", "epoch", "seq",
                                "position", "observations"})
        agent, config = self._agent, self._config
        if (type(request["producer"]) is not str or request["producer"] != config.producer
                or type(request["epoch"]) is not int or request["epoch"] != config.epoch):
            raise LiveProtocolError("SOURCE", "Producer and epoch must match the retained live configuration")
        try:
            seq = _integer(request["seq"], 1, config.manifest.max_cycles, "seq")
        except ValueError as exc:
            raise LiveProtocolError("SEQUENCE", str(exc)) from exc
        if seq > agent.cycle + 1:
            raise LiveProtocolError("OUT_OF_ORDER", "A preceding observation sequence is missing")
        duplicate = seq <= agent.cycle
        position = self._positions[seq - 1] if duplicate else agent.position
        if type(request["position"]) is not str or request["position"] != position:
            raise LiveProtocolError("POSITION", "Observation position differs from the original cycle context")
        observations = request["observations"]
        visible = {position, *dict(config.manifest.graph)[position]}
        if (type(observations) is not dict
                or any(type(path) is not str or path not in visible for path in observations)):
            raise LiveProtocolError("OBSERVATIONS", "Observations must be an object containing only local paths")
        try:
            for hazard in observations.values():
                _integer(hazard, 0, 127, "hazard")
        except ValueError as exc:
            raise LiveProtocolError("OBSERVATIONS", str(exc)) from exc
        if duplicate:
            event = agent.recorded_event(seq)
            recorded = {path: unpack(int(word, 16))[2] for path, word in event["input"].items()}
            if observations != recorded:
                raise LiveProtocolError("CONFLICT", "This sequence already names a different admitted observation")
        else:
            if agent.status == "COMPLETE" or agent.cycle >= config.manifest.max_cycles:
                raise LiveProtocolError("TERMINAL", "The declared mission or cycle budget is complete")
            # All admission checks precede step. The existing policy stages
            # its forecast before mutating its simulated state.
            agent.step(observations)
            try:
                write_json(self.path, {"format": LIVE_FORMAT, "config": config.to_dict(),
                                       "agent": agent.archive()})
            except BaseException:
                self._failed = True
                raise
            self._positions.append(position)
            event = agent.recorded_event(seq)
        return {**self._context(), "type": "result", "duplicate": duplicate, "event": event}


def serve(state_path: str | Path, *, capacity: int = 2,
          backend: str = "cpu",
          config_path: str | Path | None = None,
          input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
    """Serve newline-delimited requests, flushing only durable result replies.

    Protocol errors produce a response and leave the owner available. Oversized
    frames, stream failures and storage failures terminate the channel. EOF
    releases ownership. A complete mission stays available for result retries
    and status requests until EOF; it admits no additional cycles.
    """
    incoming = sys.stdin if input_stream is None else input_stream
    outgoing = sys.stdout if output_stream is None else output_stream
    config = None if config_path is None else LiveConfig.load(config_path)

    def emit(value: dict) -> None:
        outgoing.write(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
        outgoing.flush()

    with LiveSession(state_path, capacity, config, backend=backend) as session:
        emit(session.ready())
        while True:
            line = incoming.readline(MAX_REQUEST_CHARS + 1)
            if not line:
                return
            if len(line) > MAX_REQUEST_CHARS:
                raise ValueError(f"Live request exceeds the {MAX_REQUEST_CHARS}-character frame limit")
            try:
                try:
                    request = json.loads(line, object_pairs_hook=_unique_object,
                                         parse_constant=_reject_constant)
                except (ValueError, RecursionError) as exc:
                    raise LiveProtocolError("INVALID_JSON", "Invalid JSON request: " + str(exc)) from exc
                response = session.handle(request)
            except LiveProtocolError as exc:
                response = session.error(exc)
            emit(response)
