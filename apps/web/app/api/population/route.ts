import { NextResponse } from "next/server";

import { ahdtClient } from "@/lib/api/client";
import { can } from "@/lib/roles";
import { getSession } from "@/lib/session";

const POPULATION_URL = process.env.ATRA_POPULATION_URL ?? "http://127.0.0.1:8110";
// The cohort tool takes a person id for its argument schema; a cohort spans everyone consented.
const ANY_PERSON = "hdt-000000000000";

type Body = { tool?: unknown; args?: unknown };

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as Body | null;
  const args = body?.args && typeof body.args === "object" ? (body.args as Record<string, unknown>) : {};
  if (body?.tool === "cohort") {
    if (!can.extractCohort(session.role)) return NextResponse.json({ error: "role" }, { status: 403 });
    const r = await ahdtClient(session.token).POST("/v1/tools/ahdt.data.cohort_extract", {
      body: {
        hdt_id: ANY_PERSON,
        as_of: null,
        cohort_def: {},
        fields: args.fields as string[],
        privacy: args.privacy as { k: number },
      },
    });
    if (!r.data) return NextResponse.json({ error: (r.error as { detail?: string } | undefined)?.detail ?? "refused" }, { status: r.response.status });
    return NextResponse.json(r.data);
  }
  if (body?.tool !== "priors" && body?.tool !== "norms") {
    return NextResponse.json({ error: "tool must be priors, norms or cohort" }, { status: 400 });
  }
  const upstream = await fetch(`${POPULATION_URL}/v1/tools/population.${body.tool}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.token}`, "content-type": "application/json" },
    body: JSON.stringify(args),
    cache: "no-store",
  }).catch(() => null);
  if (!upstream) return NextResponse.json({ error: "the population twin is not reachable" }, { status: 502 });
  const data = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  return NextResponse.json(upstream.ok ? data : { error: (data.detail as string) ?? "refused" }, { status: upstream.status });
}
