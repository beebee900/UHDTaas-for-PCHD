"use client";

import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useRouter } from "@/i18n/navigation";

const NEXT: Record<string, string[]> = {
  None: ["Staging"],
  Staging: ["Production", "Archived"],
  Production: ["Archived"],
  Archived: [],
};

export function ModelActions({ modelId, version, stage }: { modelId: string; version: string; stage: string }) {
  const t = useTranslations("models");
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function send(body: Record<string, unknown>) {
    setError(null);
    const r = await fetch("/api/models", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ modelId, version, ...body }),
    }).catch(() => null);
    if (r?.ok) router.refresh();
    else setError(r?.status === 403 ? t("roleRefused") : t("failed"));
  }

  return (
    <Stack direction="row" gap={0.5} flexWrap="wrap" justifyContent="flex-end" alignItems="center">
      {(NEXT[stage] ?? []).map((s) => (
        <Button key={s} size="small" variant="outlined" onClick={() => send({ stage: s })}>
          {t(`to.${s}`)}
        </Button>
      ))}
      {stage === "Production" && (
        <Button size="small" color="warning" onClick={() => send({ rollback: true })}>
          {t("rollback")}
        </Button>
      )}
      {error && (
        <Typography variant="caption" color="error">
          {error}
        </Typography>
      )}
    </Stack>
  );
}
