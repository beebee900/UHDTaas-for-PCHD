import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";
import { getSession } from "@/lib/session";

const DECISIONS = ["accept", "sign", "verify", "consent", "edit", "query", "reject", "decline"] as const;

type Body = {
  runId?: unknown;
  recommendationId?: unknown;
  decision?: unknown;
  editedPayload?: unknown;
  reason?: unknown;
};

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as Body | null;
  const decision = DECISIONS.find((d) => d === body?.decision);
  if (typeof body?.runId !== "string" || typeof body.recommendationId !== "string" || !decision) {
    return NextResponse.json({ error: "runId, recommendationId and decision are required" }, { status: 400 });
  }
  const edited =
    body.editedPayload && typeof body.editedPayload === "object"
      ? (body.editedPayload as Record<string, unknown>)
      : null;
  const response = await apdtClient(session.token).POST("/v1/t/{tenant_id}/runs/{run_id}/resume", {
    params: { path: { tenant_id: (session.tenantId ?? "fac-a") as Tenant, run_id: body.runId } },
    body: {
      decision_id: `dec-${crypto.randomUUID()}`,
      recommendation_id: body.recommendationId,
      decided_by: { id: session.sub, role: session.role as "medical_officer" },
      decision,
      edited_payload: edited,
      override_reason: typeof body.reason === "string" ? body.reason : null,
      signature: `unsigned:${session.sub}`,
    },
  });
  if (response.response.status === 403) {
    return NextResponse.json({ error: "role" }, { status: 403 });
  }
  if (!response.data) return NextResponse.json({ error: "resume failed" }, { status: 502 });
  return NextResponse.json(response.data);
}
