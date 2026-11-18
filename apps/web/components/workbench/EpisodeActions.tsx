"use client";

import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useRouter } from "@/i18n/navigation";

type Open = "refer" | "close" | null;

// Referral to the other facility and closing the episode: medical officer actions.
export function EpisodeActions({ episodeId, tenant }: { episodeId: string; tenant: string }) {
  const t = useTranslations("episodeActions");
  const tf = useTranslations("facility");
  const router = useRouter();
  const [open, setOpen] = useState<Open>(null);
  const [text, setText] = useState("");
  const [urgency, setUrgency] = useState("routine");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const other = tenant === "fac-a" ? "fac-b" : "fac-a";

  async function send() {
    const response = await fetch(`/api/episodes/${episodeId}/${open}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(open === "refer" ? { toTenant: other, reason: text, urgency } : { outcome: text }),
    }).catch(() => null);
    const kind = open;
    setOpen(null);
    setText("");
    if (!response?.ok) {
      setMessage({ ok: false, text: t("failed") });
      return;
    }
    if (kind === "refer") {
      const result = (await response.json()) as { referral_id: string; status: string };
      setMessage({ ok: true, text: t("referred", { id: result.referral_id, status: t(`status.${result.status}`) }) });
    } else {
      setMessage({ ok: true, text: t("closed") });
      router.refresh();
    }
  }

  return (
    <>
      <Stack direction="row" gap={1}>
        <Button variant="outlined" onClick={() => setOpen("refer")}>
          {t("refer")}
        </Button>
        <Button variant="outlined" color="inherit" onClick={() => setOpen("close")}>
          {t("close")}
        </Button>
      </Stack>
      {message && (
        <Alert severity={message.ok ? "success" : "error"} onClose={() => setMessage(null)} sx={{ mt: 1 }}>
          {message.text}
        </Alert>
      )}
      <Dialog open={open !== null} onClose={() => setOpen(null)} fullWidth maxWidth="sm">
        <DialogTitle component="h2">
          {open === "refer" ? t("referTitle", { facility: tf(other) }) : t("closeTitle")}
        </DialogTitle>
        <DialogContent>
          <Stack gap={2} sx={{ mt: 1 }}>
            {open === "refer" && (
              <TextField select label={t("urgency")} value={urgency} onChange={(e) => setUrgency(e.target.value)}>
                {["routine", "urgent", "emergency"].map((u) => (
                  <MenuItem key={u} value={u}>
                    {t(`urgencies.${u}`)}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              autoFocus
              multiline
              minRows={2}
              label={open === "refer" ? t("reason") : t("outcome")}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(null)}>{t("cancel")}</Button>
          <Button variant="contained" disabled={!text.trim()} onClick={send}>
            {open === "refer" ? t("send") : t("confirmClose")}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
