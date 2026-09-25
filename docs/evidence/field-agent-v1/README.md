# Field-agent integration evidence

Measured on 25 September 2026 after the FI1-FI8 binding was committed in the
consolidated formal PDF at `5ccc0228966684b71f6d8a9172ab31ce11715230`.
The implementation extends the same `Tomigidt` with recipe-derived Klein
geometry, autonomous planning, sample regeneration and actual GPU actions.

The complete suite passed **368 tests, zero skips**, including **41 actual-device
GPU methods**, on NVIDIA GeForce RTX 5070 Ti Laptop GPU / Vulkan 591.59,
Python 3.12.14 and pinned `wgpu==0.32.0`.

| Record | Contents |
|---|---|
| [verification.json](verification.json) | Source hashes, test counts, environment, FI1-FI8 evidence mapping and remaining architecture obligations. |
| [full-tests.txt](full-tests.txt) | Complete passing test output, including legacy profiles and 57 new methods. |
| [conformance.json](conformance.json) | 23 checks, complete CPU/GPU histories, per-cycle device readbacks, FIFO instrumentation, field ablation, deferred search, live retry and cross-process recovery. |
| [cli-replay.json](cli-replay.json) | Three fresh CLI processes: GPU first action, CPU completion, GPU inspection; exact control history and unchanged saved bytes. |
| [pdf-quality.json](pdf-quality.json) | Revision 2 PDF hash, text/layout checks and visual review. |

## Reproduce

Run from the repository root with Python 3.10+ and the pinned GPU dependencies.
The hardware methods require a supported GPU; a run with skipped GPU methods
does not reproduce this device evidence.

```sh
python -m pip install -r requirements-gpu.txt
python -m unittest discover -s tests -v
python -m examples.field_agent_conformance --output output/field-agent/conformance.json
python -m solvefinite agent run --scenario examples/tomigidt-field.json --state output/field-agent/session.json --steps 1 --capacity 1 --backend gpu
python -m solvefinite agent run --state output/field-agent/session.json --steps 64 --capacity 9 --backend cpu
python -m solvefinite agent inspect output/field-agent/session.json --capacity 2 --backend gpu
```

Use a new session path for a new reference mission. The final position is
`k:3:2`, packed pair `06011145160111BB`, separate energy 90, at cycle 4.
The initial route changes after a fresh local hazard; the second move crosses
the reversing seam. Changing only the ball centre from 0 to 4 also changes the
initial route. The one-expansion version completes in 41 cycles, including
retained DEFER steps; its CPU/GPU archives agree exactly.

The conformance runner instruments actual sample derivation through
`A, B, hit A, C, A` with capacity two. Hits leave FIFO order unchanged, A is
evicted, and its next access reconstructs its exact pair. Recipe-only cold
construction and capacity changes preserve canonical results. GPU samples are
materialized from certified scalar storage; there is no hidden complete packed
world-node array. Forecasts do not advance canonical device state.

Fault tests inject a readback failure after an actual seam dispatch and a
valid-pair prediction mismatch. Both close the owner without admitting a new
event; reconstruction from the prior archive restores reproducible execution.
The original local measurements remain necessary for recovery.

## Accounting and scope

The active FIFO holds at most `8 * capacity` bytes of complete-pair payload.
The default 20-node GPU configuration separately allocates 45,944 explicit
buffer bytes and 1,200 texture bytes, totaling **47,144 device payload bytes**,
plus a logical 80-byte host scalar certificate. These counts exclude Python
objects and GPU driver overhead. Expanded geometry, retained search, sensor
observations, journal and eviction diagnostics are also outside the FIFO bound.

This realizes the finite FI1-FI8 application contract. It does not establish
eigenvector-defined Psi, full f8 ordering, Hadamard routing, geometry-changing
growth, indefinite epochs, physical wave adapters, GPU cache saturation or
comparative performance. Replay checks consistency, not authentication of a
fully rewritten history. Simulated repair is not a physical actuator action.

The ELI5 booklet is byte-identical to the version naming green-blue Tom and
pink Jitske; this implementation updates only the consolidated formal PDF.
