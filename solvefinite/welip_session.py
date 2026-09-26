"""One durable forward W owner with controlled, private R reconstruction.

The public protocol exposes current admission context and the five W events.
Its private journal is replayed in full, including cache controls; it is never
served as a historical read. Only a successful save admits a new W operation.
"""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
import json
from pathlib import Path
import re
import sys
from threading import RLock
from typing import TextIO

from .f8 import IndexBinding
from .runtime import _integer, _keys, write_json
from .session import StateLock, _read_json, _reject_constant, _unique_object
from .tomigidt import Tomigidt
from .welip import MAX_REQUEST_CHARS, OPERATIONS, PROTOCOL, WelipConfig, make_record


SESSION_FORMAT = "welip-field-session-v1"
_COMMON = {"protocol", "op", "producer", "producer_epoch", "seq", "clock_epoch",
           "tick16", "agent_cycle", "geometry_epoch"}
_FIELDS = {"IGNITE": {"payload"}, "ADVANCE": {"position", "observations"},
           "RESIZE": {"capacity"}, "INVALIDATE": {"paths", "cause"}, "EMIT": set()}
_BACKWARD = {"READ", "HISTORY", "REPLAY", "REGENERATE"}
_ROW_KEYS = {"request", "records", "agent_pair", "energy", "status", "cache"}


class WelipProtocolError(ValueError):
    """A reported rejection, or a fatal end to the current ownership period."""

    def __init__(self, code: str, message: str, *, fatal: bool = False):
        super().__init__(message)
        self.code, self.fatal = code, fatal


def _serialized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._operation:
            return method(self, *args, **kwargs)
    return locked


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _path_syntax(value):
    if (type(value) is not str or len(value) > 128
            or re.fullmatch(r"k:(0|[1-9][0-9]*):(0|[1-9][0-9]*)", value, re.ASCII) is None):
        raise ValueError("A path must use canonical k:u:v syntax")


def _name(value, label):
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise ValueError(f"{label} must be a nonempty trimmed name of at most 128 characters")


class WelipSession:
    """Own one protected archive until context exit, even after event exhaustion.

    Failed saves or uncertain owner transitions poison this instance. Reopening
    the file reconstructs the durable prefix, including its original FIFO
    history. There is deliberately no public archive/status/owner accessor.
    """

    def __init__(self, state_path: str | Path, config: WelipConfig | None = None, *,
                 backend: str = "cpu", index_binding: IndexBinding | None = None):
        if config is not None and type(config) is not WelipConfig:
            raise ValueError("config must be a WelipConfig")
        if type(backend) is not str or backend not in ("cpu", "gpu"):
            raise ValueError("backend must be cpu or gpu")
        if index_binding is not None and type(index_binding) is not IndexBinding:
            raise ValueError("index_binding must be an IndexBinding")
        self._path = Path(state_path).resolve()
        self._supplied, self._backend, self._index_binding = config, backend, index_binding
        self._operation = RLock()
        self._lock = self._agent = self._config = None
        self._rows = []
        self._failed = self._restored = False

    @property
    def path(self):
        return self._path

    def __enter__(self):
        # OS path ownership precedes the session and agent locks.
        lock = StateLock(self.path)
        lock.__enter__()
        with self._operation:
            self._lock, self._failed, self._rows = lock, False, []
            try:
                self._restored = self.path.exists()
                retained = _read_json(self.path) if self._restored else None
                if self._restored:
                    _keys(retained, {"format", "config", "operations", "agent", "expected"}, "W archive")
                    if retained["format"] != SESSION_FORMAT:
                        raise ValueError("Unsupported W archive format")
                    config = WelipConfig.from_dict(retained["config"])
                    if type(retained["operations"]) is not list or len(retained["operations"]) > config.max_events:
                        raise ValueError("W archive exceeds its finite operation bound")
                    if self._supplied is not None and self._supplied != config:
                        raise ValueError("Supplied W configuration differs from the retained configuration")
                else:
                    config = self._supplied if self._supplied is not None else WelipConfig()
                self._config = config
                options = {"backend": self._backend}
                if self._index_binding is not None:
                    options["index_binding"] = self._index_binding
                self._agent = Tomigidt(config.manifest, config.initial_capacity, **options)
                with self._agent._operation:
                    if not self._restored:
                        write_json(self.path, self._archive([]))
                    else:
                        self._restore(retained)
                return self
            except BaseException:
                self.__exit__(*sys.exc_info())
                raise

    @_serialized
    def __exit__(self, exc_type, exc_value, traceback):
        lock, agent = self._lock, self._agent
        self._lock = self._agent = self._config = None
        self._rows = []
        try:
            if agent is not None:
                agent.close()
        finally:
            if lock is not None:
                lock.__exit__(exc_type, exc_value, traceback)

    def _require_open(self):
        if self._lock is None or self._config is None or self._agent is None:
            raise RuntimeError("W session must be used within its ownership context")
        if self._failed or self._agent.closed:
            raise WelipProtocolError("OWNER_FAILED", "W owner is unavailable; close and reopen", fatal=True)

    def _poison(self, code, message, failure):
        self._failed = True
        try:
            self._agent.close()
        except BaseException:
            pass
        raise WelipProtocolError(code, message, fatal=True) from failure

    def _cache(self, removed=()):
        world = self._agent.world
        return {"capacity": world.capacity, "active_paths": list(world.active_paths),
                "hit_count": world.hit_count, "regeneration_count": world.regeneration_count,
                "evicted_count": len(world.evicted_paths), "removed": list(removed)}

    def _head(self, sequence):
        return {"seq": sequence, **self._config.clock(sequence),
                "agent_cycle": self._agent.cycle, "geometry_epoch": self._agent.geometry_epoch}

    def _context(self):
        self._require_open()
        agent, config, sequence = self._agent, self._config, len(self._rows)
        following = None
        if sequence < config.max_events:
            allowed = ["IGNITE"] if sequence == 0 else [op for op in OPERATIONS if op != "IGNITE"]
            if agent.status == "COMPLETE" or agent.cycle >= config.manifest.max_cycles:
                allowed = [op for op in allowed if op != "ADVANCE"]
            if not agent.world.active_paths:
                allowed = [op for op in allowed if op != "INVALIDATE"]
            following = {**self._head(sequence + 1), "position": agent.position,
                         "visible_paths": list(agent.visible_paths),
                         "active_paths": list(agent.world.active_paths), "capacity": agent.world.capacity,
                         "agent_status": agent.status, "allowed_ops": allowed}
        return {"protocol": PROTOCOL, "producer": config.producer, "producer_epoch": config.producer_epoch,
                "head": self._head(sequence), "next": following}

    @_serialized
    def ready(self):
        self._require_open()
        with self._agent._operation:
            return {**self._context(), "type": "READY", "restored": self._restored}

    @_serialized
    def error(self, failure: WelipProtocolError):
        if type(failure) is not WelipProtocolError:
            raise ValueError("W error responses require a WelipProtocolError")
        if self._config is None:
            raise RuntimeError("No admitted W configuration exists")
        if failure.fatal:
            context = {"protocol": PROTOCOL, "producer": self._config.producer,
                       "producer_epoch": self._config.producer_epoch, "head": None, "next": None}
        else:
            self._require_open()
            with self._agent._operation:
                context = self._context()
        return {**context, "type": "ERROR", "code": failure.code,
                "message": str(failure), "fatal": failure.fatal}

    def _static(self, request):
        if (type(request) is not dict or type(request.get("protocol")) is not str
                or request["protocol"] != PROTOCOL or type(request.get("op")) is not str):
            raise WelipProtocolError("INVALID_REQUEST", "A W request requires the exact protocol and an operation")
        operation = request["op"]
        if operation in _BACKWARD:
            raise WelipProtocolError("BACKWARD_READ", "Historical reads are not W operations")
        if operation not in _FIELDS:
            raise WelipProtocolError("INVALID_REQUEST", "Unknown W operation")
        try:
            _keys(request, _COMMON | _FIELDS[operation], "W request")
            _name(request["producer"], "Producer")
            _integer(request["producer_epoch"], 0, (1 << 32) - 1, "producer_epoch")
            _integer(request["seq"], 1, self._config.max_events + 1, "seq")
            _integer(request["clock_epoch"], 0, (1 << 32) - 1, "clock_epoch")
            _integer(request["tick16"], 0, 65535, "tick16")
            _integer(request["agent_cycle"], 0, self._config.manifest.max_cycles, "agent_cycle")
            binding = self._config.manifest.growth_binding
            _integer(request["geometry_epoch"], 0, 0 if binding is None else binding.max_epochs, "geometry_epoch")
            if operation == "IGNITE":
                payload = request["payload"]
                if (type(payload) is not str or len(payload) > 8192 or len(payload) % 2
                        or any(char not in "0123456789ABCDEF" for char in payload)):
                    raise ValueError("IGNITE requires canonical uppercase hex for 0..4096 bytes")
            elif operation == "ADVANCE":
                _path_syntax(request["position"])
                if type(request["observations"]) is not dict or len(request["observations"]) > 256:
                    raise ValueError("Observations must be a finite path-to-hazard object")
                for path, hazard in request["observations"].items():
                    _path_syntax(path)
                    _integer(hazard, 0, 127, "hazard")
            elif operation == "RESIZE":
                _integer(request["capacity"], 1, 256, "capacity")
            elif operation == "INVALIDATE":
                paths = request["paths"]
                if type(paths) is not list or not 1 <= len(paths) <= 256:
                    raise ValueError("INVALIDATE requires 1..256 active paths")
                for path in paths:
                    _path_syntax(path)
                if paths != sorted(set(paths)):
                    raise ValueError("Invalidation paths must be sorted and unique")
                _name(request["cause"], "Cause")
        except ValueError as exc:
            raise WelipProtocolError("INVALID_REQUEST", str(exc)) from exc
        if (request["producer"], request["producer_epoch"]) != (self._config.producer, self._config.producer_epoch):
            raise WelipProtocolError("SOURCE_MISMATCH", "Producer and namespace differ from the retained configuration")

    def _admit(self, request):
        self._static(request)
        sequence, current = request["seq"], len(self._rows)
        if current and sequence == current:
            if _canonical(request) != _canonical(self._rows[-1]["request"]):
                raise WelipProtocolError("CONFLICT", "The latest sequence names another request")
            return False
        if sequence < current:
            raise WelipProtocolError("STALE_SEQUENCE", "Only the latest admitted sequence can be retried")
        if sequence > current + 1:
            raise WelipProtocolError("SEQUENCE_GAP", "A preceding W operation is missing")
        if current == self._config.max_events:
            raise WelipProtocolError("BUDGET_EXHAUSTED", "The W event budget is exhausted")
        expected = self._config.clock(sequence)
        if any(request[key] != value for key, value in expected.items()):
            raise WelipProtocolError("CLOCK_MISMATCH", "The full W clock differs from this next sequence")
        agent, operation = self._agent, request["op"]
        if (request["agent_cycle"], request["geometry_epoch"]) != (agent.cycle, agent.geometry_epoch):
            raise WelipProtocolError("CONTEXT_MISMATCH", "The current agent cycle or geometry epoch differs")
        if not current and operation != "IGNITE":
            raise WelipProtocolError("NOT_IGNITED", "IGNITE must be the first W operation")
        if current and operation == "IGNITE":
            raise WelipProtocolError("ALREADY_IGNITED", "This W owner is already ignited")
        if operation == "ADVANCE":
            if agent.status == "COMPLETE":
                raise WelipProtocolError("AGENT_COMPLETE", "The declared agent mission is complete")
            if agent.cycle >= agent.manifest.max_cycles:
                raise WelipProtocolError("AGENT_BOUND", "The declared agent cycle bound is exhausted")
            if request["position"] != agent.position:
                raise WelipProtocolError("CONTEXT_MISMATCH", "Observation position differs from the current owner")
            if any(path not in agent.visible_paths for path in request["observations"]):
                raise WelipProtocolError("INVALID_SELECTOR", "Observations contain a nonlocal path")
        elif operation == "INVALIDATE":
            if any(path not in agent.world.active_paths for path in request["paths"]):
                raise WelipProtocolError("INVALID_SELECTOR", "Invalidation selects an inactive current path")
        return True

    def _emit_records(self, request, mutated):
        agent = self._agent
        try:
            phase, words = agent.emit_welip_state(request["tick16"])
        except BaseException as exc:
            pure = False
            if self._backend == "gpu":
                from .field_agent_gpu import MalformedWelipEmissionError
                pure = isinstance(exc, MalformedWelipEmissionError)
            if pure and not mutated and not agent.closed:
                raise WelipProtocolError("MALFORMED_EMISSION", "Complete device output was rejected without state mutation") from exc
            self._poison("OWNER_FAILED", "Owner emission failed; reopen the durable state", exc)
        try:
            _integer(phase, 0, 65535, "emitted phase")
            arguments = {"sequence": request["seq"], "kind": request["op"],
                         "agent_cycle": agent.cycle, "geometry_epoch": agent.geometry_epoch,
                         "pair": agent.agent_pair, "energy": agent.energy}
            records = []
            if request["op"] == "IGNITE":
                records.append(make_record(self._config, **arguments, record_seq=0,
                                           payload=bytes.fromhex(request["payload"])))
            records.append(make_record(self._config, **arguments, record_seq=len(records), state_words=words))
            if any(record["phase16"] != phase for record in records):
                raise ValueError("Emitter phase disagrees with its canonical owner words")
            return records
        except (ValueError, TypeError) as exc:
            if not mutated and not agent.closed:
                raise WelipProtocolError("MALFORMED_EMISSION", "Complete output disagrees with the admitted owner") from exc
            self._poison("OWNER_FAILED", "Output failed after an owner transition; reopen durable state", exc)

    def _execute(self, request):
        operation, agent = request["op"], self._agent
        mutated = operation == "ADVANCE"
        try:
            if mutated:
                agent.step(request["observations"])
            # Cache controls emit before cache mutation. Pure output rejection
            # therefore preserves the whole operation's semantic prestate.
            records = self._emit_records(request, mutated)
            removed = []
            if operation == "RESIZE":
                removed = agent.resize_welip_cache(request["capacity"])
            elif operation == "INVALIDATE":
                removed = agent.invalidate_welip_cache(request["paths"])
            return {"request": request, "records": records, "agent_pair": f"{agent.agent_pair:016X}",
                    "energy": agent.energy, "status": agent.status, "cache": self._cache(removed)}
        except WelipProtocolError:
            raise
        except BaseException as exc:
            self._poison("OWNER_FAILED", "W owner operation failed; reopen the durable state", exc)

    def _archive(self, rows):
        sequence = len(rows)
        return {"format": SESSION_FORMAT, "config": self._config.to_dict(), "operations": rows,
                "agent": self._agent.archive(),
                "expected": {"seq": sequence, **self._config.clock(sequence),
                             "ignited": bool(sequence), "cache": self._cache()}}

    def _restore(self, retained):
        # Controlled R: no save, transport emission or public historical reply.
        for row in retained["operations"]:
            _keys(row, _ROW_KEYS, "Retained W operation")
            request = deepcopy(row["request"])
            if not self._admit(request):
                raise ValueError("A retained W ledger must contain only new ordered operations")
            actual = self._execute(request)
            if _canonical(actual) != _canonical(row):
                raise ValueError("Retained W record, owner state or cache witness disagrees with reconstruction")
            self._rows.append(actual)
        if _canonical(self._archive(self._rows)) != _canonical(retained):
            raise ValueError("Final W archive differs from its complete reconstruction")

    @_serialized
    def handle(self, request: object):
        self._require_open()
        with self._agent._operation:
            try:
                request = deepcopy(request)
            except (TypeError, ValueError, RecursionError) as exc:
                raise WelipProtocolError("INVALID_REQUEST", "Invalid W request structure") from exc
            if not self._admit(request):
                return {**self._context(), "type": "DUPLICATE", "seq": request["seq"]}
            try:
                row = self._execute(request)
                try:
                    rows = [*self._rows, row]
                    archive = self._archive(rows)
                    write_json(self.path, archive)
                except BaseException as exc:
                    self._poison("STORAGE_FAILED", "W save failed or is uncertain; reopen the durable state", exc)
                self._rows = rows
                return {**self._context(), "type": "RESULT", "op": request["op"], "seq": request["seq"],
                        "records": deepcopy(row["records"]), "cache": deepcopy(row["cache"]),
                        "agent_status": row["status"]}
            except WelipProtocolError:
                raise
            except BaseException as exc:
                self._poison("OWNER_FAILED", "W result is uncertain; reopen the durable state", exc)


def serve(state_path: str | Path, *, config_path: str | Path | None = None,
          backend: str = "cpu", index_binding: IndexBinding | None = None,
          input_stream: TextIO | None = None, output_stream: TextIO | None = None):
    """Serve bounded JSONL; acknowledge new results only after atomic save."""
    incoming = sys.stdin if input_stream is None else input_stream
    outgoing = sys.stdout if output_stream is None else output_stream
    config = None if config_path is None else WelipConfig.load(config_path)

    def emit(value):
        outgoing.write(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
        outgoing.flush()

    with WelipSession(state_path, config, backend=backend, index_binding=index_binding) as session:
        emit(session.ready())
        while True:
            line = incoming.readline(MAX_REQUEST_CHARS + 1)
            if not line:
                return
            if len(line) > MAX_REQUEST_CHARS:
                failure = WelipProtocolError("REQUEST_TOO_LARGE", "W request exceeds the finite frame limit", fatal=True)
                emit(session.error(failure))
                raise failure
            try:
                try:
                    request = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                except (ValueError, RecursionError) as exc:
                    raise WelipProtocolError("INVALID_REQUEST", "Malformed JSON request") from exc
                response = session.handle(request)
            except WelipProtocolError as exc:
                emit(session.error(exc))
                if exc.fatal:
                    raise
            else:
                emit(response)
