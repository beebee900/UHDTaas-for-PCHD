"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { routing } from "@/i18n/routing";

type Turn = {
  role: "user" | "assistant";
  text: string;
  backend?: string | null;
  model?: string | null;
  groundedOn?: string[];
};

// A conversation with one person's twin, in any of the five languages.
export function AskTwin({ episodeId, hdtId }: { episodeId?: string; hdtId?: string }) {
  const t = useTranslations("ask");
  const tl = useTranslations("locale");
  const locale = useLocale();
  const [language, setLanguage] = useState(locale);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const utterance = text.trim();
    if (!utterance) return;
    setTurns((cur) => [...cur, { role: "user", text: utterance }]);
    setText("");
    setBusy(true);
    setError(null);
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ episodeId, hdtId, utterance, language, sessionId }),
    }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setError(response?.status === 403 ? t("role") : t("failed"));
      return;
    }
    const reply = (await response.json()) as {
      reply: string;
      sessionId: string;
      backend: string | null;
      model: string | null;
      groundedOn: string[];
    };
    setSessionId(reply.sessionId);
    setTurns((cur) => [
      ...cur,
      { role: "assistant", text: reply.reply, backend: reply.backend, model: reply.model, groundedOn: reply.groundedOn },
    ]);
  }

  return (
    <Stack gap={2}>
      <Paper variant="outlined" sx={{ p: 2, minHeight: 240, display: "flex", flexDirection: "column", gap: 1.5 }} aria-live="polite">
        {turns.length === 0 && <Typography color="text.secondary">{t("empty")}</Typography>}
        {turns.map((turn, i) => (
          <Box
            key={i}
            sx={{
              alignSelf: turn.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              bgcolor: turn.role === "user" ? "primary.main" : "action.hover",
              color: turn.role === "user" ? "primary.contrastText" : "text.primary",
              px: 2,
              py: 1.25,
              borderRadius: 3,
            }}
          >
            <Typography sx={{ whiteSpace: "pre-wrap" }}>{turn.text}</Typography>
            {turn.role === "assistant" && (
              <Stack direction="row" gap={0.75} flexWrap="wrap" sx={{ mt: 1 }}>
                {turn.backend && (
                  <Chip size="small" variant="outlined" label={t("answeredBy", { backend: t(`backend.${turn.backend}`), model: turn.model ?? "" })} />
                )}
                {turn.groundedOn?.slice(0, 4).map((g) => <Chip key={g} size="small" label={g} />)}
              </Stack>
            )}
          </Box>
        ))}
        {busy && <CircularProgress size={20} aria-label={t("thinking")} />}
      </Paper>
      {error && <Alert severity="error">{error}</Alert>}
      <Stack component="form" direction={{ xs: "column", sm: "row" }} gap={1} onSubmit={send}>
        <TextField
          select
          size="small"
          label={t("language")}
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          sx={{ minWidth: 150 }}
        >
          {routing.locales.map((l) => (
            <MenuItem key={l} value={l}>
              {tl(l)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          fullWidth
          label={t("message")}
          placeholder={t("placeholder")}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="contained" disabled={busy || !text.trim()}>
          {t("send")}
        </Button>
      </Stack>
    </Stack>
  );
}
