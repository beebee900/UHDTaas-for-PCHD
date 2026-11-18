"""Coronary, cerebral and peripheral vasculature and the microcirculation (inventory item 1).

Each bed is a three-element Windkessel: a characteristic resistance in series with a
parallel peripheral resistance and compliance, draining to zero venous pressure. Bed
resistances are sized from the reference mean pressure and the bed's share of cardiac
output, and scale with the sympathetic resistance factor and a bed-specific
endothelial factor. The microcirculation perfusion index is the bed flow relative to its
reference flow.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

BEDS = ("coronary", "cerebral", "peripheral")
ML_PER_S = 1000.0 / 60.0


def bed(name: str, p: Params, u: Mapping[str, Any]) -> tuple[float, float, float]:
    """(characteristic resistance, peripheral resistance, compliance) of one bed."""
    total = p["map_ref"] / (p["co_ref"] * ML_PER_S * p[f"share_{name}"])
    factor = float(u.get("resistance_factor", 1.0)) * float(u.get(f"{name}_factor", 1.0))
    rc = total * p["rc_fraction"] * factor
    rp = total * (1 - p["rc_fraction"]) * factor
    return rc, rp, p["tau_bed"] / (total * (1 - p["rc_fraction"]))


class VasculatureModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.cardiovascular.coronary_cerebral_peripheral_vasculature_and_microcirculation",
        twin=DTKind.CARDIOVASCULAR, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Regional blood flow and perfusion from arterial pressure",
        instances=("UBERON:0001637", "UBERON:0001638", "UBERON:0001982"),
        inputs=(Port("map", "mm[Hg]", "model:ahdt.cardiovascular.heart_chambers_and_valves#map"),
                Port("resistance_factor", "1",
                     "model:ahdt.cardiovascular.baroreflex_regulation#resistance_factor"),
                Port("endothelial_function", "1",
                     "model:ahdt.cardiovascular.vascular_endothelium#endothelial_function")),
        outputs=(*(Port(f"{b}_flow", "mL/min") for b in BEDS),
                 Port("resistance", "mm[Hg].s/mL"), Port("compliance", "mL/mm[Hg]"),
                 Port("perfusion_index", "1")),
        explainers=("sensitivity.local",))
    params_stem = "vasculature"
    state_names = tuple(f"P_{b}" for b in BEDS)

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        pressure = float(inputs.get("map", p["map_ref"]))
        out = {}
        for name in BEDS:
            rc, rp, _ = bed(name, p, inputs)
            out[f"P_{name}"] = pressure * rp / (rc + rp)
        return out

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        pressure = float(u.get("map", p["map_ref"]))
        out = []
        for name, p_c in zip(BEDS, y, strict=True):
            rc, rp, comp = bed(name, p, u)
            out.append(((pressure - p_c) / rc - p_c / rp) / comp)
        return out

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        pressure = float(u.get("map", p["map_ref"]))
        flows, total_conductance, total_comp = {}, 0.0, 0.0
        for name, p_c in zip(BEDS, y, strict=True):
            rc, rp, comp = bed(name, p, u)
            flows[f"{name}_flow"] = (pressure - p_c) / rc * 60.0
            total_conductance += 1.0 / (rc + rp)
            total_comp += comp
        reference = sum(p["co_ref"] * 1000.0 * p[f"share_{b}"] for b in BEDS)
        return {**flows, "resistance": 1.0 / total_conductance, "compliance": total_comp,
                "perfusion_index": sum(flows.values()) / reference}
