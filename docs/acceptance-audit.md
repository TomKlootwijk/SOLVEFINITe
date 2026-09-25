# TOMIGIDt objective audit

> Historical audit of the commit named below. Its request for a definition of
> solipsism was answered by Tom on 25 September 2026: one autonomous individual
> and its world, with self-referential packed LUT execution on the GPU through
> textures. The meaning-related blocker is superseded. See [gpu.md](gpu.md) for
> subsequent implementation and evidence. The historical findings below refer
> to the earlier CPU implementation, not the current GPU backend.
>
> Tom subsequently supplied the Solus addendum and directed formalization
> before further implementation. [TK-LPLUT-SDF-1.0](specification/relational-sdf-v1.md)
> now supplies intrinsic field and operator contracts for the broader
> ontological deterministic computing objective. [field.md](field.md) records
> that continuation; the historical request for clarification below is not an
> active implementation blocker.

Audit date: 25 September 2026. Implementation audited:
`a536b4b0d6cfe0614b4e615dde1963f917f72dce`.

User objective: **Make the solipsism TOMIGIDt autonomous single agent**.

**Full completion is not established.** The repository contains an executable
autonomous agent profile with verified planning, live input and recovery. The
intended meaning of "solipsism TOMIGIDt" and its autonomous duties have not been
specified. The repair experiment must not become the definition of the user's
full objective merely because that experiment passes its tests.

## Acceptance authority

The [source specification](../Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf)
defines the underlying paradigm. Its Sections 2, 15 and 16 support retained
inputs, versioned transitions, input admission and ordered output. Section 18
separates arithmetic checks from other conformance objects. Appendix D states
that numerical and algorithmic bindings still need to be supplied by a
realization. The document does not define "TOMIGIDt" or "solipsism".

[todo.md](../todo.md) preserves the earlier application discussion verbatim.
Its machine-civilization scenario presents possibilities, not an acceptance
specification selecting a particular robot, learning rule, objective generator
or physical task. The local-observation interpretation and repair duty in
[docs/tomigidt.md](tomigidt.md) are explicitly provisional application choices.

## What the current evidence establishes

| Scope | Evidence inspected | Result and limit |
|---|---|---|
| One decision maker | [Tomigidt](../solvefinite/tomigidt.py), [live ownership](../solvefinite/live.py), ownership tests in [test_live.py](../tests/test_live.py) | One policy/state owner per retained session; the mirrored half is a representation. This is not a global identity registry for copied archives. |
| Choose actions from observations | Agent policy and [navigation](../solvefinite/navigation.py); behavioral tests in [test_tomigidt.py](../tests/test_tomigidt.py) | The agent generates routes, responds to changed hazards, forecasts outcomes and selects legal actions within its declared graph. The producer supplies no routes or actions. |
| Continue unfinished reasoning | Incremental search and [recovery tests](../tests/test_incremental_agent.py) | Bounded search retains work across cycles and reconstruction; changed costs invalidate it. Progress depends on a sufficiently stable model and remaining cycle budget. |
| Memory, prediction and action share transitions | [motion.py](../solvefinite/motion.py), complete-forecast and replay tests | Predicted and executed packed movements agree under identical inputs. This proves the declared simulated semantics. |
| Regenerate state and preserve mirrors | [world.py](../solvefinite/world.py), [rp32.py](../solvefinite/rp32.py), world and arithmetic tests | Derived nodes reconstruct exactly and the active pair cache is bounded. Total retained history and Python memory are not constant. |
| Remain available for new observations | [live channel](live.md), [subprocess tests](../tests/test_live_cli.py) | Missing data and insufficient energy do not end the live process. New frames can let the same owner continue. |
| Recover saved actions without duplication | Live admission, persistence and failure tests | Original sequence retries return original events; process restart reconstructs state. Commit serialization prevents concurrent callers from acknowledging an overwritten cycle. Physical actuator delivery is outside this guarantee. |
| Preserve previous policy histories | Frozen v1 fixtures and incremental-agent replay tests | v1 journals retain v1 behavior; v2 search progress reconstructs from its original inputs. |
| Original requested wording | [todo.md](../todo.md) and Git history | The two application replies remain unchanged. Implementation and documentation are pushed on `codex/regenerating-agent-demo`. |

The full implementation suite passed **211 tests** before the audited commit.
This audit inspected the relevant test bodies and their scope; the count alone
is not evidence that the broader user objective is complete.

The following retained artifacts were independently replayed during this audit
with a one-pair cache. They are local experiment outputs under ignored `output/`,
not prerequisites shipped with the repository:

| Artifact | Verified result |
|---|---|
| `output/tomigidt/live-sensor-smoke.json` | v2; six original cycles: WAIT, INSUFFICIENT_ENERGY, three MOVE decisions, then REPAIR; 86 energy remaining. |
| `output/tomigidt/incremental-v2.json` | v2; fourteen original cycles including retained DEFER progress, three moves and repair; 86 energy remaining. |
| `output/tomigidt/session.json` | v1; six original cycles, including backtracking after a changed hazard; 78 energy remaining. |

No matching `solvefinite` or `live_sensor_demo` Python process was live at the
audit's process check. Persisted archives and lock files are not evidence of an
agent currently running or waiting for input.

## What is not established

- The intended observable behavior of **solipsism TOMIGIDt**. Local observation
  history is an implementation assumption, not a supplied definition.
- The intended independent duty, operating environment and completion test.
  A simulated repair mission demonstrates a mechanism; it does not establish
  that repair is the user's intended application.
- Full f8, Klein field/Hadamard, WElip or physical-adapter conformance. These
  must not be claimed from the existing subset. Which additional realization
  bindings this particular agent needs remains undecided.
- Physical actuation, autonomous learning, open-ended objective formation,
  distributed civilization, hardware replacement or a physical bypass of
  memory-transfer bottlenecks. The current experiments do not demonstrate
  those outcomes, and the active objective does not select their interfaces.

## Required next input

The next implementation should be selected from Tom's intended behavior, not
from another arbitrary extension of the repair experiment. A concrete
**input or situation -> expected independent action** example, together with
what "solipsism TOMIGIDt" means in the design, would identify that work.

After that input, derive acceptance cases from it, select the required source
bindings and adapters, implement the missing behavior, and audit the full
objective again. Until then the full goal remains unproven. The verified
implementation remains runnable and available for that continuation.
