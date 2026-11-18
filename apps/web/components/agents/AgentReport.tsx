"use client";

import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { AgentSteps } from "@/components/agents/AgentSteps";
import type { AgentReportData } from "@/lib/agents";
import { titleOf } from "@/lib/clinical";

const COLOURS = { met: "success", unmet: "error", not_evaluated: "default" } as const;

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <Typography variant="subtitle1" component="h3" gutterBottom>
        {title}
      </Typography>
      {children}
    </div>
  );
}

export function AgentReport({ report }: { report: AgentReportData }) {
  const t = useTranslations("agents");
  const status = (value: string) =>
    t.has(`goalStatus.${value}`) ? t(`goalStatus.${value}`) : value;
  return (
    <Stack gap={2} data-testid="agent-report">
      {report.notes.map((note) => (
        <Alert key={note} severity="info">
          {note}
        </Alert>
      ))}
      <Part title={t("goals")}>
        {report.goals.length ? (
          <List dense disablePadding>
            {report.goals.map((goal) => (
              <ListItem key={goal.id} disableGutters sx={{ gap: 1, alignItems: "flex-start" }} data-testid="agent-goal">
                <Chip
                  size="small"
                  color={COLOURS[goal.status as keyof typeof COLOURS] ?? "default"}
                  variant={goal.status === "not_evaluated" ? "outlined" : "filled"}
                  label={status(goal.status)}
                  data-testid="goal-status"
                />
                <ListItemText primary={goal.text ?? goal.id} secondary={goal.detail} />
              </ListItem>
            ))}
          </List>
        ) : (
          <Typography color="text.secondary">{t("noGoals")}</Typography>
        )}
      </Part>
      <Part title={t("steps")}>
        <AgentSteps steps={report.steps} testId="report-steps" />
      </Part>
      <Part title={t("toolCalls")}>
        {report.toolCalls.length ? (
          <Typography variant="body2">{report.toolCalls.join(", ")}</Typography>
        ) : (
          <Typography color="text.secondary">{t("noToolCalls")}</Typography>
        )}
      </Part>
      <Part title={t("proposals")}>
        {report.proposals.length ? (
          <List dense disablePadding>
            {report.proposals.map((rec) => (
              <ListItem key={rec.recommendation_id} disableGutters>
                <ListItemText primary={titleOf(rec)} secondary={rec.kind} />
              </ListItem>
            ))}
          </List>
        ) : (
          <Typography color="text.secondary">{t("noProposals")}</Typography>
        )}
      </Part>
      {report.explanations.length > 0 && (
        <Part title={t("explanations")}>
          <List dense disablePadding>
            {report.explanations.map((text) => (
              <ListItem key={text} disableGutters>
                <ListItemText primary={text} />
              </ListItem>
            ))}
          </List>
        </Part>
      )}
      <Part title={t("denials")}>
        {report.denials.length ? (
          <List dense disablePadding>
            {report.denials.map((d, i) => (
              <ListItem key={`${d.agent}-${d.action}-${i}`} disableGutters>
                <ListItemText primary={`${d.agent}: ${d.action}`} secondary={d.reason} />
              </ListItem>
            ))}
          </List>
        ) : (
          <Typography color="text.secondary">{t("noDenials")}</Typography>
        )}
      </Part>
      {report.missing.length > 0 && (
        <Alert severity="warning">{t("missing", { items: report.missing.join(", ") })}</Alert>
      )}
    </Stack>
  );
}
