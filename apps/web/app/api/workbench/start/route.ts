import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";
import { getSession } from "@/lib/session";

const GOALS = ["diagnosis", "treatment", "care"] as const;

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as
    | { episodeId?: unknown; goal?: unknown }
    | null;
  const goal = GOALS.find((g) => g === body?.goal);
  if (typeof body?.episodeId !== "string" || !goal) {
    return NextResponse.json({ error: "episodeId and goal are required" }, { status: 400 });
  }
  const api = apdtClient(session.token);
  const tenant_id = (session.tenantId ?? "fac-a") as Tenant;
  const started = await api.POST(`/v1/t/{tenant_id}/episodes/{episode_id}/goals/${goal}`, {
    params: { path: { tenant_id, episode_id: body.episodeId } },
  });
  if (!started.data) return NextResponse.json({ error: "start failed" }, { status: 502 });
  const run = await api.GET("/v1/t/{tenant_id}/runs/{run_id}", {
    params: { path: { tenant_id, run_id: started.data.run_id } },
  });
  if (!run.data) return NextResponse.json({ error: "start failed" }, { status: 502 });
  return NextResponse.json(run.data);
}
