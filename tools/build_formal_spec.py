"""Build the integrated TK-LPLUT-2.0 edition. Requires ReportLab and pypdf.

Run with the bundled PDF runtime, or install reportlab and pypdf. The default
output is the single tracked artifact under output/pdf/. No runtime is changed.
"""
from pathlib import Path
import argparse
import hashlib
import json
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Preformatted
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf'
EVIDENCE = ROOT / 'docs/evidence/formal-edition-2026-09-25'
INK = colors.HexColor('#172B3A')
TEAL = colors.HexColor('#007D83')
GOLD = colors.HexColor('#C37F28')
MUTED = colors.HexColor('#536876')
PALE = colors.HexColor('#EDF4F5')
RULE = colors.HexColor('#CCD9DF')
WIDTH, HEIGHT = A4
LEFT, RIGHT = 51, 51
CONTENT_W = WIDTH - LEFT - RIGHT
PAGES = []
STYLES = {}


def register_fonts(font_dir):
    font_dir = Path(font_dir)
    for name, filename in [('Body','segoeui.ttf'), ('Bold','segoeuib.ttf'),
                           ('Italic','segoeuii.ttf'), ('Mono','consola.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='Bold', italic='Italic', boldItalic='Bold')
    STYLES.update({
        'body': ParagraphStyle('body', fontName='Body', fontSize=10.2, leading=14.1,
                               textColor=INK, spaceAfter=8),
        'small': ParagraphStyle('small', fontName='Body', fontSize=8.6, leading=11.7,
                                textColor=MUTED, spaceAfter=6),
        'h2': ParagraphStyle('h2', fontName='Bold', fontSize=12.3, leading=16.2,
                             textColor=TEAL, spaceBefore=7, spaceAfter=6),
        'cell': ParagraphStyle('cell', fontName='Body', fontSize=9, leading=12.2, textColor=INK),
        'headcell': ParagraphStyle('headcell', fontName='Bold', fontSize=9, leading=12.2, textColor=colors.white),
        'math': ParagraphStyle('math', fontName='Mono', fontSize=9.3, leading=13.2, textColor=INK,
                               leftIndent=10, rightIndent=8, spaceBefore=7, spaceAfter=14,
                               borderPadding=9, backColor=PALE),
        'code': ParagraphStyle('code', fontName='Mono', fontSize=8.4, leading=11.3, textColor=INK),
        'callout': ParagraphStyle('callout', fontName='Body', fontSize=10.4, leading=14.6,
                                  textColor=INK, leftIndent=11, rightIndent=11,
                                  borderColor=TEAL, borderWidth=0.7, borderPadding=10,
                                  spaceBefore=8, spaceAfter=24, backColor=PALE),
    })


def p(text, style='body'):
    return Paragraph(text, STYLES[style])


def h(text): return p(text, 'h2')
def small(text): return p(text, 'small')
def box(text): return p(text, 'callout')
def eq(text): return p(escape(text).replace('\n','<br/>'), 'math')
def code(text): return Preformatted(text, STYLES['code'])


def table(headers, rows, widths=None):
    data = [[p(escape(str(x)), 'headcell') for x in headers]]
    data += [[p(str(x), 'cell') for x in row] for row in rows]
    if widths is not None: widths = [CONTENT_W*x for x in widths]
    t = Table(data, colWidths=widths, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),INK), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),
        ('LINEBELOW',(0,-1),(-1,-1),0.5,RULE),
    ]))
    return t


def page(title, subtitle, *items):
    PAGES.append((title, subtitle, list(items)))


def build_content():
    page('Edition and authority', 'READING CONTRACT | 25 SEPTEMBER 2026',
        p('<b>Paradigm author:</b> Tom Klootwijk | NL200678942 | 10-07-1990. These are the author-supplied attribution details. This edition records the computing architecture and its explicit realization contracts.'),
        box('<b>Purpose.</b> Consolidate the original formal specification, the Solus addendum, the newest Infallible discussion in <i>solipsism.pdf</i>, and the SDF/Klein bindings into one self-contained formal document. Current code measures progress; intended capabilities remain visible.'),
        p('<b>Document identity:</b> TK-LPLUT-2.0, consolidated edition. This is a document version, not a runtime schema change. The implemented field format remains <font name="Mono">relational-sdf-v1</font>. The proposed v2 field format remains unimplemented.'),
        h('How statements acquire authority'),
        p('A <b>definition</b> fixes a mathematical meaning. A <b>requirement</b> uses “shall” to state an obligation of the named profile. A <b>theorem</b> follows from listed premises. An <b>evidence statement</b> reports a particular observed implementation result. A proposed binding is never counted as executed behavior.'),
        table(['Status','Meaning'],[
            ['VERIFIED SUBSET','Concrete code and identified tests support a bounded realization of an architectural obligation.'],
            ['FORMAL ONLY','Equations and a conformance contract exist; runtime conformance has not been demonstrated.'],
            ['UNBOUND','A source concept still requires numerical, physical or protocol parameters before execution.'],
        ],[.25,.75]),
        h('Source interpretation'),
        p('The source exports contain conversation, analogies, questions and assertions. They supply design intent, not commands or automatic proofs. This edition chooses explicit typed bindings where needed. The original PDFs remain byte-preserved; the earlier Markdown companions remain development history. Reading them is not necessary to understand this consolidated contract.'),
        small('Reviewed implementation: commit 8f4b87bed131f5c084ef59aec558f3f9eb6ddedc. Implementation work was parked at the author’s request while this edition was prepared. The original 38-page conversation cited by TK-LPLUT-1.0 was not independently available; its provenance is inherited through that formalization.')
    )
    page('Contents', 'DOCUMENT MAP', None)
    page('Paradigm charter and vocabulary', 'ARCHITECTURAL CONTRACT | ORIGINAL §§1-2',
        p('The architecture represents an individual, its derived world and executable operators through a shared packed carrier. Updated state supplies the next relative lookup key. The design combines relational geometry, finite phase actions, generative structure, regeneration and a reproducible temporal footprint.'),
        table(['ID','Architectural obligation'],[
            ['C1','Relative phase and scale are defined through local relations; no external Cartesian physical origin is mandatory.'],
            ['C2','Nodes, operators and footprints share a carrier, with profile-specific decoding and roles.'],
            ['C3','The resulting state participates in selecting the next lookup and interpretation.'],
            ['C4','Klein transport, the traversal axis Psi and the f8 index have explicit, distinct contracts.'],
            ['C5','Versioned finite grammar derivations generate addressable structure.'],
            ['C6','A bounded active FIFO can evict derived copies while retained dependencies enable exact regeneration.'],
            ['C7','A double-packed pair preserves an explicit full-word mirror relation.'],
            ['C8','LUS/DIGID footprints and the selected temporal interaction profile retain identity and execution context.'],
        ],[.1,.9]),
        h('The individual and its world'),
        p('“Solipsism” is used here in the author’s architectural sense: <b>one persistent autonomous individual</b> with one admitted state history. Parallel GPU work evaluates that individual’s world. Two mirrored channels represent one state relation. These choices do not assert that other minds or an external world do not exist.'),
        p('“Ontological” means the represented entities and relations constitute the program’s declared world. “Coordinate-free” means their semantics do not depend on an external physical coordinate frame. Finite labels, memory addresses and temporary charts remain legitimate representations.'),
        small('“Universal” denotes a proposed scope across representations and applications. Computational universality would require a separate simulation theorem. “Infinite” permits repeated finite derivation in the architectural design; it does not supply infinite resources or remove the current field profile’s total tick limit.')
    )
    page('State, admission and transition', 'FORMAL MACHINE | ORIGINAL §§2, 16',
        eq('A_nu = (W, L, P, K, I, Pi)\nS_T = (nu, omega, T, X_T, Q_T, C_T, E_<=T, D_T)\nF_nu(S_T, e_T) -> Result'),
        p('The realization A contains the word carrier W, lookup program L, productions P, topology K, interpreter I and policy Pi. State S retains version nu, baseline omega, logical time T, packed state X, active queue Q and capacity C, admitted event history E and derivation context D. The historical baseline name “Svalbard” denotes a declared role; no geographic measurement is inferred.'),
        table(['Order','Obligation'],[
            ['1-3','Admit interaction kind, epoch and sequence; decode the declared profile; resolve baseline, rule version and retained dependencies.'],
            ['4-6','Lookup or derive a finite operator; evaluate typed numerical lanes; transport through topology and canonicalize the representation.'],
            ['7-9','Repack and check parity/mirror/geometric invariants; retain or evict under policy; emit a status and advance the logical order.'],
        ],[.14,.86]),
        h('Total result contract'),
        eq('Result = ACCEPT(S_next, output, lifecycle)\n       | INVALID(reason) | MISS(dependency) | DEFER(budget)'),
        p('An EVICTED record is a lifecycle outcome attached to an accepted eviction transition. It retains the original specification’s result meaning without ambiguously treating an eviction as both failure and success. A profile shall specify classification priority, bounded parsing and finite execution budgets.'),
        p('Rejected or deferred requests shall not silently masquerade as accepted state changes. A planner may save explicit partial progress through an accepted planning event; a subsequent DEFER observation then refers to that recorded progress. Existing APIs express some failures as exceptions or protocol statuses rather than this abstract tagged union.'),
        box('Every output-affecting choice belongs to the profile, state or admitted input. Time, external measurements, resource-driven semantic changes, rule selection and tie-breaking cannot be hidden dependencies of deterministic replay.')
    )
    page('Log-polar phase and lookup closure', 'FORMAL CORE | ORIGINAL §3',
        h('Scale is a declared relation'),
        eq('rho(k) = rho_* b^k,       b > 1\nlog_b(rho(k2) / rho(k1)) = k2 - k1'),
        p('The integer k names a local log-radius code; rho_* is a local unit. A profile shall declare base, quantization, finite bounds and the word field or derivation context storing k. A shift of an integer and a change of physical radius are different operations until this map relates them.'),
        h('OTAN2 is the phase action'),
        eq('U_delta(r, eta) = (r + (-1)^eta delta mod m, eta)\nr, delta in Z_m;  eta in {0,1};  RP32 uses m = 256'),
        p('OTAN2 is retained as the source’s phase operator, not silently replaced by arctangent. Its increment comes from the selected operator or a declared admitted phase input. The formula is a concrete formal binding; the source does not uniquely specify a transfer function for every physical signal.'),
        h('Self-reference is executable dependency'),
        eq('q_T = key_nu(X_T, e_T)\nO_T = L_nu(q_T)\nX_(T+1) = interpret_nu(O_T, X_T, e_T)'),
        p('The next key is derived from the updated packed state. In the implemented field profile it is (current node, sign class of current field). This produces a closed sequence without an externally supplied action list during the batch. The manifest still supplies the program and its initial conditions.'),
        p('A LUT miss, phase tie, endpoint, orientation change and budget exhaustion shall each have a defined outcome. The finite action group is Z_m semidirect Z_2, with multiplication (a,eta)*(b,zeta) = (a + (-1)^eta b, eta XOR zeta). Its continuous design analogue uses phases in R/Z. This does not identify the Klein bottle itself with a Lie group.'),
        small('Current evidence: RP32 phase/mirror arithmetic and field-selected lookup execute on CPU and GPU. The binary world carries a base-2 depth scale annotation. Active log-radius resolution changes and general physical scale adapters remain separate obligations.')
    )
    page('Uniform carrier and RP32', 'PACKED REPRESENTATION | ORIGINAL §§6-7',
        eq('W_w = {0, 1, ..., 2^w - 1}'),
        p('A profile supplies decoder, interpretation and encoder. “The packet is the operator” means a word can select or parameterize its transition through that interpretation. Common representation does not force every opcode to assign the same meaning to every field.'),
        table(['Bits / lane','RP32 interpretation'],[
            ['0-7 / R','Phase r in 0..255, wrapping modulo 256.'],
            ['8-15 / G','Traversal or lookup selector g in 0..255.'],
            ['16-23 / B','Two’s-complement signed field code in -128..127.'],
            ['24-30 / A0..6','Opcode bits 0..2; jitter bit 3; orientation bit 4; continuation bit 5; profile-local bit 6.'],
            ['31 / A7','Even parity of the complete 32-bit word.'],
        ],[.25,.75]),
        p('Opcodes 0..7 name DATA, STEP, GROW, BRANCH, SEAM, EVICT, EMIT and CONTROL. Names do not supply missing application semantics. The field profile uses STEP with explicit restrictions; the binary world uses its own declared GROW interpretation.'),
        h('Historical layouts remain separate profiles'),
        table(['Source layout','Width and roles'],[
            ['Early f8','8 + 12 + 12: log radius, Psi vector, phase differential.'],
            ['Uniform spatial','8 + 8 + 8 + 8: phase, traversal/Psi, field, metadata.'],
            ['Twin-agent','32 + 32, each described as 16-bit OTAN2 plus 16-bit Lie vector.'],
            ['DIGID / WElip','16 + 16 + 32: respectively routing/integrity/payload or ignition/wave-phase/payload.'],
        ],[.27,.73]),
        small('These historical layouts are not all implemented encodings. A stream shall retain profile and version. A long payload uses a finite ordered word sequence with declared length, continuation and fragment ordering; one word is not assigned an arbitrarily long lossless payload.')
    )
    page('Packing, mirror and exact vectors', 'REFERENCE ARITHMETIC | ORIGINAL §7 AND APPENDICES A-B',
        eq('v = r + 2^8 g + 2^16 (b mod 256) + 2^24 a\np = popcount(v) mod 2;  pack(r,g,b,a) = v + 2^31 p\nM(pack(r,g,b,a)) = pack(-r mod 256,g,b,a XOR 16)\nPair(W) = W + 2^32 M(W)'),
        p('Metadata a contains seven bits. Serialization is least-significant byte first: R, G, B, A. Decode B by subtracting 256 from bytes at least 128. Every repack recomputes parity. The complete pair is one logical unit; the right word is displayed in the high half of its hexadecimal value.'),
        h('Mirror theorem'),
        p('<b>Statement.</b> M applied twice restores every valid RP32 word, and M commutes with U_delta. <b>Proof.</b> Two phase negations and two orientation toggles cancel. Writing s = (-1)^eta, both M(U_delta(r,eta)) and U_delta(M(r,eta)) yield (-r-s*delta, eta XOR 1). G and scalar B are unchanged; deterministic repacking gives identical words.'),
        table(['Tick','Increment','Left word','Right word'],[
            ['0','Initial','81F903FA','11F90306'],
            ['1','11','81F90305','91F903FB'],
            ['2','9','01F9030E','91F903F2'],
        ],[.12,.18,.35,.35]),
        eq('Initial: r=250, g=3, b=-7, a=STEP, eta=0\nPairs: 11F9030681F903FA\n       91F903FB81F90305\n       91F903F201F9030E\nInitial bytes: FA 03 F9 81 06 03 F9 11'),
        p('A capacity-two FIFO receiving these pairs retains the last two and evicts the first as one unit. Retaining the original tuple and increments [11,9] reproduces every pair. Regeneration uses the original context, not a later tick substituted for it.'),
        small('For s&gt;0, RP32 permits a separately declared saturating quantizer Q_s(x)=min(127,max(-128,floor(x/s+1/2))). The exact SDF profile instead rejects distance overflow; it does not use saturation. A right shift is not the inverse of a left shift unless discarded bits are retained.')
    )
    page('One individual, observations and time', 'EXECUTION IDENTITY | ORIGINAL §11 AND SOLIPSISM ADDENDUM',
        p('The individual is the persistent identity and its admitted state history, not the number of CPU threads, GPU lanes or stored representations. A mirror pair is one complete state relation. Separate independent agents would require their own histories and a communication/admission protocol.'),
        eq('X_right(T) = M(X_left(T))\nU_right = M o U_left o inverse(M)'),
        p('The second equation supplies the conjugate operation when a general left update does not commute with the mirror. Synchronization compares version, baseline, epoch, ordered input prefix, tick and transformed state. Identical inputs support independent replay; delivery latency and conflicting input order still need protocol rules.'),
        h('Implemented autonomous subset'),
        p('Tomigidt retains one identity, goals, observations, planning state and execution history. Its deterministic route search uses declared costs and lexical ties. Incremental search retains a frontier across accepted planning events. Unseen distant nodes use a declared zero-hazard planning hypothesis; entering the next node requires a complete fresh local observation frame.'),
        p('The live interface receives external JSONL observations, checks producer/epoch/sequence and handles duplicate retries without advancing twice. Exclusive process ownership and an in-process lock serialize commits. A state save completes before acknowledgment; a failed save poisons the session rather than acknowledging uncommitted progress.'),
        h('Time and continuation'),
        p('A new logical transition advances T; multiple records at one tick use a strictly increasing sequence. Finite clocks require an epoch/wrap policy. Replay uses original event order. Interruptions and waiting can preserve an unfinished individual without fabricating new observations.'),
        box('The observation/planning individual and the intrinsic field machine are currently separate implemented profiles sharing RP32 machinery. The field machine has no external sensor input yet. Their integration into one evolving geometric individual remains an explicit next-stage requirement.'),
        small('Original “juiciness” names a versioned display, deformation or haptic output map from phase/jitter/field changes. Such effects alter canonical state only if admitted back as inputs. Implementation evidence is measured on pages 26-30.')
    )
    page('Generative organogram', 'GRAMMAR AND DERIVATION | ORIGINAL §8',
        eq('Grammar_nu = (Alphabet, w0, Productions_nu, Interpreter_nu)\nw0 = EncodeAxiom_nu(omega)\nN_(T,path) = Interpreter_nu(Derive(w0, rules, T, E_<=T, path))'),
        p('The retained baseline omega and the initial grammar word w0 are distinct. Each rule yields a unique finite string for its admitted context. A derivation identity includes baseline and grammar versions, the original tick and a finite production/branch path.'),
        table(['Symbol / operation','Required interpretation'],[
            ['F','Advance along the local traversal/phase relation and emit or extend a segment.'],
            ['+ and -','Apply a declared positive or negative OTAN2 increment.'],
            ['[ and ]','Push and restore the complete branch context, including orientation.'],
            ['Apex / sphere','Select a boundary primitive and its field construction.'],
            ['Shifts','Invoke a declared resolution transition with explicit widths and lost-bit semantics.'],
            ['XOR','Apply a typed bit operation or structural predicate; mutation and integrity checks have distinct roles.'],
        ],[.24,.76]),
        p('The reference contract uses parallel rewriting of one finite generation at a time. A realization shall bind priorities, unmatched-symbol handling, branch order, maximum depth, stack bounds, time inputs and interpretation costs. Regenerable derivations must be well-founded and retain every non-derived dependency.'),
        h('Current binary realization'),
        p('The binary world derives nodes from finite paths of depth at most 32. Its operator lookup depends on the current phase/selector; a branch updates the selector by (3*g + branch + 1) modulo 256. Packed GROW words, declared field updates and complete mirrors are reproducible from the retained rule set.'),
        small('This realizes a bounded binary organogram. General production tables, arbitrary cone/pyramid generation, an orientation-aware branch stack and geometry-changing growth in the SDF machine are not yet integrated. The source’s geometry vocabulary is retained on page 12 rather than replaced by the binary demo.')
    )
    page('Psi, f8 and typed field operators', 'FORMAL CONTRACTS | ORIGINAL §§5, 9',
        h('Psi requires an operator'),
        eq('A_x Psi_x = lambda_x Psi_x,   Psi_x != 0'),
        p('An eigenvector-based traversal shall bind A_x, eigenvalue selection, normalization, sign/phase convention, degeneracy handling and transport. The current field profile supplies successors directly. A supplied route is not evidence of an eigenstructure implementation.'),
        h('f8 is an index, not the topology'),
        eq('Key_nu(n) = (k_Psi, k_rho, k_theta, k_derivation)'),
        p('Use a total lexicographic order within a declared epoch. Canonicalize equivalent geometric representatives, break distinct-object ties deterministically and version or rebuild the index when ordering changes. A concrete middle-out construction recursively selects a median from the finite ordered set; an executable profile must fix the even-size median choice. Search-tree children and geometric neighbors remain separate relations.'),
        h('Hadamard and difference stencils'),
        eq('H_f(u,v)_i = clip(round_nu(u_i*v_i / 2^f))\nq = H_f(DecodeVector(W), Gradient_nu(phi))\nnext = SelectNeighbor_nu(node, q, topology)\nDelta_a^2 phi(x) = phi(x+a)-2*phi(x)+phi(x-a)\nDelta_T^2 phi_T = phi_(T+1)-2*phi_T+phi_(T-1)'),
        p('Hadamard multiplication applies to decoded numerical lanes with declared fixed-point scale, widened products, rounding and clipping. Opcode, continuation and parity bits are not vector components. The gradient/stencil, neighbor admissibility, ties, stop and fallback rules must be supplied.'),
        p('Spatial and temporal second differences are different operators. On a graph, x+a means the selected adjacent sample in a declared stencil, not an undeclared external coordinate. Spacing and units are required for divided differences.'),
        small('Current status: typed XOR, phase arithmetic and SDF second-difference bounds have checks. General Hadamard routing, eigenvector-derived Psi and a canonical f8 median index remain formal or unbound. No application-wide route-quality claim follows from the formulas alone.')
    )
    page('Relations define the field world', 'GEOMETRIC INTERPRETATION | SOLUS PP.3-6; SOLIPSISM PP.12-13',
        eq('phi(x) = sigma(x) * inf { d(x,b) : b in Boundary }'),
        p('The metric d, boundary, side function sigma and unit jointly determine signed distance. Negative, zero and positive designate inside, boundary and outside under the chosen convention. This is a three-class distinction; distance magnitude supplies additional information.'),
        p('The addenda’s “hinges and wires” become declared weighted adjacency and traversal relations. An operator has geometric support through the current field class, an admissible destination through adjacency and a resulting field value. The implemented binding on page 15 makes those dependencies executable.'),
        table(['Source primitive','Binding required for a distance meaning'],[
            ['Apex','Local convergence or phase-accumulation marker; no mandatory global origin.'],
            ['Circle / sphere','Metric, centre, radius and a boundary/side construction; an intrinsic ball is one finite binding.'],
            ['Pyramid / cone','Local shaft, transverse metric, slope, extent and exact boundary construction.'],
            ['Shaft theta','Selected local traversal/sweep direction, including any difference stencil.'],
            ['Time T','Logical ordering of transitions and input events; distinct from geometric side-view notation.'],
        ],[.25,.75]),
        h('Relational invariance'),
        p('A graph isomorphism transporting weights, sides, boundary and operator rules preserves the intrinsic geometry. Reindexing may change packed G bytes; the decoded relations agree under the bijection. Bit-identical replay additionally retains the original ordered manifest.'),
        p('Distance is measured to the specified boundary. It is not automatically distance to a “self-referential origin.” A node can carry an exact field sample and participate in a geometric operator without being assigned an undeclared physical volume.'),
        small('In this edition “waveguide” names formal guidance and a finite field-driven example. Physical wave propagation requires its own equations and calibration. The finite vertex profile uses a declared combinatorial boundary; it does not claim that a finite discrete metric alone supplies a continuum boundary.')
    )
    page('Exact finite SDF profile', 'IMPLEMENTED CONTRACT | SDF.R1-R4, R6-R8',
        p('<b>Profile:</b> relational-sdf-v1. A finite connected undirected graph G=(V,E,w) has 1..256 uniquely named nodes. Their manifest order supplies indices 0..N-1. Each edge is one sorted tuple (u,v,w), u&lt;v, with weight 1..127. Duplicate pairs, self edges and noncanonical edge ordering are rejected.'),
        eq('d(u,v) = min { sum(edge weights) : path u -> v }\nBoundary = {v : sigma(v)=0}\nD(v) = min {d(v,b) : b in Boundary}\nphi(v) = sigma(v)*D(v)'),
        p('Signs are in {-1,0,+1}; the boundary is nonempty. No edge may directly join opposite nonzero signs. Thus every path between sides crosses the boundary. One side may be empty. Positive weights give a genuine intrinsic vertex metric with symmetry and triangle inequality.'),
        table(['Binding','Strict requirement'],[
            ['Units','unit_num/unit_den, both positive integers at most 1,000,000 and in lowest terms. No physical unit is inferred.'],
            ['Distance range','Compute with widened integers; require -127..127. Reject overflow. Code -128 is unused; no saturation is permitted.'],
            ['Routes','N rows of three destinations, each adjacent to the current node or the node itself, including unselected columns.'],
            ['Turns','N rows of three integer increments in 0..255. Columns mean negative, zero and positive.'],
            ['Identity and nodes','Nonempty strings of at most 128 characters; node names are unique. Integer fields reject Boolean and noninteger values.'],
        ],[.25,.75]),
        p('The field is a scalar under the RP32 mirror: orientation changes do not invert its sign. A side function on a specified separating subset does not require a global orientation of the surrounding surface. Orientation-dependent signed sections require a different field profile.'),
        small('The schema is reproduced on page 31. Its arrays become immutable tuples internally. A malformed geometry is rejected before it becomes an executable field. Tests include disconnected graphs, absent boundaries, invalid routes, opposite-side edges and values beyond the exact distance range.')
    )
    page('Independent geometric certificate', 'THEOREMS | SDF.R5',
        p('A producer proposes signed codes phi. A checker independent of the producing shortest-path algorithm shall verify the declared sign/range, zeros exactly at the boundary, positive magnitudes elsewhere, and the following conditions for D=abs(phi):'),
        eq('|D(u)-D(v)| <= w(u,v)                 for every edge\nD(v) = w(v,u) + D(u)                  for some neighbor u\n                                     at each nonboundary v'),
        h('Theorem G1: exact boundary distance'),
        p('<b>Premises.</b> Positive edge weights, nonempty declared boundary, D=0 exactly there and both conditions above. <b>Proof.</b> The equality witness strictly decreases D. Finiteness and positive weights force a witness chain to terminate at the boundary. Telescoping its equalities yields a path of length D(v). Along any boundary-reaching path, telescoping the edge inequalities gives D(v) no greater than that path’s length. A path attaining D exists and none is shorter. Therefore D is the exact shortest distance.'),
        h('Theorem G2: signed Lipschitz bound'),
        eq('|phi(u)-phi(v)| <= d(u,v)'),
        p('<b>Proof.</b> On one side this is the distance-to-set inequality. For opposite sides, any connecting path visits the boundary because no edge joins opposite signs directly. The portions from its endpoints to the first and last boundary visits bound D(u)+D(v) by the total path length. Taking a shortest path gives the claim.'),
        h('Consequences'),
        p('A path starting at v whose length is strictly less than D(v) cannot reach the boundary. For consecutive nodes a,v,b, the magnitude of phi(b)-2*phi(v)+phi(a) is at most w(a,v)+w(v,b). The latter follows by adding the two edge difference bounds.'),
        box('Parity certifies a bit relation. This certificate certifies a geometric relation. A valid-parity word with an incorrect field value must fail geometric admission.'),
        small('Scope: exactness is relative to the supplied graph, weights and boundary. The certificate does not establish that those data match a measured physical environment. An independent Floyd-Warshall oracle and deliberately forged valid-parity values are included in the current tests.')
    )
    page('Field-governed executable words', 'IMPLEMENTED TRANSITION | SDF.R8-R10',
        eq('class(b) = 0 if b<0, 1 if b=0, 2 if b>0\nL(i,c) = pack(turns[i][c], routes[i][c],\n              phi(routes[i][c]), STEP)\nW = pack(r, i, phi(i), STEP | (eta<<4))'),
        p('Each operator is an ordinary RP32 word. Its R lane is a phase increment, G is the destination and B is the destination’s exact field. The live word uses the same carrier with a different declared role: current phase, node and field. Its companion is always the full mirror.'),
        table(['Tick stage','Exact action'],[
            ['Validate','Check pair, node, STEP/orientation metadata and B=phi(G).'],
            ['Select','Fetch O=L(G,class(B)) using the current state.'],
            ['Evaluate','Set r_next=(r+(-1)^eta*O.R) modulo 256.'],
            ['Transport','Set G_next=O.G and B_next=O.B; retain eta in v1.'],
            ['Commit','Recompute parity and mirror; increment tick and emit one pair.'],
        ],[.19,.81]),
        h('Theorem G3: field-state preservation'),
        p('Suppose the initial pair is valid and each compiled operator contains a legal destination and its certified field. Selection returns such an operator. The resulting G/B relation therefore holds; modular phase remains in range; allowed metadata is reconstructed; repacking supplies correct parity and a complete mirror. Induction preserves these invariants at every accepted tick.'),
        p('The manifest supplies initial node, phase and orientation and a maximum total tick count of 1..65,536. Each advance call accepts 1..4,096 ticks within the remaining budget. Budget overflow is rejected before mutation. Empty replay is permitted; a new advance of zero ticks is rejected.'),
        small('The current program is a finite static geometric operator table. Changing boundary or hinge data under a new manifest changes the field and compiled operators. Runtime geometry mutation, epoch extension beyond the total budget and arbitrary program synthesis are not implemented by this profile.')
    )
    page('Exact GPU realization', 'IMPLEMENTED ADAPTER | SDF.R11; ORIGINAL §14',
        h('Field construction on the device'),
        eq('D_0(v)=0 on Boundary, INF elsewhere\nD_(k+1)(v)=min(D_k(v), min_u(w(v,u)+D_k(u)))\nRun exactly N-1 synchronous rounds'),
        p('Each round reads the previous buffer and writes a separate next buffer. Guarded widened integer sums preserve the chosen infinity sentinel. A shortest path has a simple representative of at most N-1 edges, so these rounds suffice. The independent certificate checks the resulting signed field before execution.'),
        h('Persistent state and an integer operator texture'),
        p('GPU compilation creates a 3 by N r32uint texture from the field and manifest rules. An ordered execution pass reads that immutable texture. One device invocation carries the individual’s sequential state through a batch, with each tick selecting the next lookup from its predecessor. Field construction uses parallel work; the dependent state chain retains its required order.'),
        p('The texture, field buffers and canonical state stay allocated across calls. Host interaction is not required between the ticks inside a batch. Host orchestration, admission, certification, archive handling and batch result transfer remain part of the implementation.'),
        eq('decode_alpha(encode_alpha(W)) = W\ndecode_alpha(Exec_alpha(encode_alpha(S), e)) = F_nu(S,e)'),
        p('These are the adapter round-trip and refinement obligations. Integer bit patterns, word order and version must be preserved. Filtered sampling, color conversion and display interpolation are distinct output views, not canonical execution. Explicit GPU requests raise an error if unavailable; they do not silently evaluate the field on the CPU.'),
        box('Verified: exact CPU/GPU fields and packed traces on the tested Vulkan adapter. Unmeasured: texture-cache residency, cache hit rates, device saturation, energy advantage and a general bypass of von Neumann bottlenecks.'),
        small('A finite cascade of LUT stages must declare intermediate profiles, budgets and progress. Resource schedules that alter semantics are admitted replay inputs; changes only to cache residency must preserve derivation results. GPU texture semantics are described in WGSL [R1]; device profiling requires separate measurements [R2-R3].')
    )
    page('Archives, footprints and admission', 'IDENTITY AND TIME | SDF.R12; ORIGINAL §§12-13',
        eq('LUS = (nu, baseline_id, T, sequence, kind, words, status)\nID = (nu, baseline_id, producer, epoch, sequence, path)'),
        p('LUS retains the source name Linear Unit Strain and its later telemetry role. A profile declares whether a record denotes calibrated strain, simulated boundaries, agent state or another footprint. DIGID/UUID names a structured derivation identity. Naming, representation integrity, origin admission and reproducibility are distinct results.'),
        p('Arbitrary payloads are fragmented into a finite ordered sequence with total length and fragment metadata. Generated payloads may use replay descriptors when all dependencies remain available. Attribution strings are namespace metadata; they are not automatically cryptographic seeds, initialization vectors or authentication. SHA-256 in this document identifies files, not a spatial origin.'),
        h('Implemented field archive'),
        p('The archive retains format, complete manifest, ordered tick pairs and expected final state. Replay begins at the declared initial state and checks every retained pair. Unknown versions, extra/missing fields, malformed hexadecimal words and inconsistent replay are rejected. CPU and GPU adapters may resume each other’s archives. Adapter names and timings are diagnostics outside canonical state.'),
        h('Regenerative R and forward-only W'),
        table(['Profile','Public interaction contract'],[
            ['R: regenerative','Admit named historical derivations whose original context is retained. This is the current implementation family.'],
            ['W: WElip','Admit IGNITE, ADVANCE, RESIZE, INVALIDATE and EMIT; expose no historical-read operation at this interface. Formal only.'],
        ],[.23,.77]),
        p('PRISM reverse lock names a specified rejection predicate for backward-history requests. “Poisoned pill” means localized active-entry invalidation with a recorded cause and retention policy. A read attempt is an event only if the interface detects it. Observation does not automatically change parity.'),
        small('An internally consistent rewritten archive can still replay. Authentication needs an external trust mechanism. Atomic save and exclusive ownership protect the implemented update protocol; replay consistency is not a signature, nor a claim of immunity to storage failure.')
    )
    page('FIFO, regeneration and finite resources', 'FORMAL PROPERTIES | ORIGINAL §§10, 17',
        eq('push_C(Q,x): append x if |Q|<C; otherwise drop oldest, append x\nRegen(d) = Eval_nu(omega, rules, original_T, path, inputs)\nd = (nu, baseline_id, original_T, path, required_inputs)'),
        p('Eviction removes an active derived copy. Baselines, productions, derivation descriptors and external inputs have separate retention policies. A complete pair is one eviction unit. Slot reuse must preserve derivation identity rather than confusing a new occupant with an old queue position.'),
        h('Theorem R1: bounded active queue'),
        p('For C at least one and initial |Q| at most C, insertion below capacity increases length by one; insertion at capacity removes one item before appending one. Hence |Q| never exceeds C. Reducing capacity retains the newest min(|Q|,C_next) items and evicts older entries in order.'),
        h('Theorem R2: exact regeneration'),
        p('If the derivation function is single-valued and every original argument remains available, regeneration evaluates the same expression with the same arguments and yields the original word. Eviction of the active copy cannot alter that result. Missing non-derived input instead produces MISS or exclusion from the exact-regeneration set.'),
        eq('M_occupied = |Q|*w/8 <= C*w/8 bytes\nM_total = M_active + M_baseline + M_rules + M_inputs\n          + M_index + M_journal + M_runtime'),
        p('A preallocated capacity-C payload arena has M_active=C*w/8 bytes, or 8*C bytes for 64-bit pairs. A Python cache also has container and object overhead. The bounded payload is not a bound on the full journal, descriptors or retained observations. Arbitrary external information cannot be reconstructed after its only copy is discarded.'),
        h('Capacity independence and progress'),
        p('When capacity changes only residency, an identical requested derivation must produce the same result at any supported capacity. Resource-driven changes to depth, resolution or selected semantics must instead be recorded as versioned input/control events. Each admitted regeneration uses a finite budget even when the architecture permits an unbounded sequence of finite requests.'),
        small('Implemented: binary-world pair FIFO, retained-context regeneration and capacity-independent decisions. The current SDF profile keeps its finite field and operator arena resident. It does not yet integrate geometry regeneration with the world FIFO.')
    )
    page('Finite Klein quotient', 'FORMAL ONLY | K1-K3',
        p('Choose strict integers W,H at least 3 with W*H at most 256. Temporary chart labels represent a quotient; they do not introduce a mandatory external physical origin.'),
        eq('(u,v+H) ~ (u,v);        (u+W,v) ~ (u,-v)\nq=floor(u/W); u0=u-q*W; v0=((-1)^q*v) mod H\neta0=eta XOR (q mod 2); node=u0*H+v0'),
        p('Negative labels use floor division, not truncation. Phase transported into the canonical frame is multiplied by (-1)^q. Node names are k:u0:v0 in index order. Project each unit horizontal/vertical edge, retain each sorted distinct endpoint pair once and assign unit weight. The relative seam bit tau is one on horizontal wraps between columns W-1 and 0, zero elsewhere.'),
        eq('face(u,v) = [canon(u,v), canon(u+1,v),\n             canon(u+1,v+1), canon(u,v+1)]\nV=WH, E=2WH, F=WH; Euler characteristic=0'),
        h('The surface claim requires cells'),
        p('The audit shall check four distinct corners per face; correspondence between face boundaries and declared edges; graph connectivity; exactly two incident faces per edge; and a single cyclic vertex link at every vertex. These conditions establish a closed connected 2-manifold. Counts alone do not establish a surface.'),
        eq('x_g = -d_f*d_g*x_f'),
        p('Here x_f is a face orientation choice and d_f is its traversal sign along a canonically oriented shared edge. Propagate the constraint through the dual graph. A contradiction establishes nonorientability. A connected closed nonorientable surface of Euler characteristic zero is a Klein bottle [R4].'),
        box('This quotient and audit are a committed formal binding. At the measured implementation commit there is no Klein constructor, cell audit, runtime seam transport or topology test suite. Arithmetic mirror pairs alone do not implement this surface.')
    )
    page('Orientation cover and seam action', 'FORMAL ONLY | K4, K7-K9',
        eq('Cover vertices: (i,eta), encoded as 2*i+eta\n(i,eta) -- (j,eta XOR tau(i,j))\n(U,V) = (u+eta*W, (-1)^eta*v mod H)'),
        p('Lift every base edge twice and each face boundary from both starting orientations. The XOR of seam bits around a face shall be zero. The cover must be connected, closed and orientable, with counts 2WH,4WH,2WH and cyclic vertex links. The displayed map identifies it with a periodic 2W by H toroidal grid; audit the full mapped edge and face sets, not only their counts.'),
        p('A horizontal loop at v=0 returns to its base node after W steps with orientation reversed; its lift closes after 2W steps. A vertical H-step loop preserves orientation. These are explicit holonomy witnesses. The two sheets are local-frame representations of the same individual.'),
        h('Packed transport'),
        eq('Operator metadata: STEP | (tau<<6)\nt = (r + (-1)^eta*delta) mod 256\nr_next = (-1)^tau*t mod 256\neta_next = eta XOR tau'),
        p('Operator bit 6 stores relative seam action; operator bit 4 stays zero. Live metadata contains only STEP and orientation in bit 4. Bit 6 never leaks into live state. Set G to the destination and B to its certified scalar field, then recompute parity and the full mirror. Toggling orientation without reflecting phase is not this transport convention.'),
        h('Theorem K1: mirror coherence'),
        p('Let S_tau(r,eta)=((-1)^tau*r,eta XOR tau). A tick is S_tau composed with U_delta; M=S_1. The phase theorem establishes U_delta commutes with M, and both seam maps commute. Mirrored states share G and scalar B and therefore select the same operator. Their complete tick results remain mirrors.'),
        small('The proof establishes this numerical binding, conditional on a correct geometry/operator implementation. Future GPU compilation derives tau from the authoritative edge set and applies this action inside the existing tick loop. An arbitrary graph with seam bits is not automatically a Klein surface. Orientation-cover background: Hatcher [R5].')
    )
    page('Intrinsic ball and proposed v2 profile', 'FORMAL ONLY | K5-K6',
        p('The proposed manifest format is <font name="Mono">relational-sdf-v2</font>. It requires every v1 key plus <font name="Mono">seams</font> and <font name="Mono">topology</font>. Its archive container remains <font name="Mono">relational-sdf-machine-v1</font>; the manifest selects execution semantics.'),
        eq('1 <= Radius <= max_v d(center,v)\nsigma(v) = sign(d(center,v)-Radius)\nphi(v) = sigma(v) * min_b d(v,b), b in Boundary'),
        p('On the unit-edge quotient, every shortest path from the centre encounters each integer distance level. The selected level is nonempty and unit edges cannot skip from a negative side directly to a positive side. Recompute exact boundary distances; do not assume radial distance minus radius is an exact boundary distance on an arbitrary branched graph.'),
        h('Scalar pullback theorem'),
        p('The lifted field has the same value on both sheets. Every base path lifts and every cover path projects with equal length. A shortest base path to the boundary supplies a cover path to some lifted boundary point; conversely, any cover path supplies a base candidate. The two minimum distances are equal. The side function is pulled back unchanged.'),
        table(['v2 addition','Required interpretation'],[
            ['seams','Sorted unique [u,v] pairs, u&lt;v, naming reversing edges already present in edges. Others and self transitions have tau=0.'],
            ['topology','Either null for a generic relational graph or exactly {format: klein-grid-v1, width: W, height: H}.'],
            ['Descriptor check','Regenerate nodes, unit edges and seams; require exact agreement with the manifest. Only audited cells establish the surface.'],
            ['Compatibility','v1 retains its exact prior schema and bytes. Reject seam/topology additions to v1. Archive semantics follow the contained manifest version.'],
        ],[.26,.74]),
        p('The proposed default generator uses W=H=8, centre 0, radius 2, initial node 0, phase 250 and orientation 0. All field-class routes take the local u+ step; increments are [11,53,137]. This would cross a reversing seam after W ticks. It is a specification example, not a measured trace.'),
        small('Required evidence includes negative/large chart labels, odd/even sizes and 3x3/16x16 extremes, face/link audits, nonorientability, cover isomorphism, holonomy, exact scalar fields, CPU/GPU seam traces, replay and v1 compatibility. None is counted in the present 262-test implementation result.')
    )
    page('The infallible contract', 'NEW FORMALIZATION | SOLIPSISM PP.3-11',
        box('<b>Conditional infallibility.</b> Given a versioned profile with single-valued, total bounded transitions proved to preserve its declared invariants, a valid initial state, completely specified inputs and ordering, and faithful execution, every bounded request has one defined result; every accepted transition preserves those invariants; replay reproduces its canonical output.'),
        eq('Sigma = (States, Inputs, F, Invariant, CanonicalEncode)\nI(S0)\nI(S) and F(S,e)=ACCEPT(S_next,o) => I(S_next)'),
        p('“Closed” means all output-affecting dependencies are in this profile/state/input boundary. It does not mean the executing hardware has no environment. “Infallible” names the exact contract above, not an unexplained extra operation or an assertion of physical immunity.'),
        h('Theorem I1: deterministic replay'),
        p('If F is single-valued, equal profiles, initial states and ordered input sequences yield equal semantic states and canonical outputs at every finite step. <b>Proof.</b> Equality holds initially. Equal states and next inputs give equal results under the same function. Induction extends equality through the finite trace.'),
        h('Theorem I2: bounded total admission'),
        p('If parsing is bounded, every predicate terminates, every loop consumes a finite budget and result classes exhaust the declared domain with a fixed priority, every bounded request terminates with one result. <b>Proof.</b> Each stage terminates and their finite composition terminates. Single-valued classification resolves overlaps.'),
        h('Theorem I3: invariant preservation'),
        p('If I(S0) holds and every accepted step preserves I, all admitted states satisfy I. <b>Proof.</b> Induction over accepted transitions. The SDF invariant includes certified field values, legal destinations, phase/metadata bounds, full mirrors and a remaining execution budget. New geometric rules require a new preservation argument.'),
        small('These are mathematical implications with substantive premises. A proof of a transition theorem, verification of a program and validation against an external phenomenon are different obligations. Finite-state checking is possible; self-reference alone does not invoke an incompleteness theorem or prevent such verification.')
    )
    page('Proof boundary and implementation refinement', 'NEW FORMALIZATION | SOLIPSISM PP.8-16',
        eq('decode(Exec(encode(S),e)) = F(S,e)'),
        p('An implementation refines a profile when this equation holds on the admitted domain, including emitted words and result classifications. A trace comparison is evidence for tested instances. It is not by itself a proof covering every possible program state, driver or device.'),
        table(['Layer','What must be established'],[
            ['Mathematical profile','Single-valued rules, total bounded admission and invariant-preserving transitions under declared premises.'],
            ['Implementation','Encoding, arithmetic, memory order, admission and persistence execute those rules correctly.'],
            ['Fault model','Specified corruptions are detected or recovered under an explicit physical/storage/computation fault model.'],
            ['Physical interpretation','Measured units, observations and transfer functions connect the model to the represented phenomenon.'],
        ],[.27,.73]),
        h('Discrete does not mean unspecified'),
        p('Integer execution avoids floating-point rounding in the canonical field arithmetic. Width, signedness, overflow, shifting and conversion still require exact rules. Floating-point rounding is not inherently randomness; evaluation order and arithmetic semantics determine reproducibility [R6]. A finite discrete representation can execute an incorrect rule perfectly.'),
        h('Geometry changes are accepted state changes'),
        p('The addendum’s internally generated growth can be formalized as a versioned graph-rewrite event. Such an event shall supply a finite rule, affected domain, retained derivation context and deterministic node correspondence. Its result must pass connectivity, boundary, range, topology and operator checks before admission. This is a contract for future growth; no dynamic SDF rewrite is implemented yet.'),
        p('The source’s “zero-order decay” or Lambda label can name a future deterministic invalidation function Lambda_nu(S,e). Its selected entries, predicate, retention effects and result must be bound. It does not acquire a valid numerical meaning by calling unwanted input “noise.” Biological reaction-diffusion analogies require actual equations before they become physical models.'),
        small('Attribution remains attribution. Personal judgments in the exported discussion are not computing predicates. The meaningful architectural claim is a declared domain with exact admitted transitions, for which proof obligations and implementation measurements can be stated and discharged.')
    )
    page('Typed zero, XOR and integrity', 'NEW FORMALIZATION | SOLIPSISM PP.2-3, 7, 11-16',
        h('Boolean involution'),
        eq('NOT(b)=1-b, b in {0,1}\nNOT(NOT(b))=b;  b XOR 1 XOR 1=b;  0*0=0'),
        p('Two negations restore the original bit. NOT(0)=1 is one negation. If two zero operands should yield one, that is an explicitly named equality/XNOR predicate, not ordinary multiplication. Two orientation reversals likewise restore orientation; they do not establish a proposition’s truth.'),
        h('Zero is typed'),
        p('Boolean false, arithmetic zero, phase zero, boundary distance zero, an empty container and a rejected request are different values in different types. SDF zero is a valid boundary. Rejection uses a tagged status. Clearing every bit is not automatically a valid neutral state.'),
        eq('Pair(pack(0,0,0,DATA)) = 9000000000000000\n0000000000000000 fails the full RP32 mirror relation'),
        h('Theorem I4: exact parity detection boundary'),
        eq('parity(w XOR e) = parity(w) XOR parity(e)'),
        p('XOR associativity gives the equation. Even parity detects every odd-weight corruption mask, including every single-bit change, and misses every even-weight mask at that check. It neither locates nor corrects the changed bits. Full mirror comparison checks another relation, but a consistently replaced valid pair can still pass both checks.'),
        eq('pack(0,0,3,DATA) XOR pack(0,0,4,DATA) = 80070000'),
        p('This result has valid parity and B=7. It is not a certificate of the distance between adjacent samples at boundary distances 3 and 4. XORing a field with itself yields zero everywhere without making every original sample a boundary. The independent geometric certificate remains necessary.'),
        small('A chosen one-bit predicate can summarize an inside/boundary/outside condition, but one bit cannot losslessly encode all three classes. Binary hardware, finite packed words, geometric exactness and origin authentication therefore retain distinct contracts.')
    )
    page('Sensory adapters and physical meaning', 'FORMAL INTERFACES | ORIGINAL §15; ADDENDA',
        table(['Source term','Required interface binding'],[
            ['IPD','Relative phase between paired observations: unit, wrap, ambiguity and calibration.'],
            ['IDT','Arrival/sample-time difference: clocks, units, ordering and timing calibration.'],
            ['FMCW / LRAD','Sampled chirp/return model or acoustic transduction interface; deployment-specific geometry and transfer functions.'],
            ['Micro-saccades','Declared small sampling or phase perturbations linked to jitter metadata.'],
            ['Cicada cascades','Periodic triggers for sampling, regeneration or eviction, with a collision priority.'],
        ],[.27,.73]),
        eq('Delta_p = wrap_m(p_right-p_left)\nDelta_t = t_right-t_left\nc_i(T) = 1 if T mod period_i = 0, otherwise 0'),
        p('For periods 13 and 17, both triggers coincide at multiples of 221. A reference one-bit perturbation is (c_1+c_2) modulo two. The manifest must specify its effect on phase or sampling and recompute parity after an intentional state change. Jitter is not an integrity fault by definition.'),
        p('Observed samples, calibration versions and semantic scheduling decisions belong to the replay context. Converting them to range, direction, strain or density requires a physical signal model. Inverse-square physics does not follow from logarithmic addressing; wave mixing is not automatically Hadamard lane multiplication or XOR.'),
        h('Applications permitted by the contract'),
        p('The architecture can host deterministic simulation, regenerable world models, compact geometric controllers and device-independent continuation once their profiles and adapters are specified. Robotics, optical/FPGA execution, biological growth and physical autonomous construction require additional realizations. The current repository demonstrates software/GPU substrates and a simulated/live-observation individual.'),
        box('A complete application must identify what the field means, where its inputs come from, what action an output authorizes, and how the model is validated. The formal architecture supplies a common representation and execution discipline; it does not supply an absent sensor or actuator model.')
    )
    page('Implementation map at the parked commit', 'MEASURED BASELINE | 8f4b87b',
        p('Two realized stacks share the same packed arithmetic. The map below is an inventory of existing modules, not a claim that all source concepts are integrated.'),
        table(['Layer','Existing implementation','Scope'],[
            ['Packed core','rp32.py','Encoding, phase, parity, full mirror and pair.'],
            ['Derived world','world.py; runtime.py','Binary derivation, bounded active FIFO, replay and demo archives.'],
            ['Individual','motion.py; navigation.py; tomigidt.py','Costs, incremental deterministic planning, local observations and action state.'],
            ['Persistence / live','session.py; live.py','Ownership, atomic saves, admitted external frames, deduplication and durable acknowledgment.'],
            ['Packed GPU','gpu.py; packed.wgsl','World derivation and selected motion forecasts; CPU retains planning and admission.'],
            ['Intrinsic field','field.py; field_cli.py','Strict geometry/manifest, exact field, operators, one persistent sequence and replay.'],
            ['Field GPU','sdf_gpu.py; field.wgsl','Device field construction, operator texture and ordered state transitions.'],
        ],[.22,.34,.44]),
        h('Profile meanings remain explicit'),
        p('In earlier motion/world code, B may denote terrain or agent energy. In relational-sdf-v1, B is exact signed boundary distance. Their common RP32 encoding is not permission to reinterpret one profile as another. The field archive retains its complete geometry and the original autonomous stack retains its own observation and policy context.'),
        h('Paused work'),
        p('The next committed specification is the Klein quotient and orientation transport. Runtime implementation had not begun at the measured commit. This PDF detour changes documentation and evidence only. The outstanding integration is a regenerable geometric world with topology, traversal/index bindings and the one individual’s admitted observations and decisions.'),
        small('Source paths are relative to the repository’s solvefinite/ directory. Git evidence was captured from a clean working tree before document authoring. The full commit identity and command provenance are retained with the evidence and on page 33.')
    )
    page('Fresh verification and field trace', 'OBSERVED RESULTS | 25 SEPTEMBER 2026',
        table(['Measurement','Observed result'],[
            ['Full suite','262 tests passed; zero skipped; 23.359 seconds reported by unittest.'],
            ['Actual device coverage','21 GPU test methods: 12 packed-world and 9 SDF methods.'],
            ['Field-family coverage','31 methods: 16 CPU, 10 GPU/dependency, 5 CLI. These overlap the totals above.'],
            ['Conformance example','All 8 checks passed, with 64 ticks per trace.'],
            ['Hardware / software','NVIDIA GeForce RTX 5070 Ti Laptop GPU; Vulkan; driver 591.59; wgpu 0.32.0; Python 3.12.14.'],
            ['Cross-adapter continuation','All 64 packed tick pairs equal. GPU32+CPU32 and CPU32+GPU32 match uninterrupted execution.'],
        ],[.32,.68]),
        eq('Default field: [-6,-4,-3,0,2,3,5]\nMoved boundary: [-8,-6,-5,-2,0,1,3]\nFinal tick 64: node n4, pair 1102046C01020494'),
        p('Changing the boundary changed the field and its resulting execution. CPU/GPU field values and traces remained equal; split batches and archived replay agreed. This tests that geometric data actually governs operator selection rather than merely decorating an unrelated state machine.'),
        h('Reproduce the measured checks'),
        code('python -m unittest discover -s tests -v\npython -m examples.field_conformance --output result.json'),
        p('The evidence directory contains exact command arguments, captured logs, adapter details, both full 64-tick traces, the continuation probe and its source. These are observations at the named commit and device. They do not convert the test count into an architectural completion percentage.'),
        small('Evidence: docs/evidence/formal-edition-2026-09-25/. The suite includes independent geometric oracles, invalid-data rejection, valid-parity forgeries, anti-fallback checks, replay, concurrency/ownership and legacy compatibility. Runtime behavior was not modified during this document task.')
    )
    page('Progress against the architecture: I', 'CAPABILITY STATUS | FINITE REALIZATIONS',
        table(['Obligation','Measured status and remaining work'],[
            ['C1-C3: relational packed execution','<b>Verified subset.</b> RP32 and state-selected integer texture execution work. General active log-radius scale transitions and alternate historical carriers remain unbound.'],
            ['Exact intrinsic SDF','<b>Verified subset.</b> Weighted graph distance, declared separating boundary, units, certificate and field-governed traces work. Continuous primitives and physical calibration are separate.'],
            ['C4: Klein geometry','<b>Formal only.</b> Quotient, cells, cover, intrinsic ball and transported operators are specified. No runtime construction or seam trace exists yet.'],
            ['Psi traversal','<b>Supplied routes verified.</b> An eigenvector-derived traversal needs operator, eigenvalue selection, normalization, degeneracy and frame transport.'],
            ['Hadamard / Delta-Delta','<b>Partly formal.</b> Typed arithmetic and field bounds are defined; second-difference bounds are checked. A geometric Hadamard routing profile is not implemented.'],
            ['f8 middle-out index','<b>Formal / unbound.</b> Total key, canonical identity and median recursion are stated. Full canonical ordering, tie policy and versioned rebuild are not implemented.'],
        ],[.3,.7]),
        h('What the tests establish'),
        p('The implemented graph profile has exact arithmetic and a field certificate, and its tested CPU/GPU realizations agree. These are substantial completed components. They do not establish every named architectural layer by association with the same word carrier.'),
        h('What will count as progress next'),
        p('For topology, evidence must include a real closed surface complex, connected orientation cover, audited holonomy and seam-crossing CPU/GPU traces. For Psi/f8/Hadamard, a versioned numerical profile must first make the named choices executable, followed by independent conformance checks.'),
        small('The requirements matrix continues on page 29. No percentage is assigned because architectural obligations differ in size and some remain unbound; counting passing tests would produce a misleading completion estimate.')
    )
    page('Progress against the architecture: II', 'CAPABILITY STATUS | INTEGRATION AND APPLICATIONS',
        table(['Obligation','Measured status and remaining work'],[
            ['C5: generative world','<b>Verified subset.</b> Bounded binary derivation regenerates exactly. General primitives and geometry-changing grammar execution are not integrated with the SDF world.'],
            ['C6: finite active memory','<b>Verified subset.</b> Pair-atomic FIFO and retained-context regeneration work. Journals/inputs consume additional memory; the SDF arena is resident.'],
            ['C7: complete mirror','<b>Verified subset.</b> Phase involution/commutation, parity and full pair relations work. Geometric seam action awaits the Klein runtime.'],
            ['C8: individual and footprint','<b>Verified subset.</b> Planning, observations, epoch/sequence, retry handling, ownership and durable continuation work. Full LUS/DIGID envelopes and global admission/authentication remain profile obligations.'],
            ['WElip / Lambda','<b>Formal / unbound.</b> Current profiles permit regeneration. A forward-only interface and complete invalidation/clock-wrap binding remain to be implemented.'],
            ['GPU / performance','<b>Verified subset.</b> Exact tested adapters and device execution exist. Cache saturation, general speed/energy superiority and other hardware adapters are unmeasured.'],
            ['Waves / physical growth','<b>Unbound applications.</b> Signal models, physical transfer functions and calibrated action semantics are not supplied by the present code.'],
        ],[.3,.7]),
        h('Continuation sequence after the detour'),
        p('Resume with the formal Klein construction and audits; integrate packed seam transport without changing v1 semantics; then bind the remaining traversal/index operators and connect geometric derivation to the individual’s retained observation/planning loop. Each stage should preserve source traceability and add evidence against its actual obligations.'),
        small('This sequence records remaining work; it does not resume the parked implementation. Whole-system indefinite continuation, autonomous physical self-replication, consciousness and universal immunity are not demonstrated outcomes of the present finite profiles.')
    )
    page('Conformance and performance scope', 'ACCEPTANCE CRITERIA | ORIGINAL T1-T10',
        table(['ID','Criterion and present scope'],[
            ['T1-T4','Exact encode/decode, modular phase, mirror involution/commutation and odd-bit parity detection: exercised for RP32.'],
            ['T5','Canonical topology and transported field meaning: Klein requirements are formal only.'],
            ['T6-T8','FIFO order/pair atomicity, retained-context byte replay and explicit profile/version handling: exercised for existing profiles.'],
            ['T9','Equal semantic histories under tested capacities/batches/adapters: exercised in finite implementations; no general distributed deployment proof.'],
            ['T10','Declared application outputs: graph-field and simulated/live-observation contracts exercised; physical calibration remains unbound.'],
        ],[.17,.83]),
        h('Historical substrate benchmarks'),
        table(['Workload','Logical transitions','Measured batch wall time'],[
            ['Depth 16, 65,536 paths, 20 repeats','20,971,520','0.0018765 s; about 11.18 billion/s'],
            ['Depth 18, 262,144 paths, 500 repeats','2,359,296,000','0.0275231 s; about 85.72 billion/s'],
        ],[.35,.27,.38]),
        p('These repository records date from 25 September 2026 and concern the packed binary substrate. They repeatedly use a 32-byte LUT. Timings include submission/readback but exclude initialization, compilation and upload. Readback sizes were 1,048,576 and 4,194,304 bytes; explicit GPU payload accounting was 2,098,264 and 8,389,720 bytes. CPU results agreed for the benchmark cases.'),
        p('They are not fresh end-to-end autonomy timings, optimized CPU comparisons, cache-hit measurements or proof of device saturation. Logical transition rates for these particular loops cannot be generalized into an architectural bandwidth claim.'),
        h('Required comparison record'),
        p('A meaningful performance comparison records hardware, profile, rule set, LUT and working-set sizes, batch distribution, precision, initialization, transfers, retained inputs, total memory, latency, throughput, regeneration cost and output agreement. Compare the same workload and correctness target. Cache and occupancy claims need corresponding counters [R2-R3].'),
        small('Historical records: docs/benchmarks/rtx5070ti-depth16.json and rtx5070ti-depth18.json. Fresh correctness results are on page 27. No new performance benchmark was run for this PDF detour.')
    )
    page('Executable default and archive schema', 'SELF-CONTAINED REFERENCE | SDF.R1-R12',
        p('This complete default manifest reproduces the implemented seven-node field. All three route columns must be legal even when the current field selects only one.'),
        code('''{
  "format": "relational-sdf-v1", "identity": "TOMIGIDt",
  "nodes": ["n0","n1","n2","n3","n4","n5","n6"],
  "edges": [[0,1,2],[1,2,1],[2,3,3],[3,4,2],[4,5,1],[5,6,2]],
  "signs": [-1,-1,-1,0,1,1,1],
  "routes": [[1,1,0],[2,2,0],[3,3,1],[4,4,2],
             [5,5,3],[6,6,4],[6,6,5]],
  "turns": [[11,53,137],[11,53,137],[11,53,137],
            [11,53,137],[11,53,137],[11,53,137],[11,53,137]],
  "unit_num": 1, "unit_den": 1,
  "initial_node": 0, "initial_phase": 250,
  "initial_orientation": 0, "max_ticks": 65536
}'''),
        h('Reference evaluation'),
        code('''D = exact_shortest_distances_from_all_boundary_nodes(manifest)
phi = tuple(sign[i] * D[i] for i in range(N))
certify_field(manifest, phi)
W = pack(initial_phase, initial_node, phi[initial_node],
         STEP | (initial_orientation << 4))
for tick in admitted_finite_budget:
    r, i, b, a = unpack(W)
    c = 0 if b < 0 else (1 if b == 0 else 2)
    delta, dest = turns[i][c], routes[i][c]
    r = (r + (-1 if a & 16 else 1) * delta) % 256
    W = pack(r, dest, phi[dest], a)
    emit(Pair(W))'''),
        h('Canonical archive'),
        p('Top-level keys are <font name="Mono">format, manifest, trace, expected</font>. Format is <font name="Mono">relational-sdf-machine-v1</font>. Trace entries are exactly 16 uppercase hexadecimal characters, one per accepted tick. Expected contains <font name="Mono">identity, tick, node, agent_pair</font>. The manifest reconstructs the initial pair; trace length is the tick count. Every entry and expected final value must agree with replay.'),
        small('The JSON schema is strict: unknown/missing keys are invalid. Canonical word equality does not require incidental JSON whitespace to match. The initial pair is not an emitted tick. State ownership and atomic file replacement belong to the CLI persistence adapter, not to a distance equation.')
    )
    page('Required bindings and stable obligations', 'PROFILE COMPLETENESS | ORIGINAL APPENDIX D',
        table(['Binding family','Required decisions / original requirement IDs'],[
            ['Dependencies','Baseline, version, inputs, deterministic interpretation and retention; original R1.'],
            ['Phase / scale','OTAN2 increment, miss/tie/endpoint behavior, log unit/base, resolution and budget; R2.'],
            ['Topology / geometry','Canonical representatives, seam/mirror action, metric, boundary, signs, primitives and units; R3-R4.'],
            ['Words / grammar','Layout/version, continuation; rule priority, branches, original time and finite derivation; R5-R6.'],
            ['Index / routing','Canonical total keys, ties/rebuild; typed Hadamard, gradient, widths, rounding and admissibility; R7-R8.'],
            ['Regeneration','Required non-derived inputs, capacity policy, pair atomicity, missing-input and budget results; R9-R10.'],
            ['Identity / time','Epoch/input prefix, event ordering, wrap, identity allocation and separate integrity/origin outcomes; R11-R12.'],
            ['Forward interface','Detected-event predicate, localized invalidation and unaffected retained partitions; R13.'],
            ['Adapters / scaling','Exact word preservation, finite cascade stages, ownership, input delivery and resource controls; R14-R15.'],
            ['Physical adapters','Samples, units, calibration, transfer functions and retained scheduling effects; R16.'],
        ],[.27,.73]),
        p('The original R1-R16 namespace is preserved above. The implemented SDF extension uses <b>SDF.R1-R12</b>, consolidated on pages 13-17 and 31. The proposed topology extension uses <b>K1-K9</b>, consolidated on pages 19-21. Their statements retain separate scopes; satisfying one profile does not silently complete another.'),
        small('Original property cross-reference: P1 replay is I1 on p.22; P2 FIFO and P3 regeneration are R1/R2 on p.18; P4 mirror preservation is on p.8; P5 representation independence is the adapter/refinement contract on pp.16,23.'),
        small('Historical vocabulary: mosTADPOLE(thegreenone) names the source input/output lineage; TPVM is Topological Fixed-Point Virtual Machine. Det-0 names reproducibility with complete dependencies. Generative Topological Fabric, Packed Topological FIFO Matrix and Uniform Packed Operator Paradigm are successive functional views. REW expands to Reverse Electronic Warfare in the WElip source. f8’s “BVH replacement / S2 superseder” is an intended indexing/comparison role, not a measured replacement result.'),
        small('A complete manifest may reference immutable versioned rule tables rather than embedding every algorithm in a packet. No “infallible” designation waives a missing binding. A profile is executable only once all choices that affect its outputs are single-valued and finitely evaluable.')
    )
    page('Source concordance and provenance', 'RETAINED CORPUS | CONSOLIDATED READING EDITION',
        table(['Source','Integrated destination in this edition'],[
            ['O: TK-LPLUT-1.0, 24 pages','Original §§1-3: pp.4-6; §§4-5: pp.11-14,19-21; §§6-8: pp.7-10; §§9-11: pp.9,11,18; §§12-16: pp.5,16-17,25; §§17-18: pp.8,14,18,22-24,27-30. Appendices A-B: pp.8,31; C-D: pp.32-34.'],
            ['S: Solus, 7 pages','pp.3-4: operator geometry and hinge/traversal roles; pp.5-6: relational fields and self-reference. Integrated pp.6,11-16,24-25. Search/conversation material is not a new protocol.'],
            ['I: solipsism, 16 pages','pp.3-5: one closed individual, pp.9-13: infallibility/SDF claims, pp.15-16: propagation/decay intent. Integrated pp.9,12,22-25. pp.2-3 arithmetic is corrected in typed form on p.24; personal analogies on pp.14-15 supply no predicates.'],
            ['SDF companion / Klein companion','All normative SDF.R1-R12 and K1-K9 are consolidated in this PDF. Earlier Markdown remains the recorded development sequence.'],
        ],[.28,.72]),
        h('SHA-256 of preserved source PDFs'),
        code('O  8ea9cfb077630993e1d472ba72715a25d\n   2402bf243518663f7d08b03f8b83647\nS  a2ace794138bcad68463d1ce2ba4a6e99\n   54540bb4f2f29e4090d68d6e0440489\nI  1091e0435aa1648b4ede127837e66ddbf\n   2c5dbd0a67f49cbb7a7ae134ee547e7'),
        small('Join each source’s two lines without spaces. Retained paths: O at repository root, S at sources/solus-ion-ad-infinitum.pdf, I at sources/solipsism.pdf. Both addenda originated in the author-named “Philosophers stone Jitske Klootwijk” source directory.'),
        h('Implementation evidence identity'),
        code('8f4b87bed131f5c084ef59aec558f3f9eb6ddedc\nCapture: 2026-09-25, 07:52:57 to 07:54:16 UTC'),
        small('Formalization chronology: SDF specification 477e576 preceded implementation 50c9389; Klein specification 8f4b87b preceded its future runtime. Current evidence is retained under docs/evidence/formal-edition-2026-09-25/. This edition is a new consolidation and does not alter the source bytes.')
    )
    page('Notation and technical references', 'REFERENCE INDEX',
        table(['Symbol / name','Meaning'],[
            ['nu; omega; T','Version; retained baseline; logical tick.'],
            ['r; eta; delta; tau','Phase; local orientation bit; phase increment; relative seam bit.'],
            ['phi; D; sigma','Signed field; unsigned boundary distance; declared side.'],
            ['Psi; theta; f8','Bound traversal/eigenvector role; local sweep direction; relational index.'],
            ['M; Q; C','Full mirror; active FIFO; active capacity.'],
            ['RP32; LUS; DIGID','Packed carrier; typed emitted footprint; structured derivation identity.'],
            ['R / W; Lambda','Regenerative/forward-only interaction profiles; proposed bound invalidation function.'],
        ],[.28,.72]),
        h('Primary technical references'),
        small('[R1] W3C. <a href="https://www.w3.org/TR/WGSL/#textureload" color="#007D83">WebGPU Shading Language, textureLoad</a>. Integer texture access semantics. This reference supplies API background, not a proof of this runtime.'),
        small('[R2] NVIDIA. <a href="https://docs.nvidia.com/cuda/archive/12.8.0/cuda-c-best-practices-guide/" color="#007D83">CUDA C++ Best Practices Guide, version 12.8</a>. Memory hierarchy and measurement background; the tested adapter here uses Vulkan through wgpu.'),
        small('[R3] NVIDIA. <a href="https://docs.nvidia.com/nsight-compute/ProfilingGuide/" color="#007D83">Nsight Compute Profiling Guide</a>. Profiling methodology and counters. No Nsight counter evidence is claimed in this edition.'),
        small('[R4] Jacob Lurie, MIT. <a href="https://math.mit.edu/~lurie/937notes/937Lecture33.pdf" color="#007D83">Classification of Surfaces, Lecture 33</a>. Surface classification used conditionally after manifold/orientation checks.'),
        small('[R5] Allen Hatcher. <a href="https://pi.math.cornell.edu/~hatcher/AT/AT.pdf" color="#007D83">Algebraic Topology, section 3.3</a>. Orientation covers. The concrete finite quotient and required audits are specified in this edition.'),
        small('[R6] David Goldberg. <a href="https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html" color="#007D83">What Every Computer Scientist Should Know About Floating-Point Arithmetic</a> (1991). Rounding and evaluation semantics; cited to separate numerical error from inherent randomness.'),
        small('[R7] John C. Hart. <a href="https://experts.illinois.edu/en/publications/sphere-tracing-a-geometric-method-for-the-antialiased-ray-tracing/" color="#007D83">Sphere Tracing: A Geometric Method for the Antialiased Ray Tracing of Implicit Surfaces</a> (1996). Context for geometric distance bounds. The present certificate is proved directly for a finite graph.'),
        box('<b>Edition status.</b> One integrated formal contract, with exact implemented subsets, explicit formal extensions and reproducible evidence. The implementation remains parked at the author’s requested detour; the remaining architecture is recorded without being marked complete.')
    )


def cover(c, count):
    c.setFillColor(INK); c.rect(0,0,WIDTH,HEIGHT,fill=1,stroke=0)
    c.setFillColor(TEAL); c.rect(LEFT,HEIGHT-85,54,5,fill=1,stroke=0)
    c.setFont('Bold',11); c.setFillColor(colors.HexColor('#A8D5D4'))
    c.drawString(LEFT,HEIGHT-117,'TK-LPLUT-2.0  /  CONSOLIDATED FORMAL EDITION')
    c.setFillColor(colors.white); c.setFont('Bold',36)
    c.drawString(LEFT,HEIGHT-184,'The Infallible Contract')
    c.setFont('Body',21)
    c.drawString(LEFT,HEIGHT-224,'Ontological Deterministic Computing')
    c.setFont('Body',13); c.setFillColor(colors.HexColor('#CADBE2'))
    c.drawString(LEFT,HEIGHT-260,'Self-Referential Log-Encoded Polar LUT Paradigm')
    # Relational diagram: a closed dependency path, not a physical geometry.
    points=[(88,399),(229,460),(406,406),(405,289),(226,248),(87,300)]
    c.setStrokeColor(colors.HexColor('#47747E')); c.setLineWidth(1.5)
    for i in range(len(points)):
        x,y=points[i]; xx,yy=points[(i+1)%len(points)]; c.line(x,y,xx,yy)
    labels=['State','Relative lookup','Operator','Transport','Invariant','Retained history']
    for (x,y),label in zip(points,labels):
        c.setFillColor(TEAL); c.circle(x,y,7,fill=1,stroke=0)
        c.setFillColor(colors.HexColor('#DCEAED')); c.setFont('Body',11)
        c.drawCentredString(x,y-24,label)
    c.setFont('Bold',14); c.setFillColor(colors.white)
    c.drawCentredString(245,359,'ONE INDIVIDUAL')
    c.setFont('Body',10); c.drawCentredString(245,340,'one admitted state history')
    c.setStrokeColor(colors.HexColor('#47747E')); c.line(LEFT,180,WIDTH-RIGHT,180)
    c.setFillColor(colors.white); c.setFont('Bold',14); c.drawString(LEFT,151,'Tom Klootwijk')
    c.setFont('Body',10); c.setFillColor(colors.HexColor('#CADBE2'))
    c.drawString(LEFT,131,'NL200678942  |  10-07-1990')
    c.drawString(LEFT,105,'25 September 2026  |  Formalization with measured implementation progress')
    c.setFont('Body',9); c.drawString(LEFT,71,'Original specification + Solus + Infallible addendum + current code evidence')
    c.bookmarkPage('cover'); c.addOutlineEntry('The Infallible Contract','cover',0)
    c.showPage()


def render(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(output),pagesize=A4,invariant=1,pageCompression=1)
    c.setTitle('The Infallible Contract - Ontological Deterministic Computing - TK-LPLUT-2.0')
    c.setAuthor('Tom Klootwijk - paradigm author; consolidated formalization prepared with Codex')
    c.setSubject('Integrated formal specification and implementation evidence, 25 September 2026')
    count=len(PAGES)+1
    cover(c,count)
    layout=[]
    for number,(title,subtitle,items) in enumerate(PAGES,2):
        c.bookmarkPage(f'p{number}'); c.addOutlineEntry(title,f'p{number}',0)
        c.setFillColor(TEAL); c.setFont('Bold',8.5); c.drawString(LEFT,HEIGHT-42,'TK-LPLUT-2.0')
        c.setFillColor(MUTED); c.setFont('Body',8.2); c.drawRightString(WIDTH-RIGHT,HEIGHT-42,'TOM KLOOTWIJK  /  25 SEPTEMBER 2026')
        c.setStrokeColor(RULE); c.setLineWidth(.6); c.line(LEFT,HEIGHT-51,WIDTH-RIGHT,HEIGHT-51)
        title_style=ParagraphStyle('title',fontName='Bold',fontSize=22,leading=26,textColor=INK)
        title_p=Paragraph(title,title_style); tw,th=title_p.wrap(CONTENT_W,100)
        title_p.drawOn(c,LEFT,HEIGHT-72-th)
        y=HEIGHT-72-th-18
        c.setFont('Bold',8.2); c.setFillColor(TEAL); c.drawString(LEFT,y,subtitle)
        y-=25
        if title=='Contents':
            items=[]
            for pg,(t,s,_) in enumerate(PAGES,2):
                if t=='Contents': continue
                items.append((pg,t))
            for pg,t in items:
                c.setFont('Body',10); c.setFillColor(INK)
                c.drawString(LEFT,y,t); c.setFont('Bold',10); c.setFillColor(TEAL)
                c.drawRightString(WIDTH-RIGHT,y,str(pg))
                c.linkRect('',f'p{pg}',(LEFT,y-3,WIDTH-RIGHT,y+12),relative=0,thickness=0)
                y-=17.4
        else:
            for item in items:
                before=item.getSpaceBefore() if hasattr(item,'getSpaceBefore') else 0
                after=item.getSpaceAfter() if hasattr(item,'getSpaceAfter') else 0
                y-=before
                w,ht=item.wrap(CONTENT_W,max(y-60,1))
                if w>CONTENT_W+0.1: raise ValueError(f'Width overflow p{number}: {w}')
                if y-ht<59: raise ValueError(f'Page {number} overflow at {str(item)[:100]}: bottom={y-ht:.1f}')
                item.drawOn(c,LEFT,y-ht); y-=ht+after
                if isinstance(item,Table): y-=9
        layout.append({'page':number,'title':title,'content_bottom':round(y,2)})
        c.setStrokeColor(RULE); c.line(LEFT,48,WIDTH-RIGHT,48)
        c.setFont('Body',8); c.setFillColor(MUTED)
        c.drawString(LEFT,32,'FORMAL CONTRACT  /  EVIDENCE SCOPED TO DECLARED PROFILES')
        c.drawRightString(WIDTH-RIGHT,32,f'{number} / {count}')
        c.showPage()
    c.save()
    r=PdfReader(output)
    assert len(r.pages)==count
    qa_dir=ROOT/'tmp/pdfs'; qa_dir.mkdir(parents=True,exist_ok=True)
    (qa_dir/'formal-layout.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'pages':count,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                      'lowest_content_y':min(x['content_bottom'] for x in layout)},indent=2))


def verify_retained_inputs():
    expected_hashes = {
        'Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf':
            '8ea9cfb077630993e1d472ba72715a25d2402bf243518663f7d08b03f8b83647',
        'sources/solus-ion-ad-infinitum.pdf':
            'a2ace794138bcad68463d1ce2ba4a6e9954540bb4f2f29e4090d68d6e0440489',
        'sources/solipsism.pdf':
            '1091e0435aa1648b4ede127837e66ddbf2c5dbd0a67f49cbb7a7ae134ee547e7',
    }
    for relative, expected in expected_hashes.items():
        actual = hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'Source identity changed: {relative}')
    verification = json.loads((EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if verification['commit'] != '8f4b87bed131f5c084ef59aec558f3f9eb6ddedc':
        raise ValueError('This historical edition requires its named verification baseline')
    suite = next(item for item in verification['commands'] if item['name']=='full-tests')
    if (suite['test_count'],suite['skipped_count'],suite['exit_code']) != (262,0,0):
        raise ValueError('Retained verification disagrees with the edition')
    for filename in ('full-tests.txt','field-conformance.json','cross-adapter-trace.json',
                     'cross-adapter-probe-source.txt','readiness-matrix.json'):
        if not (EVIDENCE/filename).is_file():
            raise ValueError(f'Missing retained evidence: {filename}')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--font-dir',default='C:/Windows/Fonts')
    args=parser.parse_args()
    verify_retained_inputs()
    register_fonts(args.font_dir)
    build_content()
    render(args.output)
