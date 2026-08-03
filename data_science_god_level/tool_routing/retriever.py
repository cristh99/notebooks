from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "into", "is", "it", "of", "on", "or", "please", "prefer",
    "route", "step", "that", "the", "this", "to", "tool", "use",
    "using", "user", "wants", "with", "workspace", "agent", "need",
    "needs", "include", "includes", "parameter", "parameters", "string",
    "bool", "handling", "handle", "path", "operation", "request",
    "audit", "note", "planner", "prior", "run",
}

FIELD_WEIGHTS = {
    "name": 28,
    "parameters": 12,
    "description": 6,
    "domain": 5,
}


def _normalize(token):
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _words(text):
    out = []
    for match in TOKEN_RE.finditer(text.lower()):
        token = _normalize(match.group(0))
        if token and token not in STOPWORDS:
            out.append(token)
    return out


def _features(text):
    words = _words(text)
    if not words:
        return ()
    features = ["u:" + word for word in words]
    features.extend(
        "b:" + words[index] + "_" + words[index + 1]
        for index in range(len(words) - 1)
    )
    features.extend(
        "t:" + words[index] + "_" + words[index + 1] + "_" + words[index + 2]
        for index in range(len(words) - 2)
    )
    return tuple(dict.fromkeys(features))


def _feature_multiplier(feature):
    if feature.startswith("t:"):
        return 4
    if feature.startswith("b:"):
        return 2
    return 1


def build_index(tools):
    documents = []
    document_frequency = defaultdict(int)
    all_ids = []

    for tool in tools:
        tool_id = int(tool["id"])
        all_ids.append(tool_id)
        weights = defaultdict(int)
        for field, field_weight in FIELD_WEIGHTS.items():
            for feature in _features(tool.get(field, "")):
                weights[feature] += (
                    field_weight * _feature_multiplier(feature)
                )
        documents.append((tool_id, weights))
        for feature in weights:
            document_frequency[feature] += 1

    total_documents = max(1, len(documents))
    postings = defaultdict(list)
    for tool_id, weights in documents:
        for feature, field_score in weights.items():
            frequency = document_frequency[feature]
            idf = 1.0 + math.log(
                (total_documents + 1.0) / (frequency + 1.0)
            )
            postings[feature].append(
                (tool_id, int(field_score * idf * 256.0))
            )

    return {
        "postings": dict(postings),
        "fallback": tuple(sorted(all_ids)),
    }


def retrieve_tools(index, query, k):
    features = _features(query)
    if not features:
        out = list(index["fallback"][:k])
        if len(out) < k:
            out.extend([-1] * (k - len(out)))
        return out

    scores = {}
    matched = {}
    postings = index["postings"]
    for feature in features:
        entries = postings.get(feature)
        if not entries:
            continue
        query_boost = _feature_multiplier(feature)
        for tool_id, value in entries:
            scores[tool_id] = scores.get(tool_id, 0) + value * query_boost
            matched[tool_id] = matched.get(tool_id, 0) + 1

    if not scores:
        out = list(index["fallback"][:k])
    else:
        ranked = heapq.nlargest(
            k,
            (
                (
                    score + matched[tool_id] * 512,
                    -tool_id,
                )
                for tool_id, score in scores.items()
            ),
        )
        out = [-negative_id for _, negative_id in ranked]

    if len(out) < k:
        present = set(out)
        for tool_id in index["fallback"]:
            if tool_id not in present:
                out.append(tool_id)
                present.add(tool_id)
                if len(out) == k:
                    break
    if len(out) < k:
        out.extend([-1] * (k - len(out)))
    return out


def free_index(index):
    index.clear()
