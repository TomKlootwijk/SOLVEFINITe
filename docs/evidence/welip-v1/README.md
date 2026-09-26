# WElip reference and implementation evidence

The frozen preimplementation reference projects the independent organogram mission through a separate W clock, carrier, identity, and pair-cache model. Runtime evidence is captured separately by `tools/capture_welip_evidence.py`; it compares actual execution with that unchanged reference.

The normative contract is contained in pages 69-81 of the existing consolidated
[TK-LPLUT-2.0 PDF](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
Revision 11 at `74e00f4` froze the contract before runtime implementation.
`formal-pdf-quality.json` records rendering and layout review; `preservation.json`
records the original formal edition's source, contract-body and protected-PDF
comparisons. These historical records remain unchanged.
Revision 12 adds measured results on pages 82-83. `pdf-quality.json` records its
83-page render review; `runtime-preservation.json` independently verifies the
protected contract bodies, document identities, 83 bookmarks, 81 internal
links and a byte-identical rebuild.

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

These literals are conditional on the explicit fixture and frozen numerical binding. They remain independent expectations, distinct from the implementation capture below.

## Reproduce the implementation capture

The complete capture passes **698 tests, zero skipped**, including **145
actual-device GPU methods**, and all **14 W conformance checks**. Hardware is
the NVIDIA GeForce RTX 5070 Ti Laptop GPU through Vulkan. All three reference
lifecycles and all four field policies agree across CPU and GPU.

The canonical complete W archive is
`9dd6e452c43b37482d6b780786b76f40a80e41846d67feb8c9af6a2e10b8b9c1`.
Its agent projection retains the historical OG archive identity
`e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df`.

```powershell
.venv/Scripts/python.exe tools/capture_welip_evidence.py
```

Full capture requires hardware GPU execution and a complete test suite with
zero skips. `verification.json` identifies every runtime, example and test
source, the capture script and all three dependent reference families. Source
inventories and LF-normalized hashes must be identical before and after the
capture. `full-tests.txt` retains the complete suite output; `conformance.json`
retains full CPU/GPU archives, responses, fresh-process transcripts and failure
recovery results. The original formal PDF is identified by its earlier commit
and hash.

For development, `--cpu-only` writes explicitly partial reports under separate
filenames and cannot overwrite the full capture. To repeat conformance without
the complete suite, use:

```powershell
.venv/Scripts/python.exe -m examples.welip_conformance --output output/welip/recheck.json
```

The actual-device run disables the host state encoder and 17 earlier geometry
producer/compiler paths, while permitting independent admission checks and raw
IGNITE byte encoding. Three fresh endpoint processes switch GPU to CPU to GPU,
with different storage indexes, while retaining exact original W ledger prefixes
and final archive. Private evidence instrumentation reads archive files; the W
endpoint exposes only its five forward operations and current admission context.

Failure evidence distinguishes complete malformed output before mutation from
failure after advancement, uncertain device dispatch and an atomic save that
replaces the file before raising. Session tests cover earlier and later save
failures, interruption, concurrency, corrupted archives, terminal controls,
clock exhaustion and transport failure. Deferred search and naturally temporary
insufficient energy recover from retained inputs and fresh observations.
UNREACHABLE uses an explicitly injected planner outcome: all currently admitted
Klein graphs are connected, so that test does not establish disconnected-field
support.

The evidence covers finite W1-W8 correctness and durable reconstruction. It
does not establish indefinite time, global authentication, exactly-once physical
actuation, constant total memory, GPU saturation or a hardware speed advantage.
