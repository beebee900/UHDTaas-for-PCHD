import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import { consentResource, PURPOSES, type Purpose } from "@/lib/consent";
import { tenantOf } from "@/lib/data";
import { personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

export async function PUT(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as
    | { hdtId?: unknown; purposes?: unknown; withheld?: unknown }
    | null;
  const hdtId = typeof body?.hdtId === "string" ? body.hdtId : "";
  if (!personsOf(session).includes(hdtId)) return NextResponse.json({ error: "role" }, { status: 403 });
  const purposes = (Array.isArray(body?.purposes) ? body.purposes : []).filter((p): p is Purpose =>
    (PURPOSES as readonly string[]).includes(p),
  );
  const withheld = (Array.isArray(body?.withheld) ? body.withheld : []).filter((c): c is string => typeof c === "string");
  const r = await apdtClient(session.token).PUT("/v1/t/{tenant_id}/patients/{hdt_id}/consent", {
    params: { path: { tenant_id: tenantOf(session), hdt_id: hdtId } },
    body: consentResource(hdtId, purposes, withheld),
  });
  if (!r.data) return NextResponse.json({ error: "consent not saved" }, { status: r.response.status || 502 });
  return NextResponse.json(r.data);
}
