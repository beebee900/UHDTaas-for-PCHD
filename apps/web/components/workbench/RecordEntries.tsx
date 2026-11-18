import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import { getFormatter, getTranslations } from "next-intl/server";

import { Empty } from "@/components/ui/Page";
import type { ClinicalEntry } from "@/lib/clinical";

// The entries of one part of the clinical record, newest first, with who entered them and when.
export async function RecordEntries({ entries, empty }: { entries: ClinicalEntry[]; empty: string }) {
  const t = await getTranslations();
  const format = await getFormatter();
  if (!entries.length) return <Empty>{empty}</Empty>;
  return (
    <List dense disablePadding data-testid="record-entries">
      {entries.map((e) => (
        <ListItem key={e.entry_id} divider disableGutters>
          <ListItemText
            primary={e.title}
            secondary={
              <>
                {(e.details ?? []).join(". ")}
                <br />
                {t("record.by", {
                  role: t(`role.${e.recorded_by.role}`),
                  id: e.recorded_by.id,
                  time: format.dateTime(new Date(e.recorded_at), { dateStyle: "medium", timeStyle: "short" }),
                })}
              </>
            }
          />
        </ListItem>
      ))}
    </List>
  );
}
