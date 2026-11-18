"use client";

import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

export type WorkbenchTab = "review" | "twins" | "ask" | "activity";

export function WorkbenchNav({
  episodeId,
  active,
  tabs,
}: {
  episodeId: string;
  active: WorkbenchTab;
  tabs: WorkbenchTab[];
}) {
  const t = useTranslations("workbench.tabs");
  const href = (tab: WorkbenchTab) =>
    tab === "review" ? `/workbench/${episodeId}` : `/workbench/${episodeId}/${tab}`;
  return (
    <Tabs
      value={active}
      variant="scrollable"
      allowScrollButtonsMobile
      aria-label={t("label")}
      sx={{ borderBottom: 1, borderColor: "divider" }}
    >
      {tabs.map((tab) => (
        <Tab key={tab} value={tab} label={t(tab)} component={Link} href={href(tab)} />
      ))}
    </Tabs>
  );
}
