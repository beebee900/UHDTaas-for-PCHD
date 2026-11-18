"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { type FormEvent, type ReactNode, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import type { components } from "@/lib/api/apdt";

type Patient = components["schemas"]["PatientEntry"];
type Catalogue = components["schemas"]["IntakeCatalogue"];
type TestResult = "" | "positive" | "negative";

const ENCOUNTERS = ["AMB", "EMER", "IMP", "HH", "VR"] as const;
const CAPTURES = ["question", "exam", "lab"] as const;
const UNITS: Record<string, string> = { Cel: "°C", "mm[Hg]": "mmHg", "umol/L": "µmol/L" };

function Block({ title, about, children }: { title: string; about?: string; children: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.5 } }}>
      <Typography variant="h6" component="h2">
        {title}
      </Typography>
      {about && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {about}
        </Typography>
      )}
      {children}
    </Paper>
  );
}

export function NewEpisodeForm({ patients, catalogue }: { patients: Patient[]; catalogue: Catalogue }) {
  const t = useTranslations();
  const router = useRouter();
  const [hdtId, setHdtId] = useState(patients[0]?.hdt_id ?? "");
  const [present, setPresent] = useState<Set<string>>(new Set());
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [measures, setMeasures] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const patient = patients.find((p) => p.hdt_id === hdtId);

  function toggle(id: string) {
    setPresent((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const measurements = Object.fromEntries(
      Object.entries(measures)
        .filter(([, v]) => v.trim() !== "" && Number.isFinite(Number(v)))
        .map(([k, v]) => [k, Number(v)]),
    );
    const weight = Number(form.get("weight"));
    const intake = {
      findings: Object.fromEntries([...present].map((id) => [id, true])),
      tests: Object.fromEntries(
        Object.entries(tests).filter(([, v]) => v).map(([id, v]) => [id, v === "positive"]),
      ),
      measurements,
      weight_kg: weight > 0 ? weight : null,
      pregnancy: patient?.sex === "female" ? String(form.get("pregnancy") || "none") : "none",
      avpu: String(form.get("avpu") || "A"),
    };
    setBusy(true);
    setError(null);
    const response = await fetch("/api/episodes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        hdtId,
        reason: form.get("reason"),
        encounterClass: form.get("encounter"),
        intake,
      }),
    }).catch(() => null);
    const result = (await response?.json().catch(() => null)) as { episodeId?: string; error?: string } | null;
    setBusy(false);
    if (result?.episodeId) {
      router.push(`/workbench/${result.episodeId}`);
      return;
    }
    setError(response?.status === 403 ? t("newEpisode.role") : t("newEpisode.failed"));
  }

  return (
    <Stack component="form" gap={2} onSubmit={submit}>
      <Block title={t("newEpisode.who")} about={t("newEpisode.whoAbout")}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField
              select
              fullWidth
              required
              label={t("newEpisode.patient")}
              value={hdtId}
              onChange={(e) => setHdtId(e.target.value)}
            >
              {patients.map((p) => (
                <MenuItem key={p.hdt_id} value={p.hdt_id}>
                  {t("newEpisode.patientOption", {
                    initials: p.initials,
                    sex: t(`sex.${p.sex}`),
                    age: p.age_years,
                    language: t(`locale.${p.language}`),
                  })}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, md: 5 }}>
            <TextField name="reason" fullWidth required label={t("newEpisode.reason")} placeholder={t("newEpisode.reasonHint")} />
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <TextField name="encounter" select fullWidth defaultValue="AMB" label={t("newEpisode.encounter")}>
              {ENCOUNTERS.map((e) => (
                <MenuItem key={e} value={e}>
                  {t(`encounter.${e}`)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 6, md: 4 }}>
            <TextField
              name="weight"
              type="number"
              fullWidth
              label={t("newEpisode.weight")}
              slotProps={{ htmlInput: { min: 1, max: 400, step: 0.1 }, input: { endAdornment: <InputAdornment position="end">kg</InputAdornment> } }}
            />
          </Grid>
          <Grid size={{ xs: 6, md: 4 }}>
            <TextField name="avpu" select fullWidth defaultValue="A" label={t("newEpisode.avpu")}>
              {["A", "V", "P", "U"].map((a) => (
                <MenuItem key={a} value={a}>
                  {t(`avpu.${a}`)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          {patient?.sex === "female" && (
            <Grid size={{ xs: 12, md: 4 }}>
              <TextField name="pregnancy" select fullWidth defaultValue="none" label={t("newEpisode.pregnancy")}>
                {["none", "t1", "t2", "t3"].map((p) => (
                  <MenuItem key={p} value={p}>
                    {t(`pregnancy.${p}`)}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
          )}
        </Grid>
      </Block>

      <Block title={t("newEpisode.measurements")} about={t("newEpisode.measurementsAbout")}>
        <Grid container spacing={2}>
          {catalogue.measurements.map((m) => (
            <Grid key={m.field} size={{ xs: 6, sm: 4, md: 3 }}>
              <TextField
                type="number"
                fullWidth
                label={t(`measure.${m.field}`)}
                value={measures[m.field] ?? ""}
                onChange={(e) => setMeasures((cur) => ({ ...cur, [m.field]: e.target.value }))}
                slotProps={{
                  htmlInput: { step: "any" },
                  input: { endAdornment: <InputAdornment position="end">{UNITS[m.unit] ?? m.unit}</InputAdornment> },
                }}
              />
            </Grid>
          ))}
        </Grid>
      </Block>

      <Block title={t("newEpisode.findings")} about={t("newEpisode.findingsAbout")}>
        <Grid container spacing={2}>
          {CAPTURES.map((capture) => (
            <Grid key={capture} size={{ xs: 12, md: 4 }}>
              <Typography variant="subtitle2" component="h3" gutterBottom>
                {t(`newEpisode.capture.${capture}`)}
              </Typography>
              <FormGroup>
                {catalogue.findings
                  .filter((f) => f.capture === capture)
                  .map((f) => (
                    <FormControlLabel
                      key={f.id}
                      control={<Checkbox size="small" checked={present.has(f.id)} onChange={() => toggle(f.id)} />}
                      label={f.name}
                    />
                  ))}
              </FormGroup>
            </Grid>
          ))}
        </Grid>
      </Block>

      <Block title={t("newEpisode.tests")} about={t("newEpisode.testsAbout")}>
        <Grid container spacing={2}>
          {catalogue.tests.map((test) => (
            <Grid key={test.id} size={{ xs: 12, sm: 6, md: 4 }}>
              <TextField
                select
                fullWidth
                size="small"
                label={test.name}
                value={tests[test.id] ?? ""}
                onChange={(e) => setTests((cur) => ({ ...cur, [test.id]: e.target.value as TestResult }))}
              >
                <MenuItem value="">{t("newEpisode.notDone")}</MenuItem>
                <MenuItem value="positive">{t("newEpisode.positive")}</MenuItem>
                <MenuItem value="negative">{t("newEpisode.negative")}</MenuItem>
              </TextField>
            </Grid>
          ))}
        </Grid>
      </Block>

      {error && <Alert severity="error">{error}</Alert>}
      <Box>
        <Button
          type="submit"
          variant="contained"
          size="large"
          disabled={busy || !hdtId}
          startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {t("newEpisode.submit")}
        </Button>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {t("newEpisode.next")}
        </Typography>
      </Box>
    </Stack>
  );
}
