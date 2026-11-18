"""Builds the Mirth Connect channel exports in `apdt/integration/mirth/channels/`.

`python -m apdt.integration.mirth.build` writes them; a test checks that the committed
files are current.

The export layout copies the public Mirth Connect 3.6.0 example channels of
github.com/nextgenhealthcare/connect-examples ("Get Num Pages From Embedded PDF"): a Channel
Reader source, a transformer of JavaScript steps, HL7v2 data type properties, and the
channel properties block. The HTTP Sender destination lists the fields of
`HttpDispatcherProperties.java` (nextgenhealthcare/connect, development branch) with that
class's default values. Not verified against a running Mirth: the XStream form of the
`headers` map, the DICOM data type block, the import of a 3.6.0 export into Mirth 4.5,
and `${...}` replacement of configuration-map values in the destination URL and headers.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "channels"
VERSION = "3.6.0"
HL7_SCRIPT = HERE / "hl7v2_to_fhir.js"
NAMESPACE = uuid.UUID("6c1d7f0e-6a2b-4d43-9a5e-3f6f2b1c9d10")
BUNDLE_VAR = "fhirBundle"
HL7_STEP = (f"channelMap.put('{BUNDLE_VAR}', "
            "JSON.stringify(hl7v2ToBundle(String(connectorMessage.getRawData()))));")
DICOM_STEP = (f"channelMap.put('{BUNDLE_VAR}', String(connectorMessage.getRawData()));")


def _el(tag: str, *children: Any, text: str | None = None, **attrs: str) -> ET.Element:
    e = ET.Element(tag, {k.rstrip("_"): v for k, v in attrs.items()})
    if text is not None:
        e.text = text
    for c in children:
        e.append(c)
    return e


def _fields(**values: Any) -> list[ET.Element]:
    return [_el(k, text=str(v).lower() if isinstance(v, bool) else str(v))
            for k, v in values.items()]


def _resources() -> ET.Element:
    return _el("resourceIds", _el("entry", _el("string", text="Default Resource"),
                                  _el("string", text="[Default Resource]")),
               class_="linked-hash-map")


def _hl7_properties(tag: str) -> ET.Element:
    p = "com.mirth.connect.plugins.datatypes.hl7v2."
    return _el(
        tag,
        _el("serializationProperties", *_fields(
            handleRepetitions=True, handleSubcomponents=True, useStrictParser=False,
            useStrictValidation=False, stripNamespaces=True, segmentDelimiter="\\r",
            convertLineBreaks=True), class_=p + "HL7v2SerializationProperties", version=VERSION),
        _el("deserializationProperties", *_fields(
            useStrictParser=False, useStrictValidation=False, segmentDelimiter="\\r"),
            class_=p + "HL7v2DeserializationProperties", version=VERSION),
        _el("batchProperties", *_fields(splitType="MSH_Segment", batchScript=""),
            class_=p + "HL7v2BatchProperties", version=VERSION),
        _el("responseGenerationProperties", *_fields(
            segmentDelimiter="\\r", successfulACKCode="AA", successfulACKMessage="",
            errorACKCode="AE", errorACKMessage="An Error Occurred Processing Message.",
            rejectedACKCode="AR", rejectedACKMessage="Message Rejected.", msh15ACKAccept=False,
            dateFormat="yyyyMMddHHmmss.SSS"),
            class_=p + "HL7v2ResponseGenerationProperties", version=VERSION),
        _el("responseValidationProperties", *_fields(
            successfulACKCode="AA,CA", errorACKCode="AE,CE", rejectedACKCode="AR,CR",
            validateMessageControlId=True, originalMessageControlId="Destination_Encoded",
            originalIdMapVariable=""),
            class_=p + "HL7v2ResponseValidationProperties", version=VERSION),
        class_=p + "HL7v2DataTypeProperties", version=VERSION)


def _data_type(tag: str, kind: str) -> ET.Element:
    if kind == "HL7V2":
        return _hl7_properties(tag)
    return _el(tag, class_="com.mirth.connect.plugins.datatypes.dicom.DICOMDataTypeProperties",
               version=VERSION)


def _transformer(tag: str, kind: str, steps: list[tuple[str, str]]) -> ET.Element:
    elements = _el("elements", *[
        _el("com.mirth.connect.plugins.javascriptstep.JavaScriptStep",
            _el("name", text=name), _el("sequenceNumber", text=str(i)),
            _el("script", text=script)) for i, (name, script) in enumerate(steps)])
    return _el(tag, elements, _el("inboundTemplate", text="", encoding="base64"),
               _el("outboundTemplate", text="", encoding="base64"),
               _el("inboundDataType", text=kind), _el("outboundDataType", text=kind),
               _data_type("inboundProperties", kind), _data_type("outboundProperties", kind),
               version=VERSION)


def _filter() -> ET.Element:
    return _el("filter", _el("elements"), version=VERSION)


def _source(kind: str, steps: list[tuple[str, str]]) -> ET.Element:
    props = _el(
        "properties", _el("pluginProperties"),
        _el("sourceConnectorProperties", *_fields(
            responseVariable="None", respondAfterProcessing=True, processBatch=False,
            firstResponse=False, processingThreads=1), _resources(),
            *_fields(queueBufferSize=1000), version=VERSION),
        class_="com.mirth.connect.connectors.vm.VmReceiverProperties", version=VERSION)
    return _el("sourceConnector", *_fields(metaDataId=0, name="sourceConnector"), props,
               _transformer("transformer", kind, steps), _filter(),
               *_fields(transportName="Channel Reader", mode="SOURCE", enabled=True,
                        waitForPrevious=True), version=VERSION)


def _http_destination(kind: str, path: str) -> ET.Element:
    dest = _el("destinationConnectorProperties", *_fields(
        queueEnabled=True, sendFirst=False, retryIntervalMillis=10000, regenerateTemplate=False,
        retryCount=0, rotate=False, includeFilterTransformer=False, threadCount=1,
        threadAssignmentVariable="", validateResponse=False), _resources(),
        *_fields(queueBufferSize=1000, reattachAttachments=True), version=VERSION)
    headers = _el("headers", _el("entry", _el("string", text="Authorization"),
                                 _el("list", _el("string", text="Bearer ${apdtToken}"))),
                  class_="linked-hash-map")
    props = _el(
        "properties", _el("pluginProperties"), dest,
        *_fields(host="${apdtBaseUrl}" + path, useProxyServer=False, proxyAddress="",
                 proxyPort="", method="post"), headers,
        _el("parameters", class_="linked-hash-map"),
        *_fields(useHeadersVariable=False, headersVariable="", useParametersVariable=False,
                 parametersVariable="", responseXmlBody=False, responseParseMultipart=True,
                 responseIncludeMetadata=False,
                 responseBinaryMimeTypes="application/.*(?<!json|xml)$|image/.*|video/.*|audio/.*",
                 responseBinaryMimeTypesRegex=True, multipart=False, useAuthentication=False,
                 authenticationType="Basic", usePreemptiveAuthentication=False, username="",
                 password="", content="${" + BUNDLE_VAR + "}",
                 contentType="application/fhir+json" if kind == "HL7V2" else "text/plain",
                 dataTypeBinary=False, charset="UTF-8", socketTimeout=30000),
        class_="com.mirth.connect.connectors.http.HttpDispatcherProperties", version=VERSION)
    return _el("connector", *_fields(metaDataId=1, name="APDT integration"), props,
               _transformer("transformer", kind, []),
               _transformer("responseTransformer", kind, []), _filter(),
               *_fields(transportName="HTTP Sender", mode="DESTINATION", enabled=True,
                        waitForPrevious=True), version=VERSION)


def channel(name: str, description: str, kind: str, steps: list[tuple[str, str]],
            path: str) -> ET.Element:
    ch = _el("channel", version=VERSION)
    for child in (
        _el("id", text=str(uuid.uuid5(NAMESPACE, name))), _el("nextMetaDataId", text="2"),
        _el("name", text=name), _el("description", text=description),
        _el("revision", text="1"), _source(kind, steps),
        _el("destinationConnectors", _http_destination(kind, path)),
        _el("preprocessingScript", text="return message;"),
        _el("postprocessingScript", text="return;"), _el("deployScript", text="return;"),
        _el("undeployScript", text="return;"),
        _el("properties", *_fields(
            clearGlobalChannelMap=True, messageStorageMode="DEVELOPMENT", encryptData=False,
            removeContentOnCompletion=False, removeOnlyFilteredOnCompletion=False,
            removeAttachmentsOnCompletion=False, initialState="STARTED", storeAttachments=False),
            _el("attachmentProperties", _el("type", text="None"), _el("properties"),
                version=VERSION), _resources(), version=VERSION)):
        ch.append(child)
    return ch


def channels() -> dict[str, ET.Element]:
    mapping = HL7_SCRIPT.read_text(encoding="utf-8")
    return {
        "atra-hl7v2-to-fhir.xml": channel(
            "ATRA HL7v2 to FHIR",
            "ADT^A01/A03, ORU^R01 and RDE^O11 to a FHIR collection Bundle, posted to the APDT "
            "integration inbox of the tenant. The facility feed (MLLP listener or OpenHIM TCP "
            "channel) writes to this channel.",
            "HL7V2", [("Map HL7 v2 to FHIR", mapping + "\n" + HL7_STEP)],
            "/v1/t/${tenantId}/integration/fhir"),
        "atra-dicom-sr-to-fhir.xml": channel(
            "ATRA DICOM SR to FHIR",
            "Structured reports (TID 1500) are forwarded as base64 text to the APDT, which "
            "maps them with highdicom.",
            "DICOM", [("Forward the SR", DICOM_STEP)],
            "/v1/t/${tenantId}/integration/dicom-sr"),
    }


def render(element: ET.Element) -> str:
    ET.indent(element, space="  ")
    return ET.tostring(element, encoding="unicode") + "\n"


def write(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, element in channels().items():
        path = out / name
        path.write_text(render(element), encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in write():
        print(p)
