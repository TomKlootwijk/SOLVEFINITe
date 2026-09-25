# One individual, its world, and GPU texture execution

Tom's clarification on 25 September 2026 was:

> Right solipsism in the literal meaning of the word and world, single autonomous agent individual, also the paradigm wasnt self-referential universality and saturating the GPU and in the texture cache?

The implementation direction is one persistent individual whose world model,
hypothetical motion and admitted state use the same packed representation.
Parallel world nodes are internal computations of that individual. They do not
create additional identities, policies or independent agents.

The source PDF's Section 1 puts self-reference and the common packed carrier at
the center of the paradigm. Section 14 explicitly permits GPU-resident
representations and chained LUT textures. The universal direction concerns
reusable representations and interpretation across adapters and applications;
the present binary grammar is one binding, not a proof of unrestricted
computation or intelligence. No neural-network training is involved here.

## Implemented execution boundary

`--backend gpu` uses `wgpu==0.32.0` and a hardware adapter. It rejects software
adapters and reports missing dependencies instead of substituting CPU work.
CPU remains the default reference backend for portability.

The following table describes the original binary-world agent. The intrinsic
field-agent policy adds actual persistent-device actions, described below.

| Component | Execution |
|---|---|
| Derive the declared world nodes | GPU workgroups of 64 invocations, one path per lane. Each path repeatedly executes packed state -> lookup key -> packed operator -> new packed state. |
| Operator LUT | Immutable `2 x 4` `r32uint` texture, containing RP32 operator words `pack(delta, branch + 1, 0, GROW)`. Unfiltered integer `textureLoad` preserves every bit. |
| World arena | GPU storage buffer, retained across forecasts; one CPU witness is read after initial derivation. |
| Forecast a selected route | One GPU invocation follows up to 32 dependent steps through resident nodes and packed texture operators. The resulting full forecast is read for action admission. |
| Select and retain one action | CPU policy searches routes and admits the first forecast transition. A separate device buffer mirrors the admitted pair; the durable journal remains the recovery authority. |
| Observe, repair and persist | Current observation admission, target repair debit, search frontier and journal remain in Python. |

The forecast scratch pair is separate from the admitted pair: reaching a
hypothetical future does not advance the live agent. A GPU forecast supplies
the exact word used for a MOVE decision. This is integrated execution, with a
hybrid CPU/GPU control path.

The texture is immutable during a dispatch. Every derivation step recomputes
the lookup row from the preceding packed word. RP32 phase wrapping, signed
fields, metadata, parity and mirror transformation use integer operations.
The shader represents a pair with two `u32` lanes. Field-change uploads clip
to `[-255,255]`, preserving signed-byte saturation even when a profile supplies
arbitrarily large Python integers. Depth-32 paths retain all address bits.

Adapter choice does not enter the canonical manifest or archive. Identical
inputs must yield identical decisions, forecasts and journals on either
backend. Existing v1 and v2 policy semantics are retained.

## Intrinsic field-agent execution

The `tomigidt-field-observe-plan-act-v1` policy uses the same agent owner with
a `KleinFieldRecipe`. Its GPU first constructs and independently certifies exact
scalar distances, then compiles a `12 x N` integer texture: four quotient
neighbors for each of three departure field classes. Generated seam metadata
transports phase and orientation. Live B always remains the signed distance;
energy has its own canonical device lane.

Forecasts execute up to 255 edges in scratch storage. An admitted MOVE or
REPAIR dispatches from persistent device pair and energy. The owner reads back
the actual result and checks it against the prediction before journaling.
Uncertain device outcomes and prediction mismatches close the owner; replay
from its last durable archive is required before continuing. Host stages are
geometric certification, observation admission, route search, action admission
and persistence.

Field samples are reconstructed on demand from the certified scalar buffer,
with no retained array of complete packed world-node pairs. The active sample
FIFO and forecast scratch are separate from canonical state. Default resource
payload is 47,144 device bytes plus a logical 80-byte host scalar certificate,
outside the `8 * capacity` FIFO payload. Expanded geometry, retained inputs,
search, history, Python overhead and driver allocations remain additional.

```sh
python -m solvefinite agent run --scenario examples/tomigidt-field.json --state output/field-agent/gpu.json --backend gpu
python -m examples.field_agent_conformance
```

The [integration evidence](evidence/field-agent-v1/README.md) contains 23
passing conformance checks and 368 passing tests, including 41 actual-device
methods. It includes full agent execution with CPU field/transition oracles
disabled, actual-action failure recovery and equality across backend restarts.

## Run and reproduce

From the repository root, using a real Python installation:

```sh
python -m pip install -r requirements-gpu.txt
python -m solvefinite agent run --backend gpu --state output/tomigidt/gpu.json
python -m solvefinite agent inspect output/tomigidt/gpu.json --backend cpu
python -m solvefinite agent serve --backend gpu --state output/tomigidt/gpu-live.json
python -m unittest discover -s tests -v
python -m examples.gpu_benchmark --depth 16 --repeats 20
python examples/live_sensor_demo.py --backend gpu --state output/tomigidt/gpu-sensor-demo.json
```

Use `--backend gpu` with `agent inspect` and `agent live-inspect` to replay
through the GPU. Switching backends on restart requires no archive conversion.
The live input protocol and its ownership lock are unchanged.

The optional GPU tests compare actual shader execution against the CPU oracle,
including phase/orientation boundaries, signed saturation, depth 32, parity,
mirrors, energy failures, changed hazards, unfinished search and replay.
Hardware tests skip when the optional dependency or hardware is unavailable;
shader or arithmetic failures on an available device fail the suite.
The original binary-backend suite passed **231 tests** with the real NVIDIA
adapter enabled; the current integration result is recorded above.

The actual GPU live-sensor demonstration passed all five checks: wait for
fresh input, recover after hazards drop, reconstruct the same state in a new
process, retry without repeating an action, and complete the six-cycle mission.
Its final pair was `9656236786562399`. The changing-hazard scenario also
completed on the GPU and replayed identically on the CPU; its final pair was
`164E23BB064E2345`. These are different declared sensor timelines.

## Residency, locality and measurements

The measurements in this section concern the binary derivation substrate.
The texture and buffers are device resources. Texture-cache residency is a
separate hardware-managed property. The current LUT is only **32 bytes**, so
repeated access offers strong locality; allocation alone does not establish
cache hits. NVIDIA documents texture-cache locality and distinguishes cache
metrics, occupancy and resource utilization. Neither high occupancy nor a
device-busy percentage by itself establishes saturation.

- [NVIDIA CUDA Best Practices: memory optimizations](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-c-best-practices-guide/)
- [NVIDIA Nsight Compute profiling guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/)
- [WGSL integer texture loads](https://www.w3.org/TR/WGSL/#textureload)

The benchmark uploads one finite world's path descriptors once, reuses them
across dispatches, then reads every result and checks every node against the
CPU. Its timer includes submission and final readback, and excludes setup,
shader compilation and initial upload. It reports logical packed transitions
per wall second, not hardware instructions per second. The Python reference
validation time is not an optimized native CPU performance baseline.

Real-device runs, 25 September 2026:

| Measurement | Result |
|---|---|
| Hardware | NVIDIA GeForce RTX 5070 Ti Laptop GPU |
| Backend / driver | Vulkan / 591.59 |
| World | 65,536 paths, each depth 16 |
| Repetitions | 20 |
| Logical packed transitions | 20,971,520 |
| Submit + final readback wall time | 0.0018765 seconds |
| Logical transitions / wall second | About 11.18 billion, for this small-LUT workload |
| Uploads within timed interval | 0 bytes |
| Final readback | 1,048,576 bytes |
| Explicit device resource payload | 2,098,264 bytes |
| CPU agreement | Every node bit-exact; repeated GPU outputs identical |
| Cache-hit rate / GPU saturation | Not measured |

A longer run used 262,144 depth-18 paths and 500 repetitions: **2,359,296,000**
logical transitions in **0.0275231 seconds** including a 4,194,304-byte final
readback, about **85.72 billion logical transitions per wall second**. Explicit
device resource payload was 8,389,720 bytes. Every node again matched the CPU.
These figures describe repeated derivation with the same 32-byte operator LUT.
The captured reports are retained as [depth 16](benchmarks/rtx5070ti-depth16.json)
and [depth 18](benchmarks/rtx5070ti-depth18.json).

These short timings are workload-specific and sensitive to system load and
clock state. The repeated derivations intentionally reuse the same immutable
inputs. They do not measure fresh sensor processing, route search or complete
autonomous cycles. In particular, the six-node repair graph cannot saturate a
modern GPU. Larger live internal-world workloads are a next implementation
step; the larger standalone benchmark demonstrates only the substrate.

Resource accounting includes explicit buffer payloads and the texture, not
driver allocations, command buffers, staging allocations or Python objects.
Each resident node uses a 16-byte shader slot containing an 8-byte pair plus
padding. Descriptor storage and the CPU witness are additional memory. This
arena is separate from the original capacity-limited World FIFO. The agent's
history and search frontier are also separate; total memory is not claimed
constant.

## Remaining architectural work

Move larger batches of the individual's internal hypotheses and planning onto
the GPU while preserving one admission authority and exact replay. Compare
texture operators with buffer operators at equal semantics, vary LUT size and
workload, and measure L1/TEX, L2, DRAM traffic, stalls and throughput with a
hardware profiler. A tiny resident LUT is insufficient evidence for a general
performance advantage.

This execution reduces host transfers inside each chained derivation or
forecast. It does not physically remove all memory bottlenecks: this GPU still
has registers, caches, device memory and transfer limits. Neither the broader
paradigm's full conformance nor a universal bypass of those limits is claimed
from this reference subset.
