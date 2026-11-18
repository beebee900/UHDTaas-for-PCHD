import ast
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pydicom
import pytest

from ahdt.ingest import build_pipeline
from ahdt.ingest.pipeline import raw_from_payload
from ahdt.models.catalogue import default_catalogue
from atra.backends import Backends
from atra.config import ROOT, Settings
from atra.consent import demo_registry
from atra.provenance import AuditLog
from evaluation.datasets import fetch as datasets
from synth import conditions, imaging, personas
from synth.build import build
from synth.cohort import treatment_cohort
from synth.params import allele_frequencies, sources
from synth.population import Person, generate

SERVICE_PACKAGES = ("ahdt", "apdt", "atra", "population", "channels", "edge")


@pytest.fixture(scope="module")
def models():
    return default_catalogue()


def test_population_is_reproducible_and_uses_the_sources():
    a, ga = generate(200, 3)
    b, gb = generate(200, 3)
    assert [p.record() for p in a] == [p.record() for p in b]
    assert sorted(ga.edges()) == sorted(gb.edges())
    assert {p.lga for p in a} <= set(sources()["lgas"]["values"])
    assert all(p.hdt_id.startswith("hdt-") for p in a)
    assert {p.hb_genotype for p in a} <= {"HbAA", "HbAS", "HbSS"}
    genes = set(allele_frequencies())
    assert genes and all(set(p.pgx) == genes for p in a if p.sex == "female")


def test_hypertension_prior_combines_age_and_sex():
    def person(age, sex):
        return Person("hdt-000000000000", "x", sex, age, "Ikeja", "h", {}, "HbAA", {})

    assert conditions.p_hypertension(person(10, "male")) == 0.0
    young, old = person(25, "female"), person(65, "female")
    assert conditions.p_hypertension(old) > conditions.p_hypertension(young)
    assert conditions.p_hypertension(person(65, "female")) > \
        conditions.p_hypertension(person(65, "male"))


def test_malaria_is_seasonal():
    assert conditions.malaria_rate_per_day("sep") > conditions.malaria_rate_per_day("jan")


async def test_persona_documents_are_byte_identical(models, tmp_path):
    await personas.write_personas(models, out=tmp_path)
    for path in sorted(tmp_path.glob("*.json")):
        assert path.read_bytes() == (personas.PERSONA_DIR / path.name).read_bytes(), path.name


async def test_persona_readings_pass_the_ingestion_pipeline(tmp_path):
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    doc = personas.load("de")
    result = await pipeline.process(raw_from_payload(o) for o in doc["observations"])
    assert result.accepted and not result.rejected and not result.dropped
    sbp = [r.value for r in result.accepted if r.code.code == "8480-6"]
    assert np.mean(sbp) > 140
    await backends.close()


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_services_never_read_the_truth():
    """No service imports the generators or names the synthetic data directories."""
    for package in SERVICE_PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            assert not any(m == "synth" or m.startswith("synth.") for m in _imports(path)), path
            text = path.read_text()
            assert "var/synth" not in text and '"synth"' not in text, path


def test_cohort_effect_is_known_and_confounded():
    observed, truth = treatment_cohort(5)
    t = observed.column("treated").to_numpy(zero_copy_only=False)
    y = observed.column("sbp_followup").to_numpy()
    naive = y[t].mean() - y[~t].mean()
    ate = truth.column("tau").to_numpy().mean()
    assert ate < 0 and abs(naive - ate) > 1.0


def test_dicom_wrapper_sets_the_person():
    data = imaging.wrap(np.zeros((8, 8), dtype=np.uint8), hdt_id="hdt-0123456789ab",
                        label="normal", when=datetime(2026, 10, 1, tzinfo=UTC), source="test")
    ds = pydicom.dcmread(io.BytesIO(data))
    assert ds.PatientID == "hdt-0123456789ab" and ds.pixel_array.shape == (8, 8)


async def test_build_separates_truth(tmp_path):
    manifest = await build(30, 11, tmp_path)
    base = tmp_path / "11"
    assert manifest["persons"] == 30
    assert (base / "truth" / "persons.jsonl").exists()
    for line in (base / "observations.jsonl").read_text().splitlines():
        assert "resistance_factor" not in line and "parasitaemia" not in line
    first = json.loads((base / "persons.jsonl").read_text().splitlines()[0])
    assert "baseline" not in first


def test_dataset_registry_and_doc_are_current():
    assert datasets.DOC.read_text() == datasets.doc()
    assert all(d["status"] in ("pending", "approved") for d in datasets.load())
