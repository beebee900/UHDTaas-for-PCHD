"""HL7 v2 messages and public-documentation sources of the WP20 integration tests."""

from atra.personas import BY_KEY

HDT = BY_KEY["ao"].hdt_id

DOCS = {
    "hl7v2_segments": "https://hl7-definition.caristix.com/v2/HL7v2.5/Segments",
    "v2_to_fhir_conceptmaps": "https://build.fhir.org/ig/HL7/v2-to-fhir/artifacts.html",
    "mirth_examples": "https://github.com/nextgenhealthcare/connect-examples",
    "mirth_http_dispatcher": "https://github.com/nextgenhealthcare/connect/blob/development/"
                             "server/src/com/mirth/connect/connectors/http/"
                             "HttpDispatcherProperties.java",
    "mirth_js_scope": "https://github.com/nextgenhealthcare/connect/blob/development/server/"
                      "src/com/mirth/connect/server/util/javascript/JavaScriptScopeUtil.java",
    "openmrs_patient": "https://openmrs.atlassian.net/wiki/spaces/docs/pages/26935802/"
                       "Patient+Resource",
    "openmrs_observation": "https://openmrs.atlassian.net/wiki/spaces/docs/pages/26935806/"
                           "Observation+Resource",
    "openhim_mediators": "https://openhim.org/docs/dev-guide/developing-mediators",
    "openhim_auth": "https://openhim.org/docs/api/introduction/authentication",
    "openhim_core_routes": "https://github.com/jembi/openhim-core-js/blob/master/src/koaApi.js",
    "odk_auth": "https://docs.getodk.org/central-api-authentication/",
    "odk_odata": "https://docs.getodk.org/central-api-odata-endpoints/",
    "xlsform": "https://xlsform.org/en/",
    "sdc_extract": "https://build.fhir.org/ig/HL7/sdc/en/extraction.html",
    "sdc_populate": "https://build.fhir.org/ig/HL7/sdc/en/populate.html",
}

# LOINC 76772-3 and SNOMED CT 10828004 / 260385009 were looked up on tx.fhir.org.
RDT_ORU = "\r".join([
    "MSH|^~\\&|LIS|FAC-A|ATRA|APDT|202610011100||ORU^R01|LAB-0001|P|2.5",
    f"PID|1||{HDT}^^^ATRA^PI",
    "OBR|1|SR-0001|LAB-RDT-1|76772-3^Plasmodium falciparum Ag [Presence] in Blood by Rapid "
    "immunoassay^LN|||202610011030|||||||||||||||202610011100||LAB|F",
    "OBX|1|CWE|76772-3^Plasmodium falciparum Ag [Presence] in Blood by Rapid immunoassay^LN||"
    "10828004^Positive^SCT|||A|||F|||202610011045",
])

POTASSIUM_ORU = "\r".join([
    "MSH|^~\\&|LIS|FAC-A|ATRA|APDT|202610011200||ORU^R01|LAB-0002|P|2.5",
    f"PID|1||{HDT}^^^ATRA^PI",
    "OBR|1|||2823-3^Potassium^LN|||202610011130||||||||||||||||||F",
    "OBX|1|NM|2823-3^Potassium [Moles/volume] in Serum or Plasma^LN||7.0|mmol/L|3.5-5.1|HH|||F",
])

ADT_A01 = "\r".join([
    "MSH|^~\\&|OPENMRS|FAC-A|ATRA|APDT|202610010900||ADT^A01|ADT-0001|P|2.5",
    "EVN|A01|202610010900",
    f"PID|1||{HDT}^^^ATRA^PI",
    "PV1|1|I|WARD-1||||||||||||||||V-0001|||||||||||||||||||||||||202610010900",
])

ADT_A03 = ADT_A01.replace("ADT^A01|ADT-0001", "ADT^A03|ADT-0002").replace(
    "EVN|A01", "EVN|A03") + "|202610051200"

RDE_O11 = "\r".join([
    "MSH|^~\\&|PHARM|FAC-A|ATRA|APDT|202610011300||RDE^O11|RX-0001|P|2.5",
    f"PID|1||{HDT}^^^ATRA^PI",
    "ORC|NW|MR-0001|||||||202610011255|||MO^Adeyemi^Ola",
    "RXE||P01BF01^artemether and lumefantrine^WC|4||{tbl}^tablet^UCUM",
    "RXR|PO^Oral^HL70162",
])
