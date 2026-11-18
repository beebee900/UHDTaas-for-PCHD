# ahdt.whole_body.whole_body_pbpk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Plasma and organ concentrations of metformin and ceftriaxone after a dose |
| Regulatory status | research |
| Source | Valentin J, editor. Basic anatomical and physiological data for use in radiological protection: reference values. ICRP Publication 89. Ann ICRP. 2002;32(3-4).; Metformin hydrochloride tablets, US prescribing information, section 12.3 Pharmacokinetics (openFDA drug label, set id 011de1a5-1ac0-4831-9e8d-26ec79ba2205, effective 2024-08-21).; Ceftriaxone for injection, US prescribing information, Pharmacokinetics (openFDA drug label, set id 03283208-8616-4117-9d2b-aa8046017a4f, effective 2026-01-19).; ATRA design 01 rule R5 assumption register |
| Fidelity note | Generic flow-limited PBPK with ICRP 89 reference physiology; the OSP Suite backend is not installed. One tissue partition coefficient per drug, scaled to the labelled volume of distribution. The simulated metformin peak and half-life differ from the label values; the validation record states both, and the parameters are not tuned to close the gap. |
| Validation | Mass balance of a 500 mg oral dose (ICRP 89 physiology, FDA label clearances); body plus eliminated plus unabsorbed equals the dose. Label comparison, not a pass criterion: metformin Cmax 0.44 against 1.03 mg/L and plasma half-life 8.6 against 6.2 h: max_relative_mass_error = 1.95541e-14 (tolerance 1e-06, passed) |

## Inputs

- `body_weight` (kg) from `field:29463-7`
- `female` (1) from `input:demographics`
- `egfr` (mL/min) from `facet:UBERON:0002113/renal_function#egfr`
- `clearance_factor` (1) from `facet:UBERON:0002107/clearance#clearance_factor`
- `drug` ({atc}) from `input:drug`

## Outputs

- `plasma_concentration` (mg/L)
- `liver_concentration` (mg/L)
- `kidney_concentration` (mg/L)
- `brain_concentration` (mg/L)
- `muscle_concentration` (mg/L)
- `amount_in_body` (mg)
- `eliminated_amount` (mg)
- `unabsorbed_amount` (mg)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `mass_lung_m` | 500 | g | icrp89 | published |
| `mass_heart_m` | 330 | g | icrp89 | published |
| `mass_brain_m` | 1450 | g | icrp89 | published |
| `mass_kidney_m` | 310 | g | icrp89 | published |
| `mass_liver_m` | 1800 | g | icrp89 | published |
| `mass_splanchnic_m` | 1500 | g | icrp89 | published |
| `mass_muscle_m` | 29000 | g | icrp89 | published |
| `mass_adipose_m` | 14500 | g | icrp89 | published |
| `mass_skin_m` | 3300 | g | icrp89 | published |
| `mass_bone_m` | 10500 | g | icrp89 | published |
| `flow_heart_m` | 4 | % | icrp89 | published |
| `flow_brain_m` | 12 | % | icrp89 | published |
| `flow_kidney_m` | 19 | % | icrp89 | published |
| `flow_liver_m` | 6.5 | % | icrp89 | published |
| `flow_splanchnic_m` | 19 | % | icrp89 | published |
| `flow_muscle_m` | 17 | % | icrp89 | published |
| `flow_adipose_m` | 5 | % | icrp89 | published |
| `flow_skin_m` | 5 | % | icrp89 | published |
| `flow_bone_m` | 5 | % | icrp89 | published |
| `total_mass_m` | 73000 | g | icrp89 | published |
| `blood_mass_m` | 5600 | g | icrp89 | published |
| `blood_volume_m` | 5.3 | L | icrp89 | published |
| `cardiac_output_m` | 6.5 | L/min | icrp89 | published |
| `mass_lung_f` | 420 | g | icrp89 | published |
| `mass_heart_f` | 250 | g | icrp89 | published |
| `mass_brain_f` | 1300 | g | icrp89 | published |
| `mass_kidney_f` | 275 | g | icrp89 | published |
| `mass_liver_f` | 1400 | g | icrp89 | published |
| `mass_splanchnic_f` | 1385 | g | icrp89 | published |
| `mass_muscle_f` | 17500 | g | icrp89 | published |
| `mass_adipose_f` | 19000 | g | icrp89 | published |
| `mass_skin_f` | 2300 | g | icrp89 | published |
| `mass_bone_f` | 7800 | g | icrp89 | published |
| `flow_heart_f` | 5 | % | icrp89 | published |
| `flow_brain_f` | 12 | % | icrp89 | published |
| `flow_kidney_f` | 17 | % | icrp89 | published |
| `flow_liver_f` | 6.5 | % | icrp89 | published |
| `flow_splanchnic_f` | 20.5 | % | icrp89 | published |
| `flow_muscle_f` | 12 | % | icrp89 | published |
| `flow_adipose_f` | 8.5 | % | icrp89 | published |
| `flow_skin_f` | 5 | % | icrp89 | published |
| `flow_bone_f` | 5 | % | icrp89 | published |
| `total_mass_f` | 60000 | g | icrp89 | published |
| `blood_mass_f` | 4100 | g | icrp89 | published |
| `blood_volume_f` | 3.9 | L | icrp89 | published |
| `cardiac_output_f` | 5.9 | L/min | icrp89 | published |
| `arterial_blood_fraction` | 16 | % | icrp89 | published |
| `venous_blood_fraction` | 59.5 | % | icrp89 | published |
| `reference_egfr` | 125 | mL/min | icrp89 | published |
| `tissue_density` | 1 | kg/L | atra-assumption | assumption |
| `cardiac_output_exponent` | 0.75 | 1 | atra-assumption | assumption |
| `blood_to_plasma_ratio` | 1 | 1 | atra-assumption | assumption |
| `metformin_bioavailability` | 0.55 | 1 | fda-metformin | published |
| `metformin_vss` | 360 | L | atra-assumption | assumption |
| `metformin_renal_clearance` | 36 | L/h | fda-metformin | published |
| `metformin_nonrenal_clearance` | 0 | L/h | fda-metformin | published |
| `metformin_ka` | 0.27 | 1/h | atra-assumption | assumption |
| `ceftriaxone_bioavailability` | 1 | 1 | atra-assumption | assumption |
| `ceftriaxone_vss` | 9.64 | L | atra-assumption | assumption |
| `ceftriaxone_renal_clearance` | 0.525 | L/h | atra-assumption | assumption |
| `ceftriaxone_nonrenal_clearance` | 0.49 | L/h | atra-assumption | assumption |

## Sources

- **icrp89**: Valentin J, editor. Basic anatomical and physiological data for use in radiological protection: reference values. ICRP Publication 89. Ann ICRP. 2002;32(3-4). Via: Tables 2.8, 2.9, 2.39 and 2.40 and Section 8.2 of the PDF pinned in sources.lock.yaml (icrp-89).
- **fda-metformin**: Metformin hydrochloride tablets, US prescribing information, section 12.3 Pharmacokinetics (openFDA drug label, set id 011de1a5-1ac0-4831-9e8d-26ec79ba2205, effective 2024-08-21).
- **fda-ceftriaxone**: Ceftriaxone for injection, US prescribing information, Pharmacokinetics (openFDA drug label, set id 03283208-8616-4117-9d2b-aa8046017a4f, effective 2026-01-19).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `tissue_density`: Organ masses become volumes at 1 kg/L; ICRP 89 gives masses and the densities of soft tissues differ from 1 by under 10 percent
- `cardiac_output_exponent`: Cardiac output scales with body weight to this power when a person's weight differs from the ICRP reference mass; the usual allometric exponent
- `blood_to_plasma_ratio`: Concentrations are plasma concentrations and blood flows carry them unchanged; no blood to plasma ratio is available for the two drugs
- `metformin_vss`: The label gives an apparent volume V/F of 654 L; multiplying by the bioavailability of 0.55 gives the steady-state volume used to scale the tissue partition coefficients
- `metformin_ka`: First-order absorption rate fitted so that the simulated time of peak plasma concentration equals the 2.75 h of label Table 4 (500 mg single dose)
- `ceftriaxone_bioavailability`: Intravenous drug; the full dose enters the circulation
- `ceftriaxone_vss`: Midpoint of the label range of 5.78 to 13.5 L for the apparent volume of distribution over 0.15 to 3 g doses
- `ceftriaxone_renal_clearance`: Midpoint of the label range of 0.32 to 0.73 L/h for renal clearance
- `ceftriaxone_nonrenal_clearance`: Total plasma clearance (midpoint 1.015 L/h of the label range 0.58 to 1.45) minus the renal clearance
