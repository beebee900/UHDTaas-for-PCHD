from datetime import datetime

from atra import contracts as c
from atra.connectors import DTKind
from atra.ids import new_record_id

HDT = "hdt-0123456789ab"


def observation(code: str, value: float, unit: str, when: datetime,
                dt: DTKind = DTKind.ENDOCRINE) -> c.ObservationRecord:
    return c.ObservationRecord(
        record_id=new_record_id(), hdt_id=HDT, dt=dt, code=c.Code(system="http://loinc.org",
                                                                  code=code),
        value=value, unit=unit, effective_time=when, source="device", consent_tag="care",
        provenance_id="prov-test")
