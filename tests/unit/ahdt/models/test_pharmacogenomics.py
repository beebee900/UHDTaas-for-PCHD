import pytest

from ahdt.models.reference import default_kb
from ahdt.models.whole_body.pharmacogenomics import PharmacogenomicsModel


@pytest.fixture(scope="module")
def model() -> PharmacogenomicsModel:
    return PharmacogenomicsModel(kb=default_kb())


def run(model, **inputs):
    return model.evaluate(model.parameters(), {}, inputs)


def test_cyp2d6_activity_score(model):
    # *1 (1.0) + *41 (0.25) = 1.25 → normal metabolizer; *4/*41 = 0.25 → intermediate.
    out = run(model, diplotypes={"CYP2D6": "*1/*41"})
    assert out["phenotypes"] == ["CYP2D6:Normal Metabolizer"]
    out = run(model, diplotypes={"CYP2D6": "*4/*41"}, drugs=["codeine"])
    assert out["phenotypes"] == ["CYP2D6:Intermediate Metabolizer"]
    assert out["recommendations"][0].split("|")[3] == "standard_monitor"


def test_cyp2b6_efavirenz_dose_reduction(model):
    # Persona G.H. is on ART; CYP2B6 *6/*6 is a poor metabolizer.
    out = run(model, diplotypes={"CYP2B6": "*6/*6"}, drugs=["efavirenz"])
    assert out["phenotypes"] == ["CYP2B6:Poor Metabolizer"]
    assert "400 or 200 mg/day" in out["recommendations"][0]


def test_clopidogrel_by_indication(model):
    acs = run(model, diplotypes={"CYP2C19": "*1/*2"}, drugs=["clopidogrel"])
    assert acs["recommendations"][0].split("|")[3] == "alternative"
    non_acs = run(model, diplotypes={"CYP2C19": "*1/*2"}, drugs=["clopidogrel"],
                  indications={"clopidogrel": "non_acs_non_pci"})
    assert non_acs["recommendations"] == []


def test_g6pd_from_a_measured_phenotype(model):
    out = run(model, measured_phenotypes={"G6PD": "Deficient"}, drugs=["primaquine"])
    assert out["phenotypes"] == ["G6PD:Deficient"]
    assert out["recommendations"][0].split("|")[3] == "avoid"


def test_unknown_allele_gives_no_phenotype(model):
    assert run(model, diplotypes={"CYP2D6": "*1/*999"})["phenotypes"] == []
