import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { TwinDetail } from "@/components/twins/TwinDetail";
import { LinkButton } from "@/components/ui/LinkButton";
import { Page, PageHeader } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { getSession } from "@/lib/session";
import { isPersonTwin } from "@/lib/twins";

export default async function PersonTwinPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; dt: string }>;
  searchParams: Promise<{ variable?: string }>;
}) {
  const { locale, dt } = await params;
  const { variable } = await searchParams;
  setRequestLocale(locale);
  if (!isPersonTwin(dt)) notFound();
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (session.role !== "person" || !session.hdtId) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  return (
    <Page session={session}>
      <PageHeader
        overline={t("twinHome.title")}
        title={t(`twin.${dt}`)}
        actions={
          <LinkButton href="/twin" variant="outlined">
            {t("drill.back")}
          </LinkButton>
        }
      />
      <TwinDetail token={session.token} hdtId={session.hdtId} dt={dt} requested={variable} basePath={`/twin/${dt}`} />
    </Page>
  );
}
