import type { components } from "./api/apdt";

export type Recommendation = components["schemas"]["Recommendation"];
export type Bundle = components["schemas"]["ExplanationBundle"];
export type SourcedItem = components["schemas"]["SourcedItem"];
export type Tenant = "fac-a" | "fac-b";

type Payload = Record<string, unknown>;

export function titleOf(rec: Recommendation): string {
  const p = rec.payload as Payload;
  const code = p.code as { display?: string | null; code?: string } | undefined;
  for (const candidate of [code?.display, p.text, p.name, p.title, code?.code]) {
    if (typeof candidate === "string" && candidate) return candidate;
  }
  // Test recommendations list tests in value-of-information order; treatments list doses.
  const listed = namesOf(p.tests, "name") || namesOf(p.doses, "drug");
  return listed || rec.kind;
}

function namesOf(entries: unknown, key: string): string {
  if (!Array.isArray(entries)) return "";
  const names = entries
    .map((e) => (e && typeof e === "object" ? (e as Payload)[key] : undefined))
    .filter((n): n is string => typeof n === "string" && n.length > 0);
  return [...new Set(names)].join(", ");
}

export function probabilityOf(rec: Recommendation): number | null {
  const value = (rec.payload as Payload).probability;
  return typeof value === "number" ? value : (rec.confidence ?? null);
}

export type SafetyIssue = { severity: string | null; text: string };

// Safety issues arrive as a list of strings or of objects with a severity and a summary.
export function safetyIssuesOf(rec: Recommendation): SafetyIssue[] {
  const p = rec.payload as Payload;
  const raw = p.safety_issues ?? p.issues;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry): SafetyIssue[] => {
    if (typeof entry === "string") return [{ severity: null, text: entry }];
    if (entry && typeof entry === "object") {
      const e = entry as Payload;
      const text = e.summary ?? e.text ?? e.detail ?? e.message ?? e.code;
      if (typeof text === "string") {
        return [{ severity: typeof e.severity === "string" ? e.severity : null, text }];
      }
    }
    return [];
  });
}

export const percent = (value: number) => `${Math.round(value * 100)}%`;

export type ClinicalEntry = components["schemas"]["ClinicalEntry"];

// A drug of the prescription or the care plan, as the dispense and care-given sheets offer it.
export type Prescribed = { drug: string; perDose: string; route: string | null; perDay: number | null; days: number | null };

function perDoseText(perDose: unknown): string {
  const mg = (perDose as Payload | undefined)?.mg;
  if (typeof mg === "number") return `${mg} mg`;
  if (mg && typeof mg === "object") {
    return Object.entries(mg as Payload)
      .filter((e): e is [string, number] => typeof e[1] === "number")
      .map(([part, value]) => `${part} ${value} mg`)
      .join(" + ");
  }
  return "";
}

export function prescribedOf(recs: Recommendation[]): Prescribed[] {
  const found = new Map<string, Prescribed>();
  for (const rec of recs) {
    const p = rec.payload as Payload;
    for (const list of [p.doses, p.plan]) {
      if (!Array.isArray(list)) continue;
      for (const raw of list) {
        const d = raw as Payload;
        if (typeof d?.drug !== "string" || found.has(d.drug)) continue;
        const s = (d.schedule ?? {}) as Payload;
        found.set(d.drug, {
          drug: d.drug,
          perDose: perDoseText(d.per_dose),
          route: typeof s.route === "string" ? s.route : null,
          perDay: typeof s.doses_per_day === "number" ? s.doses_per_day : null,
          days: typeof s.duration_days === "number" ? s.duration_days : null,
        });
      }
    }
  }
  return [...found.values()];
}
