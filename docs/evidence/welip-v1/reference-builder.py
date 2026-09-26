"""Independent W1--W8 clock, carrier, identity and lifecycle arithmetic.

Imports no solvefinite module. Owner transitions come from the pinned,
preimplementation independent OG reference; this file independently models
the W ledger, fragment encoding, original-clock identities and pair FIFO.
It does not manufacture a new canonical Tomigidt archive or hardware result.
"""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OG_PATH = ROOT / "docs/evidence/organogram-v1/formal-reference.json"
OG_BUILDER = OG_PATH.with_name("reference-builder.py")
GD_BUILDER = ROOT / "docs/evidence/growth-v1/reference-builder.py"
OG_SHA = "21df28af479fbae2c70a7390a71b0baf9322fcbf38de3ce9db8ff5e5f3b4a6fe"
OG_BUILDER_SHA = "987c0adced856312fc3581d921ec1badaec236c0230c63f25ef6f024959f32d8"
GD_BUILDER_SHA = "b9be4e73dcfd81eb3daa7507f6a991208c1ba82abc3c009d4a2193cda75c1d7d"
HISTORICAL_ARCHIVE_SHA = "e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df"
MAX48, MAX32 = (1 << 48) - 1, (1 << 32) - 1
PROTOCOL = "welip-field-agent-v1"
WORD_PROFILE = "welip-16-16-32-v1"
STATE_PROFILE = "RP32-relational-sdf-v2"
PRODUCER = "welip-reference"
PRODUCER_EPOCH = 7
ORIGIN, EVENT_BOUND, INITIAL_CAPACITY = 65530, 64, 3
PAYLOAD = "DEADBEEF0123456789"
OPERATIONS = ("IGNITE", "ADVANCE", "RESIZE", "INVALIDATE", "EMIT")
SCHEDULE = (("IGNITE", None), ("ADVANCE", 1), ("EMIT", None), ("RESIZE", 1),
            ("INVALIDATE", None), ("ADVANCE", 2), ("ADVANCE", 3), ("ADVANCE", 4),
            ("EMIT", None), ("ADVANCE", 5), ("RESIZE", 4), ("ADVANCE", 6),
            ("ADVANCE", 7), ("INVALIDATE", None), ("ADVANCE", 8), ("ADVANCE", 9), ("EMIT", None))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def lf_digest(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("strict integer range")
    return value


def clock(origin, maximum, sequence):
    integer(origin, 0, MAX48)
    integer(maximum, 1, 1_000_000)
    if origin + maximum > MAX48:
        raise ValueError("configuration clock horizon overflow")
    integer(sequence, 0, maximum)
    total = origin + sequence
    return {"clock_epoch": total >> 16, "tick16": total & 65535}


def unpack(word):
    integer(word, 0, MAX32)
    if word.bit_count() % 2:
        raise ValueError("RP32 parity")
    signed = (word >> 16) & 255
    return word & 255, (word >> 8) & 255, signed - 256 if signed >= 128 else signed, (word >> 24) & 127


def pack(phase, node, field, metadata):
    raw = phase | (node << 8) | ((field & 255) << 16) | (metadata << 24)
    return raw | ((raw.bit_count() & 1) << 31)


def hex_word(value, width):
    if type(value) is not str or len(value) != width or any(c not in "0123456789ABCDEF" for c in value):
        raise ValueError("canonical uppercase hexadecimal word")
    return int(value, 16)


def pair_state(encoded):
    value = hex_word(encoded, 16)
    left, right = value & MAX32, value >> 32
    phase, node, field, metadata = unpack(left)
    if unpack(right) != ((-phase) % 256, node, field, metadata ^ 16):
        raise ValueError("RP32 full mirror")
    if metadata not in (1, 17, 6, 22):
        raise ValueError("owner STEP or EMIT metadata")
    if not -127 <= field <= 127:
        raise ValueError("exact field range")
    return {"phase": phase, "node": node, "field": field, "orientation": (metadata >> 4) & 1,
            "intrinsic_phase": (-phase if metadata & 16 else phase) % 256,
            "left": left, "right": right}


def encode_bytes(payload, tick16, phase16):
    if type(payload) is not bytes or len(payload) > 4096:
        raise ValueError("finite bytes payload")
    integer(tick16, 0, 65535)
    integer(phase16, 0, 65535)
    header = (tick16 << 48) | (phase16 << 32)
    return [f"{header | int.from_bytes(payload[offset:offset + 4].ljust(4, bytes(1)), 'little'):016X}"
            for offset in range(0, len(payload), 4)]


def decode_bytes(words, byte_length, fragment_count, tick16, phase16):
    integer(byte_length, 0, 4096)
    integer(fragment_count, 0, 1024)
    integer(tick16, 0, 65535)
    integer(phase16, 0, 65535)
    if type(words) is not list or len(words) != fragment_count or fragment_count != (byte_length + 3) // 4:
        raise ValueError("ordered fragment count")
    padded = bytearray()
    for encoded in words:
        word = hex_word(encoded, 16)
        if word >> 48 != tick16 or ((word >> 32) & 65535) != phase16:
            raise ValueError("clock or phase header")
        padded.extend((word & MAX32).to_bytes(4, "little"))
    if any(padded[byte_length:]):
        raise ValueError("nonzero final padding")
    return bytes(padded[:byte_length])


def state_words(encoded_pair, tick16):
    decoded = pair_state(encoded_pair)
    phase16 = decoded["intrinsic_phase"] << 8
    payload = hex_word(encoded_pair, 16).to_bytes(8, "little")
    return phase16, encode_bytes(payload, tick16, phase16)


def decode_state(words, tick16, phase16):
    payload = decode_bytes(words, 8, 2, tick16, phase16)
    if phase16 & 255:
        raise ValueError("state phase resolution")
    encoded = f"{int.from_bytes(payload, 'little'):016X}"
    decoded = pair_state(encoded)
    if phase16 != decoded["intrinsic_phase"] << 8:
        raise ValueError("state phase differs from payload")
    return encoded


def visible(path):
    _, su, sv = path.split(":")
    u, v = int(su), int(sv)
    def canonical_node(a, b):
        crossings, column = divmod(a, 4)
        return f"k:{column}:{(-b if crossings % 2 else b) % 5}"
    return sorted({path, canonical_node(u + 1, v), canonical_node(u - 1, v),
                   canonical_node(u, v + 1), canonical_node(u, v - 1)})


class Fifo:
    def __init__(self, capacity):
        self.capacity = capacity
        self.active, self.evicted = [], []
        self.hits = self.regenerations = 0

    def get(self, path):
        if path in self.active:
            self.hits += 1
            return
        if path in self.evicted:
            self.regenerations += 1
        self.active.append(path)
        while len(self.active) > self.capacity:
            self.evicted.append(self.active.pop(0))

    def resize(self, capacity):
        self.capacity = capacity
        removed = []
        while len(self.active) > capacity:
            removed.append(self.active.pop(0))
        self.evicted.extend(removed)
        return removed

    def invalidate(self, paths):
        assert paths == sorted(set(paths)) and all(path in self.active for path in paths)
        removed = [path for path in self.active if path in paths]
        self.active = [path for path in self.active if path not in paths]
        self.evicted.extend(removed)
        return removed

    def witness(self, removed=()):
        return {"capacity": self.capacity, "active_paths": list(self.active), "hit_count": self.hits,
                "regeneration_count": self.regenerations, "evicted_count": len(self.evicted), "removed": list(removed)}


def config_for(mission):
    initial = mission["initial"]
    agent = {"identity": "TOMIGIDt", "target": "k:3:2",
             "world": {"format": "klein-ball-world-v1", **mission["initial_recipe"], "baseline_id": "klein-field-world-v1"},
             "initial_node": initial["path"], "initial_phase": initial["phase"],
             "initial_orientation": initial["orientation"], "initial_energy": initial["energy"],
             "repair_cost": 5, "max_search_expansions": 4096, "max_hops": 255, "max_cycles": 10000,
             "policy": "tomigidt-field-organogram-plan-act-v1", "word_profile": STATE_PROFILE,
             "perspective": "local-observation-v1",
             "routing": {"format": "hadamard-klein-routing-v1", "gains": [[1, 1], [-1, 1], [-1, -1], [1, -1]]},
             "organogram": deepcopy(mission["binding"])}
    return {"format": "welip-field-config-v1", "agent": agent, "producer": PRODUCER,
            "producer_epoch": PRODUCER_EPOCH, "clock_origin": ORIGIN, "max_events": EVENT_BOUND,
            "initial_capacity": INITIAL_CAPACITY}


def cursor(sequence, cycle, epoch, state, status, fifo, ignited):
    head = {"seq": sequence, **clock(ORIGIN, EVENT_BOUND, sequence), "agent_cycle": cycle, "geometry_epoch": epoch}
    following = None
    if sequence < EVENT_BOUND:
        allowed = ["IGNITE"] if not ignited else [op for op in OPERATIONS if op != "IGNITE"]
        if status == "COMPLETE" or cycle >= 10000:
            allowed = [op for op in allowed if op != "ADVANCE"]
        if not fifo.active:
            allowed = [op for op in allowed if op != "INVALIDATE"]
        following = {"seq": sequence + 1, **clock(ORIGIN, EVENT_BOUND, sequence + 1),
                     "agent_cycle": cycle, "geometry_epoch": epoch, "position": state["path"],
                     "visible_paths": visible(state["path"]), "active_paths": list(fifo.active),
                     "capacity": fifo.capacity, "agent_status": status, "allowed_ops": allowed}
    return {"protocol": PROTOCOL, "producer": PRODUCER, "producer_epoch": PRODUCER_EPOCH,
            "head": head, "next": following}


def record(config, sequence, ordinal, kind, cycle, epoch, state, payload=None):
    time = clock(config["clock_origin"], config["max_events"], sequence)
    phase16, words = state_words(state["pair"], time["tick16"])
    profile, length = STATE_PROFILE, 8
    if payload is not None:
        profile, length = "bytes-v1", len(payload)
        words = encode_bytes(payload, time["tick16"], phase16)
    result = {"format": "welip-lus-v1", "word_profile": WORD_PROFILE, "payload_profile": profile,
              "baseline_id": config["agent"]["world"]["baseline_id"], "producer": config["producer"],
              "producer_epoch": config["producer_epoch"], **time, "phase16": phase16,
              "operation_seq": sequence, "record_seq": ordinal, "kind": kind,
              "agent_cycle": cycle, "geometry_epoch": epoch, "energy": state["energy"],
              "byte_length": length, "fragment_count": len(words), "words": words, "status": "ADMITTED"}
    decoded = decode_bytes(words, length, len(words), time["tick16"], phase16)
    assert decoded == (int(state["pair"], 16).to_bytes(8, "little") if payload is None else payload)
    if payload is None:
        assert decode_state(words, time["tick16"], phase16) == state["pair"]
    return result


def lifecycle(mission, postgrowth_capacity=4):
    config = config_for(mission)
    fifo = Fifo(config["initial_capacity"])
    state, status, cycle, epoch = deepcopy(mission["initial"]), "ACTIVE", 0, 0
    genesis = {"seq": 0, **clock(ORIGIN, EVENT_BOUND, 0), "ignited": False, "cache": fifo.witness()}
    ready = {**cursor(0, cycle, epoch, state, status, fifo, False), "type": "READY", "restored": False}
    rows, responses, duplicates, projection, executor_ticks = [], [], [], [], []
    action_ticks = 0
    for sequence, (operation, argument) in enumerate(SCHEDULE, 1):
        request = {"protocol": PROTOCOL, "op": operation, "producer": PRODUCER, "producer_epoch": PRODUCER_EPOCH,
                   "seq": sequence, **clock(ORIGIN, EVENT_BOUND, sequence), "agent_cycle": cycle, "geometry_epoch": epoch}
        removed = []
        if operation == "IGNITE":
            request["payload"] = PAYLOAD
        elif operation == "RESIZE":
            capacity = postgrowth_capacity if sequence == 11 else argument
            request["capacity"] = capacity
            removed = fifo.resize(capacity)
        elif operation == "INVALIDATE":
            request.update(paths=[fifo.active[0]], cause="release-old-local-copy" if sequence == 5 else "rebuild-current-local-copy")
            removed = fifo.invalidate(request["paths"])
        elif operation == "ADVANCE":
            event = mission["events"][argument - 1]
            assert argument == cycle + 1 and event["input_epoch"] == epoch
            assert sorted(event["input"]) == visible(state["path"])
            request.update(position=state["path"], observations=deepcopy(event["input"]))
            if event["kind"] == "GROW":
                fifo = Fifo(fifo.capacity)
                action_ticks = 0
            else:
                assert event["kind"] in ("MOVE", "REPAIR")
                action_ticks += 1
                for path in sorted(event["input"]):
                    fifo.get(path)
            cycle, epoch, state, status = argument, event["epoch"], deepcopy(event["state"]), event["status"]
            projection.append({"cycle": cycle, "input_epoch": event["input_epoch"], "input": deepcopy(event["input"]),
                               "kind": event["kind"], "pair": state["pair"], "energy": state["energy"],
                               "geometry_epoch": epoch, "status": status})
        records = []
        if operation == "IGNITE":
            records.append(record(config, sequence, 0, operation, cycle, epoch, state, bytes.fromhex(PAYLOAD)))
        records.append(record(config, sequence, len(records), operation, cycle, epoch, state))
        witness = fifo.witness(removed)
        rows.append({"request": request, "records": records, "agent_pair": state["pair"], "energy": state["energy"],
                     "status": status, "cache": witness})
        context = cursor(sequence, cycle, epoch, state, status, fifo, True)
        responses.append({**context, "type": "RESULT", "op": operation, "seq": sequence,
                          "records": deepcopy(records), "cache": witness, "agent_status": status})
        duplicates.append({**context, "type": "DUPLICATE", "seq": sequence})
        executor_ticks.append({"operation_seq": sequence, "agent_cycle": cycle,
                               "geometry_epoch": epoch, "executor_action_ticks": action_ticks})
        assert all(name not in duplicates[-1] for name in ("records", "event", "agent_pair", "energy", "cache"))
    expected = {"seq": len(rows), **clock(ORIGIN, EVENT_BOUND, len(rows)), "ignited": True, "cache": fifo.witness()}
    identities = [(r["word_profile"], r["baseline_id"], r["producer"], r["producer_epoch"],
                   r["clock_epoch"], r["tick16"], r["operation_seq"], r["record_seq"])
                  for row in rows for r in row["records"]]
    assert len(identities) == len(set(identities)) == 18
    fragment_count = sum(r["fragment_count"] for row in rows for r in row["records"])
    assert fragment_count == 37
    assert [row["executor_action_ticks"] for row in executor_ticks] == [0, 1, 1, 1, 1, 2, 3, 4, 4, 0, 0, 1, 2, 2, 3, 4, 4]
    assert cycle == 9 and state == mission["final"] and expected["clock_epoch"] == 1 and expected["tick16"] == 11
    assert rows[4]["request"]["paths"] == ["k:3:0"]
    assert rows[9]["cache"] == Fifo(1).witness()
    if postgrowth_capacity == 4:
        assert expected["cache"] == {"capacity": 4, "active_paths": ["k:1:0", "k:1:1", "k:1:2", "k:2:1"],
                                     "hit_count": 0, "regeneration_count": 7, "evicted_count": 16, "removed": []}
    else:
        assert expected["cache"]["hit_count"] > 0
    return {"format": "welip-independent-lifecycle-v1", "config": config, "genesis": genesis, "ready": ready,
            "operations": rows, "results": responses, "latest_retry_receipts": duplicates,
            "expected": expected, "projected_owner_transitions": projection, "final_owner": state,
            "record_count": len(identities), "fragment_count": fragment_count,
            "executor_action_tick_expectations": executor_ticks,
            "operation_transcript_sha256": digest(rows),
            "scope": "Independent W arithmetic around pinned OG mathematical transitions; not a newly measured runtime archive."}


def raw_vectors():
    result = []
    for label, payload in (("empty", b""), ("one", bytes.fromhex("A5")),
                           ("five", bytes.fromhex("0011223344")), ("nine", bytes.fromhex(PAYLOAD)),
                           ("maximum", bytes(range(256)) * 16)):
        words = encode_bytes(payload, 65531, 64000)
        assert decode_bytes(words, len(payload), len(words), 65531, 64000) == payload
        result.append({"name": label, "payload_hex": payload.hex().upper(), "byte_length": len(payload),
                       "fragment_count": len(words), "tick16": 65531, "phase16": 64000,
                       "words": words, "decoded_sha256": sha256(payload).hexdigest()})
    maximal = encode_bytes(bytes.fromhex("FFFFFFFF"), 65535, 65535)
    assert maximal == ["FFFFFFFFFFFFFFFF"]
    return {"length_cases": result, "generic_full_width": {"payload_hex": "FFFFFFFF", "tick16": 65535,
            "phase16": 65535, "words": maximal, "scope": "Generic carrier accepts all phase16; state binding additionally restricts resolution."}}


def phase_vectors():
    cases, selected = [], []
    for phase in range(256):
        for orientation in (0, 1):
            for opcode in (1, 6):
                metadata = opcode | (orientation << 4)
                left = pack(phase, 16, -2, metadata)
                right = pack((-phase) % 256, 16, -2, metadata ^ 16)
                pair = f"{right:08X}{left:08X}"
                phase16, words = state_words(pair, 65535)
                mirrored = pair[8:] + pair[:8]
                intrinsic = (-phase if orientation else phase) % 256
                assert phase16 == intrinsic << 8
                assert decode_state(words, 65535, phase16) == pair
                assert state_words(mirrored, 65535) == (phase16, list(reversed(words)))
                assert phase16 / 65536 == intrinsic / 256
                row = {"phase8": phase, "orientation": orientation, "opcode": opcode,
                       "intrinsic_phase8": intrinsic, "phase16": phase16, "pair": pair,
                       "tick16": 65535, "words": words, "mirrored_pair": mirrored,
                       "mirrored_words": list(reversed(words))}
                cases.append(row)
                if phase in (0, 1, 64, 127, 128, 187, 250, 255) and opcode == 1:
                    selected.append(row)
    assert len(cases) == 1024 and len(selected) == 16
    return {"checked_cases": len(cases), "complete_case_transcript_sha256": digest(cases),
            "coverage": "All 256 phase8 values, both orientations, STEP and EMIT; fixed node16 and B=-2.",
            "selected_literals": selected,
            "scope": "Zero added phase precision; mirrored channels preserve intrinsic phase while exchanging payload order."}


def rejected_vectors():
    raw = {"words": encode_bytes(bytes.fromhex("0011223344"), 65535, 0xABCD),
           "byte_length": 5, "fragment_count": 2, "tick16": 65535, "phase16": 0xABCD}
    cases = []
    def rejection(name, value, decoder=decode_bytes):
        try:
            decoder(**value)
        except ValueError as exc:
            cases.append({"name": name, "decoder": decoder.__name__, "input": value, "expected": str(exc)})
        else:
            raise AssertionError(f"Expected rejection: {name}")
    for name, changes in (("fragment count", {"fragment_count": 1}), ("too many words", {"words": raw["words"] + raw["words"][:1]}),
                          ("wrong tick", {"tick16": 0}), ("wrong phase", {"phase16": 1}),
                          ("boolean byte length", {"byte_length": True}), ("float phase", {"phase16": float(0xABCD)}),
                          ("oversize byte length", {"byte_length": 4097}),
                          ("lowercase hex", {"words": [word.lower() for word in raw["words"]]})):
        rejection(name, {**deepcopy(raw), **changes})
    padded = deepcopy(raw)
    padded["words"][-1] = f"{int(padded['words'][-1], 16) | 256:016X}"
    rejection("nonzero last padding", padded)
    encoded_pair = "81001010910010F0"
    phase16, words = state_words(encoded_pair, 0)
    state = {"words": words, "tick16": 0, "phase16": phase16}
    damaged = deepcopy(state)
    damaged["words"][0] = f"{int(words[0], 16) ^ 1:016X}"
    rejection("state odd parity", damaged, decode_state)
    damaged = deepcopy(state)
    right = pair_state(encoded_pair)
    replacement = pack(((-right["phase"]) + 1) % 256, right["node"], right["field"], 1)
    damaged["words"][1] = f"{(phase16 << 32) | replacement:016X}"
    rejection("even parity but wrong mirror", damaged, decode_state)
    bad_metadata = pack(0, 0, 0, 0) | (pack(0, 0, 0, 16) << 32)
    rejection("DATA pair is not owner state", {"words": encode_bytes(bad_metadata.to_bytes(8, "little"), 0, 0),
                                             "tick16": 0, "phase16": 0}, decode_state)
    rejection("state added phase precision", {"words": encode_bytes(int(encoded_pair, 16).to_bytes(8, "little"), 0, phase16 + 1),
                                              "tick16": 0, "phase16": phase16 + 1}, decode_state)
    rejection("state header disagrees with payload phase", {"words": encode_bytes(int(encoded_pair, 16).to_bytes(8, "little"), 0, phase16 + 256),
                                                           "tick16": 0, "phase16": phase16 + 256}, decode_state)
    mirrored = encoded_pair[8:] + encoded_pair[:8]
    assert decode_state(list(reversed(words)), 0, phase16) == mirrored != encoded_pair
    coordinated = {"source_pair": encoded_pair, "swapped_words": list(reversed(words)), "decoded_pair": mirrored,
                   "phase16": phase16, "codec_result": "valid mirrored representation", "owner_result": "reject different owned pair"}
    return {"rejections": cases, "representation_is_not_owner_authentication": coordinated}


def clock_vectors():
    boundary = [{"origin": ORIGIN, "max_events": EVENT_BOUND, "seq": sequence, **clock(ORIGIN, EVENT_BOUND, sequence)}
                for sequence in (0, 1, 5, 6, 17, EVENT_BOUND)]
    maximum = [{"origin": MAX48 - 64, "max_events": 64, "seq": sequence, **clock(MAX48 - 64, 64, sequence)}
               for sequence in (0, 1, 63, 64)]
    rejected = []
    for origin, limit in ((MAX48 - 63, 64), (MAX48, 1), (-1, 64), (True, 64), (0, 0), (0, 1_000_001), (0, 64.0)):
        try:
            clock(origin, limit, 0)
        except ValueError as exc:
            rejected.append({"origin": origin, "max_events": limit, "expected": str(exc)})
        else:
            raise AssertionError("Expected invalid finite clock configuration")
    return {"wrap": boundary, "u48_maximum": maximum, "configuration_rejections": rejected,
            "exhausted_next_request": {"origin": MAX48 - 64, "max_events": 64, "head_seq": 64,
                "request_seq": 65, "request_clock_epoch": MAX32, "request_tick16": 65535,
                "static_seq_valid": True, "expected": "BUDGET_EXHAUSTED before clock equality; do not compute or wrap a next cursor",
                "next": None, "exact_latest_retry": "DUPLICATE without mutation"}}


def retry_vectors(main):
    latest = main["operations"][-1]["request"]
    conflict = {**latest, "tick16": 0}
    gap = {**latest, "seq": 19, **clock(ORIGIN, EVENT_BOUND, 19)}
    forward = {**latest, "seq": 18, **clock(ORIGIN, EVENT_BOUND, 18)}
    state = main["final_owner"]
    return {"latest_after_invalidation": {"request": main["operations"][4]["request"], "response": main["latest_retry_receipts"][4],
                "scope": "At head5, paths are no longer active; compare latest canonical request before dynamic membership."},
            "latest_after_growth": {"request": main["operations"][9]["request"], "response": main["latest_retry_receipts"][9],
                "scope": "At head10, request geometry0 differs from current1; exact retry precedes current-context checks."},
            "latest_after_complete": {"request": latest, "response": main["latest_retry_receipts"][-1]},
            "rejections_at_head17": [
                {"request": main["operations"][0]["request"], "code": "STALE_SEQUENCE"},
                {"request": conflict, "code": "CONFLICT"}, {"request": gap, "code": "SEQUENCE_GAP"},
                {"request": {**latest, "op": "READ"}, "code": "BACKWARD_READ"},
                {"request": {**latest, "producer": "different"}, "code": "SOURCE_MISMATCH"}],
            "new_forward_emit": {"request": forward, "record": record(main["config"], 18, 0, "EMIT", 9, 1, state),
                "scope": "New W time; current owner state only. No raw ignition payload is recovered."},
            "scope": "Expected protocol outcomes from W4/W8; all retries/rejections have no dispatch, transition, cache mutation or durable append."}


def main():
    assert lf_digest(OG_PATH) == OG_SHA
    assert lf_digest(OG_BUILDER) == OG_BUILDER_SHA
    # OG imports this independent helper at module load; pin the full imported
    # arithmetic closure before evaluating either generator.
    assert lf_digest(GD_BUILDER) == GD_BUILDER_SHA
    reference = json.loads(OG_PATH.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("independent_OG_math", OG_BUILDER)
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    assert independent.mission() == reference["default_mission"]
    assert independent.mission(mirrored=True) == reference["mirrored_default_mission"]
    normal = lifecycle(reference["default_mission"])
    mirror = lifecycle(reference["mirrored_default_mission"])
    roomy = lifecycle(reference["default_mission"], 8)
    assert normal["projected_owner_transitions"] == roomy["projected_owner_transitions"]
    for left, right in zip(normal["operations"], mirror["operations"]):
        assert left["cache"] == right["cache"] and left["energy"] == right["energy"]
        assert left["agent_pair"] == right["agent_pair"][8:] + right["agent_pair"][:8]
        for a, b in zip(left["records"], right["records"]):
            assert a["phase16"] == b["phase16"]
            assert a["words"] == (list(reversed(b["words"])) if a["payload_profile"] == STATE_PROFILE else b["words"])
    historical_path = ROOT / "docs/evidence/organogram-v1/conformance.json"
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    assert historical["canonical_archive_sha256"] == HISTORICAL_ARCHIVE_SHA
    output = {"format": "welip-independent-formal-reference-v1",
              "scope": "Preimplementation independent finite W arithmetic and original OG mathematical owner projection; no solvefinite imports or device execution.",
              "generator_sha256_lf": lf_digest(Path(__file__)),
              "source_OG_reference_sha256": OG_SHA, "source_OG_generator_sha256_lf": OG_BUILDER_SHA,
              "source_GD_generator_sha256_lf": GD_BUILDER_SHA,
              "main_lifecycle": normal, "mirrored_lifecycle": mirror, "capacity8_lifecycle": roomy,
              "raw_payload_vectors": raw_vectors(), "phase_vectors": phase_vectors(),
              "malformed_vectors": rejected_vectors(),
              "clock_vectors": clock_vectors(), "retry_vectors": retry_vectors(normal),
              "historical_runtime_preservation_expectation": {"source": "docs/evidence/organogram-v1/conformance.json",
                  "source_sha256": lf_digest(historical_path),
                  "canonical_agent_archive_sha256": HISTORICAL_ARCHIVE_SHA,
                  "scope": "Previously measured OG runtime archive; W implementation must preserve this projection. Not a new independent W runtime measurement."}}
    path = Path(__file__).with_name("formal-reference.json")
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(path), "reference_sha256": sha256(path.read_bytes()).hexdigest(),
                      "generator_sha256_lf": output["generator_sha256_lf"],
                      "main": {"operation_count": len(normal["operations"]), "record_count": normal["record_count"],
                               "final_owner": normal["final_owner"], "expected": normal["expected"],
                               "operations_sha256": normal["operation_transcript_sha256"]},
                      "capacity8": roomy["expected"], "malformed_count": len(output["malformed_vectors"]["rejections"])}, indent=2))


if __name__ == "__main__":
    main()
