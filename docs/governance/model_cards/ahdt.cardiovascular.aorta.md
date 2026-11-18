# ahdt.cardiovascular.aorta

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | physics_hybrid |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000947 |
| Intended use | Pulse pressure, pulse wave speed and vascular resistance and compliance of an aortic segment for one cardiac cycle |
| Regulatory status | research |
| Source | Kissas G, Yang Y, Hwuang E, Witschey WR, Detre JA, Perdikaris P. Machine learning in cardiovascular flows modeling: predicting arterial blood pressure from non-invasive 4D flow MRI data using physics-informed neural networks. Comput Methods Appl Mech Eng. 2020;358:112623. doi:10.1016/j.cma.2019.112623; Valentin J, editor. Basic anatomical and physiological data for use in radiological protection: reference values. ICRP Publication 89. Ann ICRP. 2002;32(3-4).; ATRA design 01 rule R5 assumption register |
| Fidelity note | One segment and one cardiac cycle at 70 beats per minute. Wall stiffness follows from an assumed wave speed. |
| Validation | Moens-Korteweg wave speed of the finite-difference solution (Kissas 2020 equations); foot-to-foot speed against the speed that sets the wall stiffness: relative_error_wave_speed = 0.0432794 (tolerance 0.1, passed) |

## Inputs

- `stroke_volume` (mL) from `model:ahdt.cardiovascular.heart_chambers_and_valves#stroke_volume`

## Outputs

- `pulse_pressure` (mm[Hg])
- `pulse_wave_speed` (m/s)
- `resistance` (mm[Hg].s/mL)
- `compliance` (mL/mm[Hg])
- `peak_velocity` (m/s)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `rho` | 1060 | kg/m3 | kissas2020 | published |
| `mu` | 0.0035 | Pa.s | kissas2020 | published |
| `alpha` | 1.1 | 1 | kissas2020 | published |
| `friction_coefficient` | 22 | 1 | kissas2020 | published |
| `diameter_m` | 0.026 | m | icrp89 | published |
| `length_m` | 0.25 | m | atra-assumption | assumption |
| `wave_speed` | 5 | m/s | atra-assumption | unverified |
| `systole_s` | 0.3 | s | atra-assumption | assumption |
| `period_s` | 0.857 | s | atra-assumption | assumption |
| `stroke_volume_ml` | 70 | mL | atra-assumption | assumption |

## Sources

- **kissas2020**: Kissas G, Yang Y, Hwuang E, Witschey WR, Detre JA, Perdikaris P. Machine learning in cardiovascular flows modeling: predicting arterial blood pressure from non-invasive 4D flow MRI data using physics-informed neural networks. Comput Methods Appl Mech Eng. 2020;358:112623. doi:10.1016/j.cma.2019.112623 Via: arXiv:1905.04817v2, equation (1) and Section 3.1.2 (blood density and viscosity).
- **icrp89**: Valentin J, editor. Basic anatomical and physiological data for use in radiological protection: reference values. ICRP Publication 89. Ann ICRP. 2002;32(3-4). Via: Table 7.1, vessel diameter of the ascending aorta, 2.0 to 3.2 cm.
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `length_m`: Length of the modelled segment; a modelling choice, to be replaced by the length from the person's imaging
- `wave_speed`: Pulse wave speed c0 of the segment, which sets the wall stiffness beta = 2 rho c0^2 / sqrt(A0); a typical healthy adult aortic value that still needs a cited source
- `systole_s`: Duration of the half-sine inflow pulse of the ejection
- `period_s`: Cardiac period of the trained beat, 70 beats per minute
- `stroke_volume_ml`: Stroke volume of the trained beat, the inflow integral
