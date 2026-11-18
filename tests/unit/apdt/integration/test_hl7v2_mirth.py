"""HL7 v2 → FHIR on the p0 path (python-hl7) and the Mirth path (channel JavaScript run in
Node), and the Mirth channel exports (WP20 acceptance 1)."""

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from fhir.resources.R4B import get_fhir_model_class

from apdt.integration import hl7v2
from apdt.integration.mirth import build
from tests.unit.apdt.integration.fixtures import (
    ADT_A01,
    ADT_A03,
    HDT,
    POTASSIUM_ORU,
    RDE_O11,
    RDT_ORU,
)

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node.js runs the Mirth channel script")
STEP = "com.mirth.connect.plugins.javascriptstep.JavaScriptStep"


def run_step(script: str, raw: str) -> dict:
    """Runs a channel transformer step with the Mirth variables it uses."""
    harness = (
        "var store = {};\n"
        "var channelMap = {put: function (k, v) { store[k] = v; }};\n"
        f"var connectorMessage = {{getRawData: function () {{ return {json.dumps(raw)}; }}}};\n"
        f"{script}\n"
        "process.stdout.write(store['fhirBundle']);\n")
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, check=True,
                         timeout=60)
    return json.loads(out.stdout)


def normalised(resource: dict) -> dict:
    model = get_fhir_model_class(resource["resourceType"])
    return model.model_validate(resource).model_dump(mode="json", exclude_none=True)


def channel_script(name: str) -> str:
    root = ET.parse(build.OUT / name).getroot()
    return root.find(f"sourceConnector/transformer/elements/{STEP}/script").text


def test_rdt_oru_maps_to_diagnostic_report():
    m = hl7v2.map_message(RDT_ORU)
    assert m.message_type == "ORU^R01" and m.patient[1] == HDT
    obs, report = m.resources
    assert report["resourceType"] == "DiagnosticReport" and report["status"] == "final"
    assert report["code"]["coding"][0] == {
        "system": "http://loinc.org", "code": "76772-3",
        "display": "Plasmodium falciparum Ag [Presence] in Blood by Rapid immunoassay"}
    assert report["result"] == [{"reference": f"Observation/{obs['id']}"}]
    assert report["basedOn"][0]["identifier"] == {"system": hl7v2.PLACER_SYSTEM,
                                                  "value": "SR-0001"}
    assert report["effectiveDateTime"] == "2026-10-01T10:30:00Z"
    assert obs["valueCodeableConcept"]["coding"][0]["code"] == "10828004"
    assert obs["interpretation"][0]["coding"][0]["code"] == "A"
    assert obs["status"] == "final" and obs["effectiveDateTime"] == "2026-10-01T10:45:00Z"


def test_adt_and_rde_map_to_encounter_and_medication_request():
    admit = hl7v2.map_message(ADT_A01).resources[0]
    discharge = hl7v2.map_message(ADT_A03).resources[0]
    assert admit["resourceType"] == "Encounter" and admit["status"] == "in-progress"
    assert admit["class"]["code"] == "IMP" and admit["id"] == discharge["id"]
    assert discharge["status"] == "finished"
    assert discharge["period"]["end"] == "2026-10-05T12:00:00Z"
    mr = hl7v2.map_message(RDE_O11).resources[0]
    assert mr["status"] == "active" and mr["intent"] == "order"
    assert mr["medicationCodeableConcept"]["coding"][0] == {
        "system": "http://www.whocc.no/atc", "code": "P01BF01",
        "display": "artemether and lumefantrine"}
    dose = mr["dosageInstruction"][0]
    assert dose["doseAndRate"][0]["doseQuantity"]["value"] == 4
    assert dose["route"]["coding"][0]["system"] == hl7v2.V2_0162
    assert mr["requester"]["display"] == "Ola Adeyemi"


def test_unsupported_message_is_refused():
    with pytest.raises(hl7v2.HL7MappingError):
        hl7v2.map_message(RDT_ORU.replace("ORU^R01", "ORM^O01"))


def test_split_batch():
    assert len(hl7v2.split_batch(RDT_ORU + "\r" + POTASSIUM_ORU)) == 2


def test_channel_exports_are_current_and_well_formed():
    for name, element in build.channels().items():
        text = (build.OUT / name).read_text(encoding="utf-8")
        assert text == build.render(element), f"run python -m apdt.integration.mirth.build ({name})"
        root = ET.fromstring(text)
        assert root.tag == "channel" and root.get("version") == build.VERSION
        assert root.find("sourceConnector/transportName").text == "Channel Reader"
        dest = root.find("destinationConnectors/connector")
        assert dest.find("transportName").text == "HTTP Sender"
        props = dest.find("properties")
        assert props.get("class") == "com.mirth.connect.connectors.http.HttpDispatcherProperties"
        assert props.find("content").text == "${fhirBundle}"
        assert props.find("method").text == "post"


def test_hl7_channel_embeds_the_mapping_script():
    script = channel_script("atra-hl7v2-to-fhir.xml")
    assert script.startswith(build.HL7_SCRIPT.read_text(encoding="utf-8"))
    assert script.rstrip().endswith(build.HL7_STEP)


@needs_node
@pytest.mark.parametrize("message", [RDT_ORU, POTASSIUM_ORU, ADT_A01, ADT_A03, RDE_O11])
def test_mirth_mapping_matches_the_p0_path(message):
    mirth = run_step(channel_script("atra-hl7v2-to-fhir.xml"), message)
    p0 = hl7v2.to_bundle(hl7v2.map_message(message))
    assert mirth["identifier"] == p0["identifier"]
    assert [normalised(e["resource"]) for e in mirth["entry"]] == [
        e["resource"] for e in p0["entry"]]


@needs_node
def test_dicom_channel_forwards_the_raw_message():
    out = subprocess.run([NODE, "-e", (
        "var store = {}; var channelMap = {put: function (k, v) { store[k] = v; }};"
        "var connectorMessage = {getRawData: function () { return 'QUJD'; }};"
        + channel_script("atra-dicom-sr-to-fhir.xml")
        + "process.stdout.write(store['fhirBundle']);")],
        capture_output=True, text=True, check=True, timeout=60)
    assert out.stdout == "QUJD"
