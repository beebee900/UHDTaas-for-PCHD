# apdt.diagnosis.differential_bn

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Differential diagnosis: noisy-OR Bayesian network over the kb conditions with Bayesian model averaging over three structure variants |
| Regulatory status | research |
| Source | Pearl J. Probabilistic Reasoning in Intelligent Systems. Morgan Kaufmann; 1988; pgmpy (Ankan A, Panda A. SciPy 2015); parameters from the ATRA knowledge base |
| Validation | six persona scenarios (evaluation/models/apdt/scenarios.py): top_diagnosis_agreement = 1 (2026-11-02) |
| Depends on | ahdt.population.population_priors_and_norms 1.0.0 |

## Inputs

- `findings` ({finding})
- `tests` ({test})
- `prior` (1)

## Outputs

- `condition_probability` (1)

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
