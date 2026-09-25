"""Adapter selection and lifetime; numerical GPU parity is tested separately."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from solvefinite.__main__ import main
from solvefinite.live import LiveSession, load_live, serve
from solvefinite.session import load_session, run_session
from solvefinite.tomigidt import Tomigidt


class AdapterProbe(Tomigidt):
    """Exercise real CPU policy while recording requested adapter ownership."""

    created = []

    def __init__(self, manifest=None, capacity=2, *, backend="cpu"):
        super().__init__(manifest, capacity, backend="cpu")
        self.requested_backend = backend
        self.close_count = 0
        self.created.append(self)

    @property
    def execution_info(self):
        return {"backend": self.requested_backend, "test_probe": True}

    def close(self):
        self.close_count += 1
        super().close()


class BackendOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="tomigidt-adapter-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        AdapterProbe.created = []

    def test_runner_selects_backend_on_creation_and_replay_and_closes_each_owner(self):
        with patch("solvefinite.session.Tomigidt", AdapterProbe):
            first = run_session(self.path, steps=1, backend="gpu")
            resumed = run_session(self.path, steps=1, backend="gpu")
            _, loaded = load_session(self.path, backend="gpu")
        self.assertEqual([a.requested_backend for a in AdapterProbe.created],
                         ["gpu", "gpu", "gpu"])
        self.assertEqual([a.close_count for a in AdapterProbe.created], [1, 1, 0])
        self.assertEqual(first["execution_info"]["backend"], "gpu")
        self.assertTrue(resumed["restored"])
        self.assertNotIn("backend", loaded.archive()["manifest"])
        loaded.close()

    def test_live_creation_replay_and_eof_release_backend_without_protocol_changes(self):
        with patch("solvefinite.live.Tomigidt", AdapterProbe):
            with LiveSession(self.path, backend="gpu") as session:
                ready = session.ready()
                self.assertNotIn("execution_info", ready)
                self.assertEqual(AdapterProbe.created[-1].close_count, 0)
            output = StringIO()
            serve(self.path, backend="gpu", input_stream=StringIO(), output_stream=output)
            _, loaded = load_live(self.path, backend="gpu")
        self.assertEqual([a.requested_backend for a in AdapterProbe.created],
                         ["gpu", "gpu", "gpu"])
        self.assertEqual([a.close_count for a in AdapterProbe.created], [1, 1, 0])
        self.assertTrue(json.loads(output.getvalue())["restored"])
        loaded.close()

    def test_failed_initial_save_closes_backend_and_releases_state_lock(self):
        for owner in ("session", "live"):
            path = self.path.with_name(owner + ".json")
            with self.subTest(owner=owner), patch(f"solvefinite.{owner}.Tomigidt", AdapterProbe):
                with patch(f"solvefinite.{owner}.write_json", side_effect=OSError("disk failure")):
                    with self.assertRaisesRegex(OSError, "disk failure"):
                        if owner == "session":
                            run_session(path, backend="gpu")
                        else:
                            with LiveSession(path, backend="gpu"):
                                self.fail("Failed initialization admitted a live owner")
                self.assertEqual(AdapterProbe.created[-1].close_count, 1)
                self.assertFalse(path.exists())
                if owner == "session":
                    run_session(path, steps=1, backend="gpu")
                else:
                    with LiveSession(path, backend="gpu"):
                        pass
                self.assertEqual(AdapterProbe.created[-1].close_count, 1)

    def test_invalid_backend_is_rejected_before_creating_a_state_file(self):
        for backend in (None, True, "cuda", [], ""):
            with self.subTest(backend=backend):
                with self.assertRaises(ValueError):
                    run_session(self.path, backend=backend)
                with self.assertRaises(ValueError):
                    LiveSession(self.path, backend=backend)
                self.assertFalse(self.path.exists())

    def test_gpu_initialization_error_is_reported_by_cli_without_traceback(self):
        output, errors = StringIO(), StringIO()
        with patch("solvefinite.session.Tomigidt", side_effect=ValueError("wgpu dependency unavailable")):
            with redirect_stdout(output), redirect_stderr(errors):
                status = main(["agent", "run", "--state", str(self.path), "--backend", "gpu"])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("wgpu dependency unavailable", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertFalse(self.path.exists())

    def test_inspection_cli_forwards_backend_and_closes_reconstructed_agents(self):
        for command, owner, create in (
            ("inspect", "session", lambda: run_session(self.path, steps=1)),
            ("live-inspect", "live", lambda: serve(
                self.path, input_stream=StringIO(), output_stream=StringIO())),
        ):
            self.path = Path(self.directory.name) / (command + ".json")
            create()
            output = StringIO()
            with patch(f"solvefinite.{owner}.Tomigidt", AdapterProbe), redirect_stdout(output):
                status = main(["agent", command, str(self.path), "--backend", "gpu"])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["execution_info"]["backend"], "gpu")
            self.assertEqual(AdapterProbe.created[-1].requested_backend, "gpu")
            self.assertEqual(AdapterProbe.created[-1].close_count, 1)


if __name__ == "__main__":
    unittest.main()
