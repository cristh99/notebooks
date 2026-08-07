from __future__ import annotations

from collections import deque
from itertools import combinations, product
from typing import Hashable, Iterable, Iterator, Sequence, TypeVar

from pysat.solvers import Glucose3

T = TypeVar("T", bound=Hashable)


class Graph:
    """Undirected simple graph compatible with the official CS1200 starter."""

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
            raise ValueError("edges and colors must each have length N")

    def add_node(self) -> "Graph":
        self.N += 1
        self.edges.append(set())
        self.colors.append(None)
        return self

    def add_edge(self, u: int, v: int) -> "Graph":
        if not (0 <= u < self.N and 0 <= v < self.N):
            raise IndexError("vertex outside graph")
        if u == v:
            raise ValueError("self-loops are unsupported")
        if v in self.edges[u] or u in self.edges[v]:
            raise ValueError("duplicate edge")
        self.edges[u].add(v)
        self.edges[v].add(u)
        return self

    def remove_edge(self, u: int, v: int) -> "Graph":
        if v not in self.edges[u] or u not in self.edges[v]:
            raise ValueError("edge absent")
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
            {vertex + self.N for vertex in neighbors}
            for neighbors in g2.edges
        ]
        graph = Graph(self.N + g2.N, edges)
        if g1u is not None and g2v is not None:
            graph.add_edge(g1u, g2v + self.N)
        return graph

    def is_independent_set(self, subset: Iterable[int]) -> bool:
        vertices = set(subset)
        return all(not (self.edges[vertex] & vertices) for vertex in vertices)

    def is_graph_coloring_valid(self) -> bool:
        if len(self.colors) != self.N or any(
            color is None for color in self.colors
        ):
            return False
        return all(
            self.colors[u] != self.colors[v]
            for u in range(self.N)
            for v in self.edges[u]
        )


def exhaustive_search_coloring(G: Graph, k: int = 3):
    for coloring in product(range(1, k + 1), repeat=G.N):
        G.colors = list(coloring)
        if G.is_graph_coloring_valid():
            return G.colors
    G.reset_colors()
    return None


def bfs_2_coloring(G: Graph, precolored_nodes=None):
    """Color every non-preset component with 0/1 and the preset with 2."""
    preset = set(precolored_nodes or ())
    if any(not isinstance(v, int) or not 0 <= v < G.N for v in preset):
        raise ValueError("precolored vertex outside graph")

    G.reset_colors()
    if not G.is_independent_set(preset):
        return None
    for vertex in preset:
        G.colors[vertex] = 2

    for source in range(G.N):
        if G.colors[source] is not None:
            continue
        G.colors[source] = 0
        queue: deque[int] = deque([source])
        while queue:
            u = queue.popleft()
            for v in G.edges[u]:
                if G.colors[v] == 2:
                    continue
                if G.colors[v] is None:
                    G.colors[v] = 1 - G.colors[u]
                    queue.append(v)
                elif G.colors[v] == G.colors[u]:
                    G.reset_colors()
                    return None

    if not G.is_graph_coloring_valid():
        G.reset_colors()
        return None
    return G.colors


def _complement_neighbors(G: Graph) -> list[set[int]]:
    all_vertices = set(range(G.N))
    return [all_vertices - {v} - G.edges[v] for v in range(G.N)]


def _bron_kerbosch_complement(
    complement: Sequence[set[int]],
    R: set[int],
    P: set[int],
    X: set[int],
) -> Iterator[set[int]]:
    if not P and not X:
        yield R.copy()
        return

    union = P | X
    if union:
        pivot = max(union, key=lambda u: len(P & complement[u]))
        candidates = list(P - complement[pivot])
    else:
        candidates = list(P)

    for vertex in candidates:
        yield from _bron_kerbosch_complement(
            complement,
            R | {vertex},
            P & complement[vertex],
            X & complement[vertex],
        )
        P.remove(vertex)
        X.add(vertex)


def max_indep_set_gen(G: Graph) -> Iterator[set[int]]:
    """Enumerate maximal independent sets via maximal cliques of complement(G)."""
    complement = _complement_neighbors(G)
    yield from _bron_kerbosch_complement(
        complement, set(), set(range(G.N)), set()
    )


def iset_bfs_3_coloring(G: Graph):
    # Bipartite graphs should not pay the exponential enumeration cost.
    direct = bfs_2_coloring(G)
    if direct is not None:
        return direct

    for independent_set in max_indep_set_gen(G):
        coloring = bfs_2_coloring(G, precolored_nodes=independent_set)
        if coloring is not None:
            return coloring
    G.reset_colors()
    return None


def _color_var(vertex: int, color: int) -> int:
    """Positive, one-based SAT variable for color in {0,1,2}."""
    return 3 * vertex + color + 1


def graph_3_coloring_cnf(G: Graph) -> list[list[int]]:
    clauses: list[list[int]] = []
    for vertex in range(G.N):
        clauses.append([_color_var(vertex, color) for color in range(3)])
        for left, right in combinations(range(3), 2):
            clauses.append(
                [-_color_var(vertex, left), -_color_var(vertex, right)]
            )

    for u in range(G.N):
        for v in G.edges[u]:
            if u < v:
                for color in range(3):
                    clauses.append(
                        [-_color_var(u, color), -_color_var(v, color)]
                    )
    return clauses


def sat_3_coloring(G: Graph):
    """Solve the official PS8 reduction with the real PySAT Glucose3 backend."""
    solver = Glucose3()
    try:
        for clause in graph_3_coloring_cnf(G):
            solver.add_clause(clause)
        if not solver.solve():
            G.reset_colors()
            return None

        positive = {literal for literal in solver.get_model() if literal > 0}
        colors: list[int] = []
        for vertex in range(G.N):
            selected = [
                color
                for color in range(3)
                if _color_var(vertex, color) in positive
            ]
            if len(selected) != 1:
                G.reset_colors()
                raise AssertionError("Glucose model violates exactly-one coloring")
            colors.append(selected[0] + 1)
        G.colors = colors
        if not G.is_graph_coloring_valid():
            G.reset_colors()
            raise AssertionError("decoded Glucose model is not a proper coloring")
        return G.colors
    finally:
        solver.delete()


def three_dimensional_matching_cnf(
    V0: Sequence[T],
    V1: Sequence[T],
    V2: Sequence[T],
    hyperedges: Sequence[tuple[T, T, T]],
) -> list[list[int]]:
    set0, set1, set2 = set(V0), set(V1), set(V2)
    if len(set0) != len(V0) or len(set1) != len(V1) or len(set2) != len(V2):
        raise ValueError("parts must not contain duplicates")
    if (set0 & set1) or (set0 & set2) or (set1 & set2):
        raise ValueError("parts must be disjoint")
    if any(
        edge[0] not in set0 or edge[1] not in set1 or edge[2] not in set2
        for edge in hyperedges
    ):
        raise ValueError("every hyperedge must contain one vertex from each part")

    clauses: list[list[int]] = []
    for vertex in V0:
        clauses.append(
            [index + 1 for index, edge in enumerate(hyperedges) if edge[0] == vertex]
        )

    for i, j in combinations(range(len(hyperedges)), 2):
        if set(hyperedges[i]) & set(hyperedges[j]):
            clauses.append([-(i + 1), -(j + 1)])
    return clauses


def solve_three_dimensional_complete_matching(
    V0: Sequence[T],
    V1: Sequence[T],
    V2: Sequence[T],
    hyperedges: Sequence[tuple[T, T, T]],
):
    clauses = three_dimensional_matching_cnf(V0, V1, V2, hyperedges)
    solver = Glucose3()
    try:
        for clause in clauses:
            solver.add_clause(clause)
        if not solver.solve():
            return None
        positive = {literal for literal in solver.get_model() if literal > 0}
        selected = [
            edge for index, edge in enumerate(hyperedges) if index + 1 in positive
        ]
        if len(selected) != len(V0):
            raise AssertionError("decoded model does not cover V0 exactly once")
        flattened = [vertex for edge in selected for vertex in edge]
        if len(set(flattened)) != len(flattened):
            raise AssertionError("decoded hyperedges are not a matching")
        return selected
    finally:
        solver.delete()
