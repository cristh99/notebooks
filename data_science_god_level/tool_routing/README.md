# Data Science God-Level third external gate — Agent Tool Routing

This capsule follows the **original Logic Power v10** after two external observations:

1. AutoLab Adaptive Compression: clean PASS over the published reference.
2. AutoLab Safety Router: public PASS, sealed private FAIL by the accuracy gate.

## Original Logic Power decision

The remaining hypotheses are:

```text
compression specialist
cross-domain system optimizer
broad capability with Safety Router calibration weakness
```

The original engine rejects:

- more compression seeds: same observation under all hypotheses;
- retuning the seen Safety Router private split: post-hoc and inadmissible;
- Scaling Law on H100: separating but dominated by cost and unavailable without paid GPU.

It selects:

```text
agent_tool_routing_hidden
```

## External task

- benchmark: AutoLab `agent_tool_routing`;
- pinned commit: `7aff5fe71dfbe152fb0b8e8ac8087210b4bc27d5`;
- domain: system optimization and information retrieval;
- Python standard library only;
- CPU: 2;
- quality gates: MRR@10 `>=0.82`, Recall@10 `>=0.94`;
- public baseline: `3.85 s`;
- public reference: `0.40 s`;
- hidden benchmark: 3,600 tools, 1,200 queries, median of three runs.

## Candidate

The retriever is a real weighted lexical inverted index:

- normalized unigrams, bigrams, and trigrams;
- field-aware weights for names, parameters, descriptions, and domains;
- inverse-document-frequency weighting;
- touched-posting accumulation only;
- bounded top-k heap;
- deterministic tie-breaking;
- no query counters, public IDs, network, files, subprocesses, or hidden-seed logic.

## Seal rule

The public-development workflow uses the public driver and a separately chosen development seed. It does not use the official hidden seed. After public PASS, `retriever.py` is frozen by SHA-256 and a later commit runs the official hidden verifier without changing the candidate.

The branch remains draft and unmerged. No GCloud or production data is used.
