import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations } from "next-intl/server";

import { LinkButton } from "@/components/ui/LinkButton";
import type { EpisodeListItem } from "@/lib/data";

export async function EpisodeTable({ items }: { items: EpisodeListItem[] }) {
  const t = await getTranslations();
  const format = await getFormatter();
  if (!items.length) return <Typography color="text.secondary">{t("episodes.none")}</Typography>;
  return (
    <TableContainer>
      <Table size="small" aria-label={t("episodes.title")}>
        <TableHead>
          <TableRow>
            <TableCell>{t("episodes.patient")}</TableCell>
            <TableCell>{t("episodes.reason")}</TableCell>
            <TableCell>{t("episodes.opened")}</TableCell>
            <TableCell>{t("episodes.status")}</TableCell>
            <TableCell align="right">{t("episodes.actions")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map(({ episode: ep, patient }) => (
            <TableRow key={ep.episode_id} hover>
              <TableCell component="th" scope="row">
                <Typography variant="body2" sx={{ fontWeight: 650 }}>
                  {patient?.initials ?? ep.hdt_id}
                </Typography>
                {patient && (
                  <Typography variant="caption" color="text.secondary">
                    {t("episodes.who", { sex: t(`sex.${patient.sex}`), age: patient.age_years })}
                  </Typography>
                )}
              </TableCell>
              <TableCell>{ep.reason}</TableCell>
              <TableCell>
                {format.dateTime(new Date(ep.opened_at), { dateStyle: "medium", timeStyle: "short" })}
              </TableCell>
              <TableCell>
                <Chip
                  size="small"
                  color={ep.status === "open" ? "success" : "default"}
                  label={t(`workbench.episodeStatus.${ep.status}`)}
                />
              </TableCell>
              <TableCell align="right">
                <Stack direction="row" gap={1} justifyContent="flex-end" flexWrap="wrap">
                  <LinkButton size="small" variant="outlined" href={`/workbench/${ep.episode_id}`}>
                    {t("episodes.workbench")}
                  </LinkButton>
                  <LinkButton size="small" href={`/workbench/${ep.episode_id}/twins`}>
                    {t("episodes.twins")}
                  </LinkButton>
                </Stack>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
