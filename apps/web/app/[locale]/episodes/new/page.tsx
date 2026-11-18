import Alert from "@mui/material/Alert";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { NewEpisodeForm } from "@/components/episodes/NewEpisodeForm";
import { Page, PageHeader } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

export default async function NewEpisodePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  if (!can.createEpisode(session.role)) return redirect({ href: "/dashboard", locale });
  const t = await getTranslations();
  const api = apdtClient(session.token);
  const path = { tenant_id: tenantOf(session) };
  const [patients, catalogue] = await Promise.all([
    api.GET("/v1/t/{tenant_id}/patients", { params: { path } }),
    api.GET("/v1/t/{tenant_id}/intake/catalogue", { params: { path } }),
  ]);
  return (
    <Page session={session}>
      <PageHeader
        overline={t(`facility.${session.tenantId ?? "fac-a"}`)}
        title={t("newEpisode.title")}
        description={t("newEpisode.about")}
      />
      {patients.data && catalogue.data ? (
        <NewEpisodeForm patients={patients.data} catalogue={catalogue.data} />
      ) : (
        <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
      )}
    </Page>
  );
}
