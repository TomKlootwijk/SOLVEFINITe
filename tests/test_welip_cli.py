"""Actual CPU-process W transport, finite clocks and forward-only recovery."""

from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from solvefinite.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "docs/evidence/welip-v1/formal-reference.json").read_text(encoding="utf-8"))
PROTOCOL = "welip-field-agent-v1"
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
COMMON = {"protocol", "type", "producer", "producer_epoch", "head", "next"}


def request_for(response, op, **extra):
    cursor = response["next"]
    request = {"protocol": PROTOCOL, "op": op, "producer": response["producer"],
               "producer_epoch": response["producer_epoch"]}
    request.update({key: cursor[key] for key in
                    ("seq", "clock_epoch", "tick16", "agent_cycle", "geometry_epoch")})
    if op == "ADVANCE":
        request.update(position=cursor["position"],
                       observations=dict.fromkeys(cursor["visible_paths"], 0))
    request.update(extra)
    return request


class WelipClient:
    def __init__(self, state, config=None, index_options=()):
        command = [sys.executable, "-m", "solvefinite", "agent", "welip",
                   "--state", str(state), "--backend", "cpu", *index_options]
        if config is not None:
            command.extend(["--config", str(config)])
        self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", creationflags=HIDDEN)
        self.lines = queue.Queue()
        def read_stdout():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        self.reader = threading.Thread(target=read_stdout, daemon=True)
        self.reader.start()

    def read(self):
        try:
            line = self.lines.get(timeout=10)
        except queue.Empty as exc:
            raise AssertionError("W endpoint did not flush its response") from exc
        if line is None:
            self.process.wait(timeout=5)
            raise AssertionError(f"W endpoint exited {self.process.returncode}: {self.process.stderr.read()}")
        return json.loads(line)

    def send_raw(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def send(self, request):
        self.send_raw(json.dumps(request))

    def request(self, request):
        self.send(request)
        return self.read()

    def finish(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.wait(timeout=10)
        self.reader.join(timeout=5)
        return self.process.returncode, self.process.stderr.read()

    def close(self):
        try:
            self.finish()
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass


class WelipCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="welip-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.state = self.directory / "W state.json"

    def cli(self, *arguments, input_text=None, cwd=ROOT):
        return subprocess.run([sys.executable, "-m", "solvefinite", *map(str, arguments)],
                              cwd=cwd, input=input_text, capture_output=True, text=True,
                              encoding="utf-8", timeout=15, creationflags=HIDDEN)

    def config_file(self, value=None):
        path = self.directory / "W config.json"
        write_json(path, deepcopy(REFERENCE["main_lifecycle"]["config"] if value is None else value))
        return path

    def start(self, config=None, index_options=()):
        client = WelipClient(self.state, config, index_options)
        self.addCleanup(client.close)
        ready = client.read()
        self.assertEqual(set(ready), COMMON | {"restored"})
        self.assertEqual((ready["protocol"], ready["type"]), (PROTOCOL, "READY"))
        self.assertIsNone(client.process.poll())
        return client, ready

    def assert_error(self, reply, code, *, fatal=False):
        self.assertEqual(set(reply), COMMON | {"code", "message", "fatal"})
        self.assertEqual((reply["type"], reply["code"], reply["fatal"]), ("ERROR", code, fatal))
        self.assertIs(type(reply["message"]), str)
        self.assertTrue(reply["message"])
        if fatal:
            self.assertIsNone(reply["head"])
            self.assertIsNone(reply["next"])

    def test_config_generator_defaults_to_organogram_and_accepts_all_four_profiles(self):
        from solvefinite.welip import WelipConfig
        from solvefinite.field_agent import (
            FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY,
        )
        policies = {"field": FIELD_POLICY, "hadamard": HADAMARD_POLICY,
                    "growth": GROWTH_POLICY, "organogram": ORGANOGRAM_POLICY}
        for profile, policy in [(None, ORGANOGRAM_POLICY), *policies.items()]:
            output = self.directory / f"{profile} config.json"
            arguments = ["agent", "welip-config", "--output", output]
            if profile:
                arguments += ["--profile", profile]
            generated = self.cli(*arguments)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertEqual(json.loads(generated.stdout),
                             {"config": str(output.resolve()), "identity": "TOMIGIDt"})
            config = WelipConfig.from_dict(json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(config.manifest.policy, policy)
            self.assertEqual((config.producer, config.producer_epoch, config.clock_origin,
                              config.max_events, config.initial_capacity), ("sensor", 0, 0, 1000000, 2))

    def test_config_generator_retains_namespace_clock_capacity_and_rejects_bad_bounds(self):
        output = self.directory / "custom.json"
        result = self.cli("agent", "welip-config", "--producer", "camera",
                          "--producer-epoch", 4294967295, "--clock-origin", 281474976710591,
                          "--max-events", 64, "--initial-capacity", 256, "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual((config["producer"], config["producer_epoch"], config["clock_origin"],
                          config["max_events"], config["initial_capacity"]),
                         ("camera", 4294967295, 281474976710591, 64, 256))
        original = output.read_bytes()
        for flag, value in (("--producer", " spaced "), ("--producer-epoch", -1),
                            ("--clock-origin", 281474976710655), ("--max-events", 0),
                            ("--initial-capacity", 0), ("--initial-capacity", 257),
                            ("--profile", "binary")):
            with self.subTest(flag=flag, value=value):
                rejected = self.cli("agent", "welip-config", flag, value, "--output", output)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(rejected.stdout, "")
                self.assertEqual(output.read_bytes(), original)

    def test_ready_eof_and_durable_genesis_have_no_implicit_ignition(self):
        client, ready = self.start()
        self.assertFalse(ready["restored"])
        self.assertEqual(ready["next"]["allowed_ops"], ["IGNITE"])
        self.assertEqual(ready["head"], {"seq": 0, "clock_epoch": 0, "tick16": 0,
                                          "agent_cycle": 0, "geometry_epoch": 0})
        self.assertEqual(client.finish(), (0, ""))
        self.assertIsNone(client.lines.get(timeout=5))
        self.assertTrue(client.lines.empty())
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["operations"], [])
        self.assertFalse(saved["expected"]["ignited"])
        self.assertEqual(saved["config"]["agent"]["policy"], "tomigidt-field-organogram-plan-act-v1")
        restarted, restored = self.start()
        self.assertTrue(restored["restored"])
        self.assertEqual(restored["head"], ready["head"])
        self.assertEqual(restarted.finish(), (0, ""))

    def test_complete_reference_schedule_survives_reopens_carry_grow_and_latest_retries(self):
        reference = REFERENCE["main_lifecycle"]
        client, response = self.start(self.config_file())
        self.assertEqual(response, reference["ready"])
        for index, (operation, result, duplicate) in enumerate(zip(
                reference["operations"], reference["results"], reference["latest_retry_receipts"]), 1):
            with self.subTest(operation=index):
                response = client.request(operation["request"])
                self.assertEqual(response, result)
                self.assertEqual(client.request(operation["request"]), duplicate)
                if index in (5, 6, 9, 10, 16):
                    self.assertEqual(client.finish(), (0, ""))
                    client, ready = self.start(index_options=("--index-epoch", str(index),
                                                             "--index-sign", "-1",
                                                             "--index-phase-origin", "91"))
                    self.assertTrue(ready["restored"])
                    self.assertEqual((ready["head"], ready["next"]), (result["head"], result["next"]))
                    self.assertEqual(client.request(operation["request"]), duplicate)
        self.assertEqual(response["records"][0]["words"],
                         ["000BBA0016000646", "000BBA00860006BA"])
        self.assertEqual(client.finish(), (0, ""))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["operations"], reference["operations"])
        self.assertEqual(saved["expected"], reference["expected"])
        self.assertEqual(len(saved["agent"]["events"]), 9)

    def test_budget_exhaustion_keeps_latest_retry_open_at_maximum_clock(self):
        config = deepcopy(REFERENCE["main_lifecycle"]["config"])
        config.update(clock_origin=(1 << 48) - 2, max_events=1)
        client, ready = self.start(self.config_file(config))
        request = request_for(ready, "IGNITE", payload="")
        result = client.request(request)
        self.assertIsNone(result["next"])
        self.assertEqual((result["head"]["clock_epoch"], result["head"]["tick16"]),
                         (4294967295, 65535))
        before = self.state.read_bytes()
        duplicate = client.request(dict(reversed(list(request.items()))))
        self.assertEqual(set(duplicate), COMMON | {"seq"})
        self.assertEqual(duplicate["type"], "DUPLICATE")
        exhausted = dict(request, op="EMIT", seq=2)
        exhausted.pop("payload")
        self.assert_error(client.request(exhausted), "BUDGET_EXHAUSTED")
        self.assertIsNone(client.process.poll())
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(client.finish(), (0, ""))

    def test_unread_acknowledgement_reopens_as_minimal_latest_receipt(self):
        client, ready = self.start(self.config_file())
        ignition = request_for(ready, "IGNITE", payload="00")
        result = client.request(ignition)
        advance = request_for(result, "ADVANCE")
        client.send(advance)
        deadline = time.monotonic() + 10
        while client.lines.empty():
            self.assertIsNone(client.process.poll())
            if time.monotonic() >= deadline:
                self.fail("Durable acknowledgement never reached the unread response queue")
            time.sleep(.01)
        # Queue arrival proves atomic replacement is over, avoiding Windows
        # file-sharing races while intentionally not consuming the reply.
        before = self.state.read_bytes()
        self.assertEqual(client.finish(), (0, ""))
        restarted, ready_again = self.start()
        self.assertEqual(ready_again["head"]["agent_cycle"], 1)
        receipt = restarted.request(advance)
        self.assertEqual(set(receipt), COMMON | {"seq"})
        self.assertEqual((receipt["type"], receipt["seq"]), ("DUPLICATE", 2))
        self.assert_error(restarted.request(ignition), "STALE_SEQUENCE")
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(restarted.finish(), (0, ""))

    def test_malformed_transport_and_backward_names_are_nonfatal_and_pure(self):
        client, ready = self.start()
        before = self.state.read_bytes()
        invalid = ('{"protocol":"welip-field-agent-v1","protocol":"welip-field-agent-v1","op":"EMIT"}',
                   '{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}', '[]', 'null', '{')
        for line in invalid:
            client.send_raw(line)
            reply = client.read()
            self.assert_error(reply, "INVALID_REQUEST")
            self.assertEqual((reply["head"], reply["next"]), (ready["head"], ready["next"]))
        for op in ("READ", "HISTORY", "REPLAY", "REGENERATE"):
            self.assert_error(client.request({"protocol": PROTOCOL, "op": op}), "BACKWARD_READ")
        for op in ("status", "inspect", "derive_epoch", "reindex"):
            self.assert_error(client.request({"protocol": PROTOCOL, "op": op}), "INVALID_REQUEST")
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(client.request(request_for(ready, "IGNITE", payload=""))["type"], "RESULT")
        self.assertEqual(client.finish(), (0, ""))

    def test_oversized_request_is_fatal_without_interpreting_valid_tail(self):
        client, ready = self.start()
        before = self.state.read_bytes()
        valid = json.dumps(request_for(ready, "IGNITE", payload=""))
        client.send_raw(" " * 65537 + valid)
        self.assert_error(client.read(), "REQUEST_TOO_LARGE", fatal=True)
        code, _ = client.finish()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertIsNone(client.lines.get(timeout=5))

    def test_exact_transport_bound_and_maximum_payload_are_admitted(self):
        client, ready = self.start()
        payload = bytes(range(256)) * 16
        request = request_for(ready, "IGNITE", payload=payload.hex().upper())
        serialized = json.dumps(request)
        # The frame limit includes the newline consumed by readline.
        client.send_raw(serialized + " " * (65535 - len(serialized)))
        admitted = client.read()
        self.assertEqual(admitted["type"], "RESULT")
        raw = admitted["records"][0]
        self.assertEqual((raw["byte_length"], raw["fragment_count"]), (4096, 1024))
        reconstructed = b"".join((int(word, 16) & 0xFFFFFFFF).to_bytes(4, "little")
                                 for word in raw["words"])
        self.assertEqual(reconstructed, payload)
        self.assertEqual(client.request(request)["type"], "DUPLICATE")
        self.assertEqual(client.finish(), (0, ""))

    def test_configuration_mismatch_and_corrupt_startup_produce_no_ready(self):
        config = self.config_file()
        client, _ = self.start(config)
        self.assertEqual(client.finish(), (0, ""))
        before = self.state.read_bytes()
        changed = deepcopy(REFERENCE["main_lifecycle"]["config"])
        changed["initial_capacity"] = 4
        self.config_file(changed)
        rejected = self.cli("agent", "welip", "--state", self.state, "--config", config, input_text="")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.state.read_bytes(), before)
        self.state.write_text('{"format":"broken"}', encoding="utf-8")
        broken = self.cli("agent", "welip", "--state", self.state, input_text="")
        self.assertNotEqual(broken.returncode, 0)
        self.assertEqual(broken.stdout, "")

    def test_second_process_cannot_acquire_the_same_canonical_state_path(self):
        client, ready = self.start()
        denied = self.cli("agent", "welip", "--state", self.directory / "." / self.state.name,
                          input_text="")
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(denied.stdout, "")
        self.assertEqual(client.request(request_for(ready, "IGNITE", payload=""))["type"], "RESULT")
        self.assertEqual(client.finish(), (0, ""))
        restarted, _ = self.start()
        self.assertEqual(restarted.finish(), (0, ""))

    def test_w_cli_has_no_capacity_override_or_historical_subcommands(self):
        for tail in (("welip", "--capacity", "4"), ("welip", "inspect"),
                     ("welip", "--history"), ("welip-inspect",), ("welip-history",)):
            with self.subTest(tail=tail):
                result = self.cli("agent", *tail)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
