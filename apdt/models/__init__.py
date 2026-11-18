"""APDT Layer 4 models (design 05, section 5.5).

Diagnosis, treatment, care and patient-agency models over the knowledge base. Each module
imports its heavy libraries (pgmpy, xgboost, pymc, pm4py, river, ...) on first use.
`apdt.models.registry` lists every model with its `depends_on` pins.
"""
