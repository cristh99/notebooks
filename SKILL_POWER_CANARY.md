# Skill Power Foundation v1 — public finite canary

This branch is an isolated, non-sensitive verification capsule for private draft PR
[`cristh99/my_first_repository#110`](https://github.com/cristh99/my_first_repository/pull/110).

It does not import the private implementation. It independently reconstructs four
finite procedures and compares them against frozen weak baselines:

1. `claims-evidence-auditor`
2. `logic-power-meta-controller`
3. `skill-portfolio-governor`
4. `secrets-permission-guardian`

## Frozen design

- 32 scenarios: 8 per skill.
- 16 development cases and 16 canary cases.
- 4 canary cases per skill.
- 3 explicit negative-trigger cases.
- unsafe-action controls for experiment selection and external writes.
- deterministic JSON and SHA-256 semantic digests.
- no credentials, private documents, Notion data, source identities, or production state.
- no model API, cloud service, package install, paid API, GPU, GCloud, or external data call.
- external spend: `$0`.
- capsule network calls: `0`.

## Baseline comparison

The controls are intentionally weak but explicit:

- claims baseline treats any source URL as sufficient;
- logic baseline chooses the cheapest experiment without checking decision value,
  safety, authorization, or budget;
- portfolio baseline checks only that name and description exist;
- secrets baseline recognizes one token family and overreacts to the word `secret`.

The governed procedures must pass all frozen cases, beat the corresponding baseline
for every skill, produce no false activations, and accept no unsafe action.

Expected result:

```text
governed  32/32
baseline   8/32
canary    16/16
false activations  0
unsafe accepts     0
```

## Reproduce locally

```bash
python -m unittest discover -s tests -p "test_skill_power_canary.py" -v
python -m skill_power_canary \
  --scenarios skill_power_canary/frozen_scenarios.json \
  --output /tmp/generated-skill-power-report.json
cmp skill_power_canary/expected_report.json /tmp/generated-skill-power-report.json
```

The workflow installs no project dependencies and uploads no artifact. It only
rebuilds the committed report, requires byte-identical replay, prints file hashes,
and records a GitHub job summary.

## Binding

```text
private repository  cristh99/my_first_repository
private PR          110
private branch      agent/skill-power-foundation-v1
private head        0597408c3f69af715ba463be81de2fbeb369acc5
public base         main
```

## Claim boundary

A PASS supports only the frozen finite procedures, negative-trigger rules,
permission gates, and deterministic canary scenarios in this capsule. It does not
establish general LLM improvement, cross-model transfer, universal security,
production authorization, or `Verified` lifecycle status.
