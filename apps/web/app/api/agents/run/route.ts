import { NextResponse } from "next/server";

import { ahdtClient, apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";
import { getSession } from "@/lib/session";
import { isPersonTwin } from "@/lib/twins";

// The person goal of kb/goal_templates/cardiometabolic_ckd.yaml, used when none is given.
const PERSON_GOAL = "Control hypertension, type 2 diabetes and CKD stage 3 safely";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as
    | { episodeId?: unknown; twin?: unknown; conductor?: unknown; personGoal?: unknown }
    | null;
  const twin = typeof body?.twin === "string" && isPersonTwin(body.twin) ? body.twin : null;
  if (typeof body?.episodeId !== "string" || (body.conductor !== true && !twin)) {
    return NextResponse.json({ error: "episodeId and a twin or conductor are required" }, { status: 400 });
  }
  const episode = await apdtClient(session.token).GET("/v1/t/{tenant_id}/episodes/{episode_id}", {
    params: {
      path: { tenant_id: (session.tenantId ?? "fac-a") as Tenant, episode_id: body.episodeId },
    },
  });
  const hdt_id = episode.data?.episode.hdt_id;
  if (!hdt_id) return NextResponse.json({ error: "episode not found" }, { status: 404 });
  const response = await ahdtClient(session.token).POST("/v1/agents/run", {
    body:
      body.conductor === true
        ? {
            hdt_id,
            person_goal:
              typeof body.personGoal === "string" && body.personGoal.trim() ? body.personGoal.trim() : PERSON_GOAL,
          }
        : { hdt_id, twin },
  });
  if (response.response.status === 403) return NextResponse.json({ error: "role" }, { status: 403 });
  if (!response.data) return NextResponse.json({ error: "run failed" }, { status: 502 });
  return NextResponse.json(response.data);
}
