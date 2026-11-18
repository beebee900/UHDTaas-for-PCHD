"""The ISO/IEEE 11073-10101 (MDC) terms the PHD codecs use.

Each constant is named by its reference id and holds `(partition, term code)`. APDUs carry the
16-bit term code; FHIR and `kb/terminology/mdc.csv` use the context-free code
`partition × 65536 + term code`. Every constant is checked against `mdc.csv`, whose rows were
confirmed on tx.fhir.org.
"""

from __future__ import annotations

from typing import NamedTuple

PART_OBJ = 1
PART_SCADA = 2
PART_DIM = 4


class Nom(NamedTuple):
    partition: int
    term: int

    @property
    def cf(self) -> int:
        """Context-free code."""
        return self.partition << 16 | self.term


# Object classes, attributes and notifications (partition 1).
MDC_MOC_VMO_METRIC_NU = Nom(PART_OBJ, 6)
MDC_ATTR_ID_TYPE = Nom(PART_OBJ, 2351)
MDC_ATTR_TIME_STAMP_ABS = Nom(PART_OBJ, 2448)
MDC_ATTR_UNIT_CODE = Nom(PART_OBJ, 2454)
MDC_ATTR_METRIC_SPEC_SMALL = Nom(PART_OBJ, 2630)
MDC_ATTR_SOURCE_HANDLE_REF = Nom(PART_OBJ, 2631)
MDC_ATTR_NU_VAL_OBS_BASIC = Nom(PART_OBJ, 2636)
MDC_ATTR_ATTRIBUTE_VAL_MAP = Nom(PART_OBJ, 2645)
MDC_ATTR_NU_VAL_OBS_SIMP = Nom(PART_OBJ, 2646)
MDC_ATTR_METRIC_STRUCT_SMALL = Nom(PART_OBJ, 2675)
MDC_ATTR_NU_CMPD_VAL_OBS_BASIC = Nom(PART_OBJ, 2677)
MDC_ATTR_ID_PHYSIO_LIST = Nom(PART_OBJ, 2678)
MDC_NOTI_CONFIG = Nom(PART_OBJ, 3356)
MDC_NOTI_SCAN_REPORT_FIXED = Nom(PART_OBJ, 3357)

# Measured quantities (partition 2).
MDC_PULS_OXIM_PULS_RATE = Nom(PART_SCADA, 18458)
MDC_PULS_RATE_NON_INV = Nom(PART_SCADA, 18474)
MDC_PRESS_BLD_NONINV = Nom(PART_SCADA, 18948)
MDC_PRESS_BLD_NONINV_SYS = Nom(PART_SCADA, 18949)
MDC_PRESS_BLD_NONINV_DIA = Nom(PART_SCADA, 18950)
MDC_PRESS_BLD_NONINV_MEAN = Nom(PART_SCADA, 18951)
MDC_TEMP_BODY = Nom(PART_SCADA, 19292)
MDC_PULS_OXIM_SAT_O2 = Nom(PART_SCADA, 19384)
MDC_FLOW_AWAY_EXP_FORCED_PEAK = Nom(PART_SCADA, 21512)
MDC_VOL_AWAY_EXP_FORCED_1S = Nom(PART_SCADA, 21514)
MDC_CONC_GLU_CAPILLARY_WHOLEBLOOD = Nom(PART_SCADA, 29112)
MDC_MASS_BODY_ACTUAL = Nom(PART_SCADA, 57664)
MDC_LEN_BODY_ACTUAL = Nom(PART_SCADA, 57668)
MDC_RATIO_MASS_BODY_LEN_SQ = Nom(PART_SCADA, 57680)

# Units (partition 4).
MDC_DIM_PERCENT = Nom(PART_DIM, 544)
MDC_DIM_CENTI_M = Nom(PART_DIM, 1297)
MDC_DIM_X_L = Nom(PART_DIM, 1600)
MDC_DIM_KILO_G = Nom(PART_DIM, 1731)
MDC_DIM_KG_PER_M_SQ = Nom(PART_DIM, 1952)
MDC_DIM_MILLI_G_PER_DL = Nom(PART_DIM, 2130)
MDC_DIM_BEAT_PER_MIN = Nom(PART_DIM, 2720)
MDC_DIM_X_L_PER_MIN = Nom(PART_DIM, 3072)
MDC_DIM_KILO_PASCAL = Nom(PART_DIM, 3843)
MDC_DIM_MMHG = Nom(PART_DIM, 3872)
MDC_DIM_MILLI_MOLE_PER_L = Nom(PART_DIM, 4722)

TERMS: dict[str, Nom] = {k: v for k, v in dict(globals()).items()
                         if k.startswith("MDC_") and isinstance(v, Nom)}

UCUM: dict[Nom, str] = {
    MDC_DIM_PERCENT: "%",
    MDC_DIM_CENTI_M: "cm",
    MDC_DIM_X_L: "L",
    MDC_DIM_KILO_G: "kg",
    MDC_DIM_KG_PER_M_SQ: "kg/m2",
    MDC_DIM_MILLI_G_PER_DL: "mg/dL",
    MDC_DIM_BEAT_PER_MIN: "/min",
    MDC_DIM_X_L_PER_MIN: "L/min",
    MDC_DIM_KILO_PASCAL: "kPa",
    MDC_DIM_MMHG: "mm[Hg]",
    MDC_DIM_MILLI_MOLE_PER_L: "mmol/L",
}
"""UCUM code of each MDC unit."""


def term(partition: int, code: int) -> Nom | None:
    """The known term with this partition and term code."""
    found = Nom(partition, code)
    return found if found in TERMS.values() else None


def name_of(nom: Nom) -> str:
    for name, value in TERMS.items():
        if value == nom:
            return name
    raise KeyError(nom)
