# Volume formalization evidence

This directory supports TK-LPLUT-2.0 revision 15, pages 101-117 of the
[consolidated formal PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
VP1-VP16 define a finite three-dimensional Klein-times-circle realization of
the source architecture. They include cubical topology, distinct sphere/cone/
pyramid occupancy, exact signed graph distances, three-component Psi and f8,
eight-bank routing, original-context grammar, same-owner growth and Wv3.

**Status: preimplementation mathematics.** No volume runtime, GPU execution,
durable Wv3 implementation or comparative performance is claimed here.
The latest implemented directional profile remains the capture at
`2943578d6d8cb998281469fd4d93d677bf393259`: 796 tests, zero skips,
179 actual-device GPU methods, 15 directional and 8 Wv2 conformance checks.
Its 120 captured runtime/reference identities remain unchanged in this edition.

## Reproduction

From the repository root, using Python with ReportLab, pypdf and pdfplumber
for the PDF/preservation steps:

```sh
python docs/evidence/volume-v1/reference-builder.py
python docs/evidence/volume-v1/geometry-audit.py
python tools/build_formal_spec.py
python docs/evidence/volume-v1/preservation-audit.py --final --rebuild
```

The first two scripts use standard-library arithmetic. The reference imports
only SHA-pinned earlier independent grammar/carrier helpers, never solvefinite.
The geometry audit imports neither the volume reference producer nor runtime.
The builder verifies frozen inputs and compares all eight complete literal
occupancy/boundary/sign/distance arrays across the two independent outputs.
Both mathematical outputs rebuild byte-identically.

| Artifact | SHA-256 (text normalized to LF) |
|---|---|
| `reference-builder.py` | `ad0917629ec4a29105db477609b2c707861cc3ab73b998546faf41a6ddb3874d` |
| `formal-reference.json` | `a6f06509ff83133d4ef1381f02ab991e5207948459c5e8479b01b0af3471a1a1` |
| `geometry-audit.py` | `a5cee1c990ab751b24b982fb3fbb255328661180facec7d8315fc3c407462ae8` |
| `geometry-audit.json` | `3e061ad2b04ac85db204115fff8a3f6642b4407f89f6562d2bf037459a8fb284` |

## Mathematical coverage

The separate audit passes 20 checks over all 523 admitted dimension triples:
91,290 octahedral vertex links, 1,460,640 orientation-cover cells,
480 primitive cases, 111,240 transported walks and 2,400 deck/inverse-lift
comparisons. It verifies complete cubical incidence and face maps, rather than
inferring a three-manifold from neighbor or Euler counts alone.

Three-dimensional witnesses have cone 29/27/2, pyramid 45/43/2 and sphere
33/26/7 occupied/boundary/interior vertices, with respectively 4, 8 and 8
complete occupied cubes. Cone and pyramid share an axial section while
differing off-axis. The sphere differs from an intrinsic graph ball.

Wide arithmetic is essential even for an admitted 75-site cone. A wrapped
native-u32 implementation produces 40 wrong memberships in this witness.
VP11 specifies exact four-u16-limb square/add/compare operations, preserving
the original parameter domains and finite work/coordinate bounds. The audit
checks 2,024 squares, 22,304 square-sum/comparison pairs, 6,231 geometric
comparisons and 10,108 preflight candidates.

| Reference mission | Cycles | Energy | Final pair |
|---|---:|---:|---|
| Default | 10 | 170 | `9600143F860014C1` |
| Complete mirror | 10 | 170 | `860014C19600143F` |
| Two epochs | 18 | 158 | `16002BAD06002B53` |
| Zero epochs | 4 | 185 | `860236C39602363D` |
| Quantum 7 | 28 | 174 | `060020C11600203F` |

The default stage has 19 logical instructions, 23 texels, 7 forward steps,
3 primitives, 90 charged sites and stack depth 2. It grows at cycle 5 and
the owner moves along the third coordinate at cycle 8. The quantum-7 mission
has 18 DEFER events and grows at original cycle 19; index-only rebuilds between
those quanta preserve its reference history.

Each of three Wv3 lifecycles has 18 operations, 19 records and 39 carrier
fragments, ending at clock epoch 1, tick 12. A retained cross-configuration
witness gives identical initial wire records for different depth-3/depth-4
worlds. Admission therefore requires protocol plus exact configuration,
not baseline_id or raw records alone. These event/operation digests identify
mathematical expectations, not measured canonical runtime archives.

## Preservation and limits

`preservation-audit.py` pins the previous revision at `2943578`, all 82 retained
evidence files, the 120 historical/current DP inventory entries, original
source PDFs and the named Tom/Jitske ELI5 booklet. `preservation.json` records
the finished PDF identity, byte-identical rebuild, protected page bodies and
glyph placement on pages 4-100, bookmarks, links and all-page bounds.
`pdf-quality.json` records the separate rendered-page review.

This edition binds the new realization before its runtime implementation.
Finite exhaustive cases and implementation tests have declared scopes; they
are not a machine-checked proof of the whole paradigm. General graph
production, global spectral choices, physical sensing/actuation, unrestricted
universality and comparative cache/traffic/energy results remain open.
The broader implementation goal remains paused after this requested
documentation commit; this record does not mark that goal complete.
