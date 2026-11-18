# ahdt.digestive.exocrine_pancreas_facet

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | digestive |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0001264 |
| Intended use | Exocrine pancreatic enzyme secretion index |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.enzyme_secretion |

## Inputs

- none

## Outputs

- `enzyme_secretion` (1)
- `enzyme_secretion_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_enzyme_secretion` | 168 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_enzyme_secretion`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
