"""Deterministic, bounded route discovery on an explicit directed world graph.

Weights are positive integer costs of entering a node. A returned route is
optimal among routes of at most ``max_hops`` edges, with tuple order breaking
equal-cost ties; it does not assert optimality without that hop constraint.
``NoRoute`` proves that the target is unreachable in the supplied graph.
``SearchBudgetExceeded`` means a reachable target needs more hops, or the
weighted search ran out of expansions before it could certify a result.
"""

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush


class NoRoute(ValueError):
    """There is no directed route from start to target in the supplied graph."""


class SearchBudgetExceeded(ValueError):
    """The hop or expansion budget prevents a certified route result."""

    def __init__(self, message: str, expansions: int = 0):
        super().__init__(message)
        self.expansions = expansions


@dataclass(frozen=True)
class SearchResult:
    route: tuple[str, ...]
    cost: int
    expansions: int


def _path(value: object, label: str) -> str:
    if (type(value) is not str or len(value) > 32
            or any(character not in "01" for character in value)):
        raise ValueError(f"{label} must be a binary path string of length <= 32")
    return value


def _budget(value: object, upper: int, label: str) -> int:
    if type(value) is not int or not 1 <= value <= upper:
        raise ValueError(f"{label} must be an integer in [1, {upper}]")
    return value


def normalize_graph(edges: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    """Validate and copy a graph, sorting both node keys and neighbor tuples.

    This checks structure only; disconnected components, cycles, self edges,
    and sinks are all valid. Node identifiers are binary paths up to depth 32.
    """
    if not isinstance(edges, Mapping) or not 1 <= len(edges) <= 256:
        raise ValueError("edges must be a mapping containing 1..256 nodes")
    copied = {}
    for node, adjacent in edges.items():
        _path(node, "node")
        if type(adjacent) not in (list, tuple):
            raise ValueError("each adjacency must be a list or tuple")
        neighbors = tuple(adjacent)
        for neighbor in neighbors:
            _path(neighbor, "neighbor")
        if len(set(neighbors)) != len(neighbors):
            raise ValueError("each adjacency must contain unique neighbors")
        copied[node] = tuple(sorted(neighbors))
    if any(neighbor not in copied for neighbors in copied.values()
           for neighbor in neighbors):
        raise ValueError("all neighbors must be declared graph nodes")
    return {node: copied[node] for node in sorted(copied)}


def shortest_route(
    edges: Mapping[str, Sequence[str]],
    start: str,
    target: str,
    cost: Callable[[str], int],
    max_hops: int = 32,
    max_expansions: int = 4096,
) -> SearchResult:
    """Find the least ``(total entry cost, route tuple)`` within ``max_hops``.

    The route excludes ``start`` and ends at ``target``; staying at the target
    returns an empty route with zero cost and zero expansions. Inputs are fully
    validated even for that case. The graph is copied before invoking ``cost``.
    Every node's cost, including the start and unreachable nodes, is evaluated
    exactly once in sorted path order and must be a positive strict integer.

    Reverse reachability proves disconnected targets unreachable, including
    graphs with cycles. Its unweighted distances also prove when the hop bound
    is too small. This preflight is bounded by the 256-node graph limit and is
    separate from the weighted-search budget. Expansions count settled
    non-target ``(node, hop count)`` states whose outgoing edges are inspected;
    stale heap entries and the terminal target do not consume expansions.

    Distinct hop counts retain distinct best prefixes: a cheaper long prefix
    cannot displace a costlier short prefix needed to meet the hop bound.
    """
    _budget(max_hops, 32, "max_hops")
    _budget(max_expansions, 65536, "max_expansions")
    graph = normalize_graph(edges)
    _path(start, "start")
    _path(target, "target")
    if start not in graph or target not in graph:
        raise ValueError("start and target must be declared graph nodes")
    if not callable(cost):
        raise ValueError("cost must be callable")
    weights = {}
    for node in sorted(graph):
        weight = cost(node)
        if type(weight) is not int or weight < 1:
            raise ValueError("each node cost must be a positive integer (not bool)")
        weights[node] = weight
    if start == target:
        return SearchResult((), 0, 0)

    predecessors = {node: [] for node in graph}
    for node in sorted(graph):
        for neighbor in graph[node]:
            predecessors[neighbor].append(node)
    remaining_hops = {target: 0}
    pending = deque([target])
    while pending:
        node = pending.popleft()
        for predecessor in predecessors[node]:
            if predecessor not in remaining_hops:
                remaining_hops[predecessor] = remaining_hops[node] + 1
                pending.append(predecessor)
    if start not in remaining_hops:
        raise NoRoute(f"no directed route from {start!r} to {target!r}")
    if remaining_hops[start] > max_hops:
        raise SearchBudgetExceeded("target cannot be reached within max_hops")

    # Cost and the full route precede state identity in the heap's ordering.
    frontier = [(0, (), start, 0)]
    best = {(start, 0): (0, ())}
    expansions = 0
    while frontier:
        total, route, node, hops = heappop(frontier)
        if best[(node, hops)] != (total, route):
            continue
        if node == target:
            return SearchResult(route, total, expansions)
        if expansions == max_expansions:
            raise SearchBudgetExceeded("weighted route search exhausted max_expansions", expansions)
        expansions += 1
        next_hops = hops + 1
        for neighbor in graph[node]:
            if (neighbor not in remaining_hops
                    or next_hops + remaining_hops[neighbor] > max_hops):
                continue
            candidate = (total + weights[neighbor], route + (neighbor,))
            state = (neighbor, next_hops)
            if state not in best or candidate < best[state]:
                best[state] = candidate
                heappush(frontier, (*candidate, neighbor, next_hops))

    # Preflight proved a route exists within the hop bound. Reaching here would
    # therefore indicate an implementation defect, never evidence of NoRoute.
    raise RuntimeError("reachable route was lost during weighted search")
