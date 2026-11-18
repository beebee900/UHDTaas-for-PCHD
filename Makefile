# ATRA health: build, check and run targets (design 02 and 08).
PY      := .venv/bin/python
PIP     := $(PY) -m pip
TORCH   := https://download.pytorch.org/whl/cpu
OPA     := var/bin/opa
PROFILE ?= p0
BASE    ?= HEAD^
# Heavy targets run under a memory cap where a systemd user session works, so they fail alone
# instead of exhausting the machine. Set CAP= to run without it.
CAP_CMD := systemd-run --user --scope --quiet -p MemoryMax=2G -p MemorySwapMax=0
CAP     ?= $(shell $(CAP_CMD) true >/dev/null 2>&1 && echo $(CAP_CMD))

.PHONY: help setup contracts contracts-check lint typecheck test opa-test ci ci-fast web mobile e2e run demo-users demo-seed \
        pki profile-up profile-down clean-data kb-sources kb-codes kb-check kb-review \
        firmware-tools firmware firmware-test data k8s-tools k8s-check

help:
	@echo "setup            create .venv and install the locked core and build packages"
	@echo "contracts        regenerate contracts/ and policies/opa/data.json from the code"
	@echo "ci               lint, type checks, contract drift, policy tests, unit and contract tests"
	@echo "ci-fast          the ci checks, with type checks and tests limited to what changed since BASE (default HEAD^)"
	@echo "kb-sources       download the kb sources in kb/sources.yaml and build their section trees"
	@echo "kb-codes         look up every kb code and rewrite kb/terminology"
	@echo "kb-check         number check of every kb entry against its cited source"
	@echo "kb-review        write docs/governance/kb_review.pdf for sign-off"
	@echo "data             download OPA, the ontologies, Hetionet, the gait files and the kb sources into var and build their stores"
	@echo "firmware-tools   install PlatformIO in var/tools (its packages download on first build)"
	@echo "firmware         build the ESP32 board image"
	@echo "firmware-test    native unit tests of the ESP32 framing, encoding and filtering code"
	@echo "k8s-tools        download kustomize, kubeconform and the schemas of deploy/k8s into var/k8s"
	@echo "k8s-check        render every deploy/k8s overlay and validate it with kubeconform (offline)"
	@echo "web              generate the API clients, type-check and build the web app"
	@echo "mobile           generate, analyse, test and build the Flutter apps (ward web build)"
	@echo "e2e              browser tests of the web and Flutter web apps (needs demo-users, web, mobile)"
	@echo "run              start the services of PROFILE (default p0)"
	@echo "demo-users       write demo logins to deploy/keycloak/demo-logins.local.txt"
	@echo "demo-seed        open an episode for each demo persona (services must be running)"
	@echo "pki              local CA and service certificates in deploy/pki/out"
	@echo "profile-up/down  start or stop the containers of PROFILE (p1 to p4)"

setup:
	test -x $(PY) || python3.12 -m venv .venv
	$(PIP) install --no-deps --extra-index-url $(TORCH) -r requirements/dev.lock
	if test -f ../../../dyon/__init__.py; then $(PIP) install --no-deps -e ../../..; \
	  else $(PIP) install --no-deps dyon==0.11.0; fi

contracts:
	$(PY) -m atra.schemagen

contracts-check:
	$(PY) -m atra.schemagen --check

lint:
	.venv/bin/ruff check .

typecheck:
	.venv/bin/mypy atra ahdt apdt population channels edge contracts synth run.py

opa-test:
	$(OPA) test policies/opa

test:
	$(PY) -m pytest -q

ci: lint typecheck contracts-check opa-test k8s-check test

ci-fast: lint contracts-check opa-test
	@pkgs="$$($(PY) -m tests.affected mypy $(BASE))"; echo "mypy: $${pkgs:-nothing}"; \
	  test -z "$$pkgs" || .venv/bin/mypy $$pkgs
	@test -z "$$($(PY) -m tests.affected k8s $(BASE))" || $(MAKE) k8s-check
	@tests="$$($(PY) -m tests.affected pytest $(BASE))"; echo "pytest: $$(echo $$tests | wc -w) files"; \
	  test -z "$$tests" || $(PY) -m pytest -q $$tests

kb-sources:
	$(CAP) $(PY) -m apdt.knowledge.sourcing fetch
	$(CAP) $(PY) -m apdt.knowledge.sourcing sections

kb-codes:
	$(PY) -m apdt.knowledge.sourcing verify-codes

kb-check:
	$(CAP) $(PY) -m apdt.knowledge.sourcing check

kb-review:
	$(CAP) $(PY) -m apdt.knowledge.sourcing review

OPA_URL := https://github.com/open-policy-agent/opa/releases/download/v1.21.1/opa_linux_amd64_static
ONT     := var/ontologies
UA      := atra-health-datasets/0.1
GAIT    := A-novel-walking-speed-estimation-scheme-and-its-application-to-treadmill-control-for-gait-1743-0003-9-62-S1.ogv

# Each download is checked against the sha256 of the release the stores were built from.
data:
	mkdir -p var/bin $(ONT) var/hetionet var/datasets/yoon-2012-treadmill
	cp evaluation/datasets/datasets.lock.yaml var/datasets.lock.yaml.orig
	cp kb/sources.lock.yaml var/sources.lock.yaml.orig
	test -x $(OPA) || (curl -fsSL -o $(OPA) $(OPA_URL) && chmod +x $(OPA))
	test -f $(ONT)/hp.obo || curl -fsSL -o $(ONT)/hp.obo \
	  https://github.com/obophenotype/human-phenotype-ontology/releases/download/v2026-09-01/hp.obo
	test -f $(ONT)/uberon-basic.obo || curl -fsSL -o $(ONT)/uberon-basic.obo \
	  https://github.com/obophenotype/uberon/releases/download/v2026-10-01/uberon-basic.obo
	test -f $(ONT)/go-basic.obo || curl -fsSL -o $(ONT)/go-basic.obo \
	  http://purl.obolibrary.org/obo/go/go-basic.obo
	test -f $(ONT)/chebi_lite.obo || curl -fsSL -o $(ONT)/chebi_lite.obo \
	  https://ftp.ebi.ac.uk/pub/databases/chebi/ontology/chebi_lite.obo
	test -f var/hetionet/hetionet-v1.0.json.bz2 || curl -fsSL -o var/hetionet/hetionet-v1.0.json.bz2 \
	  https://media.githubusercontent.com/media/hetio/hetionet/main/hetnet/json/hetionet-v1.0.json.bz2
	test -f var/datasets/yoon-2012-treadmill/$(GAIT) || curl -fsSL -A "$(UA)" \
	  -o var/datasets/yoon-2012-treadmill/$(GAIT) https://upload.wikimedia.org/wikipedia/commons/1/1d/$(GAIT)
	test -f var/datasets/mediapipe-pose-lite/pose_landmarker_lite.task || \
	  $(PY) -m evaluation.datasets.fetch mediapipe-pose-lite
	mv var/datasets.lock.yaml.orig evaluation/datasets/datasets.lock.yaml
	printf '%s\n' \
	  "668506eb17a2eaa1fce6cc0d1f42ef85125d4ac5bda5fc74d1152d0c77145031  $(OPA)" \
	  "93dace952fcb3ec4728818857f6ba76bc2d5312f4d83266519b8694b8e798f22  $(ONT)/hp.obo" \
	  "5e1eff802a4d99f7a072f6cd239f50cffdb70aec2b11e33edf00e66746a0a75b  $(ONT)/uberon-basic.obo" \
	  "b08d45b268b8c24ccb2513dbbbc7d4df9f6521c099b413f79eb31e06e0fa3bcc  $(ONT)/go-basic.obo" \
	  "5e5d1b3e95aa690fcb11c42e8936fd074b2e6b939d239a55a5f5864af733469d  $(ONT)/chebi_lite.obo" \
	  "a342ab57e9073e6c02bb5e109d1f16917e6f933be4e5c77ebbaebfa26b984c19  var/hetionet/hetionet-v1.0.json.bz2" \
	  "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a  var/datasets/mediapipe-pose-lite/pose_landmarker_lite.task" \
	  "f06a3b0d9eb258d6f47170ffc08b456e340731753f936af23e20780618767d1f  var/datasets/yoon-2012-treadmill/$(GAIT)" \
	  | sha256sum -c
	$(CAP) $(PY) -m apdt.knowledge.sourcing fetch \
	  $$($(PY) -c "from apdt.knowledge.sources import load_lock; print(' '.join(load_lock()))")
	! diff -U0 var/sources.lock.yaml.orig kb/sources.lock.yaml | grep -q '^+ *sha256'
	mv var/sources.lock.yaml.orig kb/sources.lock.yaml
	$(CAP) $(PY) -m apdt.knowledge.sourcing sections
	test -d $(ONT)/store || $(CAP) $(PY) -m ahdt.knowledge.ontology build
	test -d var/hetionet/store || $(CAP) $(PY) -m ahdt.knowledge.hetionet build

K8S     := var/k8s
K8S_V   := v1.37.1
SCHEMAS := https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/$(K8S_V)-standalone-strict
CRDS    := https://raw.githubusercontent.com/datreeio/CRDs-catalog/main
K8S_KINDS := daemonset-apps-v1 deployment-apps-v1 statefulset-apps-v1 networkpolicy-networking-v1 \
             clusterrole-rbac-v1 clusterrolebinding-rbac-v1 role-rbac-v1 rolebinding-rbac-v1 \
             configmap-v1 namespace-v1 persistentvolumeclaim-v1 secret-v1 service-v1 serviceaccount-v1

# Every file is checked against deploy/k8s/tools.sha256.
k8s-tools:
	mkdir -p $(K8S)/bin $(K8S)/dl $(K8S)/schemas/dapr.io
	test -f $(K8S)/dl/kubeconform-linux-amd64.tar.gz || curl -fsSL -o $(K8S)/dl/kubeconform-linux-amd64.tar.gz \
	  https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz
	test -f $(K8S)/dl/kustomize_v5.8.3_linux_amd64.tar.gz || curl -fsSL -o $(K8S)/dl/kustomize_v5.8.3_linux_amd64.tar.gz \
	  https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.8.3/kustomize_v5.8.3_linux_amd64.tar.gz
	for k in $(K8S_KINDS); do test -f $(K8S)/schemas/$$k.json || \
	  curl -fsSL -o $(K8S)/schemas/$$k.json $(SCHEMAS)/$$k.json || exit 1; done
	for k in component_v1alpha1 configuration_v1alpha1 subscription_v2alpha1; do test -f $(K8S)/schemas/dapr.io/$$k.json || \
	  curl -fsSL -o $(K8S)/schemas/dapr.io/$$k.json $(CRDS)/dapr.io/$$k.json || exit 1; done
	cd $(K8S) && sha256sum -c --quiet "$(CURDIR)/deploy/k8s/tools.sha256"
	tar -xzf $(K8S)/dl/kubeconform-linux-amd64.tar.gz -C $(K8S)/bin kubeconform
	tar -xzf $(K8S)/dl/kustomize_v5.8.3_linux_amd64.tar.gz -C $(K8S)/bin kustomize

k8s-check:
	for overlay in deploy/k8s/overlays/*/; do \
	  $(K8S)/bin/kustomize build $$overlay | $(K8S)/bin/kubeconform -strict -summary \
	    -schema-location '$(K8S)/schemas/{{ .ResourceKind }}{{ .KindSuffix }}.json' \
	    -schema-location '$(K8S)/schemas/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' - \
	  || exit 1; done

PIO     := "$(CURDIR)/var/tools/pio-venv/bin/pio"
PIO_ENV := PLATFORMIO_CORE_DIR="$(CURDIR)/var/tools/platformio"

firmware-tools:
	test -x $(PIO) || (python3.12 -m venv var/tools/pio-venv && \
	  var/tools/pio-venv/bin/pip install platformio==6.2.0)

firmware:
	cd firmware/esp32 && $(PIO_ENV) $(CAP) $(PIO) run -e esp32dev

firmware-test:
	cd firmware/esp32 && $(PIO_ENV) $(CAP) $(PIO) test -e native

web:
	cd apps/web && npm run gen:api && npx tsc --noEmit && NEXT_TELEMETRY_DISABLED=1 npm run build

FLUTTER ?= $(HOME)/.local/share/atra-tools/flutter/bin/flutter

mobile:
	cd apps/mobile && $(abspath $(PY)) tool/gen_api.py && $(FLUTTER) gen-l10n && \
	  $(dir $(FLUTTER))dart run build_runner build --delete-conflicting-outputs && \
	  $(FLUTTER) analyze && $(FLUTTER) test && \
	  $(FLUTTER) build web --target lib/main_ward.dart --no-web-resources-cdn

e2e:
	$(PY) -m pytest -q -m e2e tests/e2e

run:
	$(PY) run.py --profile $(PROFILE)

demo-users:
	$(PY) -m atra.demo_users

demo-seed:
	$(PY) -m apdt.demo_seed

pki:
	$(PY) deploy/pki/make_pki.py

profile-up:
	docker compose -f deploy/compose/$(PROFILE).yaml up -d --wait

profile-down:
	docker compose -f deploy/compose/$(PROFILE).yaml down

clean-data:
	rm -rf var/data var/audit var/registry
