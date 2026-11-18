import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { getSession } from "@/lib/session";

const URGENCY = ["routine", "urgent", "emergency"] as const;
const TENANTS = ["fac-a", "fac-b"] as const;

export async function POST(request: Request, { params }: { params: Promise<{ episodeId: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const { episodeId } = await params;
  const body = (await request.json().catch(() => null)) as
    | { toTenant?: unknown; reason?: unknown; urgency?: unknown }
    | null;
  const to_tenant = TENANTS.find((x) => x === body?.toTenant);
  const urgency = URGENCY.find((x) => x === body?.urgency) ?? "routine";
  if (!to_tenant || typeof body?.reason !== "string" || !body.reason.trim()) {
    return NextResponse.json({ error: "toTenant and reason are required" }, { status: 400 });
  }
  const r = await apdtClient(session.token).POST("/v1/t/{tenant_id}/referrals", {
    params: { path: { tenant_id: tenantOf(session) } },
    body: { episode_id: episodeId, to_tenant, reason: body.reason.trim(), urgency },
  });
  if (!r.data) return NextResponse.json({ error: "referral failed" }, { status: r.response.status || 502 });
  return NextResponse.json(r.data, { status: 201 });
}
