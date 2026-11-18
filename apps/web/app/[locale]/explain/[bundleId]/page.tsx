import Alert from "@mui/material/Alert";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { LinkButton } from "@/components/ui/LinkButton";
import { Page } from "@/components/ui/Page";
import { redirect } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";
import { getSession } from "@/lib/session";

export default async function ExplainPage({
  params,
}: {
  params: Promise<{ locale: string; bundleId: string }>;
}) {
  const { locale, bundleId } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const t = await getTranslations();
  const bundle = await apdtClient(session.token).GET("/v1/t/{tenant_id}/bundles/{bundle_id}", {
    params: {
      path: { tenant_id: (session.tenantId ?? "fac-a") as Tenant, bundle_id: bundleId },
      query: { audience: "patient" },
    },
  });
  const summary = bundle.data?.patient_summary;
  return (
    <Page session={session}>
      <Stack gap={3} sx={{ maxWidth: 720, mx: "auto", width: "100%" }}>
        <Typography variant="h4" component="h1">
          {t("explain.title")}
        </Typography>
        {summary ? (
          <Paper variant="outlined" sx={{ p: 3 }}>
            <Typography variant="h5" component="p" lang={summary.language} data-testid="patient-summary">
              {summary.text}
            </Typography>
            {summary.language !== locale && (
              <Typography color="text.secondary" sx={{ mt: 2 }}>
                {t("explain.shownIn", { language: t(`locale.${summary.language}`) })}
              </Typography>
            )}
          </Paper>
        ) : (
          <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
        )}
        <div>
          <LinkButton href="/dashboard" variant="outlined">
            {t("workbench.back")}
          </LinkButton>
        </div>
      </Stack>
    </Page>
  );
}
