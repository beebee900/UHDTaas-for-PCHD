import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ModelActions } from "@/components/models/ModelActions";
import { Page, PageHeader, Section, StatCard } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { ahdtClient } from "@/lib/api/client";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

type Model = { model_id: string; version: string; twin: string; tier: string; stage: string | null };

const STAGE_COLOUR: Record<string, "success" | "info" | "default"> = { Production: "success", Staging: "info" };

export default async function ModelsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!can.readModels(session.role)) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const r = await ahdtClient(session.token).GET("/v1/models", { params: { query: {} } });
  const models = (r.data ?? []) as unknown as Model[];
  const tiers = ["T1", "T2", "T3"].map((tier) => ({ tier, count: models.filter((m) => m.tier === tier).length }));
  const stager = can.stageModels(session.role);
  const twin = (dt: string) => (t.has(`twin.${dt}`) ? t(`twin.${dt}`) : dt);
  return (
    <Page session={session}>
      <PageHeader overline={t("models.overline")} title={t("models.title")} description={t("models.about")} />
      {r.data ? (
        <>
          <Grid container spacing={2}>
            {tiers.map(({ tier, count }) => (
              <Grid key={tier} size={{ xs: 12, sm: 4 }}>
                <StatCard label={t(`models.tier.${tier}`)} value={count} hint={t(`models.tierAbout.${tier}`)} />
              </Grid>
            ))}
          </Grid>
          <Section id="registry" title={t("models.registry")} description={stager ? t("models.stagerAbout") : t("models.viewerAbout")}>
            <TableContainer sx={{ maxHeight: 720 }}>
              <Table size="small" stickyHeader aria-label={t("models.registry")}>
                <TableHead>
                  <TableRow>
                    <TableCell>{t("models.model")}</TableCell>
                    <TableCell>{t("models.twin")}</TableCell>
                    <TableCell>{t("models.tierLabel")}</TableCell>
                    <TableCell>{t("models.stage")}</TableCell>
                    {stager && <TableCell align="right">{t("models.actions")}</TableCell>}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {models.map((m) => (
                    <TableRow key={`${m.model_id}-${m.version}`} hover>
                      <TableCell sx={{ wordBreak: "break-all" }}>
                        {m.model_id} <Chip size="small" variant="outlined" label={`v${m.version}`} sx={{ ml: 0.5 }} />
                      </TableCell>
                      <TableCell>{twin(m.twin)}</TableCell>
                      <TableCell>{m.tier}</TableCell>
                      <TableCell>
                        <Chip size="small" color={STAGE_COLOUR[m.stage ?? ""] ?? "default"} label={t(`models.stages.${m.stage ?? "None"}`)} />
                      </TableCell>
                      {stager && (
                        <TableCell align="right">
                          <ModelActions modelId={m.model_id} version={m.version} stage={m.stage ?? "None"} />
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Section>
        </>
      ) : (
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      )}
    </Page>
  );
}
