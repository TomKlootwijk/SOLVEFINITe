"""OG1--OG8: finite original-context branching and certified generated fields.

The grammar front end is host work. The CPU interpreter is a producer; the
separate admission checker verifies supplied trajectories and fields without
calling that producer, a field evaluator, or a generated recipe reconstructor.
Recipes retain only immutable original inputs, never an eager trajectory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
from math import gcd
import re

from .field import FieldManifest, PROFILE_V2, certify_field, evaluate_field
from .hadamard import HadamardBinding
from .rp32 import Opcode, pack, pair, unpack, unpair
from .runtime import _integer, _keys


PROFILE = "klein-branch-organogram-v1"
WORLD_PROFILE = "klein-organogram-world-v1"
DERIVATION_PROFILE = "klein-organogram-derivation-v1"
TAPE_PROFILE = "OG-TAPE32-v1"
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
TERMINALS = {"F": 1, "+": 1, "-": 1, "[": 0, "]": 0, "R": 1, "S": 0, "SCALE": 1}
_OPCODES = tuple(TERMINALS)
_DIRECTIONS = ("u+", "v+", "u-", "v-")
_VECTORS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected a finite JSON document") from exc


def derivation_sha256(document: dict) -> str:
    return sha256(canonical_bytes(document)).hexdigest()


def _same(actual, expected, label):
    # Canonical comparison also distinguishes bool/float from exact integers.
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ValueError(f"{label} disagrees with the original context and tape")


def _json_shape(value, depth=0):
    """A supplied derivation uses exact JSON containers, never coercions."""
    if depth > 8:
        raise ValueError("Derivation containers exceed the finite document depth")
    if type(value) is dict:
        if len(value) > 8 or any(type(key) is not str for key in value):
            raise ValueError("Derivation object keys must be strings")
        for item in value.values():
            _json_shape(item, depth + 1)
    elif type(value) is list:
        if len(value) > 4096:
            raise ValueError("Derivation array exceeds the maximum finite work bound")
        for item in value:
            _json_shape(item, depth + 1)
    elif type(value) not in (str, int, bool, type(None)):
        raise ValueError("Derivation requires exact JSON containers and integer numbers")


def _array(value, minimum, maximum, label):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} requires a JSON array of {minimum}..{maximum} entries")


def _digest(value):
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError("prefix_sha256 requires 64 lowercase hexadecimal digits")


def _pair_lanes(value, metadata=None):
    if (type(value) is not str or len(value) != 16
            or any(character not in "0123456789ABCDEF" for character in value)):
        raise ValueError("Pair requires 16 uppercase hexadecimal digits")
    lanes = unpack(unpair(int(value, 16))[0])
    if metadata is not None and lanes[3] not in (metadata, metadata | 16):
        raise ValueError("Pair has an invalid opcode or reserved metadata")
    return lanes


def _token(symbol, *args):
    return {"symbol": symbol, "args": list(args)}


def _default_document():
    first = [_token("["), _token("R", 1), _token("+", 1), _token("B", 1),
             _token("["), _token("SCALE", 1), _token("-", 10), _token("F", 2),
             _token("S"), _token("R", 2), _token("]"), _token("]"),
             _token("["), _token("-", 1), _token("B", 2), _token("]")]
    later = [_token("["), _token("R", 1), _token("-", 1), _token("B", 1),
             _token("["), _token("SCALE", 1), _token("+", 1), _token("F", 1),
             _token("S"), _token("R", 2), _token("]"), _token("]"),
             _token("["), _token("+", 1), _token("B", 2), _token("]")]
    parameter = {"arg": 0, "mul": 1, "add": 0}
    return {"format": PROFILE, "max_epochs": 1, "cost": 1,
            "symbols": [{"name": "A", "arity": 1}, {"name": "B", "arity": 1}, {"name": "D", "arity": 0}],
            "axiom": [_token("A", {"context": "tick", "mul": 1, "add": 0}), _token("D")],
            "rules": [
                {"symbol": "A", "guards": [{"arg": 0, "op": "xor_eq", "mask": 1, "value": 4}], "rhs": first},
                {"symbol": "A", "guards": [], "rhs": later},
                {"symbol": "B", "guards": [{"arg": 0, "op": "eq", "value": 1}],
                 "rhs": [_token("F", parameter), _token("S")]},
                {"symbol": "B", "guards": [{"arg": 0, "op": "ge", "value": 1}],
                 "rhs": [_token("F", parameter), _token("S"), _token("R", 2)]},
                {"symbol": "D", "guards": [], "rhs": []}],
            "generations": 2,
            "limits": {"max_symbols": 128, "max_steps": 128, "max_balls": 16, "max_stack": 8}}


def _expression_schema(value, kind, arity=None):
    if type(value) is int:
        _integer(value, I32_MIN, I32_MAX, "literal parameter")
        return
    _keys(value, {kind, "mul", "add"}, "Parameter expression")
    _integer(value["mul"], -32768, 32767, "expression multiplier")
    _integer(value["add"], I32_MIN, I32_MAX, "expression addend")
    if kind == "context":
        if type(value[kind]) is not str or value[kind] not in ("tick", "epoch", "phase", "field"):
            raise ValueError("Unknown original context input")
    else:
        _integer(value[kind], 0, arity - 1, "argument index")


def _token_schema(value, arities, kind, arity=None):
    _keys(value, {"symbol", "args"}, "Grammar token")
    symbol = value["symbol"]
    if type(symbol) is not str or symbol not in arities:
        raise ValueError("Grammar token names an undeclared symbol")
    _array(value["args"], arities[symbol], arities[symbol], "Token arguments")
    for argument in value["args"]:
        _expression_schema(argument, kind, arity)


def _binding_schema(value):
    _keys(value, {"format", "max_epochs", "cost", "symbols", "axiom", "rules", "generations", "limits"},
          "Organogram binding")
    if type(value["format"]) is not str or value["format"] != PROFILE:
        raise ValueError("Unsupported organogram format")
    _integer(value["max_epochs"], 0, 4, "max_epochs")
    _integer(value["cost"], 1, 127, "organogram cost")
    _integer(value["generations"], 0, 8, "generations")
    _array(value["symbols"], 1, 16, "Nonterminal declarations")
    arities = dict(TERMINALS)
    for declaration in value["symbols"]:
        _keys(declaration, {"name", "arity"}, "Symbol declaration")
        name = declaration["name"]
        if (type(name) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", name) is None
                or name in arities):
            raise ValueError("Nonterminal name is invalid, reserved or duplicated")
        _integer(declaration["arity"], 0, 4, "nonterminal arity")
        arities[name] = declaration["arity"]
    _array(value["axiom"], 1, 32, "Axiom")
    for item in value["axiom"]:
        _token_schema(item, arities, "context")
    _array(value["rules"], 0, 64, "Rules")
    for rule in value["rules"]:
        _keys(rule, {"symbol", "guards", "rhs"}, "Production rule")
        name = rule["symbol"]
        if type(name) is not str or name not in arities or name in TERMINALS:
            raise ValueError("Only a declared nonterminal can be rewritten")
        _array(rule["guards"], 0, 8, "Rule guards")
        for guard in rule["guards"]:
            if type(guard) is not dict or type(guard.get("op")) is not str:
                raise ValueError("Invalid guard")
            operator = guard["op"]
            _keys(guard, {"arg", "op", "mask", "value"} if operator == "xor_eq" else {"arg", "op", "value"}, "Guard")
            _integer(guard["arg"], 0, arities[name] - 1, "guard argument")
            if operator == "xor_eq":
                _integer(guard["mask"], 0, (1 << 32) - 1, "XOR mask")
                _integer(guard["value"], 0, (1 << 32) - 1, "XOR result")
            elif operator in ("eq", "ne", "lt", "le", "gt", "ge"):
                _integer(guard["value"], I32_MIN, I32_MAX, "guard comparison")
            else:
                raise ValueError("Unknown guard operator")
        _array(rule["rhs"], 0, 32, "Production right-hand side")
        for item in rule["rhs"]:
            _token_schema(item, arities, "arg", arities[name])
    limits = value["limits"]
    _keys(limits, {"max_symbols", "max_steps", "max_balls", "max_stack"}, "Grammar limits")
    for name, lower, upper in (("max_symbols", 1, 1024), ("max_steps", 1, 4096),
                               ("max_balls", 1, 64), ("max_stack", 0, 32)):
        _integer(limits[name], lower, upper, name)


@dataclass(frozen=True, slots=True, init=False)
class OrganogramBinding:
    """Immutable grammar; returned JSON values are detached copies."""

    _canonical: bytes

    def __init__(self, max_epochs=1, cost=1, *, symbols=None, axiom=None, rules=None,
                 generations=2, limits=None, format=PROFILE):
        value = _default_document()
        value.update(max_epochs=max_epochs, cost=cost, generations=generations, format=format)
        for name, override in (("symbols", symbols), ("axiom", axiom), ("rules", rules), ("limits", limits)):
            if override is not None:
                value[name] = override
        _binding_schema(value)
        object.__setattr__(self, "_canonical", canonical_bytes(value))

    def to_dict(self):
        return json.loads(self._canonical)

    @classmethod
    def from_dict(cls, value):
        _binding_schema(value)
        result = object.__new__(cls)
        object.__setattr__(result, "_canonical", canonical_bytes(value))
        return result

    @property
    def max_epochs(self):
        return self.to_dict()["max_epochs"]

    @property
    def cost(self):
        return self.to_dict()["cost"]

    @property
    def generations(self):
        return self.to_dict()["generations"]

    @property
    def limits(self):
        return self.to_dict()["limits"]

    @property
    def format(self):
        return PROFILE


@dataclass(frozen=True, slots=True)
class StageContext:
    epoch: int
    tick: int
    start_pair: str
    prefix_sha256: str

    def __post_init__(self):
        _integer(self.epoch, 1, 4, "stage epoch")
        _integer(self.tick, 1, I32_MAX, "original stage tick")
        _pair_lanes(self.start_pair, int(Opcode.EMIT))
        _digest(self.prefix_sha256)

    def to_dict(self):
        return {"epoch": self.epoch, "tick": self.tick, "start_pair": self.start_pair,
                "prefix_sha256": self.prefix_sha256}

    @classmethod
    def from_dict(cls, value):
        _keys(value, {"epoch", "tick", "start_pair", "prefix_sha256"}, "Stage context")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TapeInstruction:
    address: tuple[int, ...]
    symbol: str
    args: tuple[int, ...]

    def __post_init__(self):
        if (type(self.address) is not tuple or not self.address or len(self.address) > 25
                or (len(self.address) - 1) % 3):
            raise ValueError("Instruction address requires an axiom index and generation triples")
        _integer(self.address[0], 0, 31, "axiom address")
        for offset in range(1, len(self.address), 3):
            generation, rule, child = self.address[offset:offset + 3]
            _integer(generation, 1, 8, "generation address")
            _integer(rule, -1, 63, "rule address")
            _integer(child, 0, 31, "production address")
            if generation != (offset + 2) // 3 or (rule == -1 and child != 0):
                raise ValueError("Instruction address is not a sequential derivation")
        if type(self.symbol) is not str or self.symbol not in TERMINALS:
            raise ValueError("Tape can contain only terminal symbols")
        if type(self.args) is not tuple or len(self.args) != TERMINALS[self.symbol]:
            raise ValueError("Tape argument arity disagrees with its terminal")
        for value in self.args:
            _integer(value, I32_MIN, I32_MAX, "tape argument")

    def to_dict(self):
        return {"address": list(self.address), "symbol": self.symbol, "args": list(self.args)}


@dataclass(frozen=True, slots=True)
class TapeBudget:
    effective_steps: int
    balls: int
    stack_high_water: int

    def __post_init__(self):
        _integer(self.effective_steps, 0, 4096, "effective steps")
        _integer(self.balls, 1, 64, "sphere count")
        _integer(self.stack_high_water, 0, 32, "stack high water")

    def to_dict(self):
        return {"effective_steps": self.effective_steps, "balls": self.balls,
                "stack_high_water": self.stack_high_water}


def _expression(value, inputs, kind):
    result = value if type(value) is int else inputs[value[kind]] * value["mul"] + value["add"]
    _integer(result, I32_MIN, I32_MAX, "expanded parameter")
    return result


def _matches(guard, args):
    value, operator, rhs = args[guard["arg"]], guard["op"], guard["value"]
    if operator == "xor_eq":
        return ((value % (1 << 32)) ^ guard["mask"]) == rhs
    return {"eq": value == rhs, "ne": value != rhs, "lt": value < rhs,
            "le": value <= rhs, "gt": value > rhs, "ge": value >= rhs}[operator]


def compile_tape(binding: OrganogramBinding, context: StageContext) -> tuple[TapeInstruction, ...]:
    if type(binding) is not OrganogramBinding or type(context) is not StageContext:
        raise ValueError("Tape compilation requires an organogram binding and original context")
    if context.epoch > binding.max_epochs:
        raise ValueError("Context exceeds the declared organogram epochs")
    phase, _, field, metadata = _pair_lanes(context.start_pair, int(Opcode.EMIT))
    inputs = {"tick": context.tick, "epoch": context.epoch,
              "phase": (-phase if metadata & 16 else phase) % 256, "field": field}
    grammar = binding.to_dict()
    word = [(tuple((i,)), item["symbol"], tuple(_expression(a, inputs, "context") for a in item["args"]))
            for i, item in enumerate(grammar["axiom"])]
    limit = grammar["limits"]["max_symbols"]
    if len(word) > limit:
        raise ValueError("Axiom exceeds the symbol budget")
    for generation in range(1, grammar["generations"] + 1):
        following = []
        for address, symbol, args in word:
            match = next((index for index, rule in enumerate(grammar["rules"])
                          if rule["symbol"] == symbol and all(_matches(guard, args) for guard in rule["guards"])), None)
            if match is None:
                following.append((address + (generation, -1, 0), symbol, args))
            else:
                for child, item in enumerate(grammar["rules"][match]["rhs"]):
                    following.append((address + (generation, match, child), item["symbol"],
                                      tuple(_expression(a, args, "arg") for a in item["args"])))
            if len(following) > limit:
                raise ValueError("Parallel generation exceeds the symbol budget")
        word = following
    if any(symbol not in TERMINALS for _, symbol, _ in word):
        raise ValueError("Unmatched nonterminal survives the final generation")
    result = tuple(TapeInstruction(*item) for item in word)
    preflight(result, binding)
    return result


def _terminal_bounds(instruction):
    if type(instruction) is not TapeInstruction:
        raise ValueError("Expected an immutable TapeInstruction")
    bounds = {"F": (1, 256), "+": (1, 16), "-": (1, 16), "R": (1, 127), "SCALE": (0, 4)}
    if instruction.symbol in bounds:
        _integer(instruction.args[0], *bounds[instruction.symbol], "terminal argument")


def preflight(tape: tuple[TapeInstruction, ...], binding: OrganogramBinding) -> TapeBudget:
    if type(binding) is not OrganogramBinding or type(tape) is not tuple:
        raise ValueError("Preflight requires an immutable tape and organogram binding")
    limits = binding.limits
    if len(tape) > limits["max_symbols"]:
        raise ValueError("Tape exceeds symbol budget")
    radius, scale, stack = 1, 0, []
    steps = spheres = high_water = 0
    for instruction in tape:
        _terminal_bounds(instruction)
        symbol, args = instruction.symbol, instruction.args
        if symbol == "F":
            steps += args[0] * (1 << scale)
        elif symbol == "R":
            radius = args[0]
        elif symbol == "SCALE":
            scale = args[0]
        elif symbol == "S":
            _integer(radius * (1 << scale), 1, 127, "effective sphere radius")
            spheres += 1
        elif symbol == "[":
            stack.append((radius, scale))
            high_water = max(high_water, len(stack))
        elif symbol == "]":
            if not stack:
                raise ValueError("Branch stack underflow")
            radius, scale = stack.pop()
        if steps > limits["max_steps"] or spheres > limits["max_balls"] or len(stack) > limits["max_stack"]:
            raise ValueError("Tape exceeds its finite work or stack budget")
    if stack:
        raise ValueError("Unclosed branch context")
    if not spheres:
        raise ValueError("Tape emits no boundary primitive")
    return TapeBudget(steps, spheres, high_water)


def encode_tape(tape: tuple[TapeInstruction, ...]) -> tuple[int, ...]:
    if type(tape) is not tuple:
        raise ValueError("Instruction encoder requires an immutable tape")
    result = []
    for instruction in tape:
        _terminal_bounds(instruction)
        operand = instruction.args[0] if instruction.args else 0
        raw = operand | (_OPCODES.index(instruction.symbol) << 24)
        result.append(raw | ((raw.bit_count() & 1) << 31))
    return tuple(result)


def decode_instruction(word: int) -> tuple[str, tuple[int, ...]]:
    _integer(word, 0, (1 << 32) - 1, "instruction word")
    if word.bit_count() & 1 or word & 0x78FF0000:
        raise ValueError("Instruction parity or reserved lane is invalid")
    symbol, operand = _OPCODES[(word >> 24) & 7], word & 65535
    if not TERMINALS[symbol] and operand:
        raise ValueError("No-argument terminal carries a nonzero operand")
    args = (operand,) if TERMINALS[symbol] else ()
    _terminal_bounds(TapeInstruction((0,), symbol, args))
    return symbol, args


def _base_recipe(value):
    from .field_world import KleinFieldRecipe
    if type(value) is not KleinFieldRecipe:
        raise ValueError("base must be a KleinFieldRecipe")


@dataclass(frozen=True, slots=True)
class GeneratedFieldRecipe:
    base: object
    organogram: OrganogramBinding
    routing: HadamardBinding
    stages: tuple[StageContext, ...]
    version: str = WORLD_PROFILE

    def __post_init__(self):
        _base_recipe(self.base)
        if type(self.organogram) is not OrganogramBinding or type(self.routing) is not HadamardBinding:
            raise ValueError("Generated recipe requires organogram and routing bindings")
        if type(self.version) is not str or self.version != WORLD_PROFILE:
            raise ValueError("Unsupported generated recipe format")
        if type(self.stages) is not tuple or not 1 <= len(self.stages) <= self.organogram.max_epochs:
            raise ValueError("Generated recipe requires one context per admitted stage")
        previous = 0
        for epoch, context in enumerate(self.stages, 1):
            if type(context) is not StageContext or context.epoch != epoch or context.tick <= previous:
                raise ValueError("Stages require contiguous epochs and strictly increasing original ticks")
            _, node, _, _ = _pair_lanes(context.start_pair, int(Opcode.EMIT))
            if node >= self.width * self.height:
                raise ValueError("Stage start pair names an unknown node")
            previous = context.tick

    @property
    def width(self):
        return self.base.width

    @property
    def height(self):
        return self.base.height

    @property
    def center(self):
        return self.base.center

    @property
    def radius(self):
        return self.base.radius

    @property
    def turns(self):
        return self.base.turns

    @property
    def baseline_id(self):
        return self.base.baseline_id

    def domain(self):
        return self.base.domain()

    def graph(self):
        return self.base.graph()

    def index(self, path):
        return self.base.index(path)

    def to_dict(self):
        return {"format": self.version, "base": self.base.to_dict(), "organogram": self.organogram.to_dict(),
                "routing": self.routing.to_dict(), "stages": [context.to_dict() for context in self.stages]}

    @classmethod
    def from_dict(cls, value):
        from .field_world import KleinFieldRecipe
        _keys(value, {"format", "base", "organogram", "routing", "stages"}, "Generated recipe")
        _array(value["stages"], 1, 4, "Original stages")
        return cls(KleinFieldRecipe.from_dict(value["base"]), OrganogramBinding.from_dict(value["organogram"]),
                   HadamardBinding.from_dict(value["routing"]), tuple(StageContext.from_dict(item) for item in value["stages"]),
                   value["format"])

    def field_manifest_from_signs(self, signs: tuple[int, ...]) -> FieldManifest:
        """Use supplied signs with fixed geometry; performs no production."""
        domain = self.domain()
        routes = tuple((domain.step(node, "u+")[0],) * 3 for node in range(len(domain.nodes)))
        return FieldManifest(nodes=domain.nodes, edges=domain.edges, signs=signs, routes=routes,
                             turns=(self.turns,) * len(domain.nodes), profile=PROFILE_V2,
                             seams=domain.seams, topology=(self.width, self.height))

    def field_manifest(self) -> FieldManifest:
        """Explicit CPU reconstruction; device callers supply a certificate."""
        return regenerate(self).manifest


def _inputs(prior_recipe, prior_fields, binding, context, routing):
    from .field_world import KleinFieldRecipe
    if type(prior_recipe) not in (KleinFieldRecipe, GeneratedFieldRecipe):
        raise ValueError("Prior recipe must describe a Klein field")
    if type(binding) is not OrganogramBinding or type(context) is not StageContext or type(routing) is not HadamardBinding:
        raise ValueError("Invalid stage bindings or context")
    count = prior_recipe.width * prior_recipe.height
    if type(prior_fields) is not tuple or len(prior_fields) != count:
        raise ValueError("Prior fields require an immutable complete tuple")
    for value in prior_fields:
        _integer(value, -127, 127, "prior field")
    phase, node, signed, metadata = _pair_lanes(context.start_pair, int(Opcode.EMIT))
    if node >= count or prior_fields[node] != signed:
        raise ValueError("Original context disagrees with the prior field")
    if type(prior_recipe) is GeneratedFieldRecipe:
        if (prior_recipe.organogram != binding or prior_recipe.routing != routing
                or context.epoch != len(prior_recipe.stages) + 1 or context.tick <= prior_recipe.stages[-1].tick):
            raise ValueError("Stage does not extend the original recipe")
    elif context.epoch != 1:
        raise ValueError("A base field precedes only epoch one")
    return phase, node, (metadata >> 4) & 1


def _packed(phase, node, fields, orientation):
    return f"{pair(pack(phase, node, fields[node], int(Opcode.STEP) | (orientation << 4))):016X}"


def interpret_cpu(prior_recipe, prior_fields, binding, context, routing) -> dict:
    """CPU producer: generate one complete canonical derivation document."""
    from .psi import field_axes
    phase, node, orientation = _inputs(prior_recipe, prior_fields, binding, context, routing)
    tape = compile_tape(binding, context)
    domain = prior_recipe.domain()
    axes = field_axes(domain, prior_fields)
    radius, scale, branch, stack = 1, 0, (), []
    trace, segments, balls = [], [], []
    for instruction in tape:
        symbol, args, address = instruction.symbol, instruction.args, instruction.address
        if symbol == "F":
            for step in range(1, args[0] * (1 << scale) + 1):
                bank = ((-phase if orientation else phase) % 256) // 64
                axis = axes[node]
                gu, gv = axis.gradient
                pu, pv = axis.vector
                au, av = routing.gains[bank]
                q = (au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv)
                priority = tuple(range(bank, 4)) + tuple(range(bank))
                chosen = max(priority, key=lambda index: q[0] * _VECTORS[index][0] + q[1] * _VECTORS[index][1])
                destination, seam = domain.step(node, _DIRECTIONS[chosen])
                delta = prior_recipe.turns[(prior_fields[node] > 0) - (prior_fields[node] < 0) + 1]
                phase = (phase + (-delta if orientation else delta)) % 256
                if seam:
                    phase, orientation = (-phase) % 256, orientation ^ 1
                node = destination
                segments.append({"address": list(address), "branch_path": [list(item) for item in branch],
                                 "step": step, "pair": _packed(phase, node, prior_fields, orientation)})
        elif symbol in ("+", "-"):
            delta = args[0] * prior_recipe.turns[(prior_fields[node] > 0) - (prior_fields[node] < 0) + 1]
            if symbol == "-":
                delta = -delta
            phase = (phase + (-delta if orientation else delta)) % 256
        elif symbol == "R":
            radius = args[0]
        elif symbol == "SCALE":
            scale = args[0]
        elif symbol == "S":
            balls.append({"address": list(address), "branch_path": [list(item) for item in branch],
                          "center": node, "radius": radius * (1 << scale),
                          "pair": _packed(phase, node, prior_fields, orientation)})
        elif symbol == "[":
            stack.append((phase, node, orientation, radius, scale, branch))
            branch += (address,)
        elif symbol == "]":
            phase, node, orientation, radius, scale, branch = stack.pop()
        trace.append({"address": list(address), "branch_path": [list(item) for item in branch],
                      "pair": _packed(phase, node, prior_fields, orientation), "radius": radius, "scale": scale})
    return {"format": DERIVATION_PROFILE, "context": context.to_dict(),
            "tape": [instruction.to_dict() for instruction in tape], "trace": trace,
            "segments": segments, "balls": balls,
            "final_context": {"branch_path": [list(item) for item in branch],
                              "pair": _packed(phase, node, prior_fields, orientation), "radius": radius, "scale": scale}}


def certify_derivation(prior_recipe, prior_fields, binding, context, routing, document) -> str:
    """Check a supplied trajectory using direct quotient/gradient arithmetic.

    The caller establishes prior-field provenance (certify_stage does so).
    This function checks the complete derivation relative to those values. It
    never calls interpret_cpu, generated field_manifest, Psi or routing compilers.
    """
    phase, node, orientation = _inputs(prior_recipe, prior_fields, binding, context, routing)
    tape = compile_tape(binding, context)
    work = preflight(tape, binding)
    _keys(document, {"format", "context", "tape", "trace", "segments", "balls", "final_context"}, "Derivation")
    _json_shape(document)
    _same(document["format"], DERIVATION_PROFILE, "Derivation format")
    _same(document["context"], context.to_dict(), "Derivation context")
    _same(document["tape"], [instruction.to_dict() for instruction in tape], "Ordered tape")
    _array(document["trace"], len(tape), len(tape), "Terminal trace")
    _array(document["segments"], work.effective_steps, work.effective_steps, "Segments")
    _array(document["balls"], work.balls, work.balls, "Boundary primitives")
    width, height = prior_recipe.width, prior_recipe.height

    def neighbor(source, direction):
        u, v = divmod(source, height)
        du, dv = _VECTORS[direction]
        crossings, column = divmod(u + du, width)
        return column * height + ((-v - dv if crossings % 2 else v + dv) % height), crossings % 2

    # Independent word construction, including full mirror and parity.
    def state():
        def word(r, eta):
            raw = r | (node << 8) | ((prior_fields[node] & 255) << 16) | ((1 | (eta << 4)) << 24)
            return raw | ((raw.bit_count() & 1) << 31)
        return f"{word((-phase) % 256, orientation ^ 1):08X}{word(phase, orientation):08X}"

    radius, scale, branch, stack = 1, 0, (), []
    segment_index = sphere_index = 0
    for trace_index, instruction in enumerate(tape):
        address, symbol, args = instruction.address, instruction.symbol, instruction.args
        if symbol == "F":
            for step in range(1, args[0] * (1 << scale) + 1):
                adjacent = tuple(neighbor(node, direction) for direction in range(4))
                gu = prior_fields[adjacent[0][0]] - prior_fields[adjacent[2][0]]
                gv = prior_fields[adjacent[1][0]] - prior_fields[adjacent[3][0]]
                divisor = gcd(abs(gu), abs(gv))
                pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
                bank = ((-phase if orientation else phase) % 256) >> 6
                au, av = routing.gains[bank]
                qu, qv = au * (1 + pu ** 2) * gu, av * (1 + pv ** 2) * gv
                scores = (qu, qv, -qu, -qv)
                chosen = next((bank + offset) % 4 for offset in range(4)
                              if scores[(bank + offset) % 4] == max(scores))
                destination, seam = adjacent[chosen]
                column = 0 if prior_fields[node] < 0 else 1 if prior_fields[node] == 0 else 2
                intrinsic = ((-phase if orientation else phase) + prior_recipe.turns[column]) % 256
                orientation ^= seam
                phase = (-intrinsic if orientation else intrinsic) % 256
                node = destination
                _same(document["segments"][segment_index],
                      {"address": list(address), "branch_path": [list(item) for item in branch],
                       "step": step, "pair": state()}, "Segment")
                segment_index += 1
        elif symbol in ("+", "-"):
            column = 0 if prior_fields[node] < 0 else 1 if prior_fields[node] == 0 else 2
            intrinsic = (-phase if orientation else phase) % 256
            intrinsic = (intrinsic + (1 if symbol == "+" else -1) * args[0] * prior_recipe.turns[column]) % 256
            phase = (-intrinsic if orientation else intrinsic) % 256
        elif symbol == "R":
            radius = args[0]
        elif symbol == "SCALE":
            scale = args[0]
        elif symbol == "S":
            _same(document["balls"][sphere_index],
                  {"address": list(address), "branch_path": [list(item) for item in branch],
                   "center": node, "radius": radius * (1 << scale), "pair": state()}, "Sphere")
            sphere_index += 1
        elif symbol == "[":
            stack.append((phase, node, orientation, radius, scale, branch))
            branch = branch + (address,)
        elif symbol == "]":
            phase, node, orientation, radius, scale, branch = stack.pop()
        _same(document["trace"][trace_index],
              {"address": list(address), "branch_path": [list(item) for item in branch],
               "pair": state(), "radius": radius, "scale": scale}, "Terminal state")
    _same(document["final_context"], {"branch_path": [], "pair": state(), "radius": radius, "scale": scale}, "Final context")
    return derivation_sha256(document)


def closed_distance(width, height, source, destination):
    """Exact fixed-quotient metric, independently exhaustively checked by OG8."""
    _integer(width, 3, 256, "width")
    _integer(height, 3, 256, "height")
    if width * height > 256:
        raise ValueError("Klein quotient exceeds 256 nodes")
    _integer(source, 0, width * height - 1, "source")
    _integer(destination, 0, width * height - 1, "destination")
    u, v = divmod(source, height)
    a, b = divmod(destination, height)
    direct, reflected = (v - b) % height, (v + b) % height
    du = abs(u - a)
    return min(du + min(direct, height - direct), width - du + min(reflected, height - reflected))


def _distances(domain, starts):
    adjacent = [[] for _ in domain.nodes]
    for source, destination, _ in domain.edges:
        adjacent[source].append(destination)
        adjacent[destination].append(source)
    distances = [-1] * len(adjacent)
    pending = deque(starts)
    for node in pending:
        distances[node] = 0
    while pending:
        source = pending.popleft()
        for destination in adjacent[source]:
            if distances[destination] == -1:
                distances[destination] = distances[source] + 1
                pending.append(destination)
    return tuple(distances)


def union_signs_cpu(recipe, balls) -> tuple[int, ...]:
    """CPU sphere-union producer, using graph BFS rather than the closed metric."""
    if type(balls) is not list or not balls:
        raise ValueError("Sphere union requires at least one primitive")
    domain = recipe.domain()
    margin = [I32_MAX] * len(domain.nodes)
    for sphere in balls:
        _integer(sphere["center"], 0, len(domain.nodes) - 1, "sphere center")
        _integer(sphere["radius"], 1, 127, "sphere radius")
        distances = _distances(domain, (sphere["center"],))
        margin = [min(old, distance - sphere["radius"]) for old, distance in zip(margin, distances)]
    if 0 not in margin:
        raise ValueError("Generated sphere union has an empty boundary")
    return tuple((value > 0) - (value < 0) for value in margin)


@dataclass(frozen=True, slots=True, init=False)
class GeneratedFieldCertificate:
    recipe: GeneratedFieldRecipe
    manifest: FieldManifest
    fields: tuple[int, ...]
    stage_digests: tuple[str, ...]
    _last_document: bytes

    def __init__(self, *args, **kwargs):
        raise ValueError("Use certify_stage or regenerate to admit a generated field")

    @property
    def last_derivation(self):
        return json.loads(self._last_document)

    @property
    def derivation_sha256(self):
        return self.stage_digests[-1]


def certify_stage(recipe: GeneratedFieldRecipe, prior_fields: tuple[int, ...], document: dict,
                  signs: tuple[int, ...], fields: tuple[int, ...], *,
                  prior_certificate: GeneratedFieldCertificate | None = None) -> GeneratedFieldCertificate:
    """Admit one contiguous supplied device/CPU stage without a CPU producer."""
    if type(recipe) is not GeneratedFieldRecipe:
        raise ValueError("Stage admission requires a generated recipe")
    if len(recipe.stages) == 1:
        if prior_certificate is not None:
            raise ValueError("The first stage cannot carry a generated predecessor")
        prior_recipe = recipe.base
        certify_field(prior_recipe.field_manifest(), prior_fields)
        preceding = ()
    else:
        prior_recipe = GeneratedFieldRecipe(recipe.base, recipe.organogram, recipe.routing, recipe.stages[:-1])
        if (type(prior_certificate) is not GeneratedFieldCertificate or prior_certificate.recipe != prior_recipe
                or prior_certificate.fields != prior_fields):
            raise ValueError("Missing or mismatched contiguous prior field certificate")
        preceding = prior_certificate.stage_digests
    stage_digest = certify_derivation(prior_recipe, prior_fields, recipe.organogram, recipe.stages[-1], recipe.routing, document)
    count = recipe.width * recipe.height
    if type(signs) is not tuple or type(fields) is not tuple or len(signs) != count or len(fields) != count:
        raise ValueError("Supplied signs and fields require complete immutable tuples")
    for node, sign in enumerate(signs):
        _integer(sign, -1, 1, "generated sign")
        margin = min(closed_distance(recipe.width, recipe.height, node, sphere["center"]) - sphere["radius"]
                     for sphere in document["balls"])
        if sign != (margin > 0) - (margin < 0):
            raise ValueError("Supplied sign disagrees with the certified sphere union")
    manifest = recipe.field_manifest_from_signs(signs)
    certify_field(manifest, fields)
    result = object.__new__(GeneratedFieldCertificate)
    for name, value in (("recipe", recipe), ("manifest", manifest), ("fields", fields),
                        ("stage_digests", preceding + (stage_digest,)), ("_last_document", canonical_bytes(document))):
        object.__setattr__(result, name, value)
    return result


def regenerate(recipe: GeneratedFieldRecipe) -> GeneratedFieldCertificate:
    """Reconstruct stages in order from each retained original tick and pair."""
    if type(recipe) is not GeneratedFieldRecipe:
        raise ValueError("Reconstruction requires a GeneratedFieldRecipe")
    fields = evaluate_field(recipe.base.field_manifest())
    prior, certificate = recipe.base, None
    for length, context in enumerate(recipe.stages, 1):
        current = GeneratedFieldRecipe(recipe.base, recipe.organogram, recipe.routing, recipe.stages[:length])
        document = interpret_cpu(prior, fields, recipe.organogram, context, recipe.routing)
        signs = union_signs_cpu(current, document["balls"])
        generated = evaluate_field(current.field_manifest_from_signs(signs))
        certificate = certify_stage(current, fields, document, signs, generated, prior_certificate=certificate)
        prior, fields = current, generated
    return certificate


def select_target(recipe, certified_fields: tuple[int, ...], node: int, intrinsic_phase: int, *,
                  certificate: GeneratedFieldCertificate | None = None) -> int:
    """OG5: closest to the boundary, farthest from owner, intrinsic tie rank."""
    if type(recipe) is not GeneratedFieldRecipe:
        raise ValueError("Organogram target selection requires a generated recipe")
    _integer(node, 0, recipe.width * recipe.height - 1, "owner node")
    _integer(intrinsic_phase, 0, 255, "intrinsic phase")
    if type(certified_fields) is not tuple:
        raise ValueError("Target selection requires immutable certified fields")
    if len(certified_fields) != recipe.width * recipe.height:
        raise ValueError("Target field requires one value per quotient node")
    for value in certified_fields:
        _integer(value, -127, 127, "target field")
    if certificate is None:
        certificate = regenerate(recipe)
    if (type(certificate) is not GeneratedFieldCertificate or certificate.recipe != recipe
            or certificate.fields != certified_fields):
        raise ValueError("Target field does not match its complete recipe certificate")
    candidates = tuple(index for index in range(len(certified_fields)) if index != node)
    minimum = min(abs(certified_fields[index]) for index in candidates)
    near = tuple(index for index in candidates if abs(certified_fields[index]) == minimum)
    distances = _distances(recipe.domain(), (node,))
    maximum = max(distances[index] for index in near)
    tied = tuple(index for index in near if distances[index] == maximum)
    return tied[intrinsic_phase % len(tied)]
