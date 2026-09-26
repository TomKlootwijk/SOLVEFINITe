"""DP8: versioned W continuation retains one owner and original shape history."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import (FieldAgentManifest, FIELD_POLICY, HADAMARD_POLICY,
                                     GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY)
from solvefinite.runtime import write_json
from solvefinite.session import AgentBusy, StateLock
from solvefinite.welip import (WelipConfig, CONFIG_FORMAT, CONFIG_FORMAT_V2,
                               PROTOCOL, PROTOCOL_V2, validate_record)
from solvefinite.welip_session import WelipProtocolError, WelipSession


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "docs/evidence/directional-v1/formal-reference.json").read_text(encoding="utf-8"))
LIFECYCLES = tuple(REFERENCE[key] for key in
                   ("w_v2_lifecycle", "w_v2_mirrored_lifecycle", "w_v2_capacity8_lifecycle"))
MAIN = LIFECYCLES[0]


def request_for(context, operation, **extra):
    cursor = context["next"]
    result = {"protocol": context["protocol"], "producer": context["producer"],
              "producer_epoch": context["producer_epoch"], "op": operation}
    result.update({key: cursor[key] for key in
                   ("seq", "clock_epoch", "tick16", "agent_cycle", "geometry_epoch")})
    if operation == "ADVANCE":
        result.update(position=cursor["position"], observations=dict.fromkeys(cursor["visible_paths"], 0))
    result.update(extra)
    return result


def forbid_gpu_host_producers():
    from tests.test_taper_gpu import forbid_taper_producers
    stack = ExitStack()
    stack.enter_context(forbid_taper_producers())
    for name in ("solvefinite.welip.encode_state", "solvefinite.tomigidt.regenerate_taper"):
        stack.enter_context(patch(name, side_effect=AssertionError("CPU fallback: " + name)))
    return stack


class TaperWelipConfigTests(unittest.TestCase):
    def test_explicit_versions_keep_original_four_policies_and_require_taper_for_v2(self):
        for policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            config = WelipConfig(manifest=FieldAgentManifest(policy=policy))
            self.assertEqual((config.version, config.protocol, config.session_format),
                             (CONFIG_FORMAT, PROTOCOL, "welip-field-session-v1"))
            self.assertEqual(WelipConfig.from_dict(config.to_dict()), config)
            with self.assertRaises(ValueError):
                replace(config, version=CONFIG_FORMAT_V2)
        taper = FieldAgentManifest(policy=TAPER_POLICY)
        with self.assertRaises(ValueError):
            WelipConfig(manifest=taper)
        config = WelipConfig(manifest=taper, version=CONFIG_FORMAT_V2)
        self.assertEqual((config.protocol, config.session_format),
                         (PROTOCOL_V2, "welip-field-session-v2"))
        self.assertEqual(WelipConfig.from_dict(config.to_dict()), config)
        with self.assertRaises(FrozenInstanceError):
            config.version = CONFIG_FORMAT

    def test_strict_version_schema_has_no_implicit_upgrade(self):
        config = WelipConfig.from_dict(MAIN["config"])
        self.assertEqual(config.to_dict(), MAIN["config"])
        class Version(str):
            pass
        for version in (None, True, 2, {}, [], "unknown", Version(CONFIG_FORMAT_V2), CONFIG_FORMAT):
            with self.subTest(version=version), self.assertRaises(ValueError):
                replace(config, version=version)
        for change in (lambda d: d.update(version=CONFIG_FORMAT_V2),
                       lambda d: d.pop("format"), lambda d: d.update(format=CONFIG_FORMAT),
                       lambda d: d.update(initial_capacity=True),
                       lambda d: d.update(agent=FieldAgentManifest().to_dict())):
            document = deepcopy(MAIN["config"])
            change(document)
            with self.assertRaises(ValueError):
                WelipConfig.from_dict(document)

    def test_bare_record_identity_does_not_substitute_for_enclosing_profile(self):
        vector = REFERENCE["cross_profile_identity_vector"]
        old, new = (WelipConfig.from_dict(vector[key]) for key in ("v1_config", "v2_config"))
        self.assertNotEqual(old, new)
        self.assertNotEqual(old.protocol, new.protocol)
        self.assertEqual(old.manifest.world.baseline_id, new.manifest.world.baseline_id)
        # The formal vector intentionally has identical initial carrier bytes.
        # Bare record syntax cannot identify which enclosing owner produced it.
        record = vector["identical_state_record"]
        validate_record(record, old)
        validate_record(record, new)


class TaperWelipSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="taper-welip-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "state.json"
        self.config = WelipConfig.from_dict(MAIN["config"])

    def read(self, path=None):
        return json.loads((self.path if path is None else path).read_text(encoding="utf-8"))

    def prefix(self, session, count, reference=MAIN):
        for row, expected in zip(reference["operations"][:count], reference["results"][:count]):
            self.assertEqual(session.handle(deepcopy(row["request"])), expected)

    def test_all_frozen_lifecycles_reopen_every_operation_and_retry_without_action(self):
        for variant, reference in enumerate(LIFECYCLES):
            path = self.directory / f"lifecycle-{variant}.json"
            config = WelipConfig.from_dict(reference["config"])
            for index, (row, expected, retry) in enumerate(zip(reference["operations"], reference["results"],
                                                              reference["latest_retry_receipts"])):
                with self.subTest(variant=variant, operation=index + 1), WelipSession(
                        path, config if index == 0 else None,
                        index_binding=IndexBinding(epoch=index, psi_sign=-1, phase_origin=91)) as session:
                    if index == 0:
                        self.assertEqual(session.ready(), reference["ready"])
                    self.assertEqual(session.handle(deepcopy(row["request"])), expected)
                    saved = path.read_bytes()
                    with patch.object(session._agent, "step", side_effect=AssertionError("duplicate action")), \
                            patch.object(session._agent, "emit_welip_state", side_effect=AssertionError("duplicate emission")), \
                            patch("solvefinite.welip_session.write_json", side_effect=AssertionError("duplicate save")):
                        self.assertEqual(session.handle(deepcopy(row["request"])), retry)
                    self.assertEqual(path.read_bytes(), saved)
                    archive = self.read(path)
                    self.assertEqual(archive["format"], "welip-field-session-v2")
                    self.assertEqual(archive["operations"], reference["operations"][:index + 1])
            self.assertEqual(archive["expected"], reference["expected"])
            self.assertEqual((len(archive["agent"]["events"]), reference["record_count"], reference["fragment_count"]),
                             (11, 20, 41))

    def test_mixed_archive_config_and_ledger_versions_reject_before_allocation(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 1)
        original = self.read()
        mutations = (lambda d: d.update(format="welip-field-session-v1"),
                     lambda d: d["config"].update(format=CONFIG_FORMAT),
                     lambda d: d["operations"][0]["request"].update(protocol=PROTOCOL),
                     lambda d: d["agent"]["manifest"].update(policy=ORGANOGRAM_POLICY),
                     lambda d: d["config"].update(agent=FieldAgentManifest(policy=ORGANOGRAM_POLICY).to_dict()))
        for mutation in mutations:
            document = deepcopy(original)
            mutation(document)
            write_json(self.path, document)
            saved = self.path.read_bytes()
            with patch("solvefinite.welip_session.Tomigidt") as allocate:
                with self.assertRaises(ValueError):
                    with WelipSession(self.path):
                        self.fail("Mixed protocol namespace admitted")
                allocate.assert_not_called()
            self.assertEqual(self.path.read_bytes(), saved)
            with StateLock(self.path):
                pass
        write_json(self.path, original)
        for supplied in (WelipConfig.from_dict(REFERENCE["cross_profile_identity_vector"]["v1_config"]),
                         replace(self.config, producer="another-owner"),
                         replace(self.config, initial_capacity=8),
                         replace(self.config, manifest=replace(self.config.manifest, initial_phase=249))):
            with patch("solvefinite.welip_session.Tomigidt") as allocate:
                with self.assertRaises(ValueError):
                    with WelipSession(self.path, supplied):
                        self.fail("A different retained configuration admitted")
                allocate.assert_not_called()

    def test_cross_protocol_requests_reject_before_retry_emission_or_save(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 1)
            saved, ready = self.path.read_bytes(), session.ready()
            for operation in ("IGNITE", "EMIT", "READ"):
                request = deepcopy(MAIN["operations"][0]["request"])
                request.update(protocol=PROTOCOL, op=operation)
                with patch.object(session._agent, "emit_welip_state", side_effect=AssertionError("wrong protocol emitted")), \
                        patch("solvefinite.welip_session.write_json", side_effect=AssertionError("wrong protocol saved")):
                    with self.assertRaises(WelipProtocolError) as failure:
                        session.handle(request)
                self.assertEqual((failure.exception.code, failure.exception.fatal), ("INVALID_REQUEST", False))
                self.assertEqual(session.error(failure.exception)["protocol"], PROTOCOL_V2)
                self.assertEqual(session.ready(), ready)
                self.assertEqual(self.path.read_bytes(), saved)

    def test_cache_and_grow_keep_original_agent_time_and_private_recovery(self):
        grow = next(i for i, row in enumerate(MAIN["operations"]) if row["records"][0]["geometry_epoch"] == 1)
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, grow + 1)
            archive = self.read()
            self.assertEqual(archive["expected"]["cache"], MAIN["operations"][grow]["cache"])
            self.assertEqual(archive["expected"]["cache"]["hit_count"], 0)
            self.assertEqual(archive["expected"]["cache"]["regeneration_count"], 0)
            recipe = session._agent.current_recipe.to_dict()
            stage = recipe["stages"][-1]
            self.assertEqual(stage["tick"], session._agent.cycle)
            self.assertNotEqual(stage["tick"], archive["expected"]["seq"])
            current = session._agent.archive()
        with patch("solvefinite.welip_session.write_json", side_effect=AssertionError("private recovery saved")):
            with WelipSession(self.path, index_binding=IndexBinding(epoch=7, psi_sign=-1, phase_origin=23)) as reopened:
                self.assertEqual(reopened._agent.archive(), current)
                self.assertEqual(reopened._agent.current_recipe.to_dict(), recipe)
                self.assertEqual(reopened._cache(), archive["expected"]["cache"])
        self.assertEqual(self.read(), archive)

    def test_complete_malformed_output_is_pure_and_uses_v2_error_context(self):
        with WelipSession(self.path, self.config) as session:
            self.prefix(session, 1)
            request = request_for(session.ready(), "EMIT")
            saved, ready = self.path.read_bytes(), session.ready()
            with patch.object(session._agent, "emit_welip_state", return_value=(1, ["0" * 16, "0" * 16])):
                with self.assertRaises(WelipProtocolError) as failure:
                    session.handle(request)
            self.assertEqual((failure.exception.code, failure.exception.fatal), ("MALFORMED_EMISSION", False))
            self.assertEqual(session.error(failure.exception)["protocol"], PROTOCOL_V2)
            self.assertEqual(session.ready(), ready)
            self.assertEqual(self.path.read_bytes(), saved)
            self.assertEqual(session.handle(request)["type"], "RESULT")

    def test_save_failures_before_and_after_replace_poison_and_recover_exact_prefix(self):
        for replaced in (False, True):
            path = self.directory / f"save-{replaced}.json"
            with WelipSession(path, self.config) as session:
                self.prefix(session, 1)
                request = request_for(session.ready(), "RESIZE", capacity=1)
                def fail_save(destination, value):
                    if replaced:
                        write_json(destination, value)
                    raise OSError("injected uncertain replacement")
                with patch("solvefinite.welip_session.write_json", side_effect=fail_save):
                    with self.assertRaises(WelipProtocolError) as failure:
                        session.handle(request)
                self.assertEqual((failure.exception.code, failure.exception.fatal), ("STORAGE_FAILED", True))
                self.assertTrue(session._agent.closed)
                self.assertEqual(session.error(failure.exception)["protocol"], PROTOCOL_V2)
                with self.assertRaises(AgentBusy):
                    with StateLock(path):
                        pass
            with WelipSession(path) as reopened:
                self.assertEqual(reopened.ready()["head"]["seq"], 2 if replaced else 1)
                self.assertEqual(reopened.handle(request)["type"], "DUPLICATE" if replaced else "RESULT")
                self.assertEqual(reopened._agent.cycle, 0)
                self.assertEqual(reopened._agent.world.capacity, 1)

    def test_fresh_cpu_processes_resume_original_history_with_new_indexes(self):
        config_path = self.directory / "config.json"
        write_json(config_path, self.config.to_dict())
        starts = (0, 7, 13)
        ends = (7, 13, len(MAIN["operations"]))
        for index, (start, end) in enumerate(zip(starts, ends)):
            command = [sys.executable, "-m", "solvefinite", "agent", "welip", "--state", str(self.path),
                       "--backend", "cpu", "--index-epoch", str(index + 1), "--index-sign", "-1",
                       "--index-phase-origin", str(37 * index)]
            if index == 0:
                command += ["--config", str(config_path)]
            requests = [row["request"] for row in MAIN["operations"][start:end]]
            completed = subprocess.run(command, input="".join(json.dumps(x) + "\n" for x in requests),
                                       text=True, capture_output=True, cwd=ROOT, timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rows = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(rows[0]["protocol"], PROTOCOL_V2)
            self.assertEqual(rows[0]["restored"], index != 0)
            self.assertEqual(rows[1:], MAIN["results"][start:end])
        self.assertEqual(self.read()["operations"], MAIN["operations"])
        self.assertEqual(self.read()["expected"], MAIN["expected"])


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class TaperWelipGpuTests(unittest.TestCase):
    setUp = TaperWelipSessionTests.setUp
    prefix = TaperWelipSessionTests.prefix
    read = TaperWelipSessionTests.read

    @classmethod
    def setUpClass(cls):
        from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
        from solvefinite.field_world import KleinFieldRecipe
        from solvefinite.gpu import GpuUnavailable
        try:
            probe = GpuFieldAgentExecutor(KleinFieldRecipe())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        probe.close()

    def test_all_frozen_lifecycles_are_actual_gpu_with_no_cpu_producer_or_reseed(self):
        from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
        for index, reference in enumerate(LIFECYCLES):
            path = self.directory / f"gpu-{index}.json"
            config = WelipConfig.from_dict(reference["config"])
            with self.subTest(index=index), forbid_gpu_host_producers(), \
                    WelipSession(path, config, backend="gpu") as session:
                self.assertEqual(session.ready(), reference["ready"])
                with patch.object(GpuFieldAgentExecutor, "seed", side_effect=AssertionError("host reseed")):
                    for row, expected, counter in zip(reference["operations"], reference["results"],
                                                      reference["executor_action_tick_expectations"]):
                        self.assertEqual(session.handle(deepcopy(row["request"])), expected)
                        self.assertEqual(session._agent._gpu._ticks, counter["executor_action_ticks"])
                self.assertEqual(session._agent.status, "COMPLETE")
                self.assertTrue(session._agent._gpu._terminal)
                self.assertEqual(self.read(path)["operations"], reference["operations"])
                self.assertEqual(self.read(path)["expected"], reference["expected"])
                final = deepcopy(reference["operations"][-1]["request"])
                with patch.object(session._agent._gpu, "emit_welip", side_effect=AssertionError("terminal retry emitted")):
                    self.assertEqual(session.handle(final), reference["latest_retry_receipts"][-1])

    def test_fresh_gpu_cpu_gpu_processes_reconstruct_taper_and_keep_original_ledger(self):
        config_path = self.directory / "config.json"
        write_json(config_path, self.config.to_dict())
        sections = ((0, 7, "gpu"), (7, 13, "cpu"), (13, len(MAIN["operations"]), "gpu"))
        guard_script = (
            "from tests.test_taper_welip import forbid_gpu_host_producers\n"
            "from solvefinite.__main__ import main\n"
            "with forbid_gpu_host_producers():\n"
            "    raise SystemExit(main())\n"
        )
        for index, (start, end, backend) in enumerate(sections):
            command = [sys.executable]
            command += ["-c", guard_script] if backend == "gpu" else ["-m", "solvefinite"]
            command += ["agent", "welip", "--state", str(self.path), "--backend", backend,
                        "--index-epoch", str(index + 8), "--index-sign", "-1",
                        "--index-phase-origin", str(43 * index)]
            if index == 0:
                command += ["--config", str(config_path)]
            requests = [row["request"] for row in MAIN["operations"][start:end]]
            completed = subprocess.run(command, input="".join(json.dumps(x) + "\n" for x in requests),
                                       text=True, capture_output=True, cwd=ROOT, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rows = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(rows[0]["protocol"], PROTOCOL_V2)
            self.assertEqual(rows[0]["restored"], index != 0)
            self.assertEqual(rows[1:], MAIN["results"][start:end])
        saved = self.read()
        self.assertEqual(saved["operations"], MAIN["operations"])
        self.assertEqual(saved["expected"], MAIN["expected"])
        with WelipSession(self.path, backend="cpu") as reopened:
            self.assertEqual(reopened._agent.archive(), saved["agent"])

    def test_after_grow_complete_bad_output_is_pure_but_unknown_readback_poisons(self):
        grow = next(i for i, row in enumerate(MAIN["operations"]) if row["records"][0]["geometry_epoch"] == 1)
        with forbid_gpu_host_producers(), WelipSession(self.path, self.config, backend="gpu") as session:
            self.prefix(session, grow + 1)
            executor = session._agent._gpu
            request = request_for(session.ready(), "EMIT")
            ready, saved = session.ready(), self.path.read_bytes()
            read = executor._read_outputs
            def bad_header(count):
                rows = read(count)
                row = list(rows[0])
                row[1] ^= 1
                return [tuple(row)]
            with patch.object(executor, "_read_outputs", side_effect=bad_header):
                with self.assertRaises(WelipProtocolError) as failure:
                    session.handle(request)
            self.assertEqual((failure.exception.code, failure.exception.fatal), ("MALFORMED_EMISSION", False))
            self.assertFalse(session._agent.closed)
            self.assertEqual(session.ready(), ready)
            self.assertEqual(self.path.read_bytes(), saved)
            self.assertEqual(session.handle(request)["type"], "RESULT")
            ready, saved = session.ready(), self.path.read_bytes()
            request = request_for(ready, "EMIT")
            with patch.object(executor, "_read_outputs", side_effect=OSError("unknown readback completion")):
                with self.assertRaises(WelipProtocolError) as failure:
                    session.handle(request)
            self.assertEqual((failure.exception.code, failure.exception.fatal), ("OWNER_FAILED", True))
            self.assertTrue(session._agent.closed)
            self.assertEqual(session.error(failure.exception)["protocol"], PROTOCOL_V2)
            self.assertEqual(self.path.read_bytes(), saved)
            with self.assertRaises(AgentBusy):
                with StateLock(self.path):
                    pass
        with WelipSession(self.path, backend="cpu") as reopened:
            self.assertEqual(reopened.ready()["head"], ready["head"])
            self.assertEqual(reopened._agent.geometry_epoch, 1)
            self.assertEqual(reopened.handle(request)["type"], "RESULT")


if __name__ == "__main__":
    unittest.main()
