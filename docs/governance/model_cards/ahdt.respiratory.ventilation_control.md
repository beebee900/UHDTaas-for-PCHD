# ahdt.respiratory.ventilation_control

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Ventilatory response to hypoxia and hypercapnia |
| Regulatory status | research |
| Source | Kana M. Mathematical models of cardiovascular control by the autonomic nervous system. Doctoral thesis, Czech Technical University in Prague; 2010. Table 2.4.2, chemoreceptor constants from Ursino M, Magosso E. Am J Physiol Heart Circ Physiol. 2000;279(1):H149-H165; West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 8 (control of ventilation); ATRA design 01 rule R5 assumption register |
| Validation | Chemoreflex with doubled CO2 output; arterial PCO2 held: paco2_rise_mmhg = 1.58186 (tolerance 5, passed) |

## Inputs

- `fio2` (1) from `input:scenario`
- `vco2` (mL/min) from `input:metabolism`
- `respiratory_rate` (/min) from `field:9279-1`
- `shunt_fraction` (1) from `facet:UBERON:0002048/gas_exchange#shunt_fraction`

## Outputs

- `minute_ventilation` (L/min)
- `paco2` (mm[Hg])
- `pao2` (mm[Hg])
- `chemoreceptor_activity` (Hz)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_c` | 2 | s | kana2010 | published |
| `k_ac` | 29.27 | mm[Hg] | kana2010 | published |
| `f_ac_min` | 1.16 | Hz | kana2010 | published |
| `f_ac_max` | 17.07 | Hz | kana2010 | published |
| `pao2_n` | 45 | mm[Hg] | kana2010 | published |
| `ve_rest` | 7 | L/min | west | unverified |
| `paco2_set` | 40 | mm[Hg] | west | unverified |
| `central_gain` | 2.5 | L/min/mm[Hg] | west | unverified |
| `peripheral_gain` | 0.5 | L/min/Hz | atra-assumption | assumption |
| `tau_ve` | 60 | s | atra-assumption | assumption |

## Sources

- **kana2010**: Kana M. Mathematical models of cardiovascular control by the autonomic nervous system. Doctoral thesis, Czech Technical University in Prague; 2010. Table 2.4.2, chemoreceptor constants from Ursino M, Magosso E. Am J Physiol Heart Circ Physiol. 2000;279(1):H149-H165
- **west**: West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 8 (control of ventilation)
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `ve_rest`: Resting minute ventilation as recalled from West; needs a page check
- `paco2_set`: Normal arterial PCO2 as recalled from West; needs a page check
- `central_gain`: Ventilatory response to CO2 within the 2 to 5 L/min/mmHg range recalled from West; needs a page check and per-person calibration
- `peripheral_gain`: Ventilation added per unit of chemoreceptor firing above its resting rate; no published gain for this reduced controller
- `tau_ve`: Time constant of the ventilatory response; to be sourced
