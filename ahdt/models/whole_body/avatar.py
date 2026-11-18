"""Anatomical avatar (inventory item 14): anthropometric scaling of the humanoid mesh.

The viewer's parametric glTF humanoid is scaled on three axes. Height sets the vertical
scale and waist the depth scale; the lateral scale takes up the rest of the body volume,
which is taken as proportional to weight. Body surface area follows Mosteller (1987).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


class AvatarModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.anatomical_avatar",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Scale factors of the 3-D body viewer and body size indices",
        inputs=(Port("height", "cm", "field:8302-2"), Port("weight", "kg", "field:29463-7"),
                Port("waist", "cm", "field:8280-0")),
        outputs=(Port("scale_vertical", "1"), Port("scale_lateral", "1"),
                 Port("scale_depth", "1"), Port("bmi", "kg/m2"), Port("bsa", "m2")))
    params_stem = "avatar"

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        u = {**state, **inputs}
        h = float(u.get("height", p["mesh_height"]))
        w = float(u.get("weight", p["mesh_weight"]))
        waist = float(u.get("waist", p["mesh_waist"]))
        vertical = h / p["mesh_height"]
        depth = waist / p["mesh_waist"]
        return {"scale_vertical": vertical, "scale_depth": depth,
                "scale_lateral": w / p["mesh_weight"] / (vertical * depth),
                "bmi": w / (h / 100.0) ** 2, "bsa": math.sqrt(h * w / 3600.0)}
