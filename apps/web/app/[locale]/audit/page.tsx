import Alert from "@mui/material/Alert";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AuditTable } from "@/components/audit/AuditTable";
import { LinkChip } from "@/components/ui/LinkButton";
import { Page, PageHeader, Section, StatCard } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { auditOf, chainIntact } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

const FILTERS = ["all", "denied"] as const;

export default async function AuditPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ show?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!can.readAudit(session.role)) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const requested = (await searchParams).show;
  const show = FILTERS.find((f) => f === requested) ?? "all";
  const records = await auditOf(session, { limit: 1000 });
  const denied = records?.filter((r) => r.outcome === "denied") ?? [];
  const agents = records?.filter((r) => r.agent || r.action.startsWith("agent.")) ?? [];
  return (
    <Page session={session}>
      <PageHeader overline={t(`facility.${session.tenantId ?? "fac-a"}`)} title={t("audit.title")} description={t("audit.about")} />
      {records ? (
        <>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 3 }}>
              <StatCard label={t("audit.records")} value={records.length} hint={t("audit.recordsHint")} />
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <StatCard label={t("audit.denied")} value={denied.length} hint={t("audit.deniedHint")} />
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <StatCard label={t("audit.agentActions")} value={agents.length} hint={t("audit.agentHint")} />
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <StatCard
                label={t("audit.chain")}
                value={chainIntact(records) ? t("audit.intact") : t("audit.broken")}
                hint={t("audit.chainHint")}
              />
            </Grid>
          </Grid>
          <Section
            id="records"
            title={t(`audit.show.${show}`)}
            actions={
              <Stack direction="row" gap={1}>
                {FILTERS.map((f) => (
                  <LinkChip key={f} href={`/audit?show=${f}`} label={t(`audit.show.${f}`)} color={f === show ? "primary" : "default"} />
                ))}
              </Stack>
            }
          >
            <AuditTable records={show === "denied" ? denied : records} />
          </Section>
        </>
      ) : (
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      )}
    </Page>
  );
}
