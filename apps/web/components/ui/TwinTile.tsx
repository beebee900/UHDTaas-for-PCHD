import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { StatusChip, type TwinStatus } from "./StatusChip";

export function TwinTile(props: {
  title: string;
  status: TwinStatus;
  statusLabel: string;
  headline: string;
}) {
  return (
    <Card variant="outlined" data-testid="twin-tile">
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}>
          <Typography variant="subtitle1" component="h3">
            {props.title}
          </Typography>
          <StatusChip status={props.status} label={props.statusLabel} />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {props.headline}
        </Typography>
      </CardContent>
    </Card>
  );
}
