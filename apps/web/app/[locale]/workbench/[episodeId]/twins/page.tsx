import Alert from "@mui/material/Alert";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { RunAgents } from "@/components/agents/RunAgents";
import { Coupling } from "@/components/twins/Coupling";
import { Page, Section } from "@/components/ui/Page";
import { EpisodeHeader } from "@/components/workbench/EpisodeHeader";
import { TwinPanel, TwinPanelLoading } from "@/components/workbench/TwinPanel";
import { redirect } from "@/i18n/navigation";
import { episodeOf, patientOf, tenantOf } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

export default async function TwinsPage({
  params,
}: {
  params: Promise<{ locale: string; episodeId: string }>;
}) {
  const { locale, episodeId } = await params;
  setRequestLocale(locale);
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
      <EpisodeHeader session={session} episode={ep} patient={patient} active="twins" title={t("workbench.twins")} />
      <Section id="members" title={t("twins.members")} description={t("twins.membersAbout")}>
        <Suspense fallback={<TwinPanelLoading />}>
          <TwinPanel token={session.token} tenant={tenantOf(session)} episodeId={ep.episode_id} linked />
        </Suspense>
      </Section>
      <Section id="conductor" title={t("agents.conductorTitle")} description={t("twins.conductorAbout")}>
        {can.runAgents(session.role) ? (
          <RunAgents episodeId={ep.episode_id} conductor />
        ) : (
          <Alert severity="info">{t("agents.needsRole")}</Alert>
        )}
      </Section>
      <Section id="coupling" title={t("coupling.title")} description={t("coupling.about")}>
        <Suspense fallback={<TwinPanelLoading />}>
          <Coupling token={session.token} hdtId={ep.hdt_id} />
        </Suspense>
      </Section>
    </Page>
  );
}
