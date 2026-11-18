"use client";

import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import Link from "@mui/material/Link";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";

import { type Bundle, percent } from "@/lib/clinical";

import { SourceChip } from "./SourceChip";

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <Typography variant="subtitle1" component="h3" gutterBottom>
        {title}
      </Typography>
      {children}
    </section>
  );
}

export function WhyPanel({ bundle }: { bundle: Bundle }) {
  const t = useTranslations("why");
  const source = useTranslations("workbench.source");
  const [open, setOpen] = useState(false);
  const trace = bundle.simulation_trace;
  return (
    <>
      <Button size="small" variant="outlined" onClick={() => setOpen(true)}>
        {t("button")}
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md" scroll="paper">
        <DialogTitle component="h2">{t("title")}</DialogTitle>
        <DialogContent dividers>
          <Stack gap={2} divider={<Divider flexItem />}>
            <Part title={t("recommendation")}>
              <Typography>{bundle.recommendation.text}</Typography>
              <Typography color="text.secondary">
                {t("confidence", { value: percent(bundle.recommendation.confidence) })}
              </Typography>
            </Part>
            <Part title={t("evidenceFor")}>
              <EvidenceList items={bundle.evidence_for} label={source} empty={t("none")} />
            </Part>
            <Part title={t("evidenceAgainst")}>
              <EvidenceList items={bundle.evidence_against} label={source} empty={t("none")} />
            </Part>
            <Part title={t("citations")}>
              {bundle.citations.length ? (
                <List dense disablePadding>
                  {bundle.citations.map((c) => (
                    <ListItem key={c.kb_entry_id} disableGutters>
                      <ListItemText
                        primary={
                          c.url ? (
                            <Link href={c.url} target="_blank" rel="noreferrer">
                              {c.source_title}
                            </Link>
                          ) : (
                            c.source_title
                          )
                        }
                        secondary={c.section}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Typography color="text.secondary">{t("none")}</Typography>
              )}
            </Part>
            <Part title={t("counterfactuals")}>
              {bundle.counterfactuals.length ? (
                <List dense disablePadding>
                  {bundle.counterfactuals.map((c) => (
                    <ListItem key={c.change} disableGutters>
                      <ListItemText
                        primary={t("counterfactual", { change: c.change, top: c.new_top })}
                        secondary={t("change", { value: c.delta.toFixed(2) })}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Typography color="text.secondary">{t("none")}</Typography>
              )}
            </Part>
            <Part title={t("simulation")}>
              {trace ? (
                <>
                  <Typography>{trace.summary}</Typography>
                  <Typography color="text.secondary">
                    {t("assumptions", { items: trace.assumptions.join("; ") })}
                  </Typography>
                </>
              ) : (
                <Typography color="text.secondary">{t("noSimulation")}</Typography>
              )}
            </Part>
            <Part title={t("alternatives")}>
              {bundle.alternatives.length ? (
                <List dense disablePadding>
                  {bundle.alternatives.map((a) => (
                    <ListItem key={a.text} disableGutters>
                      <ListItemText
                        primary={`${a.text} (${percent(a.score)})`}
                        secondary={a.why_lower}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Typography color="text.secondary">{t("none")}</Typography>
              )}
            </Part>
            <Part title={t("patientSummary")}>
              <Typography>{bundle.patient_summary.text}</Typography>
            </Part>
            <Part title={t("models")}>
              <Typography color="text.secondary">
                {bundle.model_versions.map((m) => `${m.model_id} ${m.version}`).join(", ")}
              </Typography>
            </Part>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>{t("close")}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function EvidenceList({
  items,
  label,
  empty,
}: {
  items: Bundle["evidence_for"];
  label: (source: "apdt" | "ahdt") => string;
  empty: string;
}) {
  if (!items.length) return <Typography color="text.secondary">{empty}</Typography>;
  return (
    <List dense disablePadding>
      {items.map((e) => (
        <ListItem key={`${e.source}-${e.item}`} disableGutters sx={{ gap: 1 }}>
          <SourceChip source={e.source} label={label(e.source)} />
          <ListItemText primary={e.item} secondary={e.weight.toFixed(1)} />
        </ListItem>
      ))}
    </List>
  );
}
