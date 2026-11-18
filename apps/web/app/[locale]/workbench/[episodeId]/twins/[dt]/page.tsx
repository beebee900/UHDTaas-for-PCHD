import Alert from "@mui/material/Alert";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { RunAgents } from "@/components/agents/RunAgents";
import { TwinDetail } from "@/components/twins/TwinDetail";
import { LinkButton } from "@/components/ui/LinkButton";
import { Page, Section } from "@/components/ui/Page";
import { EpisodeHeader } from "@/components/workbench/EpisodeHeader";
import { redirect } from "@/i18n/navigation";
import { episodeOf, patientOf } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";
import { isPersonTwin } from "@/lib/twins";

export default async function TwinPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; episodeId: string; dt: string }>;
  searchParams: Promise<{ variable?: string }>;
}) {
  const { locale, episodeId, dt } = await params;
  const { variable } = await searchParams;
  setRequestLocale(locale);
  if (!isPersonTwin(dt)) notFound();
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const t = await getTranslations();
  const ep = await episodeOf(session, episodeId);
  if (!ep) {
    return (
      <Page session={session}>
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      </Page>
    );
  }
  const patient = await patientOf(session, ep.hdt_id);
  return (
    <Page session={session}>
      <EpisodeHeader
        session={session}
        episode={ep}
        patient={patient}
        active="twins"
        title={t(`twin.${dt}`)}
        actions={
          <LinkButton href={`/workbench/${episodeId}/twins`} variant="outlined">
            {t("drill.back")}
          </LinkButton>
        }
      />
      <TwinDetail
        token={session.token}
        hdtId={ep.hdt_id}
        dt={dt}
        requested={variable}
        basePath={`/workbench/${episodeId}/twins/${dt}`}
        agents={
          <Section id="agents" title={t("agents.title")} description={t("agents.about")}>
            {can.runAgents(session.role) ? (
              <RunAgents episodeId={episodeId} twin={dt} />
            ) : (
              <Alert severity="info">{t("agents.needsRole")}</Alert>
            )}
          </Section>
        }
      />
    </Page>
  );
}
