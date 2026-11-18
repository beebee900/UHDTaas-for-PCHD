import { NextResponse } from "next/server";

import { AHDT_URL } from "@/lib/api/client";
import { personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

// The person's health knowledge graph as Turtle, for download.
export async function GET(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const hdtId = new URL(request.url).searchParams.get("hdt") ?? "";
  if (!personsOf(session).includes(hdtId)) return NextResponse.json({ error: "role" }, { status: 403 });
  const upstream = await fetch(`${AHDT_URL}/v1/persons/${encodeURIComponent(hdtId)}/phkg.ttl`, {
    headers: { Authorization: `Bearer ${session.token}` },
    cache: "no-store",
  }).catch(() => null);
  if (!upstream?.ok) return NextResponse.json({ error: "not available" }, { status: upstream?.status ?? 502 });
  return new NextResponse(await upstream.text(), {
    headers: {
      "content-type": "text/turtle; charset=utf-8",
      "content-disposition": `attachment; filename="health-knowledge-graph-${hdtId}.ttl"`,
    },
  });
}
