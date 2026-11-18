import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { LanguageStatus } from "@/components/ask/LanguageStatus";
import { Page, PageHeader, Section } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { AHDT_URL, APDT_URL } from "@/lib/api/client";
import { getSession } from "@/lib/session";
import { PERSON_TWINS } from "@/lib/twins";

const SERVICES: { key: string; url: string }[] = [
  { key: "apdt", url: APDT_URL },
  { key: "ahdt", url: AHDT_URL },
  { key: "population", url: process.env.ATRA_POPULATION_URL ?? "http://127.0.0.1:8110" },
  { key: "edge", url: process.env.ATRA_EDGE_URL ?? "http://127.0.0.1:8095" },
  { key: "channels", url: process.env.ATRA_CHANNELS_URL ?? "http://127.0.0.1:8300" },
  { key: "opa", url: process.env.ATRA_OPA_URL ?? "http://127.0.0.1:8181" },
];
const LAYERS = [1, 2, 3, 4, 5, 6, 7, 8] as const;
const STEPS = ["open", "intake", "reason", "agents", "decide", "verify", "explain", "twin"] as const;
const PERSONAS = ["ao", "bm", "cn", "de", "ef", "gh"] as const;
const AHDT_AGENTS = ["monitoring", "anomaly", "forecasting", "explanation", "recommendation", "orchestrator", "conductor"] as const;
const APDT_AGENTS = ["history", "evidence", "differential", "investigation", "treatment", "pharmacotherapy", "guard"] as const;

async function healthy(url: string): Promise<boolean> {
  const r = await fetch(`${url}/health`, { cache: "no-store", signal: AbortSignal.timeout(2500) }).catch(() => null);
  return Boolean(r?.ok);
}

export default async function SystemPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const t = await getTranslations();
  const health = await Promise.all(SERVICES.map((s) => healthy(s.url)));
  return (
    <Page session={session}>
      <PageHeader overline={t("system.overline")} title={t("system.title")} description={t("system.about")} />

      <Grid container spacing={2}>
        {(["ahdt", "apdt"] as const).map((twin) => (
          <Grid key={twin} size={{ xs: 12, md: 6 }}>
            <Paper variant="outlined" sx={{ p: 2.5, height: "100%" }}>
              <Typography variant="overline" color="primary" sx={{ fontWeight: 700 }}>
                {t(`system.twins.${twin}.short`)}
              </Typography>
              <Typography variant="h6" component="h2">
                {t(`system.twins.${twin}.name`)}
              </Typography>
              <Typography color="text.secondary">{t(`system.twins.${twin}.about`)}</Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>

      <Section id="workflow" title={t("system.workflow")} description={t("system.workflowAbout")}>
        <List disablePadding>
          {STEPS.map((step, i) => (
            <ListItem key={step} disableGutters divider sx={{ alignItems: "flex-start", gap: 2 }}>
              <Chip label={i + 1} color="primary" size="small" sx={{ mt: 0.5 }} />
              <ListItemText primary={t(`system.steps.${step}.title`)} secondary={t(`system.steps.${step}.about`)} />
            </ListItem>
          ))}
        </List>
      </Section>

      <Section id="layers" title={t("system.layers")} description={t("system.layersAbout")}>
        <Table size="small" aria-labelledby="layers">
          <TableBody>
            {[...LAYERS].reverse().map((n) => (
              <TableRow key={n}>
                <TableCell sx={{ width: 56, fontWeight: 700 }}>{n}</TableCell>
                <TableCell sx={{ width: "28%", fontWeight: 650 }}>{t(`system.layer.${n}.name`)}</TableCell>
                <TableCell>{t(`system.layer.${n}.about`)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section id="ahdt-agents" title={t("system.ahdtAgents")} description={t("system.ahdtAgentsAbout")}>
            <List dense disablePadding>
              {AHDT_AGENTS.map((a) => (
                <ListItem key={a} disableGutters>
                  <ListItemText primary={t(`system.agent.${a}.name`)} secondary={t(`system.agent.${a}.about`)} />
                </ListItem>
              ))}
            </List>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section id="apdt-agents" title={t("system.apdtAgents")} description={t("system.apdtAgentsAbout")}>
            <List dense disablePadding>
              {APDT_AGENTS.map((a) => (
                <ListItem key={a} disableGutters>
                  <ListItemText primary={t(`system.agent.${a}.name`)} secondary={t(`system.agent.${a}.about`)} />
                </ListItem>
              ))}
            </List>
          </Section>
        </Grid>
      </Grid>

      <Section id="safety" title={t("system.safety")} description={t("system.safetyAbout")}>
        <List dense disablePadding>
          {(["guard", "human", "consent", "audit"] as const).map((k) => (
            <ListItem key={k} disableGutters>
              <ListItemText primary={t(`system.safetyItem.${k}.name`)} secondary={t(`system.safetyItem.${k}.about`)} />
            </ListItem>
          ))}
        </List>
      </Section>

      <Section id="members" title={t("system.members")} description={t("system.membersAbout")}>
        <Grid container spacing={1.5}>
          {PERSON_TWINS.map((dt) => (
            <Grid key={dt} size={{ xs: 12, sm: 6, md: 4 }}>
              <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
                <Typography variant="subtitle2">{t(`twin.${dt}`)}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {t(`twinAbout.${dt}`)}
                </Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Section>

      <Section id="models" title={t("system.models")} description={t("system.modelsAbout")}>
        <Grid container spacing={2}>
          {(["T2", "T3", "T1"] as const).map((tier) => (
            <Grid key={tier} size={{ xs: 12, md: 4 }}>
              <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
                <Typography variant="h4" component="p" sx={{ fontWeight: 700 }}>
                  {t(`system.modelCount.${tier}`)}
                </Typography>
                <Typography variant="subtitle2">{t(`models.tier.${tier}`)}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {t(`models.tierAbout.${tier}`)}
                </Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Section>

      <LanguageStatus token={session.token} />

      <Section id="services" title={t("system.services")} description={t("system.servicesAbout")}>
        <Grid container spacing={1.5}>
          {SERVICES.map((s, i) => (
            <Grid key={s.key} size={{ xs: 12, sm: 6, md: 4 }}>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}>
                  <div>
                    <Typography variant="subtitle2">{t(`system.service.${s.key}.name`)}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t(`system.service.${s.key}.about`)}
                    </Typography>
                  </div>
                  <Chip size="small" color={health[i] ? "success" : "default"} label={health[i] ? t("system.up") : t("system.down")} />
                </Stack>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Section>

      <Section id="personas" title={t("system.personas")} description={t("system.personasAbout")}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("system.persona")}</TableCell>
              <TableCell>{t("system.facility")}</TableCell>
              <TableCell>{t("system.scenario")}</TableCell>
              <TableCell>{t("system.tests")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {PERSONAS.map((p) => (
              <TableRow key={p}>
                <TableCell sx={{ fontWeight: 650 }}>{t(`system.persona_.${p}.who`)}</TableCell>
                <TableCell>{t(`facility.${p === "de" || p === "gh" ? "fac-b" : "fac-a"}`)}</TableCell>
                <TableCell>{t(`system.persona_.${p}.scenario`)}</TableCell>
                <TableCell>{t(`system.persona_.${p}.shows`)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>
    </Page>
  );
}
