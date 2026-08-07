from __future__ import annotations

from itertools import product
from typing import Iterable, Iterator


class Graph:
    """Official-compatible undirected graph representation for CS1200 PS6."""

    def __init__(self, N: int, edges=None, colors=None) -> None:
        if N < 0:
            raise ValueError("N must be nonnegative")
        self.N = N
        self.edges = (
            [set(neighbors) for neighbors in edges]
            if edges is not None
            else [set() for _ in range(N)]
        )
        self.colors = (
            list(colors) if colors is not None else [None for _ in range(N)]
        )
        if len(self.edges) != N or len(self.colors) != N:
            raise ValueError("edge/color arrays must have length N")

    def add_node(self) -> "Graph":
        self.N += 1
        self.edges.append(set())
        self.colors.append(None)
        return self

    def add_edge(self, u: int, v: int) -> "Graph":
        assert v not in self.edges[u]
        assert u not in self.edges[v]
        self.edges[u].add(v)
        self.edges[v].add(u)
        return self

    def remove_edge(self, u: int, v: int) -> "Graph":
        assert v in self.edges[u]
        assert u in self.edges[v]
        self.edges[u].remove(v)
        self.edges[v].remove(u)
        return self

    def reset_colors(self) -> "Graph":
        self.colors = [None for _ in range(self.N)]
        return self

    def clone(self) -> "Graph":
        return Graph(self.N, self.edges, self.colors)

    def clone_and_merge(self, g2: "Graph", g1u, g2v) -> "Graph":
        edges = self.edges + [
            [vertex + self.N for vertex in neighbors] for neighbors in g2.edges
        ]
        graph = Graph(self.N + g2.N, edges)
        if g1u is not None and g2v is not None:
            graph.add_edge(g1u, g2v + self.N)
        return graph

    def is_graph_coloring_valid(self) -> bool:
        if len(self.colors) != self.N or any(
            color is None for color in self.colors
        ):
            return False
        for u in range(self.N):
            for v in self.edges[u]:
                if self.colors[u] == self.colors[v]:
                    return False
        return True


def exhaustive_search_coloring(G: Graph, k: int = 3):
    for coloring in product(range(k), repeat=G.N):
        G.colors = list(coloring)
        if G.is_graph_coloring_valid():
            return G.colors
    G.reset_colors()
    return None


def _complement_neighbors(G: Graph, vertex: int) -> set[int]:
    return set(range(G.N)) - G.edges[vertex] - {vertex}


def bron_kerbosch_max_indep_set(
    G: Graph, R: set[int], P: set[int], X: set[int]
) -> Iterator[set[int]]:
    """Enumerate maximal independent sets using Bron--Kerbosch on complement(G).

    The public starter's pivot loop uses original-graph neighbors where complement
    neighbors are required, which can omit maximal independent sets. This version
    preserves the intended generator interface while repairing that source defect.
    """
    if not P and not X:
        yield R.copy()
        return

    union = P | X
    if union:
        pivot = max(
            union,
            key=lambda item: len(P & _complement_neighbors(G, item)),
        )
        candidates = list(P - _complement_neighbors(G, pivot))
    else:
        candidates = list(P)

    for vertex in candidates:
        compatible = _complement_neighbors(G, vertex)
        yield from bron_kerbosch_max_indep_set(
            G,
            R | {vertex},
            P & compatible,
            X & compatible,
        )
        P.remove(vertex)
        X.add(vertex)


def get_maximal_isets(G: Graph) -> Iterator[set[int]]:
    yield from bron_kerbosch_max_indep_set(
        G, set(), set(range(G.N)), set()
    )


def bfs_2_coloring(
    G: Graph, precolored_nodes: Iterable[int] | None = None
):
    """Color an independent preset with 2 and every residual component with 0/1.

    Uses the class-style discovered set S and frontier F. On failure it resets all
    colors and returns None. Runtime is O(n + m).
    """
    preset = set(precolored_nodes or ())
    if any(not isinstance(v, int) or not 0 <= v < G.N for v in preset):
        raise ValueError("precolored vertex outside graph")

    G.reset_colors()
    for u in preset:
        if G.edges[u] & preset:
            G.reset_colors()
            return None
        G.colors[u] = 2

    S = set(preset)
    for start in range(G.N):
        if start in S:
            continue

        G.colors[start] = 0
        S.add(start)
        F = {start}

        while F:
            next_frontier: set[int] = set()
            for u in F:
                for v in G.edges[u]:
                    if v in preset:
                        continue
                    if v not in S:
                        G.colors[v] = 1 - G.colors[u]
                        S.add(v)
                        next_frontier.add(v)
                    elif G.colors[v] == G.colors[u]:
                        G.reset_colors()
                        return None
            F = next_frontier

    if not G.is_graph_coloring_valid():
        G.reset_colors()
        return None
    return G.colors


def iset_bfs_3_coloring(G: Graph):
    """Find a 3-coloring by removing a maximal independent color class."""
    for independent_set in get_maximal_isets(G):
        coloring = bfs_2_coloring(G, precolored_nodes=independent_set)
        if coloring is not None:
            return coloring
    G.reset_colors()
    return None


if __name__ == "__main__":
    probe = Graph(3).add_edge(0, 1).add_edge(1, 2).add_edge(2, 0)
    print(iset_bfs_3_coloring(probe))
