import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { LinkChip } from "@/components/ui/LinkButton";
import { Empty, Section } from "@/components/ui/Page";
import { StatusChip } from "@/components/ui/StatusChip";
import { ForecastChart } from "@/components/workbench/ForecastChart";
import { ahdtClient } from "@/lib/api/client";
import type { PersonTwin } from "@/lib/twins";

const HORIZON_H = 24;
const isNumber = (value: unknown): value is number => typeof value === "number";
const label = (key: string) => {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

// One member twin: its current state, a forecast of one state variable, and an agents slot.
export async function TwinDetail({
  token,
  hdtId,
  dt,
  requested,
  basePath,
  agents,
}: {
  token: string;
  hdtId: string;
  dt: PersonTwin;
  requested?: string;
  basePath: string;
  agents?: ReactNode;
}) {
  const t = await getTranslations();
  const format = await getFormatter();
  const api = ahdtClient(token);
  const state = await api.POST("/v1/tools/ahdt.model.state", { body: { dt, hdt_id: hdtId } });
  const entries = Object.entries(state.data?.state ?? {});
  const variables = entries.filter(([, v]) => isNumber(v)).map(([k]) => k);
  const variable = requested && variables.includes(requested) ? requested : variables[0];
  const forecast = variable
    ? await api.POST("/v1/tools/ahdt.model.forecast", {
        body: { dt, hdt_id: hdtId, variable, horizon_h: HORIZON_H },
      })
    : null;
  const fc = forecast?.data;
  const number = (v: number) => format.number(v, { maximumFractionDigits: 2 });

  return (
    <>
      <Stack direction="row" gap={2} alignItems="center" flexWrap="wrap">
        <Typography color="text.secondary">{t(`twinAbout.${dt}`)}</Typography>
        {state.data && <StatusChip status={state.data.status} label={t(`status.${state.data.status}`)} />}
      </Stack>
      {state.response.status === 403 && <Alert severity="info">{t("drill.denied")}</Alert>}

      <Section
        id="state"
        title={t("drill.state")}
        description={
          state.data
            ? t("drill.updated", {
                time: format.dateTime(new Date(state.data.updated_at), { dateStyle: "short", timeStyle: "short" }),
              })
            : undefined
        }
      >
        {state.data ? (
          entries.length ? (
            <Table size="small" aria-labelledby="state">
              <TableHead>
                <TableRow>
                  <TableCell>{t("drill.variable")}</TableCell>
                  <TableCell align="right">{t("drill.value")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {entries.map(([key, value]) => (
                  <TableRow key={key}>
                    <TableCell component="th" scope="row">
                      {label(key)}{" "}
                      <Typography component="span" variant="caption" color="text.secondary">
                        {key}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{isNumber(value) ? number(value) : String(value)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Empty>{t("drill.noState")}</Empty>
          )
        ) : (
          <Alert severity="warning">{t("dashboard.unavailable")}</Alert>
        )}
      </Section>

      <Section id="forecast" title={t("drill.forecast")} description={t("drill.forecastAbout")}>
        {variables.length > 0 && (
          <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mb: 2 }}>
            {variables.map((v) => (
              <LinkChip
                key={v}
                size="small"
                label={label(v)}
                color={v === variable ? "primary" : "default"}
                href={`${basePath}?variable=${encodeURIComponent(v)}`}
              />
            ))}
          </Stack>
        )}
        {fc ? (
          <>
            <Typography color="text.secondary" gutterBottom>
              {t("drill.forecastOf", { variable: label(variable ?? ""), level: Math.round(fc.level * 100) })}
            </Typography>
            <ForecastChart
              t={fc.t}
              mean={fc.mean}
              lower={fc.lower}
              upper={fc.upper}
              label={t("drill.chartLabel", { variable: label(variable ?? "") })}
            />
          </>
        ) : (
          <Empty>{t("drill.noForecast")}</Empty>
        )}
      </Section>
      {agents}
    </>
  );
}
