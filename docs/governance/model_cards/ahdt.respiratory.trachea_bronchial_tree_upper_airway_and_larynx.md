# ahdt.respiratory.trachea_bronchial_tree_upper_airway_and_larynx

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Airway obstruction state from asthma or COPD activity |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.airway_obstruction_index |

## Inputs

- `exacerbation_risk` (1) from `model:ahdt.respiratory.exacerbation_risk#exacerbation_risk`

## Outputs

- `airway_obstruction_index` (1)
- `airway_obstruction_index_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_airway_obstruction_index` | 48 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_airway_obstruction_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
