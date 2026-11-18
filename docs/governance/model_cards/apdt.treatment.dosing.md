# apdt.treatment.dosing

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | semantic |
| Fidelity tier | T2 |
| Intended use | Weight-band and mg/kg dosing with interaction-linked and pharmacogenomic adjustments |
| Regulatory status | research |
| Source | Rules over the ATRA knowledge base (kb/), sources cited per entry; CPIC guidelines via kb/pgx.yaml |
| Validation | six persona scenarios (evaluation/models/apdt/scenarios.py): first_option_concordance = 1 (2026-11-02) |
| Depends on | ahdt.renal_urinary.kidney_and_renal_function 1.0.0, ahdt.whole_body.pharmacogenomics 1.0.0, ahdt.whole_body.whole_body_pbpk 1.0.0 |

## Inputs

- `weight` (kg)
- `egfr` (mL/min/{1.73_m2})

## Outputs

- `dose` (mg)

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
