# C04 synthetic data dictionary

All rows are synthetic engineering fixtures. No field is a clinical reference range or individual health record.

| Field | Type | Unit / domain | Meaning |
|---|---|---|---|
| `subject_id` | string | synthetic ID | Deterministic row identifier; not a person. |
| `scenario` | enum | baseline, high_flow, low_binding_capacity, low_oxygen_partial_pressure | Synthetic fixture family. |
| `split` | enum | train, test | Deterministic within-fixture partition. |
| `sex_observed` | enum | F, M | Synthetic metadata for a falsifiable residual comparison; no causal interpretation. |
| `cardiac_output_L_min` | float | L/min | Synthetic blood-flow state `Q`. |
| `hb_g_dL` | float | g/dL | Synthetic hemoglobin state. |
| `sao2_fraction` | float | [0,1] | Synthetic arterial oxygen saturation fraction. |
| `svo2_fraction` | float | [0,1] | Synthetic venous oxygen saturation fraction. |
| `pao2_mmHg` | float | mmHg | Synthetic arterial oxygen partial pressure. |
| `pvo2_mmHg` | float | mmHg | Synthetic venous oxygen partial pressure. |
| `active_mass_kg` | float | kg | Synthetic active-mass covariate used by the size-only comparator. |
| `blood_volume_L` | float | L | Synthetic state retained for mechanism completeness; not used by the Fick identity. |
| `true_caO2_ml_L` | float | mL O2/L blood | Generator truth for arterial oxygen content. |
| `true_cvO2_ml_L` | float | mL O2/L blood | Generator truth for venous oxygen content. |
| `true_vo2_ml_min` | float | mL O2/min | Generator truth from `Q * (CaO2-CvO2)`. |
| `observed_vo2_ml_min` | float | mL O2/min | Synthetic observation after zero-mean multiplicative measurement noise. |

## Conventions

Oxygen content uses `10 * (1.34 * Hb * saturation + 0.003 * PO2)` to convert the internal dL expression to mL O2/L. Fick then multiplies L/min by mL O2/L, yielding mL O2/min. CSV floating-point fields are serialized to six decimals; the independent Node replay therefore uses a 0.005 mL/min absolute tolerance.

There are no missing values, timestamps, patient identifiers, treatments, diagnoses or outcomes from real people. Transformations and split logic are fully specified in `generator.py`; seed/sizes live in `config.json`.
