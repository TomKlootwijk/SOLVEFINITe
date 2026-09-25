"""Persist and inspect the intrinsic field execution profile."""

from pathlib import Path

from .field import FieldMachine, FieldManifest
from .runtime import write_json
from .session import StateLock, _read_json


def run_field_session(state_path, *, steps=32, backend="cpu", manifest_path=None):
    if type(steps) is not int or not 1 <= steps <= 4096:
        raise ValueError("steps must be an integer in [1, 4096]")
    if type(backend) is not str or backend not in ("cpu", "gpu"):
        raise ValueError("backend must be cpu or gpu")
    path = Path(state_path).resolve()
    with StateLock(path):
        supplied = None if manifest_path is None else FieldManifest.from_dict(_read_json(manifest_path))
        machine = None
        try:
            restored = path.exists()
            if restored:
                machine = FieldMachine.from_archive(_read_json(path), backend=backend)
                if supplied is not None and supplied != machine.manifest:
                    raise ValueError("The supplied field manifest differs from the retained state")
            else:
                machine = FieldMachine(supplied, backend=backend)
            outputs = machine.advance(steps)
            write_json(path, machine.archive())
            return {
                "profile": "relational-sdf-v1", "restored": restored,
                "executed_ticks": len(outputs), "state_path": str(path),
                "state": machine.snapshot(),
                "field": dict(zip(machine.manifest.nodes, machine.fields)),
                "execution_info": machine.execution_info,
            }
        finally:
            if machine is not None:
                machine.close()


def inspect_field(state_path, *, backend="cpu"):
    machine = FieldMachine.from_archive(_read_json(state_path), backend=backend)
    try:
        return {"verified": True, "state_path": str(Path(state_path).resolve()),
                "state": machine.snapshot(), "field": dict(zip(machine.manifest.nodes, machine.fields)),
                "execution_info": machine.execution_info}
    finally:
        machine.close()
