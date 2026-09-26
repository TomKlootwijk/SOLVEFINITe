"""Build integrated TK-LPLUT-2.0 revision 12. Requires ReportLab and pypdf.

Run with the bundled PDF runtime, or install reportlab and pypdf. The default
output is the single tracked artifact under output/pdf/. No runtime is changed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
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
KLEIN_EVIDENCE = ROOT / 'docs/evidence/klein-field-v2'
FIELD_AGENT_EVIDENCE = ROOT / 'docs/evidence/field-agent-v1'
PSI_F8_EVIDENCE = ROOT / 'docs/evidence/psi-f8-v1'
HADAMARD_EVIDENCE = ROOT / 'docs/evidence/hadamard-v1'
GROWTH_EVIDENCE = ROOT / 'docs/evidence/growth-v1'
ORGANOGRAM_EVIDENCE = ROOT / 'docs/evidence/organogram-v1'
WELIP_EVIDENCE = ROOT / 'docs/evidence/welip-v1'
OG_CAPTURE_COMMIT = 'f125a76b75052c3611c39557779c08e4553e620a'
HP_VERIFICATION = None
GD_VERIFICATION = None
GD_CONFORMANCE = None
OG_REFERENCE = None
OG_VERIFICATION = None
OG_CONFORMANCE = None
W_REFERENCE = None
W_VERIFICATION = None
W_CONFORMANCE = None
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
    if any(value is None for value in (HP_VERIFICATION, GD_VERIFICATION, GD_CONFORMANCE,
                                       OG_REFERENCE, OG_VERIFICATION, OG_CONFORMANCE, W_REFERENCE,
                                       W_VERIFICATION, W_CONFORMANCE)):
        raise ValueError('Verify historical HP/GD/OG evidence and the W capture before revision 12')
    hp_tests = HP_VERIFICATION['tests']['passed']
    hp_device_tests = sum(HP_VERIFICATION['tests']['actual_device_methods'].values())
    hp_checks = HP_VERIFICATION['conformance_checks_passed']
    hp_allocation = HP_VERIFICATION['allocation_info']
    gd_tests = GD_VERIFICATION['tests']['passed']
    gd_device_tests = sum(GD_VERIFICATION['tests']['actual_device_methods'].values())
    gd_checks = GD_VERIFICATION['conformance_checks_passed']
    gd_default = GD_CONFORMANCE['GPU']['default']
    gd_two = GD_CONFORMANCE['GPU']['two_epoch']
    gd_deferred = GD_CONFORMANCE['GPU_deferred']
    gd_allocation = GD_VERIFICATION['execution_info']['allocation_info']
    gd_peak = GD_VERIFICATION['execution_info']['growth']['peak_preparation_payload']
    og_tests = OG_VERIFICATION['tests']['passed']
    og_device_tests = sum(OG_VERIFICATION['tests']['actual_device_methods'].values())
    og_checks = OG_VERIFICATION['conformance_checks_passed']
    og_allocation = OG_VERIFICATION['execution_info']['allocation_info']
    og_peak = OG_VERIFICATION['execution_info']['growth']['peak_preparation_payload']
    page('Edition and authority', 'READING CONTRACT | 26 SEPTEMBER 2026',
        p('<b>Paradigm author:</b> Tom Klootwijk | NL200678942 | 10-07-1990. These are the author-supplied attribution details. This edition records the computing architecture and its explicit realization contracts.'),
        box('<b>Purpose.</b> Consolidate the original formal specification, the Solus addendum, the newest Infallible discussion in <i>solipsism.pdf</i>, and the SDF/Klein bindings into one self-contained formal document. Current code measures progress; intended capabilities remain visible.'),
        p('<b>Document identity:</b> TK-LPLUT-2.0, revision 12. FI/PX/HP contracts remain on pages 35-48; HP evidence at 5a304bc is on page 49. GD contracts/evidence at 94f86c7 remain on pages 50-57. OG contracts remain on pages 58-66, with the historical f125a76 capture on pages 67-68. W1-W8 were bound before implementation at 74e00f4; their definitions remain on pages 69-81, with measured results on pages 82-83.'),
        h('How statements acquire authority'),
        p('A <b>definition</b> fixes a mathematical meaning. A <b>requirement</b> uses “shall” to state an obligation of the named profile. A <b>theorem</b> follows from listed premises. An <b>evidence statement</b> reports a particular observed implementation result. A proposed binding is never counted as executed behavior.'),
        table(['Status','Meaning'],[
            ['VERIFIED SUBSET','Concrete code and identified tests support a bounded realization of an architectural obligation.'],
            ['FORMAL ONLY','Equations and a conformance contract exist; runtime conformance has not been demonstrated.'],
            ['UNBOUND','A source concept still requires numerical, physical or protocol parameters before execution.'],
        ],[.25,.75]),
        h('Source interpretation'),
        p('The source exports contain conversation, analogies, questions and assertions. They supply design intent, not commands or automatic proofs. This edition chooses explicit typed bindings where needed. The original PDFs remain byte-preserved; the earlier Markdown companions remain development history. Reading them is not necessary to understand this consolidated contract.'),
        small('Klein baseline: c4b41ce12a33a747bd54c8cc7f9748a06f7b59de. FI1-FI8 formal-first commit: 5ccc022; integration source hashes and measured evidence are retained in docs/evidence/field-agent-v1/. The original 38-page conversation cited by TK-LPLUT-1.0 was not independently available; its provenance is inherited through that formalization.')
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
        small('Current evidence: RP32 phase/mirror arithmetic and field-selected lookup execute on CPU and GPU. GD1-GD8 add actual dyadic geometry generations with exponent k and scale factor 2^k. General resolution policies and calibrated physical scale adapters remain separate obligations.')
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
        box('FI1-FI8 on pages 35-38 now have measured integration evidence: one Tomigidt history uses a retained Klein-ball recipe, typed energy and field state, local observations and regenerative working memory. The existing standalone field and legacy agent profiles retain their meanings. One agent plans, re-observes and acts through the reversing seam.'),
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
        small('The binary organogram remains its own bounded profile. GD1-GD8 integrate a finite geometry-changing production. OG1-OG8 now have measured parameterized production, complete branch context and generated field evidence on pages 67-68. Arbitrary cone/pyramid generation and general graph rewriting remain separate obligations.')
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
        small('Current status: typed arithmetic, SDF bounds, local PX eigenstructure and f8 indexing have CPU/GPU checks. HP1-HP8 now have measured phase-directed Hadamard routing evidence on page 49. Global eigenmode traversal remains separate; no route-quality claim follows from index conformance.')
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
            ['W: WElip','Admit IGNITE, ADVANCE, RESIZE, INVALIDATE and EMIT; expose no historical-read operation at this interface. W1-W8 from page 69 bind this finite profile; measured continuation is on pages 82-83.'],
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
        small('Implemented: binary-world and FI5 geometric-sample FIFOs, retained-context regeneration and capacity-independent decisions. Field-agent evidence includes actual eviction/reconstruction and changing capacities. Scalar fields, geometry, journals and GPU arenas remain separately accounted outside the active sample bound.')
    )
    page('Finite Klein quotient', 'VERIFIED FINITE PROFILE | K1-K3',
        p('Choose strict integers W,H at least 3 with W*H at most 256. Temporary chart labels represent a quotient; they do not introduce a mandatory external physical origin.'),
        eq('(u,v+H) ~ (u,v);        (u+W,v) ~ (u,-v)\nq=floor(u/W); u0=u-q*W; v0=((-1)^q*v) mod H\neta0=eta XOR (q mod 2); node=u0*H+v0'),
        p('Negative labels use floor division, not truncation. Phase transported into the canonical frame is multiplied by (-1)^q. Node names are k:u0:v0 in index order. Project each unit horizontal/vertical edge, retain each sorted distinct endpoint pair once and assign unit weight. The relative seam bit tau is one on horizontal wraps between columns W-1 and 0, zero elsewhere.'),
        eq('face(u,v) = [canon(u,v), canon(u+1,v),\n             canon(u+1,v+1), canon(u,v+1)]\nV=WH, E=2WH, F=WH; Euler characteristic=0'),
        h('The surface claim requires cells'),
        p('The audit shall check four distinct corners per face; correspondence between face boundaries and declared edges; graph connectivity; exactly two incident faces per edge; and a single cyclic vertex link at every vertex. These conditions establish a closed connected 2-manifold. Counts alone do not establish a surface.'),
        eq('x_g = -d_f*d_g*x_f'),
        p('Here x_f is a face orientation choice and d_f is its traversal sign along a canonically oriented shared edge. Propagate the constraint through the dual graph. A contradiction establishes nonorientability. A connected closed nonorientable surface of Euler characteristic zero is a Klein bottle [R4].'),
        box('At c4b41ce, KleinDomain constructs and audits this cell complex. Evidence covers all 702 admissible width/height pairs, including edge incidence, cyclic vertex links and nonorientability. Independent tests reject malformed and pinched complexes. The surface claim rests on these cells and audits, not arithmetic mirror pairs alone.')
    )
    page('Orientation cover and seam action', 'VERIFIED FINITE PROFILE | K4, K7-K9',
        eq('Cover vertices: (i,eta), encoded as 2*i+eta\n(i,eta) -- (j,eta XOR tau(i,j))\n(U,V) = (u+eta*W, (-1)^eta*v mod H)'),
        p('Lift every base edge twice and each face boundary from both starting orientations. The XOR of seam bits around a face shall be zero. The cover must be connected, closed and orientable, with counts 2WH,4WH,2WH and cyclic vertex links. The displayed map identifies it with a periodic 2W by H toroidal grid; audit the full mapped edge and face sets, not only their counts.'),
        p('A horizontal loop at v=0 returns to its base node after W steps with orientation reversed; its lift closes after 2W steps. A vertical H-step loop preserves orientation. These are explicit holonomy witnesses. The two sheets are local-frame representations of the same individual.'),
        h('Packed transport'),
        eq('Operator metadata: STEP | (tau<<6)\nt = (r + (-1)^eta*delta) mod 256\nr_next = (-1)^tau*t mod 256\neta_next = eta XOR tau'),
        p('Operator bit 6 stores relative seam action; operator bit 4 stays zero. Live metadata contains only STEP and orientation in bit 4. Bit 6 never leaks into live state. Set G to the destination and B to its certified scalar field, then recompute parity and the full mirror. Toggling orientation without reflecting phase is not this transport convention.'),
        h('Theorem K1: mirror coherence'),
        p('Let S_tau(r,eta)=((-1)^tau*r,eta XOR tau). A tick is S_tau composed with U_delta; M=S_1. The phase theorem establishes U_delta commutes with M, and both seam maps commute. Mirrored states share G and scalar B and therefore select the same operator. Their complete tick results remain mirrors.'),
        small('The proof establishes this numerical binding, conditional on correct geometry/operators. The implemented GPU compiler derives tau from the authoritative seam set and applies K8 inside its ordered tick loop; hardware traces agree with CPU execution. A generic graph with seams is not automatically a Klein surface. Orientation-cover background: Hatcher [R5].')
    )
    page('Intrinsic ball and v2 profile', 'VERIFIED FINITE PROFILE | K5-K6',
        p('The implemented manifest format is <font name="Mono">relational-sdf-v2</font>. It requires every v1 key plus <font name="Mono">seams</font> and <font name="Mono">topology</font>. Its archive container remains <font name="Mono">relational-sdf-machine-v1</font>; the manifest selects execution semantics.'),
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
        p('The default generator uses W=H=8, centre 0, radius 2, initial node 0, phase 250 and orientation 0. All field-class routes take local u+; increments are [11,53,137]. The measured 64-tick CPU/GPU trace crosses eight reversing seams and ends at k:0:0 with pair 11FE00D681FE002A.'),
        small('Klein evidence includes negative/large labels, all 702 supported dimensions, face/link audits, connected orientable covers, full torus edge/face maps, holonomy, exact scalar pullback, CPU/GPU seam traces, replay and unchanged v1 semantics. Its 311-test baseline is preserved alongside the current 421-test result on page 27.')
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
        p('The addendum’s internally generated growth can be formalized as a versioned graph-rewrite event. Such an event shall supply a finite rule, affected domain, retained derivation context and deterministic node correspondence. Its result must pass connectivity, boundary, range, topology and operator checks before admission. GD1-GD8 now realize one finite dyadic geometry production under this contract; arbitrary rewriting remains separate.'),
        p('The source’s “zero-order decay” or Lambda label requires a deterministic invalidation function Lambda_nu(S,e), including selected entries, predicate, retention effects and result. W1-W8 bind finite active-pair invalidation on page 71, with measured recovery on pages 82-83. Biological reaction-diffusion analogies require actual equations before they become physical models.'),
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
    page('Implementation map and integration', 'MEASURED PROFILES | FI, PX, HP, GD AND OG',
        p('The field-agent policy joins recipe-derived Klein geometry to the existing individual. The module map identifies implemented scope; remaining architectural concepts retain their separate obligations.'),
        table(['Layer','Existing implementation','Scope'],[
            ['Packed core','rp32.py','Encoding, phase, parity, full mirror and pair.'],
            ['Derived world','world.py; runtime.py','Binary derivation, bounded active FIFO, replay and demo archives.'],
            ['Individual','motion.py; navigation.py; tomigidt.py','Costs, incremental deterministic planning, local observations and action state.'],
            ['Persistence / live','session.py; live.py','Ownership, atomic saves, admitted external frames, deduplication and durable acknowledgment.'],
            ['Packed GPU','gpu.py; packed.wgsl','World derivation and selected motion forecasts; CPU retains planning and admission.'],
            ['Intrinsic field','field.py; field_cli.py','Strict geometry/manifest, exact field, operators, one persistent sequence and replay.'],
            ['Field GPU','sdf_gpu.py; field.wgsl','Device field construction, operator texture and ordered state transitions.'],
            ['Klein quotient','klein.py','Audited cells, connected orientation cover, intrinsic ball and v2 seam transport.'],
            ['Field / index','field_agent.py; field_world.py; field_agent_gpu.py; psi.py; f8.py','Typed field agent, sample FIFO, local eigen-axis, canonical tree and persistent device actions; field_agent.wgsl.'],
        ],[.22,.34,.44]),
        h('Profile meanings remain explicit'),
        p('Earlier motion/world profiles use B for terrain or energy; relational-sdf-v1/v2 use B for exact signed distance. FI1-FI8 preserve these schemas and implement a field-agent policy with B=phi and separate integer energy. Shared encoding never permits an implicit role change.'),
        h('Measured integration'),
        p('Tomigidt observes, plans and acts through Klein seams. hadamard.py adds phase-state routing; growth.py supplies dyadic geometry growth. organogram.py, organogram_gpu.py and organogram.wgsl now produce a branching grammar field and continue the same individual. Global Psi, general primitives and physical adapters remain separate.'),
        small('Paths are relative to solvefinite/. Historical source hashes: GD at 94f86c7 in docs/evidence/growth-v1/; OG at f125a76 in docs/evidence/organogram-v1/. Earlier FI/Klein/PX/HP captures remain. OG chronology and measurements are on pages 67-68.')
    )
    page('Retained PX verification and field trace', 'HISTORICAL CAPTURE | 25 SEPTEMBER 2026',
        table(['Measurement','Observed result'],[
            ['Full integrated suite','421 tests passed in 44.997 s; zero skipped.'],
            ['Actual device coverage','55 GPU methods: the prior 41 plus 14 F8 methods.'],
            ['Klein topology coverage','All 702 admissible dimension pairs audited, including base/cover surfaces and full torus edge/face maps.'],
            ['Conformance examples','Klein: 22 checks; field agent: 23; Psi/index: all 20 passed. PX audits 106,045 descriptors in all 702 domains; 830 GPU lookups/materializations in six domains.'],
            ['Hardware / software','NVIDIA GeForce RTX 5070 Ti Laptop GPU; Vulkan; driver 591.59; wgpu 0.32.0; Python 3.12.14.'],
            ['Cross-adapter continuation','CPU/GPU archives agree; fresh processes replay both ways before the seam and during DEFER. Live retries preserve history.'],
        ],[.32,.68]),
        eq('SDF v1: [-6,-4,-3,0,2,3,5]\nMoved boundary: [-8,-6,-5,-2,0,1,3]\nV1 tick 64: n4, pair 1102046C01020494\nKlein v2 tick 64: k:0:0, pair 11FE00D681FE002A'),
        p('Changing geometry changes field execution and agent route selection. The FI8 mission completes after four cycles at pair 06011145160111BB, energy 90. Its reversing seam yields phase 240 and eta 1. The bounded-search mission takes 41 cycles; six energy/recipe/valid-parity forecast tamper probes are rejected.'),
        h('Reproduce the measured checks'),
        code('python -m unittest discover -s tests -v\npython -m examples.psi_f8_conformance --output psi.json\npython -m examples.field_agent_conformance --output agent.json\npython -m examples.klein_conformance --output klein.json\npython -m examples.field_conformance --output sdf.json'),
        p('Retained captures: SDF 262 tests/21 device methods, Klein 311/28 and field agent 368/41. PX rebuilds preserve the complete FI8 archive and all 41 DEFER-mission cycles. These counts describe tested finite profiles, not architectural completion.'),
        small('Historical PX evidence: docs/evidence/psi-f8-v1/. Earlier captures remain in field-agent-v1/, klein-field-v2/ and formal-edition-2026-09-25/. The new HP capture is on page 49. Logs, source hashes, adapter details and archives identify each observation.')
    )
    page('Progress against the architecture: I', 'CAPABILITY STATUS | FINITE REALIZATIONS',
        table(['Obligation','Measured status and remaining work'],[
            ['C1-C3: relational packed execution','<b>Verified subset.</b> RP32, state-selected integer texture execution and GD dyadic geometry scale transitions work. General resolution policies and alternate historical carriers remain unbound.'],
            ['Exact intrinsic SDF','<b>Verified subset.</b> Weighted graph distance, declared separating boundary, units, certificate and field-governed traces work. Continuous primitives and physical calibration are separate.'],
            ['C4: Klein geometry','<b>Verified finite profile.</b> Quotient cells, nonorientability, connected orientable cover, torus maps, intrinsic ball and CPU/GPU seam transport are audited.'],
            ['Local Psi / traversal','<b>Verified local roles.</b> Exact SDF eigen-operator, primitive axis and chart transport govern indexing and HP directional gains. Global eigenmode traversal remains separate.'],
            ['Hadamard / Delta-Delta','<b>Verified finite routing profile.</b> HP1-HP8 implement phase-dependent directional costs, planning and device actions. Existing second-difference bounds remain checked.'],
            ['f8 middle-out index','<b>Verified finite binding.</b> Canonical five-component keys, lower-median preorder, actual CPU/GPU lookup and atomic versioned rebuild work for scalar base descriptors.'],
        ],[.3,.7]),
        h('What the tests establish'),
        p('The implemented graph profile has exact arithmetic and a field certificate, and its tested CPU/GPU realizations agree. These are substantial completed components. They do not establish every named architectural layer by association with the same word carrier.'),
        h('What will count as progress next'),
        p('FI, PX and HP provide field-guided planning, indexed lookup and phase-directed routing. GD1-GD8 add finite dyadic growth and continued action. OG1-OG8 now execute parameterized productions and branch context on CPU/GPU. Global Psi, general primitives, physical adapters and wider continuation remain separate obligations.'),
        small('The requirements matrix continues on page 29. No percentage is assigned because architectural obligations differ in size and some remain unbound; counting passing tests would produce a misleading completion estimate.')
    )
    page('Progress against the architecture: II', 'CAPABILITY STATUS | INTEGRATION AND APPLICATIONS',
        table(['Obligation','Measured status and remaining work'],[
            ['C5: generative world','<b>Verified finite GD and OG.</b> Dyadic Klein generations and parameterized branching productions change geometry or field and continue the same individual. Complete branch context and original-time replay are tested. General primitives remain separate.'],
            ['C6: finite active memory','<b>Verified subset.</b> Pair-atomic sample FIFO, genuine reconstruction and capacity-independent agent histories work. Journals, geometry, fields and device arenas consume additional memory.'],
            ['C7: complete mirror','<b>Verified subset.</b> Phase involution/commutation, parity and full pair relations work, including K8 phase reflection and orientation transport on CPU/GPU.'],
            ['C8: individual and footprint','<b>Verified subset.</b> Planning, observations, epoch/sequence, retry handling, ownership and durable continuation work. W adds a typed LUS envelope; broader DIGID semantics and global admission/authentication remain open.'],
            ['WElip / Lambda','<b>Verified finite W profile.</b> W1-W8 bind a forward interface, local invalidation, finite epoch clock, current-state emission and private recovery. Source-bound CPU/GPU evidence is on pages 82-83. Broader Lambda semantics remain outside this binding.'],
            ['GPU / performance','<b>Verified subset.</b> Exact tested adapters and device execution exist. Cache saturation, general speed/energy superiority and other hardware adapters are unmeasured.'],
            ['Waves / physical growth','<b>Unbound applications.</b> Signal models, physical transfer functions and calibrated action semantics are not supplied by the present code.'],
        ],[.3,.7]),
        h('Continuation after the integrated field agent'),
        p('FI joins geometry to the individual; PX adds an interchangeable index; HP makes phase and local eigenstructure affect actions. GD extends history across geometry generations. OG now produces exact new union-boundary fields from branching grammars and continues that history. Global traversal, general primitives and wider continuation need further work.'),
        small('The measured integration is finite and profile-scoped. Whole-system indefinite continuation, autonomous physical self-replication, consciousness and universal immunity are not demonstrated outcomes of the present profiles.')
    )
    page('Conformance and performance scope', 'ACCEPTANCE CRITERIA | ORIGINAL T1-T10',
        table(['ID','Criterion and present scope'],[
            ['T1-T4','Exact encode/decode, modular phase, mirror involution/commutation and odd-bit parity detection: exercised for RP32.'],
            ['T5','Canonical topology and transported field meaning: finite Klein K1-K9 are implemented and independently audited.'],
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
        small('Historical records: docs/benchmarks/rtx5070ti-depth16.json and rtx5070ti-depth18.json. PX conformance took 21.673 s as a correctness capture, not a comparative benchmark. Default explicit device payload is 49,160 bytes, peaking at 51,528 during rebuild; retained host index payload is 1,296 bytes, peaking at 2,592. These exclude Python/driver overhead; fields, geometry and journals remain outside the FIFO.')
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
        p('Original R1-R16 are preserved above. Implemented extensions use <b>SDF.R1-R12</b> on pages 13-17 and 31, <b>K1-K9</b> on pages 19-21, <b>FI1-FI8</b> on pages 35-38, <b>PX1-PX8</b> on pages 39-43, <b>HP1-HP8</b> on pages 44-48, <b>GD1-GD8</b> on pages 50-56 and <b>OG1-OG8</b> on pages 58-66. <b>W1-W8</b> begin on page 69, with measured evidence on pages 82-83. Satisfying one profile does not silently complete another.'),
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
        code('Klein: c4b41ce12a33a747bd54c8cc7f9748a06f7b59de\nCapture: 2026-09-25, 11:30:28 UTC\nPrior: 8f4b87bed131f5c084ef59aec558f3f9eb6ddedc\nPrior capture: 07:52:57 to 07:54:16 UTC'),
        small('Chronology: SDF specification 477e576 preceded implementation 50c9389; Klein specification 8f4b87b preceded c4b41ce. FI1-FI8 formal commit 5ccc022 preceded integration c8af71d. PX1-PX8 formal commit d8de349 preceded its runtime. Current source hashes: docs/evidence/psi-f8-v1/verification.json. Earlier captures and original source bytes remain preserved.')
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
        box(f"<b>Revision 12 status.</b> Historical HP retains {hp_tests} tests/{hp_checks} checks; GD retains {gd_tests}/{gd_checks}; OG at f125a76 retains {og_tests}/{og_checks}. W captures {W_VERIFICATION['tests']['passed']} tests, {sum(W_VERIFICATION['tests']['actual_device_methods'].values())} actual-device methods and {W_VERIFICATION['conformance_checks_passed']} checks. Distinct finite captures do not establish whole-architecture completion.")
    )
    page('One field-guided Tomigidt', 'VERIFIED FINITE PROFILE | FI1-FI2 | FORMAL-FIRST CONTRACT',
        h('FI1. Identity, schema and typed state'),
        p('FieldAgentManifest shall select policy <font name="Mono">tomigidt-field-observe-plan-act-v1</font>, word_profile <font name="Mono">RP32-relational-sdf-v2</font> and perspective <font name="Mono">local-observation-v1</font>. One existing Tomigidt owns the goal, local observations, retained search, live state and event history. There is no separately advancing FieldMachine or second individual.'),
        p('The exact manifest keys shall be those below. Unknown/missing keys, Boolean integers and invalid shapes shall be rejected. JSON arrays become immutable tuples. Target and initial_node are canonical names; initial_node defaults to k:0:0. The .start property supplies that same name. No graph, routes, field array or sensor-supplied phi belongs in this schema.'),
        code('identity, target, world, initial_node, initial_phase,\ninitial_orientation, initial_energy, repair_cost,\nmax_search_expansions, max_hops, max_cycles,\npolicy, word_profile, perspective'),
        eq('Live state = (Pair(pack(r,i,phi(i),STEP | (eta<<4))), E)\n0 <= E <= 2^31-1;  E is separate from the B lane'),
        p('Phase is 0..255 and orientation is 0 or 1; defaults are 250 and 0. Initial energy defaults to 100. Repair cost is 1..127; cycles are 1..1,000,000; search quantum is 1..65,536 expansions per cycle. Identity is a nonempty name of at most 128 characters. All numerical bounds use strict integers. Completion uses EMIT instead of STEP while retaining orientation.'),
        h('FI2. Retained geometric recipe'),
        p('World recipe format is <font name="Mono">klein-ball-world-v1</font> (Python attribute version). Its exact JSON keys are <font name="Mono">format,width,height,center,radius,turns,baseline_id</font>. Baseline ID is a nonempty string. Defaults are W=4, H=5, centre index 0, radius 2 and turns [11,53,137]. Width/height obey K1; centre is in 0..WH-1; radius obeys K5; turns are three unsigned eight-bit integers.'),
        p('The retained recipe regenerates canonical k:u:v nodes, every unit quotient edge, seams, cells and exact certified SDF. It replaces an expanded graph/field in the manifest. K1-K5 and the scalar mirror rule remain binding. Geometry is immutable within one manifest; original external observations remain separate retained inputs.'),
        small('This policy is a new typed application binding. Legacy AgentManifest policies, terrain/energy words, FieldMachine schemas, archives and fixture bytes retain their previous meanings. The shared session/live envelopes select this policy from their contained manifest.')
    )
    page('Observe, plan and transport', 'VERIFIED FINITE PROFILE | FI3-FI4 | ONE ACTION SEQUENCE',
        h('FI3. Local observations and retained planning'),
        p('Sensors supply only strict hazards in 0..127 for the current node and its outgoing quotient neighbors. DATA observation packets retain B=hazard under their explicit observation context; they are not SDF samples. No input may supply a route, action or phi. Before MOVE or REPAIR, require a fresh complete local frame. Partial frames produce WAIT; unseen distant nodes use the existing zero-hazard hypothesis.'),
        p('Generate the graph from all quotient edges. Use global lexical ordering of canonical names and lexical route ties. RouteSearch gains explicit relational mode with a strict hop bound in 1..255, default 255; legacy binary mode retains its 32-hop bound. Per-cycle search quanta retain unfinished work through DEFER. Search context includes position, current pair, separate energy and effective costs; a changed context invalidates stale work before an action can be admitted.'),
        eq('c(i,j,h_j) = 1 + abs(phi(j)) + h_j\nroute_cost = sum c over its entered nodes\nMOVE requires route_cost + repair_cost <= E'),
        p('This cost is a declared application rule in integer codes, not physical energy calibration. The field shall affect actual route selection. Forecast the internally selected route without mutating canonical live state. Empty forecasts are allowed but shall still validate the seed. Real moves must follow adjacent distinct nodes; target handling uses REPAIR, not a stationary movement.'),
        h('FI4. Exact packed action and target repair'),
        p('For admitted i to j, source phi selects the negative/zero/positive increment from recipe turns. Derive tau from the authoritative edge seam set. Apply the increment in the departure frame, then K8 reflection and orientation transport. Require exact destination phi, recomputed parity and a complete mirror.'),
        eq('delta = turns[class(phi(i))]; tau = seam(i,j)\nt = (r + (-1)^eta * delta) mod 256\nr_next = (-1)^tau * t mod 256; eta_next = eta XOR tau\nW_next = pack(r_next,j,phi(j),STEP | (eta_next<<4))\nE_next = E - c(i,j,h_j)'),
        p('At the freshly observed target, require E at least repair_cost. REPAIR preserves R, G, B and eta, changes the opcode to EMIT, subtracts repair_cost from separate energy and marks COMPLETE. A negative or zero field never means negative or zero energy. Decisions, forecasts, live pairs and energy shall be checked as one admitted history.'),
        small('Planner-selected destinations are this policy’s own internal decisions. FI4 does not replace or reinterpret the fixed per-class routes of standalone FieldMachine. Existing observation admission, event ordering and finite-cycle outcomes remain in force.')
    )
    page('Regeneration and device admission', 'VERIFIED FINITE PROFILE | FI5-FI6 | RESIDENCY AND HISTORY',
        h('FI5. Recipe-derived samples and bounded FIFO'),
        eq('sample(i) = Pair(pack(0,i,phi(i),DATA))\nRegen(recipe,i) = the same certified sample(i)'),
        p('The geometric world shall supply pure derive and caching get. Derive changes no cache order, counters, observations or live state. On CPU it recomputes from the retained recipe; on GPU it re-materializes the sample from the certified field buffer. Get stores atomic complete pairs in a capacity-C FIFO, C a positive strict integer. Hits do not refresh insertion order; overflow and shrinking evict oldest insertions. A later miss for an evicted node must actually reconstruct the sample.'),
        p('Cold restart rebuilds geometry, exact fields and required operators from the recipe. Regeneration retains baseline/version and original dependencies; it never substitutes a later context. Hazards and other admitted measurements must survive in the observation journal. They cannot be reconstructed from the geometric recipe. Missing original dependencies shall fail admission, not silently synthesize measurements.'),
        eq('active sample payload <= 8*C bytes\nM_total = M_FIFO + M_recipe + M_fields + M_operators\n          + M_geometry + M_observations + M_journal\n          + M_search + M_runtime'),
        p('The full scalar field tuple and GPU scalar/operator arenas are accounted outside the FIFO; the bound does not describe total memory. Python objects also have overhead. Cache capacity and incidental eviction affect residency only and stay outside canonical state. Forecasting must not admit unobserved measurements or populate the observed active sample cache.'),
        h('FI6. GPU execution with one persistent owner'),
        p('The device shall construct the field; an independent geometric certificate shall admit it before device operators are used. Compile every allowed neighbor/class operator from certified fields and authoritative seams: four distinct neighbors times three classes, a 12 by N Klein arena. Operators carry delta, destination, destination phi and relative seam bit; live metadata shall never inherit operator bit 6.'),
        p('Forecast a caller-internal planned route of at most 255 edges in scratch device state without changing the live owner. Accepted MOVE and REPAIR shall dispatch from persistent GPU pair and energy, not upload a host-computed forecast as the action. Compare the device result with the admitted prediction before committing the journal. An uncertain device outcome or prediction mismatch fails closed; reconstruct from the last durable admitted history before further work.'),
        small('CPU/GPU fields, costs, forecasts, decisions and canonical archives shall agree exactly. Explicit GPU execution shall not fall back to CPU field or transition evaluation. Adapter names, timings and cache diagnostics remain outside canonical state; host planning and admission remain explicit host stages.')
    )
    page('Integrated replay and acceptance', 'VERIFIED FINITE PROFILE | FI7-FI8 | CONFORMANCE',
        h('FI7. One journal, durable admission and replay'),
        p('Reuse Tomigidt’s session/live envelopes, process locks, atomic saves and durable acknowledgment. Field-policy event keys shall be exactly <font name="Mono">seq,input,decision,output,energy</font>; energy is a strict integer. Snapshots include energy and word_profile; retained planning summaries include energy in their context. Legacy events retain their exact four-key schema.'),
        p('Replay regenerates geometry and re-admits original observations in order, recomputing each (pair,energy) state rather than installing stored energy. Check every complete event, forecast and expected state, including WAIT/DEFER and search progress. Reject supplied replacement recipes for retained sessions and all replay-inconsistent records. Backend/capacity changes shall preserve canonical archives. Invalid frames shall not mutate live state, energy, search, observations or cache; legacy fixtures remain exact.'),
        h('FI8. Reference mission and independent checks'),
        p('Use the 4 by 5 default recipe, start k:0:0, target k:3:2, phase 250, eta 0, energy 100 and repair cost 5. Hazards are zero until hazard 70 at k:0:3 takes effect from cycle 2, and only visible hazards are reported. Initial lexical least-cost route is [4,3,17], cost 5. After entering node 4, the new local observation selects [16,17], cost 3. Edge 4 to 16 is a reversing seam.'),
        table(['Admitted action','Node / phase / phi / eta','Separate energy'],[
            ['MOVE 1','4 / 5 / -1 / 0','98'],
            ['MOVE 2, seam','16 / 240 / 0 / 1','97'],
            ['MOVE 3','17 / 187 / +1 / 1','95'],
            ['REPAIR, EMIT','17 / 187 / +1 / 1','90'],
        ],[.3,.46,.24]),
        p('With zero hazards and only the centre changed to index 4, the first planned route becomes [15,16,17], cost 4. This ablation proves field geometry changes planning, rather than decorating an unrelated route. Both CPU and GPU now reproduce these formal-first reference vectors and complete canonical archives.'),
        small('<b>Required checks.</b> Strict recipe/manifest and typed lanes; preserved legacy formats; independently calculated costs and packed words; field ablation, hazard replanning, seam reflection and mirrors; FIFO hit order, real eviction/reconstruction and recipe-only cold rebuild; capacity-independent histories; stale-search invalidation; fresh-process and both-backend replay; device action ownership, no fallback and fail-closed errors. Energy tampering shall fail complete-event replay.'),
        small('The retained FI integration capture has 23 passing checks and 368 tests, including 41 actual-device methods. Its exact mission archive is preserved under PX indexing. Neither binding establishes global Psi traversal, growth, infinite memory, calibrated physical energy or whole-architecture completion.')
    )
    page('Local SDF-derived Psi binding', 'VERIFIED FINITE PROFILE | PX1-PX2 | FORMAL-FIRST CONTRACT',
        h('PX1. A declared local eigen-operator'),
        p('This profile makes a new explicit numerical choice for the eigenvector/traversal and f8 roles in the original source (original pages 7 and 11; consolidated page 11). It is not asserted to be the unique formula implied by that source. Its operational role is indexing recipe-derived scalar base descriptors. Hadamard routing, a global Psi operator and behavior-changing traversal remain separate bindings.'),
        p('Use the immutable Klein recipe, canonical node i=uH+v and certified unit-edge scalar field phi. Directions u+, u-, v+, v- are the K1 quotient directions in the canonical chart. Define the unscaled symmetric difference g and its positive-semidefinite local operator exactly:'),
        eq('g_u = phi(u+) - phi(u-); g_v = phi(v+) - phi(v-)\ng = (g_u,g_v); A = g g^T\ng != 0: lambda = g_u^2 + g_v^2\n         P = g / gcd(abs(g_u),abs(g_v))\ng == 0: A = 0; lambda = 0; P = (1,0)\nPsi = epsilon * P; epsilon in {-1,+1}'),
        p('For nonzero g, lambda is the unique largest eigenvalue, and A*P=lambda*P. Integer gcd normalization and the declared sign select a nonzero primitive axis. For g=0, all vectors lie in the zero eigenspace; the explicit P=(1,0) tie rule chooses the axis. The fallback is a declared convention, not a recovered physical direction.'),
        h('PX2. Bounds and chart transport'),
        p('The certified unit-edge SDF has adjacent differences at most one. Thus both components of g lie in [-2,2]. Gcd-normalized P and either Psi sign also lie in [-2,2]; lambda belongs to {0,1,2,4,5,8}. Use exact widened integer arithmetic; no floating-point eigensolver, tolerance or rounded normalization participates.'),
        eq('J = diag(1,-1)\ng_prime = J*g; A_prime = J*A*J\nPsi_prime = J*Psi'),
        p('These transformations bind an orientation-reversing Klein chart. Transport the chosen axis, including the declared degenerate choice, through J. Keys shall be derived only in the canonical frame. A temporary label or opposite local frame changes displayed components, not the indexed scalar identity.'),
        small('Measured PX checks cover all 25 gradients, both signs and both local frames. The local axes, key records, full trees and actual GPU lookup results agree with independent cover/BFS oracles. The binding remains a declared finite indexing choice, not a global physical eigenmode.')
    )
    page('Canonical index identity and key', 'VERIFIED FINITE PROFILE | PX3-PX4 | SCALAR BASE DESCRIPTORS',
        h('PX3. Immutable binding and derivation identity'),
        p('IndexBinding has exactly the JSON keys below. Reject missing/unknown keys, Boolean integers and invalid values. Format is f8-klein-sdf-v1; epoch is a strict integer in 0..2^31-1, psi_sign is exactly -1 or +1, and phase_origin is in 0..255. Defaults are epoch 0, sign +1 and origin 0.'),
        code('format, epoch, psi_sign, phase_origin'),
        p('Full version identity is the complete Klein recipe content together with this binding, including baseline ID, geometry, centre/radius and turns. Epoch is scoped to that lineage; it is not a globally unique identity. Index all N recipe-derived scalar base descriptors, independently of FIFO residency. Oriented live agent states are not additional entries.'),
        eq('canonical derivation address i = u*H + v\nd(i) = unweighted quotient distance from recipe.center\nparent(root) = root\nparent(i) = min numeric j among neighbors with d(j)=d(i)-1'),
        p('The parent rule selects one finite root path. Numeric node order here differs from FI3 lexical name/route order. G remains the stable canonical node identity throughout; it is never replaced by a tree row. Alias queries reduce signed temporary Klein coordinates to their one canonical scalar identity. Strict k:u:v parsing in existing manifests remains unchanged.'),
        h('PX4. Radius, phase and the total key'),
        p('Define rho by integer bit length. It buckets graph radius plus one, and does not implement an active physical log-scale transition. Begin the root derivation with phase_origin and eta=0. Advance the K8 increment/reflection rule along the unique parent path, using each departure node’s field class to select its recipe turn.'),
        eq('rho(i) = floor(log2(d(i)+1)) = bit_length(d(i)+1)-1\ntheta(i) = (-1)^eta * r mod 256\n         = (phase_origin + sum departure turns) mod 256\nkey(i) = (Psi_u+2, Psi_v+2, rho, theta, i)'),
        p('Each key has five unsigned 32-bit components. Compare them lexicographically by numeric component, never by string representation or a hash. The final canonical node ID guarantees uniqueness even when earlier components tie. A different sign or phase origin may reorder storage while preserving every geometric node and movement edge.'),
        small('The phase derivation above is recipe/index metadata. It does not install a new phase in Tomigidt, append a movement, consume energy or supply a route to the planner.')
    )
    page('Middle-out tree and executable lookup', 'VERIFIED FINITE PROFILE | PX5-PX6 | ACTUAL DEVICE LOOKUP',
        h('PX5. Exact lower-median tree'),
        p('Sort all canonical node keys. For each half-open sorted interval [lo,hi), choose its lower median; emit that node, then its left and right subtrees recursively. Physical tree rows are this preorder. The resulting row layout is canonical for the complete recipe and binding.'),
        eq('mid = floor((lo + hi - 1)/2)\nleft interval [lo,mid); right interval [mid+1,hi)\ntree row = [key0,key1,key2,key3,key4,leftrow,rightrow,0]\nnode-key record = [key0,key1,key2,key3,key4,lambda,g_u+2,g_v+2]'),
        p('Both record types contain eight u32 values. N is 9..256; null child is 256 and the root is row 0. A valid search takes at most bit_length(N), at most nine, visited rows. Exact key equality returns the stored row and canonical node identity. A well-formed absent key returns MISS without any state change. Malformed rows, links, ordering, duplicate/missing identities or trees are invalid, not a successful miss.'),
        p('Tree edges are storage-search relations and shall never be interpreted as movement edges. The geometric graph, field, sensor neighborhood and canonical node identity remain authoritative. CPU world derive shall perform the actual tree walk before freshly regenerating a sample; a decorative tree or a direct node-to-row bypass does not satisfy this requirement.'),
        h('PX6. Certified construction and actual GPU dispatch'),
        p('The GPU shall construct keys, Psi values, numeric ranks and the complete tree from certified device fields and immutable geometry, including directional neighbors and parent/depth data. No host key compiler may substitute for explicit GPU construction. Node-key records and all rows shall exactly match independent CPU results.'),
        p('Compile the neighbor/class operator texture in tree preorder. The shader shall obtain a query key from the current state’s canonical G and walk the tree to the actual operator texture row. Validate the returned node identity before using its operator. This lookup must govern actual device actions as well as forecasts; G itself remains the canonical node ID.'),
        p('Admission certificates shall validate field-derived g, A/eigenvalue, gcd normalization, sign, parent-distance relation, K8 derivation phase and every key. They shall also validate the complete canonical lower-median/preorder tree and its node coverage. Parity or a locally plausible child link alone is insufficient.'),
        small('Existing FI6 persistent state, no-CPU-fallback, prediction comparison and fail-closed requirements remain binding. A corrupted row or wrong returned identity shall not silently select another node’s operator.'),
        small('Measured scope: nine bounds visited tree rows, not total lookup work. The current shader additionally validates rank in O(N) and checks the parent path. The conformance capture establishes exact results and actual tree use; it does not establish a speedup or a logarithmic total runtime.')
    )
    page('Atomic rebuild and semantic preservation', 'VERIFIED FINITE PROFILE | PX7 | VERSIONED STORAGE',
        h('PX7. Prepare, certify and swap one version'),
        p('A rebuild creates a new immutable IndexBinding with epoch incremented by exactly one; psi_sign and phase_origin may optionally change within their declared bounds. Reject epoch overflow at 2^31-1 before mutation. This is the versioned alternative allowed by original requirement R7, not an in-place ambiguous reordering.'),
        p('Prepare and validate the complete candidate keys, tree, operator texture and device bind-group bundle before a serialized atomic swap. Each lookup/action uses one complete admitted bundle. Retain enough ownership to distinguish a rejected candidate from an already committed replacement.'),
        table(['Outcome','Required effect'],[
            ['Invalid input or pure certificate failure','Reject with old index, canonical state, active FIFO/order/counters and retained search unchanged.'],
            ['Uncertain device outcome','Close the owner and retain unchanged admitted history; recover from that history before further work.'],
            ['Validated candidate, atomic swap','Commit the complete new bundle while preserving semantic history and working residency.'],
            ['Cleanup failure after the swap','Report a committed cleanup failure. Do not report rejection or pretend the old version remains active.'],
        ],[.32,.68]),
        h('Storage refinement, not a planning event'),
        p('Keys and tree order shall not determine planner iteration, costs, lexical ties or search quanta. Rebuilds preserve all agent pairs, separate energy, events, observations, DEFER frontier/cursor and active FIFO contents, order and counters. Residency does not change merely because its descriptor has a new tree row.'),
        p('Expose the complete binding and version identity in diagnostics. Replay may use a different independently verified index version and must produce the same canonical archive. Do not add incidental row order or index epoch to legacy/field-agent semantic schemas. If a future Psi choice changes route behavior, bind a new semantic version or an admitted event first.'),
        eq('M_total_next = existing FI5 accounting + M_index\nM_peak_rebuild includes old bundle + candidate bundle\nM_index includes all retained descriptor/key/tree metadata'),
        p('Index metadata is separate from the bounded FIFO. It shall not hide a complete arena of packed world-node pairs. Account for both old and candidate allocations during rebuild, including device resources and all retained host metadata. A smaller active-pair capacity is not a bound on total memory.'),
        small('Current FI1-FI8 behavior remains the refinement oracle: the same admitted observations must reproduce the same movement, energy, repair and persistence history through every allowed storage version.')
    )
    page('Psi-index reference and acceptance', 'VERIFIED FINITE PROFILE | PX8 | VECTORS AND CONFORMANCE',
        h('PX8. Default 4 by 5 reference'),
        p('Use the default Klein recipe (centre 0, radius 2, turns [11,53,137]) and binding epoch 0, sign +1, phase origin 0. The literal orders below follow PX1-PX5. The retained docs/evidence/psi-f8-v1/formal-reference.json contains all 20 node records and the complete tree; these are formal vectors, not runtime measurements.'),
        code('sorted node IDs:\n18,17,19,15,16,4,3,14,13,1,2,11,12,9,0,5,10,6,8,7\npreorder node IDs:\n1,16,17,18,19,15,3,4,14,13,0,11,2,12,9,6,5,10,8,7'),
        table(['Node ID','Five-component canonical key'],[
            ['0','(3,2,0,0,0)'],
            ['6','(3,3,1,22,6)'],
            ['7','(4,3,2,75,7)'],
            ['16','(1,3,1,22,16)'],
            ['17','(0,3,2,75,17)'],
        ],[.2,.8]),
        p('The root is row 0, node 1; its left child is row 1, node 16, and its right child is row 10, node 0. The tree relation 1 to 16 is not a geometric movement edge. Node 16 has g=(-2,2), lambda=8 and Psi=(-1,1). Its temporary alias (7,-1) has reflected-chart components g=(-2,-2), Psi=(-1,-1), but the same canonical key.'),
        h('Required independent conformance'),
        p('Require independent cover/BFS and field oracles; all 25 possible gradients, both signs and both local frames; eigen-equations, zero-axis tie and bounds; literal keys, complete rows and phase derivations; negative/large aliases; strict binding types, MISS and corrupted trees.'),
        p('Require real GPU construction and tree-governed texture lookup, corrupted-row rejection and no CPU fallback; actual sample eviction/regeneration; capacity and rebuild invariance including retained DEFER search; complete candidate certification, atomic failure, cleanup-after-commit reporting and epoch overflow. Legacy archives remain bit-exact, and the entire FI8 mission remains unchanged.'),
        box('<b>Revision 4 acceptance status: VERIFIED FINITE PROFILE.</b> All 20 PX conformance checks pass. The complete suite has 421 passing tests, 55 actual-device methods and zero skips. Four FI8-cycle rebuilds and 41 DEFER-cycle rebuilds preserve the prior canonical archive, energy, FIFO and retained search.'),
        small('This finite binding supplies local SDF-derived eigenstructure and a canonical middle-out storage index. It does not complete global Psi traversal, Hadamard routing, geometry-changing growth, active scale transitions, physical adapters or indefinite continuation.')
    )
    page('Typed Hadamard routing policy', 'VERIFIED FINITE PROFILE | HP1-HP2 | BEHAVIORAL BINDING',
        h('HP1. Explicit semantic policy and schema'),
        p('FieldAgentManifest gains the distinct policy tomigidt-field-hadamard-plan-act-v1. Only this policy requires the additional JSON key routing; its exact routing keys are format and gains. Format is hadamard-klein-routing-v1. Gains are an immutable 4 by 2 table of strict integers in [-4,4]; reject Boolean integers, missing/unknown keys and malformed shapes. Defaults are shown below.'),
        code('routing = {"format":"hadamard-klein-routing-v1",\n           "gains":[[1,1],[-1,1],[-1,-1],[1,-1]]}'),
        p('Existing field policy, manifest schema, FI/PX contracts and legacy archives remain unchanged. Live words retain RP32-relational-sdf-v2 with B=phi, canonical G and separate energy. This new routing object belongs to semantic identity; storage IndexBinding remains deployment metadata.'),
        h('HP2. Exact local product and movement cost'),
        p('Use PX field-derived g and primitive Psi in the canonical Klein frame. Use the live intrinsic phase t, never the index derivation phase or index phase_origin. Direction e is exclusively one of the four unit cardinal quotient directions from the source to an adjacent geometric node; diagonal or tree-edge moves are not admitted.'),
        eq('t = (-1)^eta * r mod 256; bank = floor(t/64)\nd_i = gains[bank][i] * (1 + Psi_i^2)\nq = d Hadamard g; M = max(abs(q_u),abs(q_v))\npenalty(source,dest,t) = M - dot(q,e)\ncost = 1 + abs(phi(dest)) + hazard(dest) + penalty'),
        p('This is fixed-point f=0 with widened signed i32 products/sums and no rounding or clipping. Each q component is in [-40,40], penalty in 0..80 and cost in 1..335. A route of at most 255 hops costs at most 85,425. Zero g gives q=0 and zero penalties. These are integer application costs, not calibrated physical energy.'),
        eq('J = diag(1,-1); g_prime=J*g; Psi_prime=J*Psi\nd_prime=d; q_prime=J*q; e_prime=J*e\ndot(q_prime,e_prime)=dot(q,e)'),
        p('Squared Psi components make both the local chart transformation and IndexBinding sign irrelevant to d. Costs are chart-covariant, and changing index phase_origin changes no routing bank. The complete mirror also preserves t. K8 live transport remains responsible for eta, parity and the full mirrored pair.'),
        small('Source basis: original pp.5,7,10,11,16,18; Solus pp.3-4; solipsism pp.5,13,16. These motivate qualitative field/operator/traversal roles. HP is an explicit numerical choice, not a uniquely implied source formula, global eigenmode or speed claim.')
    )
    page('Phase-state planning and admitted action', 'VERIFIED FINITE PROFILE | HP3-HP4 | FINITE LIFTED SEARCH',
        h('HP3. Immutable phase-state Dijkstra search'),
        p('Use labels (G,t,hops), with canonical node G, intrinsic phase t in 0..255 and hop count in 0..max_hops. All geometric adjacencies remain admissible and every edge has positive cost. Node-only labels, or labels omitting t, may merge arrivals with different future costs and are unsound. Revisits are permitted because phase changes can improve subsequent directional costs.'),
        eq('label = (G,t,hops)\nt_next = (t + turns[class(phi(G))]) mod 256\nhops_next = hops + 1\npriority = (total cost, lexical route, G, t, hops)'),
        p('Hop bound remains a strict integer in 1..255; per-cycle search quantum remains 1..65,536 expansions. Preserve global lexical canonical-name route ties. Use reverse unweighted hop distance to the target to prune labels that cannot finish within the remaining hop budget. Count an expansion only for a non-stale, non-target popped label whose outgoing edges are inspected. Reaching the target ends a candidate route; do not continue through it.'),
        p('Dominance applies only to the exact (G,t,hops) label. Evaluate entry weights once in lexical canonical-name order. The immutable context includes position, live pair/phase, energy, routing binding, weights and directional model. Retain the complete frontier, best costs, route ties and progress through DEFER. Changed effective hazards invalidate the cursor; invalid input preserves it and all canonical state.'),
        h('HP4. Observation, reserve and receding planning'),
        p('Fresh complete local frames still precede MOVE or REPAIR. Sensors supply only admitted local hazards; unseen distant nodes retain the zero-hazard hypothesis. Search, rather than the sensor, selects a route. Forecast its full K8 packed/energy sequence; admit one adjacent action and debit that first edge’s HP2 cost. Require the whole known route cost plus repair reserve to fit available energy.'),
        p('At the freshly observed target, retain FI4 REPAIR semantics. No planner action bypasses the target check. Under unchanged effective weights, after following the first edge of an optimal route, its remainder is still feasible within the next full hop budget. The next optimal cost is therefore at most the previous optimal cost minus that strictly positive edge cost. Receding optimal value strictly falls despite possible phase cycles.'),
        eq('V_H(G_next,t_next) <= V_H(G,t) - cost(G,G_next,t)\n                                < V_H(G,t)'),
        p('This decrease assumes an unchanged model and successful admitted movement; new observations may change its value. Full RP32 execution applies the existing source-field increment, seam reflection and eta XOR. The resulting intrinsic phase obeys t_next above independently of seam/orientation, while R and eta still follow K8.'),
        small('The finite label bound is N*256*(max_hops+1), not a constant-memory search guarantee. Search/history/object overhead remains separate from active world-pair FIFO capacity.')
    )
    page('Routing atlas and certified export', 'VERIFIED FINITE PROFILE | HP5-HP6 | CERTIFIED DEVICE MODEL',
        h('HP5. Movement and cost in one exact atlas'),
        p('The HP GPU operator atlas is an r32uint texture of width 24 and height 4N. Within each source, neighbor slots are sorted by numeric canonical destination ID. Its row is selected through the actual f8 tree walk; the row is storage, while source/destination G remain geometric identities.'),
        eq('y = bank*N + f8_row(source)\nx = 6*numeric_neighbor_slot + 2*field_class\natlas[x,y]   = existing RP32 movement operator\natlas[x+1,y] = pack(bank,source,penalty,DATA)'),
        p('There are four banks, four neighbor slots and three field-class copies: 48 movement/cost pairs per node. The movement word retains the existing delta, destination, exact destination phi and relative seam metadata. The cost word has R=bank, G=source and B=penalty. Recompute valid parity; no operator-only seam bit may leak into live metadata.'),
        p('The shader obtains bank from the persistent live pair for actual actions and from the evolving scratch pair for forecasts. Actual tree lookup governs the atlas row in both paths. Compile the atlas from certified device field, g and Psi together with the immutable gains; no host-compiled replacement may stand in for explicit GPU construction.'),
        h('HP6. Export the admitted table, then search on host'),
        p('An export_routing pass reads the actual atlas and validates all 48 movement/cost pairs for each node: parity, complete movement/cost payload, source/bank/destination, class increment and all three repeated penalty copies. It exports exactly 16N penalties and N source increments. A malformed unselected bank or class is still invalid.'),
        eq('routing model = 16*N penalties + N source increments\nentry_weight(j) = 1 + abs(phi(j)) + hazard(j)\nedge_cost(i,j,t) = entry_weight(j) + penalty[i,bank(t),j]'),
        p('An independent host certificate checks the exported table against the exact field-derived HP2 equations and semantic routing binding. CPU routing derives its equivalent model independently. The host Dijkstra heap consumes the certified device-produced table; it shall not run a host routing compiler as GPU fallback or perform a GPU dispatch for each expansion.'),
        p('The retained semantic model contains those 17N integers and effective entry weights, not a CPU scalar-field arena. Geometry and field samples remain recipe-derived under their existing contracts. CPU/GPU costs, forecasts, choices and admitted histories must agree for the same HP manifest and observations.'),
        small('For HP owners, the complete atlas and routing-table certificate extends FI6/PX6 admission. Existing persistent-action ownership, no-fallback and uncertain-outcome closure requirements remain binding.')
    )
    page('Hadamard rebuild and resource contract', 'VERIFIED FINITE PROFILE | HP7 | ONE ADMITTED BUNDLE',
        h('HP7. Atomic index replacement with routing resources'),
        p('An HP index rebuild prepares a complete candidate index, tree, routing atlas, exported routing tables and bind groups. Certify the whole candidate before a serialized atomic swap. Preserve the full semantic routing object; a storage rebuild cannot silently change gains, costs or policy.'),
        table(['Outcome','Required result'],[
            ['Invalid input / complete certificate rejection','Old index/atlas/model remains usable. Preserve canonical history, energy, FIFO contents/order/counters and the exact pending search.'],
            ['Uncertain dispatch or readback','Close the owner with the last admitted history unchanged. Reconstruct from durable admitted history before more work.'],
            ['Successful complete-bundle swap','Install the new storage version while retaining identical semantic costs, samples, state and search cursor.'],
            ['Post-swap cleanup failure','Report a committed cleanup failure, not rejected replacement. Account for and attempt cleanup of retained resources.'],
        ],[.32,.68]),
        p('Index sign and index phase_origin do not change q or t. Thus PX version changes preserve every HP planning label, comparison, cost, expansion quantum, pair, energy value and event. FIFO residency is also preserved. Replay may select a different certified storage index while retaining the same semantic manifest and observation history.'),
        h('Explicit allocation and peak accounting'),
        eq('routing atlas = 24 * (4*N) * 4 = 384*N bytes\nexported routing table = 17*N*4 = 68*N bytes\nretained host routing table = 68*N bytes\ngains table = 4*2*4 = 32 bytes'),
        p('These are logical payload sizes for the declared atlas/table/gains resources, not total process memory. Track all additional host/device index metadata, field/geometry buffers, entry weights, scratch buffers, bind groups and runtime allocations. Rebuild peaks include complete old and candidate bundles together, rather than counting only their difference.'),
        eq('M_peak includes old(index,atlas,tables,bind groups)\n              + candidate(index,atlas,tables,bind groups)\n              + retained fields, geometry, FIFO and runtime'),
        p('The world-pair FIFO retains its 8C-byte payload bound and actual regeneration obligation. Search may have N*256*(max_hops+1) labels. Frontier/routes, routing tables, observations and journal memory remain outside the FIFO bound.'),
        small('No throughput, speedup, saturation or physical-energy claim follows from these allocations. A comparative performance result would require the separate measurement protocol on page 30.')
    )
    page('Hadamard reference and acceptance', 'VERIFIED FINITE PROFILE | HP8 | INDEPENDENT VECTORS',
        h('HP8. Default phase-directed mission'),
        p('Use the FI8 4 by 5 recipe and local hazard change, with the HP1 default gains, initial phase 250, eta 0, energy 100 and repair cost 5. Initial pair is 91FE000601FE00FA. The independent reference uses quotient arithmetic, BFS, phase-state Dijkstra and a layered-DP cross-check; it imports no solvefinite runtime module.'),
        table(['Cycle / action','Route; known cost; expansions','Actual pair / energy'],[
            ['1 / MOVE','[4,3,17]; 7; 23','11FF04FB01FF0405 / 98'],
            ['2 / seam MOVE','[16,17]; 7; 6','81001010910010F0 / 93'],
            ['3 / MOVE','[17]; 2; 2','81011145910111BB / 91'],
            ['4 / REPAIR','[]; repair 5; 0','06011145160111BB / 86'],
        ],[.2,.38,.42]),
        p('From cycle 2, hazard 70 at node 3 changes the route after entering node 4. Geometry and packed seam transport remain the FI8 values, but HP2 adds directional costs. Zero gains recover the old edge costs and final energy 90. With only initial phase changed to 192, the first route is [5,10,11,12,17], cost 12; completion takes six cycles, final pair 960111E38601111D and energy 83.'),
        h('Why the search state must contain phase'),
        p('At start node 0, target 10, intrinsic phase 128 and max_hops 12, correct labels (G,t,hops) select [1,6,5,10], cost 10. Incorrect merging by (G,hops) selects [5,10], cost 11. This is a literal finite counterexample to phase-free state compression, not a performance comparison.'),
        h('Required independent conformance'),
        p('Require strict new-policy schema with exact legacy preservation; integer bounds, zero gains, all banks/signs/frames, chart covariance and mirror invariance; independent lifted-search/DP route and cost oracles, revisits, hop/quantum limits, stale-model invalidation and DEFER replay. Sensor inputs shall not supply routes or actions.'),
        p('Require real GPU atlas compilation and all 48-pair payload checks, certified exported tables, no CPU compiler fallback, actual indexed action/forecast bank selection, corruption in unselected copies, resource peaks, pure rejection, uncertain-outcome closure and committed cleanup failures. Capacity/rebuild changes preserve FIFO, cursors and archives; fresh-process cross-backend/live continuation remains exact.'),
        box(f'<b>Revision 6 acceptance status: VERIFIED FINITE PROFILE.</b> The new capture has {hp_tests} passing tests, {hp_device_tests} actual-device methods and {hp_checks} HP conformance checks. Earlier 421/55/20 PX counts retain their historical identity. Implementation evidence follows on page 49.'),
        small('Retained reference: docs/evidence/hadamard-v1/formal-reference.json and independent reference-builder.py. The equations and vectors are a declared finite routing binding, not global Psi, physical energy calibration, a speed claim or whole-architecture completion.')
    )
    page('Measured Hadamard implementation', 'REVISION 6 EVIDENCE | HP1-HP8 | FINITE PROFILE',
        p('HP1-HP8 were committed before runtime coding at <font name="Mono">0c862c3</font>. The implementation extends the same Tomigidt individual. Its certified gradient and local Psi, together with its live intrinsic phase, now alter route costs and actual CPU/GPU actions.'),
        table(['Capture','Measured result'],[
            ['Complete regression suite', f'{hp_tests} passed; {HP_VERIFICATION["tests"]["skipped"]} skipped; {HP_VERIFICATION["tests"]["elapsed_seconds"]} seconds.'],
            ['Actual-device coverage', f'{hp_device_tests} executed GPU methods; {HP_VERIFICATION["gpu_domains"]} domains, {HP_VERIFICATION["gpu_nodes"]} nodes and {HP_VERIFICATION["gpu_penalty_checks"]:,} penalty comparisons.'],
            ['HP conformance', f'All {hp_checks} named checks passed. The one-expansion DEFER mission takes {HP_VERIFICATION["deferred_mission_cycles"]} cycles and preserves search across every rebuild.'],
            ['Behavioral ablations', 'Default: four cycles, energy 86. Zero gains: energy 90. Initial phase 192: a different first route, six cycles, energy 83. Exact pairs and routes remain on page 48.'],
            ['Device payload / rebuild peak', f'{hp_allocation["device_payload_bytes"]:,} / {hp_allocation["peak_rebuild_device_payload_bytes"]:,} bytes; complete old and candidate bundles are counted.'],
            ['Routing allocations', f'Atlas {hp_allocation["routing_atlas_bytes"]:,} bytes; device/host tables {hp_allocation["device_routing_table_payload_bytes"]:,}/{hp_allocation["host_routing_table_payload_bytes"]:,} bytes. Geometry, runtime and Python-object memory remain additional.'],
        ],[.32,.68]),
        h('What changes the next action'),
        p('Separate node/phase/hop labels preserve distinct futures. The device atlas holds four phase banks; export admission checks every bank/class copy. Forecasts and persistent actions use their current phase and actual f8 lookup. Storage changes preserve routing, search, FIFO and history. Continuation across CPU/GPU backends and failure cases are identified in the retained logs.'),
        h('Reproduce and inspect the evidence'),
        code('python -m unittest discover -s tests -v\npython -m examples.hadamard_conformance --output hp.json'),
        small('Retained capture: docs/evidence/hadamard-v1/. verification.json binds source/report hashes at commit 5a304bc, formal chronology and measured counts. Earlier FI/PX captures retain their named commits and original counts.'),
        small('<b>Remaining scope:</b> global eigenmodes, geometry-changing growth, active scale transitions, physical adapters and wider continuation. These finite measurements establish no GPU saturation, general speedup or calibrated physical-energy claim.'),
    )
    page('Autonomous growth binding', 'VERIFIED FINITE PROFILE | GD1 | SEMANTIC PROFILE',
        p('Source basis: original sections 3, 8, 14 and 16; Solus page 6; Solipsism pages 13 and 16. The addendum describes growth through changes to internal distance rules. GD1-GD8 choose a finite dyadic production for the same Tomigidt individual. The source does not supply this numerical production or its target, cost and continuation rules.'),
        h('GD1. A versioned production with one history'),
        eq('policy = tomigidt-field-growth-plan-act-v1\ngrowth.format = klein-dyadic-growth-v1\ngrowth = {format, max_epochs, cost}'),
        p('The exact new FieldAgentManifest schema requires both routing and growth, in addition to the previous field-agent keys. Routing obeys HP1. GrowthBinding is immutable: max_epochs is a strict integer in 0..2 and cost is a strict integer in 1..127. Defaults are max_epochs=1 and cost=1. Reject Boolean/noninteger values, wrong formats and unknown or missing keys. Prior policies reject growth and preserve their original canonical schemas.'),
        eq('N_initial * 4^max_epochs <= 256\nepoch k starts at 0; 0 <= k <= max_epochs'),
        p('Validate the maximum node bound before allocating a candidate. When max_epochs is positive, the initial radius must be at least one. Other initial recipe, word, routing, observation, energy, search and cycle bounds retain their declared meanings. The immutable manifest stores the initial recipe, initial target and complete grammar binding; it is not overwritten with a later recipe.'),
        p('The live state additionally retains semantic geometry epoch k, current recipe and current target. A production extends this same individual and its ordered history. It neither creates a replacement agent nor resets its energy, global cycle or event sequence. Producer epochs and interchangeable storage-index epochs are distinct from k.'),
        box(f'<b>Revision 8 status: VERIFIED FINITE PROFILE.</b> GD1-GD8 preceded implementation at ec1181e; the prefix-identity refinement preceded its runtime field at 00b0e64. The separate GD capture has {gd_tests} passing tests, {gd_device_tests} actual-device methods and {gd_checks} conformance checks. Page 57 identifies that evidence.'),
        small('This binding is a finite grammar with one production family. It does not complete arbitrary L-systems, cone/pyramid synthesis, physical growth or indefinite continuation.')
    )
    page('Dyadic geometry and active scale', 'VERIFIED FINITE PROFILE | GD2 | QUOTIENT PRODUCTION',
        h('GD2. Generate a larger intrinsic quotient'),
        eq('(W,H,c,r,k) -> (2W,2H,E(c),2r,k+1)\nE(u,v) = (2u,2v)\nG = u*H+v; E(G) = (2u)*(2H)+2v\nrho(k) = rho(0)*2^k; log-radius exponent = k'),
        p('Apply exactly one finite generation. All new edges have unit integer weight. The new Klein quotient, oriented seams, centre and intrinsic-ball boundary are regenerated from the production. Node names remain canonical for that epoch. New names alone cannot identify a historical sample: the geometry epoch is part of its semantic context.'),
        h('Quotient correspondence and transport'),
        p('The doubling map respects (u,v)~(u,v+H) and (u,v)~(u+W,-v): doubling either representative gives equivalent new representatives. Every old cardinal edge maps to a two-edge cardinal path. A reversing old edge crosses the new reversing seam once; a nonreversing old edge crosses it zero times. Thus the composed seam XOR agrees with the original edge.'),
        p('Retain the current R and eta exactly through the growth mapping. The intrinsic phase t=(-1)^eta*R mod 256 is therefore preserved, as is the full mirror relation after repacking. Map the agent and centre with E. Reconstruct the new signed field from the new boundary and its shortest-path distances, using widened exact arithmetic and the existing range certificate.'),
        eq('R_next = R; eta_next = eta\nG_next = E(G); B_next = phi_next(E(G))\nE_energy_next = E_energy - growth.cost'),
        p('Do not compute B_next by shifting or doubling the old B. The newly admitted boundary-distance certificate is authoritative. The next live pair has STEP metadata; the pre-growth pair is the EMIT pair from the completed subgoal. Recompute parity and the complete mirror.'),
        p('Here active scale is the declared intrinsic dyadic generation: lengths of embedded edge paths and the ball radius expand by two while the new lattice retains unit edges. The exact exponent k controls actual geometry and its operators. No geographic origin, calibrated physical unit or claim of unchanged physical resolution is imposed.'),
        small('Literal field counterexample: W=3,H=5,centre=1,radius=3,old G=0 gives B=-3. After growth, W=6,H=10,centre=2,radius=6 and mapped G=0 give B=-4, not -6. Generated boundary vertices change the nearest-boundary distance.'),
        small('Connectivity, audited quotient cells/links, boundary separation, exact field range, local Psi, f8 and HP operator conformance must hold at every candidate epoch. A rejected candidate is not an admitted generation.')
    )
    page('Subgoals, growth and energy reserve', 'VERIFIED FINITE PROFILE | GD3 | ONE AUTONOMOUS LIFECYCLE',
        h('GD3. Complete a subgoal, then derive the next world'),
        p('Within an epoch, retain HP planning, fresh local observations, positive directional costs, full forecasts and one-edge action admission. At the freshly observed current target, REPAIR debits the manifest repair_cost and emits the same EMIT pair as FI4. The default repair cost remains five.'),
        table(['Condition after REPAIR','Required status and continuation'],[
            ['k = max_epochs','COMPLETE. This bounded growth mission has reached its final subgoal.'],
            ['k < max_epochs','GROWTH_PENDING. Retain the repaired EMIT pair. Do not report COMPLETE or silently move in the old geometry.'],
        ],[.32,.68]),
        p('A new complete fresh local observation frame in the old geometry is required before GROW. The fixed grammar then derives the candidate, maps the state and selects the next target by GD4. Exactly one admitted GROW event advances the geometry epoch. Growth is an internally selected lifecycle action; sensors never provide a replacement world, target or route.'),
        h('Reserve future finite obligations'),
        eq('m = max_epochs-k\nreserve(k) = repair_cost + m*(growth.cost+repair_cost)\nknown_route_cost + reserve(k) <= available_energy'),
        p('Require this reserve before MOVE and REPAIR; a reached target has known_route_cost=0. It includes the current repair and the remaining growth/repair costs, not the still-unknown routes in future geometries. Those routes must separately fit the energy when their epochs become current. Unseen hazards retain the HP zero-hazard hypothesis.'),
        eq('At GROWTH_PENDING, require:\ngrowth.cost + reserve(k+1) <= available_energy'),
        p('A positive growth cost is debited exactly once; energy is never replenished by a generation. Insufficient energy prevents the action under the declared agent status rules. The existing finite max_cycles bounds the whole mission across all geometry epochs; global cycle and event ordering do not restart.'),
        p('On a successful GROW, clear effective observations, retained search and active sample FIFO. The new epoch requires a new complete fresh local observation before MOVE or REPAIR. Previous observations remain in admitted history for replay; they are not silently interpreted as measurements of the new geometry.'),
        small('A zero-growth binding executes one HP subgoal with no GROW events. Max_epochs selects this finite mission size; it does not claim whole-system indefinite progression.')
    )
    page('State-selected next target', 'VERIFIED FINITE PROFILE | GD4 | INTRINSIC DETERMINISTIC SELECTION',
        h('GD4. Choose among genuinely generated nodes'),
        p('Let a=E(current_node) in the certified candidate quotient. New nodes are exactly those whose canonical u or v is odd. Use the independently certified candidate field and unweighted shortest-path distance from a. The selection order below is semantic and independent of f8 storage order.'),
        eq('C0 = {v : u(v) is odd or v_coordinate(v) is odd}\nb = min(abs(phi_next(v)) for v in C0)\nC1 = {v in C0 : abs(phi_next(v)) = b}\nd = max(distance(a,v) for v in C1)\nC2 = sorted({v in C1 : distance(a,v)=d}, by numeric G)\ntarget_next = C2[t mod len(C2)]'),
        p('C0 is nonempty after a valid dyadic production; subsequent finite minimization and maximization preserve a nonempty candidate set. Lexical node-name order is not used for this final tie. The live intrinsic phase t is unchanged by full mirroring and by index sign/origin changes, so equivalent mirrored states select the same canonical target.'),
        h('A semantic generation changes future decisions'),
        p('The new recipe, new certified phi, rebuilt local eigenstructure, routing model and selected target jointly define the next planning problem. The individual continues with its retained identity, mapped pair and remaining energy. The newly created nodes are eligible for subsequent motion through their genuine geometric adjacencies.'),
        p('For an explicit GPU realization, target selection must consume the GPU-produced field after independent admission. No host field compiler may substitute a CPU field for that source. Host admission and deterministic target selection are permitted; their complete inputs and resulting target remain replayable.'),
        p('The choice uses current packed phase and generated geometry rather than an externally supplied list of future targets. Changing the phase may select a different tied target; it cannot change the declared priority of boundary proximity or graph distance.'),
        box('A storage reindex is still a refinement that preserves history and search. GROW is a semantic transition that changes the world, target and model context. These events have deliberately different admission and invalidation effects.'),
        small('Literal tie: in the 8 by 10 candidate with centre 0, radius 4 and mapped current node 0, C2=[13,17,31,39,51,59,73,77]. Intrinsic phases 0,1,2,63 select targets 13,17,31,77 respectively.'),
        small('Two-generation reference: a 3 by 3 quotient, centre 0, radius 1, start 0 and target 4, phase 250, eta 0, energy 100 and zero hazards grows at cycles 4 and 10. New targets are 31 then 15. Cycle 25 ends at pair 86000F0E16000FF2, energy 33, in the 12 by 12 quotient. These are mathematical expected values.')
    )
    page('Atomic growth and device mapping', 'VERIFIED FINITE PROFILE | GD5 | COMPLETE CANDIDATE ADMISSION',
        h('GD5. Prepare, certify, map, then commit'),
        p('Prepare a complete candidate audited quotient, boundary field, local Psi/f8 structure, HP atlas, certified exported routing model, empty sample FIFO and runtime resources. The candidate must pass the existing independent geometry, field, index and all-bank/class operator certificates before it can replace the old world.'),
        p('For explicit GPU execution, a device growth-mapping pass reads the old packed pair and energy with the old height, computes the mapped G, reads the certified new phi, debits growth cost and writes the candidate canonical pair/energy. Read back and independently validate this result before the serialized swap. Host seeding of a precomputed mapped pair is not an allowed fallback.'),
        p('Validate the old EMIT pair, full mirror, old G/B context, preserved phase/orientation, mapped node, new B, STEP metadata and exact energy debit. The new device executor starts its per-epoch tick count at zero. This counter is diagnostic/local execution state; the agent cycle and event sequence remain global.'),
        table(['Outcome','Required effect'],[
            ['Pure precommit candidate failure','Reject with old archive, world, energy, FIFO and pending search unchanged. Dispose candidate resources.'],
            ['Uncertain candidate dispatch/readback','Close the candidate and conservatively close the owning agent; retain its last admitted history.'],
            ['Uncertain old-device result','Close the owner. Do not fabricate a successful mapping or acknowledge a new generation.'],
            ['Complete certified swap','Install the new world and canonical state, debit once, clear current observations/search/FIFO and append exactly one GROW event.'],
            ['Post-swap cleanup failure','Preserve the admitted GROW event in memory, report committed=True and close the owner. Do not report a rejected production.'],
        ],[.32,.68]),
        p('A failed live session is fatal and must reopen the last durable file. If an atomic save was uncertain, that file can contain the history before or after GROW; replay and retry handling determine the admitted result. No in-memory guess overrides the durable archive.'),
        eq('M_active_pairs <= 8*C bytes\nM_peak_growth >= M_old_world + M_candidate_world'),
        small('GD7 resource accounting includes fields, topology, indexes, routing, state, grammar, journals, observations, search and all host/device metadata. Resource ownership remains explicit until cleanup completes; the active-pair FIFO bound is not a total-memory bound.')
    )
    page('Epoch-aware replay and regeneration', 'VERIFIED FINITE PROFILE | GD6-GD7 | CONTEXT AND RETENTION',
        h('GD6. Preserve the context of every observation'),
        code('event = {seq,input,decision,output,energy,geometry_epoch,growth}\nreceipt = {format,from_epoch,to_epoch,mapped_node,target,recipe}'),
        p('For this policy only, geometry_epoch is the pre-cycle integer; growth is null except on GROW. Its receipt has exactly the keys above: format is klein-dyadic-growth-v1, mapped_node and target are new canonical names, and recipe is the full new recipe. Strict replay regenerates every event and receipt from the immutable initial manifest and admitted prefix.'),
        p('Snapshots add exactly geometry_epoch, current_recipe and scale_exponent=k. The existing target is the current target, footprint.epoch=k, and baseline remains initial. A nonnull planning context additionally contains geometry_epoch. Earlier policies retain their schemas.'),
        p('A new-policy live observation supplies geometry_epoch matching its pre-event context; validate locality in that geometry. Reject a stale/future epoch on a new event. A duplicate earlier producer sequence instead uses its original epoch/locality and returns the recorded event without another action or debit.'),
        p('The supplied simulator applies its original hazard schedule only at epoch 0; generated epochs receive fresh zero-hazard frames in their current geometry. This is a declared simulation assumption. Live input may supply arbitrary admitted local hazards. Sensors never supply worlds, targets, routes or actions.'),
        h('GD7. Generation-qualified identities and finite resources'),
        eq('derive_epoch(epoch,path) -> qualified DATA sample\nrecipe_at_epoch(epoch) -> admitted epoch recipe'),
        p('The sample contains geometry_epoch, origin_sequence (zero initially; otherwise the original GROW sequence), prefix_sha256, initial-recipe/grammar identity, path and pair. Reconstruct its recipe from the initial recipe and admitted production prefix; only already admitted epochs are accessible. Retain original context rather than substituting the current tick or recipe.'),
        eq('prefix = events[:origin_sequence]; initial prefix = []\nprefix_sha256 = SHA256(canonical_UTF8(prefix)).hexdigest()'),
        p('The digest is 64 lowercase hexadecimal characters. Canonical encoding is json.dumps(prefix, sort_keys=True, separators=(\',\',\':\'), ensure_ascii=True, allow_nan=False).encode(\'utf-8\'), with no trailing newline. Include every original event through the admitting GROW event, not only its sequence number. Equal epoch, recipe, node and DATA pair do not identify the original prefix; prefix_sha256 records its digest. Reindexing, cache capacity and exact replay preserve this digest.'),
        p('Historical derivation does not mutate the current FIFO or state. GROW starts an empty active FIFO; capacity changes may alter residency but not samples or decisions. Reindex preserves the current recipe, target, observations, search and identities; GROW invalidates that semantic context. Resource bounds and complete candidate peaks are on page 54.'),
        small('The generation exponent, global cycle, producer epoch/sequence and storage-index epoch have separate purposes. None may silently substitute for another during replay, retries or regeneration.')
    )
    page('Growth reference and acceptance', 'VERIFIED FINITE PROFILE | GD8 | INDEPENDENT VECTORS',
        h('GD8. Mathematical reference before runtime'),
        small('Use the HP8 default world, initial pair, energy and epoch-0 hazard timeline; max_epochs=1, growth cost 1 and repair cost 5. The independent reference imports no solvefinite module; every MOVE route is cross-checked by hop-layer dynamic programming.'),
        eq('cycle 4 REPAIR: 06011145160111BB, energy 86\ncycle 5 GROW:   01024045110240BB, energy 85\ncycle 14 REPAIR:160027E906002717, energy 64'),
        small('GROW maps node 17 to 64 in an 8 by 10 quotient and selects new target 39 (k:3:9). Full fields, missions, mirror/tie vectors and quotient checks are retained in docs/evidence/growth-v1/formal-reference.json with its independent reference-builder.py.'),
        h('Required conformance'),
        table(['Obligation','Required evidence'],[
            ['Strict profile and finite bounds','Exact schemas and legacy preservation; Boolean/overflow rejection; max_epochs=0,1,2; preallocation rejection when N*4^max_epochs exceeds 256.'],
            ['Production and transport','Full quotient/cell audits, equivalent aliases, every old edge\'s two-edge image and seam XOR, fresh exact field and full mirror/phase preservation.'],
            ['Autonomous continuation','Actual REPAIR, GROWTH_PENDING, GROW and later movement/repair in one history; literal targets and energy reserves; phase-dependent target ties; no external recipe/action supply.'],
            ['Device refinement','GPU-produced fields and growth-mapped canonical state; no CPU compiler or host-pair fallback; certified fields, tree, all HP atlas copies and actual post-growth device actions.'],
            ['Atomicity and durability','Pure rejection, uncertain candidate/old device, post-swap cleanup failure, committed status, save uncertainty and reopen/retry before and after durable growth.'],
            ['Replay and residency','Generation-qualified historical samples, empty new FIFO, stale observation rejection, duplicate original-epoch retries, current-geometry simulation and cross-backend/process continuation.'],
        ],[.29,.71]),
        small('Capacity and index variations must preserve history at every epoch. Reindex during DEFER and after growth; invalidate semantic planning only for growth or changed effective observations. Test cycle/energy boundaries without resetting the individual.'),
        box(f'<b>Revision 8 acceptance: VERIFIED FINITE PROFILE.</b> The separate runtime/device capture passes all {gd_checks} named conformance checks. The independent formal vectors remain expected outputs; page 57 reports their tested implementation and retained evidence.'),
        small('The full architecture still includes general production systems, global spectral traversal, physical adapters, wider temporal continuation and measured performance. Completing this finite profile does not discharge those obligations.')
    )
    page('Measured autonomous geometry growth', 'REVISION 8 EVIDENCE | GD1-GD8 | SAME INDIVIDUAL',
        p('The same Tomigidt now repairs a subgoal, derives a larger Klein quotient, maps its packed state on the device and continues to an internally selected target. GD1-GD8 were committed at ec1181e before runtime coding; the original-event-prefix digest was bound at 00b0e64 before its runtime field. Neither step rewrites the initial manifest.'),
        table(['Capture','Measured result'],[
            ['Complete regression suite', f'{gd_tests} passed; {GD_VERIFICATION["tests"]["skipped"]} skipped; {GD_VERIFICATION["tests"]["elapsed_seconds"]} seconds.'],
            ['Actual-device coverage', f'{gd_device_tests} executed GPU methods. All {gd_checks} named GD conformance checks pass, including device mapping and post-growth actions.'],
            ['One generation', f'{gd_default["archive"]["expected"]["cycle"]} cycles, final energy {gd_default["archive"]["expected"]["energy"]}. The 20-node world becomes 80 nodes; cycle 5 maps node 17 to 64 and selects target 39.'],
            ['Two generations', f'{gd_two["archive"]["expected"]["cycle"]} cycles, final energy {gd_two["archive"]["expected"]["energy"]}. The 9-node world becomes 36, then 144 nodes, under the same global history.'],
            ['Retained incremental search', f'Quantum 7: {gd_deferred["archive"]["expected"]["cycle"]} cycles. Reindexing throughout generated-world DEFER preserves the canonical history.'],
            ['Device payload / growth peak', f'{gd_allocation["device_payload_bytes"]:,} / {gd_peak["device_payload_bytes"]:,} bytes in the default final world / complete old-plus-candidate growth preparation.'],
        ],[.31,.69]),
        h('Original context survives continuation'),
        p('Historical samples retain geometry epoch, original admission sequence and the digest of the exact original event prefix. Capacity changes and storage rebuilds preserve that context. Sensors describe the current geometry; stale epochs are rejected and earlier duplicates use their original geometry. The retained suite covers rejected candidates, uncertain results, committed cleanup failures and durable save/reopen boundaries.'),
        p('CPU/GPU histories agree for default, mirrored, zero-growth and two-generation missions. The conformance capture includes six fresh-process continuations before/after growth and during generated-world DEFER, with host field/index/routing compilers disabled on explicit GPU paths. A separate CLI capture resumes GPU to CPU to GPU and verifies read-only inspection.'),
        code('python -m unittest discover -s tests -v\npython -m examples.growth_conformance --output gd.json'),
        small('Retained evidence: docs/evidence/growth-v1/. verification.json binds source hashes at historical commit 94f86c7, report hashes, actual counts and formal-first commits. Device figures are logical resource payloads; Python objects, drivers, journals and other overhead remain additional.'),
        small('<b>Remaining scope:</b> general production tables and branch stacks, global eigenmodes, physical adapters, wider temporal continuation and comparative hardware measurements. This finite growth result establishes no GPU saturation, speedup, calibrated energy advantage or whole-architecture completion.')
    )
    page('Parameterized branching organogram', 'VERIFIED FINITE PROFILE | OG1 | NEW NUMERICAL BINDING',
        p('<b>Policy:</b> tomigidt-field-organogram-plan-act-v1. The same individual uses its prior certified field to interpret finite parameterized productions. Emitted intrinsic balls define its next field on the existing Klein quotient. This changes the boundary and distances, not the quotient dimensions, edges, cocycle, departure turns or original index anchor.'),
        box('OG1-OG8 retain their formal-first requirements at commit 5c76f2c. Revision 10 adds source-bound CPU/GPU implementation evidence on pages 67-68. GD and all earlier policies retain their contracts.'),
        h('OG1. Strict immutable grammar schema'),
        code('binding = {format,max_epochs,cost,symbols,axiom,rules,\n           generations,limits}\nformat = "klein-branch-organogram-v1"'),
        table(['Field','Exact finite domain'],[
            ['Epochs / cost / generations','max_epochs 0..4; cost 1..127; generations 0..8.'],
            ['symbols','Ordered list of 1..16 distinct {name,arity}; names match [A-Z][A-Z0-9_]{0,15}, excluding F,R,S,SCALE; arity 0..4.'],
            ['axiom','Ordered list of 1..32 tokens. A token is exactly {symbol,args}; args is an ordered array. Symbol and argument count match its declaration.'],
            ['rules','Ordered list of 0..64 {symbol,guards,rhs}; left symbol is a declared nonterminal. Guards number 0..8; RHS tokens number 0..32. No terminal is a rule left side.'],
            ['limits','Exactly max_symbols 1..1024, max_steps 1..4096, max_balls 1..64 and max_stack 0..32.'],
        ],[.24,.76]),
        p('Fixed terminal arities are F:1, +:1, -:1, [:0, ]:0, R:1, S:0 and SCALE:1. Every listed key is required; undeclared keys, unknown symbols, wrong arities and Boolean or floating-point integers are invalid. Ordered lists remain immutable internally.'),
        code('OG-TAPE32-v1 codes: F,+,-,[,],R,S,SCALE = 0..7\nv = (a mod 256) + 2^8*floor(a/256) + 2^24*code\nword = v + 2^31*(popcount(v) mod 2)'),
        small('The separately tagged 32-bit instruction profile uses the sole tape argument a, or 0 when absent; scaling occurs in interpreter state. Decode a from bits 0..15 and code from 24..26; require bits 16..23 and 27..30 zero, even parity and terminal-specific bounds on device. One exact r32uint texel per instruction uses integer textureLoad in tape order, without filtering. This is not a current RP32 state or field sample. No instruction mirror is asserted: the same tape acts on full cursor pairs. Addresses and branch identities remain separate metadata.'),
        small('Source basis: original pp.4-5,7,10,12,16,18; Solus pp.3-4,6; solipsism pp.13,16. These motivate grammar, field-guided generation and branch context. The selected syntax, limits, ball union and interpreter are explicit numerical choices. Cone/pyramid primitives, general graph rewriting, global Psi and clock-wrap continuation remain separate obligations.')
    )
    page('Parameters, productions and finite tape', 'VERIFIED FINITE PROFILE | OG1-OG2 | SINGLE-VALUED EXPANSION',
        h('OG1. Parameters and exact predicates'),
        p('Parameters and literals are signed i32. An axiom argument is a literal or exactly {context,mul,add}, with context tick, epoch, phase or field. A rule RHS argument is a literal or exactly {arg,mul,add}, with arg a valid left-side parameter index. mul is -32768..32767; add is signed i32. Evaluate multiplication/addition as mathematical integers and reject a result outside signed i32 before device dispatch.'),
        eq('tick = original admitting GROW sequence\nepoch = next geometry epoch in 1..4\nphase = (-1)^eta * R mod 256; field = old B\naffine(x) = mul*x + add'),
        p('A standalone stage tick is a strict positive signed i32; the owner also requires its actual sequence within max_cycles. A comparison guard is exactly {arg,op,value}, op eq, ne, lt, le, gt or ge, with signed i32 value. An XOR guard is exactly {arg,op,mask,value}, op xor_eq, with strict u32 mask/value. Every guard arg is a strict valid left-side parameter index, never Boolean or out of range.'),
        eq('xor_eq(a,mask,value) iff\n((a mod 2^32) XOR mask) == value'),
        h('OG2. Parallel rewrite and permanent addresses'),
        p('Each generation reads only its previous word and arguments. For a nonterminal, select the first matching rule in list order; all guards must hold, and an empty guard list is true. An empty RHS erases that token. Unmatched symbols and terminals pass unchanged. New RHS tokens cannot be rewritten until the next generation. Each intermediate word, including the axiom, obeys max_symbols. Any nonterminal surviving the final generation rejects the stage.'),
        eq('axiom address = (i,)\nreplacement: append (generation,rule_index,rhs_index)\npass: append (generation,-1,0)'),
        p('Indices i, rule_index and rhs_index are zero-based; generations begin at 1. A pass address is appended for every passing token, including terminals. Final tape order retains {address,symbol,args}; addresses are flat integer arrays in serialized form.'),
        p('Before device work, preflight the complete tape. Brackets shall balance and every prefix depth is 0..max_stack; an initial POP is invalid. Track radius/scale with branch restoration. F takes n=1..256 and executes n*2^scale steps; + and - take m=1..16; R takes radius 1..127; SCALE sets absolute exponent 0..4. Each S emits radius*2^scale, at most 127. Total F steps obey max_steps and S count is 1..max_balls.'),
        small('Finite generations, words and interpreter work prove stage termination. There is no partial grammar GROW or grammar DEFER; agent planning still supports DEFER. Because DEFER advances the logical cycle, changing the manifest search quantum can change the original GROW tick and hence a time-conditioned production. Retain that manifest/input history; different search budgets need not yield the same mission. Cache and reindex operations do not advance T and must preserve results. XOR predicates do not replace parity, mirrors or geometric certification.')
    )
    page('Prior-field interpreter and branch context', 'VERIFIED FINITE PROFILE | OG3 | ORDERED PACKED EXECUTION',
        p('The complete stage uses its prior certified phi as a fixed waveguide. Begin at the actual repaired EMIT pair, changing only its opcode to STEP; local radius is 1 and scale is 0. Recompute parity and the full mirror whenever repacking. There is no independent heading state.'),
        h('OG3. Field-directed F and phase operators'),
        eq('t = (-1)^eta * R mod 256; bank = floor(t/64)\nd_i = gains[bank][i] * (1 + Psi_i^2)\nq = d Hadamard g; choose e maximizing dot(q,e)'),
        p('At every F substep, derive g and primitive Psi from the prior phi using PX, and q using HP. Choose among the four cardinal quotient edges. Break equal scores by the order [u+,v+,u-,v-] rotated left by bank positions. Apply the existing K8 departure-field-class increment and seam transport; destination B is the prior phi there. The updated intrinsic phase chooses the next lookup.'),
        p('Emit one segment after every F substep, retaining the terminal address, current branch path, 1-based substep and complete resulting STEP pair. Segments guide later placements; only S emits a boundary primitive. A +m or -m terminal applies respectively +m or -m times turns[class(prior phi at G)] through orientation-aware phase arithmetic modulo 256. It does not move the node.'),
        table(['Terminal','Interpretation effect'],[
            ['R(radius)','Set the unscaled local radius.'],
            ['SCALE(s)','Set absolute scale exponent s; semantic lengths multiply by 2^s. No destructive byte shift or global scale is implied.'],
            ['S','Emit centre G, effective scaled radius, current STEP pair, terminal address and branch path.'],
            ['[','Push complete cursor pair, radius, scale and enclosing branch path; append this PUSH terminal address to that path.'],
            [']','Restore exactly that saved context, including phase, orientation, field and complete mirror.'],
        ],[.23,.77]),
        h('What branch restoration does and does not restore'),
        p('Immutable tape arguments and the original stage context supply the rule environment. Program position, work counters, accumulated trace/segments/balls, owner energy and admitted history never rewind. Record a trace entry after every terminal, including PUSH and POP. The final hypothetical cursor does not replace the owner: OG5 admits the new field at the owner\'s unchanged node/phase/orientation.'),
        small('A saved orientation bit alone is not the complete frame. Restoration must recover the entire pair and local shape context even after a nested reversing-seam crossing, signed turn and local scale change.')
    )
    page('Intrinsic ball union and exact new field', 'VERIFIED FINITE PROFILE | OG4 | GEOMETRIC CONSTRUCTION',
        p('Every S emission declares an intrinsic ball on the unchanged unit-edge Klein quotient K. Let its canonical centre and positive integer radius be (c_i,r_i). The primitive list is ordered and retains duplicates; geometry is determined by its union potential.'),
        eq('q(v) = min_i [d_K(v,c_i) - r_i]\nsigma(v) = sign(q(v)); Z = {v : q(v)=0}\nphi_new(v) = sigma(v) * min_(z in Z) d_K(v,z)'),
        p('Reject a candidate with empty Z. Compute distance to the new zero set and apply the existing independent field certificate against the fixed graph and these signs. The union potential q is not generally the final signed distance: an individual ball boundary can become internal to the union. No old or per-ball distance may substitute for the certified result.'),
        h('Theorem OG-A: valid separating sides'),
        p('Each v -> d_K(v,c_i)-r_i is integer-valued and 1-Lipschitz on a unit edge. Their finite minimum is also 1-Lipschitz: choose a minimizing index at either endpoint and use its edge bound in each direction. Therefore adjacent q values differ by at most 1. Adjacent vertices cannot have opposite nonzero signs. Nonempty Z and the existing G1/G2 certificate then give exact signed boundary distance and its Lipschitz bound.'),
        h('Optional exact device metric'),
        eq('cyc_H(x) = min(x mod H, H-(x mod H))\nd_K((u,v),(a,b)) = min(\n  abs(u-a) + cyc_H(v-b),\n  W-abs(u-a) + cyc_H(v+b))'),
        p('Canonical representatives use 0..W-1 and 0..H-1. Lifts of (a,b) are (a+kW,(-1)^k*b+nH). Even horizontal lifts preserve the second coordinate; odd lifts reverse it. Their shortest horizontal displacements are abs(u-a) and W-abs(u-a). Independently minimizing vertical displacement over n gives the displayed formula. Independent BFS shall check it throughout the supported finite quotient domain before relying on this device construction.'),
        p('The original Klein cells, adjacency, cocycle and orientation-cover certificates stay unchanged. The new boundary, signs, exact field, PX descriptors and HP operator tables receive their own candidate certificates. The index anchor remains base.center. Reject any new distance outside the existing exact signed-code domain.'),
        small('These are intrinsic discrete balls and their union. The formula supplies no Euclidean sphere surface, cone, pyramid, continuum embedding or calibrated physical unit. Different stage fields genuinely change the represented internal distance rules while retaining the same quotient topology.')
    )
    page('The same individual admits a generated world', 'VERIFIED FINITE PROFILE | OG5 | SUBGOAL, TARGET AND ENERGY',
        p('The initial KleinFieldRecipe remains immutable. The new policy manifest includes organogram and the existing Hadamard routing binding. After REPAIR, if the current epoch k is below max_epochs, enter GROWTH_PENDING. The next complete fresh local observation frame admits one GROW transition; observations cannot supply productions, primitive centres, targets or actions.'),
        eq('reserve(k) = repair_cost\n           + (max_epochs-k)*(organogram.cost+repair_cost)'),
        p('Apply the existing GD reserve/admission bounds using organogram.cost. MOVE and REPAIR must preserve the required remaining reserve. GROW requires its cost plus reserve(k+1), consumes one global cycle, and debits its cost exactly once. Global cycle, energy and event order never reset. With max_epochs=0 the initial mission finishes without a grammar stage.'),
        h('OG5. Admit the field, not the hypothetical cursor'),
        eq('G_new = G_old; R_new = R_old; eta_new = eta_old\nB_new = certified phi_new(G_old)\nopcode_new = STEP; energy_new = energy_old-cost'),
        p('Recompute complete mirror/parity and validate this result against the candidate field. Clear effective observations, pending search and active FIFO after successful semantic admission. Retain baseline, manifest and admitted history. Final REPAIR at max_epochs completes the finite mission.'),
        h('State-selected next target'),
        eq('C0 = all canonical nodes except owner G\nC1 = argmin_(v in C0) abs(phi_new(v))\nC2 = argmax_(v in C1) unweighted_hops(G,v)\ntarget = sorted_numeric(C2)[intrinsic_phase mod len(C2)]'),
        p('The topology is unchanged, so this rule uses no born-node condition. Tie-breaking is by numeric canonical G, not lexical name order. Full mirrors have the same intrinsic phase and select the same target. The new target is internal policy state; subsequent planning and actions use the certified new field and HP routing.'),
        p('Observations and retries retain GD epoch semantics: new input must name the current pre-cycle geometry epoch and satisfy its locality; a duplicate original producer sequence resolves in its original geometry and returns its original result. Simulator hazards remain an explicitly selected input model. Arbitrary admitted local live hazards remain possible.'),
        small('Cost is an abstract mission-resource unit, not measured physical energy or interpreter work; F steps have a separate bound. Reindex preserves semantic field, target, observations, search and identities; GROW invalidates their context. A successful integration shall demonstrate changed distances and autonomous behavior, not only a detached tape.')
    )
    page('Original recipes, transcripts and replay', 'VERIFIED FINITE PROFILE | OG6 | COMPLETE DERIVATION CONTEXT',
        code('recipe = {format,base,organogram,routing,stages}\nformat = "klein-organogram-world-v1"\nstage = {epoch,tick,start_pair,prefix_sha256}'),
        p('base is the original KleinFieldRecipe; organogram and routing retain the immutable bindings. A generated recipe has 1..max_epochs stages; epoch 0 uses the base type. Stage epoch is 1..length, ticks strictly increase, and start_pair is the original full EMIT pair as 16 uppercase hex characters. Require valid parity/mirror, legal node and B equal to the preceding field. Reconstruct preceding stages before the next; never substitute current time or recipe.'),
        eq('stage.prefix_sha256 = SHA256(canonical(events before GROW))\ncanonical(x) = json.dumps(x, sort_keys=True,\n  separators=(\',\',\':\'), ensure_ascii=True,\n  allow_nan=False).encode(\'utf-8\')'),
        p('No trailing newline; digests are 64 lowercase hex characters. Excluding this GROW avoids a circular digest through its receipt. A digest binds retained context, not authentication or a spatial seed. Grammar reads no energy or sensor arguments; these remain in the journal. Historical samples separately hash through their original admitted GROW under GD7, permit only admitted epochs, and retain full base, grammar and original context.'),
        h('OG6. Canonical derivation document'),
        code('derivation = {format,context,tape,trace,segments,balls,\n              final_context}\nformat = "klein-organogram-derivation-v1"'),
        table(['Record','Exact keys and meaning'],[
            ['context / tape','context is the stage. Each tape item is {address,symbol,args}; addresses are flat integer arrays.'],
            ['trace','After every terminal: {address,branch_path,pair,radius,scale}. radius is unscaled.'],
            ['segments','{address,branch_path,step,pair}; step is 1-based within this F terminal\'s effective steps.'],
            ['balls','{address,branch_path,center,radius,pair}; center is numeric G and radius is the effective scaled radius.'],
            ['final_context','{branch_path,pair,radius,scale}; final branch_path is empty.'],
        ],[.24,.76]),
        small('branch_path is an outermost-first array of PUSH terminal addresses. Every transcript pair is the current prior-field STEP pair, encoded as 16 uppercase hex characters. Hash the complete document with the canonical encoding above. Schema, ordering and numeric/string types are part of the digest contract. Event/receipt and snapshot schemas continue on page 64.')
    )
    page('Device production and atomic admission', 'VERIFIED FINITE PROFILE | OG6-OG7 | REFINEMENT AND RESOURCE OWNERSHIP',
        h('OG6. Event, receipt and snapshot schema'),
        code('event = {seq,input,decision,output,energy,\n         geometry_epoch,growth}\nreceipt = {format,from_epoch,to_epoch,mapped_node,\n           target,recipe,derivation_sha256}'),
        p('geometry_epoch is the pre-cycle epoch; growth is null except on GROW. Receipt format is klein-organogram-growth-v1 and mapped_node is the unchanged canonical owner name. derivation_sha256 hashes OG6\'s complete document. The OG snapshot adds geometry_epoch and current_recipe; unlike GD it has no global scale_exponent because branches may use different local scales.'),
        h('OG7. Produce on device, then certify'),
        p('The host parses, expands and preflights immutable tapes for all stages before even base GPU allocation, using their declared contexts. This is host work, not proof that declared B matches the actual preceding field; verify that later per stage. The device derives every cursor/branch state and primitive from tape and prior device phi, then signs and distances. Rebuild PX/HP from the new device field.'),
        p('Independent certificates validate actual outputs; they shall not replace device trajectories, fields, indexes or routing tables with CPU-produced results. Construction and validation shall use the certified device manifest path without an eager recipe property silently invoking a host field producer. Explicit GPU operation permits no CPU fallback.'),
        p('Candidate admit_generated reads actual old device pair/energy. Require exactly one added stage and identical base, grammar and routing; for a first stage compare the owner\'s immutable binding. Match actual start_pair and the owner\'s pre-event prefix; coincident fields do not prove history. Compute OG5 state without a host seed after initialization and check every candidate output before serialized swap.'),
        table(['Outcome','Required ownership result'],[
            ['Pure precommit rejection','Preserve old world, pair, energy, observations, search, FIFO and archive; dispose the detached candidate.'],
            ['Uncertain device work','Close affected candidate and owner conservatively; retain the last admitted history, without fabricated success.'],
            ['Certified swap','Admit one GROW, install field/target/state, debit once and clear the prescribed semantic context.'],
            ['Committed cleanup failure','Preserve the admitted event, report committed=True and close the owner. Durable reopen/retry resolves saved state.'],
        ],[.29,.71]),
        small('Valid productions may yield an empty boundary or other rejected field; arbitrary grammar and finite energy/cycles do not guarantee GROW completion. Account old plus candidate host/device payloads, tapes, stacks, traces, recipes, journal and cache separately, including rejected complete-candidate peaks. The pair FIFO bound of 8C bytes is not total constant memory.')
    )
    page('Independent organogram reference', 'FORMAL-FIRST REFERENCE | OG8 | EXPECTED RESULTS BEFORE RUNTIME',
        p('The independent reference in docs/evidence/organogram-v1/ expands the grammar and evaluates integer branches, quotient BFS, union redistance and lifted HP planning without importing solvefinite. A layered dynamic-programming oracle cross-checks its mission paths. These are mathematical expected results, not runtime conformance.'),
        h('Standalone context and branch restoration'),
        p('The retained standalone input names epoch 1, original tick 5 and repaired pair 06011145160111BB. Its explicit prefix is the digest of []; this mathematical input is not a claim that a runtime admitted sequence 5 with an empty journal. Production addresses, traces, branch paths and the complete derivation document remain in the reference.'),
        table(['Nested branch moment','Exact current context'],[
            ['Before first POP','91FE00B181FE004F; radius 2, scale 1, eta 0. Nested F visits 12,11,10,15,0 across the reversing seam.'],
            ['After first POP','81020C5791020CA9; radius 1, scale 0, eta 1; enclosing branch path restored. Emitted balls are (12,1), (0,2), (2,1).'],
        ],[.29,.71]),
        p('The retained default grammar mission expects 9 cycles, energy 76 and final pair 860006BA16000646 at target 6. Two epochs expect 14 cycles, energy 66 and pair 06000E2F16000ED1; successive targets are 6 and 14. These predictions use the full fixture inputs retained with the reference.'),
        h('Union potential is not signed boundary distance'),
        eq('3 by 3 quotient; balls (centre,radius) = (0,2),(4,2)\nq   = [-2,-1,-1,-1,-2,-1,-1,-1,0]\nphi = [-2,-1,-2,-2,-2,-1,-1,-1,0]\nZ = {8}; q and phi differ at canonical nodes 2 and 3'),
        p('Both fields encode the same side classification, but only the recomputed phi is exact distance to the union boundary. This literal case detects an implementation that substitutes min per-ball residual for the required redistance.'),
        h('Exact instruction-carrier vectors'),
        code('F(256) 80000100   +(16) 01000010   -(16) 02000010\n[      03000000   ]     84000000   R(127) 8500007F\nS      06000000   SCALE(4) 07000004'),
        small('Independent BFS checks all 702 supported quotients, 106,045 vertices and 19,130,481 ordered pairs against the closed metric. The builder pins reference and generator hashes. Mathematical mission prefixes are scoped to that transcript, not runtime canonical archive hashes; actual journal/source identities require separate evidence.')
    )
    page('Organogram acceptance obligations', 'VERIFIED FINITE PROFILE | OG8 | REQUIRED ACCEPTANCE SCOPE',
        p('The retained reference in docs/evidence/organogram-v1/ supplies independent grammar expansion, integer interpretation and geometric calculations without importing solvefinite. Its vectors are mathematical expectations prepared before runtime implementation; a separate source-bound CPU/GPU capture must demonstrate refinement.'),
        h('OG8. Required acceptance evidence'),
        table(['Object','Required scope'],[
            ['Grammar and bounds','Rule priority, guard conjunction and XOR, erasure, passing terminals, unmatched final symbols, affine overflow, malformed schema, nesting and every declared size/work limit.'],
            ['Complete branch frame','Nested reversing-seam crossings and signed turns with radius/scale changes; exact POP restoration of full pair and context. Trace/counters/emissions continue without rewind.'],
            ['Geometric truth','Closed-metric/BFS agreement over supported quotients; union potential versus true-distance counterexample; empty-boundary rejection; independent certificate for generated fields.'],
            ['Context and identity','Original tick and pre-GROW prefix, immutable stages, canonical transcript digest, full mirrors, original-epoch retries and admitted historical regeneration.'],
            ['Same individual','A changed generated field changes routes/actions; multi-epoch continuation retains energy/cycles/history; target selection and reserve bounds agree independently.'],
            ['Device refinement','Actual GPU interpreter, traces, balls, signs, fields and subsequent actions; host producers/compilers disabled on explicit GPU paths; fresh-process cross-backend replay.'],
            ['Atomicity and retention','Pure rejection, uncertain dispatch/readback, committed cleanup and save/reopen boundaries; cache/reindex/planner-DEFER preservation; unchanged earlier-policy hashes.'],
        ],[.25,.75]),
        box('Revision 10 status: VERIFIED FINITE PROFILE. The separate implementation capture passes the required finite acceptance scope: 623 tests, 136 actual-device methods and 15 conformance checks. Measured results and limits follow on pages 67-68.'),
        small('This finite organogram does not complete cone/pyramid or arbitrary graph production, global eigenmodes, WElip/clock-wrap continuation, physical adapters, computational universality or comparative hardware performance. Completing OG must be judged against the full contract, not only literal reference examples.')
    )
    page('Measured organogram continuation', 'IMPLEMENTATION CAPTURE | OG1-OG8 | 26 SEPTEMBER 2026',
        p('The grammar now generates a new exact signed boundary field on the original Klein topology. The same Tomigidt admits it, keeps its actual node/phase/orientation and energy history, derives a new target and continues. The independent expectations on page 65 preceded implementation at formal commit 5c76f2c.'),
        table(['Measurement','Retained observed result'],[
            ['Complete regression',f'{og_tests} tests passed in {OG_VERIFICATION["tests"]["elapsed_seconds"]:.3f} s; zero skipped. {og_device_tests} actual-device methods include 29 OG methods.'],
            ['Independent conformance',f'All {og_checks} checks passed; capture wall time {OG_VERIFICATION["conformance_elapsed_seconds"]:.3f} s. Full stage tapes, traces, branch paths, balls, fields and digests agree with the independent reference at original runtime context.'],
            ['Adapter','NVIDIA GeForce RTX 5070 Ti Laptop GPU; Vulkan; driver 591.59; wgpu 0.32.0; Python 3.12.14.'],
        ],[.29,.71]),
        h('Measured missions agree across CPU and actual GPU'),
        table(['Fixture','Cycles / final energy','Final pair'],[
            ['Default; target 6','9 / 76','860006BA16000646'],
            ['Full mirror; target 6','9 / 76',OG_CONFORMANCE['GPU']['mirrored_default']['archive']['expected']['agent_pair']],
            ['Two epochs; targets 6,14','14 / 66','06000E2F16000ED1'],
            ['Zero epochs; initial target','4 / 86','06011145160111BB'],
        ],[.35,.26,.39]),
        p('With search quantum 7, DEFER advances original time: GROW occurs at sequence 8 and the mission completes in 17 cycles with energy 74. Different original ticks select different productions. Under the same quantum and admitted inputs, cache churn, reindex and CPU/GPU continuation preserve the complete canonical history.'),
        h('Canonical default runtime archive SHA-256'),
        code('e2834ba2cc6b4d51f2b23f274cd9f2a0db8\na4e88754ed9d2aadc76c074f134df'),
        small('Join the displayed hash lines. The runtime stage-1 derivation digest is 30f0164177a5e289cb9e7b7e244960c4bef49bcc444208cb94c618295a0c2aa3. It differs from the standalone page-65 digest because it binds the actual pre-GROW journal prefix. Timing here measures correctness capture, not comparative hardware performance.'),
        box('Evidence supports the declared finite OG profile. It does not establish general universality, texture-cache saturation, physical-energy advantage or indefinite autonomous continuation.')
    )
    page('Organogram device and retention evidence', 'IMPLEMENTATION CAPTURE | DEVICE WORK, FAILURE AND RESOURCE SCOPE',
        p('The GPU reads OG-TAPE32 instructions from an integer texture, interprets branch state, emits balls, derives signs, reconstructs exact field distances and supplies subsequent packed actions. Host work performs strict parsing, bounded expansion, independent certification, route search and admission. Six OG producers and eleven earlier CPU compilers are disabled on the guarded GPU paths; the owner is never host-reseeded after initialization.'),
        h('Boundary and continuation evidence'),
        p('Coverage includes 32 nested branches and 4,096 actual F substeps; nested seam/radius/scale restoration; the literal union-redistance counterexample; and an unbranched F(1),S case whose hypothetical cursor leaves the actual owner. Rejection probes cover malformed/over-budget grammar, empty boundary, forged certificates and mismatched original context.'),
        p('Pure precommit rejection preserves the old owner. Uncertain device failure closes it without admission; committed cleanup failure retains GROW. Save failures on either side of replacement, original-epoch retries and durable reopen are exercised. Six fresh-process CPU/GPU crossovers cover before GROW, after GROW and generated-world DEFER. Earlier FI/HP/GD archive hashes remain unchanged.'),
        h('Explicit payloads for the default CLI continuation'),
        table(['Payload','Observed bytes / interpretation'],[
            ['Current device',f'{og_allocation["device_payload_bytes"]:,} = {og_allocation["device_buffer_bytes"]:,} buffers + {og_allocation["device_texture_bytes"]:,} textures.'],
            ['GROW preparation peak',f'{og_peak["device_payload_bytes"]:,} device bytes, including old and candidate bundles plus grammar work. Instruction texture {og_peak["instruction_texture_bytes"]:,}; movement texture {og_peak["grammar_movement_texture_bytes"]:,}; grammar scratch {og_peak["grammar_scratch_buffer_bytes"]:,}.'],
            ['Shader / retained grammar',f'Private branch stack {og_peak["grammar_private_stack_payload_bytes"]:,} logical bytes; retained grammar recipe {og_peak["grammar_retained_recipe_bytes"]:,}; transcript {og_peak["grammar_retained_transcript_bytes"]:,}. Peak host stage payload {og_peak["peak_grammar_host_stage_payload_bytes"]:,}.'],
            ['Separate active FIFO',f'{og_peak["active_fifo_pair_bytes"]:,} pair bytes for CLI capacity 2. Current host index {og_allocation["host_index_payload_bytes"]:,}; routing table {og_allocation["host_routing_table_payload_bytes"]:,}; field codes {og_allocation["host_field_code_payload_bytes"]:,}.'],
        ],[.31,.69]),
        small('Logical private-stack bytes do not identify physical GPU residency. Payload accounting excludes Python objects and driver overhead; geometry, observations, planning and journals remain additional. Preparation/rebuild peaks are distinct. The sample FIFO does not bound total memory.'),
        h('Recheck execution and rebuild this retained edition'),
        code('python -m unittest discover -s tests -v\npython -m examples.organogram_conformance --output og-recheck.json\npython tools/build_formal_spec.py'),
        small('Historical capture f125a76: docs/evidence/organogram-v1/ retains verification.json, full-tests.txt, conformance.json and cli-replay.json. The builder checks that commit\'s source inventory/hashes, retained reports, chronology, reference, device counts and archives. Rechecking another checkout does not reproduce these historical counts. Remaining work at that capture includes general primitives/graphs, global spectral choices, WElip/clock continuation, physical adapters and comparative hardware measurements.')
    )
    build_w_content()


def build_w_content():
    page('WElip forward-time binding', 'APPENDIX MAP | W1-W8 | VERIFIED FINITE PROFILE',
        box('Revision 11 bound W1-W8 before implementation at 74e00f4. Revision 12 preserves those numerical definitions and adds the source-bound CPU/GPU capture on pages 82-83. Independent reference vectors remain mathematical expectations; prior FI/PX/HP/GD/OG evidence retains its original scope.'),
        p('One separate W public interface owns the same existing Tomigidt field agent. It supports FI, HP, GD and OG, defaults to OG and preserves their numerical semantics and canonical agent archives. The five forward operations add an explicit clock, lifecycle, typed record and durable admission boundary around that individual.'),
        table(['Page','Complete section'],[
            ['<link href="#p70" color="#007D83">70</link>','W1-W2: immutable configuration, clock and request context'],
            ['<link href="#p71" color="#007D83">71</link>','W3: ignition, advancement and local lifecycle operations'],
            ['<link href="#p72" color="#007D83">72</link>','W4: forward admission and latest-request retry'],
            ['<link href="#p73" color="#007D83">73</link>','W5: exact 16+16+32 carrier and state decoding'],
            ['<link href="#p74" color="#007D83">74</link>','W5: LUS envelope, identity and separate energy'],
            ['<link href="#p75" color="#007D83">75</link>','W6: ownership, private archive and cache witnesses'],
            ['<link href="#p76" color="#007D83">76</link>','W6: internal R recovery and whole-operation atomicity'],
            ['<link href="#p77" color="#007D83">77</link>','W7: actual GPU state emission and failure handling'],
            ['<link href="#p78" color="#007D83">78</link>','W8: JSONL transport and complete response schemas'],
            ['<link href="#p79" color="#007D83">79</link>','W8: validation order and exact error classes'],
            ['<link href="#p80" color="#007D83">80</link>','Independent preimplementation W reference vectors'],
            ['<link href="#p81" color="#007D83">81</link><br/><link href="#p82" color="#007D83">82</link> / <link href="#p83" color="#007D83">83</link>','W8 acceptance obligations; measured implementation and recovery evidence'],
        ],[.12,.88]),
        h('Source authority and new numerical choices'),
        p('Original p.4 requires retained output-affecting inputs and clock epochs; p.8 identifies the WElip 16+16+32 carrier; p.14 separates record identity, integrity, admission and reproduction; p.15 defines the five-event forward alphabet, local invalidation and controlled R/W separation. The exact schemas, finite bounds, codec, clock cadence and retry protocol below are declared realization choices.'),
        small('All old policies, live sessions and CLI commands retain their meanings. W is an API/profile boundary, not OS isolation or issuer authentication. Its finite clock and retained ledger do not establish indefinite time or constant total memory.')
    )
    page('W configuration and independent clocks', 'FINITE CONTRACT | W1-W2 | STRICT INPUT AND TIME DOMAINS',
        code('protocol = "welip-field-agent-v1"\nconfig = {format,agent,producer,producer_epoch,\n          clock_origin,max_events,initial_capacity}\nformat = "welip-field-config-v1"'),
        table(['Field','Exact binding'],[
            ['agent','Existing FieldAgentManifest schema, with one of the four policies listed below; default OG.'],
            ['producer','Strict string equal to its trimmed form, nonempty, at most 128 characters; default sensor.'],
            ['producer_epoch','Strict u32; default 0. Producer namespace, distinct from clock carry.'],
            ['clock_origin','Strict unsigned 48-bit integer; default 0.'],
            ['max_events','Strict integer 1..1,000,000; default 1,000,000.'],
            ['initial_capacity','Strict integer 1..256 complete pairs; default 2.'],
        ],[.25,.75]),
        p('Before owner/device allocation require clock_origin + max_events &lt;= 2^48 - 1. No Boolean or float integer coercion, unknown keys or malformed nested JSON is permitted. CLI profile selectors and full agent policies are:'),
        code('field      tomigidt-field-observe-plan-act-v1\nhadamard   tomigidt-field-hadamard-plan-act-v1\ngrowth     tomigidt-field-growth-plan-act-v1\norganogram tomigidt-field-organogram-plan-act-v1'),
        h('W2. Four distinct clocks and counters'),
        code('n = durably admitted W operations, initially 0\nT_W = clock_origin + n\nclock_epoch = T_W >> 16; tick16 = T_W & 65535'),
        p('Each new operation, including IGNITE and EMIT, advances n and T_W exactly once. Only ADVANCE increments agent.cycle; geometry_epoch remains the existing semantic generation. The device action counter is separate again. W operations never reset energy, agent history or OG\'s original GROW cycle, time or prefix. Records from one operation share T_W and use contiguous record_seq starting at 0. There is no epoch reuse or operation-sequence rollover.'),
        h('Every request: exact common keys'),
        code('{protocol,op,producer,producer_epoch,seq,clock_epoch,\n tick16,agent_cycle,geometry_epoch}'),
        p('Add only page 71\'s operation fields. seq is 1..max_events+1; a new operation requires seq=n+1 and clock=clock_origin+seq. clock_epoch is u32; tick16 is u16; agent_cycle is 0..agent.max_cycles; geometry_epoch is 0..policy.max_epochs, or 0 for FI/HP. Cycle/generation describe the current preoperation owner and are both 0 for initial IGNITE. At n=max_events only exact latest retry is allowed. Static schema/source checks precede retry classification; current-state checks follow it.')
    )
    page('The five forward operations', 'FINITE CONTRACT | W3 | ONE OWNER, EXPLICIT LOCAL EFFECTS',
        h('IGNITE: add {payload}'),
        p('payload is uppercase, even-length hexadecimal encoding 0..4,096 bytes. Only seq=1 before ignition is valid. Retain those literal bytes with the configured baseline and initial owner clock/phase context. They do not replace the initial RP32 state or become instructions. Emit raw payload record 0 followed by actual owner-state record 1. Empty payload still emits record 0 with zero fragments.'),
        h('ADVANCE: add {position,observations}'),
        p('Require prior ignition, an open owner below its cycle bound and status other than COMPLETE. WAITING, SEARCH_DEFERRED, UNREACHABLE, INSUFFICIENT_ENERGY and GROWTH_PENDING may admit fresh observations. position is the current canonical path. observations contains only currently visible local paths and strict integer hazards 0..127. Incomplete frames retain existing WAITING semantics.'),
        p('Delegate exactly one existing Tomigidt.step; the agent chooses its action. Preserve each FI/HP/GD/OG policy\'s fresh-frame, energy reserve, GROW and DEFER contracts. Emit actual postoperation owner-state record 0.'),
        h('RESIZE: add {capacity}'),
        p('capacity is a strict integer 1..256 pairs. Set the active FIFO capacity and evict oldest entries until it fits, preserving unaffected order. Identical capacity is a valid new operation. Emit actual owner-state record 0 without an agent step or energy debit.'),
        h('INVALIDATE: add {paths,cause}'),
        p('paths is a sorted, unique list of 1..256 canonical paths, all currently active at the request\'s current geometry epoch. cause is a nonempty string equal to its trimmed form, at most 128 characters. Validate the entire selector before removal. Remove complete DATA pairs and preserve unaffected FIFO order. Append removed paths to the eviction diagnostic in original FIFO order so a later get() records regeneration.'),
        p('Retain baseline, recipes, field/index/routing, observations, pending search, owner pair, energy and admitted history. Retain cause in the W request; emit actual owner-state record 0. This is the bound local invalidation action, with no automatic invalidation for a rejected read.'),
        h('EMIT: no additional fields'),
        p('Emit actual current owner-state record 0 and advance W time, without an agent step, energy debit or cache access. After agent COMPLETE, EMIT/RESIZE/INVALIDATE remain available within the W budget; ADVANCE and a new IGNITE reject. Before IGNITE every other operation rejects. Every operation uses the same owner; cache controls never spawn or reseed it.')
    )
    page('Forward boundary and latest retry', 'FINITE CONTRACT | W4 | NO PUBLIC HISTORICAL PAYLOAD',
        h('Explicit public alphabet and reverse-lock predicate'),
        p('Only IGNITE, ADVANCE, RESIZE, INVALIDATE and EMIT are public W operations. Explicit op names READ, HISTORY, REPLAY and REGENERATE reject as BACKWARD_READ. Other names and extra selectors are invalid requests. There is no public historical archive, derive_epoch, legacy inspect/status or raw-owner accessor through W. Ready/next admission metadata is transport context, not another W operation.'),
        box('Detection is explicit at this interface. Rejected requests leave admitted clock, history and cache unchanged. They do not automatically invalidate memory, change parity or authenticate the producer. Controlled private R recovery is defined on page 76.'),
        h('Exact latest retry precedes dynamic context checks'),
        p('Only the most recent durably admitted sequence n&gt;0 may be retried. Compare the complete request with the retained latest request using canonical JSON bytes: sorted keys, compact separators, ensure_ascii=True and finite values. Static shapes/ranges and source identity are checked first. Exact equality is checked before current position, generation, active membership, budget or terminal tests, because successful admission may already have changed them.'),
        table(['Request relation','Required result'],[
            ['seq=n; exact bytes','DUPLICATE, containing current admission cursor and seq only beyond the common response keys.'],
            ['seq=n; changed bytes','CONFLICT. Do not reinterpret it against the new owner context.'],
            ['seq&lt;n','STALE_SEQUENCE without fetching historical payloads.'],
            ['seq&gt;n+1','SEQUENCE_GAP. seq=0 is always invalid.'],
            ['seq=n+1','Apply the new-operation admission order on page 79.'],
        ],[.32,.68]),
        p('A duplicate returns no records, old event, packed pair, energy or old cache payload. It does not step, dispatch device emission, mutate cache/clock or write the archive. Current admission names in next remain transport metadata, with no past fields or pairs.'),
        h('Acknowledgment loss and delivery meaning'),
        p('A lost current-state observation can be replaced by a new forward EMIT at a new clock. This is not recovery of the old record. EMIT does not reproduce IGNITE\'s raw bytes: lost raw ignition output has no public recovery operation, although admitted bytes remain available to private R. No physical exactly-once actuation is implied.')
    )
    page('WElip carrier and exact state decoding', 'FINITE CONTRACT | W5 | TYPED 16+16+32 WORDS',
        code('word_profile = "welip-16-16-32-v1"'),
        eq('W64 = payload32 | (phase16 << 32) | (tick16 << 48)\nphase16 = intrinsic_phase8 << 8\nintrinsic_phase8 = (-R if eta else R) mod 256'),
        p('All integer fields are strict. Canonical transport words contain exactly 16 uppercase hexadecimal digits. tick16 and phase16 are unsigned 16-bit values; payload32 is unsigned 32-bit. State phase has zero low eight bits: it represents the same angle in 1/65,536-turn units at the existing 8-bit resolution. This binding introduces no additional phase precision.'),
        h('Raw bytes and finite fragmentation'),
        p('For byte length L in 0..4,096, split bytes into consecutive four-byte little-endian chunks, zero-padding the final chunk. fragment_count=(L+3)//4; words contains exactly that many W64 values in original order. Empty L has words=[]. Decode exactly L bytes; never infer length by deleting zero padding.'),
        p('Reject malformed word syntax or range, wrong tick/phase headers, count mismatch or nonzero final padding. The original bytes, including meaningful trailing zeros, must round-trip. Raw IGNITE bytes carry no RP32 semantics or implied parity/integrity.'),
        h('Owner pair byte order and validation'),
        code('state bytes = LE32(left_RP32) || LE32(full_mirror_RP32)\nstate byte_length = 8; fragment_count = 2'),
        p('The pair display convention puts its high word first; payload encoding instead writes the left u32 little-endian, then the full-mirror u32 little-endian. Do not confuse printed pair order with byte order. Each W word carries one of those u32 payloads with the same tick/phase header.'),
        p('State decoding additionally verifies each RP32 parity, the full mirror relation, legal STEP or EMIT metadata and agreement of the phase header with the left owner channel. Admission requires exact equality of the full owned pair, including orientation/opcode, plus energy and context. Mirror-swapping channels yields a different owned pair even when the representation remains legal.'),
        box('Word ordering and parity are representation checks. Coordinated payload changes can create another legal record; actual owner/context equality is a separate admission check. Neither the carrier nor a hash supplies issuer authentication or a spatial seed.')
    )
    page('LUS envelope and derivation identity', 'FINITE CONTRACT | W5 | COMPLETE RECORD SCHEMA',
        code('record = {format,word_profile,payload_profile,baseline_id,\n producer,producer_epoch,clock_epoch,tick16,phase16,\n operation_seq,record_seq,kind,agent_cycle,geometry_epoch,\n energy,byte_length,fragment_count,words,status}\nformat = "welip-lus-v1"'),
        table(['Field group','Exact domain and meaning'],[
            ['Profiles','word_profile is welip-16-16-32-v1. payload_profile is bytes-v1 or RP32-relational-sdf-v2.'],
            ['Baseline / producer','baseline_id is the immutable initial agent.world.baseline_id, using its existing recipe schema. producer and producer_epoch retain the W configuration bounds.'],
            ['Time / record order','clock_epoch:u32; tick16/phase16:u16; operation_seq:1..max_events; record_seq:0..1.'],
            ['Owner context','agent_cycle:0..agent.max_cycles; geometry_epoch:0..policy max_epochs, or 0 for FI/HP.'],
            ['Separate energy','Actual postoperation owner energy, strict integer 0..2^31-1. Explicit metadata; never hidden in SDF B or W64 padding.'],
            ['Kind / status','kind is the admitted operation name. status is exactly ADMITTED.'],
            ['Payload','byte_length:0..4,096; fragment_count=(L+3)//4; ordered words as page 73. State is exactly 8 bytes / 2 words.'],
        ],[.24,.76]),
        p('Every key, type and profile must be exact. IGNITE has bytes-v1 record 0 and state record 1; each other operation has only state record 0. All records carry the postoperation agent cycle/generation, actual energy, the same W time and actual intrinsic phase. Raw ignition therefore shares the initial owner context without becoming agent instructions.'),
        h('Identity under the retained configuration'),
        eq('ID = (enclosing profile, baseline, producer, producer_epoch,\n      clock_epoch, tick16, operation_seq, record_seq)'),
        p('This identity is interpreted under the fixed retained configuration and original ignition input. Producer namespace allocation is a declared responsibility, not a theorem of global uniqueness. Retain literal original inputs; no hash seeds phase. Equality of identity, equality of bytes, successful private reproduction, representation integrity and origin/admission are separate claims.'),
        small('The 64-bit carrier does not contain the whole envelope. Finite ordered uniform words carry payload fragments; explicit surrounding metadata carries the full clock epoch, energy, profiles, byte length and derivation identity.')
    )
    page('Durable W ownership and archive', 'FINITE CONTRACT | W6 | COMPLETE PRIVATE STATE',
        h('One protected path and serialized owner'),
        p('Acquire canonical-path OS StateLock, then the session RLock, then existing Tomigidt operation and cache/device locks in that order. Hold admission, execution, save and result construction inside one ownership boundary. Opening a new file binds configuration and creates the existing agent without implicitly igniting it. Persist genesis with an empty W ledger.'),
        p('Initial capacity belongs to configuration. Reopen rejects supplied configuration mismatch or a constructor capacity override. Recover the mutable current capacity by replaying retained RESIZE operations from initial_capacity; current capacity may legitimately differ from that initial value. Backend and storage index binding may change on reopen, preserving admitted semantics.'),
        h('Exact archive and operation row'),
        code('archive = {format,config,operations,agent,expected}\nformat = "welip-field-session-v1"\nrow = {request,records,agent_pair,energy,status,cache}\ncache = {capacity,active_paths,hit_count,regeneration_count,\n         evicted_count,removed}\nexpected = {seq,clock_epoch,tick16,ignited,cache}'),
        p('agent is the unchanged canonical agent archive. operations is the ordered private W ledger with at most max_events rows. agent_pair is exactly 16 uppercase hexadecimal digits in the existing pair display convention. Row energy and status equal the actual owner energy and mission status; row status is distinct from the record status ADMITTED.'),
        h('Cache witnesses and local lifecycle'),
        p('active_paths contains unique canonical names in FIFO order, bounded by capacity. The three counters are strict nonnegative integers. removed lists explicit RESIZE/INVALIDATE removals in original FIFO order. Other operations use removed=[]; their ordinary sample evictions remain diagnostics. Final expected.cache always has removed=[], because it witnesses current state rather than repeating the last removal receipt.'),
        table(['State','Required witness'],[
            ['Genesis','seq=0; clock=clock_origin; ignited=false; capacity=initial_capacity; active_paths=[]; all three counters 0; removed=[].'],
            ['GROW','Install the existing fresh FieldWorld: preserve capacity, reset active entries, counters and eviction history. Earlier W ledger rows remain retained.'],
            ['Reopen','Replay lifecycle in original order and verify every cache witness, including capacity and current FIFO order.'],
        ],[.2,.8]),
        small('Archive parsing validates all exact types/shapes and bounds. Baselines, recipe inputs, private records, observations, planner state and journal are additional to the active pair FIFO; this profile makes no total constant-memory claim.')
    )
    page('Private recovery and operation atomicity', 'FINITE CONTRACT | W6 | DURABLE COMMIT AND FAILURE SCOPE',
        h('Controlled internal R behind the W boundary'),
        p('Recreate the same agent at initial capacity and replay W operations in order, interleaving original ADVANCE observations with RESIZE and INVALIDATE. Verify every resulting record, owner state and cache witness, then the complete final canonical agent archive and expected W context. Restoring only the agent archive at final capacity is insufficient.'),
        p('Recovery may recompute on CPU or actual GPU. It emits no public records, receipts or new durable operations. Device computation may repeat; physical exactly-once actuation is not claimed. No eager historical packed-world arena or public old-epoch read is introduced. Original agent-cycle time and GROW prefixes remain unchanged by intervening W operations.'),
        h('Commit before acknowledgment'),
        p('Compute the operation result and next archive, then call atomic write_json before acknowledging. Its payload flush/fsync and replacement semantics apply; this is not a guarantee against every hardware or power failure. A successful durable admission consumes one W sequence/time. Lost transport acknowledgment is resolved by exact latest retry without executing that operation again.'),
        table(['Failure boundary','Required outcome'],[
            ['Pure validation / rejected output','Remain usable only when the entire admitted semantic W preoperation state is proven unchanged.'],
            ['After ADVANCE/GROW or cache mutation','Emission failure poisons the owner unless complete preoperation restoration is proven.'],
            ['Save failure or uncertain replacement','Close/poison; no acknowledgment. A new owner consults disk to determine the durable prefix.'],
            ['In-memory action before replacement','Reopen from the prior durable prefix. Unwritten state is not a durably admitted operation.'],
            ['Committed GROW cleanup failure','Preserve existing internal GROW semantics; close the affected owner. Never acknowledge an unsaved W event.'],
            ['After successful save; transport lost','Latest retry returns only the receipt/current cursor, with no action or emission dispatch.'],
        ],[.32,.68]),
        p('The admitted semantic prestate includes all owner state: pair, energy, cycle, history, recipe, generation, target, decision, planning and observations; cache order/counters; W clock/ledger and configuration. Ephemeral emission scratch bytes are excluded. Emission may be validated before mutating a cache control. Unchanged GPU state across emission alone does not prove a preceding ADVANCE was unchanged.'),
        small('Unexpected postmutation failure closes the owner. Closed/poisoned embedded owners refuse further requests without mutation or emission. Exact latest retry classification precedes budget, terminal and current-context tests only while a valid owner is open.')
    )
    page('Actual device W emission', 'FINITE CONTRACT | W7 | CANONICAL STATE, READ-ONLY OUTPUT',
        p('For GPU FI/HP/GD/OG owners, state W words shall be produced from the canonical device [left,right,energy,ticks], including terminal EMIT owners. Upload only the requested tick16/context, never a host replacement pair or phase. The shader reads canonical state, checks parity, full mirror, legal STEP/EMIT, G/B and energy, then computes intrinsic phase16 and both W headers.'),
        h('Fixed scratch interface'),
        code('upload = [tick16, 0]  # existing scratch buffer\nheader = (tick16 << 16) | phase16\noutput = [left,header,right,header,energy,device_ticks,ok,0]\n# eight u32; ok=1 only for valid canonical state'),
        p('The shader never advances or writes canonical owner state. Read complete output and canonical state; independently check exact agreement and preservation. G/B, energy and phase must match the actual certified owner context, in addition to representation validity. Validate reserved zeros and complete output shape.'),
        h('Device action count is not a logical clock'),
        p('device_ticks is the existing executor action counter. GROW resets it. It is neither agent.cycle nor W time. Verify and preserve it against that executor\'s expected counter. Read-only emission supports seeded terminal EMIT states and must not invoke an advance-only readiness check that rejects them.'),
        table(['Device outcome','Required handling'],[
            ['Complete valid output','Use the device-produced state words to assemble the typed LUS record; preserve the owner.'],
            ['Failed/truncated dispatch or read','Poison and close the owner; no fabricated output or acknowledgment.'],
            ['Canonical mismatch','Poison and close the owner. Propagate closure through the owning field agent, including FI.'],
            ['Complete malformed emission','Nonfatal only under W6\'s whole-operation prestate rule; after semantic mutation, poison unless fully restored.'],
        ],[.31,.69]),
        p('The host codec may wrap raw IGNITE bytes and assemble explicit LUS metadata. It may not substitute CPU-produced state words for the GPU result. Existing GPU compiler/producer guards remain active through ADVANCE, GROW and private recovery. CPU reference values certify outputs rather than replacing the device producer.'),
        box('Revision 11 specified this device work before implementation. Revision 12 records the actual-device capture on pages 82-83. Cache residency, occupancy, throughput and physical-energy advantage remain unmeasured.')
    )
    page('W transport and exact responses', 'FINITE CONTRACT | W8 | CURRENT ADMISSION METADATA',
        p('Provide JSONL endpoint <font name="Mono">agent welip</font> with --state, --config, --backend and existing storage index options. Config generator <font name="Mono">agent welip-config</font> uses --profile field/hadamard/growth/organogram, default organogram, mapping to page 70\'s policies. No W inspect/status/history command is provided.'),
        p('Maximum request line length is 65,536 characters. Require unique JSON keys and finite numbers. An oversized line is fatal; do not parse its tail. EOF or transport failure closes the owner and releases its lock. COMPLETE still permits allowed controls/emission. W budget exhaustion disables new operations; the endpoint stays open for exact latest retries until EOF or close.'),
        h('Common response and current head'),
        code('response common = {protocol,type,producer,producer_epoch,head,next}\nhead = {seq,clock_epoch,tick16,agent_cycle,geometry_epoch}\nnext = null  # exactly when the W event budget is exhausted\n# otherwise:\nnext = {seq,clock_epoch,tick16,agent_cycle,geometry_epoch,\n        position,visible_paths,active_paths,capacity,\n        agent_status,allowed_ops}'),
        p('head describes current durable admission. next sequence/clock are candidate values; cycle/generation are the current preoperation context. position is canonical; visible_paths is sorted local visibility; active_paths is current FIFO order. They contain names, not historical pairs or fields. capacity is current and agent_status is mission status.'),
        p('allowed_ops preserves IGNITE,ADVANCE,RESIZE,INVALIDATE,EMIT order after filtering. Before ignition allow only IGNITE; afterward remove IGNITE. Remove ADVANCE on COMPLETE or agent-cycle exhaustion. Remove INVALIDATE when no active entry exists. Controls and emission remain available when advancement is unavailable.'),
        table(['Response type','Exact additional fields and delivery'],[
            ['READY','{restored:boolean}; once after durable open/recovery.'],
            ['RESULT','{op,seq,records,cache,agent_status}; only after durable save.'],
            ['DUPLICATE','{seq}; no prior records, pair, energy or event.'],
            ['ERROR','{code,message,fatal}; nonfatal errors retain unchanged head/next. Fatal errors use head=null,next=null, with admitted configuration producer fields.'],
        ],[.23,.77]),
        small('Startup failure before a valid owner exists terminates with stderr/nonzero exit and no READY. Error messages are human-readable diagnostics, not retained canonical history or archive dumps. On transport write failure the owner closes; no response is assured. Current cursor metadata is an explicit forward admission interface, not a public historical read.')
    )
    page('W admission order and rejection classes', 'FINITE CONTRACT | W8 | DETERMINISTIC VALIDATION BOUNDARY',
        h('Classification order'),
        table(['Stage','Required checks before proceeding'],[
            ['1. Transport','Reject malformed/oversized transport; require protocol/op syntax.'],
            ['2. Public alphabet','Deny explicit READ/HISTORY/REPLAY/REGENERATE as BACKWARD_READ; reject other unknown ops.'],
            ['3. Static request','Require exact operation keys, shapes/ranges, canonical path syntax and source identity.'],
            ['4. Retry/order','Handle exact latest retry or conflict, then stale sequence and gap. No historical payload retrieval.'],
            ['5. New request context','Check W event budget, complete clock, current agent cycle/generation, ignition/terminal/cycle eligibility.'],
            ['6. Dynamic admission','Check current position, visibility and active membership before execution.'],
        ],[.25,.75]),
        p('The request sequence domain is 1..max_events+1, so a next-sequence request at the exhausted budget receives BUDGET_EXHAUSTED. No admitted sequence exceeds max_events. Budget classification precedes candidate-clock checks, including at the maximal 48-bit horizon. No JSON duplicate keys, unknown keys, Boolean-to-integer coercion or nonfinite values are admitted.'),
        h('Complete nonfatal error alphabet'),
        code('INVALID_REQUEST       SOURCE_MISMATCH      BACKWARD_READ\nCONFLICT              STALE_SEQUENCE       SEQUENCE_GAP\nBUDGET_EXHAUSTED      CLOCK_MISMATCH       CONTEXT_MISMATCH\nNOT_IGNITED           ALREADY_IGNITED      AGENT_COMPLETE\nAGENT_BOUND           INVALID_SELECTOR     MALFORMED_EMISSION'),
        p('INVALID_REQUEST covers malformed static/protocol input; SOURCE_MISMATCH covers producer/namespace; CLOCK_MISMATCH covers the full clock; CONTEXT_MISMATCH covers cycle/generation/position; INVALID_SELECTOR covers nonlocal observations or nonactive invalidation paths. Missing ignition, repeated ignition, COMPLETE and agent cycle exhaustion use NOT_IGNITED, ALREADY_IGNITED, AGENT_COMPLETE and AGENT_BOUND respectively. MALFORMED_EMISSION is nonfatal only under W6. Every pure rejection leaves admitted clock/history/cache unchanged.'),
        h('Fatal error alphabet'),
        code('REQUEST_TOO_LARGE     OWNER_FAILED         STORAGE_FAILED'),
        p('Fatal owner/storage errors terminate the valid ownership period. A closed or poisoned embedded owner refuses all further requests without emission or mutation. Fatal transport errors never interpret a remaining line tail as another request. Responses follow page 78\'s null-head/null-next rule only when a valid admitted configuration exists.'),
        small('The protocol does not turn an attempted read into automatic corruption or eviction. INVALIDATE is an explicit validated forward operation with a recorded cause. Neither denied names nor integrity checks supply global producer authentication.')
    )
    build_w_reference_pages()


def build_w_reference_pages():
    page('Independent W reference vectors', 'INDEPENDENT REFERENCE | MATHEMATICAL EXPECTATIONS BEFORE RUNTIME',
        p('The independent reference in docs/evidence/welip-v1/ uses frozen OG mathematical owner transitions and separate integer codec/cache logic, with no solvefinite import or device execution. Its main fixture uses producer welip-reference, producer_epoch 7, clock_origin 65,530, max_events 64 and initial capacity 3, around the nine-cycle OG mission on page 65.'),
        h('Complete lifecycle schedule'),
        code('I, A1, E, R1, X, A2, A3, A4, E, A5/GROW, R4, A6, A7, X, A8, A9, E'),
        p('I=IGNITE bytes DEADBEEF0123456789; A means ADVANCE to the stated agent cycle; E=EMIT; R=RESIZE to the stated capacity. The first X invalidates k:3:0 with cause release-old-local-copy; the second invalidates k:2:1 with cause rebuild-current-local-copy. The schedule expects 17 W operations and 18 records while preserving the nine agent transitions.'),
        h('Exact words: clock, byte order and terminal state'),
        code('IGNITE raw record0 (9 bytes; phase16=FA00):\n FFFBFA00EFBEADDE FFFBFA0067452301 FFFBFA0000000089\nIGNITE state record1 (same time and phase):\n FFFBFA0001FE00FA FFFBFA0091FE0006\nW operation6 / ADVANCE2 (epoch1, tick0000, phase1000):\n 00001000910010F0 0000100081001010\nW operation17 / EMIT (epoch1, tick000B, phaseBA00):\n 000BBA0016000646 000BBA00860006BA'),
        p('At operation 6, T_W=65,536, agent cycle=2 and energy=93. At operation 10, GROW reaches agent cycle 5 and geometry epoch 1; the new cache is empty with zero counters. Final owner pair is 860006BA16000646, energy 76, agent cycle 9, geometry epoch 1 and W clock (1,11). Final cache capacity is 4, with FIFO k:1:0,k:1:1,k:1:2,k:2:1; hits 0, regenerations 7, evictions 16.'),
        h('Independent boundary qualifications'),
        p('The reference includes raw lengths 0,1,5,9 and 4,096; 1,024 phase/orientation/STEP-or-EMIT codec cases; mirrored and capacity-8 lifecycle variants; malformed padding/count/header/parity/mirror vectors; and legal channel-swap rejection against the actual owner. The generic full-width carrier word FFFFFFFFFFFFFFFF is legal for tick=phase=65,535 and four FF bytes; state phase adds its stricter resolution rule.'),
        small('Maximum-clock fixture: origin=281474976710591 and max_events=64 end at (4294967295,65535). A next sequence 65 receives BUDGET_EXHAUSTED before clock equality; no next cursor wraps. Full requests, records, retry receipts, cache witnesses and separate executor-counter expectations are retained. Historical OG runtime archive identity is labelled separately from these mathematical W transcript identities.'),
        small('Main operation-transcript SHA-256: e2b7b8b47b057319f77fbdeea6146b73eba714c1a8e132b065b7c4671ad4c5e0. The builder pins the complete reference and generator; these are expected values, not measured W runtime results.')
    )
    build_w_acceptance_page()


def build_w_acceptance_page():
    page('W acceptance and architectural scope', 'FINITE CONTRACT | W8 | REQUIRED IMPLEMENTATION EVIDENCE',
        p('A separate source-bound implementation capture shall demonstrate the complete finite contract. Passing carrier examples alone does not establish durable lifecycle, device refinement or forward-only admission. The independent reference precedes runtime work; actual implementation evidence must retain its original inputs and versions.'),
        table(['Obligation','Required acceptance scope'],[
            ['Codec and metadata','Raw lengths 0,1,5,9 and 4,096; exact padding/count/header checks; full parity/mirror; ordered owner channels; energy metadata, wrong actual owner/context and coordinated legal-but-wrong payload rejection.'],
            ['Clocks / identity','All five new operations advance W time; IGNITE record sequence 0,1; 16-bit carry and 48-bit exhaustion; independent producer epoch, agent cycle, geometry epoch and device counter; no wrap reuse.'],
            ['Agent projection','All four supported policies; unchanged canonical agent archive under inserted W controls; exact original OG GROW time/prefix; mirrored owner, incomplete WAIT frames, incremental DEFER and fresh recovery from nonterminal outcomes.'],
            ['FIFO lifecycle','Capacity-preserving semantics, oldest eviction, complete selected-pair invalidation, unaffected order, cause retention and later regeneration; whole-selector rejection; fresh cache/counter reset at GROW; interleaved lifecycle replay.'],
            ['Forward boundary','All backward names and extra selectors denied; latest exact retry before changed context; stale/conflicting/gapped requests; no historical payload, duplicate device dispatch, clock mutation or archive write.'],
            ['Actual GPU refinement','Canonical device W production for all four policies and terminal EMIT states; host state-word fallback forbidden; complete canonical/scratch checks, preserved device counter and no reseeding after initialization.'],
            ['Durability / ownership','One OS-held owner and serialized calls; immutable configuration/path; before/after replacement failures, unread acknowledgment, post-ADVANCE/cache emission failure, save uncertainty, EOF/oversized/transport failure and fresh CPU/GPU process recovery.'],
            ['Prior profiles','FI/PX/HP/GD/OG schemas, numerical contracts and canonical reference archives remain unchanged. Existing live retry/history APIs keep their separate R semantics.'],
        ],[.25,.75]),
        box('Revision 11 fixed these acceptance obligations before implementation. Revision 12 records the source-bound capture on pages 82-83, including actual-device execution, durable recovery and unchanged agent archives. Numerical definitions and reference vectors retain their original meanings.'),
        small('Remaining architecture includes general primitive/graph productions, broader spectral choices, physical adapters, universality and comparative hardware measurements. This finite W binding is not indefinite time, global authentication, exactly-once physical actuation or total constant memory.')
    )
    build_w_measured_pages()


def build_w_measured_pages():
    tests = W_VERIFICATION['tests']
    methods = sum(tests['actual_device_methods'].values())
    checks = W_VERIFICATION['conformance_checks_passed']
    adapter = W_CONFORMANCE['adapter']
    page('Measured W clock and continuation', 'IMPLEMENTATION CAPTURE | W1-W8 | 26 SEPTEMBER 2026',
        box(f"The source-bound capture passes {tests['passed']} tests with zero skips, including {methods} actual-device GPU methods, and all {checks} W conformance checks. This is finite clock, carrier and same-owner continuation evidence under the numerical contract committed at 74e00f4."),
        p(f"Device: {escape(adapter['device'])}, {escape(adapter['backend_type'])}. All three frozen 17-operation lifecycles execute on CPU and GPU. Each produces the exact 18 records and 37 carrier words, with identical complete private W archives across backends. All four field policies retain terminal emission."),
        h('Time and identity remain separate'),
        table(['Checkpoint','Observed result in the default fixture'],[
            ['Operation 6','W clock carries to (1,0); agent cycle 2, energy 93.'],
            ['Operation 10','GROW reaches cycle 5 and geometry epoch 1; a new cache and executor counter start at zero. Global cycle and energy do not reset.'],
            ['Operation 17','W clock (1,11); cycle 9, geometry epoch 1, pair 860006BA16000646 and energy 76.'],
            ['Capacity variant','Capacity eight changes final cache hits/regenerations to 4/3 from 0/7, preserving every agent transition.'],
        ],[.24,.76]),
        h('Actual device production'),
        p('The W shader reads the current canonical pair, energy and action counter. Only tick16 and a reserved zero are uploaded. Both ordered fragments are read from device output and checked against a separate full canonical read. The host state encoder and earlier CPU geometry producers are disabled during GPU conformance, including fresh GPU recovery. Emission introduces no replacement owner or reseeding.'),
        p('One exact latest retry returns a current cursor and sequence receipt, with no earlier records, state payload, device emission or save. A new EMIT can produce the current state after completion. Every cache removal preserves complete pairs and unaffected FIFO order; private recovery repeats lifecycle events alongside the original agent steps.'),
        small('These results establish the declared finite W implementation. They do not measure texture-cache saturation, throughput, physical energy or an advantage over a conventional architecture. GPU execution still uses host admission, verification and durable journaling.')
    )
    page('W recovery, evidence and remaining work', 'MEASURED RECOVERY | SOURCE IDENTITIES | ARCHITECTURAL CONTINUATION',
        h('Failures resolve through the durable prefix'),
        p('Complete malformed device output is nonfatal only before any working-state mutation and after unchanged canonical state is established. Output failure after ADVANCE, uncertain dispatch and uncertain save close the owner. A successful replacement followed by a lost acknowledgement reconstructs as the latest duplicate; an unsaved transition reconstructs from the preceding prefix.'),
        p('Three fresh endpoint processes execute GPU, CPU and GPU with distinct storage indexes. They reconstruct the complete original W ledger and FIFO witnesses around clock carry and geometry growth. Session tests additionally cover interruption during mutation/save, before/after atomic replacement, unread acknowledgement, concurrent duplicate admission, strict archive corruption rejection and transport closure.'),
        p('Incomplete observations, deferred search and fresh observations after temporary energy failure retain the same individual. UNREACHABLE uses an injected planner outcome; the supported Klein graphs are connected. Clock exhaustion removes the next cursor but retains the latest exact retry. Mission or cycle completion stops ADVANCE while permitting controls and emission within the W budget.'),
        h('Reproducible evidence and preservation'),
        code('python -m unittest discover -s tests -v\npython -m examples.welip_conformance --output w-recheck.json\npython tools/capture_welip_evidence.py\npython tools/build_formal_spec.py'),
        small('Capture files: docs/evidence/welip-v1/verification.json, conformance.json and full-tests.txt. Source hashes use LF-normalized bytes; the capture checks identical source inventories before and after execution. The formal builder verifies those sources, reports, formal chronology, frozen reference, full lifecycle rows, device evidence and archive identities.'),
        small('Canonical W archive SHA-256: '+W_CONFORMANCE['welip_archive_sha256']),
        small('Unchanged historical OG agent archive SHA-256: '+W_CONFORMANCE['canonical_agent_archive_sha256']),
        h('Next source obligation'),
        p('Original specification p.7 requires a geometry-to-field map for every declared primitive. The present parameterized organogram generates intrinsic balls; directional pyramid/cone boundaries and general graph production remain unfinished. A further realization must explicitly bind its geometry, phase/Psi relation, seam behavior and exact redistancing before implementation. Broader spectral choices, physical adapters, universality and comparative hardware evidence also remain open.'),
        small('The three original PDFs and separate Tom/Jitske ELI5 booklet remain byte-identical. This measured milestone advances the architecture; it does not establish the full paradigm or exactly-once physical actuation.')
    )


def cover(c, count):
    c.setFillColor(INK); c.rect(0,0,WIDTH,HEIGHT,fill=1,stroke=0)
    c.setFillColor(TEAL); c.rect(LEFT,HEIGHT-85,54,5,fill=1,stroke=0)
    c.setFont('Bold',11); c.setFillColor(colors.HexColor('#A8D5D4'))
    c.drawString(LEFT,HEIGHT-117,'TK-LPLUT-2.0  /  REVISION 12')
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
    c.drawString(LEFT,105,'26 September 2026  |  Formalization with measured implementation progress')
    c.setFont('Body',9); c.drawString(LEFT,71,'Original specification + Solus + Infallible addendum + current code evidence')
    c.bookmarkPage('cover'); c.addOutlineEntry('The Infallible Contract','cover',0)
    c.showPage()


def render(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(output),pagesize=A4,invariant=1,pageCompression=1)
    c.setTitle('The Infallible Contract - Ontological Deterministic Computing - TK-LPLUT-2.0 revision 12')
    c.setAuthor('Tom Klootwijk - paradigm author; consolidated formalization prepared with Codex')
    c.setSubject('Integrated formal specification and implementation evidence, 26 September 2026')
    count=len(PAGES)+1
    cover(c,count)
    layout=[]
    for number,(title,subtitle,items) in enumerate(PAGES,2):
        c.bookmarkPage(f'p{number}'); c.addOutlineEntry(title,f'p{number}',0)
        c.setFillColor(TEAL); c.setFont('Bold',8.5); c.drawString(LEFT,HEIGHT-42,'TK-LPLUT-2.0 / REVISION 12')
        c.setFillColor(MUTED); c.setFont('Body',8.2); c.drawRightString(WIDTH-RIGHT,HEIGHT-42,'TOM KLOOTWIJK  /  26 SEPTEMBER 2026')
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
                if pg > 69: continue  # The W appendix supplies its own complete section map.
                items.append((pg,t))
            column_width = (CONTENT_W-22)/2
            split = (len(items)+1)//2
            start_y = y
            bottoms = []
            toc_style = ParagraphStyle('contents', fontName='Body', fontSize=8.6,
                                       leading=11, textColor=INK)
            for column, entries in enumerate((items[:split], items[split:])):
                x = LEFT+column*(column_width+22)
                y = start_y
                for pg,t in entries:
                    label = Paragraph(escape(t), toc_style)
                    _, ht = label.wrap(column_width-24, 80)
                    label.drawOn(c,x,y-ht)
                    c.setFont('Bold',8.6); c.setFillColor(TEAL)
                    c.drawRightString(x+column_width,y-9,str(pg))
                    c.linkRect('',f'p{pg}',(x,y-ht-2,x+column_width,y+2),relative=0,thickness=0)
                    y -= max(18.5,ht+6.5)
                bottoms.append(y)
            y=min(bottoms)
            if y < 59: raise ValueError(f'Contents overflow: bottom={y:.1f}')
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
    global HP_VERIFICATION, GD_VERIFICATION, GD_CONFORMANCE, OG_REFERENCE, OG_VERIFICATION, OG_CONFORMANCE, W_REFERENCE
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
    klein = json.loads((KLEIN_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if (klein['tests']['passed'], klein['tests']['skipped'],
            sum(klein['tests']['actual_device_methods'].values()),
            klein['dimension_pairs_audited'], klein['conformance_checks_passed']) != (311, 0, 28, 702, 22):
        raise ValueError('Retained Klein verification disagrees with revision 1')
    for filename in ('full-tests.txt', 'conformance.json', 'cli-replay.json'):
        if not (KLEIN_EVIDENCE/filename).is_file():
            raise ValueError(f'Missing retained Klein evidence: {filename}')
    integration = json.loads((FIELD_AGENT_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if (integration['tests']['passed'], integration['tests']['skipped'],
            sum(integration['tests']['actual_device_methods'].values()),
            integration['conformance_checks_passed']) != (368, 0, 41, 23):
        raise ValueError('Retained field-agent verification disagrees with revision 2')
    if (integration['formal_binding_commit'] != '5ccc0228966684b71f6d8a9172ab31ce11715230'
            or integration['base_commit'] != 'c4b41ce12a33a747bd54c8cc7f9748a06f7b59de'):
        raise ValueError('Retained field-agent chronology disagrees with revision 2')
    conformance = json.loads((FIELD_AGENT_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (conformance['format'] != 'tomigidt-field-agent-conformance-v1'
            or len(conformance['checks']) != 23
            or any(value is not True for value in conformance['checks'].values())):
        raise ValueError('Field-agent conformance does not pass all named checks')
    for relative, expected in integration['source_sha256_lf'].items():
        source = subprocess.check_output(
            ['git', 'show', f'c8af71dbb5b526deb1dee97dc61ef5bbd47e6737:{relative}'],
            cwd=ROOT).replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f'Field-agent evidence source identity changed: {relative}')
    if not (FIELD_AGENT_EVIDENCE/'full-tests.txt').is_file():
        raise ValueError('Missing retained field-agent test log')
    reference = ROOT/'docs/evidence/psi-f8-v1/formal-reference.json'
    reference_bytes = reference.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(reference_bytes).hexdigest() != '92ff743ae86bb31ef82669284467e7471040a0ec5e7995de520b8a6c5ed032d8':
        raise ValueError('Retained PX formal reference identity changed')
    px = json.loads((PSI_F8_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if (px['tests']['passed'], px['tests']['skipped'],
            sum(px['tests']['actual_device_methods'].values()), px['tests']['elapsed_seconds'],
            px['conformance_checks_passed'], px['dimension_pairs_audited'],
            px['node_descriptors_audited'], px['gpu_domains'],
            px['gpu_lookups_and_materializations'], px['deferred_mission_cycles'],
            px['conformance_elapsed_seconds']) != (421, 0, 55, 44.997, 20, 702, 106045, 6, 830, 41, 21.673):
        raise ValueError('Retained PX verification disagrees with revision 4')
    if (px['formal_binding_commit'] != 'd8de3497d1a147252cdff2635b5c5ece0bda780e'
            or px['base_commit'] != 'c8af71dbb5b526deb1dee97dc61ef5bbd47e6737'):
        raise ValueError('Retained PX chronology disagrees with revision 4')
    for relative, expected in px['source_sha256_lf'].items():
        source = subprocess.check_output(
            ['git', 'show', f'4b8fa89ea68a98fe293c21b925a31cf5870e84c7:{relative}'],
            cwd=ROOT).replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f'PX evidence source identity changed: {relative}')
    for relative, expected in px['report_sha256_lf'].items():
        report = (PSI_F8_EVIDENCE/relative).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(report).hexdigest() != expected:
            raise ValueError(f'PX evidence report identity changed: {relative}')
    px_conformance = json.loads((PSI_F8_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (px_conformance['format'] != 'psi-f8-conformance-v1'
            or len(px_conformance['checks']) != 20
            or any(value is not True for value in px_conformance['checks'].values())
            or px_conformance['canonical_archive_sha256'] != integration['canonical_archive_sha256']):
        raise ValueError('PX conformance does not retain the verified FI history')
    allocation = px['allocation_info']
    if (allocation['device_payload_bytes'], allocation['peak_rebuild_device_payload_bytes'],
            allocation['host_index_payload_bytes'], allocation['peak_rebuild_host_index_payload_bytes'],
            allocation['retained_world_node_pair_count']) != (49160, 51528, 1296, 2592, 0):
        raise ValueError('Retained PX allocation accounting disagrees with revision 4')
    hp_reference = ROOT/'docs/evidence/hadamard-v1/formal-reference.json'
    hp_reference_bytes = hp_reference.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(hp_reference_bytes).hexdigest() != '89e93219e8266b22c9aa080c580a1ae7da296a989464452bc1d85ab68597ab66':
        raise ValueError('Retained HP formal reference identity changed')
    hp = json.loads((HADAMARD_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if (hp['format'] != 'hadamard-verification-v1'
            or hp['formal_binding_commit'] != '0c862c310a13b0baef82065efc2464f14c280f9d'
            or hp['base_commit'] != '4b8fa89ea68a98fe293c21b925a31cf5870e84c7'):
        raise ValueError('Retained HP chronology disagrees with revision 6')
    tests = hp['tests']
    if (type(tests['passed']) is not int or tests['passed'] <= 421
            or tests['skipped'] != 0
            or sum(tests['actual_device_methods'].values()) <= 55):
        raise ValueError('HP requires its own complete passing implementation capture')
    if not hp['source_sha256_lf'] or not hp['report_sha256_lf']:
        raise ValueError('HP requires source and retained-report identities')
    for relative, expected in hp['source_sha256_lf'].items():
        source = subprocess.check_output(
            ['git', 'show', f'5a304bcca77965778e1acb743d49d54e2a79e380:{relative}'],
            cwd=ROOT).replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f'HP evidence source identity changed: {relative}')
    for relative, expected in hp['report_sha256_lf'].items():
        report = (HADAMARD_EVIDENCE/relative).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(report).hexdigest() != expected:
            raise ValueError(f'HP evidence report identity changed: {relative}')
    hp_conformance = json.loads((HADAMARD_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (hp_conformance['format'] != 'hadamard-conformance-v1'
            or not hp_conformance['checks']
            or len(hp_conformance['checks']) != hp['conformance_checks_passed']
            or any(value is not True for value in hp_conformance['checks'].values())):
        raise ValueError('HP conformance does not pass every named check')
    if (hp['gpu_domains'] != len(hp_conformance['GPU_domains'])
            or hp['gpu_nodes'] != sum(item['nodes'] for item in hp_conformance['GPU_domains'])
            or hp['gpu_penalty_checks'] != sum(item['penalty_checks'] for item in hp_conformance['GPU_domains'])
            or hp['deferred_mission_cycles'] != hp_conformance['GPU_deferred']['archive']['expected']['cycle']
            or hp['canonical_archive_sha256'] != hp_conformance['canonical_archive_sha256']
            or hp['allocation_info'] != hp_conformance['GPU']['execution_info']['allocation_info']
            or hp['legacy_field_archive_sha256'] != integration['canonical_archive_sha256']):
        raise ValueError('HP measurements disagree with their source reports')
    log = (HADAMARD_EVIDENCE/'full-tests.txt').read_text(encoding='utf-8')
    if f'Ran {tests["passed"]} tests in ' not in log or not log.rstrip().endswith('OK'):
        raise ValueError('HP suite count is not backed by its complete passing log')
    HP_VERIFICATION = hp
    gd_reference = GROWTH_EVIDENCE/'formal-reference.json'
    gd_bytes = gd_reference.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(gd_bytes).hexdigest() != '689bf2814a878612f85f095b33460b92733c8533cb0d5a04c997d428b5b37c6a':
        raise ValueError('Retained GD formal reference identity changed')
    gd = json.loads(gd_bytes)
    generator_bytes = (GROWTH_EVIDENCE/'reference-builder.py').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(generator_bytes).hexdigest() != gd['generator_sha256_lf']:
        raise ValueError('Retained GD independent generator identity changed')
    default = gd['default_mission']
    if (gd['format'] != 'growth-independent-formal-reference-v1'
            or default['cycles'] != 14
            or default['events'][4]['state']['pair'] != '01024045110240BB'
            or default['events'][4]['state']['energy'] != 85
            or default['events'][4]['target_after'] != 39
            or default['final']['pair'] != '160027E906002717'
            or default['final']['energy'] != 64
            or gd['two_epoch_mission']['cycles'] != 25
            or gd['two_epoch_mission']['final']['pair'] != '86000F0E16000FF2'
            or gd['two_epoch_mission']['final']['energy'] != 33):
        raise ValueError('GD displayed formal vectors disagree with the independent reference')
    growth = json.loads((GROWTH_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    if (growth['format'] != 'growth-verification-v1'
            or growth['formal_binding_commit'] != '00b0e64decd2d8202725b71c101480843b1af1e2'
            or growth['initial_formal_binding_commit'] != 'ec1181e00f40c3663e73974885573ebfae784e08'
            or growth['base_commit'] != '5a304bcca77965778e1acb743d49d54e2a79e380'):
        raise ValueError('Retained GD chronology disagrees with revision 8')
    growth_tests = growth['tests']
    if (type(growth_tests['passed']) is not int or growth_tests['passed'] <= tests['passed']
            or growth_tests['skipped'] != 0
            or sum(growth_tests['actual_device_methods'].values()) <= sum(tests['actual_device_methods'].values())):
        raise ValueError('GD requires a separate complete passing actual-device capture')
    required_sources = {'solvefinite/growth.py', 'solvefinite/tomigidt.py',
                        'solvefinite/field_agent_gpu.py', 'solvefinite/session.py',
                        'solvefinite/live.py', 'examples/growth_conformance.py',
                        'tests/test_growth_session.py', 'tools/capture_growth_evidence.py'}
    if not required_sources <= growth['source_sha256_lf'].keys():
        raise ValueError('GD capture lacks required source identities')
    for relative, expected in growth['source_sha256_lf'].items():
        source = subprocess.check_output(
            ['git', 'show', f'94f86c7ae84a6eee9b99d3101d3b531b7a307c17:{relative}'],
            cwd=ROOT).replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f'GD evidence source identity changed: {relative}')
    for relative, expected in growth['report_sha256_lf'].items():
        report = (GROWTH_EVIDENCE/relative).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(report).hexdigest() != expected:
            raise ValueError(f'GD evidence report identity changed: {relative}')
    growth_conformance = json.loads((GROWTH_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (growth_conformance['format'] != 'growth-conformance-v1'
            or growth_conformance['actual_GPU_capture'] is not True
            or growth_conformance['formal_commit'] != growth['formal_binding_commit']
            or growth_conformance['initial_formal_commit'] != growth['initial_formal_binding_commit']
            or not growth_conformance['checks']
            or any(value is not True for value in growth_conformance['checks'].values())
            or len(growth_conformance['checks']) != growth['conformance_checks_passed']
            or growth_conformance['formal_reference_sha256_lf'] != hashlib.sha256(gd_bytes).hexdigest()):
        raise ValueError('GD conformance lacks complete current CPU/GPU acceptance')
    for label in ('default', 'mirrored_default', 'two_epoch', 'zero_epoch'):
        cpu_archive = growth_conformance['CPU']['cases'][label]['archive']
        gpu_archive = growth_conformance['GPU'][label]['archive']
        expected = gd[label+'_mission']
        actual = gpu_archive['expected']
        if (cpu_archive != gpu_archive
                or actual['cycle'] != expected['cycles']
                or actual['geometry_epoch'] != expected['final_geometry_epoch']
                or actual['agent_pair'] != expected['final']['pair']
                or actual['energy'] != expected['final']['energy']
                or actual['status'] != 'COMPLETE'):
            raise ValueError(f'GD measured mission disagrees with its independent reference: {label}')
    default_archive = growth_conformance['GPU']['default']['archive']
    archive_hash = hashlib.sha256(json.dumps(default_archive, sort_keys=True,
                                           separators=(',', ':'), ensure_ascii=True,
                                           allow_nan=False).encode('utf-8')).hexdigest()
    cli = json.loads((GROWTH_EVIDENCE/'cli-replay.json').read_text(encoding='utf-8'))
    if (archive_hash != growth_conformance['canonical_archive_sha256']
            or archive_hash != growth['canonical_archive_sha256']
            or archive_hash != cli['canonical_archive_sha256']
            or cli['inspection_kept_saved_bytes'] is not True
            or growth['final_state'] != default_archive['expected']
            or growth_conformance['CPU']['deferred']['archive'] != growth_conformance['GPU_deferred']['archive']
            or len(growth_conformance['fresh_process_replays']) != 6):
        raise ValueError('GD captured histories or cross-process continuation disagree')
    log = (GROWTH_EVIDENCE/'full-tests.txt').read_text(encoding='utf-8')
    if (f'Ran {growth_tests["passed"]} tests in ' not in log
            or not log.rstrip().endswith('OK') or '... skipped' in log or 'skipped=' in log):
        raise ValueError('GD suite counts require the complete passing zero-skip log')
    if growth['eli5_pdf_unchanged_sha256'] != hashlib.sha256(
            (ROOT/'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf').read_bytes()).hexdigest():
        raise ValueError('ELI5 identity differs from the GD capture')
    GD_VERIFICATION = growth
    GD_CONFORMANCE = growth_conformance
    og_bytes = (ORGANOGRAM_EVIDENCE/'formal-reference.json').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(og_bytes).hexdigest() != '21df28af479fbae2c70a7390a71b0baf9322fcbf38de3ce9db8ff5e5f3b4a6fe':
        raise ValueError('Retained OG independent reference identity changed')
    og = json.loads(og_bytes)
    og_generator = (ORGANOGRAM_EVIDENCE/'reference-builder.py').read_bytes().replace(b'\r\n', b'\n')
    if (hashlib.sha256(og_generator).hexdigest() != '987c0adced856312fc3581d921ec1badaec236c0230c63f25ef6f024959f32d8'
            or og['generator_sha256_lf'] != hashlib.sha256(og_generator).hexdigest()
            or og['independent_GD_generator_sha256_lf'] != gd['generator_sha256_lf']):
        raise ValueError('Retained OG independent generator identities changed')
    og_stage = og['standalone_stage']
    og_document = og_stage['document']
    og_mission = og['default_mission']
    og_two = og['two_epoch_mission']
    og_metric = og['metric_certificate']
    og_union = og['union_counterexample']
    og_pop = og['branch_certificate']['exact_pop_restorations'][0]['restored']
    first_pop = next(index for index, token in enumerate(og_document['tape']) if token['symbol'] == ']')
    before_pop = og_document['trace'][first_pop-1]
    if (og['format'] != 'organogram-independent-formal-reference-v1'
            or og_stage['derivation_sha256'] != 'c21c03969f8802376e4ef3db514d73de0d819310c2d4377ebb8d436d0d6a8e24'
            or hashlib.sha256(json.dumps(og_document, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest() != og_stage['derivation_sha256']
            or (before_pop['pair'], before_pop['radius'], before_pop['scale']) != ('91FE00B181FE004F', 2, 1)
            or (og_pop['pair'], og_pop['radius'], og_pop['scale']) != ('81020C5791020CA9', 1, 0)
            or [(ball['center'], ball['radius']) for ball in og_document['balls']] != [(12, 1), (0, 2), (2, 1)]
            or (og_mission['cycles'], og_mission['final']['energy'], og_mission['final']['pair']) != (9, 76, '860006BA16000646')
            or (og_two['cycles'], og_two['final']['energy'], og_two['final']['pair']) != (14, 66, '06000E2F16000ED1')
            or (og_metric['domains'], og_metric['nodes'], og_metric['ordered_node_pairs']) != (702, 106045, 19130481)
            or og_union['margin'] != [-2,-1,-1,-1,-2,-1,-1,-1,0]
            or og_union['field'] != [-2,-1,-2,-2,-2,-1,-1,-1,0]
            or og['instruction_profile']['encoding_vectors']['words'] != ['80000100','01000010','02000010','03000000','84000000','8500007F','06000000','07000004']):
        raise ValueError('OG displayed formal vectors disagree with the independent reference')
    OG_REFERENCE = og
    og_verification_bytes = (ORGANOGRAM_EVIDENCE/'verification.json').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(og_verification_bytes).hexdigest() != '0c1a392bcfe22c4c493291e9ad2b4fe750a40279f53702f8a21e631d55b6e52d':
        raise ValueError('Revision 10 requires its complete named OG implementation capture')
    measured = json.loads(og_verification_bytes)
    formal_commit = '5c76f2cec3a1cec8fd2d16eeeac2021c45b0aea9'
    formal_pdf = subprocess.check_output(['git', 'show',
        f'{formal_commit}:output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf'], cwd=ROOT)
    if (measured['format'] != 'organogram-verification-v1'
            or measured['formal_binding_commit'] != formal_commit
            or measured['base_commit'] != '94f86c7ae84a6eee9b99d3101d3b531b7a307c17'
            or measured['preimplementation_formal_pdf_sha256'] != hashlib.sha256(formal_pdf).hexdigest()
            or measured['preimplementation_formal_pdf_sha256'] != '64d1489cad789cf45e3171295076559ca2295030a5348561292bb977b19f91b0'):
        raise ValueError('OG implementation chronology disagrees with the frozen revision 9 formal binding')
    historical_paths = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', '-z', OG_CAPTURE_COMMIT,
         '--', 'solvefinite', 'tests', 'examples'], cwd=ROOT).decode('utf-8').split('\0')
    expected_sources = {path for path in historical_paths
                        if path and Path(path).suffix in ('.py', '.wgsl', '.json')}
    expected_sources.update({'tools/capture_organogram_evidence.py',
                             'docs/evidence/organogram-v1/reference-builder.py',
                             'docs/evidence/organogram-v1/formal-reference.json'})
    if set(measured['source_sha256_lf']) != expected_sources:
        raise ValueError('OG evidence must identify all runtime, example and test sources at f125a76')
    for relative, expected in measured['source_sha256_lf'].items():
        source = subprocess.check_output(
            ['git', 'show', f'{OG_CAPTURE_COMMIT}:{relative}'], cwd=ROOT).replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f'OG evidence source identity changed: {relative}')
    if set(measured['report_sha256_lf']) != {'full-tests.txt', 'conformance.json', 'cli-replay.json'}:
        raise ValueError('OG capture requires the complete suite, conformance and CLI replay reports')
    for filename, expected in measured['report_sha256_lf'].items():
        report = (ORGANOGRAM_EVIDENCE/filename).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(report).hexdigest() != expected:
            raise ValueError(f'OG evidence report identity changed: {filename}')
    og_tests = measured['tests']
    log = (ORGANOGRAM_EVIDENCE/'full-tests.txt').read_text(encoding='utf-8')
    suite_match = re.search(r'Ran (\d+) tests in ([0-9.]+)s', log)
    if (suite_match is None or int(suite_match[1]) != og_tests['passed']
            or float(suite_match[2]) != og_tests['elapsed_seconds']
            or og_tests['passed'] != 623 or og_tests['skipped'] != 0
            or sum(og_tests['module_counts'].values()) != og_tests['passed']
            or sum(og_tests['actual_device_methods'].values()) != 136
            or not log.rstrip().endswith('OK') or '... skipped' in log or 'skipped=' in log):
        raise ValueError('OG measured counts require the complete passing zero-skip suite log')
    for module, count in og_tests['module_counts'].items():
        if len(re.findall(r'\(' + re.escape(module) + r'\.', log)) != count:
            raise ValueError(f'OG test module count disagrees with its retained log: {module}')
    for name, count in og_tests['actual_device_methods'].items():
        if len(re.findall(r'\(\w+\.' + re.escape(name) + r'\.', log)) != count:
            raise ValueError(f'OG actual-device class count disagrees with its retained log: {name}')
    captured = json.loads((ORGANOGRAM_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (captured['format'] != 'organogram-conformance-v1'
            or captured['actual_GPU_capture'] is not True
            or captured['formal_commit'] != formal_commit
            or captured['formal_reference_sha256_lf'] != hashlib.sha256(og_bytes).hexdigest()
            or len(captured['checks']) != 15
            or measured['conformance_checks_passed'] != len(captured['checks'])
            or any(value is not True for value in captured['checks'].values())
            or len(captured['disabled_OG_CPU_producers']) != 6
            or len(captured['disabled_legacy_CPU_compilers']) != 11):
        raise ValueError('OG conformance requires every actual CPU/GPU acceptance check')

    def canonical_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()

    for label in ('default', 'mirrored_default', 'two_epoch', 'zero_epoch'):
        cpu = captured['CPU']['cases'][label]
        gpu = captured['GPU'][label]
        expected = og[label+'_mission']
        actual = gpu['archive']['expected']
        if (cpu['archive'] != gpu['archive']
                or canonical_hash(gpu['archive']) != gpu['archive_sha256']
                or actual['cycle'] != expected['cycles']
                or actual['agent_pair'] != expected['final']['pair']
                or actual['energy'] != expected['final']['energy']
                or actual['status'] != 'COMPLETE'
                or len(gpu['actual_device_states']) != actual['cycle']+1
                or len(gpu['stages']) != len(expected['stages'])):
            raise ValueError(f'OG measured mission disagrees with its independent reference: {label}')
        for device_state, snapshot in zip(gpu['actual_device_states'], gpu['snapshots']):
            if (device_state['cycle'], device_state['pair'], device_state['energy']) != (
                    snapshot['cycle'], snapshot['agent_pair'], snapshot['energy']):
                raise ValueError(f'OG actual device owner disagrees with its cycle snapshot: {label}')
        for stage in gpu['stages']:
            context = stage['context']
            events = gpu['archive']['events']
            event = events[context['tick']-1]
            if (canonical_hash(stage['expected_derivation']) != stage['derivation_sha256']
                    or stage['expected_derivation']['context'] != context
                    or canonical_hash(events[:context['tick']-1]) != context['prefix_sha256']
                    or event['growth']['derivation_sha256'] != stage['derivation_sha256']
                    or event['growth']['recipe']['stages'][-1] != context):
                raise ValueError(f'OG stage transcript, original context or admission digest disagrees: {label}')
    default_archive = captured['GPU']['default']['archive']
    archive_hash = canonical_hash(default_archive)
    cli = json.loads((ORGANOGRAM_EVIDENCE/'cli-replay.json').read_text(encoding='utf-8'))
    if (archive_hash != 'e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df'
            or archive_hash != captured['canonical_archive_sha256']
            or archive_hash != measured['canonical_archive_sha256']
            or archive_hash != cli['canonical_archive_sha256']
            or cli['inspection_kept_saved_bytes'] is not True
            or measured['final_state'] != default_archive['expected']
            or cli['outputs'][-1]['state'] != measured['final_state']
            or cli['outputs'][1]['state']['status'] != 'GROWTH_PENDING'
            or cli['outputs'][2]['state']['geometry_epoch'] != 1
            or cli['outputs'][3]['execution_info'] != measured['execution_info']
            or measured['environment']['adapter'] != measured['execution_info']['adapter']
            or captured['CPU']['deferred']['archive'] != captured['GPU_deferred']['archive']):
        raise ValueError('OG archive, CLI continuation, original-time DEFER or device evidence disagrees')
    replays = captured['fresh_process_replays']
    if set(replays) != {point+'_to_'+backend for point in ('before_growth_1', 'after_growth_1', 'DEFER_after_growth')
                        for backend in ('cpu', 'gpu')}:
        raise ValueError('OG requires all six fresh-process cross-backend continuations')
    for name, replay in replays.items():
        expected = captured['GPU_deferred']['archive'] if name.startswith('DEFER_') else default_archive
        if (replay['archive'] != expected or replay['archive_sha256'] != canonical_hash(expected)
                or (name.endswith('_gpu') and replay['CPU_producers_disabled'] is not True)):
            raise ValueError(f'OG fresh-process continuation disagrees: {name}')
    if (measured['original_source_sha256'] != expected_hashes
            or measured['eli5_pdf_unchanged_sha256'] != '06556d7bbae0de54e99f3abb9329869da1fbf085c6c1aab66d563528989c3ea0'
            or measured['eli5_pdf_unchanged_sha256'] != hashlib.sha256(
                (ROOT/'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf').read_bytes()).hexdigest()):
        raise ValueError('OG capture changed an original source or the separate ELI5 document')
    OG_VERIFICATION = measured
    OG_CONFORMANCE = captured
    w_bytes = (WELIP_EVIDENCE/'formal-reference.json').read_bytes().replace(b'\r\n', b'\n')
    w_generator = (WELIP_EVIDENCE/'reference-builder.py').read_bytes().replace(b'\r\n', b'\n')
    if (hashlib.sha256(w_bytes).hexdigest() != '0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210'
            or hashlib.sha256(w_generator).hexdigest() != '369c4f4f9d81cdbf5e897c20a06a08fd0d9949deadefb6f9c42975c9063c7eb7'):
        raise ValueError('Revision 11 requires its frozen independent W reference and generator')
    w = json.loads(w_bytes)
    if (w['format'] != 'welip-independent-formal-reference-v1'
            or w['generator_sha256_lf'] != hashlib.sha256(w_generator).hexdigest()
            or w['source_OG_reference_sha256'] != hashlib.sha256(og_bytes).hexdigest()
            or w['source_OG_generator_sha256_lf'] != hashlib.sha256(og_generator).hexdigest()
            or w['source_GD_generator_sha256_lf'] != gd['generator_sha256_lf']
            or w['phase_vectors']['checked_cases'] != 1024
            or len(w['malformed_vectors']['rejections']) != 14
            or [item['byte_length'] for item in w['raw_payload_vectors']['length_cases']] != [0,1,5,9,4096]):
        raise ValueError('W formal reference provenance or displayed coverage disagrees')
    hashes = {'main_lifecycle': 'e2b7b8b47b057319f77fbdeea6146b73eba714c1a8e132b065b7c4671ad4c5e0',
              'mirrored_lifecycle': '91e4d28efd3cc55bfd5f88bb71e01f3dec488fe2a02434571e1954a64ec1e24a',
              'capacity8_lifecycle': 'c0fcef115c34ebe0c6ed8b840d673a2937c530657d0969111f0d4a6b109d67d4'}
    for name, expected_digest in hashes.items():
        lifecycle = w[name]
        rows = lifecycle['operations']
        if (len(rows) != 17 or lifecycle['record_count'] != 18
                or lifecycle['fragment_count'] != 37
                or len(lifecycle['projected_owner_transitions']) != 9
                or lifecycle['operation_transcript_sha256'] != expected_digest
                or canonical_hash(rows) != expected_digest
                or [item['executor_action_ticks'] for item in lifecycle['executor_action_tick_expectations']]
                != [0,1,1,1,1,2,3,4,4,0,0,1,2,2,3,4,4]):
            raise ValueError(f'W displayed lifecycle schedule or independent digest disagrees: {name}')
        for number, row in enumerate(rows, 1):
            tick = lifecycle['config']['clock_origin'] + number
            request = row['request']
            if (request['seq'], request['clock_epoch'], request['tick16']) != (number, tick >> 16, tick & 65535):
                raise ValueError(f'W independent request clock disagrees: {name}/{number}')
            state = int(row['agent_pair'], 16)
            left = state & 0xffffffff
            phase = ((-(left & 255) if left & (1 << 28) else left & 255) & 255) << 8
            if len(row['records']) != (2 if number == 1 else 1):
                raise ValueError('W record count differs from the five-operation contract')
            for record_seq, record in enumerate(row['records']):
                if (record['operation_seq'], record['record_seq'], record['clock_epoch'],
                        record['tick16'], record['phase16'], record['energy']) != (
                        number, record_seq, tick >> 16, tick & 65535, phase, row['energy']):
                    raise ValueError(f'W record identity/phase/energy disagrees: {name}/{number}')
                if (record['fragment_count'] != len(record['words'])
                        or record['fragment_count'] != (record['byte_length']+3)//4
                        or any((int(word,16) >> 32) != ((tick & 65535) << 16) | phase
                               for word in record['words'])):
                    raise ValueError('W displayed word fragmentation/header arithmetic disagrees')
                if record['payload_profile'] == 'RP32-relational-sdf-v2':
                    if [int(word,16) & 0xffffffff for word in record['words']] != [left, state >> 32]:
                        raise ValueError('W state payload order differs from the original owner pair')
    main = w['main_lifecycle']
    first, carry, grow, final = [main['operations'][index] for index in (0,5,9,16)]
    if (first['records'][0]['words'] != ['FFFBFA00EFBEADDE','FFFBFA0067452301','FFFBFA0000000089']
            or first['records'][1]['words'] != ['FFFBFA0001FE00FA','FFFBFA0091FE0006']
            or carry['records'][0]['words'] != ['00001000910010F0','0000100081001010']
            or (carry['records'][0]['agent_cycle'], carry['energy']) != (2,93)
            or grow['cache'] != {'capacity':1,'active_paths':[],'hit_count':0,
                                'regeneration_count':0,'evicted_count':0,'removed':[]}
            or final['records'][0]['words'] != ['000BBA0016000646','000BBA00860006BA']
            or (final['agent_pair'], final['energy'], final['records'][0]['agent_cycle'],
                final['records'][0]['geometry_epoch']) != ('860006BA16000646',76,9,1)
            or final['cache'] != {'capacity':4,'active_paths':['k:1:0','k:1:1','k:1:2','k:2:1'],
                                 'hit_count':0,'regeneration_count':7,'evicted_count':16,'removed':[]}
            or main['projected_owner_transitions'] != w['capacity8_lifecycle']['projected_owner_transitions']):
        raise ValueError('W displayed literal carrier, lifecycle or cache vectors disagree')
    horizon = w['clock_vectors']['u48_maximum'][-1]
    historical = w['historical_runtime_preservation_expectation']
    if ((horizon['origin'], horizon['max_events'], horizon['seq'], horizon['clock_epoch'], horizon['tick16'])
            != (281474976710591,64,64,4294967295,65535)
            or w['clock_vectors']['exhausted_next_request']['request_seq'] != 65
            or w['clock_vectors']['exhausted_next_request']['next'] is not None
            or w['raw_payload_vectors']['generic_full_width']['words'] != ['FFFFFFFFFFFFFFFF']
            or historical['canonical_agent_archive_sha256'] != measured['canonical_archive_sha256']
            or historical['source_sha256'] != measured['report_sha256_lf']['conformance.json']):
        raise ValueError('W horizon or separately labelled historical OG preservation expectation disagrees')
    W_REFERENCE = w
    verify_w_capture(w, expected_hashes)


def verify_w_capture(reference, protected_sources):
    global W_VERIFICATION, W_CONFORMANCE
    measured = json.loads((WELIP_EVIDENCE/'verification.json').read_text(encoding='utf-8'))
    formal_commit = '74e00f4af54a341815c64e47f7f58334adda5709'
    formal_pdf = subprocess.check_output(['git','show',
        formal_commit+':output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf'], cwd=ROOT)
    if (measured['format'] != 'welip-verification-v1'
            or measured['formal_binding_commit'] != formal_commit
            or measured['base_commit'] != OG_CAPTURE_COMMIT
            or measured['preimplementation_formal_pdf_sha256'] != hashlib.sha256(formal_pdf).hexdigest()
            or hashlib.sha256(formal_pdf).hexdigest() != '24b180ebdf91b56ca01502171d1617178c97371a9ddfb56f459a36c00b9fb865'
            or measured['actual_GPU_capture'] is not True or measured['partial'] is not False
            or measured['source_manifest_unchanged_during_capture'] is not True):
        raise ValueError('W measured chronology or full hardware-capture scope disagrees')
    sources = {path.relative_to(ROOT).as_posix() for directory in ('solvefinite','tests','examples')
               for path in (ROOT/directory).rglob('*')
               if path.is_file() and path.suffix in ('.py','.wgsl','.json')}
    sources.add('tools/capture_welip_evidence.py')
    sources.update('docs/evidence/'+directory+'/'+name
                   for directory in ('welip-v1','organogram-v1','growth-v1')
                   for name in ('reference-builder.py','formal-reference.json'))
    if set(measured['source_sha256_lf']) != sources:
        raise ValueError('W capture requires the complete current source inventory')
    for name, expected in measured['source_sha256_lf'].items():
        if hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
            raise ValueError('W capture source changed: '+name)
    if set(measured['report_sha256_lf']) != {'full-tests.txt','conformance.json'}:
        raise ValueError('W capture requires full tests and complete conformance')
    for name, expected in measured['report_sha256_lf'].items():
        if hashlib.sha256((WELIP_EVIDENCE/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
            raise ValueError('W capture report changed: '+name)
    log = (WELIP_EVIDENCE/'full-tests.txt').read_text(encoding='utf-8')
    match = re.search(r'Ran (\d+) tests in ([0-9.]+)s',log)
    tests = measured['tests']
    if (match is None or (int(match[1]),float(match[2])) != (tests['passed'],tests['elapsed_seconds'])
            or tests['skipped'] != 0 or tests['complete_suite'] is not True
            or sum(tests['module_counts'].values()) != tests['passed']
            or tests['actual_device_methods'].get('WelipGpuTests') != 9
            or not log.rstrip().endswith('OK') or '... skipped' in log or 'skipped=' in log):
        raise ValueError('W displayed counts require a complete zero-skip suite log')
    for module, count in tests['module_counts'].items():
        if len(re.findall(r'\('+re.escape(module)+r'\.',log)) != count:
            raise ValueError('W test module count disagrees: '+module)
    for name, count in tests['actual_device_methods'].items():
        if len(re.findall(r'\(\w+\.'+re.escape(name)+r'\.',log)) != count:
            raise ValueError('W GPU test class count disagrees: '+name)
    captured = json.loads((WELIP_EVIDENCE/'conformance.json').read_text(encoding='utf-8'))
    if (captured['format'] != 'welip-conformance-v1' or captured['formal_commit'] != formal_commit
            or captured['formal_reference_sha256_lf'] != '0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210'
            or captured['partial'] is not False or captured['actual_GPU_capture'] is not True
            or len(captured['checks']) != 14 or measured['conformance_checks_passed'] != 14
            or any(value is not True for value in captured['checks'].values())
            or len(captured['disabled_legacy_CPU_compilers']) != 11
            or len(captured['disabled_OG_CPU_producers']) != 6
            or captured['disabled_state_producer'] != 'solvefinite.welip.encode_state'
            or captured['adapter'] != measured['environment']['adapter']
            or captured['adapter']['adapter_type'] not in ('DiscreteGPU','IntegratedGPU')):
        raise ValueError('W conformance scope, hardware or CPU-producer guards disagree')

    def canonical(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                        ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()

    for name in ('main_lifecycle','mirrored_lifecycle','capacity8_lifecycle'):
        expected = reference[name]
        cpu = captured['CPU']['lifecycles'][name]
        gpu = captured['GPU']['lifecycles'][name]
        if (cpu['archive'] != gpu['archive'] or gpu['archive']['operations'] != expected['operations']
                or gpu['archive']['config'] != expected['config'] or gpu['archive']['expected'] != expected['expected']
                or gpu['results'] != expected['results'] or cpu['results'] != expected['results']
                or cpu['latest_retry_receipts'] != expected['latest_retry_receipts']
                or gpu['latest_retry_receipts'] != expected['latest_retry_receipts']):
            raise ValueError('W full literal lifecycle disagrees: '+name)
        for case in (cpu,gpu):
            if (case['welip_archive_sha256'] != canonical(case['archive'])
                    or case['agent_archive_sha256'] != canonical(case['archive']['agent'])
                    or case['operation_transcript_sha256'] != expected['operation_transcript_sha256']
                    or (case['record_count'],case['fragment_count']) != (18,37)):
                raise ValueError('W literal counts or archive identities disagree: '+name)
    for profile in ('field','hadamard','growth','organogram'):
        cpu = captured['CPU']['policies'][profile]
        gpu = captured['GPU']['policies'][profile]
        if (cpu['archive'] != gpu['archive'] or gpu['archive']['agent']['expected']['status'] != 'COMPLETE'
                or gpu['terminal_response']['agent_status'] != 'COMPLETE'
                or gpu['growth_count'] != int(profile in ('growth','organogram'))):
            raise ValueError('W all-policy terminal preservation disagrees: '+profile)
    main = captured['GPU']['lifecycles']['main_lifecycle']['archive']
    if (canonical(main) != captured['welip_archive_sha256']
            or canonical(main) != measured['welip_archive_sha256']
            or canonical(main['agent']) != captured['canonical_agent_archive_sha256']
            or canonical(main['agent']) != measured['canonical_agent_archive_sha256']
            or canonical(main['agent']) != 'e2834ba2cc6b4d51f2b23f274cd9f2a0db8a4e88754ed9d2aadc76c074f134df'
            or measured['final_state'] != main['agent']['expected']
            or measured['final_W_state'] != main['expected']):
        raise ValueError('W canonical history or historical OG identity changed')
    fresh = captured['fresh_process_recovery']
    if ([row['backend'] for row in fresh['captures']] != ['gpu','cpu','gpu']
            or measured['fresh_process_backends'] != ['gpu','cpu','gpu']
            or fresh['final_archive_sha256'] != canonical(main)
            or fresh['captures'][-1]['welip_archive_sha256'] != canonical(main)
            or len({tuple(row['index_arguments']) for row in fresh['captures']}) != 3):
        raise ValueError('W fresh-process/index continuation disagrees')
    expected_faults = {'complete_output_before_mutation','complete_output_after_advance',
                       'uncertain_dispatch','save_replaced_before_error'}
    if set(captured['session_faults']) != expected_faults or set(measured['session_fault_cases']) != expected_faults:
        raise ValueError('W actual-device session failure coverage is incomplete')
    for name, case in captured['session_faults'].items():
        pure = name == 'complete_output_before_mutation'
        if case['error']['fatal'] is not (not pure) or case['recovered_response']['type'] != (
                'DUPLICATE' if name in ('complete_output_before_mutation','save_replaced_before_error') else 'RESULT'):
            raise ValueError('W failure and recovery result disagrees: '+name)
    if (measured['original_source_sha256'] != protected_sources
            or measured['eli5_pdf_unchanged_sha256'] != '06556d7bbae0de54e99f3abb9329869da1fbf085c6c1aab66d563528989c3ea0'
            or measured['eli5_pdf_unchanged_sha256'] != hashlib.sha256(
                (ROOT/'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf').read_bytes()).hexdigest()):
        raise ValueError('W changed an original source PDF or the separate ELI5 booklet')
    W_VERIFICATION, W_CONFORMANCE = measured, captured


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--font-dir',default='C:/Windows/Fonts')
    args=parser.parse_args()
    verify_retained_inputs()
    register_fonts(args.font_dir)
    build_content()
    render(args.output)
