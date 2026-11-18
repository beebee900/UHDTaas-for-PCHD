"""Connector base of the AHDT coupling layer (design 04, section 4.8).

`CoupledConnector` is the supplied `Connector` with the WP01 mixins (dead-letter topic,
HLC and `prov_id` stamps), declarative field rules for both directions, enumeration
checks, and request-reply that passes the query to the answering twin.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from ahdt.coupling.mapping import Rule, SourceView, apply_rules
from atra.connection import DeadLetterMixin, ProvenanceStampMixin
from atra.connector_contracts import CONNECTORS
from atra.connectors import Connector, ContractViolation, DataContract, Message, PolicyDenied

log = logging.getLogger("ahdt.coupling")

type QueryFn = Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]


def _label(contract: DataContract) -> str:
    return f"{contract.name} v{contract.version}"


class CoupledConnector(DeadLetterMixin, ProvenanceStampMixin, Connector):
    """A 3.16 connector: rules map twin state to the contract in each direction."""

    SPEC_NAME: ClassVar[str] = ""
    OUT_RULES: ClassVar[tuple[Rule, ...]] = ()
    IN_RULES: ClassVar[tuple[Rule, ...]] = ()
    ENUMS: ClassVar[Mapping[str, frozenset[str]]] = {}

    def __init_subclass__(cls, *, spec: str | None = None, any_source: bool = False,
                          any_target: bool = False, **kwargs: Any) -> None:
        """`spec` names the 3.16 row; its kinds, mode, direction and contracts apply.

        `any_source` or `any_target` leaves that kind open for a connector with several
        rows (one per physiological twin, or two targets).
        """
        super().__init_subclass__(**kwargs)
        if spec is None:
            return
        row = next(s for s in CONNECTORS if s.name == spec)
        cls.SPEC_NAME = spec
        cls.SOURCE_KIND = None if any_source else row.source
        cls.TARGET_KIND = None if any_target else row.target
        cls.MODE, cls.DIRECTION = row.mode, row.direction
        cls.OUT_CONTRACT, cls.IN_CONTRACT = row.out_contract, row.in_contract

    def __init__(self, *args: Any, query_provider: QueryFn | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.query_provider = query_provider

    @classmethod
    def spec_name(cls) -> str:
        return cls.SPEC_NAME or cls.__name__

    def checked(self, contract: DataContract, payload: dict[str, Any]) -> dict[str, Any]:
        errors = [f"{name}={payload[name]!r} not one of {sorted(allowed)}"
                  for name, allowed in self.ENUMS.items()
                  if name in contract.fields and name in payload and payload[name] not in allowed]
        if errors:
            raise ContractViolation(_label(contract), errors)
        return payload

    def map_outbound(self, source_state: Mapping[str, Any]) -> dict[str, Any]:
        assert self.OUT_CONTRACT is not None
        return self.checked(self.OUT_CONTRACT,
                            apply_rules(self.OUT_RULES, self.OUT_CONTRACT, source_state))

    def map_reply(self, target_state: Mapping[str, Any]) -> dict[str, Any]:
        """Target-twin state as an IN_CONTRACT payload (bidirectional connectors)."""
        if self.IN_CONTRACT is None:
            raise RuntimeError(f"{self.name} is unidirectional")
        return self.checked(self.IN_CONTRACT,
                            apply_rules(self.IN_RULES, self.IN_CONTRACT, target_state))

    async def reply(self, update: Mapping[str, Any], *,
                    sim_time: float | None = None) -> Message:
        try:
            return await super().reply(update, sim_time=sim_time)
        except (ContractViolation, PolicyDenied) as exc:
            await self._dead_letter(self.topic("in"), "out", str(exc),
                                    {"source_state": dict(update)})
            raise

    async def reply_from(self, target_state: Mapping[str, Any], *,
                         sim_time: float | None = None) -> Message:
        """Map the target twin's state and send it back to the source twin."""
        try:
            update = self.map_reply(target_state)
        except ContractViolation as exc:
            await self._dead_letter(self.topic("in"), "out", str(exc),
                                    {"source_state": dict(target_state)})
            raise
        return await self.reply(update, sim_time=sim_time)

    async def _on_request(self, raw: bytes) -> None:
        # A refusal while answering is dead-lettered by `publish`; the requester times out.
        try:
            if self.query_provider is None:
                await super()._on_request(raw)
                return
            req = json.loads(raw.decode())
            state = await self.query_provider(req.get("query") or {})
            await self.publish(state, correlation_id=req["correlation_id"])
        except (ContractViolation, PolicyDenied, ValueError, KeyError) as exc:
            log.warning("%s could not answer a request: %s", self.name, exc)


class SuppliedAdapter(CoupledConnector):
    """Feeds a supplied connector's own `map_outbound` with the keys it expects.

    Subclass as `class X(SuppliedAdapter, SuppliedConnector)`. `adapt` turns the twin's
    source state into the supplied input; mapping errors become contract violations, so
    they reach the dead-letter topic like any other refusal.
    """

    def adapt(self, view: SourceView) -> dict[str, Any]:
        return dict(view.context)

    def map_outbound(self, source_state: Mapping[str, Any]) -> dict[str, Any]:
        assert self.OUT_CONTRACT is not None
        adapted = {k: v for k, v in self.adapt(SourceView(source_state)).items()
                   if v is not None}
        try:
            # Resolves past the mixins to the supplied class's mapping.
            payload: dict[str, Any] = super(  # type: ignore[safe-super]
                CoupledConnector, self).map_outbound(adapted)
        except ContractViolation:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractViolation(_label(self.OUT_CONTRACT), [f"mapping: {exc}"]) from exc
        return self.checked(self.OUT_CONTRACT, payload)
