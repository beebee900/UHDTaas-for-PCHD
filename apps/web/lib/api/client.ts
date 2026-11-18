import createClient from "openapi-fetch";

import type { paths as AhdtPaths } from "./ahdt";
import type { paths } from "./apdt";

export const APDT_URL = process.env.ATRA_APDT_URL ?? "http://127.0.0.1:8200";
export const AHDT_URL = process.env.ATRA_AHDT_URL ?? "http://127.0.0.1:8100";

export function apdtClient(token: string) {
  return createClient<paths>({
    baseUrl: APDT_URL,
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function ahdtClient(token: string) {
  return createClient<AhdtPaths>({
    baseUrl: AHDT_URL,
    headers: { Authorization: `Bearer ${token}` },
  });
}
