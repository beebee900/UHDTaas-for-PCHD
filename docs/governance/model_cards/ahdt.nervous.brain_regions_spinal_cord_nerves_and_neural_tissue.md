# ahdt.nervous.brain_regions_spinal_cord_nerves_and_neural_tissue

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | nervous |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0000955 |
| Intended use | Consciousness level, AVPU and GCS, and autonomic tone |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.autonomic_tone, range.avpu, range.gcs_total, state.consciousness_level |

## Inputs

- `core_temp` (Cel) from `connector:InfectionNeuroConnector#core_temp`
- `glucose` (mmol/L) from `field:15074-8`

## Outputs

- `consciousness_level` (1)
- `avpu` ({code})
- `gcs_total` ({score})
- `autonomic_tone` (1)
- `consciousness_level_status` ({status})
- `avpu_status` ({status})
- `gcs_total_status` ({status})
- `autonomic_tone_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_consciousness_level` | 1 | h | atra-t3-dynamics | assumption |
| `tau_avpu` | 1 | h | atra-t3-dynamics | assumption |
| `tau_gcs_total` | 1 | h | atra-t3-dynamics | assumption |
| `tau_autonomic_tone` | 6 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_consciousness_level`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_avpu`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_gcs_total`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_autonomic_tone`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
