import Alert from "@mui/material/Alert";
import Grid from "@mui/material/Grid";
import Typography from "@mui/material/Typography";
import { getTranslations } from "next-intl/server";

import { TwinTile } from "@/components/ui/TwinTile";
import { Link } from "@/i18n/navigation";
import { apdtClient } from "@/lib/api/client";
import type { Tenant } from "@/lib/clinical";

// The AHDT panel of one episode. Its 17 twin states can take several seconds, so pages
// render it inside <Suspense> and show the rest at once.
export async function TwinPanel({
  token,
  tenant,
  episodeId,
  linked = false,
}: {
  token: string;
  tenant: Tenant;
  episodeId: string;
  linked?: boolean;
}) {
  const t = await getTranslations();
  const panel = await apdtClient(token).GET("/v1/t/{tenant_id}/episodes/{episode_id}/ahdt-panel", {
    params: { path: { tenant_id: tenant, episode_id: episodeId } },
  });
  if (!panel.data) return <Alert severity="warning">{t("dashboard.unavailable")}</Alert>;
  return (
    <>
      {panel.data.degraded && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("workbench.degraded")}
        </Alert>
      )}
      <Grid container spacing={2}>
        {panel.data.tiles.map((tile) => {
          const card = (
            <TwinTile
              title={t(`twin.${tile.dt}`)}
              status={tile.status}
              statusLabel={t(`status.${tile.status}`)}
              headline={tile.headline}
            />
          );
          return (
            <Grid key={tile.dt} size={{ xs: 12, sm: 6, md: 4 }}>
              {linked ? (
                <Link
                  href={`/workbench/${episodeId}/twins/${tile.dt}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                  aria-label={t("workbench.openTwin", { twin: t(`twin.${tile.dt}`) })}
                >
                  {card}
                </Link>
              ) : (
                card
              )}
            </Grid>
          );
        })}
      </Grid>
    </>
  );
}

export async function TwinPanelLoading() {
  const t = await getTranslations();
  return <Typography color="text.secondary">{t("workbench.twinsLoading")}</Typography>;
}
