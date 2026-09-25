// TK-LPLUT-SDF-1.0 / TK-LPLUT-KLEIN-1.0: intrinsic distances and RP32 transport.
// All addresses are manifest indices, not Cartesian positions.
// Each entry point uses an automatically inferred subset of this group:
//  0 configuration [node_count, batch_ticks, max_ticks, reserved]
//  1 node signs; 2 dense row-major edge lengths (zero means no edge)
//  3 previous unsigned distances; 4 next unsigned distances
//  5 signed field codes; 6 row-major (successor, phase increment) rules
//  7 operator texture storage view; 8 sampled integer operator view
//  9 persistent [left RP32, right RP32, tick, reserved]
// 10 batch output pairs. Distances and intermediate sums are widened u32.
// 11 undirected seam adjacency, ceil(node_count / 32) u32 words per row.

@group(0) @binding(0) var<storage, read> config: array<u32>;
@group(0) @binding(1) var<storage, read> signs: array<i32>;
@group(0) @binding(2) var<storage, read> weights: array<u32>;
@group(0) @binding(3) var<storage, read> previous: array<u32>;
@group(0) @binding(4) var<storage, read_write> following: array<u32>;
@group(0) @binding(5) var<storage, read_write> fields: array<i32>;
@group(0) @binding(6) var<storage, read> rules: array<vec2<u32>>;
@group(0) @binding(7) var operator_target: texture_storage_2d<r32uint, write>;
@group(0) @binding(8) var operators: texture_2d<u32>;
@group(0) @binding(9) var<storage, read_write> state: array<u32>;
@group(0) @binding(10) var<storage, read_write> output: array<vec2<u32>>;
@group(0) @binding(11) var<storage, read> seams: array<u32>;

const INFINITY: u32 = 0x3fffffffu;

fn pack_rp32(r: u32, g: u32, b: i32, a: u32) -> u32 {
    let word = (r & 255u) | ((g & 255u) << 8u)
        | ((bitcast<u32>(b) & 255u) << 16u) | ((a & 127u) << 24u);
    return word | ((countOneBits(word) & 1u) << 31u);
}

fn signed_field(word: u32) -> i32 {
    let code = (word >> 16u) & 255u;
    return select(i32(code), i32(code) - 256, code >= 128u);
}

fn mirror_rp32(word: u32) -> u32 {
    return pack_rp32((256u - (word & 255u)) & 255u,
                     (word >> 8u) & 255u, signed_field(word),
                     ((word >> 24u) & 127u) ^ 16u);
}

@compute @workgroup_size(64)
fn initialize_distances(@builtin(global_invocation_id) id: vec3<u32>) {
    let node = id.x;
    if node >= config[0] { return; }
    following[node] = select(INFINITY, 0u, signs[node] == 0);
}

// One synchronous Bellman relaxation. The host binds distinct previous and
// following buffers and ends this pass before submitting the next round.
@compute @workgroup_size(64)
fn relax_distances(@builtin(global_invocation_id) id: vec3<u32>) {
    let node = id.x;
    let count = config[0];
    if node >= count { return; }
    var best = previous[node];
    for (var neighbor = 0u; neighbor < count; neighbor += 1u) {
        let length = weights[node * count + neighbor];
        let known = previous[neighbor];
        if length > 0u && known < INFINITY && length < INFINITY - known {
            best = min(best, known + length);
        }
    }
    following[node] = best;
}

@compute @workgroup_size(64)
fn write_fields(@builtin(global_invocation_id) id: vec3<u32>) {
    let node = id.x;
    if node >= config[0] { return; }
    // Values remain widened here. The host independently certifies the exact
    // field and RP32 range before permitting operator texture compilation.
    fields[node] = signs[node] * i32(previous[node]);
}

@compute @workgroup_size(64)
fn compile_operators(@builtin(global_invocation_id) id: vec3<u32>) {
    let slot = id.x;
    if slot >= 3u * config[0] { return; }
    let rule = rules[slot];
    let source = slot / 3u;
    let stride = (config[0] + 31u) / 32u;
    let tau = (seams[source * stride + rule.x / 32u] >> (rule.x % 32u)) & 1u;
    // Operator bit 6 holds relative edge transport; its orientation bit is 0.
    let word = pack_rp32(rule.y, rule.x, fields[rule.x], 1u | (tau << 6u));
    textureStore(operator_target, vec2<i32>(i32(slot % 3u), i32(slot / 3u)),
                 vec4<u32>(word, 0u, 0u, 0u));
}

// One individual's closed chain. No host-supplied action sequence is involved:
// each newly produced G/B pair selects the next integer texture operator.
@compute @workgroup_size(1)
fn advance_ticks(@builtin(global_invocation_id) id: vec3<u32>) {
    if any(id != vec3<u32>(0u, 0u, 0u)) { return; }
    var word = state[0];
    for (var tick = 0u; tick < config[1]; tick += 1u) {
        let b = signed_field(word);
        let column = select(select(1u, 2u, b > 0), 0u, b < 0);
        let op = textureLoad(operators,
            vec2<i32>(i32(column), i32((word >> 8u) & 255u)), 0).r;
        let phase = word & 255u;
        let delta = op & 255u;
        let metadata = (word >> 24u) & 127u;
        let departure_phase = select(phase + delta, phase + 256u - delta,
                                     (metadata & 16u) != 0u) & 255u;
        let tau = (op >> 30u) & 1u;
        let next_phase = select(departure_phase, (256u - departure_phase) & 255u,
                                tau != 0u);
        // Only STEP and the transported orientation enter live metadata.
        let next_metadata = 1u | ((metadata & 16u) ^ (tau << 4u));
        word = pack_rp32(next_phase, (op >> 8u) & 255u,
                         signed_field(op), next_metadata);
        output[tick] = vec2<u32>(word, mirror_rp32(word));
    }
    state[0] = word;
    state[1] = mirror_rp32(word);
    state[2] += config[1];
}
