import Alert from "@mui/material/Alert";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AskTwin } from "@/components/ask/AskTwin";
import { LanguageStatus } from "@/components/ask/LanguageStatus";
import { Page, Section } from "@/components/ui/Page";
import { EpisodeHeader } from "@/components/workbench/EpisodeHeader";
import { redirect } from "@/i18n/navigation";
import { episodeOf, patientOf } from "@/lib/data";
import { getSession } from "@/lib/session";

export default async function AskPage({ params }: { params: Promise<{ locale: string; episodeId: string }> }) {
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
      <EpisodeHeader session={session} episode={ep} patient={patient} active="ask" title={t("ask.title")} />
      <Section id="chat" title={t("ask.chat")} description={t("ask.aboutClinician")}>
        <AskTwin episodeId={episodeId} />
      </Section>
      <LanguageStatus token={session.token} />
    </Page>
  );
}
