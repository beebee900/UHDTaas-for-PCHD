# ahdt.whole_body.pharmacogenomics

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | semantic |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Metaboliser phenotypes and CPIC prescribing recommendations |
| Regulatory status | research |
| Source | Clinical Pharmacogenetics Implementation Consortium (CPIC) guidelines for CYP2D6, CYP2C19, CYP2B6 and G6PD; gene rules and recommendations in kb/pgx.yaml |
| Validation | CPIC phenotype tables: CYP2D6 *1/*4 and CYP2C19 *1/*17: phenotype_mismatches = 0 (tolerance 0, passed) |

## Inputs

- `diplotypes` ({gene:diplotype}) from `input:genome`
- `measured_phenotypes` ({gene:phenotype}) from `input:lab`
- `drugs` ({name}) from `input:medications`
- `indications` ({drug:indication}) from `input:medications`

## Outputs

- `phenotypes` ({gene:phenotype})
- `recommendations` ({list})
