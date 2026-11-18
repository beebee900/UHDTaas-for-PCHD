"use client";

import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";

import { Link, usePathname } from "@/i18n/navigation";
import type { NavItem } from "@/lib/roles";

import { LocaleSelect } from "./LocaleSelect";
import { SignOutButton } from "./SignOutButton";

const DRAWER = 252;

export type ShellUser = { sub: string; role: string; tenantId?: string };

function MenuGlyph() {
  return (
    <Box component="span" aria-hidden sx={{ display: "grid", gap: "4px", width: 20 }}>
      {[0, 1, 2].map((i) => (
        <Box key={i} sx={{ height: 2, bgcolor: "currentColor", borderRadius: 1 }} />
      ))}
    </Box>
  );
}

function NavList({ nav, onNavigate }: { nav: NavItem[]; onNavigate?: () => void }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  return (
    <List component="nav" aria-label={t("label")} sx={{ px: 1 }}>
      {nav.map((item) => {
        const active =
          item.href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(item.href);
        return (
          <ListItemButton
            key={item.key}
            component={Link}
            href={item.href}
            selected={active}
            aria-current={active ? "page" : undefined}
            onClick={onNavigate}
            sx={{ borderRadius: 2, mb: 0.5 }}
          >
            <ListItemText primary={t(item.key)} />
          </ListItemButton>
        );
      })}
    </List>
  );
}

export function AppShell({
  user,
  nav = [],
  actions,
  children,
}: {
  user?: ShellUser;
  nav?: NavItem[];
  actions?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const hasNav = nav.length > 0;
  const drawer = (
    <Stack sx={{ height: "100%" }}>
      <Toolbar />
      <NavList nav={nav} onNavigate={() => setOpen(false)} />
      {user && (
        <Box sx={{ mt: "auto", p: 2 }}>
          <Divider sx={{ mb: 2 }} />
          <Typography variant="caption" color="text.secondary" component="p">
            {t("shell.signedInAs")}
          </Typography>
          <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
            {user.sub}
          </Typography>
        </Box>
      )}
    </Stack>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="fixed" color="primary" elevation={0} sx={{ zIndex: (th) => th.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 1.5, flexWrap: "wrap", py: 1 }}>
          {hasNav && (
            <IconButton
              color="inherit"
              edge="start"
              aria-label={t("shell.openMenu")}
              onClick={() => setOpen(true)}
              sx={{ display: { md: "none" } }}
            >
              <MenuGlyph />
            </IconButton>
          )}
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="h6" component="p" sx={{ lineHeight: 1.2, fontWeight: 700 }}>
              {t("app.title")}
            </Typography>
            <Typography variant="caption" component="p" sx={{ opacity: 0.85, display: { xs: "none", sm: "block" } }}>
              {t("app.tagline")}
            </Typography>
          </Box>
          {user && (
            <Chip
              label={
                user.tenantId
                  ? t("shell.roleAt", { role: t(`role.${user.role}`), facility: t(`facility.${user.tenantId}`) })
                  : t(`role.${user.role}`)
              }
              sx={{ bgcolor: "rgba(255,255,255,0.16)", color: "inherit", display: { xs: "none", sm: "flex" } }}
            />
          )}
          <LocaleSelect />
          {actions}
          {user && <SignOutButton label={t("dashboard.signOut")} />}
        </Toolbar>
      </AppBar>
      {hasNav && (
        <>
          <Drawer
            variant="temporary"
            open={open}
            onClose={() => setOpen(false)}
            ModalProps={{ keepMounted: true }}
            sx={{ display: { xs: "block", md: "none" }, "& .MuiDrawer-paper": { width: DRAWER } }}
          >
            {drawer}
          </Drawer>
          <Drawer
            variant="permanent"
            sx={{
              display: { xs: "none", md: "block" },
              width: DRAWER,
              flexShrink: 0,
              "& .MuiDrawer-paper": { width: DRAWER, boxSizing: "border-box", borderRight: 1, borderColor: "divider" },
            }}
          >
            {drawer}
          </Drawer>
        </>
      )}
      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, px: { xs: 2, md: 4 }, py: 3 }}>
        <Toolbar sx={{ mb: { xs: 2, sm: 1 } }} />
        <Box sx={{ maxWidth: 1200, mx: "auto" }}>{children}</Box>
      </Box>
    </Box>
  );
}
