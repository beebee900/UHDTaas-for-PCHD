# apdt.diagnosis.neuro_symbolic

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | semantic |
| Fidelity tier | T2 |
| Intended use | SHACL exclusions and red-flag rules over the patient clinical graph; decides list membership and never sets a probability |
| Regulatory status | research |
| Source | SHACL (W3C 2017) with pySHACL; red flags from kb/conditions.yaml |
| Validation | six persona scenarios (evaluation/models/apdt/scenarios.py): top_diagnosis_agreement = 1 (2026-11-02) |

## Inputs

- `candidates` ({condition})

## Outputs

- `excluded` ({condition})
- `must_rule_out` ({condition})

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
