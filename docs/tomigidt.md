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
| DEFER | A reachable target could not be resolved within the finite search budget. |

At most 256 graph nodes and 32 hops are supported. Weighted search is bounded
by the manifest's expansion budget; preflight graph reachability is separately
bounded by the graph-size limit. DEFER records the weighted expansions consumed.
The finite cycle budget is also retained in the manifest. Budget exhaustion
never becomes a claim of successful completion or global unreachability.

The complete packed forecast and actual movement use `solvefinite.motion`.
The original colony runtime uses that same kernel without changing its v1
results. New measurements can invalidate earlier predicted futures; the next
cycle replans from the current state and new observations.

## Persistence and single ownership

Agent archives use `tomigidt-agent-v1`, policy
`tomigidt-observe-plan-act-v1`, and perspective `local-observation-v1`.
Every input that affects a decision is in the manifest or ordered event history.
Replay reconstructs the policy decisions and predicted/output pairs, not just
the final state. The retained expected state is only a comparison witness.

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

An invocation stops after a nonacting outcome instead of spinning. A subsequent
invocation can admit one fresh frame and recover if conditions have changed.
For example, a lower observed hazard can make a previously unaffordable route
viable. COMPLETE stays terminal for this mission; reaching the manifest's cycle
budget is reported separately from the last decision status.

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

## Verification and remaining scope

Tests exercise generated legal routes, changed measurements, stale or incomplete
input, full forecasts, malformed histories, cache changes, repeated recovery,
fresh-process continuation and exclusive session ownership. The original RP32
reference vectors and original colony demo remain covered.

What is now executable is one autonomous mission loop with persistent local
state. It still needs Tom's definition of "solipsism TOMIGIDt" and intended
autonomous duties before the full user goal can be audited for completion.

The current application profile does not implement open-ended goal formation,
learning, real sensors or actuators, or a continuous multi-mission lifecycle.
DEFER currently retries the same bounded route search; it does not retain a
partially explored frontier. With an unchanged model and insufficient fixed
search budget, retries cannot make progress. Resumable bounded search is the
next concrete autonomy improvement, with the same replay and admission rules.
It also does not establish full f8, Klein-bottle field/Hadamard or WElip
conformance. Those source contracts are not silently replaced by this
application's graph and planning rules. Performance, retained-history growth
and hardware realization remain separate engineering work.
