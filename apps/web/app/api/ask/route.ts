import { NextResponse } from "next/server";

import { ahdtClient } from "@/lib/api/client";
import { episodeOf } from "@/lib/data";
import { personsOf } from "@/lib/roles";
import { getSession } from "@/lib/session";

const LANGUAGES = ["en", "yo", "ha", "ig", "pcm"] as const;

type Body = { episodeId?: unknown; hdtId?: unknown; utterance?: unknown; language?: unknown; sessionId?: unknown };

// One turn of the conversation with a person's twin (`ahdt.cognitive.converse`).
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as Body | null;
  const language = LANGUAGES.find((l) => l === body?.language) ?? "en";
  if (typeof body?.utterance !== "string" || !body.utterance.trim()) {
    return NextResponse.json({ error: "utterance is required" }, { status: 400 });
  }
  let hdt_id: string | undefined;
  if (typeof body.episodeId === "string") {
    hdt_id = (await episodeOf(session, body.episodeId))?.hdt_id;
  } else if (typeof body.hdtId === "string" && personsOf(session).includes(body.hdtId)) {
    hdt_id = body.hdtId;
  }
  if (!hdt_id) return NextResponse.json({ error: "no person to ask about" }, { status: 404 });
  const r = await ahdtClient(session.token).POST("/v1/tools/ahdt.cognitive.converse", {
    body: {
      hdt_id,
      utterance: body.utterance.trim(),
      language,
      session_id: typeof body.sessionId === "string" ? body.sessionId : null,
    },
  });
  if (r.response.status === 403) return NextResponse.json({ error: "role" }, { status: 403 });
  if (!r.data) return NextResponse.json({ error: "no reply" }, { status: 502 });
  // Every tool response carries `_meta`; the converse handler names the backend that answered.
  const meta = (r.data as { _meta?: { models?: { model_id: string; version: string }[] } })._meta;
  const model = meta?.models?.[0];
  return NextResponse.json({
    reply: r.data.reply,
    language: r.data.language,
    sessionId: r.data.session_id,
    groundedOn: r.data.grounded_on.map((g) => g.label),
    backend: model?.model_id?.replace(/^language\./, "") ?? null,
    model: model?.version ?? null,
  });
}
