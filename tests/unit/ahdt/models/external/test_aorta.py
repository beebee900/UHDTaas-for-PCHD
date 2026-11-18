import json

import numpy as np
import pytest

from ahdt.models.external import aorta
from ahdt.models.params import load_params, params_path


@pytest.fixture(scope="module")
def geometry():
    return aorta.Geometry(load_params(params_path(aorta.__file__, "aorta")).values)


@pytest.fixture(scope="module")
def reference(geometry):
    return aorta.reference_solution(geometry, 1.0, nx=200)


def test_geometry_follows_the_wave_speed(geometry):
    # Moens-Korteweg: c0 = sqrt(beta sqrt(A0) / (2 rho)).
    c0 = np.sqrt(geometry.beta * np.sqrt(geometry.a0) / (2 * geometry.p["rho"]))
    assert c0 == pytest.approx(geometry.c0)
    assert geometry.compliance_ml_per_mmhg > 0 and geometry.impedance_mmhg_s_per_ml > 0


def test_reference_solution_conserves_the_ejected_volume(geometry, reference):
    x, t, a, _ = reference
    inflow = geometry.a0 * np.trapezoid(geometry.inflow_velocity(t), t)
    assert inflow == pytest.approx(geometry.p["stroke_volume_ml"] * 1e-6, rel=0.02)
    stored = geometry.a0 * np.trapezoid(a[-1], x)
    assert 0 < stored < inflow


def test_wave_speed_of_the_reference_solution(geometry):
    assert aorta.foot_to_foot_speed(geometry) == pytest.approx(geometry.c0, rel=0.10)


def test_pulse_pressure_scales_with_stroke_volume(geometry):
    small = aorta.reference_solution(geometry, 0.7, nx=100)
    large = aorta.reference_solution(geometry, 1.3, nx=100)
    mid = 50
    assert geometry.pressure_mmhg(large[2][:, mid]).max() > geometry.pressure_mmhg(
        small[2][:, mid]).max()


@pytest.fixture(scope="module")
def trained():
    meta_path = aorta.MODEL_DIR / "meta.json"
    if not meta_path.exists():
        pytest.skip("the aorta PINN has not been trained")
    return json.loads(meta_path.read_text())


def test_trained_network_matches_the_finite_difference_solution(geometry, trained):
    model = aorta.load(geometry)
    for s in (0.7, 1.0, 1.3):
        errors = aorta.compare(model, geometry, s)
        assert errors["area_rel_l2"] < 0.08, (s, errors)
        assert errors["velocity_rel_l2"] < 0.08, (s, errors)


def test_aorta_model_reports_pulse_pressure(geometry, trained):
    m = aorta.AortaModel()
    out = m.evaluate(m.parameters(), m.initial_state(m.parameters(), {}), {"stroke_volume": 70.0})
    assert 15 < out["pulse_pressure"] < 45
    assert out["pulse_wave_speed"] == pytest.approx(5.0)
    with pytest.raises(ValueError, match="outside the trained range"):
        m.evaluate(m.parameters(), {}, {"stroke_volume": 300.0})
