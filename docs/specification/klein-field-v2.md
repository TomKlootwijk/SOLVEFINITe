# TK-LPLUT-KLEIN-1.0: quotient geometry and transported field execution

This specification was consolidated before implementation in the
[TK-LPLUT-2.0 formal PDF](../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf),
pages 19-21. The PDF supplies the integrated reading edition and measured
implementation status at `8f4b87b`, when the Klein runtime was unimplemented.
The subsequent v2 implementation and fresh evidence are recorded in
[the field guide](../field.md). The PDF's dated status remains historical.

Formal companion to TK-LPLUT-1.0 and TK-LPLUT-SDF-1.0, 25 September 2026.
Paradigm author: Tom Klootwijk. Field profile: `relational-sdf-v2`.
Generated topology descriptor: `klein-grid-v1`.

This specification is recorded before implementation. It supplies the missing
Klein quotient, cell structure and orientation transport from original
Section 4 (p. 6), while retaining the exact intrinsic SDF contract. It does not
replace the full objective with a surface demonstration. Psi eigenstructure,
f8 indexing and regenerative field-world integration remain named obligations.

## 1. Finite quotient and canonical representatives

**K1.** Choose strict integers W,H at least 3, with W*H at most 256. Begin with
integer labels `(u,v)` and the quotient relations

`(u,v+H) ~ (u,v)`, and `(u+W,v) ~ (u,-v)`.

These are temporary local chart labels, not Cartesian physical positions.
They discretize the identifications in original Section 4. For arbitrary
integer u,v and orientation eta in {0,1}, let

`q = floor(u/W)`, `u0 = u-q*W`, `v0 = ((-1)^q * v) mod H`,

`eta0 = eta XOR (q mod 2)`.

The canonical base index is `i=u0*H+v0`. Node names are `k:u0:v0` in index
order. Equivalent representatives agree after transporting orientation.
Negative chart labels use floor division; truncating division is incorrect.
If a phase is transported between these frames it is reflected by `(-1)^q`.

**K2.** Project every unit horizontal and vertical relation into the quotient.
An undirected edge is the sorted pair of its distinct canonical endpoint
indices, with intrinsic weight 1. Retain each edge once, in sorted order.
The seam bit tau is 1 on a horizontal wrap between columns W-1 and 0 and 0
elsewhere. Reverse traversal has the same bit. W,H>=3 avoid collapsed edges
and ambiguous parallel-edge representations in this finite profile.

A local step `u+`, `u-`, `v+` or `v-` returns the canonical destination and its
seam bit. A seam is a geometric relation; it is not inferred from BST ordering.

## 2. Cells and a checkable surface claim

**K3.** Every `(u,v)` with `0<=u<W`, `0<=v<H` contributes the ordered face

`[canon(u,v), canon(u+1,v), canon(u+1,v+1), canon(u,v+1)]`.

The resulting finite cell complex must have V=WH, E=2WH, F=WH. These counts
alone are insufficient. The conformance check must also establish:

- all four corners of each face are distinct and all declared edges occur;
- the graph is connected and every edge has exactly two incident faces;
- at every vertex, the link formed by its face corners is one cycle;
- the Euler characteristic V-E+F is zero;
- coherent orientations cannot be assigned to all faces.

To test the last condition, give each face an orientation multiplier x_f in
{+1,-1}. For an edge shared by f and g, with canonical edge traversal signs
d_f,d_g, the constraint is `x_g=-d_f*d_g*x_f`. Propagate these constraints
through the dual graph and detect a contradiction. The vertex-link and edge
checks establish a closed 2-manifold; they prevent an arbitrary graph with
Euler characteristic zero from being called a Klein surface.

The supplied quotient is the Klein bottle. The verified finite complex also
matches its surface invariants: a connected closed nonorientable surface with
Euler characteristic zero is a Klein bottle. The classification theorem is
background mathematics, not a replacement for checking this construction.
See [MIT, Classification of Surfaces, Lecture 33](https://math.mit.edu/~lurie/937notes/937Lecture33.pdf).

## 3. Orientation cover and nontrivial holonomy

**K4.** The orientation double cover has vertices `(i,eta)`, encoded for audit
as `2*i+eta`. Every base edge `(i,j)` lifts to

`(i,eta) -- (j,eta XOR tau(i,j))` for both values of eta.

Each face lifts twice by following its edge seam bits. The XOR around a face
must be zero, so each lifted boundary closes. The cover must be connected,
closed, orientable and have Euler characteristic zero, with counts
`2WH,4WH,2WH` for vertices, edges and faces. Its vertex links must again be
single cycles. This is a torus, not two disconnected copies of the base.

An independent graph identification sends a lifted representative to

`(U,V) = (u+eta*W, (-1)^eta*v mod H)`

on the periodic `2W by H` toroidal grid. Audit the entire mapped edge set
against that grid, not only its counts. The horizontal loop at v=0 returns
to its base node after W steps with orientation flipped; after 2W steps its
lift closes. A vertical H-step loop preserves orientation. These are explicit
holonomy witnesses. The two cover sheets are representations of the same
individual's local frame, not two independent agents.

## 4. An intrinsic boundary primitive

**K5.** The generator accepts a centre node c and an integer radius R with
`1<=R<=max_v d(c,v)`. Compute unit-edge intrinsic distances from c and assign
negative, zero and positive signs according as the distance is below, equal
to or above R. This produces a nonempty boundary. Unit edges cannot skip an
integer distance level, so the separating-boundary condition of SDF R3 holds.

Recompute the exact SDF as distance to that boundary. Do not assume
`phi(v)=d(c,v)-R`, which need not hold on an arbitrary intrinsic graph. The
SDF remains a scalar across seams. Its pullback to both sheets has the same
distance to the lifted boundary because every base path lifts and every cover
path projects with the same length. A signed section whose sign reverses with
orientation is a different future field profile.

The centre and radius are retained parameters, not a mandatory global origin.
This gives the source's circle/sphere boundary vocabulary one explicit
intrinsic metric-ball binding. It makes no Euclidean solid or 3D immersion
claim and does not assign unprovided cone/pyramid equations.

## 5. Versioned field manifest

**K6.** `relational-sdf-v1` keeps its exact previous schema and execution.
`relational-sdf-v2` adds two required JSON keys to the existing field manifest:

- `seams`: sorted unique arrays `[u,v]`, u<v, naming orientation-reversing
  edges already present in `edges`. All other edges and all self transitions
  have seam bit zero. There is no separately supplied per-route flip table.
- `topology`: either null for a generic explicitly oriented relational graph,
  or exactly `{"format":"klein-grid-v1","width":W,"height":H}`.

When a Klein descriptor is present, regenerate its nodes, unit edges and seam
set from K1-K2 and require exact equality to the manifest. A descriptor cannot
label an unrelated or altered graph as this quotient. Sides and operator rules
remain explicit immutable data and retain all SDF validation requirements.
Only the generated and audited cell complex establishes the Klein claim;
a generic v2 graph with arbitrary seam bits does not.

Python `FieldManifest` gains `profile='relational-sdf-v1'`, `seams=()` and
`topology=None`. Internally a Klein descriptor is the immutable `(W,H)` tuple.
Old manifests serialize without the new keys. A v1 manifest with seams or a
topology descriptor is rejected. Archives retain their existing container
format, with semantics selected by the contained manifest version.

## 6. Packed seam action and mirror coherence

**K7.** Compile each operator with the existing R increment, G destination and
B destination field. Its metadata is `STEP | (tau<<6)`: bit 6 is the original
RP32 profile-local flag and denotes this operator's relative seam action.
Operator bit 4 remains zero. Live-state metadata remains only STEP and the
orientation eta in bit 4; the operator's bit 6 must never leak into live state.
For v1, tau is identically zero, so its operator words remain unchanged.

**K8.** Apply the phase increment in the departure frame, then transport across
the selected edge:

`t = (r + (-1)^eta * delta) mod 256`,

`r' = (-1)^tau * t mod 256`, `eta' = eta XOR tau`.

Set G to the destination and B to its certified scalar SDF, then recompute
parity and the complete mirror. Phase reflection is required: toggling only
orientation is not this chart-transport convention.

Let `U_delta(r,eta)=(r+(-1)^eta*delta,eta)` and
`S_tau(r,eta)=((-1)^tau*r,eta XOR tau)`. A tick is `S_tau o U_delta`.
The RP32 mirror is S_1. U_delta commutes with S_1, and each S_tau commutes
with S_1. Since mirrored states share G and scalar B, they select the same
operator. Therefore the complete transition commutes with the mirror.
This algebra is a declared numerical binding consistent with the source's
quotient and phase contracts; parity alone does not prove it.

**K9.** GPU compilation derives tau from the authoritative edge seam set and
stores it in the integer operator texture. During the existing on-device
tick loop, texture output supplies delta, destination, field and seam action.
Apply K8 without a host round trip. All integer widths, finite budgets,
geometric certificates, resource ownership and replay checks from SDF R1-R12
continue to apply. A mirror pair is still one admitted canonical sequence.

## 7. Generator and conformance interfaces

`KleinDomain(width=8,height=8)` supplies immutable `nodes`, `edges`, `seams`,
`faces`, `cover_edges` and `cover_faces`; `canonical(u,v,orientation=0)`,
`node(u,v)`, `step(node,direction)`, `ball_signs(center,radius)`, and `audit()`.
An audit returns the independently checked base/cover surface properties,
seam-cocycle result and toroidal-cover edge-map result. Invalid complexes are
rejected rather than reported as a successful surface.

`field_manifest(center=0,radius=2,initial_node=0,initial_phase=250,
initial_orientation=0,turns=(11,53,137),max_ticks=65536,identity='TOMIGIDt')`
generates a v2 manifest retaining `(width,height)` and the boundary signs.
All three field classes advance by `u+`; their declared phase increments
still depend on the current field class. The default tour crosses an actual
reversing seam after W ticks. Other intrinsic routing programs can be supplied
through the existing manifest contract. No action list is injected per tick.

Required checks include:

1. Negative and large chart labels, deck-equivalent representatives and both seam directions.
2. Every edge, face incidence and vertex link for odd/even dimensions, including 3x3 and 16x16.
3. Base nonorientability, connected orientable cover, exact toroidal edge isomorphism and loop holonomy.
4. Intrinsic-ball signs, exact boundary distances and scalar pullback to both sheets.
5. Explicit phase reflection and orientation toggling, plus full mirror commutation.
6. Strict v2 schema, malformed seams, descriptor/graph mismatches and unchanged v1 serialization.
7. Bit-identical CPU/GPU fields, seam-crossing traces, split batches and cross-process replay.
8. Regeneration from the retained quotient descriptor; rejection of changed geometry during replay.

No evidence for a finite cell complex is automatically evidence for physical
wave hardware, full f8 indexing or the entire ontological computing objective.
Those continue under the complete source contracts.
