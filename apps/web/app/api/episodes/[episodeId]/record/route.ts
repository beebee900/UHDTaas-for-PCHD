import { NextResponse } from "next/server";

import type { components } from "@/lib/api/apdt";
import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { getSession } from "@/lib/session";

type Schemas = components["schemas"];
type Body = { kind?: unknown; entry?: unknown };

// Enters the medical officer's diagnosis, the pharmacist's dispense or the nurse's care given.
export async function POST(request: Request, { params }: { params: Promise<{ episodeId: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const { episodeId } = await params;
  const body = (await request.json().catch(() => null)) as Body | null;
  if (!body?.entry || typeof body.entry !== "object") {
    return NextResponse.json({ error: "entry is required" }, { status: 400 });
  }
  const api = apdtClient(session.token);
  const path = { tenant_id: tenantOf(session), episode_id: episodeId };
  const sent =
    body.kind === "diagnosis"
      ? await api.POST("/v1/t/{tenant_id}/episodes/{episode_id}/record/diagnosis", {
          params: { path },
          body: body.entry as Schemas["DiagnosisEntry"],
        })
      : body.kind === "dispense"
        ? await api.POST("/v1/t/{tenant_id}/episodes/{episode_id}/record/dispense", {
            params: { path },
            body: body.entry as Schemas["DispenseEntry"],
          })
        : body.kind === "administration"
          ? await api.POST("/v1/t/{tenant_id}/episodes/{episode_id}/record/administration", {
              params: { path },
              body: body.entry as Schemas["AdministrationEntry"],
            })
          : null;
  if (!sent) return NextResponse.json({ error: "unknown kind" }, { status: 400 });
  if (!sent.data) return NextResponse.json({ error: "not recorded" }, { status: sent.response.status || 502 });
  return NextResponse.json(sent.data, { status: 201 });
}
