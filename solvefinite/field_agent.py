"""FI1-FI8: the geometric application manifest for the existing Tomigidt."""

from dataclasses import dataclass, field

from .field_world import KleinFieldRecipe
from .hadamard import HadamardBinding
from .growth import GrowthBinding
from .organogram import OrganogramBinding
from .taper import TaperBinding
from .runtime import _integer, _keys


FIELD_POLICY = "tomigidt-field-observe-plan-act-v1"
HADAMARD_POLICY = "tomigidt-field-hadamard-plan-act-v1"
GROWTH_POLICY = "tomigidt-field-growth-plan-act-v1"
ORGANOGRAM_POLICY = "tomigidt-field-organogram-plan-act-v1"
TAPER_POLICY = "tomigidt-field-taper-plan-act-v1"
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
    routing: HadamardBinding | None = None
    growth: GrowthBinding | None = None
    organogram: OrganogramBinding | None = None
    taper: TaperBinding | None = None
    graph: tuple[tuple[str, tuple[str, ...]], ...] = field(init=False)

    def __post_init__(self):
        if type(self.policy) is not str or self.policy not in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY):
            raise ValueError("Unsupported field-agent policy")
        if self.policy in (HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY):
            if self.routing is None:
                object.__setattr__(self, "routing", HadamardBinding())
            elif type(self.routing) is not HadamardBinding:
                raise ValueError("routing must be a HadamardBinding")
        elif self.routing is not None:
            raise ValueError("Only the Hadamard policy admits routing")
        if self.policy == GROWTH_POLICY:
            if self.growth is None:
                object.__setattr__(self, "growth", GrowthBinding())
            elif type(self.growth) is not GrowthBinding:
                raise ValueError("growth must be a GrowthBinding")
        elif self.growth is not None:
            raise ValueError("Only the growth policy admits growth")
        if self.policy == ORGANOGRAM_POLICY:
            if self.organogram is None:
                object.__setattr__(self, "organogram", OrganogramBinding())
            elif type(self.organogram) is not OrganogramBinding:
                raise ValueError("organogram must be an OrganogramBinding")
        elif self.organogram is not None:
            raise ValueError("Only the organogram policy admits an organogram")
        if self.policy == TAPER_POLICY:
            if self.taper is None:
                object.__setattr__(self, "taper", TaperBinding())
            elif type(self.taper) is not TaperBinding:
                raise ValueError("taper must be a TaperBinding")
        elif self.taper is not None:
            raise ValueError("Only the taper policy admits a taper binding")
        if type(self.identity) is not str or not self.identity.strip() or len(self.identity) > 128:
            raise ValueError("identity must be a nonempty name of at most 128 characters")
        if type(self.world) is not KleinFieldRecipe:
            raise ValueError("world must be a KleinFieldRecipe")
        if self.growth is not None:
            self.growth.validate_recipe(self.world)
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

    @property
    def growth_binding(self):
        """The declared lifecycle; each production family keeps its own binding."""
        if self.policy == TAPER_POLICY:
            return self.taper
        return self.organogram if self.policy == ORGANOGRAM_POLICY else self.growth

    def to_dict(self):
        result = {"identity": self.identity, "target": self.target, "world": self.world.to_dict(),
                "initial_node": self.initial_node, "initial_phase": self.initial_phase,
                "initial_orientation": self.initial_orientation, "initial_energy": self.initial_energy,
                "repair_cost": self.repair_cost, "max_search_expansions": self.max_search_expansions,
                "max_hops": self.max_hops, "max_cycles": self.max_cycles, "policy": self.policy,
                "word_profile": FIELD_WORD_PROFILE, "perspective": "local-observation-v1"}
        if self.policy in (HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY):
            result["routing"] = self.routing.to_dict()
        if self.policy == GROWTH_POLICY:
            result["growth"] = self.growth.to_dict()
        if self.policy == ORGANOGRAM_POLICY:
            result["organogram"] = self.organogram.to_dict()
        if self.policy == TAPER_POLICY:
            result["taper"] = self.taper.to_dict()
        return result

    @classmethod
    def from_dict(cls, value):
        growing = type(value) is dict and value.get("policy") == GROWTH_POLICY
        generated = type(value) is dict and value.get("policy") == ORGANOGRAM_POLICY
        tapered = type(value) is dict and value.get("policy") == TAPER_POLICY
        hadamard = type(value) is dict and value.get("policy") in (HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY, TAPER_POLICY)
        _keys(value, _KEYS | ({"routing"} if hadamard else set())
              | ({"growth"} if growing else set())
              | ({"organogram"} if generated else set())
              | ({"taper"} if tapered else set()), "Field-agent manifest")
        if (type(value["word_profile"]) is not str or value["word_profile"] != FIELD_WORD_PROFILE
                or type(value["perspective"]) is not str
                or value["perspective"] != "local-observation-v1"):
            raise ValueError("Unsupported field-agent word profile or perspective")
        return cls(**{key: value[key] for key in _KEYS - {"world", "word_profile", "perspective"}},
                   world=KleinFieldRecipe.from_dict(value["world"]),
                   routing=HadamardBinding.from_dict(value["routing"]) if hadamard else None,
                   growth=GrowthBinding.from_dict(value["growth"]) if growing else None,
                   organogram=OrganogramBinding.from_dict(value["organogram"]) if generated else None,
                   taper=TaperBinding.from_dict(value["taper"]) if tapered else None)
