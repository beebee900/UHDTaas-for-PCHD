import { NextResponse } from "next/server";

import { ahdtClient } from "@/lib/api/client";
import { getSession } from "@/lib/session";

const STAGES = ["Staging", "Production", "Archived"] as const;

// Moves a model version to another stage, or rolls the production version back.
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as
    | { modelId?: unknown; version?: unknown; stage?: unknown; rollback?: unknown }
    | null;
  if (typeof body?.modelId !== "string") return NextResponse.json({ error: "modelId is required" }, { status: 400 });
  const api = ahdtClient(session.token);
  const stage = STAGES.find((s) => s === body.stage);
  const r = body.rollback === true
    ? await api.POST("/v1/models/{model_id}/rollback", { params: { path: { model_id: body.modelId } } })
    : stage && typeof body.version === "string"
      ? await api.POST("/v1/models/{model_id}/versions/{version}/stage", {
          params: { path: { model_id: body.modelId, version: body.version } },
          body: { stage },
        })
      : null;
  if (!r) return NextResponse.json({ error: "stage or rollback is required" }, { status: 400 });
  if (!r.response.ok) return NextResponse.json({ error: "refused" }, { status: r.response.status });
  return NextResponse.json(r.data ?? {});
}
