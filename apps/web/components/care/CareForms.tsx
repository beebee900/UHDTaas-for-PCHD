"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { CATEGORIES, PURPOSES, type Purpose } from "@/lib/consent";

type Result = { ok: boolean; text: string } | null;

function Saved({ result }: { result: Result }) {
  if (!result) return null;
  return <Alert severity={result.ok ? "success" : "error"}>{result.text}</Alert>;
}

export function ConsentForm({
  hdtId,
  purposes: initialPurposes,
  withheld: initialWithheld,
}: {
  hdtId: string;
  purposes: string[];
  withheld: string[];
}) {
  const t = useTranslations("consent");
  const [purposes, setPurposes] = useState<Set<string>>(new Set(initialPurposes));
  const [withheld, setWithheld] = useState<Set<string>>(new Set(initialWithheld));
  const [result, setResult] = useState<Result>(null);

  const flip = (set: Set<string>, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  async function save() {
    const response = await fetch("/api/care/consent", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ hdtId, purposes: [...purposes], withheld: [...withheld] }),
    }).catch(() => null);
    setResult(response?.ok ? { ok: true, text: t("saved") } : { ok: false, text: t("failed") });
  }

  return (
    <Stack gap={2}>
      <div>
        <Typography variant="subtitle2" component="h3">
          {t("purposes")}
        </Typography>
        <FormGroup row>
          {PURPOSES.map((p: Purpose) => (
            <FormControlLabel
              key={p}
              control={<Checkbox checked={purposes.has(p)} onChange={() => setPurposes((cur) => flip(cur, p))} />}
              label={t(`purpose.${p}`)}
            />
          ))}
        </FormGroup>
      </div>
      <div>
        <Typography variant="subtitle2" component="h3">
          {t("categories")}
        </Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          {t("categoriesAbout")}
        </Typography>
        <Grid container spacing={1}>
          {Object.keys(CATEGORIES).map((c) => (
            <Grid key={c} size={{ xs: 12, sm: 6 }}>
              <FormControlLabel
                control={<Switch checked={!withheld.has(c)} onChange={() => setWithheld((cur) => flip(cur, c))} />}
                label={t(`category.${c}`)}
              />
            </Grid>
          ))}
        </Grid>
      </div>
      <Saved result={result} />
      <Box>
        <Button variant="contained" onClick={save}>
          {t("save")}
        </Button>
      </Box>
    </Stack>
  );
}

type Row = {
  linkId: string;
  type: string;
  text: string;
  depth: number;
  required: boolean;
  options?: { code: string; display: string }[];
};

// A rendered FHIR Questionnaire (`render` of the APDT intake module) answered in one form.
export function PreferencesForm({ hdtId, title, items }: { hdtId: string; title: string; items: Row[] }) {
  const t = useTranslations("preferences");
  const tl = useTranslations("locale");
  const [result, setResult] = useState<Result>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const answers: Record<string, unknown> = {};
    for (const item of items) {
      const value = form.get(item.linkId);
      if (value === null || value === "") continue;
      answers[item.linkId] = item.type === "integer" || item.type === "decimal" ? Number(value) : String(value);
    }
    const response = await fetch("/api/care/preferences", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ hdtId, answers }),
    }).catch(() => null);
    setResult(response?.ok ? { ok: true, text: t("saved") } : { ok: false, text: t("failed") });
  }

  const optionLabel = (item: Row, o: { code: string; display: string }) =>
    item.linkId === "language" && tl.has(o.code) ? tl(o.code) : t.has(`option.${o.code}`) ? t(`option.${o.code}`) : o.display;

  return (
    <Stack component="form" gap={2} onSubmit={submit}>
      <Typography color="text.secondary">{title}</Typography>
      <Grid container spacing={2}>
        {items.map((item) =>
          item.type === "group" ? (
            <Grid key={item.linkId} size={12}>
              <Typography variant="subtitle2" component="h3">
                {item.text}
              </Typography>
              {item.linkId === "priorities" && (
                <Typography variant="body2" color="text.secondary">
                  {t("prioritiesAbout")}
                </Typography>
              )}
            </Grid>
          ) : (
            <Grid key={item.linkId} size={{ xs: 12, sm: item.depth > 0 ? 4 : 6 }}>
              {item.options ? (
                <TextField select fullWidth name={item.linkId} label={item.text} required={item.required} defaultValue="">
                  {item.options.map((o) => (
                    <MenuItem key={o.code} value={o.code}>
                      {optionLabel(item, o)}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField
                  fullWidth
                  name={item.linkId}
                  label={item.text}
                  required={item.required}
                  type={item.type === "integer" || item.type === "decimal" ? "number" : "text"}
                  slotProps={item.type === "integer" ? { htmlInput: { min: 1, max: 5 } } : undefined}
                />
              )}
            </Grid>
          ),
        )}
      </Grid>
      <Saved result={result} />
      <Box>
        <Button type="submit" variant="contained">
          {t("save")}
        </Button>
      </Box>
    </Stack>
  );
}

export function MessageForm({ hdtId }: { hdtId: string }) {
  const t = useTranslations("message");
  const locale = useLocale();
  const [text, setText] = useState("");
  const [result, setResult] = useState<Result>(null);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const response = await fetch("/api/care/message", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ hdtId, text, language: locale }),
    }).catch(() => null);
    if (response?.ok) {
      const reply = (await response.json()) as { reply: string };
      setResult({ ok: true, text: reply.reply });
      setText("");
    } else {
      setResult({ ok: false, text: t("failed") });
    }
  }

  return (
    <Stack component="form" gap={2} onSubmit={send}>
      <TextField
        multiline
        minRows={3}
        label={t("label")}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Saved result={result} />
      <Box>
        <Button type="submit" variant="contained" disabled={!text.trim()}>
          {t("send")}
        </Button>
      </Box>
    </Stack>
  );
}
