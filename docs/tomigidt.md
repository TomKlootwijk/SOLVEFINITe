# TOMIGIDt autonomous single agent

The active user objective is: **Make the solipsism TOMIGIDt autonomous single agent**.

The existing PDF and prior repository do not define "TOMIGIDt" or "solipsism".
The implementation below is a declared application profile and concrete
progress toward the objective. It is not a replacement definition of the goal.
The exact intended meaning and autonomous task remain a question for Tom.

## One agent and its perspective

One `Tomigidt` instance owns an immutable manifest, a persistent identity, a
target, its own observation history, its packed state, and a decision sequence.
The right RP32 half is an integrity-related mirrored representation, not another
agent, adviser, or independent decision maker.

The provisional local-observation perspective is explicit:

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

When away from the target, the agent searches the explicit directed movement
graph. Graph adjacency is independent of the binary paths used to regenerate
world nodes. Every candidate route reaches the same declared target.

The planner uses positive integer entry costs and deterministic weighted search
over `(node, hop_count)`. It minimizes `(cost, route)` among routes with at most
32 hops. Keeping hop count in the search state prevents a cheap long prefix
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

At most 256 graph nodes and 32 hops are supported. In v2,
`max_search_expansions` limits weighted expansions **per accepted planning
cycle**. A DEFER consumes that quantum and retains the immutable frontier and
best prefixes. The next complete frame continues that work if the position,
packed agent state and effective entry costs still match. Even a quantum of
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

The complete packed forecast and actual movement use `solvefinite.motion`.
The original colony runtime uses that same kernel without changing its v1
results. New measurements can invalidate earlier predicted futures; the next
cycle replans from the current state and new observations.

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

## Verification and remaining scope

Tests exercise generated legal routes, changed measurements, stale or incomplete
input, full forecasts, malformed histories, cache changes, repeated recovery,
fresh-process continuation during search, old-policy replay and exclusive
session ownership. Incremental search results are compared with one-shot
search under multiple quantum sizes. The original RP32
reference vectors and original colony demo remain covered.

What is now executable is one autonomous mission loop with persistent local
state. It still needs Tom's definition of "solipsism TOMIGIDt" and intended
autonomous duties before the full user goal can be audited for completion.

The current application profile does not implement open-ended goal formation,
learning, real sensors or actuators, or a continuous multi-mission lifecycle.
It also does not establish full f8, Klein-bottle field/Hadamard or WElip
conformance. Those source contracts are not silently replaced by this
application's graph and planning rules. Performance, retained-history growth
and hardware realization remain separate engineering work.
