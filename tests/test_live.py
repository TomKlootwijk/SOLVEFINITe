"""Durable, bounded sensor protocol for one TOMIGIDt live session."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from solvefinite.live import (
    CONFIG_FORMAT, LIVE_FORMAT, PROTOCOL, LiveConfig, LiveProtocolError,
    LiveSession, load_live,
)
from solvefinite.runtime import write_json as atomic_write_json
from solvefinite.session import AgentBusy
from solvefinite.tomigidt import AgentManifest


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def status_request():
    return {"protocol": PROTOCOL, "type": "status"}


def observe_request(response, observations=None):
    next_frame = response["next"]
    if observations is None:
        observations = {path: 0 for path in next_frame["paths"]}
    return {"protocol": PROTOCOL, "type": "observe",
            "producer": response["producer"], "epoch": response["epoch"],
            "seq": next_frame["seq"], "position": next_frame["position"],
            "observations": observations}


def finish_live(session):
    response = session.handle(status_request())
    for _ in range(128):
        if response["next"] is None:
            return response
        response = session.handle(observe_request(response))
    raise AssertionError("Live test mission failed to finish")


class LiveConfigurationTests(unittest.TestCase):
    def test_configuration_is_frozen_strict_and_round_trips(self):
        self.assertEqual(PROTOCOL, "tomigidt-live-v1")
        self.assertEqual(CONFIG_FORMAT, "tomigidt-live-config-v1")
        self.assertEqual(LIVE_FORMAT, "tomigidt-live-session-v1")
        config = LiveConfig(producer="test-sensor", epoch=7)
        self.assertEqual(LiveConfig.from_dict(config.to_dict()), config)
        with self.assertRaises(FrozenInstanceError):
            config.epoch = 8
        encoded = config.to_dict()
        for key in encoded:
            damaged = deepcopy(encoded)
            damaged.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                LiveConfig.from_dict(damaged)
        damaged = deepcopy(encoded)
        damaged["extra"] = True
        with self.assertRaises(ValueError):
            LiveConfig.from_dict(damaged)
        for invalid in (None, [], True, "", {}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                LiveConfig.from_dict(invalid)

    def test_invalid_configuration_fields_rejected(self):
        for parameters in ({"manifest": {}}, {"manifest": None}, {"producer": ""},
                           {"producer": "   "}, {"producer": None}, {"producer": True},
                           {"epoch": -1}, {"epoch": True}, {"epoch": 0.0}, {"epoch": "0"},
                           {"epoch": 1 << 63}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                LiveConfig(**parameters)

    def test_load_rejects_duplicate_json_keys_and_nonfinite_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "live config.json"
            config = LiveConfig()
            write_json(path, config.to_dict())
            self.assertEqual(LiveConfig.load(path), config)
            for content in ('{"format":"a","format":"b"}',
                            '{"epoch":NaN}', '{"epoch":Infinity}', '{"epoch":-Infinity}'):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    LiveConfig.load(path)


class LiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="tomigidt-live-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "live state with spaces.json"

    def assert_protocol_error(self, session, request):
        with self.assertRaises(LiveProtocolError) as caught:
            session.handle(request)
        self.assertIs(type(caught.exception.code), str)
        self.assertTrue(caught.exception.code)

    def test_initial_ready_status_and_each_ack_match_durable_replay(self):
        config = LiveConfig(producer="instrument-1", epoch=4)
        with LiveSession(self.path, config=config, capacity=1) as session:
            ready = session.ready()
            self.assertEqual((ready["protocol"], ready["producer"], ready["epoch"]),
                             (PROTOCOL, "instrument-1", 4))
            self.assertIs(ready["restored"], False)
            self.assertEqual(ready["state"]["cycle"], 0)
            self.assertEqual(ready["next"], {"seq": 1, "position": "", "paths": ["", "0", "1"]})
            self.assertFalse(hasattr(session, "agent"))
            initial_bytes = self.path.read_bytes()
            status = session.handle(status_request())
            self.assertEqual(status["state"], ready["state"])
            self.assertEqual(status["next"], ready["next"])
            self.assertEqual(self.path.read_bytes(), initial_bytes)
            request = observe_request(ready)
            result = session.handle(request)
            self.assertEqual(result["type"], "result")
            self.assertIs(result["duplicate"], False)
            self.assertEqual(result["event"]["decision"]["kind"], "MOVE")
            self.assertEqual(result["state"]["position"], "0")
            loaded_config, agent = load_live(self.path, capacity=8)
            self.assertEqual(loaded_config, config)
            self.assertEqual(result["event"], agent.events[-1])
            self.assertEqual(result["state"], agent.snapshot())
            self.assertEqual(result["next"], {"seq": 2, "position": "0", "paths": ["", "0", "00"]})
            saved = read_json(self.path)
            self.assertEqual(set(saved), {"format", "config", "agent"})
            self.assertEqual(saved["format"], LIVE_FORMAT)
            self.assertEqual(saved["config"], config.to_dict())
            self.assertEqual(saved["agent"], agent.archive())

    def test_duplicate_old_sequence_returns_original_event_with_current_state(self):
        with LiveSession(self.path) as session:
            first_request = observe_request(session.ready())
            first = session.handle(first_request)
            second = session.handle(observe_request(first))
            self.assertEqual(second["state"]["position"], "00")
            before = self.path.read_bytes()
            repeated = session.handle(deepcopy(first_request))
            self.assertIs(repeated["duplicate"], True)
            self.assertEqual(repeated["event"], first["event"])
            self.assertEqual(repeated["state"], second["state"])
            self.assertEqual(repeated["next"], second["next"])
            self.assertEqual(self.path.read_bytes(), before)
            changed = deepcopy(first_request)
            changed["observations"]["0"] = 1
            self.assert_protocol_error(session, changed)
            wrong_position = deepcopy(first_request)
            wrong_position["position"] = second["state"]["position"]
            self.assert_protocol_error(session, wrong_position)
            self.assertEqual(self.path.read_bytes(), before)

    def test_duplicate_ack_can_be_recovered_after_reopening_process_state(self):
        with LiveSession(self.path) as session:
            request = observe_request(session.ready())
            result = session.handle(request)
        before = self.path.read_bytes()
        with LiveSession(self.path, capacity=8) as reopened:
            self.assertIs(reopened.ready()["restored"], True)
            duplicate = reopened.handle(request)
            self.assertIs(duplicate["duplicate"], True)
            self.assertEqual(duplicate["event"], result["event"])
            self.assertEqual(duplicate["state"], result["state"])
            self.assertEqual(self.path.read_bytes(), before)

    def test_partial_frame_waits_and_new_complete_frame_recovers(self):
        with LiveSession(self.path) as session:
            ready = session.ready()
            partial = observe_request(ready, {"": 0, "0": 0})
            waited = session.handle(partial)
            self.assertEqual((waited["event"]["decision"]["kind"], waited["state"]["status"]),
                             ("WAIT", "WAITING"))
            self.assertEqual(waited["state"]["position"], "")
            self.assertEqual(waited["next"]["seq"], 2)
            again = session.handle(observe_request(waited, {"1": 0}))
            self.assertEqual(again["event"]["decision"]["kind"], "WAIT")
            self.assertEqual(again["state"]["position"], "")
            moved = session.handle(observe_request(again))
            self.assertEqual(moved["event"]["decision"]["kind"], "MOVE")
            self.assertEqual(moved["state"]["position"], "0")

    def test_infeasible_sensor_frame_can_recover_in_same_open_session(self):
        with LiveSession(self.path) as session:
            ready = session.ready()
            blocked = session.handle(observe_request(ready, {"": 0, "0": 127, "1": 127}))
            self.assertEqual(blocked["state"]["status"], "INSUFFICIENT_ENERGY")
            self.assertEqual(blocked["state"]["agent_pair"], ready["state"]["agent_pair"])
            recovered = session.handle(observe_request(blocked))
            self.assertEqual(recovered["state"]["status"], "ACTIVE")
            self.assertEqual(recovered["state"]["position"], "0")

    def test_incremental_planner_progress_survives_live_reopening(self):
        config = LiveConfig(manifest=AgentManifest(max_search_expansions=1))
        with LiveSession(self.path, config=config) as session:
            first = session.handle(observe_request(session.ready()))
            self.assertEqual(first["event"]["decision"]["kind"], "DEFER")
            self.assertEqual(first["state"]["planning"]["expansions"], 1)
        with LiveSession(self.path, capacity=1) as session:
            second = session.handle(observe_request(session.ready()))
            self.assertEqual(second["state"]["planning"]["expansions"], 2)
            completed = finish_live(session)
            self.assertEqual(completed["state"]["status"], "COMPLETE")
        _, restored = load_live(self.path, capacity=8)
        self.assertEqual(restored.snapshot(), completed["state"])

    def test_protocol_source_sequence_and_observation_errors_have_no_effect(self):
        with LiveSession(self.path) as session:
            original = observe_request(session.ready())
            invalid = [None, [], "", {}, {"protocol": PROTOCOL, "type": "status", "extra": 1}]
            for field, values in (
                ("protocol", ["future", None, True]),
                ("type", ["move", "repair", "reset", True]),
                ("producer", ["other-sensor", None, True]),
                ("epoch", [1, -1, True, 0.0, "0"]),
                ("seq", [0, -1, 2, True, 1.0, "1"]),
                ("position", ["0", None, True]),
                ("observations", [None, [], {"00": 0}, {"0": True}, {"0": -1}, {"0": 128}]),
            ):
                for value in values:
                    changed = deepcopy(original)
                    changed[field] = value
                    invalid.append(changed)
            for field in original:
                changed = deepcopy(original)
                changed.pop(field)
                invalid.append(changed)
            for field, value in (("action", "MOVE"), ("route", ["1", "10", "11"]),
                                 ("candidates", [["0", "00", "11"]])):
                changed = deepcopy(original)
                changed[field] = value
                invalid.append(changed)
            before = self.path.read_bytes()
            state = session.handle(status_request())["state"]
            for request in invalid:
                with self.subTest(request=request):
                    self.assert_protocol_error(session, request)
                    self.assertEqual(self.path.read_bytes(), before)
                    self.assertEqual(session.handle(status_request())["state"], state)
            self.assertEqual(session.handle(original)["state"]["cycle"], 1)

    def test_response_and_request_mutations_cannot_change_retained_state(self):
        with LiveSession(self.path) as session:
            ready = session.ready()
            original_ready = deepcopy(ready)
            ready["state"].clear()
            ready["next"]["paths"].append("hidden")
            self.assertEqual(session.ready(), original_ready)
            request = observe_request(original_ready)
            response = session.handle(request)
            original = deepcopy(response)
            before = self.path.read_bytes()
            request["observations"]["0"] = 127
            response["event"]["decision"].clear()
            response["state"].clear()
            response["next"]["paths"].clear()
            state = session.handle(status_request())
            self.assertEqual(state["state"], original["state"])
            self.assertEqual(state["next"], original["next"])
            _, restored = load_live(self.path)
            self.assertEqual(restored.events[-1], original["event"])
            self.assertEqual(self.path.read_bytes(), before)

    def test_resume_configuration_must_match_and_lock_has_one_live_owner(self):
        config = LiveConfig(producer="sensor-a", epoch=9)
        with LiveSession(self.path, config=config) as session:
            session.handle(observe_request(session.ready()))
            with self.assertRaises(AgentBusy):
                with LiveSession(self.path):
                    self.fail("A concurrent writer acquired an owned live state")
        before = self.path.read_bytes()
        incompatible = [LiveConfig(producer="sensor-b", epoch=9),
                        LiveConfig(producer="sensor-a", epoch=10),
                        LiveConfig(manifest=AgentManifest(identity="different"), producer="sensor-a", epoch=9)]
        for other in incompatible:
            with self.subTest(config=other), self.assertRaises(ValueError):
                with LiveSession(self.path, config=other):
                    self.fail("Changed configuration resumed retained state")
            self.assertEqual(self.path.read_bytes(), before)
        with LiveSession(self.path, config=config, capacity=8) as session:
            self.assertEqual(session.ready()["state"]["cycle"], 1)

    def test_public_path_cannot_redirect_writes_into_another_live_owner(self):
        other_path = self.path.parent / "other live state.json"
        with LiveSession(self.path) as first, LiveSession(other_path) as second:
            second_state = second.ready()["state"]
            second_bytes = other_path.read_bytes()
            with self.assertRaises(AttributeError):
                first.path = second.path
            self.assertEqual(first.path, self.path.resolve())
            result = first.handle(observe_request(first.ready()))
            self.assertEqual(result["state"]["cycle"], 1)
            self.assertEqual(read_json(self.path)["agent"]["expected"]["cycle"], 1)
            self.assertEqual(other_path.read_bytes(), second_bytes)
            self.assertEqual(read_json(other_path)["agent"]["expected"]["cycle"], 0)
            self.assertEqual(second.handle(status_request())["state"], second_state)

    def test_concurrent_requests_wait_for_durable_commit_before_replying(self):
        entered_write = Event()
        release_write = Event()
        results, failures, started, finished = {}, {}, {}, {}
        threads = []

        def gated_write(path, value):
            if value["agent"]["expected"]["cycle"] == 1:
                entered_write.set()
                if not release_write.wait(5):
                    raise TimeoutError("Test did not release the pending commit")
            atomic_write_json(path, value)

        def launch(name, operation):
            started[name], finished[name] = Event(), Event()

            def run():
                started[name].set()
                try:
                    results[name] = operation()
                except BaseException as exc:
                    failures[name] = exc
                finally:
                    finished[name].set()

            thread = Thread(target=run, name="live-test-" + name, daemon=True)
            threads.append(thread)
            thread.start()

        with LiveSession(self.path) as session:
            ready = session.ready()
            first_request = observe_request(ready, {})
            second_request = observe_request(ready)
            second_request["seq"] = 2
            with patch("solvefinite.live.write_json", side_effect=gated_write):
                try:
                    launch("first", lambda: session.handle(first_request))
                    self.assertTrue(entered_write.wait(5), "First request never reached its commit")
                    launch("reader", session.ready)
                    launch("retry", lambda: session.handle(first_request))
                    launch("second", lambda: session.handle(second_request))
                    for name in ("reader", "retry", "second"):
                        self.assertTrue(started[name].wait(5), name)
                    for name in ("reader", "retry", "second"):
                        self.assertFalse(finished[name].wait(0.1),
                                         f"{name} replied before the prior cycle committed")
                    self.assertEqual(read_json(self.path)["agent"]["expected"]["cycle"], 0)
                finally:
                    release_write.set()
                    for thread in threads:
                        thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(failures, {})
            self.assertEqual(results["first"]["state"]["cycle"], 1)
            self.assertEqual(results["first"]["event"]["decision"]["kind"], "WAIT")
            self.assertIs(results["retry"]["duplicate"], True)
            self.assertEqual(results["retry"]["event"], results["first"]["event"])
            self.assertIn(results["retry"]["state"]["cycle"], (1, 2))
            self.assertIn(results["reader"]["state"]["cycle"], (1, 2))
            self.assertEqual(results["second"]["state"]["cycle"], 2)
            self.assertEqual(results["second"]["event"]["decision"]["kind"], "MOVE")
            saved = read_json(self.path)["agent"]
            self.assertEqual(saved["expected"], results["second"]["state"])
            self.assertEqual([event["seq"] for event in saved["events"]], [1, 2])
            self.assertEqual(session.ready()["state"], saved["expected"])

    def test_context_exit_waits_for_commit_before_releasing_ownership(self):
        entered_write, release_write = Event(), Event()
        exit_started, exit_finished = Event(), Event()
        results, failures = {}, {}
        session = LiveSession(self.path)
        session.__enter__()
        request = observe_request(session.ready(), {})

        def gated_write(path, value):
            entered_write.set()
            if not release_write.wait(5):
                raise TimeoutError("Test did not release the pending commit")
            atomic_write_json(path, value)

        def accept():
            try:
                results["accepted"] = session.handle(request)
            except BaseException as exc:
                failures["accepted"] = exc

        def close():
            exit_started.set()
            try:
                session.__exit__(None, None, None)
            except BaseException as exc:
                failures["closed"] = exc
            finally:
                exit_finished.set()

        writer = Thread(target=accept, name="live-test-commit", daemon=True)
        closer = Thread(target=close, name="live-test-close", daemon=True)
        try:
            with patch("solvefinite.live.write_json", side_effect=gated_write):
                try:
                    writer.start()
                    self.assertTrue(entered_write.wait(5), "Request never reached its commit")
                    closer.start()
                    self.assertTrue(exit_started.wait(5))
                    self.assertFalse(exit_finished.wait(0.1), "Context exited before commit")
                    self.assertEqual(read_json(self.path)["agent"]["expected"]["cycle"], 0)
                    with self.assertRaises(AgentBusy):
                        with LiveSession(self.path):
                            self.fail("Ownership was released during an uncommitted observation")
                finally:
                    release_write.set()
                    writer.join(5)
                    if closer.ident is not None:
                        closer.join(5)
            self.assertFalse(writer.is_alive())
            self.assertFalse(closer.is_alive())
            self.assertEqual(failures, {})
            self.assertTrue(exit_finished.is_set())
            self.assertEqual(results["accepted"]["state"]["cycle"], 1)
            with LiveSession(self.path) as reopened:
                self.assertEqual(reopened.ready()["state"], results["accepted"]["state"])
                self.assertIs(reopened.handle(request)["duplicate"], True)
        finally:
            release_write.set()
            session.__exit__(None, None, None)

    def test_completion_is_read_only_but_historical_duplicate_is_acknowledged(self):
        with LiveSession(self.path) as session:
            first_request = observe_request(session.ready())
            first = session.handle(first_request)
            completed = finish_live(session)
            self.assertEqual(completed["state"]["status"], "COMPLETE")
            self.assertIsNone(completed["next"])
            before = self.path.read_bytes()
            repeated = session.handle(first_request)
            self.assertIs(repeated["duplicate"], True)
            self.assertEqual(repeated["event"], first["event"])
            self.assertEqual(repeated["state"], completed["state"])
            self.assertIsNone(repeated["next"])
            future = deepcopy(first_request)
            future["seq"] = completed["state"]["cycle"] + 1
            future["position"] = completed["state"]["position"]
            self.assert_protocol_error(session, future)
            self.assertEqual(session.handle(status_request())["state"], completed["state"])
            self.assertEqual(self.path.read_bytes(), before)

    def test_cycle_budget_closes_admission_without_claiming_completion(self):
        config = LiveConfig(manifest=AgentManifest(max_cycles=1))
        with LiveSession(self.path, config=config) as session:
            first_request = observe_request(session.ready())
            exhausted = session.handle(first_request)
            self.assertEqual((exhausted["state"]["cycle"], exhausted["state"]["status"]), (1, "ACTIVE"))
            self.assertIsNone(exhausted["next"])
            before = self.path.read_bytes()
            future = deepcopy(first_request)
            future["seq"] = 2
            future["position"] = "0"
            future["observations"] = {"": 0, "0": 0, "00": 0}
            self.assert_protocol_error(session, future)
            self.assertIs(session.handle(first_request)["duplicate"], True)
            self.assertEqual(self.path.read_bytes(), before)

    def test_write_failure_requires_reopen_and_recovers_only_durable_events(self):
        failed_request = None
        with LiveSession(self.path) as session:
            first = session.handle(observe_request(session.ready()))
            failed_request = observe_request(first)
            before = self.path.read_bytes()
            with patch("solvefinite.live.write_json", side_effect=OSError("injected disk failure")) as writer:
                with self.assertRaisesRegex(OSError, "injected disk failure"):
                    session.handle(failed_request)
                writer.assert_called_once()
                self.assertEqual(writer.call_args.args[1]["agent"]["expected"]["cycle"], 2)
                for operation in (session.ready, lambda: session.handle(status_request()),
                                  lambda: session.handle(failed_request)):
                    with self.assertRaises(RuntimeError):
                        operation()
                writer.assert_called_once()
            self.assertEqual(self.path.read_bytes(), before)
            _, restored = load_live(self.path)
            self.assertEqual(restored.snapshot(), first["state"])
        with LiveSession(self.path, capacity=8) as reopened:
            self.assertEqual(reopened.ready()["state"], first["state"])
            recovered = reopened.handle(failed_request)
            self.assertIs(recovered["duplicate"], False)
            self.assertEqual(recovered["state"]["cycle"], 2)
            self.assertEqual(recovered["state"]["position"], "00")

    def test_failure_after_atomic_replacement_recovers_committed_duplicate(self):
        def committed_then_failed(path, value):
            atomic_write_json(path, value)
            raise OSError("failure after replacement")

        with LiveSession(self.path) as session:
            first = session.handle(observe_request(session.ready()))
            uncertain_request = observe_request(first)
            with patch("solvefinite.live.write_json", side_effect=committed_then_failed):
                with self.assertRaisesRegex(OSError, "failure after replacement"):
                    session.handle(uncertain_request)
            with self.assertRaises(RuntimeError):
                session.handle(status_request())
            durable = read_json(self.path)
            self.assertEqual(durable["agent"]["expected"]["cycle"], 2)
        before = self.path.read_bytes()
        with LiveSession(self.path) as reopened:
            duplicate = reopened.handle(uncertain_request)
            self.assertIs(duplicate["duplicate"], True)
            self.assertEqual(duplicate["event"], durable["agent"]["events"][-1])
            self.assertEqual(duplicate["state"], durable["agent"]["expected"])
            self.assertEqual(duplicate["next"]["seq"], 3)
            self.assertEqual(self.path.read_bytes(), before)

    def test_payload_fsync_failure_keeps_old_file_and_poisoned_owner_cannot_ack(self):
        with LiveSession(self.path) as session:
            first = session.handle(observe_request(session.ready()))
            request = observe_request(first)
            before = self.path.read_bytes()
            with patch("solvefinite.runtime.os.fsync", side_effect=OSError("payload fsync failed")) as sync:
                with self.assertRaisesRegex(OSError, "payload fsync failed"):
                    session.handle(request)
                sync.assert_called_once()
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(list(self.path.parent.glob(self.path.name + ".*.tmp")), [])
            with self.assertRaises(RuntimeError):
                session.ready()
            with self.assertRaises(RuntimeError):
                session.handle(request)
            _, durable = load_live(self.path)
            self.assertEqual(durable.snapshot(), first["state"])
        with LiveSession(self.path) as reopened:
            result = reopened.handle(request)
            self.assertIs(result["duplicate"], False)
            self.assertEqual(result["state"]["cycle"], 2)

    def test_failed_initialization_releases_ownership_and_closed_access_is_rejected(self):
        instance = LiveSession(self.path)
        with self.assertRaises(RuntimeError):
            instance.ready()
        with patch("solvefinite.live.write_json", side_effect=OSError("initialization failure")):
            with self.assertRaisesRegex(OSError, "initialization failure"):
                with instance:
                    self.fail("Initialization failure opened a live owner")
        self.assertFalse(self.path.exists())
        with LiveSession(self.path) as reopened:
            self.assertEqual(reopened.ready()["state"]["cycle"], 0)
        with self.assertRaises(RuntimeError):
            reopened.ready()
        with self.assertRaises(RuntimeError):
            reopened.handle(status_request())

    def test_tampered_live_envelopes_and_agent_history_are_rejected(self):
        with LiveSession(self.path) as session:
            session.handle(observe_request(session.ready()))
        original = read_json(self.path)
        changes = {
            "wrong format": lambda a: a.update(format="other-live-format"),
            "extra field": lambda a: a.update(extra=True),
            "missing config": lambda a: a.pop("config"),
            "changed agent manifest": lambda a: a["agent"]["manifest"].update(identity="imposter"),
            "mismatched configuration manifest": lambda a: a["config"]["agent"].update(identity="other-agent"),
            "changed decision": lambda a: a["agent"]["events"][0]["decision"].update(kind="REPAIR"),
            "changed expected state": lambda a: a["agent"]["expected"].update(position="11"),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            write_json(self.path, damaged)
            before = self.path.read_bytes()
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    load_live(self.path)
                with self.assertRaises(ValueError):
                    with LiveSession(self.path):
                        self.fail("Tampered session reopened")
                self.assertEqual(self.path.read_bytes(), before)

    def test_loading_legacy_policy_does_not_upgrade_its_decisions(self):
        config = LiveConfig(manifest=AgentManifest(policy="tomigidt-observe-plan-act-v1", max_search_expansions=1))
        with LiveSession(self.path, config=config) as session:
            first = session.handle(observe_request(session.ready()))
            self.assertEqual(first["event"]["decision"]["expansions"], 1)
            self.assertNotIn("planning", first["state"])
        with LiveSession(self.path) as session:
            second = session.handle(observe_request(session.ready()))
            self.assertEqual((second["event"]["decision"]["kind"], second["event"]["decision"]["expansions"]),
                             ("DEFER", 1))
            self.assertNotIn("planning", second["state"])
        loaded_config, agent = load_live(self.path)
        self.assertEqual(loaded_config, config)
        self.assertEqual(agent.manifest.policy, "tomigidt-observe-plan-act-v1")


if __name__ == "__main__":
    unittest.main()
