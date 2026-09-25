"""FI1-FI8: the geometric application manifest for the existing Tomigidt."""

from dataclasses import dataclass, field

from .field_world import KleinFieldRecipe
from .runtime import _integer, _keys


FIELD_POLICY = "tomigidt-field-observe-plan-act-v1"
FIELD_WORD_PROFILE = "RP32-relational-sdf-v2"
MAX_ENERGY = (1 << 31) - 1
_KEYS = {"identity", "target", "world", "initial_node", "initial_phase",
         "initial_orientation", "initial_energy", "repair_cost", "max_search_expansions",
         "max_hops", "max_cycles", "policy", "word_profile", "perspective"}


@dataclass(frozen=True)
class FieldAgentManifest:
    """Retain a geometric recipe and a goal, never supplied routes or actions."""

    identity: str = "TOMIGIDt"
    target: str = "k:3:2"
    world: KleinFieldRecipe = field(default_factory=KleinFieldRecipe)
    initial_node: str = "k:0:0"
    initial_phase: int = 250
    initial_orientation: int = 0
    initial_energy: int = 100
    repair_cost: int = 5
    max_search_expansions: int = 4096
    max_hops: int = 255
    max_cycles: int = 10_000
    policy: str = FIELD_POLICY
    graph: tuple[tuple[str, tuple[str, ...]], ...] = field(init=False)

    def __post_init__(self):
        if type(self.policy) is not str or self.policy != FIELD_POLICY:
            raise ValueError("Unsupported field-agent policy")
        if type(self.identity) is not str or not self.identity.strip() or len(self.identity) > 128:
            raise ValueError("identity must be a nonempty name of at most 128 characters")
        if type(self.world) is not KleinFieldRecipe:
            raise ValueError("world must be a KleinFieldRecipe")
        self.world.index(self.initial_node)
        self.world.index(self.target)
        _integer(self.initial_phase, 0, 255, "initial_phase")
        _integer(self.initial_orientation, 0, 1, "initial_orientation")
        _integer(self.initial_energy, 0, MAX_ENERGY, "initial_energy")
        _integer(self.repair_cost, 1, 127, "repair_cost")
        _integer(self.max_search_expansions, 1, 65536, "max_search_expansions")
        _integer(self.max_hops, 1, 255, "max_hops")
        _integer(self.max_cycles, 1, 1_000_000, "max_cycles")
        object.__setattr__(self, "graph", self.world.graph())

    @property
    def start(self):
        return self.initial_node

    def to_dict(self):
        return {"identity": self.identity, "target": self.target, "world": self.world.to_dict(),
                "initial_node": self.initial_node, "initial_phase": self.initial_phase,
                "initial_orientation": self.initial_orientation, "initial_energy": self.initial_energy,
                "repair_cost": self.repair_cost, "max_search_expansions": self.max_search_expansions,
                "max_hops": self.max_hops, "max_cycles": self.max_cycles, "policy": self.policy,
                "word_profile": FIELD_WORD_PROFILE, "perspective": "local-observation-v1"}

    @classmethod
    def from_dict(cls, value):
        _keys(value, _KEYS, "Field-agent manifest")
        if (type(value["word_profile"]) is not str or value["word_profile"] != FIELD_WORD_PROFILE
                or type(value["perspective"]) is not str
                or value["perspective"] != "local-observation-v1"):
            raise ValueError("Unsupported field-agent word profile or perspective")
        return cls(**{key: value[key] for key in _KEYS - {"world", "word_profile", "perspective"}},
                   world=KleinFieldRecipe.from_dict(value["world"]))
