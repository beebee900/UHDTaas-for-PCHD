# apdt.care.pathways

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | semantic |
| Fidelity tier | T2 |
| Intended use | PlanDefinition $apply to a draft CarePlan and Tasks, and token-replay conformance of executed tasks against the BPMN pathway |
| Regulatory status | research |
| Source | HL7 FHIR R4 PlanDefinition/$apply; BPMN 2.0 (OMG 2011); pm4py (Berti A et al. arXiv:1905.06169) |
| Validation | not validated yet |

## Inputs

- `diagnosis` ({condition})
- `task_log` ({task})

## Outputs

- `care_plan` ({resource})
- `deviation` ({task})
