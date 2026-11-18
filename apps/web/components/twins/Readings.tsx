import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations } from "next-intl/server";

import { Empty } from "@/components/ui/Page";
import { ForecastChart } from "@/components/workbench/ForecastChart";
import { ahdtClient } from "@/lib/api/client";

// LOINC codes of the vital signs and results the twin stores.
const CODES: Record<string, string> = {
  "8310-5": "temperature",
  "8867-4": "heart_rate",
  "9279-1": "respiratory_rate",
  "8480-6": "sbp",
  "8462-4": "dbp",
  "59408-5": "spo2",
  "2339-0": "glucose",
  "718-7": "hb",
};
const UNITS: Record<string, string> = { Cel: "°C", "mm[Hg]": "mmHg" };
const DAYS = 7;

// The person's latest readings over the past week, one small chart per measure.
export async function Readings({ token, hdtId }: { token: string; hdtId: string }) {
  const t = await getTranslations();
  const format = await getFormatter();
  const end = new Date();
  const start = new Date(end.getTime() - DAYS * 24 * 3600 * 1000);
  const r = await ahdtClient(token).POST("/v1/tools/ahdt.data.observations", {
    body: {
      hdt_id: hdtId,
      as_of: null,
      codes: Object.keys(CODES),
      period: { start: start.toISOString(), end: end.toISOString() },
      aggregate: "1h",
    },
  });
  if (r.response.status === 403) return <Empty>{t("readings.denied")}</Empty>;
  const series = Object.entries(r.data?.series ?? {})
    .map(([code, points]) => ({ code, points: points.filter((p) => typeof p.v === "number") }))
    .filter((s) => s.points.length > 0);
  if (!series.length) return <Empty>{t("readings.none")}</Empty>;
  return (
    <Grid container spacing={2}>
      {series.map(({ code, points }) => {
        const values = points.map((p) => p.v as number);
        const last = points[points.length - 1];
        const field = CODES[code] ?? code;
        return (
          <Grid key={code} size={{ xs: 12, sm: 6, md: 4 }}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="body2" color="text.secondary">
                {t.has(`measure.${field}`) ? t(`measure.${field}`) : field}
              </Typography>
              <Typography variant="h5" component="p" sx={{ fontWeight: 700 }}>
                {format.number(last.v as number, { maximumFractionDigits: 1 })} {UNITS[last.unit] ?? last.unit}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {format.dateTime(new Date(last.t), { dateStyle: "short", timeStyle: "short" })}
              </Typography>
              <ForecastChart
                t={points.map((p) => new Date(p.t).getTime())}
                mean={values}
                lower={values}
                upper={values}
                label={t("readings.chart", { measure: field })}
              />
            </Paper>
          </Grid>
        );
      })}
    </Grid>
  );
}
