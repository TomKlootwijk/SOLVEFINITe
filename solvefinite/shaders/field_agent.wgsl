// FI1-FI8: one SDF individual, separate energy and scratch route forecasts.
// config = [count, forecast_hops, destination, hazard_or_repair_cost,
//           negative_turn, zero_turn, positive_turn, hadamard_enabled,
//           signed_psi_sign, phase_origin, maximum_tree_visits, center].
// neighbors are four sorted canonical indices per node; seams are undirected
// row bitsets. The 12xN texture holds three field classes per neighbor slot.
// state = [left, mirror, separate_energy, admitted_actions]. Forecast groups
// bind independent scratch state; only actual movement/repair bind live state.
// output entries are [left, mirror, cost, energy, status, 0, 0, 0].

@group(0) @binding(0) var<storage, read> config: array<u32>;
@group(0) @binding(1) var<storage, read> fields: array<i32>;
struct Geometry {
    neighbors: vec4<u32>,
    directions: vec4<u32>,
    parent: u32,
    depth: u32,
    // x: four geometric seam flags in numeric-neighbor order; y: reserved.
    seam_flags: vec2<u32>,
}
struct Record { head: vec4<u32>, tail: vec4<u32> }
@group(0) @binding(2) var<storage, read> geometry: array<Geometry>;
@group(0) @binding(3) var<storage, read> seams: array<u32>;
@group(0) @binding(4) var operator_target: texture_storage_2d<r32uint, write>;
@group(0) @binding(5) var operators: texture_2d<u32>;
@group(0) @binding(6) var<storage, read> jobs: array<vec2<u32>>;
@group(0) @binding(7) var<storage, read_write> state: array<u32>;
@group(0) @binding(8) var<storage, read_write> output: array<vec4<u32>>;
@group(0) @binding(11) var<storage, read_write> records: array<Record>;
@group(0) @binding(12) var<storage, read_write> tree: array<Record>;
@group(0) @binding(13) var<storage, read_write> build_status: array<u32>;
@group(0) @binding(14) var<storage, read> routing_gains: array<i32>;
@group(0) @binding(15) var<storage, read_write> routing_table: array<u32>;

fn key_compare(left: Record, right: Record) -> i32 {
    for (var component = 0u; component < 4u; component += 1u) {
        if left.head[component] < right.head[component] { return -1; }
        if left.head[component] > right.head[component] { return 1; }
    }
    if left.tail.x < right.tail.x { return -1; }
    return select(0, 1, left.tail.x > right.tail.x);
}

fn field_record(node: u32) -> Record {
    let directions = geometry[node].directions;
    let gu = fields[directions.x] - fields[directions.y];
    let gv = fields[directions.z] - fields[directions.w];
    var a = u32(abs(gu));
    var b = u32(abs(gv));
    while b != 0u { let remainder = a % b; a = b; b = remainder; }
    var primitive = vec2<i32>(1, 0);
    if a != 0u { primitive = vec2<i32>(gu, gv) / i32(a); }
    primitive *= bitcast<i32>(config[8]);
    var theta = config[9];
    var cursor = node;
    for (var step = 0u; step < config[0]; step += 1u) {
        let parent = geometry[cursor].parent;
        if parent == cursor { break; }
        let field = fields[parent];
        let column = select(select(1u, 2u, field > 0), 0u, field < 0);
        theta = (theta + config[4u + column]) & 255u;
        cursor = parent;
    }
    return Record(vec4<u32>(u32(primitive.x + 2), u32(primitive.y + 2),
                  31u - countLeadingZeros(geometry[node].depth + 1u), theta),
                  vec4<u32>(node, u32(gu * gu + gv * gv), u32(gu + 2), u32(gv + 2)));
}

// [physical preorder row, left child, right child, reserved]. Numeric ranks
// are computed on-device, not uploaded as a node-to-row indirection table.
fn ranked_position(needle: Record) -> vec4<u32> {
    var rank = 0u;
    for (var node = 0u; node < config[0]; node += 1u) {
        rank += select(0u, 1u, key_compare(records[node], needle) < 0);
    }
    var lo = 0u;
    var hi = config[0];
    var slot = 0u;
    for (var step = 0u; step < config[10]; step += 1u) {
        let middle = (lo + hi - 1u) / 2u;
        if rank == middle {
            return vec4<u32>(slot, select(256u, slot + 1u, lo < middle),
                select(256u, slot + 1u + middle - lo, middle + 1u < hi), 0u);
        }
        if rank < middle { hi = middle; slot += 1u; }
        else { slot += 1u + middle - lo; lo = middle + 1u; }
    }
    return vec4<u32>(256u);
}

@compute @workgroup_size(64)
fn build_keys(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x < config[0] { records[id.x] = field_record(id.x); }
}

@compute @workgroup_size(64)
fn build_tree(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= config[0] { return; }
    let key = records[id.x];
    let position = ranked_position(key);
    if position.x < config[0] {
        tree[position.x] = Record(key.head, vec4<u32>(id.x, position.y, position.z, 0u));
    }
}

// Every consumer follows actual links. Rank validation only verifies the
// visited row's storage identity; it cannot substitute for successful search.
fn resolve_row(node: u32) -> u32 {
    if node >= config[0] { return 256u; }
    let needle = records[node];
    let expected = field_record(node);
    if any(needle.head != expected.head) || any(needle.tail != expected.tail) { return 256u; }
    var row = 0u;
    var lower = 256u;
    var upper = 256u;
    for (var visit = 0u; visit < config[10]; visit += 1u) {
        if row >= config[0] { return 256u; }
        let current = tree[row];
        if current.tail.x >= config[0] || current.tail.w != 0u { return 256u; }
        if (current.tail.y >= config[0] && current.tail.y != 256u)
            || (current.tail.z >= config[0] && current.tail.z != 256u) { return 256u; }
        if key_compare(current, records[current.tail.x]) != 0 { return 256u; }
        if lower != 256u && key_compare(current, tree[lower]) <= 0 { return 256u; }
        if upper != 256u && key_compare(current, tree[upper]) >= 0 { return 256u; }
        let comparison = key_compare(needle, current);
        if comparison == 0 {
            let position = ranked_position(needle);
            if current.tail.x != node || position.x != row
                || position.y != current.tail.y || position.z != current.tail.z { return 256u; }
            return row;
        }
        if comparison < 0 { upper = row; row = current.tail.y; }
        else { lower = row; row = current.tail.z; }
    }
    return 256u;
}

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

fn valid_movement(word: u32, source: u32, destination: u32, column: u32) -> bool {
    var slot = 4u;
    for (var index = 0u; index < 4u; index += 1u) {
        if geometry[source].neighbors[index] == destination { slot = index; }
    }
    if slot == 4u { return false; }
    let tau = (geometry[source].seam_flags.x >> slot) & 1u;
    // Decode each numerical/metadata lane independently of the pack helper.
    return (countOneBits(word) & 1u) == 0u
        && (word & 255u) == config[4u + column]
        && ((word >> 8u) & 255u) == destination
        && signed_field(word) == fields[destination]
        && ((word >> 24u) & 127u) == (1u | (tau << 6u));
}

fn valid_cost(word: u32, source: u32, bank: u32) -> bool {
    return (countOneBits(word) & 1u) == 0u
        && (word & 255u) == bank && ((word >> 8u) & 255u) == source
        && ((word >> 24u) & 127u) == 0u
        && signed_field(word) >= 0 && signed_field(word) <= 80;
}

fn directional_penalty(source: u32, destination: u32, bank: u32) -> i32 {
    let record = records[source];
    let gradient = vec2<i32>(i32(record.tail.z) - 2, i32(record.tail.w) - 2);
    let psi = vec2<i32>(i32(record.head.x) - 2, i32(record.head.y) - 2);
    let gains = vec2<i32>(routing_gains[2u * bank], routing_gains[2u * bank + 1u]);
    let response = gains * (vec2<i32>(1) + psi * psi) * gradient;
    let directions = geometry[source].directions;
    var projection = 0;
    if destination == directions.x { projection = response.x; }
    else if destination == directions.y { projection = -response.x; }
    else if destination == directions.z { projection = response.y; }
    else if destination == directions.w { projection = -response.y; }
    return max(abs(response.x), abs(response.y)) - projection;
}

// Return [next word, cost, status, reserved], without touching either state.
fn transition(word: u32, destination: u32, hazard: u32) -> vec4<u32> {
    let source = (word >> 8u) & 255u;
    if source >= config[0] || destination >= config[0] || hazard > 127u {
        return vec4<u32>(word, 0u, 1u, 0u);
    }
    var slot = 4u;
    for (var neighbor = 0u; neighbor < 4u; neighbor += 1u) {
        if geometry[source].neighbors[neighbor] == destination { slot = neighbor; }
    }
    if slot == 4u { return vec4<u32>(word, 0u, 1u, 0u); }
    let row = resolve_row(source);
    if row >= config[0] { return vec4<u32>(word, 0u, 3u, 0u); }
    let b = signed_field(word);
    let column = select(select(1u, 2u, b > 0), 0u, b < 0);
    let phase = word & 255u;
    let eta = (word >> 28u) & 1u;
    let intrinsic = select(phase, (256u - phase) & 255u, eta != 0u);
    let bank = intrinsic / 64u;
    var penalty = 0u;
    var x = 3u * slot + column;
    var y = row;
    if config[7] != 0u { x = 2u * x; y += bank * config[0]; }
    let op = textureLoad(operators, vec2<i32>(i32(x), i32(y)), 0).r;
    if ((op >> 8u) & 255u) != destination { return vec4<u32>(word, 0u, 3u, 0u); }
    if config[7] != 0u {
        let cost_word = textureLoad(operators, vec2<i32>(i32(x + 1u), i32(y)), 0).r;
        if !valid_movement(op, source, destination, column)
            || !valid_cost(cost_word, source, bank) { return vec4<u32>(word, 0u, 4u, 0u); }
        penalty = u32(signed_field(cost_word));
    }
    let delta = op & 255u;
    let tau = (op >> 30u) & 1u;
    let departure = select(phase + delta, phase + 256u - delta, eta != 0u) & 255u;
    let next_phase = select(departure, (256u - departure) & 255u, tau != 0u);
    let next_word = pack_rp32(next_phase, (op >> 8u) & 255u, signed_field(op),
                              1u | ((eta ^ tau) << 4u));
    return vec4<u32>(next_word, 1u + u32(abs(signed_field(op))) + hazard + penalty, 0u, 0u);
}

@compute @workgroup_size(64)
fn compile_neighbors(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= config[0] { return; }
    let source = id.x;
    let row = resolve_row(source);
    build_status[source] = select(3u, 0u, row < config[0]);
    if row >= config[0] { return; }
    let stride = (config[0] + 31u) / 32u;
    for (var slot = 0u; slot < 4u; slot += 1u) {
        let destination = geometry[source].neighbors[slot];
        let tau = (seams[source * stride + destination / 32u] >> (destination % 32u)) & 1u;
        for (var column = 0u; column < 3u; column += 1u) {
            let word = pack_rp32(config[4u + column], destination, fields[destination], 1u | (tau << 6u));
            textureStore(operator_target, vec2<i32>(i32(3u * slot + column), i32(row)),
                         vec4<u32>(word, 0u, 0u, 0u));
        }
    }
}

@compute @workgroup_size(64)
fn compile_hadamard(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= config[0] { return; }
    let source = id.x;
    let row = resolve_row(source);
    build_status[source] = select(3u, 0u, row < config[0]);
    if row >= config[0] { return; }
    let stride = (config[0] + 31u) / 32u;
    for (var bank = 0u; bank < 4u; bank += 1u) {
        for (var slot = 0u; slot < 4u; slot += 1u) {
            let destination = geometry[source].neighbors[slot];
            let tau = (seams[source * stride + destination / 32u] >> (destination % 32u)) & 1u;
            let penalty = directional_penalty(source, destination, bank);
            for (var column = 0u; column < 3u; column += 1u) {
                let location = vec2<i32>(i32(6u * slot + 2u * column), i32(bank * config[0] + row));
                let movement = pack_rp32(config[4u + column], destination, fields[destination], 1u | (tau << 6u));
                let cost_word = pack_rp32(bank, source, penalty, 0u);
                textureStore(operator_target, location, vec4<u32>(movement, 0u, 0u, 0u));
                textureStore(operator_target, location + vec2<i32>(1, 0), vec4<u32>(cost_word, 0u, 0u, 0u));
            }
        }
    }
}

@compute @workgroup_size(64)
fn export_routing(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= config[0] { return; }
    let source = id.x;
    let row = resolve_row(source);
    if row >= config[0] { build_status[source] = 3u; return; }
    let source_field = fields[source];
    let source_class = select(select(1u, 2u, source_field > 0), 0u, source_field < 0);
    for (var bank = 0u; bank < 4u; bank += 1u) {
        for (var slot = 0u; slot < 4u; slot += 1u) {
            let destination = geometry[source].neighbors[slot];
            let expected = directional_penalty(source, destination, bank);
            var first_penalty = 0;
            for (var column = 0u; column < 3u; column += 1u) {
                let location = vec2<i32>(i32(6u * slot + 2u * column), i32(bank * config[0] + row));
                let movement = textureLoad(operators, location, 0).r;
                let cost_word = textureLoad(operators, location + vec2<i32>(1, 0), 0).r;
                if !valid_movement(movement, source, destination, column)
                    || !valid_cost(cost_word, source, bank) || signed_field(cost_word) != expected {
                    build_status[source] = 4u; return;
                }
                if column == 0u { first_penalty = signed_field(cost_word); }
                else if signed_field(cost_word) != first_penalty { build_status[source] = 4u; return; }
                if bank == 0u && slot == 0u && column == source_class {
                    routing_table[16u * config[0] + source] = movement & 255u;
                }
            }
            routing_table[16u * source + 4u * bank + slot] = u32(first_penalty);
        }
    }
}

@compute @workgroup_size(1)
fn lookup_node() {
    let row = resolve_row(config[2]);
    output[0] = vec4<u32>(row, config[2], 0u, 0u);
    output[1] = vec4<u32>(select(3u, 0u, row < config[0]), 0u, 0u, 0u);
}

@compute @workgroup_size(1)
fn derive_node() {
    let node = config[2];
    if resolve_row(node) >= config[0] { emit(0u, 0u, 0u, 0u, 3u); return; }
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
