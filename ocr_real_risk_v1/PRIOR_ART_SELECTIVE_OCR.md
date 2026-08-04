# Prior art and claim boundary — selective OCR risk control

This experiment does **not** claim that abstaining OCR, conformal risk control,
or geometric verification are new in general.  Its narrow contribution is an
open, reproducible, location-bound evaluation on public Honduran procurement
PDFs with an untouched final partition and exact finite-sample gates.

## Directly relevant prior art

1. W. Gong, Yiping Zuo, Zijian Lu, Xin He, Weibei Fan, Lianyong Qi, and S. Jin,
   2026, arXiv, *From Plausibility to Verifiability: Risk-Controlled Generative
   OCR for Vision-Language Models* (1 citation at retrieval).
   https://consensus.app/papers/from-plausibility-to-verifiability-riskcontrolled-gong-zuo/9b3641385e5b550fa8e8dc218ed124a3/?utm_source=chatgpt

   The paper frames OCR deployment as selective accept/abstain and uses
   geometric, cross-view stability to reduce extreme and unsupported errors.
   It supports the architectural decision to certify retained risk rather than
   trust plausibility or model confidence.

2. Anastasios Nikolas Angelopoulos, Stephen Bates, Emmanuel Candès, Michael I.
   Jordan, and Lihua Lei, 2021, arXiv, *Learn then Test: Calibrating Predictive
   Algorithms to Achieve Risk Control* (233 citations at retrieval).
   https://consensus.app/papers/learn-then-test-calibrating-predictive-algorithms-to-angelopoulos-bates/3fd9f18c047354ef8a0ee86d8f09fbf7/?utm_source=chatgpt

   The framework motivates freezing a policy after development and testing it
   once on untouched data with explicit finite-sample guarantees.

3. Alexander Rombach and Nijat Mehdiyev, 2026, *International Journal on
   Document Analysis and Recognition*, 29:551–563, *Beyond Accuracy:
   Understanding Model Confidence in Key Information Extraction with Conformal
   Prediction* (2 citations at retrieval).
   https://consensus.app/papers/details/feaa186ee35d5c49b4498cb298366ac2/?utm_source=chatgpt

   It shows that structured document fields differ materially in uncertainty
   and that calibrated prediction sets can route reliable fields while
   deferring uncertain ones.

## What this branch may claim if the final gate passes

- a predeclared policy achieved a simultaneous lower confidence bound of at
  least `10×` reduction in numeric error among accepted outputs versus the
  first-pass baseline;
- the guarantee was obtained on the untouched SHA partition of public Honduran
  procurement documents;
- every observation was bound to source hash, page and PDF coordinates;
- the policy retained at least the predeclared coverage floor;
- all computation used open local software and zero paid infrastructure.

## What it may not claim

- universal OCR SOTA;
- 10× full-text accuracy;
- complete numeric coverage;
- causal superiority on populations outside the frozen sampling frame;
- novelty of selective prediction, conformal risk control or geometric OCR
  verification as general ideas.
