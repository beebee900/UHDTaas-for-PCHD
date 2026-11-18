import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { EpisodeTable } from "@/components/episodes/EpisodeTable";
import { LinkButton } from "@/components/ui/LinkButton";
import { Empty, Page, PageHeader, Section, StatCard } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { auditOf, chainIntact, episodesOf, worklistOf } from "@/lib/data";
import { can, HOME_PATH, homeOf } from "@/lib/roles";
import { getSession, type Session } from "@/lib/session";

export default async function DashboardPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const home = homeOf(session.role);
  if (HOME_PATH[home] !== "/dashboard") return redirect({ href: HOME_PATH[home], locale });
  return (
    <Page session={session}>
      {home === "clinician" ? <ClinicianHome session={session} /> : <GovernanceHome session={session} />}
    </Page>
  );
}

async function ClinicianHome({ session }: { session: Session }) {
  const t = await getTranslations();
  const [worklist, episodes] = await Promise.all([worklistOf(session), episodesOf(session)]);
  const blocked = worklist?.filter((i) => i.priority === 1).length ?? 0;
  return (
    <>
      <PageHeader
        overline={t(`facility.${session.tenantId ?? "fac-a"}`)}
        title={t("home.title", { role: t(`role.${session.role}`) })}
        description={t(`home.intro.${session.role}`)}
        actions={
          can.createEpisode(session.role) && (
            <LinkButton href="/episodes/new" variant="contained">
              {t("nav.newEpisode")}
            </LinkButton>
          )
        }
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("home.openEpisodes")} value={episodes?.length ?? "–"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("home.worklistItems")} value={worklist?.length ?? "–"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("home.blocked")} value={blocked} hint={t("home.blockedHint")} />
        </Grid>
      </Grid>
      <Section id="worklist" title={t("dashboard.worklist")} description={t(`home.worklistAbout.${session.role}`)}>
        {worklist ? (
          worklist.length ? (
            <List dense disablePadding>
              {worklist.map((item) => (
                <ListItem key={item.item_id} divider sx={{ gap: 1, flexWrap: "wrap" }}>
                  <ListItemText primary={item.title} secondary={t(`worklistKind.${item.kind}`)} />
                  {item.priority === 1 && <Chip size="small" color="error" label={t("home.blockedChip")} />}
                  {(item.episode_id || item.hdt_id) && (
                    <LinkButton
                      size="small"
                      variant="outlined"
                      href={item.episode_id ? `/workbench/${item.episode_id}` : `/workbench/open/${item.hdt_id}`}
                      aria-label={t("dashboard.openFor", { title: item.title })}
                    >
                      {t("dashboard.open")}
                    </LinkButton>
                  )}
                </ListItem>
              ))}
            </List>
          ) : (
            <Empty>{t("dashboard.worklistEmpty")}</Empty>
          )
        ) : (
          <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
        )}
      </Section>
      <Section
        id="episodes"
        title={t("home.patients")}
        description={t("home.patientsAbout")}
        actions={<LinkButton href="/episodes" size="small">{t("home.allEpisodes")}</LinkButton>}
      >
        {episodes ? <EpisodeTable items={episodes} /> : <Alert severity="warning">{t("dashboard.unavailable")}</Alert>}
      </Section>
      <Section id="explore" title={t("home.explore")} description={t("home.exploreAbout")}>
        <Stack direction="row" gap={1} flexWrap="wrap">
          <LinkButton href="/system" variant="outlined">{t("nav.system")}</LinkButton>
          {can.readPopulation(session.role) && (
            <LinkButton href="/population" variant="outlined">{t("nav.population")}</LinkButton>
          )}
          {can.readAudit(session.role) && (
            <LinkButton href="/audit" variant="outlined">{t("nav.audit")}</LinkButton>
          )}
          {can.readModels(session.role) && (
            <LinkButton href="/models" variant="outlined">{t("nav.models")}</LinkButton>
          )}
        </Stack>
      </Section>
    </>
  );
}

async function GovernanceHome({ session }: { session: Session }) {
  const t = await getTranslations();
  const audit = await auditOf(session, { limit: 500 });
  const denied = audit?.filter((a) => a.outcome === "denied").length ?? 0;
  return (
    <>
      <PageHeader
        overline={t(`facility.${session.tenantId ?? "fac-a"}`)}
        title={t("home.title", { role: t(`role.${session.role}`) })}
        description={t(`home.intro.${session.role}`)}
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("audit.records")} value={audit?.length ?? "–"} hint={t("audit.recordsHint")} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("audit.denied")} value={denied} hint={t("audit.deniedHint")} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard
            label={t("audit.chain")}
            value={audit ? (chainIntact(audit) ? t("audit.intact") : t("audit.broken")) : "–"}
            hint={t("audit.chainHint")}
          />
        </Grid>
      </Grid>
      <Section id="governance" title={t("home.governanceTools")}>
        <Stack direction="row" gap={1} flexWrap="wrap">
          <LinkButton href="/audit" variant="contained">{t("nav.audit")}</LinkButton>
          <LinkButton href="/models" variant="outlined">{t("nav.models")}</LinkButton>
          {can.readPopulation(session.role) && (
            <LinkButton href="/population" variant="outlined">{t("nav.population")}</LinkButton>
          )}
          <LinkButton href="/system" variant="outlined">{t("nav.system")}</LinkButton>
        </Stack>
      </Section>
    </>
  );
}
