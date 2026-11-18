import Alert from "@mui/material/Alert";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AuditTable } from "@/components/audit/AuditTable";
import { Page, Section } from "@/components/ui/Page";
import { EpisodeHeader } from "@/components/workbench/EpisodeHeader";
import { redirect } from "@/i18n/navigation";
import { auditOf, episodeOf, patientOf } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

export default async function ActivityPage({ params }: { params: Promise<{ locale: string; episodeId: string }> }) {
  const { locale, episodeId } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!can.readAudit(session.role)) return redirect({ href: `/workbench/${episodeId}`, locale });
  const t = await getTranslations();
  const ep = await episodeOf(session, episodeId);
  if (!ep) {
    return (
      <Page session={session}>
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      </Page>
    );
  }
  const [patient, records] = await Promise.all([
    patientOf(session, ep.hdt_id),
    auditOf(session, { hdtId: ep.hdt_id, limit: 500 }),
  ]);
  return (
    <Page session={session}>
      <EpisodeHeader session={session} episode={ep} patient={patient} active="activity" title={t("audit.episodeTitle")} />
      <Section id="trail" title={t("audit.trail")} description={t("audit.episodeAbout")}>
        {records ? <AuditTable records={records} /> : <Alert severity="warning">{t("dashboard.unavailable")}</Alert>}
      </Section>
    </Page>
  );
}
