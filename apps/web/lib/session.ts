import { cookies } from "next/headers";

export const TOKEN_COOKIE = "atra_token";

export type Session = {
  token: string;
  sub: string;
  role: string;
  tenantId?: string;
  hdtId?: string;
  proxyFor: string[];
  carerFor: string[];
};

type Claims = {
  sub: string;
  role?: string;
  tenant_id?: string;
  hdt_id?: string;
  proxy_for?: string[];
  carer_for?: string[];
  exp: number;
};

// Reads the token's claims to choose what to show. The APDT verifies the token on every call.
function claimsOf(token: string): Claims | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    return JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as Claims;
  } catch {
    return null;
  }
}

export async function getSession(): Promise<Session | null> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) return null;
  const claims = claimsOf(token);
  if (!claims?.role || claims.exp * 1000 < Date.now()) return null;
  return {
    token,
    sub: claims.sub,
    role: claims.role,
    tenantId: claims.tenant_id,
    hdtId: claims.hdt_id,
    proxyFor: claims.proxy_for ?? [],
    carerFor: claims.carer_for ?? [],
  };
}
