import Chip from "@mui/material/Chip";

export function SourceChip({ source, label }: { source: "apdt" | "ahdt"; label: string }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      color={source === "ahdt" ? "secondary" : "primary"}
      label={label}
      data-testid={`source-${source}`}
    />
  );
}
