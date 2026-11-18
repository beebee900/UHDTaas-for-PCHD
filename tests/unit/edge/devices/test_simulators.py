"""Acceptance for WP10: every device class streams a persona's truth over its wire format,
through the edge gateway and the WP12 pipeline, into the Layer 3 stores with the right codes,
UCUM units and values within the wire format's resolution."""

import asyncio
import gzip
import io
from datetime import UTC, datetime

import numpy as np
import pydicom
import pytest
from sqlalchemy import select

from ahdt.devices.sink import EdgeSink
from ahdt.ingest import build_pipeline
from ahdt.ingest.fields import field_index
from ahdt.models.catalogue import default_catalogue
from ahdt.stores import tables
from atra import units
from atra.backends import Backends
from atra.config import Settings
from atra.consent import demo_registry
from atra.provenance import AuditLog
from edge.devices.gateway import DeviceGateway
from edge.devices.sim import ble, clinical, environment, mqtt, phd, phone
from edge.devices.transport import coap
from synth import imaging
from synth.streams import persona_stream

LOINC = "http://loinc.org"
FIELD = "urn:atra:field"
MDC = "urn:iso:std:iso:11073:10101"


@pytest.fixture(scope="module")
def streams():
    models = default_catalogue()

    async def build():
        out = {k: await persona_stream(k, models, hours=3) for k in ("de", "ef")}
        out["ao"] = await persona_stream("ao", models, hours=36, step_s=43200)
        return out

    return asyncio.run(build())


class Rig:
    def __init__(self, backends, pipeline):
        self.backends, self.pipeline = backends, pipeline
        index = field_index()

        def twin_of(code):
            ref = index.resolve(code)
            return ref.twin.value if ref else None

        self.gateway = DeviceGateway(backends.events, EdgeSink(pipeline), twin_of=twin_of,
                                     clock=lambda: datetime(2026, 10, 10, 12, tzinfo=UTC))
        self.t = self.gateway.transports

    async def ingest(self):
        result = await self.gateway.flush()
        await self.backends.events.bus.aclose(timeout=300)
        return result

    def records(self, device_id=None):
        out = []
        for e in self.backends.events.published:
            if e.event_type != "observation.ingested":
                continue
            out.append(e.payload)
        rows = {r["record_id"]: r for r in self.pipeline.lake.arrow("observations").to_pylist()}
        return [{**p, "device_id": rows[p["record_id"]]["device_id"],
                 "system": rows[p["record_id"]]["code_system"]} for p in out
                if device_id is None or rows[p["record_id"]]["device_id"] == device_id]

    def values(self, code, device_id=None):
        return [r["value"] for r in self.records(device_id) if r["code"] == code]

    async def rejected(self):
        async with self.backends.relational.engine().begin() as conn:
            return {r.record_id: r.reason for r in await conn.execute(select(tables.rejected))}


@pytest.fixture
async def rig(tmp_path):
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    pipeline.subscribe()
    yield Rig(backends, pipeline)
    await backends.close()


def truth(stream, name):
    return stream.at(name, 0.0)


async def test_ble_vitals_arrive_with_codes_and_units(rig, streams):
    de = streams["de"]
    for device_id, cls, sim in (("watch-1", "smartwatch", ble.Smartwatch),
                                ("cuff-1", "bp_cuff", ble.BpCuff),
                                ("gluc-1", "glucometer", ble.Glucometer),
                                ("oxi-1", "pulse_oximeter", ble.PulseOximeter),
                                ("scale-1", "smart_scale", ble.Scale),
                                ("therm-1", "thermometer", ble.Thermometer)):
        rig.gateway.register(device_id, de.hdt_id, cls)
        sim(device_id, de).run(rig.t.ble)
    await rig.ingest()
    assert not rig.gateway.dead_letters and not await rig.rejected()
    n = len(de.times("heart_rate"))
    assert rig.values("8867-4", "watch-1") == [round(truth(de, "heart_rate"))] * n
    assert all(v > 0 for v in rig.values("hrv_rmssd", "watch-1"))
    assert rig.values("8480-6", "cuff-1") == [round(truth(de, "sbp"))] * n
    assert rig.values("8462-4", "cuff-1") == [round(truth(de, "dbp"))] * n
    assert rig.values("8478-0", "cuff-1")
    assert rig.values("15074-8", "gluc-1") == pytest.approx(
        [truth(de, "glucose")] * n, abs=0.05)
    assert rig.values("59408-5", "oxi-1") == [round(truth(de, "spo2"))] * n
    assert rig.values("29463-7", "scale-1") == pytest.approx([truth(de, "weight")] * n,
                                                             abs=0.005)
    assert rig.values("8302-2", "scale-1") == pytest.approx([truth(de, "height")] * n,
                                                            abs=0.1)
    assert rig.values("39156-5", "scale-1") == pytest.approx(
        [truth(de, "weight") / (truth(de, "height") / 100) ** 2] * n, abs=0.1)
    assert rig.values("8310-5", "therm-1") == pytest.approx([truth(de, "temperature")] * n,
                                                            abs=0.05)
    units_by_code = {r["code"]: r["unit"] for r in rig.records()}
    assert units_by_code["8867-4"] == "/min" and units_by_code["8480-6"] == "mm[Hg]"
    assert units_by_code["15074-8"] == "mmol/L" and units_by_code["8302-2"] == "cm"
    stored = await rig.backends.timeseries.query(de.hdt_id, "8480-6")
    assert len(stored) == n
    fhir = await rig.backends.fhir.search("Observation", {"code": "8480-6"}, partition="ahdt")
    coding = fhir[0]["code"]["coding"]
    assert {"system": MDC, "code": "MDC_PRESS_BLD_NONINV_SYS"} in [
        {"system": c["system"], "code": c["code"]} for c in coding]


async def test_phd_agents_associate_and_report(rig, streams):
    de = streams["de"]
    for device_id, make in (("cuff-2", phd.bp_cuff), ("gluc-2", phd.glucometer),
                            ("scale-2", phd.scale), ("spiro-1", phd.spirometer)):
        rig.gateway.register(device_id, de.hdt_id, "phd")
        make(device_id, de).run(rig.t.phd)
    await rig.ingest()
    assert not rig.gateway.dead_letters and not await rig.rejected()
    n = len(de.times("sbp"))
    assert rig.values("8480-6", "cuff-2") == [round(truth(de, "sbp"))] * n
    mg = round(units.convert(truth(de, "glucose"), "mmol/L", "mg/dL", substance="glucose"))
    assert rig.values("15074-8", "gluc-2") == pytest.approx(
        [units.convert(mg, "mg/dL", "mmol/L", substance="glucose")] * n, rel=1e-6)
    assert rig.values("19935-6", "spiro-1") == [round(truth(de, "pef"))] * n
    assert rig.values("20150-9", "spiro-1") == pytest.approx([truth(de, "fev1")] * n,
                                                             abs=0.005)
    assert rig.values("39156-5", "scale-2")
    extended = [f for f in rig.t.phd.frames if f[0] == "manager" and f[1][:2] == b"\xe3\x00"]
    assert len(extended) == 4
    assert {r["unit"] for r in rig.records("spiro-1")} == {"L/min", "L"}


async def test_mqtt_streams_and_waveforms(rig, streams):
    de = streams["de"]
    for device_id, cls, sim in (("patch-1", "ecg_patch", mqtt.EcgPatch),
                                ("imu-1", "imu", mqtt.Imu),
                                ("sole-1", "pressure_insoles", mqtt.Insoles),
                                ("pump-1", "insulin_pump", mqtt.InsulinPump),
                                ("dht-1", "environmental", mqtt.Dht22),
                                ("phone-1", "phone", mqtt.PhoneSensors)):
        rig.gateway.register(device_id, de.hdt_id, cls)
        sim(device_id, de).run(rig.t.mqtt)
    await rig.ingest()
    assert not rig.gateway.dead_letters and not await rig.rejected()
    segments = rig.pipeline.waveforms.read(de.hdt_id, "MDC_ECG_ELEC_POTL_II", de.start)
    assert len(segments) == len(de.times("heart_rate"))
    assert segments[0].period_ms == 4.0 and segments[0].samples.max() == pytest.approx(
        1.2, abs=0.02)
    cadence = truth(de, "cadence")
    assert rig.values("cadence", "imu-1") == pytest.approx([cadence] * 4, abs=1.0)
    assert rig.values("cadence", "sole-1") == pytest.approx([cadence] * 4, abs=2.0)
    assert sum(rig.values("insulin_delivered", "pump-1")) == pytest.approx(
        sum(v for _, v in de.series["insulin_delivered"]), abs=0.01)
    assert rig.values("ambient_temp", "dht-1") == pytest.approx([28.0] * 4)
    assert rig.values("humidity", "dht-1") == pytest.approx([70.0] * 4)
    assert rig.values("active_minutes", "phone-1") == [round(truth(de, "active_minutes"))] * 4
    assert all(r["system"] == FIELD for r in rig.records("pump-1"))


async def test_environment_over_coap_and_chirpstack(rig, streams):
    de = streams["de"]
    rig.gateway.register("nb-1", de.hdt_id, "environmental")
    rig.gateway.register("a84041000181c3f1", de.hdt_id, "environmental")
    codes = environment.CoapAirSensor("nb-1", de).run(rig.t.coap)
    environment.LoraAirSensor("a84041000181c3f1", de).run(rig.t.mqtt)
    assert set(codes) == {coap.CHANGED}
    await rig.ingest()
    pm = truth(de, "pm25")
    assert rig.values("pm25", "nb-1") == pytest.approx([pm] * 4, abs=0.05)
    assert rig.values("pm25", "a84041000181c3f1") == pytest.approx([pm] * 4, abs=0.05)
    assert rig.values("humidity", "a84041000181c3f1") == pytest.approx([70.0] * 4, abs=0.25)
    assert {r["unit"] for r in rig.records("nb-1")} == {"ug/m3", "Cel", "%"}


async def test_clinical_documents(rig, streams):
    de, ef = streams["de"], streams["ef"]
    rig.gateway.register("lab-1", de.hdt_id, "lab_analyser")
    rig.gateway.register("ecg-1", de.hdt_id, "ecg_machine")
    rig.gateway.register("cr-1", ef.hdt_id, "imaging")
    rig.gateway.register("seq-1", ef.hdt_id, "genomics")
    rig.gateway.register("omrs-1", ef.hdt_id, "records")
    oru = clinical.LabAnalyser("lab-1", de).messages()
    rig.gateway.submit("hl7v2", oru.encode(), device_id="lab-1")
    header, data = clinical.EcgMachine("ecg-1", de).record(0.0)
    rig.gateway.submit_wfdb(header, data, device_id="ecg-1")
    pixels = np.tile(np.arange(64, dtype=np.uint8) * 4, (64, 1))
    dicom = imaging.wrap(pixels, hdt_id=ef.hdt_id, label="synthetic gradient",
                         when=ef.start, source="synthetic")
    body, content_type = clinical.ImagingModality("cr-1", ef).stow([dicom])
    rig.gateway.submit("stow", body, device_id="cr-1", content_type=content_type)
    rig.gateway.submit("vcf", clinical.Sequencer("seq-1", ef).vcf(ef.start), device_id="seq-1")
    rig.gateway.submit("fhir", clinical.RecordsExport("omrs-1", ef).bundle(), device_id="omrs-1")
    result = await rig.ingest()
    assert not rig.gateway.dead_letters
    lab, dcm, vcf, records = result.uploads
    assert lab.counts()["accepted"] == 2 and records.counts()["accepted"] == 2
    creat = await rig.backends.timeseries.latest(de.hdt_id, "14682-9")
    assert creat.v == pytest.approx(truth_lab(de, "14682-9"), abs=0.05) and creat.unit == \
        "umol/L"
    assert (await rig.backends.timeseries.latest(ef.hdt_id, "718-7")).unit == "g/dL"
    segment = rig.pipeline.waveforms.read(de.hdt_id, "MDC_ECG_ELEC_POTL_II", de.start)[0]
    assert segment.period_ms == 2.0 and len(segment.samples) == 5000
    stored = await rig.backends.objects.get(dcm.key)
    assert pydicom.dcmread(io.BytesIO(stored)).PatientID == ef.hdt_id
    text = gzip.decompress(await rig.backends.objects.get(vcf.key)).decode()
    assert "rs334\tT\tA\t.\tPASS\t.\tGT\t1/1" in text and vcf.hdt_id == ef.hdt_id


def truth_lab(stream, loinc):
    return next(r["value"] for p in stream.documents["labs"] for r in p["results"]
                if r["loinc"] == loinc)


async def test_phone_media_and_self_report(rig, streams):
    de = streams["de"]
    rig.gateway.register("phone-2", de.hdt_id, "phone")
    mic, cam = phone.Microphone("phone-2", de), phone.Camera("phone-2", de)
    rig.gateway.submit("audio", mic.clip(0.0), device_id="phone-2")
    rig.gateway.submit("photo", cam.photo(), device_id="phone-2", content_type="image/png")
    rig.gateway.submit("usage", phone.UsageLog("phone-2", de).day(0.0), device_id="phone-2")
    report = phone.SelfReport("phone-2", de)
    rig.gateway.submit("questionnaire_response", report.questionnaire_response("phq9", de.start),
                       device_id="phone-2")
    rig.gateway.submit("odk", report.odk("gad7"), device_id="phone-2")
    result = await rig.ingest()
    assert not rig.gateway.dead_letters and not await rig.rejected()
    assert rig.values("cough_events") == pytest.approx([truth(de, "cough_events")], abs=12.0)
    assert rig.values("screen_time") == pytest.approx([truth(de, "screen_time")], abs=0.01)
    answers = de.documents["questionnaires"]
    assert rig.values("44261-6") == [sum(int(v) for v in answers["phq9"].values())]
    assert rig.values("70274-6") == [sum(int(v) for v in answers["gad7"].values())]
    assert {r["unit"] for r in rig.records() if r["code"] == "44261-6"} == {"{score}"}
    keys = [u.key for u in result.uploads]
    assert any(k.endswith(".png") for k in keys) and any(k.endswith(".wav") for k in keys)


async def test_fever_follows_the_malaria_truth(rig, streams):
    ao = streams["ao"]
    rig.gateway.register("therm-ao", ao.hdt_id, "thermometer")
    ble.Thermometer("therm-ao", ao).run(rig.t.ble)
    await rig.ingest()
    temps = rig.values("8310-5", "therm-ao")
    assert temps == pytest.approx([round(v, 1) for _, v in ao.series["temperature"]], abs=0.05)
    assert max(temps) > 38.0


async def test_rejected_consentless_and_undecodable_records(rig, streams):
    de = streams["de"]
    rig.gateway.register("therm-x", de.hdt_id, "thermometer")
    rig.gateway.register("lab-x", de.hdt_id, "lab_analyser")
    from edge.devices.decode.gatt import DateTime, temperature

    hot = temperature.TemperatureMeasurement(55.0, time_stamp=DateTime.of(de.start))
    rig.t.ble.notify("therm-x", temperature.UUID, temperature.encode(hot), de.start)
    rig.t.ble.notify("therm-x", temperature.UUID, b"\x00\x01", de.start)
    rig.t.ble.notify("ghost", temperature.UUID, temperature.encode(hot), de.start)
    oru = clinical.LabAnalyser("lab-x", de, patient=("NIN-00000000001", "NIMC")).messages()
    rig.gateway.submit("hl7v2", oru.encode(), device_id="lab-x")
    result = await rig.ingest()
    assert [r["code"] for r in rig.records()] == []
    assert "plausibility" in next(iter((await rig.rejected()).values()))
    assert len(rig.gateway.dead_letters) == 2
    assert result.uploads[0].dropped and not result.uploads[0].accepted
    drops = rig.pipeline.audit.query(action="ingest.drop")
    assert {d.reason for d in drops} == {"no consent for care"}
