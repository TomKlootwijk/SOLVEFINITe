# Independent WElip reference

This is a preimplementation mathematical reference for the finite W1–W8 binding. It is not a W runtime, GPU measurement, or new canonical Tomigidt archive. It projects the already frozen independent organogram mission through a separate W clock, carrier, identity, and pair-cache model.

The normative contract is contained in pages 69-81 of the existing consolidated
[TK-LPLUT-2.0 revision 11 PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
This directory records its reference arithmetic and formal-document checks.
`formal-pdf-quality.json` records rendering and layout review; `preservation.json`
records the independent source, contract-body and protected-PDF comparisons.

Run from the repository root:

```powershell
.venv/Scripts/python.exe docs/evidence/welip-v1/reference-builder.py
```

The generator imports no `solvefinite` code. Before loading the independent OG generator, it verifies the LF-normalized hashes of the OG reference, OG generator, and the GD arithmetic helper that OG imports. The independent OG default and mirrored missions are recomputed and compared with the pinned literals. The historical OG runtime archive hash is retained only as a labelled preservation expectation; it is not used to generate W transitions.

The JSON includes three complete 17-operation mathematical lifecycles: default, mirrored initial owner, and a capacity-eight continuation. Each has 18 LUS records and 37 carrier fragments. It contains exact requests, expected operation rows, responses, latest-only duplicate receipts, current admission cursors, cache witnesses, and owner transition projections. Executor action tick expectations are separate from operation row schemas: MOVE/REPAIR increment that counter, GROW starts a new executor at zero, and emission/cache controls leave it unchanged.

Raw payload vectors cover 0, 1, 5, 9, and 4,096 bytes. State checks cover all 256 phase values, both orientations, and STEP/EMIT metadata: 1,024 cases with 16 selected literals. Fourteen malformed vectors distinguish fragment count, header, syntax, padding, parity, mirror relation, owner metadata, and phase resolution failures. Clock vectors cover the 16-bit carry and the unsigned 48-bit horizon. Retry vectors distinguish current duplicate receipts, stale requests, conflicts, gaps, backward reads, and a new forward emission after completion.

For the main fixture, operation 6 carries from `(clock_epoch=0, tick16=65535)` to `(1,0)` while the agent reaches cycle 2. Operation 10 is agent cycle 5 and geometry epoch 1; it resets the local pair cache and executor action counter. Operation 17 is `(1,11)`, agent cycle 9, geometry epoch 1, energy 76, and pair `860006BA16000646`. The final cache has zero hits, seven regenerations and sixteen evictions. The capacity-eight variant preserves the owner transition projection and ends with four hits, three regenerations and eight evictions.

Two consecutive builds produced byte-identical JSON. Hashes use LF-normalized bytes for source files; emitted JSON is LF:

| Artifact | SHA-256 |
| --- | --- |
| `formal-reference.json` | `0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210` |
| `reference-builder.py` | `369c4f4f9d81cdbf5e897c20a06a08fd0d9949deadefb6f9c42975c9063c7eb7` |
| Canonical main operation transcript | `e2b7b8b47b057319f77fbdeea6146b73eba714c1a8e132b065b7c4671ad4c5e0` |
| Complete phase-case transcript | `8c7bfb35807f741e1d0e5115a958b670f5449b15f5790859b26b8d64561c3a42` |

These literals are conditional on the explicit fixture and frozen numerical binding. Runtime acceptance must separately demonstrate actual owner state emission, whole-operation failure behavior, strict schemas, durable private recovery, and the absence of a public historical read path.
