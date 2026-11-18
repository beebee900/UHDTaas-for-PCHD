"""Policies on every connector (design 03, 3.16; design 07, 7.1.3).

- `PersonConsentPolicy`: the supplied `ConsentPolicy` over the 3.16 consent pairs, plus
  the person's current consent from the `ConsentRegistry`;
- the supplied `RangeGuardPolicy` with the 3.16 safety limits;
- `OPAPolicy` (package `ahdt.connectors`) when an OPA client is given.
"""

from __future__ import annotations

from collections.abc import Mapping

from atra.connector_contracts import CARE, CONNECTORS, RANGE_GUARD, ConnectorSpec, expanded_pairs
from atra.connectors import (
    ConsentPolicy,
    Decision,
    Direction,
    DTKind,
    Message,
    Policy,
    RangeGuardPolicy,
)
from atra.consent import ConsentRegistry
from atra.policy import OPAPolicy, SyncPolicyClient


def spec_of(name: str) -> ConnectorSpec:
    return next(s for s in CONNECTORS if s.name == name)


def purpose_of(spec: ConnectorSpec) -> str:
    """The purpose of use a connector's messages carry."""
    return "care" if spec.purposes >= CARE else min(spec.purposes)


def consent_pairs() -> dict[tuple[DTKind, DTKind], set[str]]:
    """(source, target) -> purposes, for both directions of bidirectional connectors."""
    pairs: dict[tuple[DTKind, DTKind], set[str]] = {}
    for name, source, target in expanded_pairs():
        spec = spec_of(name)
        pairs.setdefault((source, target), set()).update(spec.purposes)
        if spec.direction is Direction.BIDIRECTIONAL:
            pairs.setdefault((target, source), set()).update(spec.purposes)
    return pairs


class PersonConsentPolicy(ConsentPolicy):
    """Consent pairs of 3.16 and the person's consent to the message's purpose."""

    def __init__(self, hdt_id: str, consents: ConsentRegistry,
                 pairs: Mapping[tuple[DTKind, DTKind], set[str]] | None = None) -> None:
        super().__init__(pairs if pairs is not None else consent_pairs())
        self.hdt_id = hdt_id
        self.registry = consents

    def evaluate(self, message: Message, direction: str) -> Decision:
        pair = super().evaluate(message, direction)
        if not pair.allowed:
            return pair
        consent = self.registry.get(self.hdt_id)
        if consent is None or message.purpose not in consent.purposes:
            return Decision(False, f"the person has not consented to purpose "
                                   f"'{message.purpose}'", self.name)
        return pair


def connector_policies(hdt_id: str, consents: ConsentRegistry,
                       opa: SyncPolicyClient | None = None) -> list[Policy]:
    policies: list[Policy] = [PersonConsentPolicy(hdt_id, consents),
                              RangeGuardPolicy(RANGE_GUARD)]
    if opa is not None:
        policies.append(OPAPolicy(opa))
    return policies
