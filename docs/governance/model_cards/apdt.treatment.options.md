# apdt.treatment.options

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | semantic |
| Fidelity tier | T2 |
| Intended use | Guideline-concordant treatment options by diagnosis, severity, age, pregnancy, weight, intake and prior treatment, with the rules that fired |
| Regulatory status | research |
| Source | Rules over the ATRA knowledge base (kb/), sources cited per entry |
| Validation | six persona scenarios (evaluation/models/apdt/scenarios.py): first_option_concordance = 1 (2026-11-02) |
| Depends on | ahdt.whole_body.maternal_foetal 1.0.0 |

## Inputs

- `diagnosis` ({condition})

## Outputs

- `option` ({option})

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
