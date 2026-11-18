"""Maternal-foetal (inventory item 14), a twin nested in the placenta and foetus state.

- Estimated foetal weight from head circumference, abdominal circumference and femur
  length by the Hadlock (1985) formula.
- Maternal physiology adjustments by gestational age: each adjustment rises linearly to
  its peak relative increase at the peak week and is reported once the knowledge-base
  values are sourced.
- The placental function index is read from the Reproductive twin's placenta facet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import default_kb
from atra import contracts as c
from atra.connectors import DTKind

ADJUSTED = ("cardiac_output", "plasma_volume", "gfr")


def hadlock_efw(hc_cm: float, ac_cm: float, fl_cm: float, p: Params) -> float:
    log10 = (p["c0"] + p["c_hc"] * hc_cm + p["c_ac"] * ac_cm + p["c_fl"] * fl_cm
             + p["c_acfl"] * ac_cm * fl_cm)
    return float(10 ** log10)


class MaternalFoetalModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.maternal_foetal",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Foetal growth and maternal physiological adaptation in pregnancy",
        inputs=(Port("gestation_weeks", "wk",
                     "facet:UBERON:0001987/maternal_foetal#gestation_weeks"),
                Port("placental_function", "1",
                     "facet:UBERON:0001987/maternal_foetal#placental_function"),
                Port("hc", "cm", "field:11984-2"),
                Port("ac", "cm", "field:11979-2"),
                Port("fl", "cm", "field:11963-6")),
        outputs=(Port("efw", "g"), Port("gestation_weeks", "wk"),
                 Port("placental_function", "1"),
                 *(Port(f"{k}_factor", "1") for k in ADJUSTED)),
        validity={"pregnancy": "singleton"})
    params_stem = "maternal_foetal"


    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        u = {**state, **inputs}
        out: dict[str, Any] = {}
        if all(u.get(k) is not None for k in ("hc", "ac", "fl")):
            out["efw"] = hadlock_efw(float(u["hc"]), float(u["ac"]), float(u["fl"]), p)
        for key in ("gestation_weeks", "placental_function"):
            if u.get(key) is not None:
                out[key] = float(u[key])
        weeks = u.get("gestation_weeks")
        adj = (self.kb or default_kb()).resolve("pregnancy.maternal_adjustments")
        if weeks is not None and adj.get("peak_week"):
            ramp = min(float(weeks) / float(adj["peak_week"]), 1.0)
            for key in ADJUSTED:
                if adj.get(key) is not None:
                    out[f"{key}_factor"] = 1.0 + float(adj[key]) * ramp
        return out
