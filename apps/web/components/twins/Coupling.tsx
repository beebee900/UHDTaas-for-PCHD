import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { getTranslations } from "next-intl/server";

import { ahdtClient } from "@/lib/api/client";

// How the person's member twins feed each other: connectors from each source twin.
export async function Coupling({ token, hdtId }: { token: string; hdtId: string }) {
  const t = await getTranslations();
  const r = await ahdtClient(token).GET("/v1/persons/{hdt_id}/coupling", {
    params: { path: { hdt_id: hdtId } },
  });
  if (!r.data) return <Alert severity="info">{t("coupling.notRunning")}</Alert>;
  const rows = Object.entries(r.data.matrix)
    .map(([source, targets]) => ({
      source,
      targets: Object.entries(targets).filter(([, names]) => names.length > 0),
    }))
    .filter((row) => row.targets.length > 0)
    .sort((a, b) => b.targets.length - a.targets.length);
  const name = (dt: string) => (t.has(`twin.${dt}`) ? t(`twin.${dt}`) : dt);
  return (
    <Stack gap={1}>
      <Typography variant="body2" color="text.secondary">
        {t("coupling.count", { count: r.data.count })}
      </Typography>
      <Table size="small" aria-label={t("coupling.title")}>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.source}>
              <TableCell component="th" scope="row" sx={{ width: "28%", fontWeight: 650 }}>
                {name(row.source)}
              </TableCell>
              <TableCell>
                <Stack direction="row" gap={0.75} flexWrap="wrap">
                  {row.targets.map(([target, names]) => (
                    <Chip
                      key={target}
                      size="small"
                      variant="outlined"
                      label={`${name(target)} · ${names.length}`}
                      title={names.join(", ")}
                    />
                  ))}
                </Stack>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Stack>
  );
}
