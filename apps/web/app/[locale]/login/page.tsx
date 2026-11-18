"use client";

import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { AppShell } from "@/components/ui/AppShell";
import { useRouter } from "@/i18n/navigation";

// Demo user names by what they show; the passwords are in the demo login sheet.
const DEMO: { group: string; users: string[] }[] = [
  { group: "clinical", users: ["medical_officer.fac-a", "pharmacist.fac-b", "nurse.fac-a", "medical_officer.fac-b"] },
  { group: "patients", users: ["patient.ao", "proxy.bm", "person.de", "carer.de"] },
  { group: "governance", users: ["clinical_safety_officer.fac-a", "administrator.fac-a"] },
  { group: "population", users: ["researcher", "public_health_official"] },
];

export default function LoginPage() {
  const t = useTranslations();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setFailed(false);
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
    });
    setBusy(false);
    if (response.ok) router.push("/dashboard");
    else setFailed(true);
  }

  return (
    <AppShell>
      <Grid container spacing={3} sx={{ maxWidth: 1080, mx: "auto", alignItems: "stretch" }}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Stack gap={2}>
            <Typography variant="overline" color="primary" sx={{ fontWeight: 700 }}>
              {t("login.overline")}
            </Typography>
            <Typography variant="h4" component="p" sx={{ fontWeight: 700 }}>
              {t("login.headline")}
            </Typography>
            <Typography color="text.secondary">{t("login.about")}</Typography>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle1" component="h2" gutterBottom>
                {t("login.demo")}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t("login.demoAbout")}
              </Typography>
              <Stack gap={1.5} sx={{ mt: 1 }}>
                {DEMO.map(({ group, users }) => (
                  <div key={group}>
                    <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 0.5 }}>
                      {t(`login.groups.${group}`)}
                    </Typography>
                    <Stack direction="row" gap={0.75} flexWrap="wrap">
                      {users.map((u) => (
                        <Chip key={u} label={u} size="small" variant={u === username ? "filled" : "outlined"} color="primary" onClick={() => setUsername(u)} />
                      ))}
                    </Stack>
                  </div>
                ))}
              </Stack>
            </Paper>
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <Paper variant="outlined" sx={{ p: 3 }}>
            <Typography variant="h5" component="h1" gutterBottom>
              {t("login.title")}
            </Typography>
            <Stack component="form" onSubmit={submit} gap={2}>
              <TextField
                name="username"
                label={t("login.username")}
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
              <TextField name="password" type="password" label={t("login.password")} autoComplete="current-password" required />
              {failed && <Alert severity="error">{t("login.failed")}</Alert>}
              <Button type="submit" variant="contained" size="large" disabled={busy}>
                {t("login.submit")}
              </Button>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </AppShell>
  );
}
