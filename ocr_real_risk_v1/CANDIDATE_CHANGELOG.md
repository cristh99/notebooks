# OCR numeric verifier candidate progression

| Candidate | Status | Accepted / eligible | Natural false accepts | Counterfactual false accepts | External claim |
| --- | --- | ---: | ---: | ---: | --- |
| Handcrafted strict pixel verifier | development baseline | 47 / 571 | 0 | 1 | none |
| Post-outcome consensus rule | rejected after transfer check | 82 / 571 | 0 | 1 | none |
| `digit-forest-v3` | frozen for untouched external validation | 362 / 571 | 0 | 0 | none yet |

`digit-forest-v3` uses a learned ten-class digit forest over four deterministic crop views. Its development evidence is out-of-sample within SROIE, including company-disjoint folds and a train-only evaluation on the SROIE test split. Because all SROIE outcomes have now been opened, the result is development evidence only. The next admissible claim requires the separately predeclared untouched CORD protocol.
