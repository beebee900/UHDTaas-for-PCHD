import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { LinkButton } from "@/components/ui/LinkButton";
import { Empty, Page, Section } from "@/components/ui/Page";
import { DecisionBar } from "@/components/workbench/DecisionBar";
import { EpisodeActions } from "@/components/workbench/EpisodeActions";
import { EpisodeHeader } from "@/components/workbench/EpisodeHeader";
import { RecordEntries } from "@/components/workbench/RecordEntries";
import { CareGivenSheet, DiagnosisSheet, DispenseSheet } from "@/components/workbench/RecordSheets";
import { SourceChip } from "@/components/workbench/SourceChip";
import { TwinPanel, TwinPanelLoading } from "@/components/workbench/TwinPanel";
import { WhyPanel } from "@/components/workbench/WhyPanel";
import { redirect } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import {
  type Bundle,
  type ClinicalEntry,
  percent,
  prescribedOf,
  probabilityOf,
  type Recommendation,
  safetyIssuesOf,
  titleOf,
} from "@/lib/clinical";
import { patientOf, tenantOf } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

const TREATMENT_ROLES = new Set(["medical_officer", "pharmacist"]);
const CARE_ROLES = new Set(["medical_officer", "nurse"]);

export default async function WorkbenchPage({
  params,
}: {
  params: Promise<{ locale: string; episodeId: string }>;
}) {
  const { locale, episodeId } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const t = await getTranslations();
  const format = await getFormatter();
  const api = apdtClient(session.token);
  const tenant_id = tenantOf(session);
  const path = { tenant_id, episode_id: episodeId };

  const [episode, recs, unified, record] = await Promise.all([
    api.GET("/v1/t/{tenant_id}/episodes/{episode_id}", { params: { path } }),
    api.GET("/v1/t/{tenant_id}/episodes/{episode_id}/recommendations", { params: { path } }),
    api.GET("/v1/t/{tenant_id}/episodes/{episode_id}/unified-view", { params: { path } }),
    api.GET("/v1/t/{tenant_id}/episodes/{episode_id}/record", { params: { path } }),
  ]);
  if (!episode.data) {
    return (
      <Page session={session}>
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      </Page>
    );
  }
  const ep = episode.data.episode;
  const patient = await patientOf(session, ep.hdt_id);
  const recommendations: Recommendation[] = recs.data ?? [];
  const bundles = new Map<string, Bundle>();
  await Promise.all(
    recommendations.flatMap((rec) =>
      rec.bundle_id
        ? [
            api
              .GET("/v1/t/{tenant_id}/bundles/{bundle_id}", {
                params: { path: { tenant_id, bundle_id: rec.bundle_id } },
              })
              .then((b) => {
                if (b.data && rec.bundle_id) bundles.set(rec.bundle_id, b.data);
              }),
          ]
        : [],
    ),
  );

  const of = (kind: string) => recommendations.filter((r) => r.kind === kind);
  const diagnoses = of("diagnosis");
  const tests = of("test");
  const treatments = of("treatment");
  const care = of("care");
  const top = diagnoses[0];
  const decidedDiagnosis = diagnoses.some((r) => r.status === "proposed") ? undefined : diagnoses.at(-1);
  const probability = top ? probabilityOf(top) : null;
  const topBundle = top?.bundle_id ? bundles.get(top.bundle_id) : undefined;
  const missing = [...(unified.data?.missing_evidence ?? [])];
  const degraded = Boolean(unified.data?.degraded);
  const entries: ClinicalEntry[] = record.data ?? [];
  const entriesOf = (kind: ClinicalEntry["kind"]) => entries.filter((e) => e.kind === kind);
  const isOpen = ep.status === "open";
  const proposals = top
    ? [
        { text: titleOf(top), recommendationId: top.recommendation_id },
        ...(topBundle?.alternatives ?? []).map((alt) => ({ text: alt.text, recommendationId: null })),
      ]
    : [];
  const activities = care.flatMap((rec) => {
    const monitoring = (rec.payload as { monitoring?: unknown }).monitoring;
    return Array.isArray(monitoring)
      ? monitoring.flatMap((m) => (typeof m === "string" ? [m] : typeof m?.text === "string" ? [m.text as string] : []))
      : [];
  });
  const timeOf = (iso?: string | null) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "short", timeStyle: "short" }) : "";

  return (
    <Page session={session}>
      <EpisodeHeader
        session={session}
        episode={ep}
        patient={patient}
        active="review"
        title={t("workbench.title")}
        actions={
          can.decide(session.role) && ep.status === "open" && <EpisodeActions episodeId={ep.episode_id} tenant={tenant_id} />
        }
      />

      <Typography color="text.secondary">{t("workbench.about")}</Typography>

      {degraded && (
        <Alert severity="warning" data-testid="degraded-banner">
          <AlertTitle>{t("workbench.degradedTitle")}</AlertTitle>
          {t("workbench.degraded")}
          {missing.length > 0 && ` ${t("workbench.missing", { items: missing.join(", ") })}`}
        </Alert>
      )}

      {!recommendations.length && (
        <Alert severity="info">
          <AlertTitle>{t("workbench.noRecsTitle")}</AlertTitle>
          {t("workbench.noRecs")}
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Stack gap={2}>
            <Section id="differential" title={t("workbench.differential")} description={t("workbench.differentialAbout")}>
              {top ? (
                <List dense disablePadding>
                  <ListItem disableGutters sx={{ gap: 1, flexWrap: "wrap" }}>
                    <ListItemText
                      primary={titleOf(top)}
                      secondary={probability === null ? undefined : t("workbench.probability", { value: percent(probability) })}
                    />
                    {topBundle && <WhyPanel bundle={topBundle} />}
                  </ListItem>
                  {topBundle?.alternatives.map((alt) => (
                    <ListItem key={alt.text} disableGutters>
                      <ListItemText
                        primary={alt.text}
                        secondary={`${t("workbench.probability", { value: percent(alt.score) })}. ${alt.why_lower}`}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Empty>{t("workbench.noDifferential")}</Empty>
              )}
            </Section>

            <Section id="tests" title={t("workbench.tests")} description={t("workbench.testsAbout")}>
              {tests.length ? <RecommendationList items={tests} bundles={bundles} /> : <Empty>{t("workbench.noTests")}</Empty>}
            </Section>

            <Section id="treatments" title={t("workbench.treatments")} description={t("workbench.treatmentsAbout")}>
              {treatments.length ? (
                <RecommendationList items={treatments} bundles={bundles} showSafety />
              ) : (
                <Empty>{t("workbench.noTreatments")}</Empty>
              )}
              {treatments[0] && TREATMENT_ROLES.has(session.role) && (
                <Stack sx={{ mt: 2 }}>
                  <DecisionBar
                    episodeId={ep.episode_id}
                    recommendationId={treatments[0].recommendation_id}
                    goal="treatment"
                    role={session.role}
                    autoStart={false}
                  />
                </Stack>
              )}
            </Section>

            <Section id="dispensing" title={t("record.dispensing")} description={t("record.dispensingAbout")}>
              <Stack gap={2}>
                {session.role === "pharmacist" && isOpen && (
                  <DispenseSheet episodeId={ep.episode_id} prescribed={prescribedOf(treatments)} />
                )}
                <RecordEntries entries={entriesOf("dispense")} empty={t("record.noDispense")} />
              </Stack>
            </Section>

            <Section id="care" title={t("workbench.care")} description={t("workbench.careAbout")}>
              {care.length ? <RecommendationList items={care} bundles={bundles} /> : <Empty>{t("workbench.noCare")}</Empty>}
              {care[0] && CARE_ROLES.has(session.role) && (
                <Stack sx={{ mt: 2 }}>
                  <DecisionBar
                    episodeId={ep.episode_id}
                    recommendationId={care[0].recommendation_id}
                    goal="care"
                    role={session.role}
                    autoStart={false}
                  />
                </Stack>
              )}
            </Section>

            <Section id="care-given" title={t("record.careGiven")} description={t("record.careGivenAbout")}>
              <Stack gap={2}>
                {session.role === "nurse" && isOpen && (
                  <CareGivenSheet
                    episodeId={ep.episode_id}
                    prescribed={prescribedOf([...treatments, ...care])}
                    activities={activities}
                  />
                )}
                <RecordEntries entries={entriesOf("administration")} empty={t("record.noCareGiven")} />
              </Stack>
            </Section>
          </Stack>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Stack gap={2}>
            <Section id="decision" title={t("workbench.decision.title")} description={t("workbench.decisionAbout")}>
              {decidedDiagnosis ? (
                <Alert severity="success" data-testid="decision-recorded">
                  {t("workbench.decision.recorded", { decision: t(`workbench.recStatus.${decidedDiagnosis.status}`) })}
                </Alert>
              ) : top && can.decide(session.role) ? (
                <DecisionBar
                  episodeId={ep.episode_id}
                  recommendationId={top.recommendation_id}
                  goal="diagnosis"
                  role={session.role}
                />
              ) : (
                <Empty>{top ? t("workbench.decision.onlyMo") : t("workbench.decision.none")}</Empty>
              )}
              {topBundle && (
                <LinkButton href={`/explain/${topBundle.bundle_id}`} sx={{ mt: 2 }}>
                  {t("workbench.patientExplanation")}
                </LinkButton>
              )}
            </Section>

            <Section id="diagnosis-sheet" title={t("record.diagnosisSheet")} description={t("record.diagnosisSheetAbout")}>
              <Stack gap={2}>
                {session.role === "medical_officer" && isOpen && (
                  <DiagnosisSheet episodeId={ep.episode_id} proposals={proposals} />
                )}
                <RecordEntries entries={entriesOf("diagnosis")} empty={t("record.noDiagnosis")} />
              </Stack>
            </Section>

            <Section id="unified" title={t("workbench.unified")} description={t("workbench.unifiedAbout")}>
              {unified.data?.items.length ? (
                <List dense disablePadding>
                  {unified.data.items.map((item) => (
                    <ListItem key={`${item.source}-${item.label}-${item.time}`} disableGutters sx={{ gap: 1 }}>
                      <SourceChip source={item.source} label={t(`workbench.source.${item.source}`)} />
                      <ListItemText
                        primary={`${item.label}: ${String(item.value ?? "")}${item.unit ? ` ${item.unit}` : ""}`}
                        secondary={timeOf(item.time)}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Empty>{t("workbench.noUnified")}</Empty>
              )}
            </Section>
          </Stack>
        </Grid>
      </Grid>

      <Section
        id="twins-heading"
        title={t("workbench.twins")}
        description={t("workbench.twinsAbout")}
        actions={
          <LinkButton href={`/workbench/${ep.episode_id}/twins`} size="small" variant="outlined">
            {t("workbench.openTwinsAndAgents")}
          </LinkButton>
        }
      >
        <Suspense fallback={<TwinPanelLoading />}>
          <TwinPanel token={session.token} tenant={tenant_id} episodeId={ep.episode_id} linked />
        </Suspense>
      </Section>
    </Page>
  );
}

async function RecommendationList({
  items,
  bundles,
  showSafety = false,
}: {
  items: Recommendation[];
  bundles: Map<string, Bundle>;
  showSafety?: boolean;
}) {
  const t = await getTranslations("workbench");
  return (
    <List dense disablePadding>
      {items.map((rec) => {
        const bundle = rec.bundle_id ? bundles.get(rec.bundle_id) : undefined;
        const issues = safetyIssuesOf(rec);
        return (
          <ListItem key={rec.recommendation_id} disableGutters sx={{ gap: 1, flexWrap: "wrap" }}>
            <ListItemText
              primary={titleOf(rec)}
              secondary={
                showSafety
                  ? issues.length
                    ? issues.map((i) => (i.severity ? `${i.severity}: ${i.text}` : i.text)).join("; ")
                    : t("noSafetyIssues")
                  : t(`recStatus.${rec.status}`)
              }
            />
            {bundle && <WhyPanel bundle={bundle} />}
          </ListItem>
        );
      })}
    </List>
  );
}
