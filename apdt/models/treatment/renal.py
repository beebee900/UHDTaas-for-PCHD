"""eGFR from creatinine with the CKD-EPI 2021 equation and parameters of the AHDT kidney
model (`ahdt.renal_urinary.kidney_and_renal_function`), which the dosing model pins."""

from __future__ import annotations

from functools import lru_cache

from ahdt.models.params import MODELS_DIR, load_params
from ahdt.models.renal_urinary.kidney import ckd_epi_2021


@lru_cache(maxsize=1)
def _params() -> dict[str, float]:
    ps = load_params(MODELS_DIR / "renal_urinary" / "kidney.params.yaml")
    return {name: p.value for name, p in ps.params.items()}


def egfr_ckd_epi(creatinine_umol_l: float, age_years: float, female: bool) -> float:
    return ckd_epi_2021(creatinine_umol_l, age_years, female, _params())
