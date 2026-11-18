import numpy as np
import pytest

from ahdt.models.external import backends, cosim

pytestmark = pytest.mark.skipif(
    not (backends.pythonfmu().available and backends.fmpy().available),
    reason="pythonfmu and FMPy are required")

STOP_S = 1800.0
STEP_S = 60.0
TOLERANCE = 0.02


@pytest.fixture(scope="module")
def fmus(tmp_path_factory):
    return cosim.build_fmus(tmp_path_factory.mktemp("fmus"))


def ramp(t):
    return 70.0 + 20.0 * min(t / STOP_S, 1.0)


DRIVES = {("Cardiovascular", "heart_rate"): ramp, ("Respiratory", "fio2"): lambda t: 0.21}


def test_fmus_expose_the_coupled_variables(fmus):
    from fmpy import read_model_description

    names = {n: {v.name: v.causality for v in read_model_description(str(p)).modelVariables}
             for n, p in fmus.items()}
    assert names["Cardiovascular"]["cardiac_output"] == "output"
    assert names["Respiratory"]["cardiac_output"] == "input"
    assert names["Renal"]["cardiac_output"] == "input"


def test_coupled_variables_are_conserved_against_the_uncoupled_reference(fmus):
    co = cosim.run_cosimulation(fmus, DRIVES, STOP_S, STEP_S)
    ref = cosim.run_reference(DRIVES, STOP_S, STEP_S)
    produced = co.values["Cardiovascular.cardiac_output"]
    for consumer in ("Respiratory.cardiac_output", "Renal.cardiac_output"):
        delivered = co.values[consumer]
        # The master hands each FMU the output of the previous communication point.
        assert np.allclose(delivered[1:], produced[:-1], rtol=1e-9)
        assert np.allclose(delivered, ref.values[consumer], rtol=TOLERANCE)
    for name in ("Respiratory.minute_ventilation", "Respiratory.paco2", "Respiratory.pao2",
                 "Renal.egfr", "Renal.creatinine", "Cardiovascular.map"):
        assert np.allclose(co.values[name], ref.values[name], rtol=TOLERANCE), name


def test_cosimulation_responds_to_the_drive(fmus):
    co = cosim.run_cosimulation(fmus, DRIVES, STOP_S, STEP_S)
    assert co.values["Cardiovascular.heart_rate"][-1] > co.values["Cardiovascular.heart_rate"][0]
    assert co.values["Cardiovascular.cardiac_output"][-1] != pytest.approx(
        co.values["Cardiovascular.cardiac_output"][0], rel=1e-4)
