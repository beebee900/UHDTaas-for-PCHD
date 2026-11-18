"""Life course and ageing (inventory item 14).

The frailty index q (proportion of deficits present) grows log-linearly with age,
ln q = c0 + k t (Mitnitski et al. 2002). The person's biological age is the age at which
the population curve reaches their observed index. The mortality hazard follows a
Gompertz law whose population parameters are knowledge-base entries; it is reported only
once they are sourced.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import default_kb
from atra import contracts as c
from atra.connectors import DTKind


class LifeCourseModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.life_course_and_ageing",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Frailty trajectory, biological age and mortality hazard",
        inputs=(Port("age", "a", "input:demographics"),
                Port("frailty_index", "1", "input:assessment")),
        outputs=(Port("expected_frailty_index", "1"), Port("biological_age", "a"),
                 Port("mortality_hazard", "/a")),
        validity={"age_years": [65, 100], "population": "community-dwelling older adults"},
        explainers=("counterfactual.scenario",))
    params_stem = "life_course"


    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        u = {**state, **inputs}
        out: dict[str, Any] = {}
        age = u.get("age")
        if age is not None:
            out["expected_frailty_index"] = math.exp(p["ln_q_intercept"] + p["ln_q_slope"]
                                                     * float(age))
        q = u.get("frailty_index")
        if q is not None and float(q) > 0:
            out["biological_age"] = (math.log(float(q)) - p["ln_q_intercept"]) / p["ln_q_slope"]
        gompertz = (self.kb or default_kb()).resolve("lifecourse.gompertz")
        a, b = gompertz.get("a_per_year"), gompertz.get("b_per_year")
        reference_age = out.get("biological_age", age)
        if a is not None and b is not None and reference_age is not None:
            out["mortality_hazard"] = float(a) * math.exp(float(b) * float(reference_age))
        return out
