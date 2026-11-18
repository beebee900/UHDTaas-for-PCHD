import Alert from "@mui/material/Alert";
import Card from "@mui/material/Card";
import CardActions from "@mui/material/CardActions";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations, setRequestLocale } from "next-intl/server";

import { LinkButton } from "@/components/ui/LinkButton";
import { Empty, Page, PageHeader, Section } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { episodesOf } from "@/lib/data";
import { homeOf, personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

export default async function CarePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (homeOf(session.role) !== "patient") return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const format = await getFormatter();
  const persons = personsOf(session);
  const lists = await Promise.all(persons.map((hdtId) => episodesOf(session, { hdtId, status: "all" })));
  const episodes = lists.flatMap((l) => l ?? []);
  return (
    <Page session={session}>
      <PageHeader
        overline={t(`facility.${session.tenantId ?? "fac-a"}`)}
        title={t("care.title")}
        description={t(session.role === "proxy" ? "care.aboutProxy" : "care.about")}
      />
      <Section id="episodes" title={t("care.episodes")}>
        {lists.every((l) => l === null) ? (
          <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
        ) : episodes.length ? (
          <Grid container spacing={2}>
            {episodes.map(({ episode: ep, patient }) => (
              <Grid key={ep.episode_id} size={{ xs: 12, md: 6 }}>
                <Card variant="outlined" sx={{ height: "100%" }}>
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between" gap={1} sx={{ mb: 1 }}>
                      <Typography variant="overline">{patient?.initials ?? ""}</Typography>
                      <Chip
                        size="small"
                        color={ep.status === "open" ? "success" : "default"}
                        label={t(`workbench.episodeStatus.${ep.status}`)}
                      />
                    </Stack>
                    <Typography variant="h6" component="h3">
                      {ep.reason}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t("care.since", {
                        date: format.dateTime(new Date(ep.opened_at), { dateStyle: "long" }),
                        clinician: ep.responsible_clinician,
                      })}
                    </Typography>
                  </CardContent>
                  <CardActions>
                    <LinkButton href={`/care/${ep.episode_id}`} variant="contained">
                      {t("care.open")}
                    </LinkButton>
                  </CardActions>
                </Card>
              </Grid>
            ))}
          </Grid>
        ) : (
          <Empty>{t("care.none")}</Empty>
        )}
      </Section>
    </Page>
  );
}
