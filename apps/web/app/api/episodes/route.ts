import { NextResponse } from "next/server";

import type { components } from "@/lib/api/apdt";
import { apdtClient } from "@/lib/api/client";
import { tenantOf } from "@/lib/data";
import { getSession } from "@/lib/session";

type Intake = components["schemas"]["IntakeRecord"];
type EncounterClass = components["schemas"]["EpisodeCreate"]["encounter_class"];

type Body = { hdtId?: unknown; reason?: unknown; encounterClass?: unknown; intake?: unknown };

// Opens an episode and records its intake, so the reasoner can propose at once.
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as Body | null;
  if (typeof body?.hdtId !== "string" || typeof body.reason !== "string" || !body.reason.trim()) {
    return NextResponse.json({ error: "hdtId and reason are required" }, { status: 400 });
  }
  const api = apdtClient(session.token);
  const tenant_id = tenantOf(session);
  const created = await api.POST("/v1/t/{tenant_id}/episodes", {
    params: { path: { tenant_id } },
    body: {
      hdt_id: body.hdtId,
      reason: body.reason.trim(),
      encounter_class: (typeof body.encounterClass === "string" ? body.encounterClass : "AMB") as EncounterClass,
    },
  });
  if (created.response.status === 403) return NextResponse.json({ error: "role" }, { status: 403 });
  if (!created.data) return NextResponse.json({ error: "the episode could not be opened" }, { status: 502 });
  const episode_id = created.data.episode.episode_id;
  if (body.intake && typeof body.intake === "object") {
    const intake = await api.POST("/v1/t/{tenant_id}/episodes/{episode_id}/intake", {
      params: { path: { tenant_id, episode_id } },
      body: body.intake as Intake,
    });
    if (!intake.data) {
      return NextResponse.json({ episodeId: episode_id, error: "intake" }, { status: 422 });
    }
  }
  return NextResponse.json({ episodeId: episode_id }, { status: 201 });
}
