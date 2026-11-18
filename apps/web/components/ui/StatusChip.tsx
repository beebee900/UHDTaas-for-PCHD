import Chip from "@mui/material/Chip";

export type TwinStatus = "normal" | "watch" | "alert" | "unavailable";

const COLOURS = {
  normal: "success",
  watch: "warning",
  alert: "error",
  unavailable: "default",
} as const;

export function StatusChip({ status, label }: { status: TwinStatus; label: string }) {
  return <Chip size="small" color={COLOURS[status]} label={label} />;
}
