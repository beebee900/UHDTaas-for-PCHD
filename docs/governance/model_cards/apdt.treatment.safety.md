# apdt.treatment.safety

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | semantic |
| Fidelity tier | T2 |
| Intended use | Interaction, contraindication, allergy, duplication and dose-range checks that produce FHIR DetectedIssue resources |
| Regulatory status | research |
| Source | kb/interactions.yaml, kb/doses |
| Validation | six persona scenarios (evaluation/models/apdt/scenarios.py): expected_issue_recall = 1 (2026-11-02) |
| Depends on | ahdt.hepatobiliary.liver_drug_clearance_capacity 1.0.0, ahdt.renal_urinary.kidney_and_renal_function 1.0.0 |

## Inputs

- `regimen` ({regimen})

## Outputs

- `detected_issue` ({issue})

## Validation report

Persona scenarios.

| Persona | Top diagnosis | Expected | First option | Expected |
|---|---|---|---|---|
| ao | cond.malaria_falciparum | cond.malaria_falciparum | tx.malaria.uncomplicated.artemether_lumefantrine | tx.malaria.uncomplicated.artemether_lumefantrine |
| bm | cond.malaria_falciparum | cond.malaria_falciparum | tx.malaria.severe.artesunate | tx.malaria.severe.artesunate |
| cn | cond.pyelonephritis | cond.pyelonephritis | tx.pyelonephritis.pregnancy.ceftriaxone | tx.pyelonephritis.pregnancy.ceftriaxone |
| de | cond.hypertension | cond.hypertension | tx.hypertension.hearts_ccb_first | tx.hypertension.hearts_ccb_first |
| ef | cond.scd_crisis | cond.scd_crisis | tx.scd_crisis.painful_crisis | tx.scd_crisis.painful_crisis |
| gh | cond.tb_pulmonary | cond.tb_pulmonary | tx.tb.ds.six_month_hrze | tx.tb.ds.six_month_hrze |
