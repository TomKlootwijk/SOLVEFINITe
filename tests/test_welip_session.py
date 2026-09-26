"""W1-W8 durable CPU ownership, private replay and whole-operation failures."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import (
    FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, FieldAgentManifest,
)
from solvefinite.runtime import write_json
from solvefinite.navigation import NoRoute
from solvefinite.session import AgentBusy, StateLock
from solvefinite.tomigidt import Tomigidt
from solvefinite.welip import WelipConfig, PROTOCOL
from solvefinite.welip_session import WelipProtocolError, WelipSession, serve


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "docs/evidence/welip-v1/formal-reference.json").read_text(encoding="utf-8"))
MAIN = REFERENCE["main_lifecycle"]
COMMON = {"protocol", "type", "producer", "producer_epoch", "head", "next"}


def request_for(response, operation, **extra):
    cursor = response["next"]
    request = {"protocol": PROTOCOL, "op": operation, "producer": response["producer"],
               "producer_epoch": response["producer_epoch"]}
    request.update({key: cursor[key] for key in
                    ("seq", "clock_epoch", "tick16", "agent_cycle", "geometry_epoch")})
    if operation == "ADVANCE":
        request.update(position=cursor["position"], observations=dict.fromkeys(cursor["visible_paths"], 0))
    request.update(extra)
    return request


def semantic_state(session):
    agent, world = session._agent, session._agent.world
    return (agent.archive(), deepcopy(session._rows), world.capacity, world.active_paths,
            world.evicted_paths, world.hit_count, world.regeneration_count,
            agent.current_recipe, world.index, session.ready())


class WelipSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="welip-session-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "owner.json"
        self.config = WelipConfig.from_dict(MAIN["config"])

    def read(self, path=None):
        return json.loads((self.path if path is None else path).read_text(encoding="utf-8"))

    def prefix(self, session, count):
        for row, expected in zip(MAIN["operations"][:count], MAIN["results"][:count]):
            self.assertEqual(session.handle(deepcopy(row["request"])), expected)
        return session.ready()

    def reject(self, session, request, code):
        before, saved = semantic_state(session), session.path.read_bytes()
        with patch.object(session._agent, "emit_welip_state", wraps=session._agent.emit_welip_state) as emit:
            with patch("solvefinite.welip_session.write_json", wraps=write_json) as save:
                with self.assertRaises(WelipProtocolError) as caught:
                    session.handle(request)
                self.assertEqual((caught.exception.code, caught.exception.fatal), (code, False))
                emit.assert_not_called()
                save.assert_not_called()
        self.assertEqual(semantic_state(session), before)
        self.assertEqual(session.path.read_bytes(), saved)
        error = session.error(caught.exception)
        self.assertEqual(set(error), COMMON | {"code", "message", "fatal"})
        self.assertEqual((error["head"], error["next"]), (before[-1]["head"], before[-1]["next"]))

    def assert_poisoned(self, session, request):
        self.assertTrue(session._agent.closed)
        for action in (session.ready, lambda: session.handle(request)):
            with self.assertRaises(WelipProtocolError) as caught:
                action()
            self.assertEqual((caught.exception.code, caught.exception.fatal), ("OWNER_FAILED", True))
            error = session.error(caught.exception)
            self.assertIsNone(error["head"])
            self.assertIsNone(error["next"])
        with self.assertRaises(AgentBusy):
            with StateLock(session.path):
                self.fail("Failed W owner released its path lock before context exit")

    def test_genesis_is_saved_once_before_ready_and_never_implicitly_ignites(self):
        with patch("solvefinite.welip_session.write_json", wraps=write_json) as save:
            with WelipSession(self.path, self.config) as session:
                self.assertEqual(session.ready(), MAIN["ready"])
                self.assertEqual(save.call_count, 1)
                saved = self.read()
                self.assertEqual(saved["operations"], [])
                self.assertEqual(saved["expected"], MAIN["genesis"])
                self.assertEqual(saved["agent"]["events"], [])
        before = self.path.read_bytes()
        with patch("solvefinite.welip_session.write_json", wraps=write_json) as save:
            with WelipSession(self.path) as reopened:
                self.assertTrue(reopened.ready()["restored"])
                save.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrong_root_archive_and_config_mismatch_reject_before_owner_allocation(self):
        for value in (None, True, 0, [], "", {}, {"format": "welip-field-session-v1"}):
            write_json(self.path, value)
            before = self.path.read_bytes()
            with self.subTest(root=value), patch("solvefinite.welip_session.Tomigidt") as allocate:
                with self.assertRaises(ValueError):
                    with WelipSession(self.path):
                        self.fail("An invalid existing archive opened")
                allocate.assert_not_called()
                self.assertEqual(self.path.read_bytes(), before)
                with StateLock(self.path):
                    pass
        self.path.unlink()
        with WelipSession(self.path, self.config):
            pass
        for changed in (replace(self.config, initial_capacity=4), replace(self.config, producer="other"),
                        replace(self.config, clock_origin=65529), replace(self.config, max_events=63),
                        replace(self.config, manifest=replace(self.config.manifest, initial_energy=99))):
            with self.subTest(config=changed), patch("solvefinite.welip_session.Tomigidt") as allocate:
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    with WelipSession(self.path, changed):
                        self.fail("A replacement configuration was allocated")
                allocate.assert_not_called()
                self.assertEqual(self.path.read_bytes(), before)

    def test_constructor_rejects_rebinding_capacity_and_bad_adapters(self):
        for options in ({"config": {}}, {"backend": True}, {"backend": "future"},
                        {"index_binding": {}}, {"capacity": 4}):
            with self.subTest(options=options), self.assertRaises((ValueError, TypeError)):
                WelipSession(self.path, **options)
        self.assertFalse(self.path.exists())

    def test_failed_genesis_closes_allocated_owner_and_releases_path(self):
        allocated = []
        def make_agent(*args, **kwargs):
            agent = Tomigidt(*args, **kwargs)
            allocated.append(agent)
            return agent
        with patch("solvefinite.welip_session.Tomigidt", side_effect=make_agent), \
                patch("solvefinite.welip_session.write_json", side_effect=OSError("genesis storage failed")):
            with self.assertRaises(OSError):
                with WelipSession(self.path, self.config):
                    self.fail("Genesis failure acknowledged an owner")
        self.assertEqual(len(allocated), 1)
        self.assertTrue(allocated[0].closed)
        self.assertFalse(self.path.exists())
        with WelipSession(self.path, self.config) as session:
            self.assertEqual(session.ready(), MAIN["ready"])
        with self.assertRaises(RuntimeError):
            session.ready()

    def test_all_three_frozen_lifecycles_reopen_every_operation_without_public_replay(self):
        for name in ("main_lifecycle", "mirrored_lifecycle", "capacity8_lifecycle"):
            reference = REFERENCE[name]
            path = self.directory / (name + ".json")
            config = WelipConfig.from_dict(reference["config"])
            with self.subTest(lifecycle=name):
                for index, (row, result, duplicate) in enumerate(zip(reference["operations"], reference["results"],
                                                                   reference["latest_retry_receipts"])):
                    with WelipSession(path, config if index == 0 else None,
                                      index_binding=IndexBinding(epoch=index, psi_sign=-1, phase_origin=91)) as session:
                        self.assertEqual(session.handle(deepcopy(row["request"])), result)
                        before = path.read_bytes()
                        with patch.object(session._agent, "step", side_effect=AssertionError("duplicate step")), \
                                patch.object(session._agent, "emit_welip_state", side_effect=AssertionError("duplicate emission")), \
                                patch("solvefinite.welip_session.write_json", side_effect=AssertionError("duplicate save")):
                            self.assertEqual(session.handle(dict(reversed(list(row["request"].items())))), duplicate)
                        self.assertEqual(path.read_bytes(), before)
                        self.assertEqual(self.read(path)["operations"], reference["operations"][:index + 1])
                saved = self.read(path)
                self.assertEqual(saved["expected"], reference["expected"])
                self.assertEqual(len(saved["agent"]["events"]), 9)

    def test_private_recovery_preserves_interleaved_capacity_and_original_grow_context(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 10)
            original = self.read()
            self.assertEqual(original["expected"]["cache"]["capacity"], 1)
            self.assertEqual(original["config"]["initial_capacity"], 3)
            self.assertEqual(original["expected"]["cache"]["active_paths"], [])
            self.assertEqual(original["agent"]["events"][-1]["seq"], 5)
        with patch("solvefinite.welip_session.write_json", side_effect=AssertionError("recovery must not save")):
            with WelipSession(self.path, self.config) as reopened:
                self.assertEqual(reopened._agent.archive(), original["agent"])
                self.assertEqual(reopened._cache(), original["expected"]["cache"])
                self.assertEqual(reopened.ready()["head"], MAIN["results"][9]["head"])
        self.assertEqual(self.read(), original)

    def test_strict_common_request_domains_and_static_checks_precede_retry(self):
        with WelipSession(self.path, self.config) as session:
            ignition = deepcopy(MAIN["operations"][0]["request"])
            session.handle(ignition)
            for key in ("producer_epoch", "seq", "clock_epoch", "tick16", "agent_cycle", "geometry_epoch"):
                for invalid in (True, float(ignition[key]), str(ignition[key]), None, -1):
                    with self.subTest(key=key, invalid=invalid):
                        self.reject(session, dict(ignition, **{key: invalid}), "INVALID_REQUEST")
            bad = [None, [], dict(ignition, unknown=0), {k: v for k, v in ignition.items() if k != "payload"},
                   dict(ignition, protocol=True), dict(ignition, payload="ff"), dict(ignition, payload="0"),
                   dict(ignition, payload="00" * 4097), dict(ignition, producer=" spaced "),
                   dict(ignition, producer_epoch=1 << 32), dict(ignition, tick16=65536),
                   dict(ignition, clock_epoch=1 << 32), dict(ignition, seq=66),
                   dict(ignition, agent_cycle=10001), dict(ignition, geometry_epoch=2)]
            for request in bad:
                with self.subTest(request=request):
                    self.reject(session, request, "INVALID_REQUEST")
            class Protocol(str):
                pass
            self.reject(session, dict(ignition, protocol=Protocol(PROTOCOL)), "INVALID_REQUEST")
            self.reject(session, dict(ignition, producer="other"), "SOURCE_MISMATCH")
            self.reject(session, dict(ignition, producer_epoch=8), "SOURCE_MISMATCH")
            self.reject(session, dict(ignition, payload="00"), "CONFLICT")

    def test_forward_denial_order_budget_clock_context_and_ignition_precedence(self):
        with WelipSession(self.path, self.config) as session:
            for op in ("READ", "HISTORY", "REPLAY", "REGENERATE"):
                self.reject(session, {"protocol": PROTOCOL, "op": op, "junk": True}, "BACKWARD_READ")
            self.reject(session, {"protocol": "other", "op": "READ"}, "INVALID_REQUEST")
            for op in ("STATUS", "inspect", "derive_epoch", "reindex"):
                self.reject(session, {"protocol": PROTOCOL, "op": op}, "INVALID_REQUEST")
            emit = request_for(session.ready(), "EMIT")
            self.reject(session, dict(emit, seq=3), "SEQUENCE_GAP")
            self.reject(session, dict(emit, tick16=0, agent_cycle=1), "CLOCK_MISMATCH")
            self.reject(session, dict(emit, agent_cycle=1), "CONTEXT_MISMATCH")
            self.reject(session, emit, "NOT_IGNITED")
            first = session.handle(request_for(session.ready(), "IGNITE", payload=""))
            self.reject(session, request_for(first, "IGNITE", payload=""), "ALREADY_IGNITED")
            second = session.handle(request_for(first, "EMIT"))
            stale = deepcopy(MAIN["operations"][0]["request"])
            self.reject(session, stale, "STALE_SEQUENCE")
            self.reject(session, dict(request_for(second, "EMIT"), seq=4), "SEQUENCE_GAP")
        path = self.directory / "max-clock.json"
        config = replace(self.config, clock_origin=(1 << 48) - 2, max_events=1)
        with WelipSession(path, config) as session:
            original = request_for(session.ready(), "IGNITE", payload="")
            session.handle(original)
            next_request = dict(original, op="EMIT", seq=2, tick16=0)
            next_request.pop("payload")
            self.reject(session, next_request, "BUDGET_EXHAUSTED")
            self.assertEqual(session.handle(original)["type"], "DUPLICATE")

    def test_dynamic_selectors_are_checked_only_after_static_and_current_context(self):
        with WelipSession(self.path, self.config) as session:
            response = session.handle(deepcopy(MAIN["operations"][0]["request"]))
            advance = request_for(response, "ADVANCE")
            self.reject(session, dict(advance, position="k:00:0"), "INVALID_REQUEST")
            self.reject(session, dict(advance, position="k:9:9", observations={"k:9:9": 0}), "CONTEXT_MISMATCH")
            self.reject(session, dict(advance, observations={"k:9:9": 0}), "INVALID_SELECTOR")
            for hazard in (True, 0.0, -1, 128, "0", None):
                self.reject(session, dict(advance, observations={"k:0:0": hazard}), "INVALID_REQUEST")
            response = session.handle(advance)
            paths = sorted(response["next"]["active_paths"])
            self.assertTrue(paths)
            original = request_for(response, "INVALIDATE", paths=[paths[0]], cause="release")
            for selector in ([], tuple(paths), [paths[0], paths[0]], paths[::-1], ["k:00:0"]):
                if selector == sorted(set(selector)) and type(selector) is list and selector:
                    continue
                self.reject(session, dict(original, paths=selector), "INVALID_REQUEST")
            self.reject(session, dict(original, paths=sorted({paths[0], "k:9:9"})), "INVALID_SELECTOR")
            for cause in ("", " padded ", "x" * 129, True):
                self.reject(session, dict(original, cause=cause), "INVALID_REQUEST")
            admitted = session.handle(original)
            self.assertNotIn(paths[0], admitted["next"]["active_paths"])
            self.assertEqual(session.handle(original)["type"], "DUPLICATE")

    def test_wait_and_cycle_bound_preserve_owner_while_controls_remain_available(self):
        config = replace(self.config, manifest=replace(self.config.manifest, max_cycles=1))
        with WelipSession(self.path, config) as session:
            first = session.handle(request_for(session.ready(), "IGNITE", payload=""))
            initial = first["records"][-1]
            waited = session.handle(request_for(first, "ADVANCE", observations={}))
            self.assertEqual(waited["agent_status"], "WAITING")
            self.assertEqual((waited["records"][0]["energy"], waited["records"][0]["phase16"]),
                             (initial["energy"], initial["phase16"]))
            self.assertNotIn("ADVANCE", waited["next"]["allowed_ops"])
            self.reject(session, request_for(waited, "ADVANCE"), "AGENT_BOUND")
            resized = session.handle(request_for(waited, "RESIZE", capacity=7))
            emitted = session.handle(request_for(resized, "EMIT"))
            self.assertEqual((emitted["head"]["agent_cycle"], emitted["cache"]["capacity"]), (1, 7))

    def test_terminal_agent_allows_controls_and_new_emission_but_no_new_action(self):
        with WelipSession(self.path, self.config) as session:
            response = self.prefix(session, 17)
            pair, energy = session._agent.agent_pair, session._agent.energy
            self.reject(session, request_for(response, "ADVANCE"), "AGENT_COMPLETE")
            resized = session.handle(request_for(response, "RESIZE", capacity=1))
            invalidated = session.handle(request_for(resized, "INVALIDATE",
                                                     paths=sorted(resized["next"]["active_paths"]), cause="release terminal local copy"))
            emitted = session.handle(request_for(invalidated, "EMIT"))
            self.assertEqual((session._agent.agent_pair, session._agent.energy), (pair, energy))
            self.assertEqual(emitted["head"]["agent_cycle"], 9)
            self.assertEqual(emitted["cache"]["active_paths"], [])

    def test_deferred_search_survives_wait_cache_controls_reopen_and_original_grow_time(self):
        manifest = replace(self.config.manifest, max_search_expansions=1)
        config = replace(self.config, manifest=manifest, max_events=512)
        reference = Tomigidt(manifest, config.initial_capacity)
        self.addCleanup(reference.close)
        saw_growth = False
        # Reopen across unfinished searches as well as later movement; W-only
        # time must not enter the retained agent prefix or grammar GROW tick.
        for stop in (1, 2, 20, 40, 60, 100):
            with WelipSession(self.path, config if stop == 1 else None,
                              index_binding=IndexBinding(epoch=stop, psi_sign=-1, phase_origin=37)) as session:
                if stop == 1:
                    session.handle(request_for(session.ready(), "IGNITE", payload=""))
                self.assertEqual(session._agent.archive(), reference.archive())
                while reference.cycle < stop and reference.status != "COMPLETE":
                    request = request_for(session.ready(), "ADVANCE")
                    if reference.cycle == 1:
                        request["observations"] = {}
                        pending = reference.snapshot()["planning"]
                    decision = reference.step(request["observations"])
                    response = session.handle(request)
                    self.assertEqual(session._agent.archive(), reference.archive())
                    if decision.kind == "DEFER":
                        self.assertEqual(response["agent_status"], "SEARCH_DEFERRED")
                        self.assertTrue(session._agent.pending_search)
                    if reference.cycle == 2:
                        self.assertEqual(decision.kind, "WAIT")
                        self.assertEqual(session._agent.snapshot()["planning"], pending)
                    saw_growth |= decision.kind == "GROW"
                    admitted = session._agent.archive()
                    response = session.handle(request_for(response, "EMIT"))
                    if reference.cycle % 7 == 0:
                        response = session.handle(request_for(response, "RESIZE", capacity=1 + reference.cycle % 4))
                        if response["next"]["active_paths"]:
                            session.handle(request_for(response, "INVALIDATE",
                                                       paths=sorted(response["next"]["active_paths"]),
                                                       cause="release deferred local copies"))
                    self.assertEqual(session._agent.archive(), admitted)
        self.assertEqual(reference.status, "COMPLETE")
        self.assertTrue(saw_growth)
        self.assertEqual(self.read()["agent"], reference.archive())
        self.assertGreater(self.read()["expected"]["seq"], reference.cycle)

    def test_insufficient_energy_reopens_and_recovers_after_fresh_local_hazards(self):
        config = replace(self.config, manifest=FieldAgentManifest(initial_energy=10))
        with WelipSession(self.path, config) as session:
            first = session.handle(request_for(session.ready(), "IGNITE", payload=""))
            request = request_for(first, "ADVANCE")
            request["observations"] = dict.fromkeys(first["next"]["visible_paths"], 70)
            blocked = session.handle(request)
            self.assertEqual(blocked["agent_status"], "INSUFFICIENT_ENERGY")
            self.assertEqual(session._agent.energy, 10)
            self.assertIn("ADVANCE", blocked["next"]["allowed_ops"])
            original_pair = session._agent.agent_pair
        with WelipSession(self.path) as reopened:
            self.assertEqual((reopened._agent.agent_pair, reopened._agent.energy), (original_pair, 10))
            waited = reopened.handle(request_for(reopened.ready(), "ADVANCE", observations={}))
            self.assertEqual(waited["agent_status"], "WAITING")
            self.assertEqual((reopened._agent.agent_pair, reopened._agent.energy), (original_pair, 10))
            response = reopened.handle(request_for(waited, "ADVANCE"))
            self.assertEqual(response["agent_status"], "ACTIVE")
            for _ in range(10):
                if response["agent_status"] == "COMPLETE":
                    break
                response = reopened.handle(request_for(response, "ADVANCE"))
            self.assertEqual((response["agent_status"], reopened._agent.energy), ("COMPLETE", 0))

    def test_injected_unreachable_is_nonterminal_and_admits_fresh_observations_after_reopen(self):
        # Every currently admitted Klein graph is connected. Inject the
        # existing planner's NoRoute outcome to test this public status branch;
        # this fixture is not evidence of a disconnected supported field.
        config = replace(self.config, manifest=FieldAgentManifest())
        with WelipSession(self.path, config) as session:
            response = session.handle(request_for(session.ready(), "IGNITE", payload=""))
            original_pair = session._agent.agent_pair
            with patch("solvefinite.tomigidt.RouteSearch.start", side_effect=NoRoute("injected disconnected planner outcome")):
                response = session.handle(request_for(response, "ADVANCE"))
            self.assertEqual(response["agent_status"], "UNREACHABLE")
            self.assertIn("ADVANCE", response["next"]["allowed_ops"])
        # Private reconstruction must reproduce the same synthetic planner
        # outcome. Release the injection before fresh observations recover.
        with patch("solvefinite.tomigidt.RouteSearch.start", side_effect=NoRoute("injected disconnected planner outcome")):
            reopened = WelipSession(self.path).__enter__()
        try:
            self.assertEqual(reopened.ready()["next"]["agent_status"], "UNREACHABLE")
            waited = reopened.handle(request_for(reopened.ready(), "ADVANCE", observations={"k:0:0": 1}))
            self.assertEqual(waited["agent_status"], "WAITING")
            self.assertEqual((reopened._agent.agent_pair, reopened._agent.energy), (original_pair, 100))
            fresh = request_for(waited, "ADVANCE")
            response = reopened.handle(fresh)
            self.assertEqual(response["agent_status"], "ACTIVE")
            self.assertNotEqual(reopened._agent.agent_pair, original_pair)
            self.assertEqual((reopened._agent.energy, reopened._agent.cycle), (98, 3))
            self.assertEqual(response["head"]["seq"], 4)
            emitted = reopened.handle(request_for(response, "EMIT"))
            self.assertEqual(emitted["head"]["agent_cycle"], 3)
        finally:
            reopened.__exit__(None, None, None)

    def test_all_profiles_preserve_the_existing_agent_archive_projection(self):
        for policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            config = replace(self.config, manifest=FieldAgentManifest(policy=policy))
            path = self.directory / (policy + ".json")
            reference = Tomigidt(config.manifest, config.initial_capacity)
            self.addCleanup(reference.close)
            with self.subTest(policy=policy), WelipSession(path, config) as session:
                response = session.handle(request_for(session.ready(), "IGNITE", payload="00"))
                while reference.status != "COMPLETE":
                    request = request_for(response, "ADVANCE")
                    reference.step(request["observations"])
                    response = session.handle(request)
                    self.assertEqual(session._agent.archive(), reference.archive())
                    response = session.handle(request_for(response, "EMIT"))
                saved = self.read(path)
                self.assertEqual(saved["agent"], reference.archive())
            with WelipSession(path) as reopened:
                self.assertEqual(reopened._agent.archive(), reference.archive())

    def test_external_request_and_response_mutation_cannot_change_retained_history(self):
        with WelipSession(self.path, self.config) as session:
            ready = session.ready()
            ready["next"]["allowed_ops"].clear()
            ready["next"]["visible_paths"].append("k:9:9")
            ready["head"]["seq"] = 99
            self.assertEqual(session.ready(), MAIN["ready"])
            first = session.handle(deepcopy(MAIN["operations"][0]["request"]))
            request = request_for(first, "ADVANCE")
            original_request = deepcopy(request)
            reply = session.handle(request)
            saved, before = self.path.read_bytes(), semantic_state(session)
            request["observations"].clear()
            request["position"] = "k:9:9"
            reply["records"][0]["words"].clear()
            reply["records"][0]["energy"] = 0
            reply["cache"]["active_paths"].clear()
            reply["next"]["active_paths"].append("k:9:9")
            reply["head"]["seq"] = 99
            self.assertEqual(semantic_state(session), before)
            self.assertEqual(self.path.read_bytes(), saved)
            self.assertEqual(session.handle(original_request)["type"], "DUPLICATE")

    def test_concurrent_identical_requests_execute_emit_and_save_exactly_once(self):
        with WelipSession(self.path, self.config) as session:
            first = session.handle(deepcopy(MAIN["operations"][0]["request"]))
            request = request_for(first, "ADVANCE")
            barrier = Barrier(8)
            def submit():
                barrier.wait(timeout=5)
                return session.handle(request)
            with patch.object(session._agent, "step", wraps=session._agent.step) as step, \
                    patch.object(session._agent, "emit_welip_state", wraps=session._agent.emit_welip_state) as emit, \
                    patch("solvefinite.welip_session.write_json", wraps=write_json) as save:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    outcomes = list(pool.map(lambda _: submit(), range(8)))
                self.assertEqual([x["type"] for x in outcomes].count("RESULT"), 1)
                self.assertEqual([x["type"] for x in outcomes].count("DUPLICATE"), 7)
                step.assert_called_once()
                emit.assert_called_once()
                save.assert_called_once()
            self.assertEqual((len(self.read()["operations"]), session._agent.cycle), (2, 1))

    def test_readiness_and_duplicate_wait_for_the_same_durable_save_boundary(self):
        with WelipSession(self.path, self.config) as session:
            first = session.handle(deepcopy(MAIN["operations"][0]["request"]))
            request = request_for(first, "ADVANCE")
            entered, release, reading = Event(), Event(), Event()
            def delayed_save(path, value):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test did not release save")
                write_json(path, value)
            def read_ready():
                reading.set()
                return session.ready()
            with patch("solvefinite.welip_session.write_json", side_effect=delayed_save):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    pending = pool.submit(session.handle, request)
                    self.assertTrue(entered.wait(5))
                    ready = pool.submit(read_ready)
                    duplicate = pool.submit(session.handle, request)
                    try:
                        self.assertTrue(reading.wait(2))
                        self.assertFalse(ready.done())
                        self.assertFalse(duplicate.done())
                    finally:
                        release.set()
                    result = pending.result(timeout=5)
                    self.assertEqual(ready.result(timeout=5)["head"], result["head"])
                    self.assertEqual(duplicate.result(timeout=5)["type"], "DUPLICATE")

    def test_archive_tampering_is_rejected_without_rewriting_or_leaking_the_lock(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 10)
        original = self.read()
        mutations = {
            "extra archive key": lambda a: a.update(extra=0),
            "missing expected": lambda a: a.pop("expected"),
            "wrong archive format": lambda a: a.update(format="future"),
            "extra config key": lambda a: a["config"].update(extra=0),
            "bool initial capacity": lambda a: a["config"].update(initial_capacity=True),
            "changed initial capacity": lambda a: a["config"].update(initial_capacity=1),
            "rows wrong shape": lambda a: a.update(operations={}),
            "duplicate row": lambda a: a["operations"].append(deepcopy(a["operations"][-1])),
            "row extra key": lambda a: a["operations"][0].update(extra=0),
            "row missing key": lambda a: a["operations"][0].pop("status"),
            "row float energy": lambda a: a["operations"][0].update(energy=100.0),
            "row boolean energy": lambda a: a["operations"][0].update(energy=True),
            "row swapped pair": lambda a: a["operations"][0].update(agent_pair="01FE00FA91FE0006"),
            "changed request": lambda a: a["operations"][1]["request"]["observations"].update({"k:0:0": 70}),
            "record extra key": lambda a: a["operations"][0]["records"][0].update(extra=0),
            "record boolean seq": lambda a: a["operations"][0]["records"][0].update(operation_seq=True),
            "record float length": lambda a: a["operations"][0]["records"][0].update(byte_length=9.0),
            "record boolean zero": lambda a: a["operations"][0]["records"][0].update(agent_cycle=False),
            "record wrong energy": lambda a: a["operations"][0]["records"][0].update(energy=99),
            "cache extra key": lambda a: a["operations"][1]["cache"].update(extra=0),
            "cache bool zero": lambda a: a["operations"][1]["cache"].update(hit_count=False),
            "cache float zero": lambda a: a["operations"][1]["cache"].update(regeneration_count=0.0),
            "cache wrong FIFO": lambda a: a["operations"][1]["cache"]["active_paths"].reverse(),
            "lost invalidation witness": lambda a: a["operations"][4]["cache"].update(removed=[]),
            "expected extra key": lambda a: a["expected"].update(extra=0),
            "expected missing key": lambda a: a["expected"].pop("cache"),
            "expected boolean seq": lambda a: a["expected"].update(seq=True),
            "expected integer ignition": lambda a: a["expected"].update(ignited=1),
            "expected float cache": lambda a: a["expected"]["cache"].update(capacity=1.0),
            "expected obsolete removal": lambda a: a["expected"]["cache"].update(removed=["k:3:0"]),
            "agent extra key": lambda a: a["agent"].update(extra=0),
            "agent altered event": lambda a: a["agent"]["events"][0].update(energy=99),
            "agent altered expected": lambda a: a["agent"]["expected"].update(energy=84),
        }
        for label, mutate in mutations.items():
            altered = deepcopy(original)
            mutate(altered)
            write_json(self.path, altered)
            before = self.path.read_bytes()
            with self.subTest(tamper=label):
                with self.assertRaises(ValueError):
                    with WelipSession(self.path):
                        self.fail("Tampered archive was admitted")
                self.assertEqual(self.path.read_bytes(), before)
                with StateLock(self.path):
                    pass

    def test_save_failure_before_replace_preserves_disk_and_requires_reopen(self):
        with WelipSession(self.path, self.config) as session:
            response = self.prefix(session, 1)
            request = request_for(response, "ADVANCE")
            before = self.path.read_bytes()
            with patch("solvefinite.welip_session.write_json", side_effect=OSError("before replacement")):
                with self.assertRaises(WelipProtocolError) as caught:
                    session.handle(request)
            self.assertEqual((caught.exception.code, caught.exception.fatal), ("STORAGE_FAILED", True))
            self.assertEqual(self.path.read_bytes(), before)
            self.assert_poisoned(session, request)
        with WelipSession(self.path) as reopened:
            self.assertEqual(reopened.ready()["head"]["agent_cycle"], 0)
            self.assertEqual(reopened.handle(request)["type"], "RESULT")
            self.assertEqual(reopened._agent.cycle, 1)

    def test_save_failure_after_replace_recovers_committed_minimal_duplicate(self):
        def committed_then_failed(path, value):
            write_json(path, value)
            raise OSError("after replacement")
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 1)
            request = request_for(session.ready(), "ADVANCE")
            with patch("solvefinite.welip_session.write_json", side_effect=committed_then_failed):
                with self.assertRaises(WelipProtocolError) as caught:
                    session.handle(request)
            self.assertEqual(caught.exception.code, "STORAGE_FAILED")
            self.assert_poisoned(session, request)
            self.assertEqual(self.read()["expected"]["seq"], 2)
        saved = self.path.read_bytes()
        with WelipSession(self.path) as reopened:
            with patch.object(reopened._agent, "step", side_effect=AssertionError("committed action repeated")), \
                    patch.object(reopened._agent, "emit_welip_state", side_effect=AssertionError("retry emitted old payload")), \
                    patch("solvefinite.welip_session.write_json", side_effect=AssertionError("retry wrote archive")):
                duplicate = reopened.handle(request)
                self.assertEqual(set(duplicate), COMMON | {"seq"})
                self.assertEqual(duplicate["type"], "DUPLICATE")
            self.assertEqual(self.path.read_bytes(), saved)

    def test_fsync_and_atomic_replace_failures_leave_no_temporary_artifact(self):
        for boundary in ("os.fsync", "os.replace"):
            path = self.directory / (boundary + ".json")
            with self.subTest(boundary=boundary), WelipSession(path, self.config) as session:
                first = session.handle(deepcopy(MAIN["operations"][0]["request"]))
                request = request_for(first, "ADVANCE")
                before = path.read_bytes()
                with patch("solvefinite.runtime." + boundary, side_effect=OSError("storage boundary failed")):
                    with self.assertRaises(WelipProtocolError) as caught:
                        session.handle(request)
                self.assertEqual(caught.exception.code, "STORAGE_FAILED")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(path.parent.glob(path.name + ".*.tmp")), [])
                self.assert_poisoned(session, request)

    def test_complete_malformed_output_before_controls_leaves_whole_prestate_unchanged(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 2)
            requests = [request_for(session.ready(), "EMIT"),
                        request_for(session.ready(), "RESIZE", capacity=1),
                        request_for(session.ready(), "INVALIDATE", paths=sorted(session._agent.world.active_paths)[:1],
                                    cause="release local copy")]
            for request in requests:
                before, saved = semantic_state(session), self.path.read_bytes()
                with self.subTest(operation=request["op"]), \
                        patch.object(session._agent, "emit_welip_state", return_value=(0, ["0000000000000000"])), \
                        patch("solvefinite.welip_session.write_json", side_effect=AssertionError("bad emission saved")):
                    with self.assertRaises(WelipProtocolError) as caught:
                        session.handle(request)
                    self.assertEqual((caught.exception.code, caught.exception.fatal), ("MALFORMED_EMISSION", False))
                self.assertEqual(semantic_state(session), before)
                self.assertEqual(self.path.read_bytes(), saved)
            self.assertEqual(session.handle(requests[-1])["type"], "RESULT")

    def test_malformed_output_after_move_or_grow_poison_and_replay_prior_geometry(self):
        for prefix in (1, 9):
            path = self.directory / f"bad-output-{prefix}.json"
            with self.subTest(prefix=prefix), WelipSession(path, self.config) as session:
                self.prefix(session, prefix)
                request = deepcopy(MAIN["operations"][prefix]["request"])
                before = path.read_bytes()
                old_geometry = session._agent.geometry_epoch
                with patch.object(session._agent, "emit_welip_state", return_value=(0, [])):
                    with self.assertRaises(WelipProtocolError) as caught:
                        session.handle(request)
                self.assertEqual((caught.exception.code, caught.exception.fatal), ("OWNER_FAILED", True))
                self.assertEqual(path.read_bytes(), before)
                self.assert_poisoned(session, request)
            with WelipSession(path) as reopened:
                self.assertEqual(reopened._agent.geometry_epoch, old_geometry)
                self.assertEqual(reopened.handle(request), MAIN["results"][prefix])

    def test_failure_after_cache_mutation_poison_preserves_prior_durable_fifo(self):
        for operation, method in (("RESIZE", "resize_welip_cache"), ("INVALIDATE", "invalidate_welip_cache")):
            path = self.directory / (operation + "-failed.json")
            with self.subTest(operation=operation), WelipSession(path, self.config) as session:
                self.prefix(session, 2)
                request = (request_for(session.ready(), operation, capacity=1) if operation == "RESIZE" else
                           request_for(session.ready(), operation, paths=sorted(session._agent.world.active_paths)[:1], cause="release"))
                before, cache = path.read_bytes(), session._cache()
                original = getattr(session._agent, method)
                def mutate_then_fail(*args):
                    original(*args)
                    raise RuntimeError("cache cleanup failed after mutation")
                with patch.object(session._agent, method, side_effect=mutate_then_fail):
                    with self.assertRaises(WelipProtocolError) as caught:
                        session.handle(request)
                self.assertEqual(caught.exception.code, "OWNER_FAILED")
                self.assertNotEqual(session._cache(), cache)
                self.assertEqual(path.read_bytes(), before)
                self.assert_poisoned(session, request)
            with WelipSession(path) as reopened:
                self.assertEqual(reopened._cache(), cache)
                self.assertEqual(reopened.handle(request)["type"], "RESULT")

    def test_interrupt_after_owner_or_cache_mutation_closes_owner_until_context_exit(self):
        for failure in (KeyboardInterrupt, SystemExit):
            for operation, prefix, method in (("MOVE", 1, "step"), ("GROW", 9, "step"),
                                              ("RESIZE", 2, "resize_welip_cache"),
                                              ("INVALIDATE", 2, "invalidate_welip_cache")):
                path = self.directory / f"interrupt-{failure.__name__}-{operation}.json"
                with self.subTest(failure=failure.__name__, operation=operation), WelipSession(path, self.config) as session:
                    self.prefix(session, prefix)
                    if operation in ("MOVE", "GROW"):
                        request = deepcopy(MAIN["operations"][prefix]["request"])
                    elif operation == "RESIZE":
                        request = request_for(session.ready(), operation, capacity=1)
                    else:
                        request = request_for(session.ready(), operation, paths=sorted(session._agent.world.active_paths)[:1], cause="release")
                    before = path.read_bytes()
                    original = getattr(session._agent, method)
                    def mutate_then_interrupt(*args):
                        original(*args)
                        raise failure("interrupted after mutation")
                    with patch.object(session._agent, method, side_effect=mutate_then_interrupt):
                        with self.assertRaises(WelipProtocolError) as caught:
                            session.handle(request)
                    self.assertEqual((caught.exception.code, caught.exception.fatal), ("OWNER_FAILED", True))
                    self.assertEqual(path.read_bytes(), before)
                    self.assert_poisoned(session, request)
                with WelipSession(path) as reopened:
                    self.assertEqual(reopened.handle(request)["type"], "RESULT")

    def test_interrupt_during_save_before_or_after_replace_uses_disk_on_reopen(self):
        for failure in (KeyboardInterrupt, SystemExit):
            for replaced in (False, True):
                path = self.directory / f"save-{failure.__name__}-{replaced}.json"
                with self.subTest(failure=failure.__name__, replaced=replaced), WelipSession(path, self.config) as session:
                    self.prefix(session, 1)
                    request = request_for(session.ready(), "ADVANCE")
                    before = path.read_bytes()
                    def interrupted_save(path, value):
                        if replaced:
                            write_json(path, value)
                        raise failure("interrupted storage outcome")
                    with patch("solvefinite.welip_session.write_json", side_effect=interrupted_save):
                        with self.assertRaises(WelipProtocolError) as caught:
                            session.handle(request)
                    self.assertEqual((caught.exception.code, caught.exception.fatal), ("STORAGE_FAILED", True))
                    self.assertEqual(path.read_bytes() != before, replaced)
                    self.assert_poisoned(session, request)
                with WelipSession(path) as reopened:
                    self.assertEqual(reopened.handle(request)["type"], "DUPLICATE" if replaced else "RESULT")
                    self.assertEqual(reopened._agent.cycle, 1)

    def test_result_delivery_failure_after_save_recovers_without_repeating_action(self):
        for failure in (RuntimeError, KeyboardInterrupt, SystemExit):
            path = self.directory / ("delivery-" + failure.__name__ + ".json")
            with self.subTest(failure=failure.__name__), WelipSession(path, self.config) as session:
                self.prefix(session, 1)
                request = request_for(session.ready(), "ADVANCE")
                with patch.object(session, "_context", side_effect=failure("delivery failed")):
                    with self.assertRaises(WelipProtocolError) as caught:
                        session.handle(request)
                self.assertEqual(caught.exception.code, "OWNER_FAILED")
                self.assertEqual(self.read(path)["expected"]["seq"], 2)
                self.assert_poisoned(session, request)
            with WelipSession(path) as reopened:
                self.assertEqual(reopened.handle(request)["type"], "DUPLICATE")
                self.assertEqual(reopened._agent.cycle, 1)

    def test_transport_write_failure_after_durable_result_closes_and_lost_ack_retries(self):
        request = deepcopy(MAIN["operations"][0]["request"])
        config_path = self.directory / "config.json"
        write_json(config_path, self.config.to_dict())
        class LostResult(StringIO):
            def write(self, text):
                if json.loads(text)["type"] == "RESULT":
                    raise BrokenPipeError("receiver lost acknowledgement")
                return super().write(text)
        stream = LostResult()
        with self.assertRaises(BrokenPipeError):
            serve(self.path, config_path=config_path, input_stream=StringIO(json.dumps(request) + "\n"),
                  output_stream=stream)
        self.assertEqual(json.loads(stream.getvalue())["type"], "READY")
        self.assertEqual(self.read()["expected"]["seq"], 1)
        before = self.path.read_bytes()
        with WelipSession(self.path) as reopened:
            duplicate = reopened.handle(request)
            self.assertEqual(set(duplicate), COMMON | {"seq"})
            self.assertEqual(duplicate["type"], "DUPLICATE")
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
