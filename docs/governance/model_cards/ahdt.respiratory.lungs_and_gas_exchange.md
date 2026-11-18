# ahdt.respiratory.lungs_and_gas_exchange

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0002048 |
| Intended use | Arterial blood gases and oxygen saturation from ventilation and perfusion |
| Regulatory status | research |
| Source | Severinghaus JW. Simple, accurate equations for human blood O2 dissociation computations. J Appl Physiol Respir Environ Exerc Physiol. 1979;46(3):599-602. doi:10.1152/jappl.1979.46.3.599; West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapters 2 (ventilation), 5 (gas transport) and 7 (mechanics); ATRA design 01 rule R5 assumption register |
| Validity | {'altitude': 'sea level', 'state': 'steady'} |
| Validation | Severinghaus 1979 standard curve; P50 of 26.8 mmHg: saturation_error_at_p50 = -0.00140531 (tolerance 0.005, passed) |

## Inputs

- `respiratory_rate` (/min) from `field:9279-1`
- `tidal_volume` (mL) from `input:ventilation`
- `fio2` (1) from `input:scenario`
- `hb` (g/dL) from `facet:UBERON:0000178/oxygen_carriage#hb`
- `cardiac_output` (L/min) from `facet:UBERON:0000948/haemodynamics#cardiac_output`

## Outputs

- `pao2` (mm[Hg])
- `paco2` (mm[Hg])
- `PAO2` (mm[Hg])
- `aa_gradient` (mm[Hg])
- `spo2` (%)
- `cao2` (mL/dL)
- `shunt_fraction` (1)
- `alveolar_ventilation` (L/min)
- `minute_ventilation` (L/min)
- `peak_airway_pressure` (cm[H2O])

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `p_atm` | 760 | mm[Hg] | west | published |
| `p_h2o` | 47 | mm[Hg] | west | published |
| `rq` | 0.8 | 1 | west | published |
| `k_paco2` | 0.863 | mm[Hg].L/mL | west | published |
| `hufner` | 1.34 | mL/g | west | published |
| `o2_solubility` | 0.003 | mL/dL/mm[Hg] | west | published |
| `dead_space` | 150 | mL | west | published |
| `vco2` | 200 | mL/min | west | published |
| `vo2` | 250 | mL/min | west | published |
| `shunt_fraction` | 0.03 | 1 | atra-assumption | assumption |
| `compliance` | 0.1 | L/cm[H2O] | west | unverified |
| `airway_resistance` | 2 | cm[H2O].s/L | west | unverified |
| `inspiratory_time` | 1 | s | atra-assumption | assumption |

## Sources

- **severinghaus1979**: Severinghaus JW. Simple, accurate equations for human blood O2 dissociation computations. J Appl Physiol Respir Environ Exerc Physiol. 1979;46(3):599-602. doi:10.1152/jappl.1979.46.3.599
- **west**: West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapters 2 (ventilation), 5 (gas transport) and 7 (mechanics)
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `shunt_fraction`: Physiological shunt of a few percent; calibrated to the person's SpO2
- `compliance`: Typical total respiratory system compliance as recalled from West; needs a page check
- `airway_resistance`: Typical adult airway resistance as recalled from West; needs a page check
- `inspiratory_time`: Inspiratory time used for the mean inspiratory flow in the peak pressure; replaced by the observed value when available
