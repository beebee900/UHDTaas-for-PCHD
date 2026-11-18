import type { components } from "./api/apdt";
import { apdtClient } from "./api/client";
import type { Tenant } from "./clinical";
import type { Session } from "./session";

export type EpisodeListItem = components["schemas"]["EpisodeListItem"];
export type PatientEntry = components["schemas"]["PatientEntry"];
export type WorklistItem = components["schemas"]["WorklistItem"];
export type AuditRecord = components["schemas"]["AuditRecord"];

export const tenantOf = (session: Session) => (session.tenantId ?? "fac-a") as Tenant;

export async function episodesOf(
  session: Session,
  options: { status?: "open" | "closed" | "all"; hdtId?: string } = {},
): Promise<EpisodeListItem[] | null> {
  const r = await apdtClient(session.token).GET("/v1/t/{tenant_id}/episodes", {
    params: {
      path: { tenant_id: tenantOf(session) },
      query: { status: options.status ?? "open", hdt_id: options.hdtId },
    },
  });
  return r.data ?? null;
}

export async function worklistOf(session: Session): Promise<WorklistItem[] | null> {
  const r = await apdtClient(session.token).GET("/v1/t/{tenant_id}/worklists/{role}", {
    params: { path: { tenant_id: tenantOf(session), role: session.role as "nurse" } },
  });
  return r.data?.items ?? null;
}

export async function auditOf(
  session: Session,
  options: { episodeId?: string; hdtId?: string; limit?: number } = {},
): Promise<AuditRecord[] | null> {
  const r = await apdtClient(session.token).GET("/v1/t/{tenant_id}/audit", {
    params: {
      path: { tenant_id: tenantOf(session) },
      query: { episode_id: options.episodeId, hdt_id: options.hdtId, limit: options.limit ?? 200 },
    },
  });
  return r.data ?? null;
}

// Each record names the hash of the one before it; a break means the log was altered.
export function chainIntact(newestFirst: AuditRecord[]): boolean {
  for (let i = 0; i + 1 < newestFirst.length; i++) {
    const record = newestFirst[i];
    const before = newestFirst[i + 1];
    if (record.seq === before.seq + 1 && record.prev_hash !== before.hash) return false;
  }
  return true;
}

export async function patientOf(session: Session, hdtId: string): Promise<PatientEntry | null> {
  const r = await apdtClient(session.token).GET("/v1/t/{tenant_id}/patients", {
    params: { path: { tenant_id: tenantOf(session) } },
  });
  return r.data?.find((p) => p.hdt_id === hdtId) ?? null;
}

export async function episodeOf(session: Session, episodeId: string) {
  const r = await apdtClient(session.token).GET("/v1/t/{tenant_id}/episodes/{episode_id}", {
    params: { path: { tenant_id: tenantOf(session), episode_id: episodeId } },
  });
  return r.data?.episode ?? null;
}
