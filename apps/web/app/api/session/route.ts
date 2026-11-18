import { NextResponse } from "next/server";

import { APDT_URL } from "@/lib/api/client";
import { TOKEN_COOKIE } from "@/lib/session";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as
    | { username?: unknown; password?: unknown }
    | null;
  if (typeof body?.username !== "string" || typeof body.password !== "string") {
    return NextResponse.json({ error: "username and password are required" }, { status: 400 });
  }
  const upstream = await fetch(`${APDT_URL}/auth/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: body.username, password: body.password }),
    cache: "no-store",
  }).catch(() => null);
  if (!upstream) {
    return NextResponse.json({ error: "the sign-in service is not reachable" }, { status: 502 });
  }
  if (!upstream.ok) {
    return NextResponse.json({ error: "sign-in failed" }, { status: 401 });
  }
  const token = (await upstream.json()) as { access_token: string; expires_in: number; role: string };
  const response = NextResponse.json({ role: token.role });
  response.cookies.set(TOKEN_COOKIE, token.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production" && !APDT_URL.startsWith("http://127."),
    path: "/",
    maxAge: token.expires_in,
  });
  return response;
}

export async function DELETE() {
  const response = new NextResponse(null, { status: 204 });
  response.cookies.delete(TOKEN_COOKIE);
  return response;
}
