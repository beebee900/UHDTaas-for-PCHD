# ahdt.cardiovascular.heart_chambers_and_valves

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000948 |
| Intended use | Beat-averaged cardiac output, arterial pressures and ventricular volumes |
| Regulatory status | research |
| Source | Smith BW, Chase JG, Nokes RI, Shaw GM, Wake G. Minimal haemodynamic system model including ventricular interaction and valve dynamics. Med Eng Phys. 2004;26(2):131-139. doi:10.1016/j.medengphy.2003.10.001 |
| Validity | {'population': 'adult at rest'} |
| Validation | Smith 2004 reference parameter set; closed-loop volume conservation: stressed_volume_drift_ml = 6.82121e-12 (tolerance 0.001, passed) |

## Inputs

- `heart_rate` (/min) from `model:ahdt.cardiovascular.baroreflex_regulation#heart_rate`
- `contractility_factor` (1) from `model:ahdt.cardiovascular.baroreflex_regulation#contractility_factor`
- `resistance_factor` (1) from `model:ahdt.cardiovascular.baroreflex_regulation#resistance_factor`

## Outputs

- `cardiac_output` (L/min)
- `stroke_volume` (mL)
- `ejection_fraction` (%)
- `heart_rate` (/min)
- `sbp` (mm[Hg])
- `dbp` (mm[Hg])
- `map` (mm[Hg])
- `lv_edv` (mL)
- `lv_esv` (mL)
- `lvedp` (mm[Hg])

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `R_mt` | 0.0158 | mm[Hg].s/mL | smith2004 | published |
| `R_av` | 0.018 | mm[Hg].s/mL | smith2004 | published |
| `R_tc` | 0.0237 | mm[Hg].s/mL | smith2004 | published |
| `R_pv` | 0.0055 | mm[Hg].s/mL | smith2004 | published |
| `R_pul` | 0.1552 | mm[Hg].s/mL | smith2004 | published |
| `R_sys` | 1.0889 | mm[Hg].s/mL | smith2004 | published |
| `L_tc` | 8.0093e-05 | mm[Hg].s2/mL | smith2004 | published |
| `L_pv` | 0.00014868 | mm[Hg].s2/mL | smith2004 | published |
| `L_mt` | 7.6968e-05 | mm[Hg].s2/mL | smith2004 | published |
| `L_av` | 0.00012189 | mm[Hg].s2/mL | smith2004 | published |
| `P_th` | -4 | mm[Hg] | smith2004 | published |
| `A` | 1 | 1 | smith2004 | published |
| `B` | 80 | /s2 | smith2004 | published |
| `C` | 0.375 | s | smith2004 | published |
| `period` | 0.75 | s | smith2004 | published |
| `P_0_pcd` | 0.5003 | mm[Hg] | smith2004 | published |
| `V_0_pcd` | 200 | mL | smith2004 | published |
| `lambda_pcd` | 0.03 | /mL | smith2004 | published |
| `E_es_lvf` | 2.8798 | mm[Hg]/mL | smith2004 | published |
| `V_d_lvf` | 0 | mL | smith2004 | published |
| `P_0_lvf` | 0.1203 | mm[Hg] | smith2004 | published |
| `lambda_lvf` | 0.033 | /mL | smith2004 | published |
| `V_0_lvf` | 0 | mL | smith2004 | published |
| `E_es_rvf` | 0.585 | mm[Hg]/mL | smith2004 | published |
| `V_d_rvf` | 0 | mL | smith2004 | published |
| `P_0_rvf` | 0.2157 | mm[Hg] | smith2004 | published |
| `lambda_rvf` | 0.023 | /mL | smith2004 | published |
| `V_0_rvf` | 0 | mL | smith2004 | published |
| `E_es_spt` | 48.754 | mm[Hg]/mL | smith2004 | published |
| `V_d_spt` | 2 | mL | smith2004 | published |
| `P_0_spt` | 1.1101 | mm[Hg] | smith2004 | published |
| `lambda_spt` | 0.435 | /mL | smith2004 | published |
| `V_0_spt` | 2 | mL | smith2004 | published |
| `E_es_pa` | 0.369 | mm[Hg]/mL | smith2004 | published |
| `V_d_pa` | 0 | mL | smith2004 | published |
| `E_es_pu` | 0.0073 | mm[Hg]/mL | smith2004 | published |
| `V_d_pu` | 0 | mL | smith2004 | published |
| `E_es_ao` | 0.6913 | mm[Hg]/mL | smith2004 | published |
| `V_d_ao` | 0 | mL | smith2004 | published |
| `E_es_vc` | 0.0059 | mm[Hg]/mL | smith2004 | published |
| `V_d_vc` | 0 | mL | smith2004 | published |
| `V_lv0` | 94.6812 | mL | smith2004 | published |
| `V_rv0` | 90.7302 | mL | smith2004 | published |
| `V_pa0` | 43.0123 | mL | smith2004 | published |
| `V_pu0` | 808.458 | mL | smith2004 | published |
| `V_ao0` | 133.338 | mL | smith2004 | published |
| `V_vc0` | 329.78 | mL | smith2004 | published |
| `Q_mt0` | 245.581 | mL/s | smith2004 | published |
| `Q_tc0` | 190.066 | mL/s | smith2004 | published |

## Sources

- **smith2004**: Smith BW, Chase JG, Nokes RI, Shaw GM, Wake G. Minimal haemodynamic system model including ventricular interaction and valve dynamics. Med Eng Phys. 2004;26(2):131-139. doi:10.1016/j.medengphy.2003.10.001 Via: Physiome Model Repository, smith_chase_nokes_shaw_wake_2004.cellml. The file labels pressures as kPa; the values are in mmHg, as in the paper..
