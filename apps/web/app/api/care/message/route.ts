import { NextResponse } from "next/server";

import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

const LANGUAGES = ["en", "yo", "ha", "ig", "pcm"] as const;

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as
    | { hdtId?: unknown; text?: unknown; language?: unknown }
    | null;
  const hdtId = typeof body?.hdtId === "string" ? body.hdtId : "";
  if (!personsOf(session).includes(hdtId)) return NextResponse.json({ error: "role" }, { status: 403 });
  if (typeof body?.text !== "string" || !body.text.trim()) {
    return NextResponse.json({ error: "text is required" }, { status: 400 });
  }
  const r = await apdtClient(session.token).POST("/v1/t/{tenant_id}/patients/{hdt_id}/messages", {
    params: { path: { tenant_id: tenantOf(session), hdt_id: hdtId } },
    body: { text: body.text.trim(), language: LANGUAGES.find((l) => l === body.language) ?? "en", channel: "web" },
  });
  if (!r.data) return NextResponse.json({ error: "message not sent" }, { status: r.response.status || 502 });
  return NextResponse.json(r.data);
}
