# Dyadic geometry growth: GD1-GD8

The consolidated formal PDF defines this profile. The original sources motivate
growth through changes to internal distance rules; the specific dyadic rule,
target selector, energy cost and finite epoch budget are explicit implementation
bindings. The initial manifest and admitted event history remain authoritative.

`reference-builder.py` and `formal-reference.json` contain independent arithmetic
references. They must not import the `solvefinite` implementation. Their pairs,
targets and routes are expected values, not evidence that the runtime executes
them. `formal-pdf-quality.json` records the formal edition's layout checks.

The production doubles both quotient dimensions and the ball radius. It maps
each old node to even coordinates, retains phase and orientation, and recomputes
the signed field. New boundary nodes can shorten boundary distance: the retained
counterexample maps signed distance -3 to -4, rather than -6.

GD1-GD8 were committed before runtime at `ec1181e`. The historical-prefix
identity amendment was committed at `00b0e64` before adding the required
`prefix_sha256` field. The independent reference uses `RUNNING` for the runtime's
`ACTIVE` state; its numeric states, decisions, routes, costs and final status
are compared directly.

The runtime now performs REPAIR/GROW/continuation within one Tomigidt owner.
The GPU maps actual old canonical state into its independently certified new
field. Complete old and candidate resources coexist until serialized admission;
pure rejection preserves history, while uncertain device outcomes close the
owner. A cleanup error after the swap reports `committed=True` and retains the
new event. Failed live sessions recover by replaying the actual durable file.

| Independent mission | Cycles | Final geometry | Final energy | Final pair |
|---|---:|---|---:|---|
| Default | 14 | 8 by 10 | 64 | `160027E906002717` |
| Full mirror | 14 | 8 by 10 | 64 | `06002717160027E9` |
| Two generations | 25 | 12 by 12 | 33 | `86000F0E16000FF2` |
| Zero generations | 4 | 4 by 5 | 86 | `06011145160111BB` |

The 16 conformance checks compare CPU/GPU histories, actual device state at
every admitted cycle, regenerated samples, capacity/index variations and six
fresh-process continuation cuts. A seven-expansion planning quantum produces
a 61-cycle mission whose retained search survives reindexing in the new
geometry. Eleven CPU compiler entry points are disabled during explicit GPU
construction, growth, actions, history reconstruction and replay; host admission
and route search still execute on the CPU.

Historical samples retain the SHA256 fingerprint of the exact original event
prefix through their admission sequence. Its encoding is compact, sorted-key,
ASCII-escaped JSON encoded as UTF-8 with no trailing newline. The complete
events remain in the archive. A same-named node in another generation or a
sample from a different original history does not silently replace it.

Default old-plus-candidate device payload is 177,504 bytes (137,904 buffer bytes
and 39,600 texture bytes). Covered host payload includes 6,432 index bytes,
6,800 routing-table bytes, 1,600 routing-neighbor bytes, 64 gain bytes, 400 field
code bytes and 1,600 geometry bytes. These are logical payloads, not total
process/driver memory. Complete rejected candidates also contribute to the
preparation peak. Active sample FIFO, expanded topology, transient compilation,
search and retained history have separate costs.

Reproduce with the GPU-enabled Python:

```sh
python docs/evidence/growth-v1/reference-builder.py
python -m examples.growth_conformance --output output/growth-conformance.json
python tools/capture_growth_evidence.py
```

The capture writes `full-tests.txt`, `conformance.json`, `cli-replay.json` and
`verification.json`. The last file binds normalized source and report hashes,
formal chronology, test counts, adapter identity and the canonical archive.
The final formal PDF and `pdf-quality.json` are produced after that capture.

The complete suite passes **546 tests, zero skipped**, including **107 actual
device GPU methods**. Its retained log covers strict bindings, independent
geometry arithmetic, actual device mapping and later actions, original-prefix
sample identity, complete rejected-candidate peaks, uncertain detached/old
device failures, committed cleanup errors, fresh-frame gates, live duplicate
recovery and atomic-save uncertainty. The earlier 479 tests still pass.

The finite profile does not establish arbitrary production grammars, global
spectral traversal, physical adapters, indefinite continuation or a hardware
performance advantage. Those remain within the broader architecture objective.
