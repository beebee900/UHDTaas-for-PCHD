# apdt.diagnosis.xgboost_comparator

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Multi-class comparator for the primary diagnosis with 90 % conformal sets; a disagreement with the network is a signal for the clinician |
| Regulatory status | research |
| Source | Chen T, Guestrin C. XGBoost: a scalable tree boosting system. KDD 2016; split-conformal sets (Lei J et al. JASA 2018;113(523):1094-1111; MAPIE LAC score); trained on the ATRA synthetic cohort (evaluation/models/apdt) |
| Validation | not validated yet |

## Inputs

- `findings` ({finding})
- `tests` ({test})

## Outputs

- `class_probability` (1)
- `conformal_set` ({condition})
