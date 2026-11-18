# Day-0 Download List (P1)

Measured on 2026-10-09. Nothing in this list has been downloaded.

## How to read this list

**Need** says why an item is on the list:

| Need | Meaning |
|---|---|
| Core | The student's main demo needs it: the APDT worked example and use cases UC1 to UC12 in profile p0 |
| Full scope | Needed only to cover a technology, model or profile that the source documents name |
| Build | Used to build or test the program. The running program does not use it |

**Delivery** says what the student receives:

| Delivery | Meaning |
|---|---|
| Ships | Inside the delivered `atra_health/` folder |
| Setup | Not inside the folder. A setup script (`make setup`, `make models`, `make images`) fetches it on the machine that runs the program |
| Outputs ship | Used only to make something that ships, for example a trained model file. The student needs it only to re-train or reproduce an evaluation |

The delivered folder holds the source code, the lock file, configuration, the knowledge base and the trained model files. Third-party libraries, base model weights, container images and toolchains are fetched by setup scripts. Datasets never ship.

**Sizes** are download sizes in MB (10^6 bytes):
- Python wheels: from PyPI and PyTorch index metadata.
- Docker images: compressed linux/amd64 layers from registry manifests. On disk, images take about 2 to 3 times more.
- Files: from HTTP `Content-Length`. Hugging Face models: from the Hub API.

## Status (2026-10-09)

Core and build items are installed on the laptop. Full-scope items are fetched on the VM when their work packages start.

| Item | Where |
|---|---|
| Python core + build set, `requirements/dev.lock` (411 packages) | `.venv` (self-contained) |
| Dyon 0.11.0 | `.venv`, editable from the repository root |
| bge-small-en-v1.5, mms-tts-yor, mms-tts-hau, docling-layout-heron, mms-tts-ibo-baseline configuration | Hugging Face cache |
| faster-whisper-small | Hugging Face cache (was already present) |
| TorchXRayVision densenet121-res224-all | `var/models/` |
| HPO 2026-09-01, UBERON basic 2026-10-01 | `var/ontologies/` |
| OPA 1.21.1 | `var/bin/opa` |
| Flutter 3.47.7 (Dart 3.13.5) | `~/.local/share/atra-tools/flutter` |
| Playwright Chromium (1.6 GB on disk) | `~/.cache/ms-playwright` |

## The project environment is self-contained

The venv does not see anaconda base (`include-system-site-packages = false`). The import check found eight anaconda packages compiled against numpy 1.x (`numexpr`, `bottleneck`, `tables`, `pyerfa`, `catboost`, `gensim`, `prophet`, `ale-py`). pandas and xarray load `numexpr` and `bottleneck` on their own, and both fail under numpy 2.2.6. The student's machine will not have anaconda either. So every package, including torch, is installed into the venv from the lock, and `pip check` reports only the dependency that `overrides.txt` removes (D1).

Before downloading, all 16 Python environments on this machine were scanned. 49 locked packages (206 MB) were already in anaconda base at the locked version, and 54 more (77 MB) only in unrelated virtualenvs. These were not reused, for the reasons above.

Already present outside Python:
- Docker images neo4j:5, influxdb:2.7, redis:7-alpine, eclipse-mosquitto:2, minio, grafana, mongo:5 and nginx
- Java 21 and Node 18

## A. Python libraries: 2,172 MB

| Group | MB | What it is for | Need | Delivery |
|---|---|---|---|---|
| Libraries shared by many packages (numpy, scipy, pandas, transformers, pydantic, grpc and others; torch 176) | 819 | Base of everything | Core | Setup |
| Service, agent and APDT libraries: FastAPI, MCP, A2A, LangGraph, FHIR, HL7, pgmpy, scikit-learn, lifelines, OR-Tools, PyMC, DoWhy/EconML, d3rlpy, pm4py, SHAP, DiCE, MAPIE, medspaCy, MONAI, TorchXRayVision, pydicom, NeMo Guardrails, OpenTelemetry, Qdrant, LlamaIndex, Docling, MLflow, Captum | 242 | The APDT diagnosis, test-selection, treatment, care and agency models; the AHDT services the gateway calls; the agents and APIs; explanations | Core | Setup |
| avalanche-lib | 138 | Continual learning for the sleep-staging model | Full scope | Setup |
| mediapipe | 123 | Gait features from phone video | Full scope | Setup |
| ray | 92 | Model serving and hyperparameter search | Full scope | Setup |
| tellurium | 84 | SBML systems-biology models (β-cell, cortisol) | Full scope | Setup |
| graphrag (Microsoft) | 77 | Community index of the guideline corpus | Full scope | Setup |
| llama-cpp-python | 77 | Runs the edge small language model | Full scope | Setup |
| quantus | 74 | Explanation quality metrics | Full scope | Setup |
| opensim | 72 | Musculoskeletal gait model | Full scope | Setup |
| opendp | 47 | Differentially private releases to the Population twin | Full scope | Setup |
| interpret | 44 | Glass-box risk models (EBM) | Full scope | Setup |
| fmpy | 37 | Co-simulation of the CV, respiratory and renal models (FMI) | Full scope | Setup |
| owlready2 | 27 | Organ–system ontology reasoning (HermiT) | Full scope | Setup |
| pyiceberg 24, flwr 24, duckdb 22, temporalio 15, evidently 13, feast 11 | 109 | Data lake, federated learning, lake queries, durable workflows, drift reports, feature store | Full scope | Setup |
| 44 smaller libraries (Covasim, Mesa, DeepXDE, Darts, River, NeuroKit2, SALib, chaospy, TimeSHAP, Opacus, Langfuse, DeepEval, Ragas, Mem0 and others) | 52 | Models and tools that the AHDT inventory names | Full scope | Setup |
| pytest, hypothesis, ruff, mypy, playwright | 60 | Tests and code checks | Build | Setup |

Core Python total: 1,061 MB. Full-scope-only Python total: 1,051 MB. Build: 60 MB.

## B. Model weights: 7,626 MB new

| Item | MB | What it is for | Need | Delivery |
|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 | 134 | Embeddings for guideline and note search | Core | Setup |
| Systran/faster-whisper-small | 0 (cached; 486) | Speech-to-text in English and Pidgin; consultation scribing | Core | Setup |
| facebook/mms-tts-yor, facebook/mms-tts-hau | 290 | Spoken prompts and the Yoruba audio summary (UC11, FR15) | Core | Setup |
| rnjema-unima/mms-tts-ibo-baseline (configuration files only) | 0 (shares the Yoruba weights) | Fine-tuning configuration for the Igbo voice (FR15). See D3 | Core | Outputs ship (the trained Igbo voice) |
| google/WaxalNLP, `ibo_tts` configuration | not measured | Igbo speech for training the Igbo voice on the VM. See D3 | Core | Outputs ship (the trained Igbo voice) |
| TorchXRayVision densenet121-res224-all | 28 | Chest X-ray second reader (UC5) | Core | Setup |
| docling-project/docling-layout-heron | 172 | Turns guideline PDFs into section trees with citations | Build | Outputs ship (the section trees) |
| facebook/mms-1b-all + yor/hau/ibo adapters | 3,887 | Speech-to-text in Yoruba, Hausa and Igbo. See D4 | Full scope | Setup |
| BAAI/bge-reranker-base | 1,112 | Re-ranks search results | Full scope | Setup |
| Qwen2.5-0.5B-Instruct (safetensors) | 1,000 | Base model for the Nigerian-language LoRA adapters | Full scope | Outputs ship (adapters, a few MB each) |
| Qwen2.5-0.5B-Instruct GGUF Q4_K_M | 491 | Edge small language model (triage and summaries with the cloud down) | Full scope | Setup |
| FremyCompany/BioLORD-2023 | 439 | Biomedical embeddings next to BGE | Full scope | Setup |
| scispaCy side environment (spaCy 35.5, nmslib 14.2, `en_core_sci_sm` 14) | 64 | Biomedical entity linking. See D2 | Full scope | Setup |
| MediaPipe pose_landmarker_full | 9 | Gait features | Full scope | Setup |

Core: 452 MB new. Build: 172 MB. Full scope only: 7,002 MB.

## C. Datasets and ontologies: about 5,603 MB

| Item | MB | What it is for | Need | Delivery |
|---|---|---|---|---|
| NIH/NLM Malaria Cell Images | 353 | Microscopy second reader for the malaria worked example | Core | Outputs ship (trained model) |
| HPO 10, UBERON basic 12 | 22 | Phenotype similarity in APDT diagnosis; organ identifiers | Core | Outputs ship (loaded graph extract) |
| Public chest X-ray samples | not measured (small) | Demo imaging studies for UC5 | Core | Ships (a few images) |
| WESAD | 2,249 | Stress model | Full scope | Outputs ship |
| PTB-XL 1.0.3 | 1,839 | Atrial fibrillation classifier | Full scope | Outputs ship |
| Sleep-EDF Expanded, 20 nights (full set is 8,715) | about 960 | Sleep-staging model | Full scope | Outputs ship |
| MIT-BIH Arrhythmia Database | 77 | Arrhythmia beat classifier (edge ONNX model) | Full scope | Outputs ship |
| GO basic 32, ChEBI lite 55 | 87 | Personal knowledge graph ontologies | Full scope | Outputs ship |
| Hetionet v1.0 | 16 | Domain knowledge graph | Full scope | Outputs ship |
| MENYO-20k, BioModels SBML files | not measured (small) | Yoruba LoRA data; systems-biology models | Full scope | Outputs ship |

Core: about 375 MB. Full scope only: about 5,228 MB.

## D. Docker images: 8,870 MB, all full scope

The demo runs in profile p0. In p0, every container below has an in-process stand-in, so the main demo needs none of them. They prove that the real infrastructure works, one profile at a time, and they are what a real deployment would run.

| Profile | Images and MB | What it is for | Delivery |
|---|---|---|---|
| p1 | kafka 239, apicurio 435, postgis 213, qdrant 75, hapi 446, orthanc 678, htsget-rs 22, toxiproxy 8 (total 2,116) | Real message bus, schema registry, database, vector store, FHIR server, imaging store, genome slices, network-fault testing | Setup |
| p2 | keycloak 265, kong 123, opa 31, vault 193 (total 612) | Login and SMART scopes, API gateway, policy server, secrets and encryption keys | Setup |
| p3 | python:3.12-slim 43, temporal 215 + ui 32, langfuse v2 242, prometheus 114, jaeger 37, superset 323, jupyter 1,303 (total 2,309) | Model registry server, durable workflows, LLM traces, metrics, tracing, population dashboard, research notebooks | Setup |
| p4 | OpenMRS 3.8 (backend 683, frontend 167, gateway 26, mariadb 104), OpenHIM 95, Mirth 730, ODK Central 614 + enketo (built locally), ChirpStack 29 + simulator (built from source) (total 2,428) | Facility EMR, health information exchange, HL7 v2 conversion, CHW forms, LoRaWAN sensors | Setup |
| job | openCARP 1,337 | Cardiac electrophysiology simulation | Setup |
| build | node:20-alpine 48 | Builds the web and OHIF images | Setup |

## E. Toolchains: 2,044 MB measured

| Item | MB | What it is for | Need | Delivery |
|---|---|---|---|---|
| Flutter 3.47.7 SDK | 1,578 | Builds the patient, ward, CHW, personal and carer apps (UC12 needs the CHW app offline) | Core | Outputs ship (web build; APK needs an Android phone, P6) |
| OPA binary | 64 | Authorisation decision on every AHDT call (NFR2) | Core | Setup |
| npm packages for `apps/web` and `apps/ohif-ext` | not measured | Clinician workbench; imaging viewer for UC5 | Core | Setup |
| Playwright browsers | not measured | Web tests | Build | Setup |
| R 27 (+ dependencies), .NET 8 runtime 24, `ospsuite` 47 | 98 | PBPK drug models through PK-Sim. A Python fallback exists | Full scope | Setup |
| k3s 81, kubectl 61, helm 18, linkerd 82, dapr 55, kubeconform 7 | 304 | Kubernetes manifests and their validation | Full scope | Setup |
| PlatformIO + espressif32 platform | not measured | ESP32 firmware build | Full scope | Setup |

## Totals

| Need | MB |
|---|---|
| Core | about 3,530 (Python 1,061, models 452, data 375, toolchains 1,642, plus the unmeasured npm packages) |
| Build | about 232 (plus Playwright browsers) |
| Full scope only | about 22,553 |
| **All** | **about 26,315** |

## Decisions taken while measuring

- **D1. torch.** `requirements/constraints.txt` pins `torch==2.7.0+cpu` from the PyTorch CPU index, so no CUDA build or `nvidia-*` wheel is ever chosen. `requirements/overrides.txt` removes `nvidia-nccl-cu13`, which xgboost declares only for multi-GPU training.
- **D2. scispaCy in a side environment.** scispaCy 0.6.2 requires numpy < 2. scispaCy 0.5.5 requires spaCy < 3.8, and medspaCy 1.3.1 on Python 3.12 requires spaCy ≥ 3.8. No scispaCy release fits the main venv. scispaCy runs in `.venv-scispacy` (anaconda base, numpy 1.26.4) as an entity-linking worker process.
- **D3. Igbo TTS.** `facebook/mms-tts-ibo` does not exist, and no trained Igbo VITS voice with a stated licence and evaluation is published. `rnjema-unima/mms-tts-ibo-baseline` holds fine-tuning configuration only: its weights are byte-identical to `facebook/mms-tts-yor` (SHA-256 `aa4e892d1d4f…`). The Igbo voice is therefore trained in WP14d on the VM: `facebook/mms-tts-yor` fine-tuned on `google/WaxalNLP` `ibo_tts` (CC-BY-SA-4.0) with the `finetune-hf-vits` recipe. The trained voice keeps the CC-BY-NC-4.0 licence of the MMS base.
- **D4. MMS ASR memory.** `mms-1b-all` has 1 billion parameters (3.86 GB at fp32). Loaded as is, it needs about 4 GB of RAM, which is all of the free RAM on this laptop. On a machine with more RAM it loads as is. On this laptop it needs int8 quantisation and on-demand loading.
- **D5. medspaCy needs no spaCy model.** medspaCy builds its pipeline on a blank spaCy English pipeline, so `en_core_web_sm` is not downloaded.

## Running on an ARM VM

Oracle's free-tier VMs often use ARM (aarch64) processors. All checked container images also have ARM builds. These Python packages have no ARM build on PyPI:
- `opensim` (gait model)
- the `tellurium` stack (`libroadrunner`, `antimony`, `phrasedml`)

Another 25 packages ship only as source on ARM. Most are pure Python. A few (`econml`, `ecos`, `quadprog`, `llama-cpp-python`, the medspaCy C helpers) compile at install, which needs build tools on the VM. On an x86-64 VM, every item installs as measured above.
