import { setRequestLocale } from "next-intl/server";

import { redirect } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";
import { getSession } from "@/lib/session";

// Opens a care episode for a worklist person and continues to its workbench.
export default async function OpenWorkbench({
  params,
}: {
  params: Promise<{ locale: string; hdtId: string }>;
}) {
  const { locale, hdtId } = await params;
  setRequestLocale(locale);
  const session = await getSession();
  if (!session) return redirect({ href: "/login", locale });
  const created = await apdtClient(session.token).POST("/v1/t/{tenant_id}/episodes", {
    params: { path: { tenant_id: (session.tenantId ?? "fac-a") as Tenant } },
    body: { hdt_id: hdtId, reason: "Clinical review", encounter_class: "AMB" },
  });
  if (!created.data) return redirect({ href: "/dashboard", locale });
  return redirect({
    href: `/workbench/${created.data.episode.episode_id}`,
    locale,
  });
}
