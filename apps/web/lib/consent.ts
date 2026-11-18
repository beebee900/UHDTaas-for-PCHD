// The consent categories a person switches in the app and the AHDT tools each withholds
// (atra.contracts.CONSENT_CATEGORIES), and the FHIR Consent the APDT stores (atra.consent).

export const PURPOSES = ["care", "emergency", "self_management", "public_health", "research"] as const;
export type Purpose = (typeof PURPOSES)[number];

const HL7: Record<Purpose, string> = {
  care: "TREAT",
  emergency: "ETREAT",
  research: "HRESCH",
  public_health: "PUBHLTH",
  self_management: "PATRQT",
};

export const CATEGORIES: Record<string, string[]> = {
  vital_signs_and_device_data: ["ahdt.data.observations", "ahdt.data.timeseries"],
  laboratory_and_imaging: ["ahdt.data.imaging"],
  medicines: ["ahdt.data.medications"],
  genome: ["ahdt.data.genome"],
  knowledge_graph_and_notes: ["ahdt.data.graph_query", "ahdt.data.documents", "ahdt.data.knowledge"],
  body_models_and_simulation: [
    "ahdt.model.calibrate", "ahdt.model.cosimulate", "ahdt.model.facet", "ahdt.model.forecast",
    "ahdt.model.simulate", "ahdt.model.state",
  ],
  explanations: ["ahdt.xai.causal_graph", "ahdt.xai.explain"],
  conversation_and_speech: [
    "ahdt.cognitive.converse", "ahdt.cognitive.perceive", "ahdt.cognitive.reason",
    "ahdt.cognitive.request_data",
  ],
};

export function withheldCategories(refusedTools: string[]): string[] {
  const refused = new Set(refusedTools);
  return Object.entries(CATEGORIES)
    .filter(([, tools]) => tools.some((tool) => refused.has(tool)))
    .map(([category]) => category);
}

export function consentResource(hdtId: string, purposes: Purpose[], withheld: string[]) {
  const tools = [...new Set(withheld.flatMap((c) => CATEGORIES[c] ?? []))].sort();
  return {
    resourceType: "Consent",
    meta: { profile: ["https://atra.local/fhir/StructureDefinition/atra-consent"] },
    status: "active",
    scope: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/consentscope", code: "patient-privacy" }] },
    category: [{ coding: [{ system: "http://loinc.org", code: "59284-0" }] }],
    patient: { reference: `Patient/${hdtId}` },
    dateTime: new Date().toISOString(),
    policyRule: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/v3-ActCode", code: "OPTIN" }] },
    provision: {
      type: "permit",
      purpose: purposes.map((p) => ({ system: "http://terminology.hl7.org/CodeSystem/v3-ActReason", code: HL7[p] })),
      provision: tools.map((code) => ({
        type: "deny",
        code: [{ coding: [{ system: "https://atra.local/fhir/CodeSystem/ahdt-tool", code }] }],
      })),
    },
  };
}
