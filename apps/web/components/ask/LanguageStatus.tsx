import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import { getTranslations } from "next-intl/server";

import { Empty, Section } from "@/components/ui/Page";
import { AHDT_URL } from "@/lib/api/client";

type Status = {
  residency_mode: string;
  hosted: { provider: string; model: string; keys: number } | null;
  chain: { backend: string; model: string }[];
  usage: Record<string, { calls: number; failures: number; prompt_tokens: number; completion_tokens: number }>;
};

export async function languageStatus(token: string): Promise<Status | null> {
  const r = await fetch(`${AHDT_URL}/v1/language/status`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  }).catch(() => null);
  return r?.ok ? ((await r.json()) as Status) : null;
}

// Which language backends answer, in the order they are tried, and how often each answered.
export async function LanguageStatus({ token }: { token: string }) {
  const t = await getTranslations("language");
  const status = await languageStatus(token);
  return (
    <Section id="language" title={t("title")} description={t("about")}>
      {status ? (
        <List dense disablePadding>
          {status.chain.map((b, i) => {
            const use = status.usage[b.backend];
            return (
              <ListItem key={b.backend} disableGutters divider>
                <ListItemText
                  primary={`${i + 1}. ${t(`backend.${b.backend}`)}`}
                  secondary={
                    b.backend === status.hosted?.provider
                      ? t("hostedDetail", { model: b.model, keys: status.hosted.keys })
                      : t(`backendAbout.${b.backend}`)
                  }
                />
                <Stack direction="row" gap={0.75}>
                  <Chip size="small" variant="outlined" label={t("calls", { count: use?.calls ?? 0 })} />
                  {(use?.failures ?? 0) > 0 && (
                    <Chip size="small" color="warning" label={t("failures", { count: use?.failures ?? 0 })} />
                  )}
                </Stack>
              </ListItem>
            );
          })}
        </List>
      ) : (
        <Empty>{t("unavailable")}</Empty>
      )}
    </Section>
  );
}
