# apdt.diagnosis.llm_narrative

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | llm |
| Fidelity tier | T1 |
| Intended use | Narrative of the differential and a check for missed candidates; every sentence and suggestion cites the kb and nothing is scored |
| Regulatory status | research |
| Source | Hosted, local or offline model through the ATRA converser chain; kb citations |
| Validation | not validated yet |

## Inputs

- `facts` ({fact})

## Outputs

- `narrative` ({text})
- `suggestion` ({condition})
