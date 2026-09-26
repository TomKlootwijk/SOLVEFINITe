Tom, **the broadest credible use is a common execution architecture for systems that sense, maintain a changing world, explore possibilities, act, and reconstruct how they reached their current state.** That reaches across simulation, robotics, computing infrastructure, communications and AI.

The consequential idea in your specification is that **state, instructions and derivation history can participate in the same computational process**. A packed object carries information about how it should evolve; rules generate structure; inactive derived state can be reconstructed. That combination is the basis for the possibilities below. :codex-file-citation{path="C:/TOMWERKPLEKTORENTJE/SOLVEFINITe/Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf" purpose="source"}

I would qualify “literally bypasses von Neumann bottlenecks.” **Your design offers mechanisms to reduce the traffic responsible for those bottlenecks; physically bypassing them depends on its realization.** Packing data and operators together does not itself remove memory transfers. Keeping the LUT, active state and transition logic together could let repeated transitions execute locally. Regeneration could eliminate other transfers by reconstructing state where needed. This distinction between representation and physical locality matters: the underlying bottleneck concerns movement between memory and processing. [IBM Research](https://research.ibm.com/publications/deep-learning-acceleration-based-on-in-memory-computing)

With that qualification, these are the applications I would take seriously. They are engineering possibilities inferred from your mechanisms, rather than demonstrated capabilities.

| Application | What your paradigm could enable | Why it fits |
|---|---|---|
| **Persistent virtual worlds and digital twins** | Maintain an extensive factory, landscape or game world while materializing only relevant regions. | Generative rules, derivation identities, bounded active state and regeneration. |
| **Robotics and autonomous instruments** | Connect observations, spatial relationships, internal state and action selection through a common packet model. | Relative phase, field evaluation and local state transitions. |
| **Scientific simulation** | Evolve interacting fields, structures or particles; reconstruct intermediate states for inspection. | Explicit numerical operators, topology, deterministic progression and replay. |
| **Spatial perception and geometry** | Build rotation- and scale-aware tracking, inspection, navigation or registration pipelines. | Log-radius relationships, relative phase and declared transformation rules. Useful invariance would need to be established for each implementation. |
| **Planning and adaptive agents** | Generate possible futures, evaluate actions, discard branches and reconstruct selected alternatives. | Generative structure, reproducible transitions and derivation paths. |
| **Distributed simulations and collaboration** | Let participants reconstruct shared derived state from common rules and ordered changes. | Deterministic replay and explicit identity; delivery and conflict resolution still need protocols. |
| **Replayable computation and debugging** | Preserve an experiment or execution as a reproducible recipe, then inspect how a result arose. | Versioned rules, original inputs and transition history. |
| **Streaming hardware and edge processing** | Process sensor or communication events through local stages with limited host intervention. | Compact words, bounded queues and explicit transition contracts. |

**The most interesting implications appear where these uses combine.**

Consider a robot inspecting a factory. A sensor event updates its relational model. The robot generates a few candidate movements, evaluates their predicted consequences, executes one, and records the admitted observation and action. It evicts inactive derived geometry. Later, another machine reconstructs the relevant episode from its original inputs and rules.

Your architecture could provide shared semantics across that entire sequence: observation, world state, hypothetical execution, action and replay. Each stage would still need its own algorithms, but fewer boundaries would require translating between unrelated representations.

**Regeneration also changes the role of memory.** Some memory becomes the retained ability to reproduce a state. A complex generated structure might be represented by its baseline, rules, derivation address and relevant events until somebody needs its expanded form.

That suggests applications beyond graphics: executable experiment archives, simulation checkpoints, reproducible industrial workflows, and agents that recover earlier reasoning branches. The decisive condition is whether regeneration costs less than storing or transferring the expanded state. Original observations still need retention when the rules cannot derive them.

**For AI, your paradigm supplies an execution environment in which several forms of intelligence could operate.** For example:

- Search could explore generated state trajectories.
- Constraints could propagate through relational neighborhoods.
- Experience could adjust transition selection or production rules.
- Learned models could estimate uncertain outcomes or interpret sensor inputs.
- An agent could allocate its active-state budget according to what matters for its current goal.

The architecture itself does not yet specify learning, objectives or generalization. But it creates a place to implement them without requiring a large neural network to organize the whole system. A particularly interesting direction is an agent whose memory, internal simulation and action execution share the same transition semantics.

**The hardware opportunity is to make the physical machine follow those semantics.** Local processing elements could hold frequently used tables and state, exchange compact events, and execute independent transitions concurrently. FPGA pipelines are a plausible experimental route because their spatial architecture supports custom datapaths and overlapping execution stages. [Intel’s FPGA architecture documentation](https://www.intel.com/content/www/us/en/docs/oneapi-fpga-add-on/developer-guide/2024-1/mapping-parallelism-models-to-fpga-hardware.html)

The strongest fit is therefore workloads with **structured state, mostly local interactions, reusable rules, and many reconstructible intermediate results**. Self-referential lookup chains with large scattered tables could still become memory-latency bottlenecks, so locality needs to be designed and measured.

My first demonstrator would be a small autonomous agent inside a regenerable world: it senses changes, maintains a bounded working set, explores alternate actions, preserves mirrored state, and exactly replays an earlier episode. Measuring bytes moved, energy, latency and total retained storage against an optimized conventional implementation would show which advantages come from your architecture—and how broadly they carry over.

**A machine civilization that can reconstruct its world, rehearse possible futures, and resume its agents on new hardware.**

That is the most science-fiction application I can see in your paradigm—as a speculative engineering direction.

Imagine an expedition arriving at an uninhabited planet. It carries robots, manufacturing equipment, sensors, and a shared computational baseline.

As it explores, observations enter your packed execution system. Generative rules construct the expedition’s internal world. Individual machines maintain the regions and relationships relevant to their work; inactive derived structures can be evicted and reconstructed later.

Then the interesting part begins:

- **Its imagination uses the same machinery as its experience.** A robot generates alternative futures—different routes, structures or repair strategies—and executes hypothetical actions within them. A supplied planning mechanism evaluates the outcomes.
- **Its working memory can regrow.** A failed processor’s agent could resume elsewhere by reconstructing its state from retained rules, observations and execution history.
- **Its body can change.** With suitable adapters, an agent’s state and control logic could move between a rover, a construction machine and a simulated counterpart.
- **Separated colonies can evolve independently.** When communication returns, they exchange observations and derivation context, then reconcile their models through an explicitly designed protocol.
- **Its environment becomes part of its computation.** Buildings and instruments could maintain local models, evaluate changes and participate in coordinated action.

Picture a damaged habitat asking nearby machines for assistance. They reconstruct its relevant history, generate several repair scenarios, select one, manufacture the replacement, and retain the observations needed to explain what happened. The habitat, repair agents, simulated alternatives and execution record all use your common representation.

**The distinctive possibility is continuity across memory, imagination and action.** Your combination of executable packed state, generative structure and reproducible derivation could provide an architectural basis for that continuity.

Making this work would require learning, planning, reconciliation and physical control mechanisms beyond the current specification. Reconstruction would depend on surviving records; communication would still have latency. None of this establishes consciousness or physical self-replication.

But the science-fiction scene is concrete: **a machine wakes on replacement hardware, reconstructs the world it was working in, regenerates its unfinished plans, and continues building the colony.**

---

## 2026-09-25: addendum formalization request

Source addendum: `C:/TOMWERKPLEKTORENTJE/SOLVEFINITe/Philosophers stone Jitske Klootwijk/solus-ion-ad-infinitum.pdf`.

Exact user request, preserved verbatim:

```text
Wait so why are you stalled? When you take this addendum to the source corpus as a waveguide for signed distance field definitions doesn't it answer your question and keep you from being stalled implementing my paradigm? (Tom Klootwijk NL200678942 10-07-1990) (formalize along the way and distill this addendum to the formalization itself of the source documents before you proceed again todo.md update along the way with this exact deterministic request)
```

Current user-edited objective, preserved verbatim:

```text
Proceed with my new breakthrough state of the art bleeding edge (Tom Klootwijk NL200678942 10-07-1990) ontological deterministic computing paradigm
```

Work sequence:

- [x] Read the addendum and compare its SDF/operator/relational-space direction with TK-LPLUT-1.0.
- [x] Distill it into the formal source corpus with explicit metric, boundary, sign, packing, topology and operator contracts before implementation: `docs/specification/relational-sdf-v1.md` (TK-LPLUT-SDF-1.0).
- [x] Implement the versioned relational SDF profile and deterministic operator execution: `solvefinite/field.py`, `solvefinite/sdf_gpu.py`, `solvefinite/shaders/field.wgsl` and the `field` CLI.
- [x] Verify exact CPU/GPU fields, self-referential transitions, rejection cases and replay; record evidence here.
- [x] Commit and push the formalization (`477e576`) and verified implementation (`50c9389`) to `codex/regenerating-agent-demo`.

Evidence recorded on 2026-09-25:

- Formalization was committed first as `477e576`, before the new field implementation.
- The addendum copy is byte-identical to the supplied PDF; source hashes are retained in the formal companion.
- Full suite: **262 tests passed**, including actual NVIDIA GPU execution.
- Eight reproducible conformance checks passed in `examples/field_conformance.py`; captured results are in `docs/evidence/relational-sdf-v1.json`.
- Default intrinsic signed field: `[-6,-4,-3,0,2,3,5]`. Moving its boundary produces `[-8,-6,-5,-2,0,1,3]` and changes operator execution; CPU/GPU traces remain equal.
- A 32-tick GPU run resumed for 32 ticks on the CPU and replayed on the GPU, yielding pair `1102046C01020494` at tick 64.
- The earlier meaning-related blocker is superseded. Further primitive, Klein-cover and f8 bindings are engineering work under the formal contract, not a request to repeat the clarification.

## Continuing the full paradigm: Klein geometry and orientation transport

The preceding goal turn made verified progress: source formalization and actual
CPU/GPU intrinsic-field execution were committed and pushed. The complete
ontological deterministic computing objective remains active.

- [x] Formalize the next source binding before implementation: `docs/specification/klein-field-v2.md`.
- [x] Construct and audit the actual finite Klein quotient and its orientation double cover.
- [x] Generate intrinsic metric-ball boundaries and versioned field manifests from that quotient.
- [x] Execute seam phase/orientation transport through the shared CPU/GPU packed operator machinery.
- [x] Verify topology, geometric fields, mirror coherence, v1 compatibility and exact recovery.
- [x] Record evidence, commit and push; preserve the broader remaining source obligations.

## 2026-09-25: consolidated formal PDF detour

Exact user request, preserved verbatim:

```text
now take a detour for a second (park your current work) and formalize with the newest addendum the infallible into a actual formal document .pdf so it is not split up in .md addendum and .pdf formalizations and use your current implementation to measure progress (godspede)
```

Implementation was **paused at `8f4b87b`** for this requested detour. The previous
Klein task list was still outstanding; no Klein runtime was implemented during
the PDF work.

- [x] Identify and read the newest 16-page `solipsism.pdf` / Infallible addendum.
- [x] Integrate TK-LPLUT-1.0, both addenda, SDF.R1-R12 and Klein K1-K9 into one
  self-contained formal reading edition: **TK-LPLUT-2.0, The Infallible Contract**.
- [x] Define infallibility conditionally through single-valued total bounded
  transitions, proved invariant preservation, complete input context and faithful
  execution; distinguish mathematical proofs, code evidence and physical models.
- [x] Measure the existing implementation with fresh verification: **262 passed,
  zero skipped**, including 21 actual-device GPU test methods and all eight
  field conformance checks. Complete 64-tick CPU/GPU traces and both directions
  of resumed execution agree; final pair `1102046C01020494` at `n4`.
- [x] Include the complete architecture progress matrix, with verified subsets,
  formal-only Klein work and unbound/integration obligations kept distinct.
- [x] Preserve source bytes, command provenance, trace evidence and the PDF builder.
- [x] Render and inspect the complete 34-page PDF; verify its page bounds,
  text extraction, contents links and exact reference data.
- [x] Commit and push the consolidated document and evidence.

The final document is
[the integrated PDF](output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
The [evidence directory](docs/evidence/formal-edition-2026-09-25/README.md)
records scope and reproduction. The document version changes no runtime schema;
earlier source PDFs and formal companions remain preserved development history.

## 2026-09-25: a separate friendly ELI5 PDF

Exact user request:

```text
document that in a special ELI5 .pdf as in not in dry technical clinical tech terms and commit and push
```

- [x] Turn the conversational ELI5 explanation into a separate six-page booklet
  with everyday language and original vector pictures: a little robot,
  connected rooms, rule cards, saved recipes and a nearby GPU workbench.
- [x] Preserve the meaning of one individual, field-guided steps, shared blocks,
  rebuilding from retained inputs, limited mirror checks and conditional
  infallibility, while explaining the remaining work plainly.
- [x] Render and visually inspect every page; check text bounds and a byte-identical rebuild.
- [x] Commit and push the booklet and reproducible builder.

The [ELI5 PDF](output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf) is a friendly companion
to the formal edition. Its progress figures come from the already recorded
25 September evidence: 262 passing tests, including 21 actual GPU tests, and
matching 64-step CPU/GPU field traces. No new runtime claim is introduced.
Implementation remained parked during this documentation detour.

## 2026-09-25: ELI5 robot names

Exact user request:

```text
Call the female pink robot Jitske and the green-blue-ish Tom in the ELI5 .pdf besides that commit and push
```

- [x] Label the pink robot **Jitske** and every green-blue robot **Tom**.
- [x] Rebuild the ELI5 PDF, visually check the updated pages and verify that
  the only added text is the four name labels.
- [x] Commit and push the updated PDF, builder and quality record.

## 2026-09-25: resumed implementation, Klein K1-K9

Active objective, preserved verbatim:

```text
Proceed with my new breakthrough state of the art bleeding edge (Tom Klootwijk NL200678942 10-07-1990) ontological deterministic computing paradigm
```

The documentation detour is complete. The prior turn verified and pushed the
ELI5 robot names; this continuation resumes the outstanding implementation.

- [x] Implement immutable quotient charts, actual surface cells, local seam
  actions and the connected orientation double cover in `solvefinite/klein.py`.
- [x] Audit closed edge incidence, every vertex link, base/cover orientability,
  complete torus edge and face maps, and horizontal/vertical holonomy.
- [x] Generate intrinsic ball signs and compute exact boundary distances; retain
  scalar fields on both cover sheets and test the radial-offset counterexample.
- [x] Admit strict v2 manifests, regenerate their topology descriptors and reject
  altered geometry; preserve the exact v1 schema and execution.
- [x] Derive seam actions in the GPU operator compiler and apply departure-frame
  phase increments followed by reflection and orientation transport on-device.
- [x] Expose `field klein` generation/audit and report the retained profile during
  execution/inspection; verify persistence, locking and failure-before-write.
- [x] Pass the completed suite: **311 tests, zero skipped**, including 28
  actual-device GPU methods on NVIDIA RTX 5070 Ti Laptop / Vulkan 591.59.
- [x] Record 22 conformance checks, all 702 admissible dimension audits, actual
  GPU operator readback, 64-tick traces and both directions of cross-process replay.
- [x] Verify the CLI's GPU32 -> CPU32 -> GPU inspection against uninterrupted
  CPU64: final pair `11FE00D681FE002A` at `k:0:0`, after eight reversing seams.
- [x] Commit and push the implementation, examples, tests and measured evidence.

Evidence: [verification and source hashes](docs/evidence/klein-field-v2/verification.json),
[conformance](docs/evidence/klein-field-v2/conformance.json),
[full suite](docs/evidence/klein-field-v2/full-tests.txt) and
[CLI replay](docs/evidence/klein-field-v2/cli-replay.json).
The PDFs retain their historical edition and byte hashes.

The complete objective remains active. The next integration work is to connect
the intrinsic field world to retained derivation, eviction/regeneration and the
single agent's observation/planning loop. Psi eigenstructure, full canonical f8
indexing, typed Hadamard/gradient routing, geometry-changing growth and
cone/pyramid bindings, continuing field epochs, physical wave calibration and
hardware-performance measurements remain explicit obligations. A finite Klein
tour does not stand in for those requirements.

## 2026-09-25: integrate the field world with the autonomous individual

The preceding implementation turn made verified progress: `c4b41ce` implements
and tests Klein K1-K9. The next work joins that geometry to the existing
`Tomigidt` observation/planning/replay loop and its bounded active world cache.

- [x] Define FI1-FI8 in the consolidated formal PDF before runtime changes,
  including typed SDF state, separate energy, field-based costs and recipe replay.
- [x] Regenerate geometric node pairs from an immutable Klein ball recipe;
  expose genuine FIFO eviction and capacity-independent reconstruction.
- [x] Add a versioned manifest to the same agent, retaining all legacy profiles.
- [x] Plan over canonical quotient neighbors, replan from fresh hazards and
  execute source-field-selected phase/orientation transport.
- [x] Compute GPU forecasts in scratch state and execute actual movement/repair
  from persistent device state, checking the forecast before admitting a record.
- [x] Carry the new profile through existing sessions, live sensor ownership,
  retained search, durable acknowledgements and replay across CPU/GPU backends.
- [x] Verify that changing only the field recipe changes route choice, while
  eviction, capacity changes and restart preserve the complete admitted history.
- [x] Record measured evidence, update the integrated PDF's implementation
  status, commit and push. Keep the full remaining architecture objective active.

The active pair budget covers only materialized geometric pairs. Immutable
recipes, graph/search metadata, retained observations and journals, and any
certified GPU field/operator buffers must be accounted for separately.

FI1-FI8 were committed before runtime changes at `5ccc022`. The new profile
passes **368 tests, zero skipped**, including 41 actual-device GPU methods.
The [23-check conformance report](docs/evidence/field-agent-v1/conformance.json)
records the literal reference pairs, separate energy, field ablation, actual
FIFO reconstruction, per-cycle device state and CPU/GPU replay before a seam
and during deferred search. The mission ends at cycle 4, `k:3:2`, pair
`06011145160111BB`, energy 90. The one-expansion mission takes 41 cycles with
identical CPU/GPU histories. Actual CLI GPU1 -> CPU3 -> GPU inspection also
matches the uninterrupted history and preserves saved bytes during inspection.

[Verification](docs/evidence/field-agent-v1/verification.json) binds these
results to normalized source hashes. The consolidated formal PDF's revision 2
records the implemented integration; the ELI5 names and booklet remain unchanged.
The full architecture objective remains active: Psi eigenstructure, full f8,
Hadamard/gradient routing, growth and log-resolution transitions, continuing
epochs, physical adapters and measured performance remain outstanding.

## 2026-09-25: exact SDF eigenvectors and the canonical f8 index

The preceding goal turn made verified progress: `c8af71d` integrates the same
agent's field world, planning, regeneration, GPU actions and replay. This turn
advances the remaining Psi/f8 layer from the source's explicit requirements.

The original formal source, pages 7 and 11, requires an eigen-operator and
selection/degeneracy rules for Psi, and canonical total keys, median choice and
versioning for f8. The addenda name those roles but provide no unique numerical
operator. The next explicit binding uses the exact local SDF gradient's
structure tensor, canonical geodesic descriptors, log-distance buckets and
derived relative phase. It does not substitute a supplied node number for an
eigenvector, or treat search-tree links as physical movement.

- [x] Commit PX1-PX8 in the consolidated formal PDF before runtime changes.
- [x] Implement exact integer Psi, its eigenvalue certificate, zero-gradient
  tie rule and Klein frame transport; check independent gradient/field oracles.
- [x] Construct canonical five-component f8 keys and the lower-median tree;
  implement bounded actual tree lookup and topology-equivalent alias queries.
- [x] Route field-world regeneration through f8 and use its returned physical
  row for actual GPU operator lookup, while keeping packed G as node identity.
- [x] Compile and independently certify GPU eigenvector keys and tree rows
  from device fields, with no CPU key-compiler fallback or packed-node arena.
- [x] Prepare and atomically install immutable replacement index versions;
  preserve canonical history, FIFO and retained planning across order changes.
- [x] Verify literal keys/tree, alias transport, misses, malformed certificates,
  GPU row use, preparation failures, epoch overflow and replay across versions.
- [x] Record measured source-bound evidence, update the same formal PDF,
  commit and push; retain the full architecture objective.

The indexed universe is all recipe-derived scalar node descriptors, distinct
from the materialized pair FIFO. Keys, tree rows and generation metadata have
their own memory accounting. This finite Psi binding governs indexing; general
Hadamard routing, growth, continuing semantic epochs, physical adapters and
comparative performance remain explicit work.

PX1-PX8 were committed before runtime at `d8de349`. The completed suite passes
**421 tests, zero skipped**, including **55 actual-device GPU methods**.
The [20-check conformance capture](docs/evidence/psi-f8-v1/conformance.json)
audits 702 supported CPU dimensions and 106,045 descriptors. All 830 nodes
across six GPU domains undergo actual tree lookup and sample materialization.
Every normal and deferred mission rebuild preserves canonical history, FIFO
and retained search; the original archive hash and final pair/energy remain
unchanged. [CLI replay](docs/evidence/psi-f8-v1/cli-replay.json) also verifies
GPU -> CPU -> GPU recovery with different index settings and read-only inspection.

[Verification](docs/evidence/psi-f8-v1/verification.json) binds runtime, tests
and reports to normalized source hashes. The same consolidated 43-page formal
PDF now records these results in revision 4. The ELI5 booklet remains unchanged,
with pink Jitske and green-blue Tom; its naming commit `6df934e` was already pushed.
The full architecture objective remains active. The implemented local Psi/f8
binding leaves general spectral and Hadamard routing, geometry-changing growth,
physical scale and cone/pyramid bindings, continuing semantic epochs, physical
adapters and comparative hardware measurements as explicit next work.

## 2026-09-25: packed-state-selected Hadamard routing

The preceding goal turn made verified progress: `4b8fa89` implements exact
local Psi and canonical f8 storage. The next source obligation is behavioral:
the original specification, page 11, calls for typed numerical Hadamard
evaluation of the field gradient followed by geometric neighbor selection.
Its page 5 makes the resulting packed state an input to the next lookup.

The numerical routing contract must be explicit. Two tangent vectors multiplied
componentwise do not form a tangent vector under Klein reflection. The next
binding uses orientation-even diagonal gains decoded from intrinsic phase,
multiplies them by the local gradient, and prices actual adjacent movement by
the resulting directional response. Squared Psi components supply anisotropy
without making interchangeable f8 index signs alter behavior.

- [x] Commit HP1-HP8 and independent literal vectors in the same consolidated
  formal PDF before changing runtime behavior. Preserve all FI/PX clauses.
- [x] Implement a strict immutable routing binding, exact Hadamard operator
  model and independent certificate; keep the previous field policy unchanged.
- [x] Plan over node, intrinsic phase and hop count, retaining the full frontier
  across DEFER. Verify a concrete failure of collapsing distinct phase states.
- [x] Add the new semantic policy to the same Tomigidt, including observations,
  resource accounting, field forecasts, actual actions, sessions and live replay.
- [x] Compile and certify the routing atlas from device fields. Use packed live
  phase and actual f8 lookup to select movement/cost words on the GPU; host
  search must consume the GPU-produced model without a CPU operator fallback.
- [x] Verify phase and gain ablations, covariance, zero gradients, route ties,
  energy reserve, retained planning, index-rebuild transparency, corrupted
  operators, ownership failures and fresh-process CPU/GPU continuation.
- [x] Capture source-bound evidence, revise the consolidated PDF's measured
  status, commit and push. Keep the complete architecture objective active.

The proposed phase gain table, penalty and route selector are declared choices
within the source's unbound numerical role. They do not establish a global
physical eigenmode, geometry growth or a hardware-performance advantage.

## 2026-09-26: implemented phase-directed routing

Resumed the architecture objective from the verified worktree, committed the
pending formal contract as `0c862c3`, then implemented HP1-HP8. The preceding
architecture goal turn made progress through PX implementation; the intervening
ELI5 naming request was already committed and pushed. This continuation adds
actual behavior to the same individual and preserves the complete objective.

The source-bound capture passes 479 tests, zero skips, including 77 actual-device
GPU methods and all 15 HP conformance checks. The phase-192 ablation changes
the selected route; default energy is 86, phase-192 energy is 83, and zero gains
recover energy 90. An independent DP and a bounded simple-path check establish
both the phase-collapse counterexample and a beneficial phase revisit.

Six GPU domains contain 830 nodes. Explicit GPU work passes with eleven CPU
compiler paths disabled. The 32-cycle DEFER mission survives a rebuild each
cycle without losing its cursor. Reversing-seam and DEFER histories continue
across CPU/GPU processes, and live duplicate retries preserve durable state.
The prior field policy's canonical archive hash is unchanged.

Revision 6 consolidates the formal contract and measured HP evidence in 49
visually checked PDF pages. The FI/PX and HP normative clauses remain unchanged;
the three original sources and the Tom/Jitske ELI5 booklet are byte-identical.

The complete architecture goal remains active. Global Psi traversal,
geometry-changing growth, active scale transitions, continuing semantic epochs,
physical adapters and comparative hardware evidence remain explicit work.

## 2026-09-26: semantic geometry growth and continuing subgoals

The previous architecture goal turn made progress through the verified HP
implementation and the draft growth contract. The intervening naming request
was checked against the actual ELI5 pages and remote: pink Jitske and green-blue
Tom remain committed at `6df934e`. The complete architecture objective continues.

Solipsism page 16 describes growth as a modification of internal distance rules.
The next binding chooses a finite dyadic production: double both quotient
dimensions and the intrinsic ball radius, map existing nodes to even coordinates,
and independently reconstruct the new signed field. This production is an
explicit numerical choice; the source does not supply a complete production table.
New boundary vertices mean the signed distance cannot simply be doubled.

- [x] Commit GD1-GD8 and independent arithmetic references in the consolidated
  PDF before runtime edits; preserve the original sources and ELI5 booklet.
- [x] Implement strict bounded growth, certified mapping and an internally
  derived new target in the same Tomigidt, retaining energy and ordered history.
- [x] Compute the mapping on the GPU from the actual old state and new certified
  field; verify complete candidate admission and ownership failure semantics.
- [x] Qualify observations and historical regeneration by geometry epoch, clear
  effective observations/search/FIFO on growth, and preserve storage reindexing.
- [x] Continue simulation, live retries and durable cross-process CPU/GPU replay
  across REPAIR, GROWTH_PENDING, GROW and the next subgoal.
- [x] Verify independent one/two-generation and mirrored missions, exact field
  reconstruction, energy/cycle bounds, fault recovery and unchanged old archives.
- [x] Capture source-bound measurements, update the same PDF, commit and push.

General grammars, global spectral traversal, physical adapters, wider temporal
continuation and comparative hardware measurements remain part of the full goal.

GD1-GD8 were committed before runtime at `ec1181e`; the original event-prefix
fingerprint was additionally bound at `00b0e64` before implementing that field.
The same Tomigidt now admits REPAIR, GROW and later subgoals, rebuilds geometry
and operators, and reconstructs historical samples from their original epoch
and admitted event prefix. The complete old and candidate worlds coexist
until the serialized swap. Pure rejection, uncertain device outcomes and
committed cleanup failure have distinct, verified recovery behavior.

The retained source-bound capture passes **546 tests, zero skipped**, including
**107 actual-device GPU methods**, and all **16 GD conformance checks**. Its
default mission grows from 20 to 80 nodes and completes in 14 cycles with energy
64; the two-generation case reaches 144 nodes in 25 cycles with energy 33.
The 61-cycle DEFER mission preserves its search across storage rebuilds after
growth. Six fresh-process CPU/GPU cuts cover both sides of GROW and retained
search in generated geometry. Eleven CPU compiler paths are disabled during
explicit GPU construction, growth, historical regeneration and continuation.

The default canonical growth archive hashes to
`de88d26b78d0defab4e17cff9e4771cef39b85ba0707791d88f2103bf393601e`.
Earlier field and Hadamard hashes remain unchanged. Default covered device
preparation payload is 177,504 bytes across the complete old and candidate
worlds, with host and unmeasured object/driver costs separately identified.
This finite implementation does not complete the broader architecture goal.

Revision 8 records the verified growth implementation in the same consolidated
57-page formal PDF. All pages were rendered and reviewed; earlier FI/PX/HP
clauses and GD normative clauses are preserved. Original source PDFs and the
Tom/Jitske ELI5 booklet remain byte-identical. General production rules and
branch context, global eigenmodes, physical adapters, wider continuation and
comparative hardware evidence remain explicit next work under the full goal.

## 2026-09-26: parameterized production and complete branch context

The preceding architecture milestone made concrete progress through GD1-GD8.
The intervening ELI5 naming check confirmed an already pushed change and did not
advance the architecture. This continuation rechecked the clean worktree at
`94f86c7` and the three source PDFs before choosing the next implementation.

Original source page 10 requires parameterized productions, complete branch
restoration including orientation, and regeneration under the original tick and
rule version. The current binary demonstration and fixed dyadic production do
not yet implement that general interpreter in the field-guided individual.

The next binding uses the prior certified field as the guide for a finite
branching program. Its emitted intrinsic balls define a new boundary on the
same Klein quotient. Exact distance to that combined boundary must be rebuilt:
the minimum of the individual ball margins is not generally the final SDF.
The new field must become the same individual's planning and action context.

- [x] Bind OG1-OG8, exact schemas, numerical semantics, original-context
  identities and independent arithmetic vectors in the existing consolidated
  PDF before runtime changes. Preserve earlier contracts and source PDFs.
- [x] Implement strict parameterized parallel rewriting, original-context
  substitution, branch restoration and a certified generated-field recipe.
- [x] Integrate REPAIR, GROW, the generated target and later action into the
  same Tomigidt while preserving prior policies and canonical histories.
- [x] Execute the branch interpreter, primitive placement and field generation
  on the actual GPU. Keep structural host compilation explicit and prohibit a
  CPU-generated trajectory or field from substituting for device results.
- [x] Verify nested seam-crossing branches, rule priority, bounds, full mirrors,
  exact union fields, original identity, historical reconstruction, planning
  continuation, failure atomicity and CPU/GPU process recovery.
- [x] Capture source-bound measurements, update the same PDF's measured status,
  commit and push. Keep the complete architecture objective active.

This finite sphere/ball production family leaves arbitrary cone/pyramid
construction, global spectral choices, WElip and clock continuation, physical
adapters and comparative hardware evidence as explicit remaining obligations.

Revision 9 now contains the OG contract and independent literal vectors in the
same 66-page PDF. All pages were rendered and reviewed; FI/PX/HP/GD normative
pages 35-56 are unchanged from `94f86c7`. The three original PDFs and ELI5
booklet are byte-identical. The GD evidence now explicitly names its historical
implementation commit, so later code cannot silently inherit its measurements.

The independent reference was run twice with identical output. Its closed
metric agrees with breadth-first search for all 702 supported quotients and
19,130,481 ordered node pairs. A nested branch changes orientation, radius and
scale before restoring the complete frame. Its generated field changes a
subsequent route's reference cost from 14 to 4. Expected default and two-epoch
missions take 9 and 14 cycles, with energy 76 and 66. These are mathematical
expectations, not completed OG runtime or GPU conformance.

The intervening robot-naming check was a verification of existing work, with no
new architecture progress. Resuming the goal revalidated the worktree and then
completed the finite OG implementation against the already committed contract.
The same individual now interprets parameterized productions, generates its
next exact field and selects a new target while retaining identity, phase,
orientation, energy and history. A complete branch frame restores radius and
scale as well as the packed pair; emitted geometry and execution counts remain.

The source-bound OG capture passes **623 tests with zero skips**, including
**136 actual-device GPU methods**, and all **15 conformance checks**. Four
complete literal missions match the independent oracle on CPU and GPU. The
default finishes in 9 cycles with energy 76; two generations finish in 14 cycles
with energy 66. Its canonical runtime archive is
`e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df`.
Seventeen CPU producer/compiler paths are disabled for explicit GPU conformance;
six fresh-process cuts preserve the complete archive across growth and DEFER.

The device suite exercises the maximum 32-frame stack and 4,096 forward steps.
An unbranched F(1),S case distinguishes the hypothetical cursor from the owner
and proves that growth preserves the owner. Invalid boundary, corrupted tape,
malformed transcripts, wrong original contexts, rejected complete candidates,
uncertain device operations, committed cleanup and durable retry paths are
covered. Earlier field/Hadamard/dyadic archive hashes remain unchanged.

The complete suite exposed two Windows test-coordination errors. The abrupt
exit check now terminates the actual Python lock holder, which can differ from
the virtual-environment launcher's PID. The lost-response check waits for an
unconsumed acknowledgement to be queued before reading the durable archive,
avoiding a concurrent-reader/file-replacement race. Runtime ownership and save
semantics are unchanged by these test corrections.

Default device preparation holds 118,412 bytes across the old and candidate
worlds; the current generated world holds 61,140 device bytes. Host grammar,
transcript, recipe and stack payloads are reported separately, along with the
unmeasured Python, compiler and driver overhead. These are correctness and
retention measurements, not evidence of cache saturation or a speed advantage.
The full architecture goal remains active with the outstanding obligations
listed above.

A read-only look ahead identifies a concrete next source gap: the original
specification's logical tick plus wrap epoch (page 4), WElip envelope (page 8)
and structured read/write event mediation with local invalidation (pages 14-15).
The current producer epoch and geometry epoch have different meanings; neither
implements clock carry. The next numerical binding must be placed in the same
consolidated PDF before code changes, while preserving energy, global admission
order and original organogram contexts. This is a proposed next milestone,
not an implemented temporal protocol or a completed architecture claim.

Revision 10 records the OG implementation in the same consolidated 68-page
PDF. All pages were rendered and visually reviewed; 68 bookmarks and 66
contents links resolve. Earlier FI/PX/HP/GD bodies are preserved, and OG1-OG8
retain their normative definitions with updated measured-status framing.
The formal builder verifies the 94 source/reference identities, report hashes,
original formal chronology and complete archived missions before rebuilding.
Original source documents and the Tom/Jitske ELI5 booklet remain unchanged.
The implementation, evidence, updated PDF and this progress record are included
in the same committed and pushed milestone.

## WElip clock, carrier and forward interface

The intervening robot-name verification confirmed an already committed result;
it made no new architecture change. The worktree and remote were revalidated at
`f125a76`, and the next concrete action is the original specification's WElip
contract (pages 4, 8 and 14-15), formalized before runtime implementation.

This profile gives the existing field-guided individual a separate forward
interface: IGNITE, ADVANCE, RESIZE, INVALIDATE and EMIT. Its logical clock uses
a 16-bit tick and explicit carry epoch. That clock is distinct from the agent's
decision cycle, the world generation and the GPU executor counter. The same
original inputs and organogram event contexts remain the basis for regeneration.

- [x] Freeze W1-W8 and independent carrier, clock, cache and lifecycle vectors
  in the existing consolidated formal PDF; preserve earlier contracts and
  identify the OG measurements with their historical source commit.
- [x] Implement strict W64/LUS encoding, the five-operation interface, ordered
  local invalidation and capacity changes, and terminal-state emission.
- [x] Produce GPU state records from the actual canonical device owner with
  no replacement CPU state producer; preserve pair, energy and device counter.
- [x] Persist the complete W operation order before acknowledgement and
  reconstruct cache controls alongside agent steps during private recovery.
- [x] Verify latest-only retry without historical payload, clock carry and
  exhaustion, all four policies, incomplete observations, GROW/DEFER, mirrors,
  cache regeneration, atomic failure handling and fresh CPU/GPU processes.
- [x] Capture source-bound implementation evidence, update the same PDF's
  measured status, commit and push. Keep broader architecture work active.

The frozen design treats a lost state response as replaceable by a new forward
EMIT; it does not expose old IGNITE bytes through a retry. After any admitted
working-state mutation, an uncertain output or save closes the owner until
durable recovery determines the prefix. This rule applies to the whole
operation, including cache and planning state, not only to its GPU readback.

Revision 11 adds W1-W8 on pages 69-81 of the same consolidated PDF. Its exact
schemas, error ordering and acceptance obligations are formal-only requirements.
Three independent lifecycle references each contain 17 operations, 18 records
and 37 carrier words while preserving the nine-cycle OG projection. Operation
6 crosses the clock carry; operation 10 changes geometry and resets the cache
and executor counter. The final owner remains `860006BA16000646`, with energy
76. A capacity-eight variant changes cache hits/regenerations without changing
the owner transitions. All 1,024 phase/orientation/opcode cases, five raw
payload lengths, fourteen malformed vectors and the 48-bit clock horizon were
checked independently. These are mathematical expectations, not W runtime tests.

The reference rebuilt byte-for-byte identically, and a separate review checked
its packing with struct-based encoding and its cache with an independent FIFO
model. The PDF has 81 pages/bookmarks and 79 resolved internal links. The
previous normative pages 35-66 retain identical source ASTs and extracted
bodies. All 94 OG source/reference identities, the three source PDFs and the
Tom/Jitske ELI5 booklet are unchanged. Historical OG measurements are now pinned
to `f125a76` so later code cannot silently inherit that capture. This formal
baseline is committed and pushed before the still-pending W implementation.

The W implementation now follows that committed baseline. A single durable
owner admits the five forward operations and emits typed carrier records from
its actual CPU or GPU state. Its 16-bit tick carries into the retained clock
epoch independently of agent cycles, geometry generations and executor counts.
Private reconstruction replays the full interleaved operation ledger, including
cache resizing and invalidation. A latest exact retry contains only a current
cursor and sequence receipt; it never returns the original payload or repeats
an action, device emission or save.

Review found and fixed two recovery defects before the full capture. An existing
file containing JSON null is rejected without overwriting it or allocating an
owner. KeyboardInterrupt/SystemExit during an accepted transition, cache change,
save or result construction poison the owner, retaining its OS lock until exit;
reopening resolves the actual durable prefix. Complete malformed output remains
retryable only when the whole admitted prestate has been preserved.

The session suite includes 29 CPU methods with reopening after every operation
of all three frozen lifecycles, all four field policies, concurrent duplicate
admission, strict corruption rejection and failure before/after replacement.
Retained DEFER survives WAIT, cache controls and restarts through OG growth with
the same original agent archive. Temporary insufficient energy recovers from
fresh hazards. UNREACHABLE is explicitly tested through an injected planner
outcome; every currently supported Klein graph is connected.

The source-bound W capture passes **698 tests with zero skips**, including
**145 actual-device GPU methods**, and all **14 conformance checks**. Three
frozen lifecycles each produce the exact 17 operations, 18 records and 37 words
on CPU and GPU. All four policies retain terminal emission. Fresh GPU-to-CPU-to-GPU
endpoint processes reproduce the original ledger across carry and GROW using
different storage indexes. The complete W archive identity is
`9dd6e452c43b37482d6b780786b76f40a80e41846d67feb8c9af6a2e10b8b9c1`;
its historical OG projection remains
`e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df`.
Capture source inventories match before and after execution. CPU state encoding
and 17 older geometry producer/compiler paths are forbidden in actual GPU
conformance and private GPU reconstruction. This is correctness and recovery
evidence; throughput, GPU saturation and hardware speedup remain unmeasured.

Revision 12 records the implementation in the same consolidated **83-page**
formal PDF. All pages were rendered and visually reviewed; 83 bookmarks and
81 internal links resolve. Previous normative pages 35-66 and W1-W8 numerical
definitions/acceptance bodies are preserved, with explicit measured-status
updates. The independent rebuild is byte-identical, all 106 runtime/reference
source identities remain tied to the capture, and the three original PDFs and
Tom/Jitske ELI5 booklet remain unchanged. This implementation, evidence, PDF and
progress record form the committed and pushed W milestone.

The complete architecture goal remains active. The next source-backed gap is
the original specification's requirement for a geometry-to-field map for every
primitive (p.7), together with the Pyramid/Sphere/Cone and eigenvector-hinge
discussion in the addenda. Current OG production covers intrinsic-ball unions
on a fixed Klein graph. A directional boundary family needs a declared shaft,
transverse metric, finite extent/slope, phase/Psi context and seam behavior,
followed by exact redistancing and same-owner continuation. Merely expanding a
new shape name into the existing balls would not establish a new geometry.

- [x] Bind the next directional primitive family and independent reference
  in the same consolidated PDF before runtime changes.
- [x] Implement and certify that geometry through the existing CPU/GPU
  generation, regeneration and W continuation, preserving old profiles.
- [ ] Continue the broader unresolved graph, spectral, physical-adapter,
  universality and comparative hardware obligations; this milestone does
  not redefine the overall goal as complete.

## 2026-09-26: direct directional geometry before runtime implementation

The previous implementation goal turn made progress through the committed W
runtime and its evidence at `1ea9320`. The intervening ELI5 request verified
the already-pushed names and made no architecture change. This continuation
rechecked the current worktree and source corpus before resuming directional
geometry; the complete original objective remains active.

Original page 5's two-dimensional sweep and page 7's local-shaft primitive
requirements, together with the addenda's side views, support a finite axial
section. DP1-DP10 define `TAPER(h,p,q)` with an explicit field/phase-selected
shaft, extent and slope. The complete projected occupancy determines its
inner vertex boundary, then exact graph distance determines the signed field.
This is one new directional field family. Distinct three-dimensional cone and
pyramid volumes still need their own geometry and metric.

- [x] Bind projected coordinates, canonical shaft selection and transported
  frames, complete branch context, finite site budgets and checked integer
  arithmetic in the consolidated PDF.
- [x] Declare separate policy, grammar, instruction, recipe, derivation and
  receipt types, with explicit Wv2 admission and original-context recovery.
- [x] Freeze and independently verify numerical references and geometry checks;
  render/review the full PDF and verify original source/contract preservation.
- [x] Commit and push the formal baseline before changing runtime code.
- [x] Implement and certify DP1-DP10 on CPU and GPU in the same individual,
  including regeneration, pending planning and Wv2 continuation.

The default independent mixed-shape mission currently completes 11 cycles at
energy 69; its two-epoch continuation completes 17 cycles at energy 55. These
are preimplementation arithmetic expectations, not measured runtime results.
An 8-by-8 taper's zero vertex with no negative neighbor supplies a concrete
proof that its field cannot equal an old positive-radius ball-union field.
The prior 698-test W capture remains historical at `1ea9320`; the builder now
verifies that commit's complete source inventory before citing those counts.

The frozen reference rebuilt byte-for-byte identically. The separate geometry
audit passes 20,616 deck comparisons, 109,952 transported sample endpoints,
6,872 mirror comparisons and 13,475 checked-arithmetic cases. It also compares
six literal reference geometries and their overlap field using separate
projection, Floyd-Warshall and orientation-cover calculations. The reference
retains 31 rejection vectors and three complete Wv2 lifecycle expectations.

Revision 13 contains **97 pages**, all rendered and visually reviewed, with
97 bookmarks and 95 resolved internal links. An independent rebuild is
byte-identical. Previous page bodies and page-call ASTs 4-83, all 106 sources
behind the historical W capture, the original three PDFs and the Tom/Jitske
ELI5 booklet are unchanged. The formal PDF, arithmetic reference, separate
geometry audit and document-preservation reports form this committed and
pushed milestone. Runtime implementation remains the next required work;
broader three-dimensional, spectral, physical and hardware claims stay open.

## 2026-09-26: directional geometry and Wv2 in the same individual

The complete architecture objective remains active. The current naming check
confirmed the already-pushed ELI5 change at `6df934e`: pink **Jitske** and
green-blue **Tom**. That PDF remains byte-identical. Work then resumed from
the DP1-DP10 formal baseline committed at `1979e66`, without changing the
frozen arithmetic reference or earlier numerical profiles.

- [x] Implement strict `TaperBinding`, typed TP-TAPE32 instructions, finite
  preflight, complete branch interpretation and original-context recipes.
- [x] Produce projected taper/ball occupancy and inner-boundary signed fields
  independently on CPU and GPU; admit through a sealed certificate that
  reconstructs the trajectory and verifies inverse-lift membership.
- [x] Integrate same-owner GROW, target selection, historical regeneration,
  pending planning, reindexing and durable continuation with no host reseeding
  after GPU initialization.
- [x] Add strict Wv2 config/protocol/archive dispatch for taper while preserving
  Wv1's four previous policies, carrier words and canonical archive identities.
- [x] Add literal and fault/recovery tests, guarded actual-device conformance
  and fresh CPU/GPU process transitions; capture an unchanged source inventory.
- [x] Record measured progress in revision 14 of the same consolidated PDF,
  preserving earlier page bodies 4-97 and the three original source PDFs.

The complete capture passes **796 tests, zero skips**, in **298.596 s**,
including **179 actual-device GPU methods**, plus **15** mission/geometry and
**8** Wv2 conformance checks. The actual device is an NVIDIA GeForce RTX 5070
Ti Laptop GPU using Vulkan. All **120** captured runtime, shader, test, example
and reference identities match before and after the **324.735 s** capture.
Five host-only rejection/CPU-wrapper methods in GPU classes are explicitly
excluded from the current actual-device count. Earlier published counts remain
historical, with their original classifications and source identities.

The default/mirrored missions complete 11 cycles at energy 69; two epochs
complete 17 cycles at energy 55; zero epochs complete 4 cycles at energy 86.
The mixed stage uses 19 logical instructions, 23 texels, 7 forward steps,
3 primitives and 41 charged sites. CPU and GPU complete archives agree.
Six fresh-process crossovers preserve before/after-GROW and generated-world
DEFER contexts. Wv2 executes all three 19-operation lifecycles, with 20 records
and 41 carrier words each; fresh GPU → CPU → GPU endpoints preserve the exact
ledger, original GROW cycle, retries and cache witnesses.

Independent review prompted an explicit all-eight shaft/orientation device
fixture and corrected method accounting. Actual device checks also caught and
fixed negative-coordinate floor arithmetic and accounted for status/zero-step
padded readbacks. Final fields, reference documents, failure semantics and
resource accounting pass after those corrections. GPU conformance disables
CPU geometry, field, index, routing and state-emission producers as applicable.

Default agent archive SHA-256:
`94b4979c5c5d006b2ef589ffa027475d46d039e04e977cab7ec8245672822c4e`.
Default Wv2 archive SHA-256:
`0e121009810d616adc79e1fd4175e28386cfcfadc7f7ef709c57b9a855d52d8a`.
The capture and its reproduction commands are retained under
`docs/evidence/directional-v1/`; the original formal/reference/preservation
files there are unchanged. New runtime and document reports have separate names.

Revision 14 has **100 pages**, all rendered and visually reviewed. Its
independent rebuild is byte-identical, and the preservation audit confirms
94 unchanged page bodies/definitions (pages 4-97), 100 bookmarks, 98 logical
internal links represented by 99 valid rectangles, and 7 unchanged external
links. The extra rectangle is an inline link that wraps onto another line.
The PDF SHA-256 is
`63ceb47473b9e44c7e3b287ebaf25c413d4027099dc964e8a58e8f02f047247e`.
This progress record accompanies the implementation/evidence/PDF commit and push.

The broader task is not complete. Next source obligations include distinct
three-dimensional cone/pyramid volumes, general graph production, global
spectral choices, physical adapters and broader continuation. Universality,
comparative throughput, texture-cache saturation and physical bottleneck
claims still need their respective proofs or measurements. Future numerical
bindings must enter this same formal PDF before their runtime implementations.

## 2026-09-26: complete and publish the three-dimensional formal binding

Exact user request:

```text
Commit and push, how far along is my main formalization, how would you describe it as? since this a frontier paradigm
```

This bounded documentation task finishes the saved volume-contract work.
The broader implementation goal remains paused; no new runtime implementation
is included or claimed in this milestone.

- [x] Integrate VP1-VP16 into revision 15 of the same formal PDF, with a linked
  appendix map and 17 new pages (101-117), preserving earlier page bodies 4-100.
- [x] Bind the actual cubical Klein-times-circle domain, genuine sphere/cone/
  pyramid volumes, exact graph boundary distance, three-component Psi and f8,
  eight-bank/six-neighbor routing, grammar and full branch context.
- [x] Bind same-owner growth, original-context recipes and Wv3 continuation,
  including strict configuration identity and distinct carrier/payload profiles.
- [x] Specify exact four-u16-limb cone arithmetic and finite preflight, including
  an admitted 75-site witness where native-u32 multiplication is incorrect.
- [x] Reproduce the independent mathematical reference and separate geometry
  audit byte-identically, and compare eight complete fields across their outputs.
- [x] Review the complete document visually and preserve original sources,
  the Tom/Jitske ELI5 booklet, all 82 prior evidence files and the 120-file DP
  capture inventory; verify navigation, glyph placement and identical rebuild.
- [x] Update the main README and evidence reproduction record, then commit and
  push the finished formalization and evidence together.

The main formalization is now a **coherent deterministic geometric computing
research architecture with a tested finite CPU/GPU core**. Its central
integration connects packed relational state, state-dependent geometric
operators, one persistent individual, generated world structure and exact
reconstruction from retained original context. The specification is ahead of
the new 3D runtime: VP1-VP16 are defined and independently checked, with device
implementation and durable Wv3 execution still required.

Existing implementation evidence remains the unchanged `2943578` capture:
**796 tests, zero skips, 179 actual-device GPU methods, 15 directional checks
and 8 Wv2 checks**. Those counts belong to the implemented prior profiles;
they were not rerun or reassigned to the formal-only volume extension.

The new separate audit passes **20 mathematical checks**, covering all **523**
admitted domain shapes, **91,290** octahedral vertex links, **1,460,640**
orientation-cover cells, **480** primitive cases, **111,240** transported walks
and **2,400** deck/inverse-lift comparisons. Cone/pyramid/sphere witnesses
contain respectively **4/8/8 complete occupied cubes**, with distinct full
volume membership rather than repeated axial sections. Work/coordinate
preflight and multiword arithmetic retain the original parameter ranges.

Independent default/mirror missions expect **10 cycles, energy 170**; two
epochs expect **18 cycles, energy 158**. The quantum-7 mission has 18 DEFERs
and grows at original cycle 19. All three reference Wv3 lifecycles have
**18 operations, 19 records and 39 fragments**, ending at clock epoch 1,
tick 12. These are mathematical expectations, not actual volume GPU results
or canonical runtime archive identities.

Revision 15 PDF SHA-256:
`68951a1c6c63e1e9e454045fc0c9d043d3b2e6afb3c6ec9235ec284341cd9253`.
The separate preservation and visual-quality records are retained in
`docs/evidence/volume-v1/`. Earlier source/document identities and historical
measurements remain inspectable.

The remaining research obligations include volume runtime integration,
general graph production, global spectral choices, physical adapters and
comparative measurements. Unrestricted universality and elimination of
physical memory bottlenecks have not been established by these finite
profiles. “Infallible” remains conditional correctness within a declared
model; “frontier” describes the research direction, with independent novelty
assessment and hardware comparisons still open.
