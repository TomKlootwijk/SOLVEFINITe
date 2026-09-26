# Parameterized organograms: OG1-OG8

The normative OG1-OG8 contract is in the existing consolidated
[TK-LPLUT-2.0 PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
The contract and arithmetic reference were committed at `5c76f2c` before
runtime implementation. This directory contains that independent reference
and a separate measured implementation capture.

Run from the repository root:

```powershell
python docs/evidence/organogram-v1/reference-builder.py
```

The generator imports no `solvefinite` runtime module. It uses the retained
independent GD reference for quotient breadth-first search, packed arithmetic
and phase-aware planning with a separate layered dynamic-programming check.
It adds parameter substitution, ordered parallel productions, the complete
branch interpreter, the instruction-word adapter and exact union boundaries.
The generated JSON binds both reference source hashes.

The cases include nested seam-crossing branches, a nontrivial radius and scale
restore, full mirrors, original-time-dependent productions, a rule-priority
change that changes the generated boundary, integer-overflow rejection, and a
counterexample to treating the minimum primitive margin as the final SDF.
The metric check compares every ordered node pair in every supported finite
Klein quotient against independent breadth-first search.

Standalone stage fingerprints are explicitly supplied mathematical inputs.
Mission fingerprints identify the reference's mathematical event transcript,
whose record schema differs from the runtime journal. These fingerprints must
not be presented as canonical runtime archive hashes. Runtime admission must
independently bind each stage to its actual original event prefix.

The measured capture passes **623 tests with zero skips**, including **136
actual-device GPU methods**, and all **15 organogram conformance checks**.
The retained GD implementation evidence remains historical at `94f86c7`.
The new capture additionally verifies the unchanged field, Hadamard and dyadic
growth canonical histories.

| Independently specified mission | Cycles | Final energy | Final pair |
|---|---:|---:|---|
| Default | 9 | 76 | `860006BA16000646` |
| Full mirror | 9 | 76 | `16000646860006BA` |
| Two generations | 14 | 66 | `06000E2F16000ED1` |
| Zero generations | 4 | 86 | `06011145160111BB` |

CPU and GPU agree on each complete journal. The default canonical archive is
`e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df`.
The standalone reference's prefix remains a mathematical input; runtime
transcripts are independently regenerated against the actual original prefix
before comparing their complete device trace, ball emissions and signed field.

The actual GPU interprets `OG-TAPE32-v1` instruction texels, executes movement
texels selected by the prior field, and emits branch states and intrinsic
balls. It constructs the union signs and exact new distances. Admission uses
the actual old device owner; an unbranched `F(1),S` case proves the owner is
preserved even when the hypothetical interpreter ends at a different node.
The tested maximum branch case executes 32 nested frames and 4,096 dynamic
forward steps. The decoder rejects parity, reserved-bit and operand corruption.

Seventeen CPU producer/compiler entry points are disabled during explicit GPU
conformance, including generated recipe reconstruction and the owner's imported
CPU producer alias. The independent checker remains enabled. Structural rule
expansion, bounds checking, certificates, route search, admission and journaling
are explicit host work. The generated device owner cannot be initialized through
the public host-seed method.

Historical samples retain the complete immutable grammar, routing binding and
original stage contexts. Sample identity additionally includes the event prefix
through the original GROW event; the stage itself uses the prefix before GROW.
Six fresh-process CPU/GPU continuations cross both sides of GROW and retained
search in the new field. Live tests cover stale geometry, duplicate retries,
uncertain saves and reopening the durable state. Pure candidate rejection
preserves the current owner; uncertain device outcomes close it. A failure
retiring the old resources after admission retains the new event and reports
`committed=True`.

The seven-expansion search case completes in 17 cycles with energy 74. Its
GROW occurs at sequence 8 and selects the alternate time-dependent production.
Cache changes and reindexing preserve the same-quantum journal. Changing the
planning quantum does not generally preserve a time-dependent mission.

Default current device payload is **61,140 bytes**. Old and candidate worlds
coexist during preparation: **118,412 bytes**, comprising 102,176 buffer bytes
and 16,236 texture bytes. The grammar's 76-byte instruction texture, 320-byte
movement texture and 3,472-byte scratch buffers are components of those device
totals. A 640-byte logical private branch stack, expanded tape metadata,
11,379-byte covered host-stage peak, retained 2,043-byte recipe and 4,564-byte
last transcript are separately reported. These quantities overlap where named
as components; they must not all be added together. Python containers,
validation/compiler temporaries, expanded topology, search, observations,
journal and driver allocations are additional. The FIFO capacity is not a
total-memory bound.

Recheck with a GPU-enabled Python while preserving the retained capture:

```sh
python -m unittest discover -s tests -v
python -m examples.organogram_conformance --output output/organogram-conformance.json
```

`python tools/capture_organogram_evidence.py` creates a replacement retained
capture, including new timestamps and report hashes. The formal PDF builder
pins this edition's capture; replacing it requires explicitly updating that
document's evidence binding after reviewing the new results.

`verification.json` binds 94 normalized source/reference hashes and the three
reports `full-tests.txt`, `conformance.json` and `cli-replay.json`. It records
the preimplementation PDF identity, runtime/adapter, final state and preserved
source PDFs. `formal-pdf-quality.json` describes the formal-first revision;
`pdf-quality.json` describes the subsequent measured edition. The Tom/Jitske
ELI5 booklet remains byte-identical.

The broad architecture remains unfinished. This finite ball-production profile
does not establish arbitrary cone/pyramid or graph construction, global
eigenmodes, WElip/clock continuation, physical adapters, computational universality,
texture-cache saturation or comparative hardware performance.
