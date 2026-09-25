"""Drive TOMIGIDt through its public JSONL CLI using external synthetic sensors.

Run with the same Python environment as the project, for example:
    python examples/live_sensor_demo.py --state output/tomigidt/live-demo.json

The state path must be fresh. Sensor frames cause an incomplete-input wait,
an energy warning, and recovery after hazards drop. The client then terminates
its own agent process, restores it, and retries an already committed reading.
The agent chooses every route, movement, and repair action.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


PROTOCOL = "tomigidt-live-v1"
ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 10


class SensorConnection:
    """Own one child process and read its flushed JSON lines with a deadline."""

    def __init__(self, state: Path, backend: str = "cpu"):
        self._diagnostics = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "solvefinite", "agent", "serve", "--state", str(state),
                 "--backend", backend],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._diagnostics, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except BaseException:
            self._diagnostics.close()
            raise
        self._lines: queue.Queue[str | None] = queue.Queue()

        def read_lines() -> None:
            try:
                for line in self.process.stdout:
                    self._lines.put(line)
            finally:
                self._lines.put(None)

        self._reader = threading.Thread(target=read_lines, daemon=True)
        self._reader.start()
        self._closed = False

    def read(self) -> dict:
        try:
            line = self._lines.get(timeout=TIMEOUT)
        except queue.Empty as exc:
            raise RuntimeError("The agent did not produce a response within ten seconds") from exc
        if line is None:
            self.process.wait(timeout=TIMEOUT)
            self._diagnostics.seek(0)
            diagnostic = self._diagnostics.read().strip()
            raise RuntimeError(f"Agent process exited {self.process.returncode}: {diagnostic}")
        response = json.loads(line)
        if type(response) is not dict or response.get("protocol") != PROTOCOL:
            raise RuntimeError("The agent returned an unexpected protocol response")
        if response.get("type") == "error":
            raise RuntimeError(f"The agent rejected its sensor input: {response}")
        return response

    def request(self, request: dict) -> dict:
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        return self.read()

    def finish(self) -> None:
        """Close the sensor stream and require a normal agent exit."""
        self.process.stdin.close()
        code = self.process.wait(timeout=TIMEOUT)
        if code != 0:
            self._diagnostics.seek(0)
            raise RuntimeError(f"Agent process exited {code}: {self._diagnostics.read().strip()}")

    def close(self) -> None:
        """Release only this client's child, pipes, reader, and diagnostics."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=TIMEOUT)
        finally:
            self._reader.join(timeout=TIMEOUT)
            for stream in (self.process.stdin, self.process.stdout, self._diagnostics):
                try:
                    stream.close()
                except OSError:
                    pass


def sensor_request(response: dict) -> dict:
    """Supply only local readings for the next sequence the agent requests."""
    requested = response["next"]
    if requested is None:
        raise RuntimeError("The agent cannot accept another sensor cycle")
    sequence = requested["seq"]
    if sequence == 1:
        observations = {}
    else:
        observations = {
            path: (127 if sequence == 2 and path in ("0", "1") else 0)
            for path in requested["paths"]
        }
    return {
        "protocol": PROTOCOL, "type": "observe",
        "producer": response["producer"], "epoch": response["epoch"],
        "seq": sequence, "position": requested["position"],
        "observations": observations,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def demonstrate(state_path: Path, backend: str = "cpu") -> dict:
    # Check the supplied path before resolving links, including dangling ones.
    if state_path.exists() or state_path.is_symlink():
        raise ValueError(f"A fresh state path is required; already exists: {state_path}")
    state_path = state_path.resolve()
    connection = None
    launches = 0
    try:
        connection = SensorConnection(state_path, backend)
        launches += 1
        ready = connection.read()
        require(ready["type"] == "ready" and not ready["restored"],
                "The demo requires a new agent; an existing session was found")
        require(ready["state"]["cycle"] == 0, "The new agent did not begin at cycle zero")

        waiting = connection.request(sensor_request(ready))
        waited = waiting["state"]["status"] == "WAITING" and waiting["state"]["cycle"] == 1
        require(waited, "Incomplete sensor input did not make the agent wait")

        blocked = connection.request(sensor_request(waiting))
        require(blocked["state"]["status"] == "INSUFFICIENT_ENERGY",
                "The declared high hazards did not trigger the expected energy constraint")
        committed_request = sensor_request(blocked)
        committed = connection.request(committed_request)
        recovered = committed["event"]["decision"]["kind"] == "MOVE"
        require(recovered and committed["state"]["cycle"] == 3,
                "The agent did not choose movement after the hazards dropped")

        # Terminate only the child this demonstration created. Its durable
        # archive is the sole bridge to the replacement process.
        connection.close()
        connection = SensorConnection(state_path, backend)
        launches += 1
        restored = connection.read()
        resumed = (restored["type"] == "ready" and restored["restored"]
                   and restored["state"] == committed["state"])
        require(resumed, "The replacement process did not reconstruct the same state")

        retried = connection.request(committed_request)
        retry_safe = (retried["duplicate"] and retried["event"] == committed["event"]
                      and retried["state"] == committed["state"]
                      and retried["next"] == committed["next"])
        require(retry_safe, "Retrying the retained sensor sequence repeated or changed an action")

        response = retried
        for _ in range(64):
            if response["state"]["status"] == "COMPLETE":
                break
            response = connection.request(sensor_request(response))
        completed = response["state"]["status"] == "COMPLETE" and response["next"] is None
        require(completed, "The agent did not complete its goal within the demo cycle bound")
        connection.finish()
        return {
            "state_path": str(state_path),
            "checks": {
                "waited_for_fresh_input": waited,
                "recovered_after_hazard_drop": recovered,
                "resumed_same_state": resumed,
                "retry_did_not_repeat_action": retry_safe,
                "complete": completed,
            },
            "event_count": response["state"]["cycle"],
            "agent_pair": response["state"]["agent_pair"],
            "process_launch_count": launches,
        }
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("output/tomigidt/live-demo.json"),
                        help="Fresh state file; existing files are never overwritten")
    parser.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    arguments = parser.parse_args()
    try:
        report = demonstrate(arguments.state, arguments.backend)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"live_sensor_demo: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
