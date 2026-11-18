// HL7 v2 to FHIR R4 mapping of the Mirth channels (design 05, 5.3).
// The same mapping as apdt/integration/hl7v2.py: ORU^R01 -> DiagnosticReport + Observation,
// ADT^A01/A03 -> Encounter, RDE^O11 -> MedicationRequest. ECMAScript 5 only, so that it runs
// in the Rhino engine of Mirth Connect and in Node for the offline tests.

var CODING_SYSTEMS = {
  LN: "http://loinc.org", SCT: "http://snomed.info/sct", MDC: "urn:iso:std:iso:11073:10101",
  WC: "http://www.whocc.no/atc", UCUM: "http://unitsofmeasure.org"
};
var UNKNOWN_SYSTEM = "urn:atra:hl7v2:coding:";
var AUTHORITY_SYSTEM = "urn:atra:hl7v2:authority:";
var PATIENT_SYSTEM = "https://atra.health/hdt-id";
var PLACER_SYSTEM = "urn:atra:hl7v2:placer";
var FILLER_SYSTEM = "urn:atra:hl7v2:filler";
var V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074";
var V2_0162 = "http://terminology.hl7.org/CodeSystem/v2-0162";
var OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category";
var INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation";
var ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode";
var UCUM = "http://unitsofmeasure.org";
var OBSERVATION_STATUS = {A: "amended", C: "corrected", D: "entered-in-error", F: "final",
  P: "preliminary", X: "cancelled", W: "entered-in-error"};
var REPORT_STATUS = {O: "registered", I: "registered", S: "registered", P: "preliminary",
  C: "corrected", R: "partial", F: "final", X: "cancelled"};
var REQUEST_STATUS = {AF: "active", CA: "active", CR: "revoked", DC: "revoked", DF: "revoked",
  DR: "revoked", FU: "completed", HD: "active", HR: "on-hold", NW: "active", OC: "revoked",
  OD: "revoked", OH: "on-hold", OK: "active", PR: "active", PY: "active", RL: "active",
  RO: "active", RQ: "active"};
var PATIENT_CLASS = {E: "EMER", I: "IMP", O: "AMB", P: "PRENC", R: "R", B: "B", C: "C", N: "N",
  U: "U"};
var INTERPRETATION_CODES = ["<", ">", "A", "AA", "B", "CAR", "D", "DET", "E", "EX", "EXP", "H",
  "HH", "HU", "I", "IE", "IND", "L", "LL", "LU", "MS", "N", "NCL", "ND", "NEG", "NR", "NS",
  "POS", "R", "RR", "S", "SDD", "SYN-R", "SYN-S", "U", "VS", "UNE", "W", "WR"];
var COMPARATORS = ["<", "<=", ">=", ">"];

function has(list, value) {
  for (var i = 0; i < list.length; i++) { if (list[i] === value) { return true; } }
  return false;
}

function lookup(table, key, fallback) {
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : fallback;
}

function fhirId(value) {
  return value.replace(/[^A-Za-z0-9\-.]/g, "-").substring(0, 64);
}

function pad(n) { return (n < 10 ? "0" : "") + n; }

function hl7Time(value) {
  var m = /^(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2}))?(\d{2})?(?:\.\d+)?([+-]\d{4})?$/
    .exec(value.replace(/^\s+|\s+$/g, ""));
  if (!m) { throw new Error("not an HL7 timestamp: " + value); }
  var zone = m[7] ? m[7].substring(0, 3) + ":" + m[7].substring(3) : "+00:00";
  return m[1] + "-" + m[2] + "-" + m[3] + "T" + (m[4] || "00") + ":" + (m[5] || "00") + ":" +
    (m[6] || "00") + zone;
}

function parse(text) {
  text = text.replace(/\r\n/g, "\r").replace(/\n/g, "\r").replace(/^\r+|\r+$/g, "");
  var enc = {field: text.charAt(3), comp: text.charAt(4), rep: text.charAt(5)};
  var segments = [];
  var lines = text.split("\r");
  for (var i = 0; i < lines.length; i++) {
    if (!lines[i]) { continue; }
    var fields = lines[i].split(enc.field);
    // MSH-1 is the field separator itself, so MSH field n sits at index n - 1.
    if (fields[0] === "MSH") { fields.splice(1, 0, enc.field); }
    segments.push(fields);
  }
  return {enc: enc, segments: segments};
}

function get(msg, seg, number, component) {
  component = component || 1;
  if (!seg || number >= seg.length) { return ""; }
  var parts = seg[number].split(msg.enc.rep)[0].split(msg.enc.comp);
  return component <= parts.length ? parts[component - 1] : "";
}

function segment(msg, name) {
  for (var i = 0; i < msg.segments.length; i++) {
    if (msg.segments[i][0] === name) { return msg.segments[i]; }
  }
  return null;
}

function coding(msg, seg, number) {
  var code = get(msg, seg, number, 1);
  if (!code) { return null; }
  var sid = get(msg, seg, number, 3);
  var out = {system: lookup(CODING_SYSTEMS, sid, UNKNOWN_SYSTEM + sid), code: code};
  if (get(msg, seg, number, 2)) { out.display = get(msg, seg, number, 2); }
  return out;
}

function concept(c) {
  var out = {coding: [c]};
  if (c.display) { out.text = c.display; }
  return out;
}

function subject(patient) {
  return {identifier: {system: patient[0], value: patient[1]}};
}

function quantity(value, unit) {
  var q = {value: value};
  if (unit) { q.unit = unit; q.system = UCUM; q.code = unit; }
  return q;
}

function observation(msg, obx, control, index, patient, whenDefault) {
  var code = coding(msg, obx, 3);
  if (!code) { throw new Error("OBX " + index + " has no OBX-3 code"); }
  var setId = get(msg, obx, 1) || String(index);
  var body = {
    resourceType: "Observation", id: fhirId("obs-" + control + "-" + setId),
    status: lookup(OBSERVATION_STATUS, get(msg, obx, 11), "unknown"),
    category: [{coding: [{system: OBS_CATEGORY, code: "laboratory"}]}],
    code: concept(code), subject: subject(patient)
  };
  var when = get(msg, obx, 14) || whenDefault;
  if (when) { body.effectiveDateTime = hl7Time(when); }
  var vtype = get(msg, obx, 2);
  var unit = get(msg, obx, 6);
  if (vtype === "NM" && get(msg, obx, 5)) {
    body.valueQuantity = quantity(parseFloat(get(msg, obx, 5)), unit);
  } else if (vtype === "SN" && get(msg, obx, 5, 2)) {
    var q = quantity(parseFloat(get(msg, obx, 5, 2)), unit);
    if (has(COMPARATORS, get(msg, obx, 5, 1))) { q.comparator = get(msg, obx, 5, 1); }
    body.valueQuantity = q;
  } else if ((vtype === "CE" || vtype === "CWE") && coding(msg, obx, 5)) {
    body.valueCodeableConcept = concept(coding(msg, obx, 5));
  } else if (get(msg, obx, 5)) {
    body.valueString = obx[5];
  }
  var flag = get(msg, obx, 8);
  if (has(INTERPRETATION_CODES, flag)) {
    body.interpretation = [{coding: [{system: INTERPRETATION, code: flag}]}];
  }
  return body;
}

function patientOf(msg) {
  var pid = segment(msg, "PID");
  var value = get(msg, pid, 3, 1);
  var authority = get(msg, pid, 3, 4);
  if (!value) { throw new Error("PID-3 has no identifier"); }
  if (authority === "ATRA") { return [PATIENT_SYSTEM, value]; }
  return [AUTHORITY_SYSTEM + (authority || "unknown"), value];
}

function mapOru(msg, out) {
  var report = null;
  var reports = [];
  var obrWhen = "";
  var index = 0;
  for (var i = 0; i < msg.segments.length; i++) {
    var seg = msg.segments[i];
    if (seg[0] === "OBR") {
      obrWhen = get(msg, seg, 7);
      report = {
        resourceType: "DiagnosticReport",
        id: fhirId("dr-" + out.controlId + "-" + (get(msg, seg, 1) || String(reports.length + 1))),
        status: lookup(REPORT_STATUS, get(msg, seg, 25), "unknown"),
        category: [{coding: [{system: V2_0074, code: get(msg, seg, 24) || "LAB"}]}],
        subject: subject(out.patient), result: []
      };
      if (coding(msg, seg, 4)) { report.code = concept(coding(msg, seg, 4)); }
      if (get(msg, seg, 2)) {
        report.basedOn = [{type: "ServiceRequest",
          identifier: {system: PLACER_SYSTEM, value: get(msg, seg, 2)}}];
      }
      if (get(msg, seg, 3)) { report.identifier = [{system: FILLER_SYSTEM, value: get(msg, seg, 3)}]; }
      if (obrWhen) { report.effectiveDateTime = hl7Time(obrWhen); }
      if (get(msg, seg, 22)) { report.issued = hl7Time(get(msg, seg, 22)); }
      reports.push(report);
    } else if (seg[0] === "OBX") {
      index += 1;
      var obs = observation(msg, seg, out.controlId, index, out.patient, obrWhen);
      out.resources.push(obs);
      if (report !== null) {
        report.result.push({reference: "Observation/" + obs.id});
        if (!report.code) { report.code = obs.code; }
      }
    }
  }
  for (var j = 0; j < reports.length; j++) { out.resources.push(reports[j]); }
}

function mapAdt(msg, out) {
  var pv1 = segment(msg, "PV1");
  var visit = get(msg, pv1, 19) || out.controlId;
  var body = {
    resourceType: "Encounter", id: fhirId("enc-" + visit),
    status: out.trigger === "A03" ? "finished" : "in-progress",
    "class": {system: ACT_CODE, code: lookup(PATIENT_CLASS, get(msg, pv1, 2), "U")},
    subject: subject(out.patient),
    identifier: [{system: PLACER_SYSTEM, value: visit}]
  };
  var period = {};
  var any = false;
  if (get(msg, pv1, 44)) { period.start = hl7Time(get(msg, pv1, 44)); any = true; }
  if (get(msg, pv1, 45)) { period.end = hl7Time(get(msg, pv1, 45)); any = true; }
  if (any) { body.period = period; }
  out.resources.push(body);
}

function medicationRequest(msg, orc, rxe, out, count) {
  var medication = coding(msg, rxe, 2);
  if (!medication) { throw new Error("RXE-2 has no give code"); }
  var placer = orc ? get(msg, orc, 2) : "";
  var body = {
    resourceType: "MedicationRequest", id: fhirId("mr-" + (placer || out.controlId) + "-" + count),
    status: lookup(REQUEST_STATUS, orc ? get(msg, orc, 1) : "", "unknown"),
    intent: "order", medicationCodeableConcept: concept(medication),
    subject: subject(out.patient), dosageInstruction: [{}]
  };
  if (placer) { body.identifier = [{system: PLACER_SYSTEM, value: placer}]; }
  if (orc && get(msg, orc, 9)) { body.authoredOn = hl7Time(get(msg, orc, 9)); }
  if (orc && get(msg, orc, 12, 2)) {
    var parts = [];
    if (get(msg, orc, 12, 3)) { parts.push(get(msg, orc, 12, 3)); }
    parts.push(get(msg, orc, 12, 2));
    body.requester = {display: parts.join(" ")};
  }
  if (get(msg, rxe, 3)) {
    body.dosageInstruction[0].doseAndRate = [{doseQuantity: quantity(parseFloat(get(msg, rxe, 3)),
      get(msg, rxe, 5))}];
  }
  return body;
}

function mapRde(msg, out) {
  var orc = null;
  var pending = null;
  var count = 0;
  for (var i = 0; i < msg.segments.length; i++) {
    var seg = msg.segments[i];
    if (seg[0] === "ORC") {
      orc = seg;
    } else if (seg[0] === "RXE") {
      if (pending !== null) { out.resources.push(pending); }
      count += 1;
      pending = medicationRequest(msg, orc, seg, out, count);
    } else if (seg[0] === "RXR" && pending !== null) {
      var route = coding(msg, seg, 1);
      if (route) {
        if (route.system === UNKNOWN_SYSTEM + "HL70162") { route.system = V2_0162; }
        pending.dosageInstruction[0].route = concept(route);
      }
    }
  }
  if (pending !== null) { out.resources.push(pending); }
}

function hl7v2ToBundle(text) {
  var msg = parse(text);
  var msh = segment(msg, "MSH");
  var out = {
    messageType: get(msg, msh, 9, 1) + "^" + get(msg, msh, 9, 2), trigger: get(msg, msh, 9, 2),
    controlId: get(msg, msh, 10), patient: patientOf(msg), resources: []
  };
  if (out.messageType === "ORU^R01") {
    mapOru(msg, out);
  } else if (out.messageType === "ADT^A01" || out.messageType === "ADT^A03") {
    mapAdt(msg, out);
  } else if (out.messageType === "RDE^O11") {
    mapRde(msg, out);
  } else {
    throw new Error("unsupported message type " + out.messageType);
  }
  var entries = [];
  for (var k = 0; k < out.resources.length; k++) { entries.push({resource: out.resources[k]}); }
  return {resourceType: "Bundle", type: "collection",
    identifier: {system: "urn:atra:hl7v2:control-id", value: out.controlId}, entry: entries};
}
