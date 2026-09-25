"""Pure movement shared by planning and execution in the simulated profiles.

RP32 supplies packing, phase and mirror arithmetic. Interpreting the agent's B
lane as energy, the world's B lane as terrain and observations as hazard cost
is an application binding, not an additional physical claim about the source
paradigm. Neither function changes a world cache or an input pair.
"""

from __future__ import annotations

from .rp32 import Opcode, pack, pair, step, unpack, unpair
from .world import World


class EnergyExhausted(ValueError):
    """The agent cannot pay the declared cost of entering a waypoint."""


def movement_cost(node_pair: int, hazard: int) -> int:
    """Return the simulated terrain and observation cost for a valid pinion."""
    if type(hazard) is not int or not 0 <= hazard <= 127:
        raise ValueError("hazard must be an integer in [0, 127]")
    terrain = unpack(unpair(node_pair)[0])[2]
    return 1 + abs(terrain) // 8 + hazard


def move(agent_pair: int, path: str, world: World, hazard: int = 0) -> tuple[int, int]:
    """Derive a waypoint and compute one exact movement without mutation.

    The caller supplies the admitted hazard observation. The same function can
    therefore evaluate a hypothetical movement and execute the selected movement
    using identical retained input. It defines no navigation adjacency by itself.
    """
    if not isinstance(world, World):
        raise ValueError("world must be a World")
    left, _ = unpair(agent_pair)
    r, g, energy, a = unpack(left)
    node = world.derive(path)
    cost = movement_cost(node.pair, hazard)
    if energy < cost:
        raise EnergyExhausted(f"Insufficient energy to enter waypoint {path!r}")
    _, node_g, _, _ = unpack(unpair(node.pair)[0])
    row = (g ^ node_g ^ (r >> 6)) & 3
    branch = int(path[-1]) if path else 0
    delta = world.config.phase_turns[row][branch]
    next_r = unpack(step(left, delta))[0]
    return pair(pack(next_r, node_g, energy - cost,
                     (a & ~7) | Opcode.STEP)), cost
