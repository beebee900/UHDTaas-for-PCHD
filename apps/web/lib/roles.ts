import type { Session } from "./session";

// Role groups that mirror the service policies (policies/opa and the AHDT role checks).
export const CLINICIANS = new Set([
  "medical_officer", "radiologist", "pharmacist", "nurse", "lab_scientist",
  "community_health_worker", "therapist",
]);
const CREATE_EPISODE = new Set(["medical_officer", "nurse", "community_health_worker"]);
const PATIENT_SIDE = new Set(["patient", "proxy"]);
const AUDIT = new Set(["medical_officer", "administrator", "clinical_safety_officer"]);
const MODELS = new Set(["medical_officer", "nurse", "administrator", "clinical_safety_officer"]);
const MODEL_STAGING = new Set(["administrator", "clinical_safety_officer"]);
const POPULATION = new Set(["medical_officer", "administrator", "researcher", "public_health_official"]);
const COHORT = new Set(["researcher", "public_health_official"]);
const RUN_AGENTS = new Set(["medical_officer", "nurse", "patient"]);
const CONVERSE = new Set([
  ...CLINICIANS, "patient", "proxy", "person", "carer",
]);

export type Home = "clinician" | "patient" | "person" | "carer" | "governance" | "population";

// Where each home lives; clinicians and governance roles use the dashboard itself.
export const HOME_PATH: Record<Home, string> = {
  clinician: "/dashboard",
  governance: "/dashboard",
  patient: "/care",
  person: "/twin",
  carer: "/cared",
  population: "/population",
};

export const can = {
  createEpisode: (role: string) => CREATE_EPISODE.has(role),
  readAudit: (role: string) => AUDIT.has(role),
  readModels: (role: string) => MODELS.has(role),
  stageModels: (role: string) => MODEL_STAGING.has(role),
  readPopulation: (role: string) => POPULATION.has(role),
  extractCohort: (role: string) => COHORT.has(role),
  runAgents: (role: string) => RUN_AGENTS.has(role),
  converse: (role: string) => CONVERSE.has(role),
  decide: (role: string) => role === "medical_officer",
};

export function homeOf(role: string): Home {
  if (CLINICIANS.has(role)) return "clinician";
  if (PATIENT_SIDE.has(role)) return "patient";
  if (role === "person") return "person";
  if (role === "carer") return "carer";
  if (role === "administrator" || role === "clinical_safety_officer") return "governance";
  return "population";
}

// The persons a patient-side or carer session acts for.
export function personsOf(session: Session): string[] {
  if (session.role === "proxy") return session.proxyFor;
  if (session.role === "carer") return session.carerFor;
  return session.hdtId ? [session.hdtId] : [];
}

export type NavKey =
  | "home" | "episodes" | "newEpisode" | "myCare" | "myTwin" | "cared" | "population"
  | "audit" | "models" | "system";

export type NavItem = { key: NavKey; href: string };

export function navFor(session: Session): NavItem[] {
  const role = session.role;
  const home = homeOf(role);
  const items: NavItem[] =
    home === "clinician" || home === "governance" ? [{ key: "home", href: "/dashboard" }] : [];
  if (CLINICIANS.has(role)) items.push({ key: "episodes", href: "/episodes" });
  if (can.createEpisode(role)) items.push({ key: "newEpisode", href: "/episodes/new" });
  if (PATIENT_SIDE.has(role)) items.push({ key: "myCare", href: "/care" });
  if (role === "person") items.push({ key: "myTwin", href: "/twin" });
  if (role === "carer") items.push({ key: "cared", href: "/cared" });
  if (can.readPopulation(role)) items.push({ key: "population", href: "/population" });
  if (can.readAudit(role)) items.push({ key: "audit", href: "/audit" });
  if (can.readModels(role)) items.push({ key: "models", href: "/models" });
  items.push({ key: "system", href: "/system" });
  return items;
}
