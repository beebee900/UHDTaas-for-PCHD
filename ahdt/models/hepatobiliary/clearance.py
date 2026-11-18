"""Liver drug clearance capacity (inventory item 6).

Hepatic clearance by the well-stirred model, CL_H = Q_H fu CL_int / (Q_H + fu CL_int). The
intrinsic clearance is scaled by a clearance factor that depends on the Child-Pugh class,
scored from bilirubin, albumin, INR, ascites and encephalopathy with the knowledge-base
criteria. The class-specific factors are knowledge-base entries; an unsourced class keeps
the factor 1. The clotting factor synthesis output is an index, the reciprocal of the INR,
read by the haematological coagulation state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import default_kb
from atra import contracts as c
from atra.connectors import DTKind


def child_pugh(u: Mapping[str, Any], criteria: Mapping[str, Any]) -> tuple[int, str] | None:
    needed = ("bilirubin", "albumin", "inr")
    if any(u.get(k) is None for k in needed):
        return None
    b1, b2 = criteria["bilirubin_umol_l"]
    a1, a2 = criteria["albumin_g_l"]
    i1, i2 = criteria["inr"]
    bil, alb, inr = float(u["bilirubin"]), float(u["albumin"]), float(u["inr"])
    score = (1 if bil < b1 else 2 if bil <= b2 else 3)
    score += (1 if alb > a1 else 2 if alb >= a2 else 3)
    score += (1 if inr < i1 else 2 if inr <= i2 else 3)
    score += 1 + criteria["ascites"].index(u.get("ascites", "none"))
    score += 1 + criteria["encephalopathy"].index(u.get("encephalopathy", "none"))
    for name, (lo, hi) in criteria["classes"].items():
        if lo <= score <= hi:
            return score, name
    raise ValueError(f"Child-Pugh score {score} outside the class table")


def well_stirred(q_h: float, fu: float, cl_int: float) -> float:
    return q_h * fu * cl_int / (q_h + fu * cl_int)


class LiverClearanceModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.hepatobiliary.liver_drug_clearance_capacity",
        twin=DTKind.HEPATOBILIARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Hepatic clearance capacity for dose adjustment and PBPK",
        instances=("UBERON:0002107",),
        inputs=(Port("bilirubin", "umol/L", "field:1975-2"), Port("albumin", "g/L", "field:1751-7"),
                Port("inr", "{INR}", "facet:UBERON:0000178/coagulation#inr"),
                Port("fu", "1", "input:drug"), Port("cl_int", "L/min", "input:drug")),
        outputs=(Port("clearance_factor", "1"), Port("child_pugh_score", "1"),
                 Port("child_pugh_class", "{class}"), Port("hepatic_clearance", "L/min"),
                 Port("extraction_ratio", "1"), Port("clotting_factor_synthesis", "1")),
        explainers=("counterfactual.scenario",))
    params_stem = "clearance"


    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        kb = self.kb or default_kb()
        u = {**state, **inputs}
        graded = child_pugh(u, kb.entry("severity.child_pugh").content())
        fractions = kb.resolve("hepatic.clint_fraction_by_child_pugh")
        factor = 1.0
        out: dict[str, Any] = {}
        if graded is not None:
            score, klass = graded
            out.update({"child_pugh_score": float(score), "child_pugh_class": klass})
            if isinstance(fractions.get(klass), int | float):
                factor = float(fractions[klass])
        out["clearance_factor"] = factor
        if u.get("inr") is not None:
            out["clotting_factor_synthesis"] = 1.0 / float(u["inr"])
        if u.get("fu") is not None and u.get("cl_int") is not None:
            cl = well_stirred(p["hepatic_blood_flow"], float(u["fu"]),
                              float(u["cl_int"]) * factor)
            out.update({"hepatic_clearance": cl, "extraction_ratio": cl / p["hepatic_blood_flow"]})
        return out
