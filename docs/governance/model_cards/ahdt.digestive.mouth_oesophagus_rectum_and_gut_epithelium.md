# ahdt.digestive.mouth_oesophagus_rectum_and_gut_epithelium

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | digestive |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Oral intake, swallowing and bowel habit state |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.oral_intake_ok, range.stool_frequency, state.dysphagia |

## Inputs

- none

## Outputs

- `oral_intake_ok` (1)
- `dysphagia` (1)
- `stool_frequency` (/d)
- `oral_intake_ok_status` ({status})
- `dysphagia_status` ({status})
- `stool_frequency_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_oral_intake_ok` | 12 | h | atra-t3-dynamics | assumption |
| `tau_dysphagia` | 48 | h | atra-t3-dynamics | assumption |
| `tau_stool_frequency` | 48 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_oral_intake_ok`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_dysphagia`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_stool_frequency`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
