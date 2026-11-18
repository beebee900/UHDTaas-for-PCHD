"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { type FormEvent, type ReactNode, useState } from "react";

const CONDITIONS = ["cond.malaria_falciparum", "cond.hypertension", "cond.diabetes_type2", "cond.hiv", "cond.tb_pulmonary"];
const REGIONS = ["island_and_coast", "mainland_core", "north_west", "west_and_ikorodu"];
const FIELDS = ["temperature", "heart_rate", "respiratory_rate", "sbp", "spo2", "glucose", "hb", "creatinine"];

type Reply = { ok: boolean; data: Record<string, unknown> };

async function call(tool: string, args: Record<string, unknown>): Promise<Reply> {
  const r = await fetch("/api/population", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tool, args }),
  }).catch(() => null);
  const data = ((await r?.json().catch(() => null)) ?? { error: "unreachable" }) as Record<string, unknown>;
  return { ok: Boolean(r?.ok), data };
}

function Tool({ title, about, children }: { title: string; about: string; children: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.5 } }}>
      <Typography variant="h6" component="h2">
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {about}
      </Typography>
      {children}
    </Paper>
  );
}

function Rows({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            {columns.map((c) => (
              <TableCell key={c}>{c}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {columns.map((c) => (
                <TableCell key={c}>{typeof row[c] === "number" ? Math.round((row[c] as number) * 10000) / 10000 : String(row[c] ?? "")}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function Failed({ reply }: { reply: Reply | null }) {
  if (!reply || reply.ok) return null;
  return <Alert severity="warning">{String(reply.data.error ?? "")}</Alert>;
}

export function PopulationTools({ cohort }: { cohort: boolean }) {
  const t = useTranslations("population");
  const tm = useTranslations("measure");
  const [priors, setPriors] = useState<Reply | null>(null);
  const [norms, setNorms] = useState<Reply | null>(null);
  const [extract, setExtract] = useState<Reply | null>(null);
  const [fields, setFields] = useState<Set<string>>(new Set(["temperature", "sbp"]));
  const [mode, setMode] = useState<"dp" | "k">("dp");

  async function askPriors(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setPriors(
      await call("priors", {
        conditions: CONDITIONS,
        age_band: String(f.get("age")),
        sex: f.get("sex"),
        region: f.get("region"),
        season: f.get("season"),
      }),
    );
  }

  async function askNorms(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setNorms(await call("norms", { fields: FIELDS, age_band: String(f.get("age")), sex: f.get("sex") }));
  }

  async function askCohort(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const privacy = mode === "dp" ? { epsilon: Number(f.get("epsilon")) } : { k: Number(f.get("k")) };
    setExtract(await call("cohort", { fields: ["age_band", ...fields], privacy }));
  }

  const people = (
    <>
      <Grid size={{ xs: 6, md: 3 }}>
        <TextField name="age" type="number" label={t("age")} defaultValue={47} fullWidth slotProps={{ htmlInput: { min: 0, max: 110 } }} />
      </Grid>
      <Grid size={{ xs: 6, md: 3 }}>
        <TextField name="sex" select label={t("sex")} defaultValue="female" fullWidth>
          <MenuItem value="female">{t("female")}</MenuItem>
          <MenuItem value="male">{t("male")}</MenuItem>
        </TextField>
      </Grid>
    </>
  );

  const priorRows = (priors?.ok ? (priors.data.priors as Record<string, unknown>[]) : []) ?? [];
  const normRows = (norms?.ok ? (norms.data.norms as Record<string, unknown>[]) : []) ?? [];

  return (
    <Stack gap={2}>
      <Tool title={t("priors")} about={t("priorsAbout")}>
        <Grid container spacing={2} component="form" onSubmit={askPriors}>
          {people}
          <Grid size={{ xs: 6, md: 3 }}>
            <TextField name="region" select label={t("region")} defaultValue={REGIONS[1]} fullWidth>
              {REGIONS.map((r) => (
                <MenuItem key={r} value={r}>
                  {t(`regions.${r}`)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <TextField name="season" select label={t("season")} defaultValue="rainy" fullWidth>
              <MenuItem value="rainy">{t("rainy")}</MenuItem>
              <MenuItem value="dry">{t("dry")}</MenuItem>
            </TextField>
          </Grid>
          <Grid size={12}>
            <Button type="submit" variant="contained">
              {t("show")}
            </Button>
          </Grid>
        </Grid>
        <Failed reply={priors} />
        {priorRows.length > 0 && (
          <Rows
            rows={priorRows.map((r) => ({ ...r, prevalence: `${Math.round((r.prevalence as number) * 1000) / 10}%` }))}
            columns={["condition", "prevalence", "age_band", "season", "region", "source"]}
          />
        )}
      </Tool>

      <Tool title={t("norms")} about={t("normsAbout")}>
        <Grid container spacing={2} component="form" onSubmit={askNorms}>
          {people}
          <Grid size={{ xs: 12, md: 6 }}>
            <Button type="submit" variant="contained">
              {t("show")}
            </Button>
          </Grid>
        </Grid>
        <Failed reply={norms} />
        {normRows.length > 0 && <Rows rows={normRows} columns={["field", "unit", "p05", "p50", "p95", "n"]} />}
      </Tool>

      {cohort && (
        <Tool title={t("cohort")} about={t("cohortAbout")}>
          <Stack component="form" gap={2} onSubmit={askCohort}>
            <FormGroup row>
              {FIELDS.map((f) => (
                <FormControlLabel
                  key={f}
                  control={
                    <Checkbox
                      checked={fields.has(f)}
                      onChange={() =>
                        setFields((cur) => {
                          const next = new Set(cur);
                          if (next.has(f)) next.delete(f);
                          else next.add(f);
                          return next;
                        })
                      }
                    />
                  }
                  label={tm(f)}
                />
              ))}
            </FormGroup>
            <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
              <TextField select label={t("privacy")} value={mode} onChange={(e) => setMode(e.target.value as "dp" | "k")} sx={{ minWidth: 240 }}>
                <MenuItem value="dp">{t("dp")}</MenuItem>
                <MenuItem value="k">{t("k")}</MenuItem>
              </TextField>
              {mode === "dp" ? (
                <TextField name="epsilon" type="number" label={t("epsilon")} defaultValue={1} slotProps={{ htmlInput: { min: 0.01, step: 0.01 } }} />
              ) : (
                <TextField name="k" type="number" label={t("kValue")} defaultValue={5} slotProps={{ htmlInput: { min: 2 } }} />
              )}
            </Stack>
            <Box>
              <Button type="submit" variant="contained" disabled={fields.size === 0}>
                {t("extract")}
              </Button>
            </Box>
          </Stack>
          <Failed reply={extract} />
          {extract?.ok && (
            <Stack gap={1} sx={{ mt: 2 }}>
              <Typography variant="subtitle2">{t("privacyReport")}</Typography>
              <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: "action.hover", borderRadius: 2, overflowX: "auto", fontSize: 13 }}>
                {JSON.stringify(extract.data.privacy_report, null, 2)}
              </Box>
              {Array.isArray(extract.data.rows) && (
                <Rows rows={extract.data.rows as Record<string, unknown>[]} columns={["age_band", ...fields]} />
              )}
              {extract.data.aggregates != null && (
                <>
                  <Typography variant="subtitle2">{t("aggregates")}</Typography>
                  <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: "action.hover", borderRadius: 2, overflowX: "auto", fontSize: 13 }}>
                    {JSON.stringify(extract.data.aggregates, null, 2)}
                  </Box>
                </>
              )}
            </Stack>
          )}
        </Tool>
      )}
    </Stack>
  );
}
