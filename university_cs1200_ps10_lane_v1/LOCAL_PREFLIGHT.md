# Local preflight

Before the GitHub Actions replay, the lane was downloaded from this branch and executed in an isolated local container.

- Python compilation: PASS.
- Independent oracle, one worker: PASS.
- Independent oracle, four workers: PASS.
- Scientific-field parity assertion: PASS.
- Official source modified: no.
- Canonical Notion state promoted from this local run: no.
- Current-head GitHub Actions replay explicitly requested after the prior successful artifact was found to bind the parent commit rather than the latest PR head.

Only the GitHub Actions artifact and independently inspected receipt may close the canonical PS10 lane.
