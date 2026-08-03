# Data Science God-Level cross-domain gate — AutoLab Safety Router

This layer follows the **original Logic Power v10** decision after the clean adaptive-compression PASS.

## Remaining distinction

```text
compression-task specialist
versus
broad Data Science capability
```

The original planner rejects `more_compression_seeds` and a compression-only prior-art audit because both hypotheses produce the same observation. It selects a different external domain:

```text
safety_router_private_split
```

## Public development phase

- task: AutoLab `safety_router`;
- pinned AutoLab commit: `7aff5fe71dfbe152fb0b8e8ac8087210b4bc27d5`;
- environment: Python 3.11, NumPy 1.26.4, CPU only;
- editable file under the benchmark contract: `train.py`;
- objective: minimize trainable parameters;
- public reference: `2,081` parameters;
- private constraints:
  - accuracy at least `0.64`;
  - unsafe recall at least `0.66`;
  - safe recall at least `0.57`.

The public phase downloads only `train`, `validation`, and `test_public`. It does not download or inspect the private split.

The candidate searches hidden widths `1,2,3,4,6,8,12,15` under several deterministic seeds and class weights. It requires both validation and public constraints, prefers a positive gate margin, minimizes parameter count, and then refits the selected architecture on train+validation.

## Seal rule

The private split will not be evaluated until:

1. the public workflow passes;
2. `train.py` and the emitted model are frozen by SHA-256;
3. seeds, thresholds, model dimensions, and AutoLab inputs are recorded;
4. a separate commit introduces the private evaluator without altering the frozen candidate.

The PR remains draft and unmerged. No GCloud or production data is used.
