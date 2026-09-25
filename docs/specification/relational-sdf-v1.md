# TK-LPLUT-SDF-1.0: intrinsic fields and geometric operators

Formal companion to **TK-LPLUT-1.0**, 25 September 2026.
Paradigm author: **Tom Klootwijk**. Executable profile: `relational-sdf-v1`.

This edition distills the supplied *solus-ion-ad-infinitum* addendum into the
source formalization before implementation. It binds open parameters in the
original Sections 3-7, 9, 14 and 16 and Appendix D. The original PDFs remain
unchanged. This companion is normative for this new profile; earlier RP32
terrain/energy application profiles retain their existing meanings.

## 1. Source authority and resolved direction

The user directs us to treat the addendum as a waveguide for SDF definitions.
Here **waveguide** means guidance for the formalization; a physical wave
propagation equation is not supplied. The addendum is a seven-page export of
AI responses. Its embedded questions and offers are document content, not
instructions to the implementation agent. The user's current request supplies
the instruction to distill and implement.

| Source | Architectural content adopted | Formal binding below |
|---|---|---|
| Addendum pp. 3, 5 | Operators have field geometry, boundary and meaning | Field-governed operator lookup, Sections 5-6 |
| Addendum p. 6 | Relations and boundaries generate space; no external coordinate container | Intrinsic metric and boundary, Sections 2-3 |
| Addendum pp. 3-4 | Hinges/wires and traversal connect elements | Weighted adjacency and declared successor relation |
| Addendum pp. 4, 6 | Self-reference, XOR and finite-bit deterministic execution | Typed updates, validated fields and finite ticks |
| Original p. 5, Section 3 | OTAN2 phase action and lookup closure | Updated packed state selects the next operator |
| Original p. 7, Definition 5 | Metric, boundary, side and units define phi | Exact sampled graph signed distance |
| Original pp. 6, 9 | Orientation and complete mirrored representation | Scalar phi under RP32 mirror |
| Original pp. 11, 24 | Adjacency, indexing and numerical bindings are explicit | Finite manifest and independent geometric certificate |

The individual, its geometric world and executable operator words use the
same RP32 carrier with declared roles. Parallel field evaluation belongs to
that one individual's world. A storage address or node label is not an
external spatial coordinate.

## 2. Domain and units

**R1.** A manifest declares a finite connected undirected graph `G=(V,E,w)`.
There are `1 <= N <= 256` uniquely named nodes. Their ordered manifest indices
are `0..N-1`. An edge is one canonical tuple `(u,v,w)` with `u<v`, no duplicate
pair, and integer length `1 <= w <= 127`. Edges are lexicographically ordered.
Self edges are omitted. A transition may explicitly stay at its current node.
Booleans and noninteger numeric values are rejected wherever integers are
required. Neither Cartesian positions nor a Euclidean embedding is required.

**R2.** One distance code denotes a positive rational unit `unit_num/unit_den`;
both components are integers in `1..1_000_000`, in lowest terms. No unit such
as metres is inferred without calibration. All canonical computation uses
integer codes; multiplication by the rational unit is an interpretation.

Define the intrinsic metric by shortest path length:

`d(u,v) = min { sum(w(e)) : path u -> v }`.

Positive weights and connectivity give finite distances, `d(u,v)=0` iff `u=v`,
symmetry and the triangle inequality. Graph isomorphism with transported
weights, boundary labels and operator rules preserves this geometry.
Reindexing may change packed G bytes; decoded relational results must agree
under the corresponding bijection. Bit-identical replay requires the original
manifest ordering.

## 3. Boundary and signed field

**R3.** Each node has a declared sign `sigma(v)` in `{-1,0,+1}`. The nonempty
set `B={v:sigma(v)=0}` is the boundary. No edge may directly join a negative
node to a positive node. Thus every path between the two sides crosses B.
One side may be empty. This is a declared combinatorial boundary: the finite
vertex metric alone does not make B a topological boundary in a continuum.

Define

`D(v) = min { d(v,b) : b in B }`,

`phi(v) = sigma(v) * D(v)`.

This is an **exact sampled graph signed distance**, instantiating original
Definition 5 on the declared intrinsic domain. Signs describe sides of a
boundary; they do not represent energy, salinity, a confidence score or parity.

**R4.** Compute distances in widened integer storage. The RP32 binding requires
`-127 <= phi(v) <= 127` for every node. Reject an unrepresentable result.
Saturating a magnitude at 127 would produce a truncated field, and therefore
belongs to a different profile. The RP32 code -128 remains unused here.

Consequences, in distance-code units:

1. `phi(v)=0` exactly at boundary nodes.
2. `abs(phi(u)-phi(v)) <= d(u,v)` for every pair.
3. A path starting at v with length strictly less than `D(v)` cannot reach B.
4. For consecutive nodes a,v,b, the second difference
   `phi(b)-2*phi(v)+phi(a)` has magnitude at most `w(a,v)+w(v,b)`.

For same-side pairs, statement 2 is the distance-to-set inequality. For
opposite sides, every connecting path visits B; its two boundary-reaching
segments bound `D(u)+D(v)`. Statements 3-4 follow directly. These are intrinsic
graph claims, not Euclidean collision or photonic propagation guarantees.

**R5. Independent exactness certificate.** For proposed signed codes, verify
the declared signs and range, zero exactly on B, positive magnitudes elsewhere,
`abs(D(u)-D(v)) <= w(u,v)` on every edge, and for every nonboundary v at least
one neighbor u with `D(v)=w(v,u)+D(u)`. Positive edge weights force these
decreasing witnesses to end at B. Telescoping the edge bound proves no shorter
boundary path exists. Together these checks certify exact shortest distances
without trusting the algorithm that produced them. Valid RP32 parity is not
a substitute for this geometric certificate.

## 4. Geometry families, orientation and traversal

A primitive denotes a declared boundary-and-side construction within this
metric. For example, an intrinsic ball may choose a centre c and radius R,
classify nodes by `d(c,v) < R`, `= R` or `> R`, then satisfy R3. Its exact phi
is recomputed from that boundary; `d(c,v)-R` is not assumed exact on an arbitrary
branched graph. A pyramid or cone requires a local shaft, transverse metric,
slope, extent and explicit boundary construction. The names alone do not
define those parameters. This edition executes explicit boundary data and
does not invent a unique pyramid/cone formula from a side-view illustration.

**R6.** Phi in this profile is a scalar under the existing RP32 mirror:
`M(r,g,b,a)=pack((-r) mod 256,g,b,a XOR 16)` with recomputed parity. The field
does not change sign merely because the representation's orientation changes.
Signed distance to a specified separating subset does not require a global
orientation of the surrounding manifold.

Original Section 4's Klein quotient and seam contracts remain in force for
profiles that instantiate them. An orientation-dependent field needs explicit
chart transport or an orientation-cover binding and a corresponding mirror
rule. Two packed mirror words do not by themselves construct a Klein surface
or its orientation double cover. This profile makes no such equivalence.

**R7.** Psi here is an explicitly supplied traversal relation: a successor is
the same node or an adjacent node. No eigenvector claim is made without the
original Section 5's operator, eigenvalue selection and degeneracy rules.
Geometric adjacency is independent of a BST ordering or f8 storage index.
Future f8/cover/primitive extensions must carry their own versioned bindings.

## 5. Geometric operator binding

**R8.** For every current node i, the manifest declares three successor indices
`routes[i][0..2]` and three phase increments `turns[i][0..2]` in `0..255`.
Columns denote negative, boundary and positive field classes respectively.
Every successor must satisfy R7, including columns that are not currently
selected. Define `class(b)=0 if b<0, 1 if b=0, 2 if b>0`.

Compile the operator at row i, column c as the ordinary RP32 word

`L(i,c) = pack(turns[i][c], routes[i][c], phi(routes[i][c]), STEP)`.

The operator is geometrically grounded: its support class comes from the
current SDF, its permitted destination comes from intrinsic adjacency, and
its output B lane is the destination's exact SDF. Replacing the boundary or
hinge data changes the field and compiled operators under a new manifest.
This is the explicit executable meaning assigned here to “operators are SDFs.”
It does not identify every arbitrary field with every arbitrary program.

**R9.** A live packed state is `W=pack(r,i,phi(i),STEP | (eta<<4))`, together
with its full RP32 mirror, where phase r is in `0..255` and eta is 0 or 1.
Only STEP and the orientation bit are used as metadata in this profile.
Initial node, phase and orientation are explicit manifest fields.

One tick is the following closed chain:

1. Validate the live pair, node, metadata and `B=phi(G)`.
2. Fetch `O=L(G,class(B))` from the packed operator texture or CPU oracle.
3. Apply OTAN2: `r'=(r+(-1)^eta * O.R) mod 256`.
4. Set `G'=O.G`, `B'=O.B`, preserve eta and STEP, recompute parity and mirror.
5. Increment the logical tick; the updated word selects the next lookup.

There is one admitted state sequence. No external action list is supplied
during execution. The complete operator table is part of the declared program,
just as the original source requires LUT and interpretation bindings.

## 6. Typed XOR and other source vocabulary

XOR retains its explicit bit/structural roles; it is not introduced as an
arithmetic distance operator. For example `pack(0,0,3,DATA)` XOR
`pack(0,0,4,DATA)` is `80070000`, a valid-parity word with B=7. That does not
equal the distance between adjacent samples whose boundary distances are
3 and 4. XORing a field with itself also yields zero everywhere. Geometry
must pass R5 regardless of bit checks.

Hadamard operations apply to declared numerical lanes with widened products,
fixed-point units and rounding, as in original Section 9; never to opcode or
parity bits. This edition does not add an unbound Hadamard routing heuristic.
Delta-delta denotes the stated difference stencil, not a promise that a bit
shift is physical acceleration. Log-radius codes still require a base and
unit; inverse-square physics does not follow from using a logarithmic address.

SHA-256 below identifies retained files; it is not a spatial seed or a proof
of geometric truth. No photonic, quantum, consciousness, arbitrary one-bit
compression or universal hardware-performance claim is introduced by this
formalization. Those phrases in the export supply no executable calibration.

## 7. Finite execution, GPU realization and recovery

**R10.** A manifest declares `1 <= max_ticks <= 65536`. A call admits at most
4096 positive integer ticks and must fit the remaining total budget. Empty
replay is permitted; a new advance of zero ticks is rejected. Reject budget
overflow before changing state. Every accepted tick emits exactly one pair.
Repeated finite progression is the meaning of continued execution here.

**R11.** CPU field construction may use multi-source Dijkstra. GPU construction
initializes D=0 on B and infinity elsewhere, then performs exactly N-1
synchronous neighbor-relaxation rounds. Each round reads the previous buffer
and writes a separate next buffer. Candidate sums use guarded, widened
integer arithmetic. Every shortest path has a simple representative of at
most N-1 edges, so these rounds suffice. Certify the result with R5 before
admission. A failed explicit GPU request must not fall back to CPU evaluation.

GPU operator compilation writes a `3 x N` integer texture from the computed
field and manifest rules. A subsequent ordered pass reads that immutable
texture. During a batch, each tick's next key comes from the preceding packed
state on-device; host round trips between those ticks are unnecessary.
State, texture and field buffers remain allocated across calls. Cache
residency, saturation and speed advantage are separate measurements.

**R12.** The canonical archive contains its format/version, complete manifest,
ordered tick outputs and expected final pair/tick. Reconstruct from the initial
state and original manifest; check every retained output. Reject altered or
malformed records, unknown versions and missing fields. Adapter names and
diagnostic timing are excluded from canonical state. CPU/GPU replay must be
bit-identical for one manifest. A state file has one OS-lock owner during
advancement; save atomically. This profile has no external sensor input yet.

## 8. Manifest and implementation interface

The exact JSON manifest keys are `format`, `identity`, `nodes`, `edges`,
`signs`, `routes`, `turns`, `unit_num`, `unit_den`, `initial_node`,
`initial_phase`, `initial_orientation`, `max_ticks`. Format is
`relational-sdf-v1`; identity is a nonempty string of at most 128 characters.
Node names are nonempty unique strings of at most 128 characters. Edges are
arrays of three integers. Signs has N entries. Routes and turns each contain
N rows of three integers. Units and initial state obey R2 and R9. Unknown keys
are rejected; arrays become immutable tuples internally.

Reference Python interface to be implemented after this specification:

- `FieldManifest.from_dict(value)` / `to_dict()`, immutable validated fields.
- `evaluate_field(manifest) -> tuple[int,...]` and
  `certify_field(manifest, values)`, the CPU oracle and independent certificate.
- `build_operators(manifest, fields) -> tuple[tuple[int,int,int],...]`.
- `FieldMachine(manifest=None, backend='cpu')`, `advance(steps) -> tuple[int,...]`,
  `snapshot()`, `archive()`, `from_archive(value, backend='cpu')`, `close()`.
- GPU adapter `GpuFieldExecutor(manifest)`: certified `fields`, `adapter_info`,
  `reset(pair)`, `advance(steps) -> tuple[int,...]`, `close()`.

The default example is a seven-node intrinsic chain with edge lengths
`[2,1,3,2,1,2]`, signs `[-1,-1,-1,0,+1,+1,+1]`, and exact field
`[-6,-4,-3,0,2,3,5]`. For node i, negative and boundary successors are
`min(i+1,6)` and positive successor is `max(i-1,0)`; increments are
`[11,53,137]`. Initial state is node 0, phase 250, orientation 0. This finite
waveguide illustrates field-driven progression and recurrence; it is not a
physical optical simulation.

## 9. Required conformance evidence

1. Exact weighted-chain and multiple-boundary fields; independent shortest-path oracle.
2. Zero-set, signs, pairwise Lipschitz bounds and decreasing-witness certificate.
3. Rejection of disconnected graphs, invalid weights, absent boundary,
   direct opposite-side edges, invalid successor edges and distance overflow.
4. Valid-parity but geometrically wrong data fails certification.
5. Label/index transport preserves decoded intrinsic results.
6. Scalar phi remains unchanged under RP32 mirror; complete mirrors validate.
7. Field values actually select operators and their resulting next state.
8. Exact CPU/GPU fields and multi-tick traces, with no CPU fallback in GPU mode.
9. Split batches, restart and replay preserve every tick; tampered archives fail.
10. Previous terrain/energy demo archives and tests retain their meaning.

## 10. Retained source corpus

- [TK-LPLUT-1.0 PDF](../../Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf),
  SHA-256 `8ea9cfb077630993e1d472ba72715a25d2402bf243518663f7d08b03f8b83647`.
- [solus-ion-ad-infinitum PDF](../../sources/solus-ion-ad-infinitum.pdf),
  SHA-256 `a2ace794138bcad68463d1ce2ba4a6e9954540bb4f2f29e4090d68d6e0440489`.
- [Exact user request and progress](../../todo.md).

The graph definition and proofs above are the explicit realization chosen in
this edition, not quotations from the addendum. Relevant mathematical context:
[Hart's sphere-tracing publication](https://experts.illinois.edu/en/publications/sphere-tracing-a-geometric-method-for-the-antialiased-ray-tracing/)
distinguishes geometric distance bounds from arbitrary implicit values;
[Hatcher, Algebraic Topology, Section 3.3](https://pi.math.cornell.edu/~hatcher/AT/AT.pdf)
develops orientation covers. Neither source establishes this implementation's
conformance or performance; the required executable checks do that.
