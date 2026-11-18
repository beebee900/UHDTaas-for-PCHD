import { getTranslations, setRequestLocale } from "next-intl/server";

import { PopulationTools } from "@/components/population/PopulationTools";
import { Page, PageHeader } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

export default async function PopulationPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!can.readPopulation(session.role)) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  return (
    <Page session={session}>
      <PageHeader overline={t("twin.population")} title={t("population.title")} description={t("population.about")} />
      <PopulationTools cohort={can.extractCohort(session.role)} />
    </Page>
  );
}
