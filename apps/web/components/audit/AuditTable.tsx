import Chip from "@mui/material/Chip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { getFormatter, getTranslations } from "next-intl/server";

import { Empty } from "@/components/ui/Page";
import type { AuditRecord } from "@/lib/data";

const OUTCOME = { ok: "success", denied: "error", degraded: "warning", error: "error" } as const;

export async function AuditTable({ records, showEpisode = true }: { records: AuditRecord[]; showEpisode?: boolean }) {
  const t = await getTranslations("audit");
  const format = await getFormatter();
  if (!records.length) return <Empty>{t("none")}</Empty>;
  return (
    <TableContainer sx={{ maxHeight: 640 }}>
      <Table size="small" stickyHeader aria-label={t("title")}>
        <TableHead>
          <TableRow>
            <TableCell>{t("seq")}</TableCell>
            <TableCell>{t("time")}</TableCell>
            <TableCell>{t("actor")}</TableCell>
            <TableCell>{t("action")}</TableCell>
            {showEpisode && <TableCell>{t("episode")}</TableCell>}
            <TableCell>{t("outcome")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {records.map((r) => (
            <TableRow key={`${r.seq}-${r.hash}`} hover>
              <TableCell>
                <Typography variant="body2">{r.seq}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }} title={r.hash}>
                  {r.hash.slice(0, 10)}
                </Typography>
              </TableCell>
              <TableCell sx={{ whiteSpace: "nowrap" }}>
                {format.dateTime(new Date(r.t), { dateStyle: "short", timeStyle: "medium" })}
              </TableCell>
              <TableCell>
                <Typography variant="body2">{r.actor.id}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {r.agent ? t("viaAgent", { agent: r.agent, role: r.actor.role }) : r.actor.role}
                </Typography>
              </TableCell>
              <TableCell>
                <Typography variant="body2">{r.action}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-all" }}>
                  {r.target}
                </Typography>
              </TableCell>
              {showEpisode && <TableCell>{r.episode_id ?? ""}</TableCell>}
              <TableCell>
                <Chip size="small" color={OUTCOME[r.outcome]} label={t(`outcomes.${r.outcome}`)} />
                {r.reason && (
                  <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.5 }}>
                    {r.reason}
                  </Typography>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
