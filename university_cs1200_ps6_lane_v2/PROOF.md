# Harvard CS1200 PS6 — mandatory technical lane

This document closes the public technical obligations of PS6 in a scoped,
source-bound lane. It does not answer the personal reflection, access a private
grader, assign a course grade, or mark Harvard CS1200 complete.

## 1. Interval coloring

Let the input be intervals with distinct endpoints and let `k` be the maximum
number that overlap at any point.

### Lower bound

At a point where `k` intervals overlap, every pair of those intervals conflicts.
A valid assignment therefore needs at least `k` colors.

### Greedy by starting time

Process intervals in increasing order of start time. Reuse any color whose most
recent interval has ended; otherwise open a new color.

Suppose the algorithm opens color `c` for an interval `I`. Every earlier color
has an interval that overlaps the start of `I`. Together with `I`, those `c+1`
intervals overlap at the same point, so `c+1 <= k`. The greedy solution uses at
most `k` colors. Combined with the lower bound, it is optimal.

Sorting costs `O(n log n)`. Scanning up to `k` colors per interval gives
`O(n log n + nk)`. A min-heap of current ending times reduces the assignment
phase to `O(n log k)`, so the whole algorithm is `O(n log n)`.

The independent oracle tests both variants against the exact maximum overlap on
3,000 deterministic instances.

## 2. Greedy maximal independent set

Scan vertices in any fixed order. Select a vertex when no previously selected
vertex is adjacent to it, then block it and its neighbors.

The selected set is independent by construction. At termination, every omitted
vertex was blocked by a selected neighbor, so no omitted vertex can be added;
the result is maximal. With adjacency lists, each vertex and edge is processed a
constant number of times, giving `O(n + m)`.

Maximal does not mean maximum. The lane never treats this greedy output as an
optimal independent set.

## 3. BFS 2-coloring

For every unvisited component, place one vertex in frontier `F`, add it to the
discovered set `S`, and alternate colors 0 and 1 across each BFS layer. A preset
independent set receives color 2.

If an explored edge has equal binary colors at its endpoints, the component
contains an odd cycle and no 2-coloring exists. Otherwise every edge has distinct
endpoint colors. Every vertex enters a frontier once and every undirected edge is
examined twice, so runtime is `O(n + m)` and auxiliary space is `O(n)`.

## 4. 3-coloring through maximal independent sets

If a graph is 3-colorable, one color class is independent. Extend that class to a
maximal independent set. Removing additional vertices cannot create an odd cycle,
so the residual graph remains bipartite. Conversely, an independent set colored 2
plus a 2-coloring of the residual graph is a valid 3-coloring.

The algorithm enumerates maximal independent sets and invokes BFS on each
residual graph. By the Moon-Moser bound, an `n`-vertex graph has at most
`3^(n/3)` maximal independent sets. Each BFS costs `O(n + m)`, yielding the
course bound `O((n + m) 3^(n/3))`, approximately `O((n + m) 1.45^n)`.

## 5. Source defect and repair

The official starter intends to run Bron-Kerbosch on the complement graph, but
its pivot loop subtracts neighbors in the original graph. That can omit maximal
independent sets. A five-vertex counterexample with edge-mask 431 has four maximal
independent sets, while the starter loop emits only one.

The repaired generator uses complement-neighbor intersections for recursion and
standard complement-graph pivoting. The oracle compares the repaired generator
with brute-force enumeration for every simple graph on at most five vertices.

## 6. Validation contract

The lane requires all of the following:

1. frozen official commit and blob hashes;
2. exact official public 2-color and 3-color test files;
3. no functional public-test failure;
4. declared one-second 3-color timeouts retained in the denominator, because the
   assignment explicitly says some timeouts are expected;
5. exhaustive independent checks on 1,100 graphs;
6. all independent preset subsets on those graphs;
7. exact maximal-independent-set parity against brute force;
8. 3,000 interval-coloring oracles;
9. serial and four-worker scientific-payload parity;
10. bounded experiments on both official graph-generator families;
11. receipt and SHA-256 ledger.

## 7. Scope boundary

A green receipt means the mandatory public technical lane is closed under this
contract. It does **not** mean:

- personal reflection answered;
- optional survey submitted;
- private Canvas/Gradescope grader passed;
- official course grade earned;
- PS6 or Harvard CS1200 exhaustively complete.
