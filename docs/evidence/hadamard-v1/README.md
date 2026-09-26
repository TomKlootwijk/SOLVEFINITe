# Phase-selected Hadamard routing: measured implementation

HP1-HP8 were committed in the consolidated formal PDF at `0c862c3` before
runtime implementation. This capture advances the Psi/f8 baseline `4b8fa89`.
The same Tomigidt individual now uses its live packed phase, local gradient
and squared primitive Psi components to determine directional movement costs.
The semantic policy is `tomigidt-field-hadamard-plan-act-v1`.

**479 tests passed, zero skipped**, including **77 actual-device GPU methods**
on NVIDIA GeForce RTX 5070 Ti Laptop / Vulkan 591.59 with `wgpu==0.32.0`.
The complete suite took 74.444 seconds. These are correctness checks, not a
comparative performance measurement.

## Retained evidence

| File | What it establishes |
|---|---|
| [formal-reference.json](formal-reference.json) | Literal missions, phase/gain ablations and phase-collapse counterexample, committed before runtime implementation. |
| [reference-builder.py](reference-builder.py) | Independent quotient arithmetic, BFS, integer products, phase search and layered-DP cross-check; imports no runtime module. |
| [verification.json](verification.json) | Current source/report hashes, formal chronology, exact test counts, hardware, allocations and remaining obligations. |
| [full-tests.txt](full-tests.txt) | Complete passing regression log, including all prior profiles and new HP coverage. |
| [conformance.json](conformance.json) | Fifteen named checks, actual device outputs, full canonical archives, ablations, index rebuilds, fresh-process replay and live retries. |
| [cli-replay.json](cli-replay.json) | GPU execution through a reversing seam, CPU completion and GPU inspection with different certified index bindings. |
| [formal-pdf-quality.json](formal-pdf-quality.json) | Revision-5 formal specification and visual QA before implementation. |
| [pdf-quality.json](pdf-quality.json) | Revision-6 consolidated PDF identity, normative preservation and final visual QA. |

## Behavior and search

The default mission moves through nodes 4, 16 and 17, then repairs. Its energy
values are 100, 98, 93, 91 and 86. Changing only the initial phase to 192 changes
the first planned route to `[5,10,11,12,17]`; that mission completes in six
cycles with energy 83. Zero gains recover the earlier field policy's movement
costs and final energy 90. These costs are declared integer application units.

The new canonical archive SHA-256 is
`ba3c7a5e2afb068f4648fd0033741bcac36e3db971362cd23b209557c0134467`.
The old field policy still produces
`291b28c7f14634079fb262d69b87c8fca2b4749fe367519e9cb75a92e15aa9cb`.

Search labels contain node, intrinsic phase and hop count. The literal
counterexample reaches node 10 from node 0 at phase 128 for cost 10; merging
different phases loses that route and returns cost 11. A separate independent
test proves an optimal route with a repeated node: under gains multiplied by
four, start 1, target 13 and phase 26, `[2,3,2,1,0,5,10,14,13]` costs 16.
An exhaustive bounded simple-path check finds no route without a revisit at
that cost or below. Other independent DP cases cover ties, hop limits and
quantum boundaries.

The one-expansion-per-cycle mission completes in 32 cycles. Replacing the
index during every cycle retains the exact pending search object, routing
model, observations, energy and FIFO state. New effective hazards invalidate
stale search; invalid observations do not alter admitted state.

## Device execution and admission

Six actual GPU domains contain 830 nodes, including both thin 255-node
domains and a 16-by-16 domain. Independent quotient/BFS equations check each
exported model. The 26,560 penalty comparisons query the certified exported
table at phase-bank boundaries; they are not per-edge GPU dispatches.

The GPU constructs the atlas from certified device fields, gradients, Psi
and gains. Export admission validates every movement/cost pair across all
four banks, four neighbors and three field classes. Tests inject corruption
into each of the 48 pair locations, then check parity, every payload lane,
wrong gain compilation and forged exported penalties/increments. Actual
forecasts and persistent actions select the bank from their evolving packed
state and use real f8 lookup for texture-row selection.

Eleven CPU compiler paths are disabled during explicit GPU construction,
planning, actions, rebuilds, GPU replay and live continuation. The host still
constructs immutable geometry metadata, independently certifies device
results, searches the exported model, admits actions and retains history.

Fresh processes reproduce the complete archive in both CPU/GPU directions
after a reversing seam and during DEFER. Live duplicate retries retain the
same event, file bytes and persistent device state. Fault coverage includes
partial allocation of the gains/export buffers, complete certificate rejection,
uncertain dispatch/readback, valid-parity corruption after admission and
cleanup failure after a committed swap.

## Memory scope

The default device payload is **57,272 bytes**, rising to **67,752 bytes**
while complete old and candidate bundles coexist. The routing atlas is
7,680 bytes; host and device routing tables are 1,360 bytes each. Candidate
certification briefly holds two host routing tables, 2,720 bytes, before
sharing the original equal immutable model with retained planning.

The index, certified device field codes, routing geometry, gains, other
buffers and textures are counted separately in `allocation_info`. Python
objects, driver allocations, temporary compiler data, search routes/frontiers,
observations and journal storage are additional. Only active world sample
pairs have the `8 * capacity` payload bound. The search label bound is
`N * 256 * (max_hops + 1)`; total memory is not constant.

## Reproduce

```sh
python -m pip install -r requirements-gpu.txt
python tools/capture_hadamard_evidence.py
```

The capture requires a supported hardware GPU and rejects skipped tests.
It runs the complete suite, actual-device conformance and CLI replay, then
binds the reports to the inspected source. Rebuild the consolidated PDF with
the PDF dependencies using `python tools/build_formal_spec.py`, followed by
rendered-page inspection. PDF layout QA is separate from runtime evidence.

Global eigenmodes, geometry-changing growth, active scale transitions,
continuing semantic epochs, physical adapters and comparative hardware
measurements remain open architecture obligations. This finite implementation
does not establish cache saturation, a general speedup, calibrated physical
energy or completion of the whole paradigm.
