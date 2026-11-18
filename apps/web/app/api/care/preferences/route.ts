import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

export async function PUT(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as { hdtId?: unknown; answers?: unknown } | null;
  const hdtId = typeof body?.hdtId === "string" ? body.hdtId : "";
  if (!personsOf(session).includes(hdtId)) return NextResponse.json({ error: "role" }, { status: 403 });
  const answers = body?.answers && typeof body.answers === "object" ? (body.answers as Record<string, unknown>) : {};
  const r = await apdtClient(session.token).PUT("/v1/t/{tenant_id}/patients/{hdt_id}/preferences", {
    params: { path: { tenant_id: tenantOf(session), hdt_id: hdtId } },
    body: { answers },
  });
  if (!r.data) return NextResponse.json({ error: "preferences not saved" }, { status: r.response.status || 502 });
  return NextResponse.json(r.data);
}
