// RP32-v1 world derivation and shared simulated movement, using exact integers.
//
// Group 0 ABI, validated and populated by the host:
//   0: op_lut, 2 x 4 r32uint texture. Texel (branch, row) is the packed
//      operator pack(phase_delta, branch + 1, 0, GROW). textureLoad performs
//      an integer texel fetch; no sampler, interpolation, or float conversion.
//   1: config, read-only u32 storage [world_seed, field_change_0,
//      field_change_1, job_count]. Changes are two's-complement i32 clipped
//      to [-255, 255], which exactly preserves signed-byte saturation.
//   2: jobs, read-only vec4<u32> storage:
//      derive:   (path_bits, depth, 0, 0); bits consumed most significant first.
//      forecast: (resident_node_index, final_path_bit_or_0, hazard, 0).
//   3: resident_nodes, read/write vec4<u32> storage (left, mirror, 0, 0).
//   4: output, read/write vec4<u32> storage (left, mirror, entry_cost, status).
//   5: state, read/write u32 storage [agent_left, agent_mirror, total_cost,
//      status]. Initialize cost/status to zero for an independent forecast.
//
// Both entries use RP32 low-word/high-word order. Host validation covers word
// parity, full mirror equality, buffer extents, depth <= 32, branch <= 1, and
// hazard <= 127. A forecast has exactly one advancing invocation: jobs are
// sequential steps of one canonical agent, not independently acting agents.
// Status 0 means success; status 1 means insufficient energy. A failed step
// emits the unchanged last valid pair and attempted cost, retains accumulated
// successful cost in state, and leaves later output entries untouched.

@group(0) @binding(0) var op_lut: texture_2d<u32>;
@group(0) @binding(1) var<storage, read> config: array<u32>;
@group(0) @binding(2) var<storage, read> jobs: array<vec4<u32>>;
@group(0) @binding(3) var<storage, read_write> resident_nodes: array<vec4<u32>>;
@group(0) @binding(4) var<storage, read_write> output: array<vec4<u32>>;
@group(0) @binding(5) var<storage, read_write> state: array<u32>;

fn signed_field(word: u32) -> i32 {
    let byte = (word >> 16u) & 255u;
    if (byte >= 128u) {
        return i32(byte) - 256;
    }
    return i32(byte);
}

fn pack_rp32(phase: u32, selector: u32, field: i32, metadata: u32) -> u32 {
    let payload = (phase & 255u)
        | ((selector & 255u) << 8u)
        | ((bitcast<u32>(field) & 255u) << 16u)
        | ((metadata & 127u) << 24u);
    return payload | ((countOneBits(payload) & 1u) << 31u);
}

fn mirror_rp32(word: u32) -> u32 {
    let phase = (256u - (word & 255u)) & 255u;
    let selector = (word >> 8u) & 255u;
    let metadata = ((word >> 24u) & 127u) ^ 16u;
    return pack_rp32(phase, selector, signed_field(word), metadata);
}

fn moved_phase(phase: u32, metadata: u32, delta: u32) -> u32 {
    if ((metadata & 16u) != 0u) {
        return (phase + 256u - delta) & 255u;
    }
    return (phase + delta) & 255u;
}

fn lookup_operator(branch: u32, row: u32) -> u32 {
    return textureLoad(op_lut, vec2<i32>(i32(branch), i32(row)), 0).r;
}

@compute @workgroup_size(64)
fn derive(@builtin(global_invocation_id) invocation: vec3<u32>) {
    let index = invocation.x;
    if (index >= config[3]) {
        return;
    }
    let path_bits = jobs[index].x;
    let depth = jobs[index].y;
    var word = config[0];
    for (var level = 0u; level < depth; level += 1u) {
        // A depth-zero path never enters the loop. At depth 32 the greatest
        // shift is 31, so the complete binary derivation address is retained.
        let branch = (path_bits >> (depth - 1u - level)) & 1u;
        let phase = word & 255u;
        let selector = (word >> 8u) & 255u;
        let metadata = (word >> 24u) & 127u;
        let row = (selector ^ (phase >> 6u)) & 3u;
        let packed_operator = lookup_operator(branch, row);
        let delta = packed_operator & 255u;
        let growth = (packed_operator >> 8u) & 255u;
        let opcode = (packed_operator >> 24u) & 7u;
        let next_phase = moved_phase(phase, metadata, delta);
        let next_selector = (3u * selector + growth) & 255u;
        let next_field = clamp(signed_field(word) + bitcast<i32>(config[1u + branch]),
                               -128, 127);
        word = pack_rp32(next_phase, next_selector, next_field,
                         (metadata & 120u) | opcode);
    }
    resident_nodes[index] = vec4<u32>(word, mirror_rp32(word), 0u, 0u);
}

@compute @workgroup_size(1)
fn forecast(@builtin(global_invocation_id) invocation: vec3<u32>) {
    if (any(invocation != vec3<u32>(0u))) {
        return;
    }
    var word = state[0];
    var total_cost = state[2];
    for (var index = 0u; index < config[3]; index += 1u) {
        let job = jobs[index];
        let node = resident_nodes[job.x].x;
        let cost = 1u + u32(abs(signed_field(node))) / 8u + job.z;
        let energy = signed_field(word);
        if (energy < i32(cost)) {
            output[index] = vec4<u32>(word, mirror_rp32(word), cost, 1u);
            state[3] = 1u;
            return;
        }
        let phase = word & 255u;
        let selector = (word >> 8u) & 255u;
        let metadata = (word >> 24u) & 127u;
        let node_selector = (node >> 8u) & 255u;
        let row = (selector ^ node_selector ^ (phase >> 6u)) & 3u;
        let delta = lookup_operator(job.y, row) & 255u;
        let next_phase = moved_phase(phase, metadata, delta);
        word = pack_rp32(next_phase, node_selector, energy - i32(cost),
                         (metadata & 120u) | 1u);
        let mirrored = mirror_rp32(word);
        total_cost += cost;
        output[index] = vec4<u32>(word, mirrored, cost, 0u);
        state[0] = word;
        state[1] = mirrored;
        state[2] = total_cost;
        state[3] = 0u;
    }
}
