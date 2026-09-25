# Colony runtime v1: explicit realization bindings

This file distinguishes implemented source contracts from choices introduced
for the runnable experiment. It accompanies source specification TK-LPLUT-1.0.

## Version and carrier

The journal format is `solvefinite-journal-v1`. The runtime is
`colony-runtime-v1`, with word profile `RP32-v1` and world grammar
`binary-organogram-v1`. Unknown versions and extra or missing fields fail
admission. A version's algorithm must remain stable when replaying its journals.

RP32 follows Section 7 and Appendix B: phase R and selector G are unsigned
bytes, B is a signed byte, seven A bits are metadata, and bit 31 is even parity.
Metadata bit 4 is orientation. A phase step adds or subtracts its increment
according to orientation. Mirror negates phase modulo 256 and toggles
orientation. Packing recomputes parity. A pinion stores the left word in its
low half and its exact mirror in its high half.

The runtime computes a canonical left update and constructs its right mirror.
It does not simulate two independently scheduled network agents. Mirror and
per-word parity are checked separately when a pair is consumed.

## Baseline and grammar

The manifest retains the complete world seed `(250, 3, 20, 2)`, the identifier
`colony-baseline-v1`, the phase table, field changes and depth budget. This is a
synthetic baseline, not a physical Svalbard measurement or a hash seed.

A binary derivation path is a string of `0` and `1`. The empty string names the
root. The default maximum depth is 8; supported manifests can declare 0..32.
One branch production transforms the current word `(r, g, b, a)` as follows:

```text
row       = (g XOR (r >> 6)) AND 3
delta     = phase_turns[row][branch]
next_r    = OTAN2_256(r, delta, orientation(a))
next_g    = (3*g + branch + 1) modulo 256
next_b    = saturate_to_signed_byte(b + field_changes[branch])
next_a    = (a AND NOT 7) OR GROW
next_word = pack(next_r, next_g, next_b, next_a)
```

Default phase-table rows are `(11,53)`, `(29,83)`, `(47,101)`, `(71,137)`;
field changes are `(-3,4)`. Current output feeds the next row selection.
The depth is a log-radius code with base 2 and local scale unit 1. This is a
scale annotation; waypoint paths do not automatically imply physical distance,
collision-free adjacency or a complete f8 spatial index.

`derive(path)` is pure. `get(path)` materializes a complete mirrored pair in an
oldest-first FIFO cache. Hits do not reorder the cache. Resizing retains the
newest entries. Diagnostic history and retained input records are separate
from the active payload budget.

## Observations, motion and planning

The agent baseline is `(250, 3, 100, STEP)`. Its B lane denotes remaining energy.
A world node's B lane denotes a synthetic terrain code. An observation's B lane
denotes a nonnegative hazard cost. These are profile-specific interpretations
of the same carrier, not interchangeable physical quantities.

An OBSERVE packet carries the generated waypoint's phase and selector, a hazard
in 0..127, and DATA metadata. Its envelope retains the derivation path. The
latest admitted observation for each path affects future motion; all original
observations remain in the journal. A missing observation contributes zero
additional hazard in this synthetic model. That convention is not a claim
that an unobserved real environment is safe.

For agent lanes `(r,g,energy,a)` and waypoint lanes `(_,node_g,terrain,_)`:

```text
cost   = 1 + floor(abs(terrain)/8) + latest_observed_hazard(path)
row    = (g XOR node_g XOR (r >> 6)) AND 3
branch = last bit of path, or 0 at the root
delta  = phase_turns[row][branch]
next   = pack(OTAN2_256(r,delta,orientation(a)), node_g,
              energy-cost, (a AND NOT 7) OR STEP)
```

Negative energy is rejected. The selected plan must also leave the declared
repair cost, which defaults to 5. The planner accepts at most 32 supplied routes
with 1..32 waypoints each. It evaluates all valid candidates, filters routes
with insufficient energy, then minimizes `(movement_cost, route_tuple)`.
The lexical tie rule makes candidate input order irrelevant. There is no
learned policy or automatic route search in this edition.

Repair requires completion of a nonempty selected route and sufficient energy.
It deducts the repair cost, sets EMIT metadata and marks the mission complete.
The completed mission admits no further state-changing events. Actual and
hypothetical movement use the same pure kernel.

## Event envelopes and original time

Every admitted event has consecutive `seq` and `tick` values starting at 1, a
kind, and an eight-digit uppercase hexadecimal RP32 word. A JSON envelope
carries metadata that cannot fit into the four-byte word.

| Kind | Packet contract | Additional envelope data |
|---|---|---|
| OBSERVE | `pack(node_r,node_g,hazard,DATA)` | Original waypoint path. |
| PLAN | `pack(0,0,0,BRANCH)` | Every candidate route, in its original order. |
| ADVANCE | `pack(0,0,0,STEP)` | None; the next waypoint follows from retained plan state. |
| REPAIR | `pack(0,0,repair_cost,CONTROL)` | None. |

The command word's opcode and other fields must match its declared kind. This
prevents accepting arbitrary valid-parity words as executable commands. Word
serialization uses hexadecimal text in JSON; raw RP32 serialization remains
least-significant-byte first as specified in the PDF.

The journal retains all admitted events and original manifest contents. Each
event is validated before live state or cache mutation. Invalid events are
reported as errors and are not recorded. The demo journal budget is 10,000
events; the bounded route and derivation limits make each event finite.

This experiment uses the regenerative interaction profile. It does not expose
or implement WElip's forward-only public interface or historical-read rejection.

## Recovery and conformance

Recovery initializes from the original manifest and applies events at their
original ticks. It never substitutes the request time or loads the expected
snapshot as state. The final derived snapshot must equal the retained witness,
including its types. Duplicate JSON keys, malformed words, missing sequence
entries and unsupported schemas are rejected.

The archive does not contain the live world cache. Different capacities may
change eviction history but must not change the canonical agent or journal.
The demonstration proves this across a subprocess boundary and compares a
resumed run with an uninterrupted control run.

Tests reproduce the Appendix A packed trace, 512 mirror involutions, 131,072
phase/mirror commutations and 96 single-bit corruption checks. Additional tests
cover grammar vectors, finite budgets, observation retention, imagination
purity, command admission, deterministic selection and exact continuation.

These tests establish the declared software behavior. They do not establish
physical model accuracy, complete source-paradigm conformance, cryptographic
authenticity, learning, consciousness, or a hardware performance advantage.
