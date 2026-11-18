import pytest

from apdt.services.inputs import MissingInputs, from_resources, to_resources
from evaluation.models.apdt.scenarios import SCENARIOS, Scenario


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.key)
def test_resources_carry_the_scenario_inputs(s: Scenario) -> None:
    patient, obs = from_resources(to_resources(s.patient, s.observations), s.patient.tenant_id)
    for name in ("age_years", "sex", "weight_kg", "pregnancy", "hb_genotype", "tenant_id"):
        assert getattr(patient, name) == getattr(s.patient, name)
    assert patient.conditions == s.patient.conditions
    assert patient.medications == s.patient.medications
    assert obs == s.observations


def test_an_episode_without_age_and_sex_is_refused() -> None:
    with pytest.raises(MissingInputs) as err:
        from_resources([], "fac-a")
    assert err.value.missing == ["age_years", "sex"]
