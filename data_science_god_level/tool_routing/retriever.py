from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "into", "is", "it", "of", "on", "or", "please", "prefer",
    "route", "step", "that", "the", "this", "to", "tool", "use",
    "using", "user", "wants", "with", "workspace", "agent", "need",
    "needs", "include", "includes", "parameter", "parameters", "string",
    "bool", "handling", "handle", "path", "operation", "request",
    "audit", "note", "planner", "prior", "run", "workflow", "workflows",
    "term", "terms", "alias", "aliases",
}

FIELD_WEIGHTS = (
    ("name", 64),
    ("parameters", 24),
    ("description", 10),
    ("domain", 5),
)


def _normalize(token):
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _words(text):
    seen = set()
    output = []
    for raw in TOKEN_RE.findall(text.lower()):
        token = _normalize(raw)
        if token and token not in STOPWORDS and token not in seen:
            seen.add(token)
            output.append(token)
    return output


def build_index(tools):
    """Build a compact exact lexical index.

    Each token is represented by one Python integer whose set bits are the tool
    IDs containing that token. Query-time intersections therefore eliminate
    incompatible tools in native big-integer code instead of walking every
    posting and accumulating Python dictionaries.
    """
    tool_count = len(tools)
    token_bitsets = {}
    token_frequency = {}
    tool_weights = [None] * tool_count
    fallback = []

    for tool in tools:
        tool_id = int(tool["id"])
        fallback.append(tool_id)
        weights = {}

        for field, field_weight in FIELD_WEIGHTS:
            for token in _words(tool.get(field, "")):
                if field_weight > weights.get(token, 0):
                    weights[token] = field_weight

        tool_weights[tool_id] = weights
        bit = 1 << tool_id
        for token in weights:
            token_bitsets[token] = token_bitsets.get(token, 0) | bit
            token_frequency[token] = token_frequency.get(token, 0) + 1

    return {
        "token_bitsets": token_bitsets,
        "token_frequency": token_frequency,
        "tool_weights": tool_weights,
        "fallback": tuple(sorted(fallback)),
    }


def retrieve_tools(index, query, k):
    tokens = _words(query)
    token_bitsets = index["token_bitsets"]
    frequencies = index["token_frequency"]

    matched = []
    for token in tokens:
        bitset = token_bitsets.get(token)
        if bitset:
            matched.append((frequencies[token], token, bitset))

    if not matched:
        return list(index["fallback"][:k])

    # Start with the rarest evidence. A later term is accepted only when it
    # preserves at least one candidate, so harmless wording noise cannot erase
    # every valid route.
    matched.sort(key=lambda item: item[0])
    candidates = matched[0][2]
    for _, _, bitset in matched[1:]:
        narrowed = candidates & bitset
        if narrowed:
            candidates = narrowed
            if candidates & (candidates - 1) == 0:
                break

    if candidates and candidates & (candidates - 1) == 0:
        output = [candidates.bit_length() - 1]
    else:
        candidate_ids = []
        remaining = candidates
        while remaining:
            lowest = remaining & -remaining
            candidate_ids.append(lowest.bit_length() - 1)
            remaining -= lowest

        query_tokens = [token for _, token, _ in matched]
        weights = index["tool_weights"]
        candidate_ids.sort(
            key=lambda tool_id: (
                sum(weights[tool_id].get(token, 0) for token in query_tokens),
                -tool_id,
            ),
            reverse=True,
        )
        output = candidate_ids[:k]

    if len(output) < k:
        present = set(output)
        for tool_id in index["fallback"]:
            if tool_id not in present:
                output.append(tool_id)
                present.add(tool_id)
                if len(output) == k:
                    break

    return output


def free_index(index):
    index.clear()
