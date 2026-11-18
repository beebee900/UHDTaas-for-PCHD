import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { getSession } from "@/lib/session";

export async function POST(request: Request, { params }: { params: Promise<{ episodeId: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const { episodeId } = await params;
  const body = (await request.json().catch(() => null)) as { outcome?: unknown } | null;
  if (typeof body?.outcome !== "string" || !body.outcome.trim()) {
    return NextResponse.json({ error: "outcome is required" }, { status: 400 });
  }
  const r = await apdtClient(session.token).POST("/v1/t/{tenant_id}/episodes/{episode_id}/close", {
    params: { path: { tenant_id: tenantOf(session), episode_id: episodeId } },
    body: { outcome: body.outcome.trim() },
  });
  if (!r.data) return NextResponse.json({ error: "close failed" }, { status: r.response.status || 502 });
  return NextResponse.json(r.data);
}
