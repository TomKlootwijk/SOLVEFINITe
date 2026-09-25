"""Real-process interaction with the persistent live TOMIGIDt JSONL endpoint."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from solvefinite.live import LiveConfig, load_live
from solvefinite.runtime import write_json
from solvefinite.tomigidt import AgentManifest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "tomigidt-live-v1"
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class Client:
    def __init__(self, state, capacity=2, config=None):
        command = [sys.executable, "-m", "solvefinite", "agent", "serve",
                   "--state", str(state), "--capacity", str(capacity)]
        if config is not None:
            command.extend(["--config", str(config)])
        self.process = subprocess.Popen(
            command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=HIDDEN,
        )
        self.lines = queue.Queue()

        def read_stdout():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)

        self.reader = threading.Thread(target=read_stdout, daemon=True)
        self.reader.start()

    def read(self):
        try:
            line = self.lines.get(timeout=5)
        except queue.Empty as exc:
            raise AssertionError(f"Live process {self.process.pid} did not flush a response") from exc
        if line is None:
            self.process.wait(timeout=5)
            raise AssertionError(f"Live process exited {self.process.returncode}: {self.process.stderr.read()}")
        return json.loads(line)

    def send(self, request):
        self.send_raw(json.dumps(request))

    def send_raw(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def request(self, request):
        self.send(request)
        return self.read()

    def finish(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        return self.process.returncode, self.process.stderr.read()

    def terminate(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=5)

    def close(self):
        self.terminate()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass


def observations_request(response, observations=None):
    next_frame = response["next"]
    return {
        "protocol": PROTOCOL, "type": "observe",
        "producer": response["producer"], "epoch": response["epoch"],
        "seq": next_frame["seq"], "position": next_frame["position"],
        "observations": ({path: 0 for path in next_frame["paths"]}
                         if observations is None else observations),
    }


class LiveCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tomigidt-live-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.state = self.directory / "live state.json"

    def cli(self, *arguments, input_text=None):
        return subprocess.run(
            [sys.executable, "-m", "solvefinite", *(str(argument) for argument in arguments)],
            cwd=ROOT, input=input_text, capture_output=True, text=True,
            encoding="utf-8", timeout=5, creationflags=HIDDEN,
        )

    def start(self, capacity=2, config=None):
        client = Client(self.state, capacity, config)
        self.addCleanup(client.close)
        ready = client.read()
        self.assertEqual((ready["protocol"], ready["type"]), (PROTOCOL, "ready"))
        self.assertIsNone(client.process.poll())
        return client, ready

    def config_file(self, config):
        path = self.directory / "live config.json"
        write_json(path, config.to_dict())
        return path

    def finish_agent(self, client, response):
        for _ in range(64):
            if response["state"]["status"] == "COMPLETE":
                return response
            response = client.request(observations_request(response))
            self.assertEqual(response["type"], "result")
        self.fail("Default live objective did not complete within 64 observations")

    def test_live_config_command_writes_valid_config_and_inspection_replays_state(self):
        output = self.directory / "generated config.json"
        generated = self.cli("agent", "live-config", "--output", output)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(generated.stderr, "")
        self.assertEqual(json.loads(generated.stdout),
                         {"config": str(output.resolve()), "identity": "TOMIGIDt"})
        self.assertEqual(LiveConfig.from_dict(json.loads(output.read_text())), LiveConfig())
        client, ready = self.start(config=output)
        result = client.request(observations_request(ready))
        inspected = self.cli("agent", "live-inspect", self.state, "--capacity", "7")
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        summary = json.loads(inspected.stdout)
        self.assertEqual(summary, {
            "verified": True, "state": result["state"], "state_path": str(self.state.resolve()),
            "event_count": 1, "producer": "sensor", "epoch": 0,
        })

    def test_ready_flushes_and_eof_exits_without_trailing_json(self):
        client, ready = self.start()
        self.assertFalse(ready["restored"])
        self.assertEqual(ready["state"]["cycle"], 0)
        self.assertEqual(ready["next"], {"seq": 1, "position": "", "paths": ["", "0", "1"]})
        code, stderr = client.finish()
        self.assertEqual((code, stderr), (0, ""))
        self.assertIsNone(client.lines.get(timeout=5))
        with self.assertRaises(queue.Empty):
            client.lines.get_nowait()
        _, retained = load_live(self.state)
        self.assertEqual(retained.cycle, 0)

    def test_hazard_drop_recovers_insufficient_energy_in_the_same_process(self):
        client, ready = self.start()
        expensive = {path: 127 for path in ready["next"]["paths"]}
        blocked = client.request(observations_request(ready, expensive))
        self.assertEqual(blocked["state"]["status"], "INSUFFICIENT_ENERGY")
        self.assertEqual(blocked["state"]["position"], "")
        self.assertIsNone(client.process.poll())
        resumed = client.request(observations_request(blocked))
        self.assertEqual(resumed["event"]["decision"]["kind"], "MOVE")
        completed = self.finish_agent(client, resumed)
        self.assertIsNone(completed["next"])
        self.assertIsNone(client.process.poll())
        status = client.request({"protocol": PROTOCOL, "type": "status"})
        self.assertEqual(status["state"], completed["state"])
        self.assertIsNone(status["next"])
        self.assertEqual(client.finish(), (0, ""))

    def test_incomplete_sensor_frame_waits_then_a_fresh_full_frame_moves(self):
        client, ready = self.start()
        waiting = client.request(observations_request(ready, {"": 0}))
        self.assertEqual(waiting["state"]["status"], "WAITING")
        self.assertEqual(waiting["state"]["position"], "")
        self.assertEqual(waiting["state"]["cycle"], 1)
        moved = client.request(observations_request(waiting))
        self.assertEqual(moved["event"]["decision"]["kind"], "MOVE")
        self.assertEqual(moved["state"]["cycle"], 2)
        self.assertFalse(moved["duplicate"])

    def test_single_expansion_search_resumes_after_fresh_process_restart(self):
        config = LiveConfig(manifest=replace(AgentManifest(), max_search_expansions=1))
        client, ready = self.start(config=self.config_file(config), capacity=1)
        first = client.request(observations_request(ready))
        self.assertEqual(first["state"]["status"], "SEARCH_DEFERRED")
        self.assertEqual(first["state"]["planning"]["expansions"], 1)
        old_pid = client.process.pid
        self.assertEqual(client.finish(), (0, ""))
        restarted, restored = self.start(capacity=8)
        self.assertNotEqual(restarted.process.pid, old_pid)
        self.assertTrue(restored["restored"])
        self.assertEqual(restored["state"], first["state"])
        second = restarted.request(observations_request(restored))
        self.assertEqual(second["event"]["decision"]["expansions"], 2)
        completed = self.finish_agent(restarted, second)
        self.assertEqual(completed["state"]["status"], "COMPLETE")
        self.assertEqual(restarted.finish(), (0, ""))

    def test_unread_acknowledgement_retries_after_disk_commit_without_duplicate_action(self):
        client, ready = self.start()
        request = observations_request(ready)
        client.send(request)
        deadline = time.monotonic() + 5
        while True:
            self.assertIsNone(client.process.poll())
            _, retained = load_live(self.state)
            if retained.cycle == 1:
                break
            if time.monotonic() >= deadline:
                self.fail("Live request did not commit its cycle within five seconds")
            time.sleep(.01)
        committed = retained.snapshot()
        event = retained.events[0]
        # The client has never consumed its queued response. Lose this process
        # and retry the same producer sequence against the durable archive.
        client.terminate()
        restarted, ready_again = self.start()
        self.assertTrue(ready_again["restored"])
        duplicate = restarted.request(request)
        self.assertEqual(duplicate["type"], "result")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["event"], event)
        self.assertEqual(duplicate["state"], committed)
        _, retained_again = load_live(self.state)
        self.assertEqual(len(retained_again.events), 1)
        accepted = restarted.request(observations_request(duplicate))
        self.assertFalse(accepted["duplicate"])
        self.assertEqual(accepted["state"]["cycle"], 2)

    def test_competing_writer_is_rejected_while_ready_process_still_owns_state(self):
        client, ready = self.start()
        contender = self.cli("agent", "serve", "--state", self.state, input_text="")
        self.assertEqual(contender.returncode, 2)
        self.assertEqual(contender.stdout, "")
        self.assertIn("solvefinite:", contender.stderr)
        self.assertNotIn("Traceback", contender.stderr)
        self.assertIsNone(client.process.poll())
        accepted = client.request(observations_request(ready))
        self.assertEqual(accepted["state"]["cycle"], 1)

    def test_protocol_errors_preserve_sequence_and_next_valid_input_still_works(self):
        client, ready = self.start()
        request = observations_request(ready)
        out_of_order = dict(request, seq=2)
        self.assertEqual(client.request(out_of_order)["type"], "error")
        duplicate_keys = json.dumps(request).replace('"seq": 1', '"seq": 1, "seq": 1')
        nonfinite = deepcopy(request)
        nonfinite["observations"][""] = float("nan")
        for invalid_json in ("{bad json", duplicate_keys, json.dumps(nonfinite)):
            with self.subTest(invalid_json=invalid_json):
                client.send_raw(invalid_json)
                error = client.read()
                self.assertEqual((error["type"], error["code"]), ("error", "INVALID_JSON"))
                self.assertEqual(error["state"], ready["state"])
                self.assertEqual(error["next"], ready["next"])
        _, retained = load_live(self.state)
        self.assertEqual(retained.cycle, 0)
        accepted = client.request(request)
        self.assertEqual(accepted["type"], "result")
        self.assertEqual(accepted["state"]["cycle"], 1)
        conflicting = deepcopy(request)
        conflicting["observations"][""] = 1
        self.assertEqual(client.request(conflicting)["type"], "error")
        duplicate = client.request(request)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["state"]["cycle"], 1)
        accepted_next = client.request(observations_request(duplicate))
        self.assertEqual(accepted_next["state"]["cycle"], 2)
        self.assertIsNone(client.process.poll())

    def test_oversized_line_is_fatal_without_interpreting_its_tail_or_following_frames(self):
        trailing_status = json.dumps({"protocol": PROTOCOL, "type": "status"})
        oversized = "x" * 65537 + "\n" + trailing_status + "\n"
        failed = self.cli("agent", "serve", "--state", self.state, input_text=oversized)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("frame limit", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)
        emitted = [json.loads(line) for line in failed.stdout.splitlines()]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "ready")
        self.assertEqual(emitted[0]["state"]["cycle"], 0)
        _, retained = load_live(self.state)
        self.assertEqual(retained.cycle, 0)
        self.assertEqual(retained.events, [])
        before = self.state.read_bytes()
        reopened, ready = self.start()
        self.assertTrue(ready["restored"])
        self.assertEqual(ready["state"], emitted[0]["state"])
        self.assertEqual(reopened.finish(), (0, ""))
        self.assertEqual(self.state.read_bytes(), before)

    def test_completed_session_accepts_duplicate_retry_and_status_while_staying_open(self):
        manifest = AgentManifest(target="", graph=(("", ()),))
        config = LiveConfig(manifest=manifest, producer="instrument-A", epoch=4)
        client, ready = self.start(config=self.config_file(config))
        request = observations_request(ready)
        completed = client.request(request)
        self.assertEqual(completed["state"]["status"], "COMPLETE")
        self.assertIsNone(completed["next"])
        repeated = client.request(request)
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["event"], completed["event"])
        self.assertEqual(repeated["state"], completed["state"])
        status = client.request({"protocol": PROTOCOL, "type": "status"})
        self.assertEqual(status["state"], completed["state"])
        self.assertIsNone(client.process.poll())
        self.assertEqual(client.finish(), (0, ""))

    def test_startup_malformed_config_and_state_fail_cleanly(self):
        config = self.directory / "bad config.json"
        config.write_text('{"bad":true}', encoding="utf-8")
        invalid = self.cli("agent", "serve", "--state", self.state, "--config", config, input_text="")
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, "")
        self.assertIn("solvefinite:", invalid.stderr)
        self.assertNotIn("Traceback", invalid.stderr)
        self.assertFalse(self.state.exists())
        self.state.write_text('{"bad":true}', encoding="utf-8")
        before = self.state.read_bytes()
        invalid_state = self.cli("agent", "serve", "--state", self.state, input_text="")
        self.assertEqual(invalid_state.returncode, 2)
        self.assertNotIn("Traceback", invalid_state.stderr)
        self.assertEqual(self.state.read_bytes(), before)
        inspected = self.cli("agent", "live-inspect", self.state)
        self.assertEqual(inspected.returncode, 2)
        self.assertNotIn("Traceback", inspected.stderr)


if __name__ == "__main__":
    unittest.main()
