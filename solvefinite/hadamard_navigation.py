"""HP3: immutable bounded search over node, intrinsic phase and hop count.

The certified routing model supplies phase-dependent directional penalties.
Labels with different phase or hop count cannot dominate one another. Route
tuples use canonical names for lexical ties, independently of f8 storage order.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from heapq import heappop, heappush

from .hadamard import RoutingModel
from .navigation import NoRoute, SearchBudgetExceeded, SearchResult, _budget
from .runtime import _integer


@dataclass(frozen=True)
class HadamardRouteSearch:
    """Retained Dijkstra work over one immutable semantic routing model.

    Construct with ``start`` and retain the cursor returned by ``advance``.
    Entry costs are copied once in lexical path order; the callback is never
    retained. If observations or semantic routing change, start a new cursor.
    A storage-only index rebuild leaves this model and unfinished work valid.
    """

    _model: RoutingModel
    _nodes: tuple[str, ...]
    _weights: tuple[int, ...]
    _remaining_hops: tuple[int, ...]
    _target: int
    _max_hops: int
    _frontier: tuple[tuple[int, tuple[str, ...], int, int, int], ...]
    _best: tuple[tuple[tuple[int, int, int], tuple[int, tuple[str, ...]]], ...]
    expansions: int = 0
    _result: SearchResult | None = None

    @classmethod
    def start(
        cls,
        model: RoutingModel,
        start: str,
        target: str,
        cost: Callable[[str], int],
        max_hops: int = 255,
        *,
        initial_phase: int,
    ) -> HadamardRouteSearch:
        """Validate and snapshot the complete model before any expansion.

        ``initial_phase`` is intrinsic phase ``(-1)**eta * R mod 256``.
        Entry costs exclude the model's directional penalty and must be strict
        integers in 1..255. They include every node, even the starting node
        and unused nodes. Each resulting edge costs between 1 and 335.
        """
        if type(model) is not RoutingModel:
            raise ValueError("model must be a RoutingModel")
        _budget(max_hops, 255, "max_hops")
        _integer(initial_phase, 0, 255, "initial_phase")
        start_index = model.recipe.index(start)
        target_index = model.recipe.index(target)
        nodes = model.recipe.domain().nodes
        if not callable(cost):
            raise ValueError("cost must be callable")
        weights = [0] * len(nodes)
        for index in sorted(range(len(nodes)), key=nodes.__getitem__):
            value = cost(nodes[index])
            _integer(value, 1, 255, "entry cost")
            weights[index] = value
        frozen_weights = tuple(weights)
        if start_index == target_index:
            remaining = tuple(0 if index == target_index else -1
                              for index in range(len(nodes)))
            return cls(model, nodes, frozen_weights, remaining, target_index,
                       max_hops, (), (), _result=SearchResult((), 0, 0))

        predecessors = [[] for _ in nodes]
        for source, neighbors in enumerate(model.neighbors):
            for destination in neighbors:
                predecessors[destination].append(source)
        remaining = [-1] * len(nodes)
        remaining[target_index] = 0
        pending = deque([target_index])
        while pending:
            node = pending.popleft()
            for predecessor in predecessors[node]:
                if remaining[predecessor] == -1:
                    remaining[predecessor] = remaining[node] + 1
                    pending.append(predecessor)
        if remaining[start_index] == -1:
            raise NoRoute(f"no directed route from {start!r} to {target!r}")
        if remaining[start_index] > max_hops:
            raise SearchBudgetExceeded("target cannot be reached within max_hops", 0)
        return cls(model, nodes, frozen_weights, tuple(remaining), target_index,
                   max_hops, ((0, (), start_index, initial_phase, 0),),
                   (((start_index, initial_phase, 0), (0, ())),))

    @property
    def pending_states(self) -> int:
        """Live frontier labels, excluding superseded heap entries."""
        best = dict(self._best)
        return sum(best.get((node, phase, hops)) == (total, route)
                   for total, route, node, phase, hops in self._frontier)

    def advance(self, max_expansions: int) -> tuple[HadamardRouteSearch, SearchResult | None]:
        """Settle at most one quantum of non-stale, non-target labels.

        Stale entries and a reached target consume no expansion, including
        at the quantum boundary. All changes belong to the returned cursor.
        The finite label bound is N * 256 * (max_hops + 1), outside the FIFO.
        """
        _budget(max_expansions, 65536, "max_expansions")
        frontier = list(self._frontier)
        best = dict(self._best)
        expansions = self.expansions
        result = self._result
        if result is None:
            while frontier:
                entry = heappop(frontier)
                total, route, node, phase, hops = entry
                if best.get((node, phase, hops)) != (total, route):
                    continue
                if node == self._target:
                    result = SearchResult(route, total, expansions)
                    frontier = []
                    best = {}
                    break
                if expansions - self.expansions == max_expansions:
                    heappush(frontier, entry)
                    break
                expansions += 1
                next_hops = hops + 1
                next_phase = self._model.next_phase(node, phase)
                for neighbor in self._model.neighbors[node]:
                    distance = self._remaining_hops[neighbor]
                    if distance == -1 or next_hops + distance > self._max_hops:
                        continue
                    candidate = (
                        total + self._weights[neighbor]
                        + self._model.penalty(node, phase, neighbor),
                        route + (self._nodes[neighbor],),
                    )
                    state = (neighbor, next_phase, next_hops)
                    if state not in best or candidate < best[state]:
                        best[state] = candidate
                        heappush(frontier, (*candidate, neighbor, next_phase, next_hops))
            if not frontier and result is None:
                raise RuntimeError("reachable route was lost during weighted search")
        updated = HadamardRouteSearch(
            self._model, self._nodes, self._weights, self._remaining_hops,
            self._target, self._max_hops, tuple(frontier), tuple(sorted(best.items())),
            expansions, result,
        )
        return updated, result
