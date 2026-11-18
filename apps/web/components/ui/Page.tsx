import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { navFor } from "@/lib/roles";
import type { Session } from "@/lib/session";

import { AppShell } from "./AppShell";

// A signed-in page: the shell with the session's navigation. The token stays on the server.
export function Page({ session, children }: { session: Session; children: ReactNode }) {
  return (
    <AppShell
      user={{ sub: session.sub, role: session.role, tenantId: session.tenantId }}
      nav={navFor(session)}
    >
      <Stack gap={3}>{children}</Stack>
    </AppShell>
  );
}

export function PageHeader({
  overline,
  title,
  description,
  actions,
  children,
}: {
  overline?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} gap={2} justifyContent="space-between" alignItems={{ sm: "flex-end" }}>
      <Box sx={{ minWidth: 0 }}>
        {overline && (
          <Typography variant="overline" color="primary" component="p" sx={{ fontWeight: 700 }}>
            {overline}
          </Typography>
        )}
        <Typography variant="h4" component="h1" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        {description && (
          <Typography color="text.secondary" sx={{ mt: 0.5, maxWidth: 760 }}>
            {description}
          </Typography>
        )}
        {children}
      </Box>
      {actions && (
        <Stack direction="row" gap={1} flexWrap="wrap" sx={{ flexShrink: 0 }}>
          {actions}
        </Stack>
      )}
    </Stack>
  );
}

export function Section({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Paper component="section" variant="outlined" sx={{ p: { xs: 2, md: 2.5 } }} aria-labelledby={id}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={2} sx={{ mb: 1.5 }}>
        <Box>
          <Typography id={id} variant="h6" component="h2">
            {title}
          </Typography>
          {description && (
            <Typography variant="body2" color="text.secondary">
              {description}
            </Typography>
          )}
        </Box>
        {actions && <Stack direction="row" gap={1} flexWrap="wrap">{actions}</Stack>}
      </Stack>
      {children}
    </Paper>
  );
}

export function StatCard({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h4" component="p" sx={{ fontWeight: 700, my: 0.5 }}>
        {value}
      </Typography>
      {hint && (
        <Typography variant="caption" color="text.secondary">
          {hint}
        </Typography>
      )}
    </Paper>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <Typography color="text.secondary">{children}</Typography>;
}
