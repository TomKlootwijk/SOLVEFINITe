# Directional geometry: DP1-DP10

The normative contract is in the existing consolidated
[TK-LPLUT-2.0 PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf),
pages 84-97, was committed in revision 13 at `1979e66` before runtime
implementation. Revision 14 preserves that contract and adds measured results
on pages 98-100. The original arithmetic and formal preservation reports below
remain historical; new runtime evidence uses separate report files.

Original specification pages 5 and 7 and the addenda's side-view discussion
motivate a two-dimensional section with a local shaft, slope and extent.
`TAPER(h,p,q)` binds one such family on the existing Klein quotient. The
complete projected occupancy determines an inner vertex boundary; graph
redistancing then produces the exact signed field. The finite rasterization,
boundary convention, limits and versions are explicit realization choices.
Distinct three-dimensional cone and pyramid volumes remain unfinished.

The new `tomigidt-field-taper-plan-act-v1` policy has separate grammar,
instruction, recipe, derivation and growth-receipt profiles. Its W continuation
uses explicit v2 config/protocol/archive identities. Old OG and Wv1 profiles
retain their numerical contracts. Unchanged W words and `baseline_id` labels
alone cannot distinguish the geometry: admission retains the complete protocol
and exact configuration context.

Reproduce the arithmetic from the repository root:

```powershell
python docs/evidence/directional-v1/reference-builder.py
python docs/evidence/directional-v1/geometry-audit.py
python tools/build_formal_spec.py
python docs/evidence/directional-v1/preservation-audit.py --final --rebuild
```

`reference-builder.py` imports only pinned independent OG/GD/W helpers, with no
`solvefinite` import. It retains grammar expansion, complete branch context,
typed instruction words, descriptors, occupancy, boundary, exact field,
independent planned missions and a Wv2 projection. These are literal expected
results for future runtime conformance. Reference event-prefix hashes name
mathematical transcripts, not existing runtime journals or archive hashes.

| Independent expected mission | Cycles | Final energy | Final pair |
|---|---:|---:|---|
| One geometry epoch | 11 | 69 | `16000534060005CC` |
| Full mirror | 11 | 69 | `060005CC16000534` |
| Two geometry epochs | 17 | 55 | `0600111E960011E2` |
| Zero geometry epochs | 4 | 86 | `06011145160111BB` |

The mixed default stage emits two tapers and one ball using 19 logical
instructions, 23 texels, 7 effective forward steps and 41 primitive sites.
Its Wv2 projection contains 19 operations, 20 records and 41 carrier words;
clock carry and cache controls preserve the original agent GROW cycle.

`geometry-audit.py` is a separate standard-library-only checker. It compares
cover projection with transported edge walks and changed deck representatives,
checks mirrored occupancy, compares exact distance using BFS, Floyd-Warshall
and orientation-cover pullback, and compares guarded arithmetic to unbounded
integers. An 8-by-8 taper has a zero vertex with no negative neighbor, proving
that its field cannot equal an old positive-radius OG ball-union field.
Its finite enumeration scope is stated in the report; it is not an exhaustive
enumeration of all allowed parameters or hardware execution.

`preservation.json` and `pdf-quality.json` record source/contract preservation,
reproducibility and rendered PDF review. The historical W measurements remain
bound to commit `1ea9320` and its 106 source/reference identities, rather than
being inherited by future implementations. The three source PDFs and the
Tom/Jitske ELI5 booklet remain unchanged.

The CPU/GPU producer, independent sealed certificate, same-owner continuation
and Wv2 recovery are now implemented. `conformance.json` captures all four
literal missions, independent complete stage documents, actual device states,
historical samples, deferred planning and six fresh-process crossovers.
`welip-conformance.json` captures all three 19-operation Wv2 lifecycles and
GPU → CPU → GPU endpoint recovery with CPU geometry/state producers disabled.

`verification.json` binds the complete zero-skip test log (`full-tests.txt`),
both conformance reports, device identity, formal chronology and the source
inventory before/after execution. Its actual-device method count excludes five
host-only rejection/CPU-wrapper tests inside GPU test classes; the separate
class-level adapter probe is not counted as execution by those methods.
`runtime-preservation.json` and `runtime-pdf-quality.json` audit revision 14;
the earlier `preservation.json` and `pdf-quality.json` remain unchanged.

The retained capture passes **796 tests, zero skipped**, including **179
actual-device GPU methods**, plus **15 mission/geometry** and **8 Wv2** checks.
The suite takes 298.596 s; the complete capture takes 324.735 s on the recorded
NVIDIA GeForce RTX 5070 Ti Laptop GPU/Vulkan environment. All 120 captured
source/reference identities remain unchanged during execution. These timings
describe validation work and are not throughput benchmarks.

Recheck into temporary reports without replacing this capture:

```powershell
python -m unittest discover -s tests -v
python -m examples.taper_conformance --output tmp/dp-recheck.json
python -m examples.taper_welip_conformance --output tmp/wv2-recheck.json
python tools/capture_taper_evidence.py --output-dir tmp/dp-capture
python tools/build_formal_spec.py
python docs/evidence/directional-v1/runtime-preservation-audit.py --final --rebuild
```

The broader architecture objective also retains 3D volumes, more general
graphs/production, global spectral choices, physical adapters, universality
and comparative hardware measurements. This contract does not claim GPU
saturation or a measured bypass of physical memory bottlenecks.
