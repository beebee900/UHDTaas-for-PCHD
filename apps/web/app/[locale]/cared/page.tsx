import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { AskTwin } from "@/components/ask/AskTwin";
import { Readings } from "@/components/twins/Readings";
import { Empty, Page, PageHeader, Section } from "@/components/ui/Page";
import { TwinPanelLoading } from "@/components/workbench/TwinPanel";
import { redirect } from "@/i18n/navigation";
import { getSession } from "@/lib/session";

export default async function CaredPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (session.role !== "carer") return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  return (
    <Page session={session}>
      <PageHeader overline={t("role.carer")} title={t("cared.title")} description={t("cared.about")} />
      {session.carerFor.length === 0 && <Empty>{t("cared.none")}</Empty>}
      {session.carerFor.map((hdtId, i) => (
        <Section
          key={hdtId}
          id={`person-${i}`}
          title={t("cared.person", { n: i + 1 })}
          description={t("cared.personAbout")}
        >
          <Suspense fallback={<TwinPanelLoading />}>
            <Readings token={session.token} hdtId={hdtId} />
          </Suspense>
        </Section>
      ))}
      {session.carerFor[0] && (
        <Section id="ask" title={t("ask.title")} description={t("ask.aboutCarer")}>
          <AskTwin hdtId={session.carerFor[0]} />
        </Section>
      )}
    </Page>
  );
}
