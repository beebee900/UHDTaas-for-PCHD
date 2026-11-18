"""IEEE 11073-20601 agents: one association per run, one confirmed fixed scan report per
measurement, then release (message order in `edge.devices.decode.phd`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from atra import units
from edge.devices.decode import phd
from edge.devices.decode.phd import configs
from edge.devices.decode.phd.apdu import AssociationResponse
from edge.devices.sim.base import Simulator, TruthStream, seed_of
from edge.devices.transport import PhdLink

Values = Callable[[Simulator, float], float | Sequence[float]]


class AssociationRefused(RuntimeError):
    pass


def _bp(sim: Simulator, t: float) -> Sequence[float]:
    sbp, dbp = round(sim.measure("sbp", t)), round(sim.measure("dbp", t))
    return [sbp, dbp, round(dbp + (sbp - dbp) / 3)]


def _field(name: str, digits: int, scale: float = 1.0) -> Values:
    return lambda sim, t: round(sim.measure(name, t) * scale, digits)


@dataclass
class PhdAgent(Simulator):
    config: configs.Configuration = configs.BLOOD_PRESSURE
    values: Mapping[int, Values] = field(default_factory=dict)
    """Metric object handle -> value at a time, in the configuration's unit."""
    driver: str = "sbp"
    """The truth field whose sample times are the measurement times."""

    def run(self, link: PhdLink) -> None:
        system_id = seed_of(self.device_id).to_bytes(8, "big")
        reply = self._send(link, phd.association_request(system_id, self.config.config_id))
        if not isinstance(reply, AssociationResponse) or reply.result not in (
                phd.ACCEPTED, phd.ACCEPTED_UNKNOWN_CONFIG):
            raise AssociationRefused(f"{self.device_id}: {reply}")
        invoke = 0
        if reply.result == phd.ACCEPTED_UNKNOWN_CONFIG:
            self._send(link, phd.config_event(invoke, self.config))
            invoke += 1
        for n, t in enumerate(self.schedule(self.driver)):
            report = phd.scan_report(
                self.config, {h: v(self, t) for h, v in self.values.items()},
                self.stream.when(t).replace(tzinfo=None), scan_report_no=n % 65536)
            self._send(link, phd.scan_event(invoke % 65536, report))
            invoke += 1
        self._send(link, phd.ReleaseRequest())

    def _send(self, link: PhdLink, apdu: phd.Apdu) -> phd.Apdu | None:
        reply = link.send(self.device_id, phd.encode(apdu))
        return phd.decode(reply) if reply else None


def _agent(config: configs.Configuration, values: Mapping[int, Values], driver: str
           ) -> Callable[..., PhdAgent]:
    def make(device_id: str, stream: TruthStream,
             noise: Mapping[str, float] | None = None) -> PhdAgent:
        return PhdAgent(device_id, stream, dict(noise or {}), config=config, values=values,
                        driver=driver)
    return make


def _mg_dl(sim: Simulator, t: float) -> float:
    return round(units.convert(sim.measure("glucose", t), "mmol/L", "mg/dL",
                               substance="glucose"))


def _bmi(sim: Simulator, t: float) -> float:
    return round(sim.measure("weight", t) / (sim.stream.at("height", t) / 100) ** 2, 1)


bp_cuff = _agent(configs.BLOOD_PRESSURE, {1: _bp, 2: _field("heart_rate", 0)}, "sbp")
glucometer = _agent(configs.GLUCOMETER, {1: _mg_dl}, "glucose")
"""mmol/L truth sent in the standard configuration's mg/dL."""
scale = _agent(configs.WEIGHING_SCALE_BMI,
               {1: _field("weight", 1), 2: _field("height", 1), 3: _bmi}, "weight")
spirometer = _agent(configs.SPIROMETER, {1: _field("pef", 0), 2: _field("fev1", 2)}, "pef")
