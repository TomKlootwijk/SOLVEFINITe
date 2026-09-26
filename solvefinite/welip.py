"""W1, W2 and W5: finite W clock, carrier and source-bound LUS records.

These codecs do not own a session, advance an agent or authenticate an issuer.
A legal mirrored carrier can name a different owner; admission separately
compares the complete supplied pair and energy with the actual current owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .field_agent import (FieldAgentManifest, FIELD_POLICY, HADAMARD_POLICY,
                          GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY, MAX_ENERGY)
from .rp32 import unpack, unpair
from .runtime import _integer, _keys


PROTOCOL = "welip-field-agent-v1"
CONFIG_FORMAT = "welip-field-config-v1"
PROTOCOL_V2 = "welip-field-agent-v2"
CONFIG_FORMAT_V2 = "welip-field-config-v2"
# The enclosing immutable configuration supplies the geometry namespace. The
# unchanged carrier/LUS words cannot identify it without that context.
_VERSION_BINDINGS = {
    CONFIG_FORMAT: (PROTOCOL, "welip-field-session-v1",
                    (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY)),
    CONFIG_FORMAT_V2: (PROTOCOL_V2, "welip-field-session-v2", (TAPER_POLICY,)),
}
WORD_PROFILE = "welip-16-16-32-v1"
STATE_PROFILE = "RP32-relational-sdf-v2"
LUS_FORMAT = "welip-lus-v1"
OPERATIONS = ("IGNITE", "ADVANCE", "RESIZE", "INVALIDATE", "EMIT")
MAX_REQUEST_CHARS = 65_536
MAX_CLOCK = (1 << 48) - 1
MAX_EPOCH = (1 << 32) - 1
MAX_EVENTS = 1_000_000
MAX_PAYLOAD_BYTES = 4096
_CONFIG_KEYS = {"format", "agent", "producer", "producer_epoch", "clock_origin", "max_events", "initial_capacity"}
_RECORD_KEYS = {"format", "word_profile", "payload_profile", "baseline_id", "producer", "producer_epoch",
                "clock_epoch", "tick16", "phase16", "operation_seq", "record_seq", "kind", "agent_cycle",
                "geometry_epoch", "energy", "byte_length", "fragment_count", "words", "status"}


def _literal(value: object, expected: str, label: str) -> None:
    if type(value) is not str or value != expected:
        raise ValueError(f"Unsupported {label}")


def _config(value: object) -> None:
    if type(value) is not WelipConfig:
        raise ValueError("config must be a WelipConfig")


def _version(value: object) -> tuple[str, str, tuple[str, ...]]:
    if type(value) is not str or value not in _VERSION_BINDINGS:
        raise ValueError("Unsupported W configuration format")
    return _VERSION_BINDINGS[value]


@dataclass(frozen=True, slots=True)
class WelipConfig:
    """One immutable namespace, initial field agent and finite clock horizon."""

    manifest: FieldAgentManifest = field(default_factory=lambda: FieldAgentManifest(policy=ORGANOGRAM_POLICY))
    producer: str = "sensor"
    producer_epoch: int = 0
    clock_origin: int = 0
    max_events: int = MAX_EVENTS
    initial_capacity: int = 2
    version: str = CONFIG_FORMAT

    def __post_init__(self) -> None:
        _, _, policies = _version(self.version)
        if type(self.manifest) is not FieldAgentManifest:
            raise ValueError("W manifest must be a FieldAgentManifest")
        if self.manifest.policy not in policies:
            raise ValueError("Agent policy is outside this W configuration version")
        if (type(self.producer) is not str or not self.producer or self.producer != self.producer.strip()
                or len(self.producer) > 128):
            raise ValueError("producer must be a trimmed nonempty name of at most 128 characters")
        _integer(self.producer_epoch, 0, MAX_EPOCH, "producer_epoch")
        _integer(self.clock_origin, 0, MAX_CLOCK, "clock_origin")
        _integer(self.max_events, 1, MAX_EVENTS, "max_events")
        _integer(self.initial_capacity, 1, 256, "initial_capacity")
        if self.clock_origin + self.max_events > MAX_CLOCK:
            raise ValueError("clock_origin + max_events exceeds the unsigned 48-bit clock horizon")

    def to_dict(self) -> dict:
        return {"format": self.version, "agent": self.manifest.to_dict(), "producer": self.producer,
                "producer_epoch": self.producer_epoch, "clock_origin": self.clock_origin,
                "max_events": self.max_events, "initial_capacity": self.initial_capacity}

    @classmethod
    def from_dict(cls, value: object) -> WelipConfig:
        _keys(value, _CONFIG_KEYS, "W configuration")
        _version(value["format"])
        return cls(manifest=FieldAgentManifest.from_dict(value["agent"]),
                   version=value["format"],
                   **{key: value[key] for key in _CONFIG_KEYS - {"format", "agent"}})

    @property
    def protocol(self) -> str:
        return _version(self.version)[0]

    @property
    def session_format(self) -> str:
        return _version(self.version)[1]

    @classmethod
    def load(cls, path: str | Path) -> WelipConfig:
        # Reuse the repository's duplicate-key and nonfinite-number rejection.
        from .session import _read_json
        return cls.from_dict(_read_json(path))

    def clock(self, seq: int) -> dict[str, int]:
        """Split an admitted W time; never wrap or calculate an exhausted next."""
        _integer(seq, 0, self.max_events, "operation sequence")
        total = self.clock_origin + seq
        return {"clock_epoch": total >> 16, "tick16": total & 65535}


def _word(value: object) -> int:
    if (type(value) is not str or len(value) != 16
            or any(character not in "0123456789ABCDEF" for character in value)):
        raise ValueError("W carrier words require 16 uppercase hexadecimal digits")
    return int(value, 16)


def _state(pair: int) -> tuple[int, int]:
    _integer(pair, 0, (1 << 64) - 1, "owner pair")
    phase, node, scalar, metadata = unpack(unpair(pair)[0])
    if metadata not in (1, 17, 6, 22):
        raise ValueError("Owner state requires STEP or EMIT without reserved metadata")
    if scalar == -128:
        raise ValueError("Owner state field must be an exact scalar in [-127, 127]")
    intrinsic = (-phase if metadata & 16 else phase) % 256
    return intrinsic << 8, node


def encode_bytes(payload: bytes, tick16: int, phase16: int) -> list[str]:
    """Encode ordered little-endian fragments; padding adds no payload bytes."""
    if type(payload) is not bytes or len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload must be bytes with length 0..4096")
    _integer(tick16, 0, 65535, "tick16")
    _integer(phase16, 0, 65535, "phase16")
    header = (tick16 << 48) | (phase16 << 32)
    return [f"{header | int.from_bytes(payload[offset:offset + 4], 'little'):016X}"
            for offset in range(0, len(payload), 4)]


def decode_bytes(words: list[str], byte_length: int, fragment_count: int, tick16: int, phase16: int) -> bytes:
    """Reject malformed headers, ordering shape, fragment count and padding."""
    _integer(byte_length, 0, MAX_PAYLOAD_BYTES, "byte_length")
    _integer(fragment_count, 0, MAX_PAYLOAD_BYTES // 4, "fragment_count")
    _integer(tick16, 0, 65535, "tick16")
    _integer(phase16, 0, 65535, "phase16")
    if type(words) is not list or len(words) != fragment_count or fragment_count != (byte_length + 3) // 4:
        raise ValueError("words must be an ordered JSON array with the exact fragment count")
    payload = bytearray()
    for encoded in words:
        word = _word(encoded)
        if word >> 48 != tick16 or ((word >> 32) & 65535) != phase16:
            raise ValueError("W carrier header disagrees with tick16 or phase16")
        payload.extend((word & MAX_EPOCH).to_bytes(4, "little"))
    if any(payload[byte_length:]):
        raise ValueError("W carrier has nonzero final padding")
    return bytes(payload[:byte_length])


def encode_state(pair: int, tick16: int) -> tuple[int, list[str]]:
    """CPU state producer; a GPU owner must instead supply device state words."""
    phase16, _ = _state(pair)
    return phase16, encode_bytes(pair.to_bytes(8, "little"), tick16, phase16)


def decode_state(words: list[str], tick16: int, phase16: int) -> int:
    """Check a representation without asserting it is the actual owned pair."""
    payload = decode_bytes(words, 8, 2, tick16, phase16)
    if phase16 & 255:
        raise ValueError("State phase16 must preserve the owner's eight-bit phase resolution")
    pair = int.from_bytes(payload, "little")
    actual_phase, _ = _state(pair)
    if phase16 != actual_phase:
        raise ValueError("State phase16 disagrees with its intrinsic RP32 phase")
    return pair


def _node_bound(config: WelipConfig, geometry_epoch: int) -> int:
    manifest = config.manifest
    bound = manifest.growth_binding.max_epochs if manifest.growth_binding is not None else 0
    _integer(geometry_epoch, 0, bound, "geometry_epoch")
    count = manifest.world.width * manifest.world.height
    return count * (4 ** geometry_epoch) if manifest.policy == GROWTH_POLICY else count


def validate_record(record: object, config: WelipConfig, *, expected_pair: int | None = None,
                    expected_energy: int | None = None) -> None:
    """Validate exact LUS syntax/identity and optional actual-owner equality.

    Context ranges and configured W time are checked here. The owning session
    additionally verifies the admitted current cycle/generation and operation.
    No field compiler or CPU state producer is used by this checker.
    The caller retains the exact enclosing config/protocol namespace: a bare
    record's baseline label and carrier words do not authenticate that context.
    """
    _config(config)
    _keys(record, _RECORD_KEYS, "LUS record")
    for key, expected in (("format", LUS_FORMAT), ("word_profile", WORD_PROFILE),
                          ("baseline_id", config.manifest.world.baseline_id),
                          ("producer", config.producer), ("status", "ADMITTED")):
        _literal(record[key], expected, key)
    _integer(record["producer_epoch"], 0, MAX_EPOCH, "producer_epoch")
    if record["producer_epoch"] != config.producer_epoch:
        raise ValueError("LUS producer_epoch differs from the configured namespace")
    _integer(record["operation_seq"], 1, config.max_events, "operation_seq")
    _integer(record["record_seq"], 0, 1, "record_seq")
    _integer(record["clock_epoch"], 0, MAX_EPOCH, "clock_epoch")
    _integer(record["tick16"], 0, 65535, "tick16")
    _integer(record["phase16"], 0, 65535, "phase16")
    _integer(record["agent_cycle"], 0, config.manifest.max_cycles, "agent_cycle")
    _integer(record["energy"], 0, MAX_ENERGY, "energy")
    count = _node_bound(config, record["geometry_epoch"])
    if any(record[key] != value for key, value in config.clock(record["operation_seq"]).items()):
        raise ValueError("LUS clock differs from the original configured W sequence")
    if type(record["kind"]) is not str or record["kind"] not in OPERATIONS:
        raise ValueError("LUS kind must name an admitted W operation")
    raw = record["kind"] == "IGNITE" and record["record_seq"] == 0
    _literal(record["payload_profile"], "bytes-v1" if raw else STATE_PROFILE, "LUS payload profile")
    if record["kind"] == "IGNITE":
        if record["operation_seq"] != 1 or record["agent_cycle"] != 0 or record["geometry_epoch"] != 0:
            raise ValueError("IGNITE records require the first W sequence and initial agent context")
    elif record["record_seq"] != 0 or record["operation_seq"] == 1:
        raise ValueError("Only IGNITE uses sequence one or a second record")
    if record["phase16"] & 255:
        raise ValueError("LUS phase16 must preserve actual owner's eight-bit phase resolution")
    decode_bytes(record["words"], record["byte_length"], record["fragment_count"], record["tick16"], record["phase16"])
    decoded_pair = None
    if not raw:
        if record["byte_length"] != 8 or record["fragment_count"] != 2:
            raise ValueError("Owner state requires eight bytes and two fragments")
        decoded_pair = decode_state(record["words"], record["tick16"], record["phase16"])
        if _state(decoded_pair)[1] >= count:
            raise ValueError("Owner state selector exceeds this geometry's node count")
    if expected_pair is not None:
        actual_phase, node = _state(expected_pair)
        if node >= count or record["phase16"] != actual_phase:
            raise ValueError("LUS header or selector differs from the actual owner")
        if decoded_pair is not None and decoded_pair != expected_pair:
            raise ValueError("LUS payload differs from the actual complete owner pair")
    if expected_energy is not None:
        _integer(expected_energy, 0, MAX_ENERGY, "expected_energy")
        if record["energy"] != expected_energy:
            raise ValueError("LUS energy differs from the actual owner")


def make_record(config: WelipConfig, *, sequence: int, record_seq: int, kind: str,
                agent_cycle: int, geometry_epoch: int, pair: int, energy: int,
                payload: bytes | None = None, state_words: list[str] | None = None) -> dict:
    """Wrap CPU or independently supplied device words in exact LUS metadata.

    Supplied device words are checked against the actual pair and retained
    verbatim. They are never regenerated or replaced through encode_state.
    Raw IGNITE bytes use the same actual intrinsic phase as the state record.
    """
    _config(config)
    _integer(sequence, 1, config.max_events, "operation sequence")
    time = config.clock(sequence)
    phase16, _ = _state(pair)
    if state_words is not None:
        if decode_state(state_words, time["tick16"], phase16) != pair:
            raise ValueError("Supplied state words differ from the actual complete owner pair")
    if payload is not None:
        words = encode_bytes(payload, time["tick16"], phase16)
        profile, length = "bytes-v1", len(payload)
    else:
        words = encode_state(pair, time["tick16"])[1] if state_words is None else list(state_words)
        profile, length = STATE_PROFILE, 8
    result = {"format": LUS_FORMAT, "word_profile": WORD_PROFILE, "payload_profile": profile,
              "baseline_id": config.manifest.world.baseline_id, "producer": config.producer,
              "producer_epoch": config.producer_epoch, **time, "phase16": phase16,
              "operation_seq": sequence, "record_seq": record_seq, "kind": kind,
              "agent_cycle": agent_cycle, "geometry_epoch": geometry_epoch, "energy": energy,
              "byte_length": length, "fragment_count": len(words), "words": words, "status": "ADMITTED"}
    validate_record(result, config, expected_pair=pair, expected_energy=energy)
    return result
