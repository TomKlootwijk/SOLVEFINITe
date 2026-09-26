# Organogram reference evidence

The normative OG1-OG8 contract is in the existing consolidated
[TK-LPLUT-2.0 PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
This directory retains reproducible arithmetic expectations prepared before
runtime implementation. It is not an implementation-conformance report.

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

CPU/GPU execution, compiler-disabled device production, ownership failures and
fresh-process continuation remain acceptance work until a separate measured
capture exists. The retained GD implementation evidence remains historical at
commit `94f86c7`; the OG arithmetic expectations do not replace it.
