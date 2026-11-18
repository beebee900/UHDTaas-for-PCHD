"""Population PK with PyMC on a test model entry."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from apdt.models.treatment import popk

# Test-only parameters; they do not describe any real drug.
ENTRY: dict[str, Any] = {
    "drug": "testdrug", "typical": {"cl_l_h": 10.0, "v_l": 100.0, "ka_per_h": 1.0, "f": 1.0},
    "omega": {"cl": 0.3, "v": 0.2}, "sigma_prop": 0.05,
    "weight": {"reference_kg": 70.0, "exponent_cl": 0.75, "exponent_v": 1.0}}


def test_no_entry_means_no_model() -> None:
    assert popk.popk_entry("artemether") is None


def test_concentration_curve() -> None:
    t = np.array([0.0, 2.0, 24.0])
    c = popk.concentration(t, 500.0, 10.0, 100.0, 1.0, 1.0)
    assert c[0] == pytest.approx(0.0) and c[1] > c[2] > 0
    assert np.trapezoid(popk.concentration(np.linspace(0, 400, 4000), 500.0, 10.0, 100.0, 1.0,
                                           1.0), np.linspace(0, 400, 4000)
                        ) == pytest.approx(500.0 / 10.0, rel=0.01)


def test_individual_clearance_is_recovered() -> None:
    cl_true, v_true = 10.0 * np.exp(0.4), 100.0
    times = np.array([1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    rng = np.random.default_rng(3)
    conc = popk.concentration(times, 500.0, cl_true, v_true, 1.0, 1.0) * np.exp(
        rng.normal(0, 0.05, times.size))
    est = popk.individual_pk(ENTRY, 500.0, 70.0, list(zip(times, conc, strict=True)),
                             draws=200, tune=200)
    assert est.cl_interval[0] <= cl_true <= est.cl_interval[1]
    assert abs(est.cl_l_h - cl_true) / cl_true < 0.2
    assert est.cl_l_h > est.typical_cl
    assert est.auc_mg_h_l == pytest.approx(500.0 / cl_true, rel=0.2)
