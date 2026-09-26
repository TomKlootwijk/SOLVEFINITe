"""DP1--DP10: finite directional sections with independent field admission.

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
from .organogram import StageContext


PROFILE = "klein-taper-organogram-v1"
WORLD_PROFILE = "klein-taper-world-v1"
DERIVATION_PROFILE = "klein-taper-derivation-v1"
TAPE_PROFILE = "TP-TAPE32-v1"
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
TERMINALS = {"F": 1, "+": 1, "-": 1, "[": 0, "]": 0, "R": 1, "S": 0, "SCALE": 1, "TAPER": 3}
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
        if len(value) > 10 or any(type(key) is not str for key in value):
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
             _token("TAPER", 1, 1, 2), _token("R", 2), _token("]"), _token("]"),
             _token("["), _token("-", 1), _token("B", 2), _token("]")]
    later = [_token("["), _token("R", 1), _token("-", 1), _token("B", 1),
             _token("["), _token("SCALE", 1), _token("+", 1), _token("F", 1),
             _token("TAPER", 1, 1, 2), _token("R", 2), _token("]"), _token("]"),
             _token("["), _token("+", 1), _token("B", 2), _token("]")]
    parameter = {"arg": 0, "mul": 1, "add": 0}
    return {"format": PROFILE, "max_epochs": 1, "cost": 1,
            "symbols": [{"name": "A", "arity": 1}, {"name": "B", "arity": 1}, {"name": "D", "arity": 0}],
            "axiom": [_token("A", {"context": "tick", "mul": 1, "add": 0}), _token("D")],
            "rules": [
                {"symbol": "A", "guards": [{"arg": 0, "op": "xor_eq", "mask": 1, "value": 4}], "rhs": first},
                {"symbol": "A", "guards": [], "rhs": later},
                {"symbol": "B", "guards": [{"arg": 0, "op": "eq", "value": 1}],
                 "rhs": [_token("F", parameter), _token("TAPER", {"arg": 0, "mul": 1, "add": 2}, 1, 2)]},
                {"symbol": "B", "guards": [{"arg": 0, "op": "ge", "value": 1}],
                 "rhs": [_token("F", parameter), _token("S"), _token("R", 2)]},
                {"symbol": "D", "guards": [], "rhs": []}],
            "generations": 2,
            "limits": {"max_symbols": 128, "max_steps": 128, "max_primitives": 16, "max_stack": 8, "max_primitive_sites": 1 << 20}}


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
          "Taper binding")
    if type(value["format"]) is not str or value["format"] != PROFILE:
        raise ValueError("Unsupported taper format")
    _integer(value["max_epochs"], 0, 4, "max_epochs")
    _integer(value["cost"], 1, 127, "taper cost")
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
    _keys(limits, {"max_symbols", "max_steps", "max_primitives", "max_stack", "max_primitive_sites"}, "Grammar limits")
    for name, lower, upper in (("max_symbols", 1, 1024), ("max_steps", 1, 4096),
                               ("max_primitives", 1, 64), ("max_stack", 0, 32),
                               ("max_primitive_sites", 1, 1 << 24)):
        _integer(limits[name], lower, upper, name)


@dataclass(frozen=True, slots=True, init=False)
class TaperBinding:
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
    primitives: int
    primitive_sites: int
    stack_high_water: int
    logical_instructions: int
    texels: int

    def __post_init__(self):
        _integer(self.effective_steps, 0, 4096, "effective steps")
        _integer(self.primitives, 1, 64, "primitive count")
        _integer(self.primitive_sites, 1, 1 << 24, "primitive sites")
        _integer(self.stack_high_water, 0, 32, "stack high water")
        _integer(self.logical_instructions, 1, 1024, "logical instructions")
        _integer(self.texels, 1, 1152, "instruction texels")

    def to_dict(self):
        return {"effective_steps": self.effective_steps, "primitives": self.primitives,
                "primitive_sites": self.primitive_sites, "stack_high_water": self.stack_high_water,
                "logical_instructions": self.logical_instructions, "texels": self.texels}


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


def compile_tape(binding: TaperBinding, context: StageContext) -> tuple[TapeInstruction, ...]:
    if type(binding) is not TaperBinding or type(context) is not StageContext:
        raise ValueError("Tape compilation requires an taper binding and original context")
    if context.epoch > binding.max_epochs:
        raise ValueError("Context exceeds the declared taper epochs")
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
    _check_tape(result, binding)
    return result


def _terminal_bounds(instruction):
    if type(instruction) is not TapeInstruction:
        raise ValueError("Expected an immutable TapeInstruction")
    bounds = {"F": (1, 256), "+": (1, 16), "-": (1, 16), "R": (1, 127), "SCALE": (0, 4)}
    if instruction.symbol in bounds:
        _integer(instruction.args[0], *bounds[instruction.symbol], "terminal argument")
    elif instruction.symbol == "TAPER":
        for value in instruction.args:
            _integer(value, 1, 65535, "TAPER argument")
        if gcd(instruction.args[1], instruction.args[2]) != 1:
            raise ValueError("TAPER slope must be reduced")


def taper_bounds(width, height, h, p, q, scale):
    """DP6 exact widened arithmetic, before enumerating any geometry."""
    _integer(width, 3, 256, "width")
    _integer(height, 3, 256, "height")
    if width * height > 256:
        raise ValueError("Klein quotient exceeds 256 nodes")
    for value in (h, p, q):
        _integer(value, 1, 65535, "TAPER argument")
    _integer(scale, 0, 4, "scale")
    if gcd(p, q) != 1:
        raise ValueError("TAPER slope must be reduced")
    extent = h << scale
    product = p * extent
    _integer(extent, 1, I32_MAX, "effective TAPER height")
    _integer(product, 1, I32_MAX, "TAPER pH")
    breadth = product // q
    _integer(q * breadth, 0, I32_MAX, "TAPER qB")
    _integer(width - 1 + extent + breadth, 1, I32_MAX, "lifted u bound")
    _integer(height - 1 + extent + breadth, 1, I32_MAX, "lifted v bound")
    return {"height": extent, "transverse_bound": breadth, "pH": product,
            "qB": q * breadth, "rectangle_sites": (extent + 1) * (2 * breadth + 1)}


def _check_tape(tape, binding, recipe=None):
    if type(binding) is not TaperBinding or type(tape) is not tuple:
        raise ValueError("Preflight requires an immutable tape and taper binding")
    limits = binding.limits
    if not tape or len(tape) > limits["max_symbols"]:
        raise ValueError("Tape exceeds symbol budget")
    if recipe is not None:
        _geometry_recipe(recipe)
    width, height = (3, 3) if recipe is None else (recipe.width, recipe.height)
    radius, scale, stack = 1, 0, []
    steps = primitives = sites = high_water = texels = 0
    for instruction in tape:
        _terminal_bounds(instruction)
        symbol, args = instruction.symbol, instruction.args
        texels += 3 if symbol == "TAPER" else 1
        if symbol == "F":
            steps += args[0] * (1 << scale)
        elif symbol == "R":
            radius = args[0]
        elif symbol == "SCALE":
            scale = args[0]
        elif symbol == "S":
            _integer(radius * (1 << scale), 1, 127, "effective sphere radius")
            primitives += 1
            sites += 0 if recipe is None else width * height
        elif symbol == "TAPER":
            sites += taper_bounds(width, height, *args, scale)["rectangle_sites"]
            primitives += 1
        elif symbol == "[":
            stack.append((radius, scale))
            high_water = max(high_water, len(stack))
        elif symbol == "]":
            if not stack:
                raise ValueError("Branch stack underflow")
            radius, scale = stack.pop()
        if (steps > limits["max_steps"] or primitives > limits["max_primitives"]
                or len(stack) > limits["max_stack"] or sites > limits["max_primitive_sites"] or texels > 1152):
            raise ValueError("Tape exceeds its finite work or stack budget")
    if stack:
        raise ValueError("Unclosed branch context")
    if not primitives:
        raise ValueError("Tape emits no boundary primitive")
    if recipe is not None:
        return TapeBudget(steps, primitives, sites, high_water, len(tape), texels)


def preflight(tape: tuple[TapeInstruction, ...], binding: TaperBinding, recipe) -> TapeBudget:
    """Complete DP6 admission; includes N ball sites and chart size bounds."""
    _geometry_recipe(recipe)
    return _check_tape(tape, binding, recipe)


def encode_tape(tape: tuple[TapeInstruction, ...], *, profile=TAPE_PROFILE) -> tuple[int, ...]:
    if type(profile) is not str or profile != TAPE_PROFILE:
        raise ValueError("Unsupported instruction profile")
    if type(tape) is not tuple or not 1 <= len(tape) <= 1024:
        raise ValueError("Instruction encoder requires an immutable tape")
    result = []
    for instruction in tape:
        _terminal_bounds(instruction)
        parts = (zip((8, 9, 10), instruction.args) if instruction.symbol == "TAPER" else
                 [(_OPCODES.index(instruction.symbol), instruction.args[0] if instruction.args else 0)])
        for code, operand in parts:
            raw = operand | (code << 24)
            result.append(raw | ((raw.bit_count() & 1) << 31))
    if len(result) > 1152:
        raise ValueError("Instruction texture exceeds 1152 texels")
    return tuple(result)


def word_offsets(tape: tuple[TapeInstruction, ...]) -> tuple[int, ...]:
    encode_tape(tape)
    offsets, position = [], 0
    for instruction in tape:
        offsets.append(position)
        position += 3 if instruction.symbol == "TAPER" else 1
    return tuple(offsets)


def decode_tape(words: tuple[int, ...], *, profile=TAPE_PROFILE) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Decode a whole typed texture, including every continuation and tail."""
    if type(profile) is not str or profile != TAPE_PROFILE:
        raise ValueError("Unsupported instruction profile")
    if type(words) is not tuple or not 1 <= len(words) <= 1152:
        raise ValueError("Instruction texture requires 1..1152 immutable words")
    parts = []
    for word in words:
        _integer(word, 0, (1 << 32) - 1, "instruction word")
        if word.bit_count() & 1 or word & 0x70FF0000:
            raise ValueError("Instruction parity or reserved lane is invalid")
        code = (word >> 24) & 15
        if code > 10:
            raise ValueError("Unknown instruction code")
        parts.append((code, word & 65535))
    result, index = [], 0
    while index < len(parts):
        code, operand = parts[index]
        if code == 8:
            if index + 2 >= len(parts) or tuple(x[0] for x in parts[index:index + 3]) != (8, 9, 10):
                raise ValueError("TAPER continuation order or truncation")
            symbol, args = "TAPER", tuple(x[1] for x in parts[index:index + 3])
            index += 3
        else:
            if code in (9, 10):
                raise ValueError("Stray TAPER continuation")
            symbol = _OPCODES[code]
            if not TERMINALS[symbol] and operand:
                raise ValueError("No-argument terminal carries a nonzero operand")
            args = (operand,) if TERMINALS[symbol] else ()
            index += 1
        _terminal_bounds(TapeInstruction((0,), symbol, args))
        result.append((symbol, args))
        if len(result) > 1024:
            raise ValueError("Decoded tape exceeds 1024 logical instructions")
    return tuple(result)


def _base_recipe(value):
    from .field_world import KleinFieldRecipe
    if type(value) is not KleinFieldRecipe:
        raise ValueError("base must be a KleinFieldRecipe")


def _geometry_recipe(value):
    from .field_world import KleinFieldRecipe
    if type(value) not in (KleinFieldRecipe, TaperFieldRecipe):
        raise ValueError("Expected a base or typed taper field recipe")


@dataclass(frozen=True, slots=True)
class TaperFieldRecipe:
    base: object
    taper: TaperBinding
    routing: HadamardBinding
    stages: tuple[StageContext, ...]
    version: str = WORLD_PROFILE

    def __post_init__(self):
        _base_recipe(self.base)
        if type(self.taper) is not TaperBinding or type(self.routing) is not HadamardBinding:
            raise ValueError("Generated recipe requires taper and routing bindings")
        if type(self.version) is not str or self.version != WORLD_PROFILE:
            raise ValueError("Unsupported generated recipe format")
        if type(self.stages) is not tuple or not 1 <= len(self.stages) <= self.taper.max_epochs:
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
    def binding(self):
        return self.taper

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
        return {"format": self.version, "base": self.base.to_dict(), "taper": self.taper.to_dict(),
                "routing": self.routing.to_dict(), "stages": [context.to_dict() for context in self.stages]}

    @classmethod
    def from_dict(cls, value):
        from .field_world import KleinFieldRecipe
        _keys(value, {"format", "base", "taper", "routing", "stages"}, "Generated recipe")
        _array(value["stages"], 1, 4, "Original stages")
        return cls(KleinFieldRecipe.from_dict(value["base"]), TaperBinding.from_dict(value["taper"]),
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
    if type(prior_recipe) not in (KleinFieldRecipe, TaperFieldRecipe):
        raise ValueError("Prior recipe must describe a Klein field")
    if type(binding) is not TaperBinding or type(context) is not StageContext or type(routing) is not HadamardBinding:
        raise ValueError("Invalid stage bindings or context")
    count = prior_recipe.width * prior_recipe.height
    if type(prior_fields) is not tuple or len(prior_fields) != count:
        raise ValueError("Prior fields require an immutable complete tuple")
    for value in prior_fields:
        _integer(value, -127, 127, "prior field")
    phase, node, signed, metadata = _pair_lanes(context.start_pair, int(Opcode.EMIT))
    if node >= count or prior_fields[node] != signed:
        raise ValueError("Original context disagrees with the prior field")
    if type(prior_recipe) is TaperFieldRecipe:
        if (prior_recipe.taper != binding or prior_recipe.routing != routing
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
    preflight(tape, binding, prior_recipe)
    domain = prior_recipe.domain()
    axes = field_axes(domain, prior_fields)
    radius, scale, branch, stack = 1, 0, (), []
    trace, segments, primitives = [], [], []

    def shaft():
        bank = ((-phase if orientation else phase) % 256) // 64
        axis = axes[node]
        gu, gv = axis.gradient
        pu, pv = axis.vector
        au, av = routing.gains[bank]
        q = (au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv)
        priority = tuple(range(bank, 4)) + tuple(range(bank))
        return max(priority, key=lambda index: q[0] * _VECTORS[index][0] + q[1] * _VECTORS[index][1])

    for instruction in tape:
        symbol, args, address = instruction.symbol, instruction.args, instruction.address
        if symbol == "F":
            for step in range(1, args[0] * (1 << scale) + 1):
                destination, seam = domain.step(node, _DIRECTIONS[shaft()])
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
            primitives.append({"kind": "ball", "address": list(address),
                               "branch_path": [list(item) for item in branch],
                               "center": node, "radius": radius * (1 << scale),
                               "pair": _packed(phase, node, prior_fields, orientation)})
        elif symbol == "TAPER":
            primitives.append({"kind": "taper", "address": list(address),
                               "branch_path": [list(item) for item in branch],
                               "apex": node, "height": args[0] << scale,
                               "numerator": args[1], "denominator": args[2], "shaft": shaft(),
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
            "segments": segments, "primitives": primitives,
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
    work = preflight(tape, binding, prior_recipe)
    _keys(document, {"format", "context", "tape", "trace", "segments", "primitives", "final_context"}, "Derivation")
    _json_shape(document)
    _same(document["format"], DERIVATION_PROFILE, "Derivation format")
    _same(document["context"], context.to_dict(), "Derivation context")
    _same(document["tape"], [instruction.to_dict() for instruction in tape], "Ordered tape")
    _array(document["trace"], len(tape), len(tape), "Terminal trace")
    _array(document["segments"], work.effective_steps, work.effective_steps, "Segments")
    _array(document["primitives"], work.primitives, work.primitives, "Boundary primitives")
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

    def checked_shaft():
        adjacent = tuple(neighbor(node, direction) for direction in range(4))
        gu = prior_fields[adjacent[0][0]] - prior_fields[adjacent[2][0]]
        gv = prior_fields[adjacent[1][0]] - prior_fields[adjacent[3][0]]
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        bank = ((-phase if orientation else phase) % 256) >> 6
        au, av = routing.gains[bank]
        qu, qv = au * (1 + pu ** 2) * gu, av * (1 + pv ** 2) * gv
        scores = (qu, qv, -qu, -qv)
        return next((bank + offset) % 4 for offset in range(4)
                    if scores[(bank + offset) % 4] == max(scores))

    radius, scale, branch, stack = 1, 0, (), []
    segment_index = primitive_index = 0
    for trace_index, instruction in enumerate(tape):
        address, symbol, args = instruction.address, instruction.symbol, instruction.args
        if symbol == "F":
            for step in range(1, args[0] * (1 << scale) + 1):
                destination, seam = neighbor(node, checked_shaft())
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
            _same(document["primitives"][primitive_index],
                  {"kind": "ball", "address": list(address), "branch_path": [list(item) for item in branch],
                   "center": node, "radius": radius * (1 << scale), "pair": state()}, "Sphere")
            primitive_index += 1
        elif symbol == "TAPER":
            _same(document["primitives"][primitive_index],
                  {"kind": "taper", "address": list(address), "branch_path": [list(item) for item in branch],
                   "apex": node, "height": args[0] << scale, "numerator": args[1],
                   "denominator": args[2], "shaft": checked_shaft(), "pair": state()}, "Taper")
            primitive_index += 1
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


def _primitive_schema(recipe, primitives):
    """Validate direct producer inputs completely before geometry allocation."""
    _geometry_recipe(recipe)
    _array(primitives, 1, 64, "Primitives")
    _json_shape(primitives)
    sites = 0
    for primitive in primitives:
        if type(primitive) is not dict or type(primitive.get("kind")) is not str:
            raise ValueError("Invalid primitive kind")
        common = {"kind", "address", "branch_path", "pair"}
        if primitive["kind"] == "ball":
            _keys(primitive, common | {"center", "radius"}, "Ball primitive")
            node = primitive["center"]
            _integer(primitive["radius"], 1, 127, "effective ball radius")
            sites += recipe.width * recipe.height
        elif primitive["kind"] == "taper":
            _keys(primitive, common | {"apex", "height", "numerator", "denominator", "shaft"}, "Taper primitive")
            node = primitive["apex"]
            extent, p, q = primitive["height"], primitive["numerator"], primitive["denominator"]
            _integer(extent, 1, 65535 << 4, "effective taper height")
            _integer(p, 1, 65535, "numerator")
            _integer(q, 1, 65535, "denominator")
            _integer(primitive["shaft"], 0, 3, "shaft")
            if gcd(p, q) != 1:
                raise ValueError("Taper slope must be reduced")
            _integer(p * extent, 1, I32_MAX, "Taper pH")
            breadth = p * extent // q
            _integer(q * breadth, 0, I32_MAX, "Taper qB")
            _integer(recipe.width - 1 + extent + breadth, 1, I32_MAX, "lifted u bound")
            _integer(recipe.height - 1 + extent + breadth, 1, I32_MAX, "lifted v bound")
            sites += (extent + 1) * (2 * breadth + 1)
        else:
            raise ValueError("Unknown primitive kind")
        _integer(node, 0, recipe.width * recipe.height - 1, "primitive node")
        if _pair_lanes(primitive["pair"], int(Opcode.STEP))[1] != node:
            raise ValueError("Primitive pair names another node")
        _array(primitive["address"], 1, 25, "Primitive address")
        TapeInstruction(tuple(primitive["address"]), "S", ())
        _array(primitive["branch_path"], 0, 32, "Primitive branch path")
        for address in primitive["branch_path"]:
            _array(address, 1, 25, "Branch address")
            TapeInstruction(tuple(address), "[", ())
    limits = recipe.taper.limits if type(recipe) is TaperFieldRecipe else {
        "max_primitives": 64, "max_primitive_sites": 1 << 24}
    if len(primitives) > limits["max_primitives"] or sites > limits["max_primitive_sites"]:
        raise ValueError("Primitive geometry exceeds its finite work budget")


def occupancy_cpu(recipe, primitives) -> tuple[bool, ...]:
    """Producer: project complete cover sites and union closed occupied sets.

    The site budget charges the complete rectangle, including rejected sites.
    Enumeration below may omit its provably rejected transverse suffixes.
    """
    _primitive_schema(recipe, primitives)
    width, height = recipe.width, recipe.height
    occupied = [False] * (width * height)
    domain = recipe.domain()
    for primitive in primitives:
        if primitive["kind"] == "ball":
            distances = _distances(domain, (primitive["center"],))
            for node, distance in enumerate(distances):
                if distance <= primitive["radius"]:
                    occupied[node] = True
            continue
        ax, ay = divmod(primitive["apex"], height)
        eu, ev = _VECTORS[primitive["shaft"]]
        eta = (_pair_lanes(primitive["pair"], int(Opcode.STEP))[3] >> 4) & 1
        fu, fv = (ev, -eu) if eta else (-ev, eu)
        for s in range(primitive["height"] + 1):
            breadth = primitive["numerator"] * s // primitive["denominator"]
            for t in range(-breadth, breadth + 1):
                x, y = ax + s * eu + t * fu, ay + s * ev + t * fv
                crossings, u = divmod(x, width)
                v = (-y if crossings & 1 else y) % height
                occupied[u * height + v] = True
    return tuple(occupied)


def signs_from_occupancy_cpu(recipe, occupied: tuple[bool, ...]) -> tuple[int, ...]:
    """Producer: remove hidden primitive boundaries before redistancing."""
    _geometry_recipe(recipe)
    if (type(occupied) is not tuple or len(occupied) != recipe.width * recipe.height
            or any(type(value) is not bool for value in occupied)):
        raise ValueError("Occupancy requires a complete immutable Boolean mask")
    if not any(occupied) or all(occupied):
        raise ValueError("Generated union is empty or full and has no boundary")
    domain = recipe.domain()
    return tuple(1 if not inside else
                 0 if any(not occupied[domain.step(node, direction)[0]] for direction in _DIRECTIONS) else -1
                 for node, inside in enumerate(occupied))


def union_signs_cpu(recipe, primitives) -> tuple[int, ...]:
    return signs_from_occupancy_cpu(recipe, occupancy_cpu(recipe, primitives))


def _certified_occupancy(recipe, primitives):
    """Independent checker: test quotient-node lifts against each local wedge.

    No forward projection, site producer, domain builder or CPU field evaluator
    is used. Cardinal rectangle bounds keep inverse membership finite under
    the already checked primitive-site budget, including very thin sections.
    """
    width, height = recipe.width, recipe.height
    result = []
    for node in range(width * height):
        u, v = divmod(node, height)
        found = False
        for primitive in primitives:
            if primitive["kind"] == "ball":
                if closed_distance(width, height, node, primitive["center"]) <= primitive["radius"]:
                    found = True
                    break
                continue
            ax, ay = divmod(primitive["apex"], height)
            eu, ev = _VECTORS[primitive["shaft"]]
            eta = (_pair_lanes(primitive["pair"], int(Opcode.STEP))[3] >> 4) & 1
            fu, fv = (ev, -eu) if eta else (-ev, eu)
            extent, p, q = primitive["height"], primitive["numerator"], primitive["denominator"]
            breadth = p * extent // q
            xmin = ax + min(0, extent * eu) - breadth * abs(fu)
            xmax = ax + max(0, extent * eu) + breadth * abs(fu)
            ymin = ay + min(0, extent * ev) - breadth * abs(fv)
            ymax = ay + max(0, extent * ev) + breadth * abs(fv)
            first_m = -((u - xmin) // width)
            last_m = (xmax - u) // width
            for m in range(first_m, last_m + 1):
                lifted_v = -v if m & 1 else v
                first_n = -((lifted_v - ymin) // height)
                last_n = (ymax - lifted_v) // height
                dx = u + m * width - ax
                for n in range(first_n, last_n + 1):
                    dy = lifted_v + n * height - ay
                    s, t = dx * eu + dy * ev, dx * fu + dy * fv
                    if 0 <= s <= extent and q * abs(t) <= p * s:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        result.append(found)
    return tuple(result)


@dataclass(frozen=True, slots=True, init=False)
class TaperFieldCertificate:
    recipe: TaperFieldRecipe
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


def certify_stage(recipe: TaperFieldRecipe, prior_fields: tuple[int, ...], document: dict,
                  signs: tuple[int, ...], fields: tuple[int, ...], *,
                  prior_certificate: TaperFieldCertificate | None = None) -> TaperFieldCertificate:
    """Admit one contiguous supplied device/CPU stage without a CPU producer."""
    if type(recipe) is not TaperFieldRecipe:
        raise ValueError("Stage admission requires a generated recipe")
    if len(recipe.stages) == 1:
        if prior_certificate is not None:
            raise ValueError("The first stage cannot carry a generated predecessor")
        prior_recipe = recipe.base
        certify_field(prior_recipe.field_manifest(), prior_fields)
        preceding = ()
    else:
        prior_recipe = TaperFieldRecipe(recipe.base, recipe.taper, recipe.routing, recipe.stages[:-1])
        if (type(prior_certificate) is not TaperFieldCertificate or prior_certificate.recipe != prior_recipe
                or prior_certificate.fields != prior_fields):
            raise ValueError("Missing or mismatched contiguous prior field certificate")
        preceding = prior_certificate.stage_digests
    stage_digest = certify_derivation(prior_recipe, prior_fields, recipe.taper, recipe.stages[-1], recipe.routing, document)
    count = recipe.width * recipe.height
    if type(signs) is not tuple or type(fields) is not tuple or len(signs) != count or len(fields) != count:
        raise ValueError("Supplied signs and fields require complete immutable tuples")
    occupied = _certified_occupancy(recipe, document["primitives"])
    if not any(occupied) or all(occupied):
        raise ValueError("Certified occupied union is empty or full")
    for node, sign in enumerate(signs):
        _integer(sign, -1, 1, "generated sign")
        u, v = divmod(node, recipe.height)
        adjacent = []
        for du, dv in _VECTORS:
            crossing, x = divmod(u + du, recipe.width)
            y = (-v - dv if crossing & 1 else v + dv) % recipe.height
            adjacent.append(x * recipe.height + y)
        expected = (1 if not occupied[node] else
                    0 if any(not occupied[other] for other in adjacent) else -1)
        if sign != expected:
            raise ValueError("Supplied sign disagrees with the union's inner vertex boundary")
    manifest = recipe.field_manifest_from_signs(signs)
    certify_field(manifest, fields)
    result = object.__new__(TaperFieldCertificate)
    for name, value in (("recipe", recipe), ("manifest", manifest), ("fields", fields),
                        ("stage_digests", preceding + (stage_digest,)), ("_last_document", canonical_bytes(document))):
        object.__setattr__(result, name, value)
    return result


def regenerate(recipe: TaperFieldRecipe) -> TaperFieldCertificate:
    """Reconstruct stages in order from each retained original tick and pair."""
    if type(recipe) is not TaperFieldRecipe:
        raise ValueError("Reconstruction requires a TaperFieldRecipe")
    # Reject the complete retained structural workload before even the base
    # field producer runs. Actual prior B values are checked in stage order.
    for context in recipe.stages:
        preflight(compile_tape(recipe.taper, context), recipe.taper, recipe)
    fields = evaluate_field(recipe.base.field_manifest())
    prior, certificate = recipe.base, None
    for length, context in enumerate(recipe.stages, 1):
        current = TaperFieldRecipe(recipe.base, recipe.taper, recipe.routing, recipe.stages[:length])
        document = interpret_cpu(prior, fields, recipe.taper, context, recipe.routing)
        signs = union_signs_cpu(current, document["primitives"])
        generated = evaluate_field(current.field_manifest_from_signs(signs))
        certificate = certify_stage(current, fields, document, signs, generated, prior_certificate=certificate)
        prior, fields = current, generated
    return certificate


def select_target(recipe, certified_fields: tuple[int, ...], node: int, intrinsic_phase: int, *,
                  certificate: TaperFieldCertificate | None = None) -> int:
    """DP8: closest to the boundary, farthest from owner, intrinsic tie rank."""
    if type(recipe) is not TaperFieldRecipe:
        raise ValueError("Taper target selection requires a generated recipe")
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
    if (type(certificate) is not TaperFieldCertificate or certificate.recipe != recipe
            or certificate.fields != certified_fields):
        raise ValueError("Target field does not match its complete recipe certificate")
    candidates = tuple(index for index in range(len(certified_fields)) if index != node)
    minimum = min(abs(certified_fields[index]) for index in candidates)
    near = tuple(index for index in candidates if abs(certified_fields[index]) == minimum)
    distances = _distances(recipe.domain(), (node,))
    maximum = max(distances[index] for index in near)
    tied = tuple(index for index in near if distances[index] == maximum)
    return tied[intrinsic_phase % len(tied)]
