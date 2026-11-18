import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AskTwin } from "@/components/ask/AskTwin";
import { ConsentForm, MessageForm, PreferencesForm } from "@/components/care/CareForms";
import { Empty, Page, PageHeader, Section } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import { withheldCategories } from "@/lib/consent";
import { episodeOf, tenantOf } from "@/lib/data";
import { homeOf, personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

type Rendered = {
  render: {
    title: string;
    items: { linkId: string; type: string; text: string; depth: number; required: boolean; options?: { code: string; display: string }[] }[];
  };
};

const STATUS_COLOUR = { proposed: "default", accepted: "success", edited: "info", signed: "success", overridden: "warning", declined: "error" } as const;

export default async function CareEpisodePage({ params }: { params: Promise<{ locale: string; episodeId: string }> }) {
  const { locale, episodeId } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (homeOf(session.role) !== "patient") return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const ep = await episodeOf(session, episodeId);
  if (!ep || !personsOf(session).includes(ep.hdt_id)) {
    return (
      <Page session={session}>
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      </Page>
    );
  }
  const api = apdtClient(session.token);
  const tenant_id = tenantOf(session);
  const [recs, consent, prefs] = await Promise.all([
    api.GET("/v1/t/{tenant_id}/episodes/{episode_id}/recommendations", { params: { path: { tenant_id, episode_id: episodeId } } }),
    api.GET("/v1/t/{tenant_id}/patients/{hdt_id}/consent", { params: { path: { tenant_id, hdt_id: ep.hdt_id } } }),
    api.GET("/v1/t/{tenant_id}/questionnaires/{qid}", { params: { path: { tenant_id, qid: "preferences" } } }),
  ]);
  const explained = await Promise.all(
    (recs.data ?? []).map(async (rec) => {
      const bundle = rec.bundle_id
        ? await api.GET("/v1/t/{tenant_id}/bundles/{bundle_id}", {
            params: { path: { tenant_id, bundle_id: rec.bundle_id }, query: { audience: "patient" } },
          })
        : null;
      return { rec, summary: bundle?.data?.patient_summary };
    }),
  );
  const questionnaire = (prefs.data as Rendered | undefined)?.render;
  return (
    <Page session={session}>
      <PageHeader overline={t(`facility.${ep.tenant_id}`)} title={ep.reason} description={t("care.episodeAbout")}>
        <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
          <Chip size="small" color={ep.status === "open" ? "success" : "default"} label={t(`workbench.episodeStatus.${ep.status}`)} />
          <Chip size="small" label={t("workbench.clinician", { name: ep.responsible_clinician })} />
        </Stack>
      </PageHeader>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Stack gap={2}>
            <Section id="results" title={t("explain.title")} description={t("care.resultsAbout")}>
              {explained.length ? (
                <List disablePadding>
                  {explained.map(({ rec, summary }) => (
                    <ListItem key={rec.recommendation_id} divider disableGutters sx={{ gap: 1, alignItems: "flex-start" }}>
                      <ListItemText
                        primary={summary?.text ?? t(`care.kind.${rec.kind}`)}
                        secondary={t(`care.kind.${rec.kind}`)}
                        slotProps={{ primary: { lang: summary?.language } }}
                      />
                      <Chip size="small" color={STATUS_COLOUR[rec.status]} label={t(`care.status.${rec.status}`)} />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Empty>{t("care.noResults")}</Empty>
              )}
            </Section>
            <Section id="ask" title={t("ask.titleOwn")} description={t("ask.aboutPatient")}>
              <AskTwin hdtId={ep.hdt_id} />
            </Section>
            <Section id="message" title={t("message.title")} description={t("message.about")}>
              <MessageForm hdtId={ep.hdt_id} />
            </Section>
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <Stack gap={2}>
            <Section id="consent" title={t("consent.title")} description={t("consent.about")}>
              {consent.data ? (
                <ConsentForm
                  hdtId={ep.hdt_id}
                  purposes={consent.data.purposes}
                  withheld={withheldCategories(consent.data.refused_tools)}
                />
              ) : (
                <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
              )}
            </Section>
            <Section id="preferences" title={t("preferences.title")} description={t("preferences.about")}>
              {questionnaire ? (
                <PreferencesForm hdtId={ep.hdt_id} title={questionnaire.title} items={questionnaire.items} />
              ) : (
                <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
              )}
            </Section>
          </Stack>
        </Grid>
      </Grid>
    </Page>
  );
}
