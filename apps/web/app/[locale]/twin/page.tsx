import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { AskTwin } from "@/components/ask/AskTwin";
import { Coupling } from "@/components/twins/Coupling";
import { PersonTwinGrid } from "@/components/twins/PersonTwinGrid";
import { Page, PageHeader, Section } from "@/components/ui/Page";
import { TwinPanelLoading } from "@/components/workbench/TwinPanel";
import { redirect } from "@/i18n/navigation";
import { getSession } from "@/lib/session";

export default async function TwinHome({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (session.role !== "person" || !session.hdtId) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const hdtId = session.hdtId;
  return (
    <Page session={session}>
      <PageHeader
        overline={t("twinHome.overline")}
        title={t("twinHome.title")}
        description={t("twinHome.about")}
        actions={
          <Button variant="outlined" href={`/api/phkg?hdt=${encodeURIComponent(hdtId)}`}>
            {t("twinHome.download")}
          </Button>
        }
      />
      <Alert severity="info">{t("twinHome.lifelong")}</Alert>
      <Section id="members" title={t("twins.members")} description={t("twins.membersAbout")}>
        <Suspense fallback={<TwinPanelLoading />}>
          <PersonTwinGrid token={session.token} hdtId={hdtId} basePath="/twin" />
        </Suspense>
      </Section>
      <Section id="ask" title={t("ask.titleOwn")} description={t("ask.aboutPerson")}>
        <AskTwin hdtId={hdtId} />
      </Section>
      <Section id="coupling" title={t("coupling.title")} description={t("coupling.about")}>
        <Suspense fallback={<TwinPanelLoading />}>
          <Coupling token={session.token} hdtId={hdtId} />
        </Suspense>
      </Section>
    </Page>
  );
}
