# Exact local Psi and canonical f8: measured implementation

PX1-PX8 were committed in the consolidated formal PDF at `d8de349` before
runtime implementation. This capture advances the field-agent baseline
`c8af71dbb5b526deb1dee97dc61ef5bbd47e6737`. The same autonomous `Tomigidt`
now uses an exact SDF-derived eigenvector index for world reconstruction and
actual GPU texture-row selection.

**421 tests passed, zero skipped**, including **55 actual-device GPU methods**
on NVIDIA GeForce RTX 5070 Ti Laptop / Vulkan 591.59 with `wgpu==0.32.0`.
The full suite took 44.997 seconds on this machine. These are correctness
measurements, not a comparative hardware performance benchmark.

## Retained evidence

| File | What it establishes |
|---|---|
| [formal-reference.json](formal-reference.json) | Literal default 20-node keys, eigenvalues, gradients, canonical order and full tree, committed before runtime. |
| [verification.json](verification.json) | Source and report hashes, exact test counts, adapter, allocations, commands and remaining obligations. |
| [full-tests.txt](full-tests.txt) | Complete passing test log, including legacy behavior, live ownership and CPU/GPU failure paths. |
| [conformance.json](conformance.json) | 20 named checks; independent geometry/BFS/eigenvector oracle; full keys, trees, archives and replay witnesses. |
| [cli-replay.json](cli-replay.json) | Fresh-process GPU1 -> CPU completion -> GPU inspection with different bindings and unchanged saved bytes on inspection. |
| [pdf-quality.json](pdf-quality.json) | Final consolidated PDF identity, render and visual inspection results. |

The conformance runner audits all **702 supported dimension pairs**, covering
**106,045 descriptors**. An independent cover/BFS oracle checks field values,
numeric parent ties, phase transport, keys and median/preorder layout. All 25
bounded gradient pairs are checked under both signs and both chart frames.
Equivalent negative and large coordinate aliases reach the same canonical row.
Valid absent keys return a miss; malformed records and tree witnesses fail
the certificate.

Six actual GPU cases contain **830 nodes** in total. Every node receives a real
device tree lookup and DATA materialization; complete device records and rows
agree with the independent oracle. The default root stores G=1 in row0, and
G=0 is stored in row 10. Tree edge 1->16 is deliberately checked as a
non-geometric edge. Packed G remains the geometric identity throughout.

GPU construction, rebuild and complete mission execution also pass with the
CPU field, Psi, key and tree compilers disabled. The host still constructs
geometry metadata, independently certifies results, searches routes, admits
observations/actions and persists history.

## Rebuilds preserve the same individual

The normal mission performs four replacement index builds; the one-expansion
mission performs 41. Each replacement preserves the full canonical archive,
agent pair and energy, observations, FIFO contents/order/counters, and the
retained planning object's identity. Actual device pair/energy is read at
each checkpoint. Changed index signs and phase origins change storage order
without changing the decisions.

The normal mission still finishes at cycle 4, `k:3:2`, pair
`06011145160111BB`, energy 90. Its canonical archive SHA-256 remains
`291b28c7f14634079fb262d69b87c8fca2b4749fe367519e9cb75a92e15aa9cb`, identical
to the field-agent baseline. Fresh processes replay in both CPU/GPU directions
before the seam and during DEFER. Live retry after a backend/index change
returns the recorded result without admitting another action.

Fault tests cover invalid bindings, epoch overflow before allocation, rejected
certificates, partially allocated candidates, uncertain readback, forged GPU
keys/identities/links, cleanup after an admitted swap and simultaneous operations.
Pure rejection retains the usable previous index. Uncertain device outcomes
close the owner with its admitted history unchanged. Cleanup after a swap is
reported as a committed replacement and requires recovery; it is not reported
as a rejected candidate.

## Storage and scope

Default steady explicit device payload is **49,160 bytes**. During replacement,
both bundles coexist and peak at **51,528 bytes**. Host index logical payload
is **1,296 bytes**, rising to **2,592** for old and candidate versions. The
host field witness is 80 bytes and the executor's neighbor tuple is 320 bytes.
The active FIFO separately budgets `8 * capacity` bytes of sample pairs.
No complete packed world-node arena is retained. Expanded manifests, recipes,
compiler temporaries, search, observations, history, Python objects and driver
allocations are additional; these numbers are not a total process-memory bound.

At most nine tree rows are visited on a 256-node domain. Successful GPU lookup
also performs rank validation and parent-path checking, so that bound does not
describe total lookup work. No speedup, texture-cache hit rate or GPU saturation
is inferred from this capture.

This binds the local rank-one tensor `A = g g^T`, its exact primitive integer
axis and zero-gradient tie. It does not claim that the source addenda uniquely
specified that numerical operator. General spectral Psi, typed Hadamard routing,
geometry growth, cone/pyramid and physical log-resolution bindings, continuing
semantic epochs, physical adapters and comparative performance remain work
toward the full architecture objective.

The original source PDFs remain unchanged. The ELI5 PDF is byte-identical to
the committed booklet naming green-blue Tom and pink Jitske, SHA-256
`06556d7bbae0de54e99f3abb9329869da1fbf085c6c1aab66d563528989c3ea0`.

## Reproduce

From a checkout with Python 3.12 and the pinned optional GPU dependency:

```sh
python -m unittest discover -s tests -v
python -m examples.psi_f8_conformance --output output/psi-f8/conformance.json
python tools/build_formal_spec.py
```

The formal builder also requires ReportLab, pypdf and its configured fonts.
It verifies current PX evidence against current sources and the older FI
source capture against its named Git commit. A source export without that Git
history cannot validate the historical capture through the builder.
