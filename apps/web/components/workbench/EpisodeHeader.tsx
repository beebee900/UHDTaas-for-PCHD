import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import { getFormatter, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/ui/Page";
import type { components } from "@/lib/api/apdt";
import type { PatientEntry } from "@/lib/data";
import { can } from "@/lib/roles";
import type { Session } from "@/lib/session";

import { type WorkbenchTab, WorkbenchNav } from "./WorkbenchNav";

type Episode = components["schemas"]["Episode"];

export async function EpisodeHeader({
  session,
  episode: ep,
  patient,
  active,
  title,
  actions,
}: {
  session: Session;
  episode: Episode;
  patient: PatientEntry | null;
  active: WorkbenchTab;
  title: string;
  actions?: ReactNode;
}) {
  const t = await getTranslations();
  const format = await getFormatter();
  const tabs: WorkbenchTab[] = ["review", "twins"];
  if (can.converse(session.role)) tabs.push("ask");
  if (can.readAudit(session.role)) tabs.push("activity");
  const who = patient
    ? t("workbench.patientWho", {
        initials: patient.initials,
        sex: t(`sex.${patient.sex}`),
        age: patient.age_years,
        language: t(`locale.${patient.language}`),
      })
    : ep.hdt_id;
  return (
    <Stack gap={2}>
      <PageHeader overline={who} title={title} actions={actions}>
        <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1.5 }}>
          <Chip size="small" label={t("workbench.episode", { id: ep.episode_id })} />
          <Chip size="small" label={t("workbench.reason", { reason: ep.reason })} />
          <Chip size="small" label={t("workbench.clinician", { name: ep.responsible_clinician })} />
          <Chip
            size="small"
            label={t("workbench.openedAt", {
              time: format.dateTime(new Date(ep.opened_at), { dateStyle: "medium", timeStyle: "short" }),
            })}
          />
          <Chip
            size="small"
            color={ep.status === "open" ? "success" : "default"}
            label={t(`workbench.episodeStatus.${ep.status}`)}
          />
        </Stack>
      </PageHeader>
      <WorkbenchNav episodeId={ep.episode_id} active={active} tabs={tabs} />
    </Stack>
  );
}
