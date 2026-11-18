import type { Recommendation } from "./clinical";

type Json = Record<string, unknown>;

export type GoalStatus = "met" | "unmet" | "not_evaluated";

export type AgentStep = {
  node: string;
  agent: string;
  status: string;
  tools: string[];
  missing: string[];
};

export type AgentGoal = { id: string; text: string | null; status: string; detail: string };
export type AgentDenial = { agent: string; action: string; reason: string };

export type AgentReportData = {
  goals: AgentGoal[];
  steps: AgentStep[];
  toolCalls: string[];
  proposals: Recommendation[];
  explanations: string[];
  denials: AgentDenial[];
  missing: string[];
  notes: string[];
};

const isRecord = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const texts = (value: unknown): string[] => list(value).filter((v): v is string => typeof v === "string");

function toolNames(value: unknown): string[] {
  return list(value).flatMap((entry) => {
    if (typeof entry === "string") return [entry];
    return isRecord(entry) && typeof entry.tool === "string" ? [entry.tool] : [];
  });
}

// Steps of an APDT run (`result.steps`) and of an AHDT orchestrator report share this shape.
export function stepsOf(value: unknown): AgentStep[] {
  return list(value).filter(isRecord).map((s) => ({
    node: text(s.node),
    agent: text(s.agent),
    status: text(s.status),
    tools: toolNames(s.tool_calls ?? s.tools),
    missing: texts(s.missing_evidence),
  }));
}

function denialsOf(value: unknown): AgentDenial[] {
  return list(value).filter(isRecord).map((d) => ({
    agent: text(d.agent),
    action: text(d.action),
    reason: text(d.reason),
  }));
}

function orchestratorPart(report: Json) {
  return {
    steps: stepsOf(report.steps),
    toolCalls: toolNames(report.tool_calls),
    proposals: list(report.proposals).filter(isRecord) as unknown as Recommendation[],
    explanations: texts(report.explanations),
    denials: denialsOf(report.denials),
    missing: texts(report.missing_evidence),
  };
}

export function parseReport(raw: unknown): AgentReportData {
  const report = isRecord(raw) ? raw : {};
  if (report.kind === "conductor") {
    const parts = Object.values(isRecord(report.orchestrators) ? report.orchestrators : {})
      .filter(isRecord)
      .map(orchestratorPart);
    return {
      goals: list(report.sub_goals).filter(isRecord).map((g) => ({
        id: text(g.goal_id),
        text: null,
        status: text(g.status),
        detail: text(g.detail),
      })),
      steps: parts.flatMap((p) => p.steps),
      toolCalls: parts.flatMap((p) => p.toolCalls),
      proposals: parts.flatMap((p) => p.proposals),
      explanations: parts.flatMap((p) => p.explanations),
      denials: denialsOf(report.denials),
      missing: parts.flatMap((p) => p.missing),
      notes: texts(report.notes),
    };
  }
  return {
    goals: list(report.goals).filter(isRecord).map((g) => ({
      id: text(g.goal_id),
      text: text(g.text) || null,
      status: text(g.status),
      detail: text(g.detail),
    })),
    ...orchestratorPart(report),
    notes: [],
  };
}
