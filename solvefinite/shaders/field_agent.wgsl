// FI1-FI8: one SDF individual, separate energy and scratch route forecasts.
// config = [count, forecast_hops, destination, hazard_or_repair_cost,
//           negative_turn, zero_turn, positive_turn, reserved].
// neighbors are four sorted canonical indices per node; seams are undirected
// row bitsets. The 12xN texture holds three field classes per neighbor slot.
// state = [left, mirror, separate_energy, admitted_actions]. Forecast groups
// bind independent scratch state; only actual movement/repair bind live state.
// output entries are [left, mirror, cost, energy, status, 0, 0, 0].

@group(0) @binding(0) var<storage, read> config: array<u32>;
@group(0) @binding(1) var<storage, read> fields: array<i32>;
@group(0) @binding(2) var<storage, read> neighbors: array<vec4<u32>>;
@group(0) @binding(3) var<storage, read> seams: array<u32>;
@group(0) @binding(4) var operator_target: texture_storage_2d<r32uint, write>;
@group(0) @binding(5) var operators: texture_2d<u32>;
@group(0) @binding(6) var<storage, read> jobs: array<vec2<u32>>;
@group(0) @binding(7) var<storage, read_write> state: array<u32>;
@group(0) @binding(8) var<storage, read_write> output: array<vec4<u32>>;

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
        (word >> 8u) & 255u, signed_field(word), ((word >> 24u) & 127u) ^ 16u);
}

fn emit(index: u32, word: u32, cost: u32, energy: u32, status: u32) {
    output[2u * index] = vec4<u32>(word, mirror_rp32(word), cost, energy);
    output[2u * index + 1u] = vec4<u32>(status, 0u, 0u, 0u);
}

// Return [next word, cost, status, reserved], without touching either state.
fn transition(word: u32, destination: u32, hazard: u32) -> vec4<u32> {
    let source = (word >> 8u) & 255u;
    if source >= config[0] || destination >= config[0] || hazard > 127u {
        return vec4<u32>(word, 0u, 1u, 0u);
    }
    var slot = 4u;
    for (var neighbor = 0u; neighbor < 4u; neighbor += 1u) {
        if neighbors[source][neighbor] == destination { slot = neighbor; }
    }
    if slot == 4u { return vec4<u32>(word, 0u, 1u, 0u); }
    let b = signed_field(word);
    let column = select(select(1u, 2u, b > 0), 0u, b < 0);
    let op = textureLoad(operators, vec2<i32>(i32(3u * slot + column), i32(source)), 0).r;
    let phase = word & 255u;
    let delta = op & 255u;
    let eta = (word >> 28u) & 1u;
    let tau = (op >> 30u) & 1u;
    let departure = select(phase + delta, phase + 256u - delta, eta != 0u) & 255u;
    let next_phase = select(departure, (256u - departure) & 255u, tau != 0u);
    let next_word = pack_rp32(next_phase, (op >> 8u) & 255u, signed_field(op),
                              1u | ((eta ^ tau) << 4u));
    return vec4<u32>(next_word, 1u + u32(abs(signed_field(op))) + hazard, 0u, 0u);
}

@compute @workgroup_size(64)
fn compile_neighbors(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= 12u * config[0] { return; }
    let source = id.x / 12u;
    let column = id.x % 3u;
    let slot = (id.x % 12u) / 3u;
    let destination = neighbors[source][slot];
    let stride = (config[0] + 31u) / 32u;
    let tau = (seams[source * stride + destination / 32u] >> (destination % 32u)) & 1u;
    let word = pack_rp32(config[4u + column], destination, fields[destination], 1u | (tau << 6u));
    textureStore(operator_target, vec2<i32>(i32(3u * slot + column), i32(source)),
                 vec4<u32>(word, 0u, 0u, 0u));
}

@compute @workgroup_size(1)
fn derive_node() {
    let node = config[2];
    emit(0u, pack_rp32(0u, node, fields[node], 0u), 0u, 0u, 0u);
}

@compute @workgroup_size(1)
fn forecast() {
    var word = state[0];
    for (var index = 0u; index < config[1]; index += 1u) {
        let result = transition(word, jobs[index].x, jobs[index].y);
        emit(index, result.x, result.y, 0u, result.z);
        if result.z != 0u { return; }
        word = result.x;
    }
    state[0] = word;
    state[1] = mirror_rp32(word);
}

@compute @workgroup_size(1)
fn advance_to() {
    let result = transition(state[0], config[2], config[3]);
    if result.z != 0u {
        emit(0u, state[0], result.y, state[2], result.z);
        return;
    }
    if result.y > state[2] {
        emit(0u, state[0], result.y, state[2], 2u);
        return;
    }
    state[0] = result.x;
    state[1] = mirror_rp32(result.x);
    state[2] -= result.y;
    state[3] += 1u;
    emit(0u, state[0], result.y, state[2], 0u);
}

@compute @workgroup_size(1)
fn repair() {
    let cost = config[3];
    if cost > state[2] {
        emit(0u, state[0], cost, state[2], 2u);
        return;
    }
    let word = state[0];
    state[0] = pack_rp32(word & 255u, (word >> 8u) & 255u,
                         signed_field(word), 6u | ((word >> 24u) & 16u));
    state[1] = mirror_rp32(state[0]);
    state[2] -= cost;
    state[3] += 1u;
    emit(0u, state[0], cost, state[2], 0u);
}
