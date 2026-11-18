import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { EpisodeTable } from "@/components/episodes/EpisodeTable";
import { LinkButton, LinkChip } from "@/components/ui/LinkButton";
import { Page, PageHeader, Section } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { episodesOf } from "@/lib/data";
import { can, CLINICIANS } from "@/lib/roles";
import { getSession } from "@/lib/session";

const STATUSES = ["open", "closed", "all"] as const;

export default async function EpisodesPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ status?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!CLINICIANS.has(session.role)) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const requested = (await searchParams).status;
  const status = STATUSES.find((s) => s === requested) ?? "open";
  const episodes = await episodesOf(session, { status });
  return (
    <Page session={session}>
      <PageHeader
        overline={t(`facility.${session.tenantId ?? "fac-a"}`)}
        title={t("episodes.title")}
        description={t("episodes.about")}
        actions={
          can.createEpisode(session.role) && (
            <LinkButton href="/episodes/new" variant="contained">
              {t("nav.newEpisode")}
            </LinkButton>
          )
        }
      />
      <Section
        id="list"
        title={t(`episodes.filter.${status}`)}
        actions={
          <Stack direction="row" gap={1}>
            {STATUSES.map((s) => (
              <LinkChip
                key={s}
                href={`/episodes?status=${s}`}
                label={t(`episodes.filter.${s}`)}
                color={s === status ? "primary" : "default"}
              />
            ))}
          </Stack>
        }
      >
        {episodes ? <EpisodeTable items={episodes} /> : <Alert severity="warning">{t("dashboard.unavailable")}</Alert>}
      </Section>
    </Page>
  );
}
