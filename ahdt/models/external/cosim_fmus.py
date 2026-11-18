"""FMI 2.0 co-simulation slaves of the cardiovascular, respiratory and renal models.

Each slave wraps a WP14a Layer 4 model with pythonfmu. Inputs and outputs are the coupled
connector variables: the cardiovascular slave outputs `cardiac_output` (L/min), which the
respiratory and renal slaves read. The slaves are built into FMUs by `cosim.build_fmus`.
"""

from __future__ import annotations

import numpy as np
from pythonfmu import Fmi2Causality, Fmi2Slave, Fmi2Variability, Real

CAUSALITY_IN = Fmi2Causality.input
CAUSALITY_OUT = Fmi2Causality.output
CONTINUOUS = Fmi2Variability.continuous


def _real(slave: Fmi2Slave, name: str, causality: Fmi2Causality, start: float | None = None,
          description: str = "") -> None:
    slave.register_variable(Real(name, causality=causality, variability=CONTINUOUS,
                                 start=start, description=description))


class CardiovascularSlave(Fmi2Slave):
    """Heart model: beat-averaged haemodynamics at the commanded heart rate."""

    author = "ATRA"
    description = "Cardiovascular model (ahdt.cardiovascular.heart_chambers_and_valves)"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        from ahdt.models.cardiovascular.heart import HeartModel

        self.model = HeartModel()
        self.p = self.model.parameters()
        self.state = self.model.initial_state(self.p, {})
        self.cache: dict[float, dict[str, float]] = {}
        self.heart_rate = 70.0
        self.cardiac_output = 0.0
        self.map = 0.0
        self.sbp = 0.0
        self.dbp = 0.0
        _real(self, "heart_rate", CAUSALITY_IN, 70.0, "beats per minute")
        _real(self, "cardiac_output", CAUSALITY_OUT, description="L/min")
        _real(self, "map", CAUSALITY_OUT, description="mm[Hg]")
        _real(self, "sbp", CAUSALITY_OUT, description="mm[Hg]")
        _real(self, "dbp", CAUSALITY_OUT, description="mm[Hg]")
        self.refresh()

    def refresh(self) -> None:
        key = round(self.heart_rate, 3)
        if key not in self.cache:
            self.cache[key] = self.model.evaluate(self.p, self.state, {"heart_rate": key})
        values = self.cache[key]
        self.cardiac_output = float(values["cardiac_output"])
        self.map, self.sbp, self.dbp = (float(values[k]) for k in ("map", "sbp", "dbp"))

    def exit_initialization_mode(self) -> None:
        self.refresh()

    def do_step(self, current_time: float, step_size: float) -> bool:
        self.refresh()
        return True


class RespiratorySlave(Fmi2Slave):
    """Ventilation control with gas exchange; perfusion comes from the cardiac output."""

    author = "ATRA"
    description = "Respiratory model (ahdt.respiratory.ventilation_control)"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        from ahdt.models.respiratory.ventilation import VentilationControlModel

        self.model = VentilationControlModel()
        self.p = self.model.parameters()
        self.fio2 = 0.21
        self.cardiac_output = 5.0
        initial = self.model.initial_state(self.p, {"fio2": self.fio2,
                                                    "cardiac_output": self.cardiac_output})
        self.y = np.array([initial[n] for n in self.model.state_names])
        self.minute_ventilation = 0.0
        self.paco2 = 0.0
        self.pao2 = 0.0
        _real(self, "fio2", CAUSALITY_IN, 0.21, "inspired oxygen fraction")
        _real(self, "cardiac_output", CAUSALITY_IN, 5.0, "L/min")
        _real(self, "minute_ventilation", CAUSALITY_OUT, description="L/min")
        _real(self, "paco2", CAUSALITY_OUT, description="mm[Hg]")
        _real(self, "pao2", CAUSALITY_OUT, description="mm[Hg]")
        self.observe()

    def inputs(self) -> dict[str, float]:
        return {"fio2": self.fio2, "cardiac_output": self.cardiac_output}

    def observe(self) -> None:
        out = self.model.observe(0.0, self.y, self.p, self.inputs())
        self.minute_ventilation = float(out["minute_ventilation"])
        self.paco2, self.pao2 = float(out["paco2"]), float(out["pao2"])

    def exit_initialization_mode(self) -> None:
        self.observe()

    def do_step(self, current_time: float, step_size: float) -> bool:
        u = self.inputs()
        ys = self.model.integrate(self.p, self.y, np.array([0.0, step_size]), lambda t: u)
        self.y = np.asarray(ys[-1])
        self.observe()
        return True


class RenalSlave(Fmi2Slave):
    """Kidney model: creatinine and filtration at the delivered cardiac output."""

    author = "ATRA"
    description = "Renal model (ahdt.renal_urinary.kidney_and_renal_function)"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        from ahdt.models.renal_urinary.kidney import KidneyModel

        self.model = KidneyModel()
        self.p = self.model.parameters()
        self.cardiac_output = 5.0
        initial = self.model.initial_state(self.p, {})
        self.y = np.array([initial[n] for n in self.model.state_names])
        self.creatinine = 0.0
        self.egfr = 0.0
        self.filtration_fraction = 0.0
        _real(self, "cardiac_output", CAUSALITY_IN, 5.0, "L/min")
        _real(self, "creatinine", CAUSALITY_OUT, description="umol/L")
        _real(self, "egfr", CAUSALITY_OUT, description="mL/min/1.73 m2")
        _real(self, "filtration_fraction", CAUSALITY_OUT, description="1")
        self.observe()

    def observe(self) -> None:
        out = self.model.observe(0.0, self.y, self.p, {"cardiac_output": self.cardiac_output})
        self.creatinine, self.egfr = float(out["creatinine"]), float(out["egfr"])
        self.filtration_fraction = float(out["filtration_fraction"])

    def exit_initialization_mode(self) -> None:
        self.observe()

    def do_step(self, current_time: float, step_size: float) -> bool:
        u = {"cardiac_output": self.cardiac_output}
        scale = self.model.time_scale_s
        ys = self.model.integrate(self.p, self.y, np.array([0.0, step_size / scale]),
                                  lambda t: u)
        self.y = np.asarray(ys[-1])
        self.observe()
        return True
