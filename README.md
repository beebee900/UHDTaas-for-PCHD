# ATRA Health

ATRA Health is a software prototype of two connected digital twins for health care in sub-Saharan Africa, with Nigeria as the reference setting.

- **The Agentic Human Digital Twin (AHDT)** models one person for the whole of their life. It is a federation of 17 member twins: 13 body-system twins, such as the cardiovascular and renal twins, and four twins for the whole body, behaviour and cognition, social context and the population.
- **The Agentic Patient Digital Twin (APDT)** represents the same person while they are a patient in a care episode at a health facility. It supports the medical officer in diagnosis, treatment and care, and it represents the patient's consent and preferences.

Both twins follow the **Agentic Twin Reference Architecture (ATRA)**. It has eight layers and adds explainable AI, cognitive services and a layer of AI agents to the usual digital twin layers.

The core rule is: **clinicians decide, patients consent, agents propose.** The code enforces it. An agent that tries to sign a prescription is refused, and the refusal goes into a tamper-evident audit log. Every patient in the system is synthetic. Open datasets are used only to train and validate models.

## What is in the repository

| Path | Contents |
|---|---|
| `atra/` | Data shapes, connectors, the AHDT tool gateway, the hash-chained audit log, the knowledge base loader, the demo personas |
| `ahdt/` | The 17 twin definitions, ingestion and stores, the knowledge graph, the mechanistic, reference-state, trained and language models, explainers, services, coupling and agents |
| `apdt/` | Care episodes, intake, the clinical reasoner, recommender, explanation bundles and agents |
| `population/` | The population twin |
| `edge/`, `firmware/` | The edge service with its devices and actuators, and the ESP32 board firmware |
| `channels/` | USSD, SMS, voice and a phone simulator |
| `synth/` | The synthetic population generator |
| `kb/` | The knowledge base of sourced clinical entries |
| `policies/` | The Open Policy Agent policies |
| `contracts/` | Schemas generated from the code |
| `apps/web/`, `apps/mobile/` | The clinician web app and the Flutter apps |
| `evaluation/` | Model training, dataset fetching and the acceptance run |
| `deploy/` | Compose profiles, Kubernetes manifests, Terraform, the local PKI and the tool downloads |
| `tests/` | Unit, contract and end-to-end tests |
| `docs/governance/` | The dataset register, the knowledge base review and the model cards |

## Run it

You need Ubuntu 24.04 (Windows users can use WSL), Python 3.12, Node.js 18 or newer, `make`, a C compiler and at least 8 GB of RAM.

    make setup
    make data
    make demo-users
    cd apps/web && npm ci && npm run build && cd ../..
    make run

`make setup` creates `.venv` and installs the locked package versions, including the Dyon framework 0.11.0 from PyPI. `make data` downloads OPA, the ontologies, Hetionet, the gait files and the knowledge base sources into `var/`. `make demo-users` writes the demo logins to `deploy/keycloak/demo-logins.local.txt`.

`make run` starts the services. Wait for the line `all services are healthy`. Then start the web app in a second terminal:

    cd apps/web && npm start

Open http://localhost:3000 and sign in as `medical_officer.fac-a` with the password from `deploy/keycloak/demo-logins.local.txt`.

| Address | Service |
|---|---|
| http://127.0.0.1:8095 | Edge (CoAP on UDP 5683) |
| http://127.0.0.1:8100 | AHDT (gRPC on 50051) |
| http://127.0.0.1:8110 | Population |
| http://127.0.0.1:8181 | OPA |
| http://127.0.0.1:8200 | APDT |
| http://127.0.0.1:8300 | Channels, with the phone simulator at `/simulator` |
| http://localhost:3000 | Web app |

## Trained models

The trained models (`var/models/`) and the model registry (`var/registry/`) are not part of the repository. `make data` does not create them.

- The models trained on synthetic data run on a laptop: `python -m evaluation.models.ahdt.train`.
- The models trained on the open datasets run on a separate machine through the job queue in `ahdt/models/ml/vm/`. Set `ATRA_VM` to `user@host` and `ATRA_VM_KEY` to the SSH key file, then use `push.sh`, `start.sh` and `pull.sh`. `pull.sh` registers the results with `python -m ahdt.models.ml register`.
- `python -m ahdt.models.ml list` lists the registered models and their main metric.

## Tests

    make ci

This runs the linter, the type checker, the contract check, the OPA policy tests, the Kubernetes manifest check and the test suite. `make e2e` runs the browser tests. They need the demo logins and the built web and mobile apps. `make help` lists every target.

## Data and licences

`docs/governance/datasets.md` lists every open dataset with its licence, status and citation. Some datasets allow non-commercial use only. A dataset is used only after its status is `approved`. Each trained model has a card in `docs/governance/model_cards/`.
