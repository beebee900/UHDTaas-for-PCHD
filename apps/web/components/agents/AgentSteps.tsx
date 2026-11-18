"use client";

import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";

import type { AgentStep } from "@/lib/agents";

const words = (name: string) => name.replace(/_/g, " ");

export function AgentSteps({ steps, testId = "agent-steps" }: { steps: AgentStep[]; testId?: string }) {
  const t = useTranslations("agents");
  if (!steps.length) return <Typography color="text.secondary">{t("noSteps")}</Typography>;
  return (
    <List dense disablePadding data-testid={testId}>
      {steps.map((step, index) => (
        <ListItem key={`${step.node}-${index}`} disableGutters data-testid="agent-step">
          <ListItemText
            disableTypography
            primary={
              <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
                <Typography variant="body2" fontWeight={600}>
                  {index + 1}. {words(step.node)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {step.agent}
                </Typography>
                {step.status && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={t.has(`stepStatus.${step.status}`) ? t(`stepStatus.${step.status}`) : step.status}
                  />
                )}
              </Stack>
            }
            secondary={
              <>
                <Typography variant="body2" color="text.secondary" component="span" display="block">
                  {step.tools.length
                    ? t("tools", { tools: step.tools.join(", ") })
                    : t("noTools")}
                </Typography>
                {step.missing.length > 0 && (
                  <Typography variant="body2" color="warning.main" component="span" display="block">
                    {t("missing", { items: step.missing.join(", ") })}
                  </Typography>
                )}
              </>
            }
          />
        </ListItem>
      ))}
    </List>
  );
}
