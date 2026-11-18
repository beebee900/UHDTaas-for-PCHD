"""Autonomy levels granted to agents and lowered by the person (design 03, 3.14; design 07).

Agents hold a level per action class, read from `autonomy.yaml`; without a table every agent
holds the AHDT level of 3.14. The person may lower the level of an action class on their own
twin, never raise it. The effective level is the lower of the two; OPA computes it again from
both inputs, so this module only supplies them.
"""

from __future__ import annotations

from collections.abc import Mapping

from atra.contracts import AutonomyLevel
from edge.actuators.catalogue import table

ORDER = (AutonomyLevel.NEVER, AutonomyLevel.INFORM, AutonomyLevel.RECOMMEND,
         AutonomyLevel.PREPARE_FOR_SIGNATURE, AutonomyLevel.ACT_WITH_APPROVAL, AutonomyLevel.ACT)


def rank(level: AutonomyLevel) -> int:
    return ORDER.index(level)


class AutonomyDenied(PermissionError):
    """An actuator command refused by the autonomy check; `reasons` come from the policy."""

    def __init__(self, command_id: str, reasons: tuple[str, ...]) -> None:
        super().__init__(f"{command_id}: " + "; ".join(reasons))
        self.command_id = command_id
        self.reasons = reasons


class AutonomyTable:
    def __init__(self, grants: Mapping[str, Mapping[str, AutonomyLevel]] | None = None) -> None:
        self.grants = grants
        self._person: dict[tuple[str, str], AutonomyLevel] = {}

    @staticmethod
    def class_level(action_class: str) -> AutonomyLevel:
        return AutonomyLevel(table()["action_classes"][action_class]["level"])

    def granted(self, agent: str, action_class: str) -> AutonomyLevel:
        if self.grants is None:
            return self.class_level(action_class)
        return self.grants.get(agent, {}).get(action_class, AutonomyLevel.NEVER)

    def person_level(self, hdt_id: str, action_class: str) -> AutonomyLevel | None:
        return self._person.get((hdt_id, action_class))

    def lower(self, hdt_id: str, action_class: str, level: AutonomyLevel) -> None:
        current = self.person_level(hdt_id, action_class) or self.class_level(action_class)
        if rank(level) > rank(current):
            raise ValueError(f"the person may lower {action_class} below {current.value}, "
                             f"not raise it to {level.value}")
        self._person[(hdt_id, action_class)] = level
