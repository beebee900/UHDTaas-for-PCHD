# ahdt.haematological.bone_marrow_and_erythrocytes.leukopoiesis

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | haematological |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002371 |
| Intended use | Neutrophil and lymphocyte output of the marrow (component of the bone marrow item) |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.lymphocyte_output, state.neutrophil_output |

## Inputs

- none

## Outputs

- `neutrophil_output` (1)
- `lymphocyte_output` (1)
- `neutrophil_output_status` ({status})
- `lymphocyte_output_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_neutrophil_output` | 72 | h | atra-t3-dynamics | assumption |
| `tau_lymphocyte_output` | 168 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_neutrophil_output`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_lymphocyte_output`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
