"use client";

import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AgentSteps } from "@/components/agents/AgentSteps";
import { type AgentStep, stepsOf } from "@/lib/agents";

type Run = {
  run_id: string;
  status: string;
  result?: { steps?: unknown; status?: unknown } | null;
  interrupt?: {
    kind: string;
    payload: { recommendation_id?: string };
    allowed_decisions: string[];
    required_role: string;
  } | null;
};

const DECISIONS = ["accept", "sign", "verify", "consent", "edit", "query", "reject", "decline"] as const;
type Decision = (typeof DECISIONS)[number];
type Goal = "diagnosis" | "treatment" | "care";

const PRIMARY = new Set<Decision>(["accept", "sign", "verify", "consent"]);
const NEEDS_TEXT = new Set<Decision>(["edit", "query", "reject", "decline"]);
const DANGER = new Set<Decision>(["reject", "decline"]);

type State =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "none" }
  | { phase: "open"; run: Run }
  | { phase: "error"; message: "failed" | "role" };

// Starts the goal's agent run and shows its interrupt. Only a human with the interrupt's role
// can decide; others see whom the step waits for. A decision can open the next interrupt
// (for example signing hands the prescription to the pharmacist).
export function DecisionBar({
  episodeId,
  recommendationId,
  goal,
  role,
  autoStart = true,
}: {
  episodeId: string;
  recommendationId: string;
  goal: Goal;
  role: string;
  autoStart?: boolean;
}) {
  const t = useTranslations("agents");
  const [steps, setSteps] = useState<AgentStep[]>([]);
  return (
    <Stack gap={2}>
      <DecisionControls
        episodeId={episodeId}
        recommendationId={recommendationId}
        goal={goal}
        role={role}
        autoStart={autoStart}
        onSteps={setSteps}
      />
      {(autoStart || steps.length > 0) && (
        <div>
          <Typography variant="subtitle1" component="h3" gutterBottom>
            {t("steps")}
          </Typography>
          <AgentSteps steps={steps} />
        </div>
      )}
    </Stack>
  );
}

function DecisionControls({
  episodeId,
  recommendationId,
  goal,
  role,
  autoStart,
  onSteps,
}: {
  episodeId: string;
  recommendationId: string;
  goal: Goal;
  role: string;
  autoStart: boolean;
  onSteps: (steps: AgentStep[]) => void;
}) {
  const t = useTranslations("workbench.decision");
  const tr = useTranslations("role");
  const [state, setState] = useState<State>({ phase: autoStart ? "loading" : "idle" });
  const [recorded, setRecorded] = useState<Decision | null>(null);
  const [dialog, setDialog] = useState<Decision | null>(null);
  const [text, setText] = useState("");

  useEffect(() => {
    if (state.phase !== "loading") return;
    let live = true;
    fetch("/api/workbench/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ episodeId, goal }),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("start");
        const run = (await response.json()) as Run;
        if (!live) return;
        onSteps(stepsOf(run.result?.steps));
        setState(run.interrupt ? { phase: "open", run } : { phase: "none" });
      })
      .catch(() => live && setState({ phase: "error", message: "failed" }));
    return () => {
      live = false;
    };
  }, [episodeId, goal, state.phase, onSteps]);

  async function decide(run: Run, decision: Decision) {
    const response = await fetch("/api/workbench/resume", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        runId: run.run_id,
        recommendationId: run.interrupt?.payload.recommendation_id ?? recommendationId,
        decision,
        editedPayload: decision === "edit" ? { comment: text } : undefined,
        reason: NEEDS_TEXT.has(decision) && decision !== "edit" ? text : undefined,
      }),
    });
    setDialog(null);
    setText("");
    if (!response.ok) {
      setState({ phase: "error", message: response.status === 403 ? "role" : "failed" });
      return;
    }
    const resumed = (await response.json().catch(() => null)) as Run | null;
    onSteps(stepsOf(resumed?.result?.steps));
    setRecorded(decision);
    setState(resumed?.interrupt ? { phase: "open", run: resumed } : { phase: "none" });
  }

  const done = recorded && (
    <Alert severity="success" data-testid="decision-recorded" sx={{ mb: 1 }}>
      {t("recorded", { decision: t(recorded) })}
    </Alert>
  );

  if (state.phase === "idle") {
    return (
      <div>
        <Button variant="outlined" onClick={() => setState({ phase: "loading" })}>
          {t(`start.${goal}`)}
        </Button>
      </div>
    );
  }
  if (state.phase === "loading") return <Typography color="text.secondary">{t("starting")}</Typography>;
  if (state.phase === "none") {
    return done || <Typography color="text.secondary">{t("none")}</Typography>;
  }
  if (state.phase === "error") {
    return <Alert severity="error">{state.message === "role" ? t("needsRole") : t("failed")}</Alert>;
  }
  const run = state.run;
  const interrupt = run.interrupt;
  const allowed = DECISIONS.filter((d) => interrupt?.allowed_decisions.includes(d));
  if (interrupt && interrupt.required_role !== role) {
    return (
      <>
        {done}
        <Alert severity="info" data-testid="decision-waiting">
          {t("waitingFor", { step: t(`step.${interrupt.kind}`), role: tr(interrupt.required_role) })}
        </Alert>
      </>
    );
  }
  return (
    <>
      {done}
      {interrupt && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t("yourStep", { step: t(`step.${interrupt.kind}`) })}
        </Typography>
      )}
      <Stack direction="row" gap={1} flexWrap="wrap" aria-label={t("title")} role="group">
        {allowed.map((d) => (
          <Button
            key={d}
            variant={PRIMARY.has(d) ? "contained" : "outlined"}
            color={DANGER.has(d) ? "error" : "primary"}
            onClick={() => (NEEDS_TEXT.has(d) ? setDialog(d) : decide(run, d))}
          >
            {t(d)}
          </Button>
        ))}
      </Stack>
      <Dialog open={dialog !== null} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle component="h2">{dialog && t(`dialog.${dialog}`)}</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={2}
            margin="dense"
            label={dialog === "edit" ? t("editLabel") : t("reasonLabel")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>{t("cancel")}</Button>
          <Button variant="contained" disabled={!text.trim()} onClick={() => dialog && decide(run, dialog)}>
            {t("confirm")}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
