# TOMIGIDt autonomous single agent

The active user objective is: **Make the solipsism TOMIGIDt autonomous single agent**.

On 25 September 2026 Tom clarified "solipsism" as one autonomous individual
and its world, and reaffirmed self-reference, universality and GPU texture
execution as the architectural direction. That clarification supersedes the
meaning-related blocker in the earlier [objective audit](acceptance-audit.md).
The movement-and-repair task below remains a finite application profile.
[GPU execution](gpu.md) now implements world derivation and packed motion on
real hardware while retaining the CPU policy and durable journal.

## One agent and its perspective

One `Tomigidt` instance owns an immutable manifest, a persistent identity, a
target, its own observation history, its packed state, and a decision sequence.
The right RP32 half is an integrity-related mirrored representation, not another
agent, adviser, or independent decision maker.

The current application's local-observation rules are explicit:

- The agent knows the declared baseline, production rules and movement graph.
- It receives current measurements only for its position and outgoing neighbors.
- It retains earlier admitted measurements in its internal model.
- Unseen farther nodes use a declared zero-additional-hazard hypothesis.
- It requires a complete fresh local frame before moving or repairing. Old
  frames cannot be combined to pretend that fresh input has arrived.
- The simulated sensor source owns changing environment values and supplies
  observations. It never supplies candidate routes or decides the next action.

The snapshot exposes identity, goal, position, packed state, observed packets,
latest forecast and status. A structured footprint records profile, baseline,
agent name, epoch zero, sequence and current derivation path. It names the
derivation context; it is not authentication or proof of global uniqueness.

## Autonomous cycle

`Tomigidt.step(observations)` validates and encodes the new sensor frame, updates
a hypothetical copy of its internal model, chooses an action and predicts its
packed result before changing live state. Each accepted cycle emits its input
packets, decision, full route forecast and resulting pair into the journal.

When away from the target, the agent searches the movement graph. The binary
application declares this graph independently of derivation paths; the field
application generates it from the retained Klein recipe. Every candidate route
reaches the same declared target.

The planner uses positive integer entry costs and deterministic weighted search
over `(node, hop_count)`. It minimizes `(cost, route)` among routes with at most
32 hops in the binary application, or the field manifest's `max_hops` (default
255). Keeping hop count in the search state prevents a cheap long prefix
from incorrectly displacing a shorter viable route under the hop limit.
Search budgets and target reachability have different results:

| Decision | Result |
|---|---|
| MOVE | Forecast the entire chosen route with the shared RP32 movement kernel, then execute its first legal edge. |
| REPAIR | At the observed target, debit repair energy and complete this declared mission. |
| WAIT | Fresh local observations are incomplete; no movement or energy debit occurs. |
| UNREACHABLE | The declared directed graph has no route to the target. |
| INSUFFICIENT_ENERGY | The current least-cost model cannot preserve the required repair energy. |
| DEFER | A reachable target is unresolved; v2 retains unfinished weighted search for the next cycle. A route beyond the fixed hop limit has no resumable search. |

At most 256 graph nodes are supported. In binary v2 and the field policy,
`max_search_expansions` limits weighted expansions **per accepted planning
cycle**. A DEFER consumes that quantum and retains the immutable frontier and
best prefixes. The next complete frame continues that work if the position,
packed agent state and effective entry costs still match. Field planning also
binds the separate energy value. Even a quantum of
one can eventually establish a route in a sufficiently stable model, given
enough remaining cycles. A result reached exactly at the quantum boundary is
used immediately. Decision `expansions` is cumulative for that search, including
earlier DEFER cycles; it resets when the planning context changes.

Fresh changed costs discard pending work before it can choose an action.
Incomplete frames produce WAIT: unchanged costs preserve the search without
advancing it; changed costs invalidate it. MOVE, REPAIR and resolved planning
outcomes clear the cursor. Persistent environmental changes can keep
invalidating searches, so progress is conditional on a sufficiently stable
model. Search cycles advance the sensor timeline even when no movement occurs.

Preflight graph reachability is separately bounded by the graph-size limit.
The expansion quantum does not limit all work in a cycle: reconstructing costs,
copying the cursor and writing the journal also take time. Frontier entries,
best prefixes and route tuples consume memory beyond the active world cache.
The finite cycle budget is also retained in the manifest. Budget exhaustion
never becomes a claim of successful completion or global unreachability.

The binary profile's packed forecast and movement use `solvefinite.motion`.
The original colony runtime uses that kernel without changing its v1 results.
The field profile uses `field_world.py` and `field_agent_gpu.py` for its typed
transitions. New measurements can invalidate earlier predicted futures; the
next cycle replans from the current state and new observations.

## Persistence and single ownership

Agent archives use envelope `tomigidt-agent-v1` and perspective
`local-observation-v1`. The manifest selects the behavior version. New agents
default to `tomigidt-observe-plan-act-v2`, which retains search work.
`tomigidt-observe-plan-act-v1` remains supported with its original bounded
search, decisions and snapshot shape; existing journals are never silently
upgraded. Frozen fixtures from the previous implementation verify this.
Every input that affects a decision is in the manifest or ordered event history.
Replay reconstructs the policy decisions and predicted/output pairs, not just
the final state. The retained expected state is only a comparison witness.

For v2, that witness also includes a `planning` summary: context, cumulative
expansions and pending state count, or null when no search remains. Replay
rebuilds the actual frontier from the original observations and policy cycles.
It never installs the summary as trusted live state. Restarting halfway through
planning therefore continues the same search after verification.

The CLI session also retains the simulated environment and its versioned change
schedule. Resuming checks that historical sensor inputs agree with that
schedule, reconstructs the agent, and continues at the next original cycle.
Changing cache capacity changes residency only, not the canonical decisions.

`agent run` holds an OS-backed exclusive lock on a stable sibling of the state
file. It reads and advances the session only while holding that lock. A second
writer is rejected; exiting releases ownership through the operating system.
The lock file is not deleted or treated as a process-liveness indicator.
Ownership is scoped to the canonical state-file path, not a global registry of
all possible copies of an agent identity.

Each accepted cycle is atomically written before proceeding to the next cycle.
This is a simulation transaction: there is no physical actuator or external
side effect between a decision and its saved record. Exactly-once physical
actions would require an additional actuator acknowledgment protocol.

An invocation continues pending v2 search within its `--steps` budget, saving
every DEFER before admitting the next frame. Other nonacting outcomes return
control after one new frame. A subsequent invocation can admit another fresh
frame and recover if conditions have changed.
For example, a lower observed hazard can make a previously unaffordable route
viable. COMPLETE stays terminal for this mission; reaching the manifest's cycle
budget is reported separately from the last decision status.
Stopping at `--steps` while a search remains pending reports
`STEP_BUDGET_EXHAUSTED`, with status `SEARCH_DEFERRED`. A hop-limit DEFER has no
cursor and stops immediately; repeating it cannot extend the declared hop bound.

## Default runnable experiment

The scenario runner below is one input adapter. The [live channel](live.md)
adds a persistent `agent serve` process that accepts new local observations
over standard input and emits its own decisions. It remains available after
WAIT or insufficient energy, saves each admitted cycle before replying, and
deduplicates retries across restarts. Its sensing interface is live; movement
and repair retain the simulated application semantics described here.

```sh
python -m solvefinite agent run --state output/tomigidt/session.json --steps 1
python -m solvefinite agent run --state output/tomigidt/session.json --steps 64 --capacity 1
python -m solvefinite agent inspect output/tomigidt/session.json
```

The agent initially chooses `root -> 0 -> 00 -> 11`. At cycle 2 it observes a
hazard at `00`, computes another route and backtracks. Its executed positions
become `root -> 0 -> root -> 1 -> 10 -> 11`; the sixth cycle repairs the target.
It finishes with 78 energy units and packed pair `164E23BB064E2345`.
These are consequences of the policy and synthetic inputs, not a supplied list
of actions. The environment carries no candidate route sequence.

To stop an invocation after a finite amount of work, set `--steps`. The next
invocation resumes the same identity and history. The agent's COMPLETE status
means only that its declared simulated target was repaired. It does not mark
the user's broader Codex goal complete.

To interrupt unfinished planning, use the supplied static scenario with one
weighted expansion per cycle and a new state file:

```sh
python -m solvefinite agent run --scenario examples/tomigidt-incremental.json --state output/tomigidt/incremental.json --steps 2 --capacity 1
python -m solvefinite agent run --state output/tomigidt/incremental.json --steps 64 --capacity 8
python -m solvefinite agent inspect output/tomigidt/incremental.json
```

After the first command, the agent is at the root with two accumulated search
expansions. The next process reconstructs those cycles, continues the frontier
and completes at cycle 14. It traverses `root -> 0 -> 00 -> 11`, finishing with
86 energy units and pair `9656236786562399`. Its complete archive matches an
uninterrupted run of the same scenario. The static sensor schedule here differs
from the changing-hazard default above; it isolates planning continuation.

## Intrinsic field application profile

FI1-FI8 in the consolidated formal PDF define
`tomigidt-field-observe-plan-act-v1`. `FieldAgentManifest` selects this policy
inside the existing `Tomigidt`, session runner and live channel. Its retained
`klein-ball-world-v1` recipe generates quotient adjacency, an intrinsic ball
boundary, signed distances and phase increments. The manifest accepts no
supplied graph, route or scalar field. It preserves the earlier policies and
their exact archive schemas.

```sh
python -m solvefinite agent run --scenario examples/tomigidt-field.json --state output/tomigidt/field.json --steps 1 --backend gpu --capacity 1
python -m solvefinite agent run --state output/tomigidt/field.json --steps 64 --backend cpu --capacity 8
python -m solvefinite agent inspect output/tomigidt/field.json --backend gpu
```

Canonical nodes use `k:u:v` names. A live pair stores phase R, node index G,
signed distance B and orientation in the metadata; energy is a separate strict
integer. Local observation packets use B for hazard only in their declared
DATA context. Entry cost is `1 + abs(phi(destination)) + hazard`. The planner
reserves the full chosen route cost plus repair energy before moving. It uses
lexical route order to break equal-cost ties, with resumable search quanta.

The departure field selects the turn, then a reversing seam reflects phase
and toggles orientation. B becomes the destination's certified distance. Repair
preserves these lanes, changes the opcode to EMIT and debits separate energy.

| Cycle | Action / position | Packed pair | Energy |
|---|---|---|---:|
| 0 | Initial `k:0:0` | `91FE000601FE00FA` | 100 |
| 1 | MOVE `k:0:4` | `11FF04FB01FF0405` | 98 |
| 2 | MOVE `k:3:1`, reversing seam | `81001010910010F0` | 97 |
| 3 | MOVE `k:3:2` | `81011145910111BB` | 95 |
| 4 | REPAIR `k:3:2` | `06011145160111BB` | 90 |

The initial route is `k:0:4 -> k:0:3 -> k:3:2`, cost 5. At cycle 2, a fresh
hazard of 70 at `k:0:3` changes the remaining route to `k:3:1 -> k:3:2`, cost 3.
With zero hazards and only the ball centre changed from 0 to 4, the first
route instead becomes `k:3:0 -> k:3:1 -> k:3:2`, cost 4.

`FieldWorld.derive` reconstructs a sample without touching the active cache.
`get` retains complete pairs in insertion-order FIFO storage; hits do not
refresh order. CPU derivation recomputes exact distances. GPU derivation
dispatches a fresh sample from the certified scalar buffer, without a retained
packed world-node array. Recipe-only cold construction rebuilds geometry and
fields. Measured hazards require their original retained observations.

The GPU uses a 12-column integer operator texture for four neighbors and three
departure field classes. Forecasts run in scratch state; actual MOVE and REPAIR
dispatch from the persistent device pair and energy. The owner compares the
actual result with its admitted prediction before recording a cycle. An
uncertain device operation or mismatch closes the owner; a new owner must
replay the last durable archive. The host still admits observations, searches
routes, certifies results and writes history.

Field events add an explicit `energy` key; snapshots identify the word profile
and include energy, including unfinished planning context. Replay recomputes
every event rather than installing retained outputs. Cache capacities and
backend choice are outside canonical history. See the
[23-check conformance capture](evidence/field-agent-v1/conformance.json) and
[verification record](evidence/field-agent-v1/verification.json).

The active FIFO accounts for only `8 * capacity` bytes of pair payload. The
default 20-node GPU configuration now allocates 49,160 bytes of explicit device
payload, plus a logical 80-byte host field certificate and 1,296-byte host index.
Replacing the index peaks at 51,528 device bytes and 2,592 host index bytes while
the old and candidate versions coexist. Python objects, temporary compilation, expanded
geometry, search, observations, journals, eviction diagnostics and driver
allocations are additional. No total-memory bound is inferred from the FIFO.

## Changing indexed storage

Field agents accept an optional `IndexBinding(epoch=0, psi_sign=1, phase_origin=0)`.
These settings select a certified storage version and are diagnostic deployment
metadata. They do not change observation, decision or archive schemas.
`agent.reindex(psi_sign=-1, phase_origin=42)` increments the index epoch by exactly
one and prepares a complete replacement before installation. Invalid settings
or a failed certificate preserve the old usable index. An uncertain GPU fault
closes the owner; a cleanup failure after installation is explicitly reported
as a committed replacement requiring recovery.

World derivation walks the canonical tree before reconstructing a node. The GPU
also walks its device tree to obtain the physical texture row for each move.
Changing row order preserves pairs, energy, observations, events, FIFO order and
counters, and the very same retained planning object during a DEFER cycle.
Index links never define a movement edge, cost, search order or tie breaker.

`agent run`, `inspect`, `serve` and `live-inspect` accept `--index-epoch`,
`--index-sign` and `--index-phase-origin` for this profile. Replaying with other
settings reconstructs the same canonical archive. The index epoch is scoped to
the recipe and binding; it is separate from a live sensor producer's epoch.
See [Psi/f8 conformance and failure checks](evidence/psi-f8-v1/README.md).

## Verification and remaining scope

Tests exercise generated legal routes, changed measurements, stale or incomplete
input, full forecasts, malformed histories, cache changes, repeated recovery,
fresh-process continuation during search, old-policy replay and exclusive
session ownership. Incremental search results are compared with one-shot
search under multiple quantum sizes. The original RP32
reference vectors and original colony demo remain covered.

What is now executable is one autonomous mission loop with persistent local
state and optional GPU world derivation and motion forecasts. Tom's clarified
single-individual direction is recorded above. The repair profile establishes
these mechanisms within its declared finite world.

The current application profile does not implement open-ended goal formation,
learning, a physical sensor or actuator adapter, or a continuous multi-mission lifecycle.
Klein cell geometry, exact scalar fields and seam transport are now verified
finite subsets. The local Psi tensor and canonical f8 tree now implement
PX1-PX8. General spectral/Hadamard routing and WElip remain
unimplemented source obligations. Those contracts are not silently replaced by this
application's graph and planning rules. Larger GPU planning workloads,
cache/utilization measurements and retained-history growth remain engineering work.
