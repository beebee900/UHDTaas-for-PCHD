"use client";

import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AgentReport } from "@/components/agents/AgentReport";
import { type AgentReportData, parseReport } from "@/lib/agents";

type State =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; report: AgentReportData }
  | { phase: "error"; message: "failed" | "role" };

// Runs one twin's agents (`twin`) or the conductor (`conductor`) for the episode's person.
export function RunAgents({
  episodeId,
  twin,
  conductor = false,
}: {
  episodeId: string;
  twin?: string;
  conductor?: boolean;
}) {
  const t = useTranslations("agents");
  const [state, setState] = useState<State>({ phase: "idle" });
  const [goal, setGoal] = useState(() => t("conductorGoal"));

  async function run() {
    setState({ phase: "running" });
    try {
      const response = await fetch("/api/agents/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          conductor ? { episodeId, conductor: true, personGoal: goal } : { episodeId, twin },
        ),
      });
      if (!response.ok) {
        setState({ phase: "error", message: response.status === 403 ? "role" : "failed" });
        return;
      }
      setState({ phase: "done", report: parseReport(await response.json()) });
    } catch {
      setState({ phase: "error", message: "failed" });
    }
  }

  return (
    <Stack gap={2}>
      {conductor && (
        <TextField
          label={t("goalLabel")}
          helperText={t("goalHelp")}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          fullWidth
        />
      )}
      <div>
        <Button
          variant="contained"
          onClick={run}
          disabled={state.phase === "running" || (conductor && !goal.trim())}
          startIcon={state.phase === "running" ? <CircularProgress size={16} /> : undefined}
        >
          {conductor ? t("runConductor") : t("run")}
        </Button>
      </div>
      {state.phase === "error" && (
        <Alert severity="error">{state.message === "role" ? t("needsRole") : t("failed")}</Alert>
      )}
      {state.phase === "done" && <AgentReport report={state.report} />}
    </Stack>
  );
}
