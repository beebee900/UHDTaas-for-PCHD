import Grid from "@mui/material/Grid";
import { getTranslations } from "next-intl/server";

import { TwinTile } from "@/components/ui/TwinTile";
import { Link } from "@/i18n/navigation";
import { ahdtClient } from "@/lib/api/client";
import { PERSON_TWINS, type PersonTwin } from "@/lib/twins";

const BATCH = 3;

type Tile = { dt: PersonTwin; status: "normal" | "watch" | "alert" | "unavailable"; headline: string };

const label = (key: string) => key.replace(/_/g, " ");

// The person's member twins read straight from the AHDT (`ahdt.model.state`), a few at a time
// so the twin models are not all evaluated at once.
export async function PersonTwinGrid({ token, hdtId, basePath }: { token: string; hdtId: string; basePath: string }) {
  const t = await getTranslations();
  const api = ahdtClient(token);
  const tiles: Tile[] = [];
  for (let i = 0; i < PERSON_TWINS.length; i += BATCH) {
    const batch = PERSON_TWINS.slice(i, i + BATCH);
    const states = await Promise.all(batch.map((dt) => api.POST("/v1/tools/ahdt.model.state", { body: { dt, hdt_id: hdtId } })));
    batch.forEach((dt, j) => {
      const data = states[j].data;
      const shown = Object.entries(data?.state ?? {})
        .filter(([, v]) => typeof v === "number")
        .slice(0, 2)
        .map(([k, v]) => `${label(k)} ${Math.round((v as number) * 100) / 100}`);
      tiles.push({
        dt,
        status: data?.status ?? "unavailable",
        headline: data ? shown.join(", ") || t("drill.noState") : t("dashboard.unavailable"),
      });
    });
  }
  return (
    <Grid container spacing={2}>
      {tiles.map((tile) => (
        <Grid key={tile.dt} size={{ xs: 12, sm: 6, md: 4 }}>
          <Link
            href={`${basePath}/${tile.dt}`}
            style={{ textDecoration: "none", color: "inherit" }}
            aria-label={t("workbench.openTwin", { twin: t(`twin.${tile.dt}`) })}
          >
            <TwinTile title={t(`twin.${tile.dt}`)} status={tile.status} statusLabel={t(`status.${tile.status}`)} headline={tile.headline} />
          </Link>
        </Grid>
      ))}
    </Grid>
  );
}
