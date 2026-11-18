"use client";

import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Button from "@mui/material/Button";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { useTranslations } from "next-intl";
import { type FormEvent, type ReactNode, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import type { Prescribed } from "@/lib/clinical";

const ROUTES = ["oral", "intravenous", "intramuscular", "subcutaneous", "topical", "inhaled", "rectal", "other"] as const;

type Kind = "diagnosis" | "dispense" | "administration";
type Proposal = { text: string; recommendationId: string | null };

function useSend(episodeId: string, kind: Kind) {
  const t = useTranslations("record");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  async function send(entry: Record<string, unknown>): Promise<boolean> {
    setBusy(true);
    const response = await fetch(`/api/episodes/${episodeId}/record`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind, entry }),
    }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setResult({ ok: false, text: response?.status === 403 ? t("role") : t("failed") });
      return false;
    }
    setResult({ ok: true, text: t(`saved.${kind}`) });
    router.refresh();
    return true;
  }
  return { busy, result, clear: () => setResult(null), send };
}

function SheetForm({
  onSubmit,
  busy,
  disabled,
  submit,
  result,
  onClose,
  children,
}: {
  onSubmit: () => void;
  busy: boolean;
  disabled: boolean;
  submit: string;
  result: { ok: boolean; text: string } | null;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Stack
      component="form"
      gap={2}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      {children}
      <Stack direction="row" gap={2} alignItems="center" flexWrap="wrap">
        <Button type="submit" variant="contained" disabled={disabled || busy}>
          {submit}
        </Button>
        {result && (
          <Alert severity={result.ok ? "success" : "error"} onClose={onClose} sx={{ flexGrow: 1 }}>
            {result.text}
          </Alert>
        )}
      </Stack>
    </Stack>
  );
}

// The medical officer's own diagnosis: chosen from the APDT's proposals or written in full.
export function DiagnosisSheet({ episodeId, proposals }: { episodeId: string; proposals: Proposal[] }) {
  const t = useTranslations("record");
  const { busy, result, clear, send } = useSend(episodeId, "diagnosis");
  const [condition, setCondition] = useState("");
  const [status, setStatus] = useState<"confirmed" | "provisional">("confirmed");
  const [basis, setBasis] = useState("");

  async function submit() {
    const match = proposals.find((p) => p.text === condition.trim());
    const ok = await send({
      condition: condition.trim(),
      status,
      basis: basis.trim() || null,
      recommendation_id: match?.recommendationId ?? null,
    });
    if (ok) {
      setCondition("");
      setBasis("");
    }
  }

  return (
    <SheetForm onSubmit={submit} busy={busy} disabled={!condition.trim()} submit={t("submit.diagnosis")} result={result} onClose={clear}>
      <Autocomplete
        freeSolo
        options={proposals.map((p) => p.text)}
        inputValue={condition}
        onInputChange={(_, value) => setCondition(value)}
        renderInput={(params) => <TextField {...params} required label={t("field.condition")} helperText={t("help.condition")} />}
      />
      <TextField select label={t("field.status")} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
        <MenuItem value="confirmed">{t("status.confirmed")}</MenuItem>
        <MenuItem value="provisional">{t("status.provisional")}</MenuItem>
      </TextField>
      <TextField multiline minRows={2} label={t("field.basis")} value={basis} onChange={(e) => setBasis(e.target.value)} />
    </SheetForm>
  );
}

const describe = (p: Prescribed, times: (n: number) => string, days: (n: number) => string) =>
  [p.perDose, p.perDay ? times(p.perDay) : "", p.days ? days(p.days) : ""].filter(Boolean).join(", ");

// The pharmacist's dispense: the drug handed over, its directions and the quantity.
export function DispenseSheet({ episodeId, prescribed }: { episodeId: string; prescribed: Prescribed[] }) {
  const t = useTranslations("record");
  const { busy, result, clear, send } = useSend(episodeId, "dispense");
  const [medication, setMedication] = useState("");
  const [dose, setDose] = useState("");
  const [quantity, setQuantity] = useState("");
  const [daysSupply, setDaysSupply] = useState("");
  const [notes, setNotes] = useState("");

  function pick(drug: string) {
    setMedication(drug);
    const p = prescribed.find((x) => x.drug === drug);
    if (!p) return;
    setDose(describe(p, (n) => t("timesPerDay", { n }), (n) => t("forDays", { n })));
    if (p.days) setDaysSupply(String(p.days));
  }

  async function submit() {
    const days = Number.parseInt(daysSupply, 10);
    const ok = await send({
      medication: medication.trim(),
      dose: dose.trim(),
      quantity: quantity.trim(),
      days_supply: Number.isFinite(days) && days > 0 ? days : null,
      notes: notes.trim() || null,
    });
    if (ok) {
      for (const reset of [setMedication, setDose, setQuantity, setDaysSupply, setNotes]) reset("");
    }
  }

  return (
    <SheetForm
      onSubmit={submit}
      busy={busy}
      disabled={!medication.trim() || !dose.trim() || !quantity.trim()}
      submit={t("submit.dispense")}
      result={result}
      onClose={clear}
    >
      <Autocomplete
        freeSolo
        options={prescribed.map((p) => p.drug)}
        inputValue={medication}
        onInputChange={(_, value, reason) => (reason === "reset" ? pick(value) : setMedication(value))}
        renderInput={(params) => <TextField {...params} required label={t("field.medication")} helperText={t("help.prescribed")} />}
      />
      <TextField required label={t("field.directions")} value={dose} onChange={(e) => setDose(e.target.value)} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6 }}>
          <TextField
            fullWidth
            required
            label={t("field.quantity")}
            placeholder={t("placeholder.quantity")}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <TextField
            fullWidth
            type="number"
            label={t("field.daysSupply")}
            value={daysSupply}
            onChange={(e) => setDaysSupply(e.target.value)}
            slotProps={{ htmlInput: { min: 1, max: 365 } }}
          />
        </Grid>
      </Grid>
      <TextField multiline minRows={2} label={t("field.dispenseNotes")} value={notes} onChange={(e) => setNotes(e.target.value)} />
    </SheetForm>
  );
}

function localNow(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

// The nurse's record of care given: a medication given to the patient or a care activity.
export function CareGivenSheet({
  episodeId,
  prescribed,
  activities,
}: {
  episodeId: string;
  prescribed: Prescribed[];
  activities: string[];
}) {
  const t = useTranslations("record");
  const { busy, result, clear, send } = useSend(episodeId, "administration");
  const [kind, setKind] = useState<"medication" | "care">("medication");
  const [item, setItem] = useState("");
  const [dose, setDose] = useState("");
  const [route, setRoute] = useState<string>("");
  const [givenAt, setGivenAt] = useState(localNow);
  const [notes, setNotes] = useState("");

  function pick(value: string) {
    setItem(value);
    const p = kind === "medication" ? prescribed.find((x) => x.drug === value) : undefined;
    if (!p) return;
    setDose(p.perDose);
    setRoute(p.route && (ROUTES as readonly string[]).includes(p.route) ? p.route : p.route ? "other" : "");
  }

  async function submit() {
    const ok = await send({
      kind,
      item: item.trim(),
      dose: kind === "medication" ? dose.trim() || null : null,
      route: kind === "medication" ? route || null : null,
      given_at: givenAt ? new Date(givenAt).toISOString() : null,
      notes: notes.trim() || null,
    });
    if (ok) {
      for (const reset of [setItem, setDose, setRoute, setNotes]) reset("");
      setGivenAt(localNow());
    }
  }

  return (
    <SheetForm onSubmit={submit} busy={busy} disabled={!item.trim()} submit={t("submit.administration")} result={result} onClose={clear}>
      <ToggleButtonGroup
        exclusive
        size="small"
        color="primary"
        value={kind}
        onChange={(_, value: "medication" | "care" | null) => {
          if (!value) return;
          setKind(value);
          setItem("");
        }}
        aria-label={t("field.kind")}
      >
        <ToggleButton value="medication">{t("kind.medication")}</ToggleButton>
        <ToggleButton value="care">{t("kind.care")}</ToggleButton>
      </ToggleButtonGroup>
      <Autocomplete
        freeSolo
        options={kind === "medication" ? prescribed.map((p) => p.drug) : activities}
        inputValue={item}
        onInputChange={(_, value, reason) => (reason === "reset" ? pick(value) : setItem(value))}
        renderInput={(params) => (
          <TextField
            {...params}
            required
            label={kind === "medication" ? t("field.medicationGiven") : t("field.activity")}
            helperText={kind === "medication" ? t("help.prescribed") : t("help.activity")}
          />
        )}
      />
      {kind === "medication" && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth label={t("field.doseGiven")} value={dose} onChange={(e) => setDose(e.target.value)} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth select label={t("field.route")} value={route} onChange={(e) => setRoute(e.target.value)}>
              {ROUTES.map((r) => (
                <MenuItem key={r} value={r}>
                  {t(`route.${r}`)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
        </Grid>
      )}
      <TextField
        type="datetime-local"
        label={t("field.givenAt")}
        value={givenAt}
        onChange={(e) => setGivenAt(e.target.value)}
        slotProps={{ inputLabel: { shrink: true } }}
      />
      <TextField multiline minRows={2} label={t("field.careNotes")} value={notes} onChange={(e) => setNotes(e.target.value)} />
    </SheetForm>
  );
}
