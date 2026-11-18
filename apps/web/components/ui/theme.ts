"use client";

import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "media" },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#0f6b5c" },
        secondary: { main: "#7a4b9e" },
        background: { default: "#f4f6f8", paper: "#ffffff" },
        divider: "#dde3e8",
      },
    },
    dark: {
      palette: {
        primary: { main: "#5fc7b4" },
        secondary: { main: "#c3a2e0" },
        background: { default: "#0f1318", paper: "#171d25" },
        divider: "#2a333f",
      },
    },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans', sans-serif",
    h4: { fontSize: "1.85rem", letterSpacing: "-0.01em" },
    h6: { fontSize: "1.1rem", fontWeight: 650 },
    overline: { letterSpacing: "0.08em" },
  },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { textTransform: "none", fontWeight: 600, borderRadius: 10 } },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
    MuiPaper: { styleOverrides: { outlined: { borderColor: "var(--mui-palette-divider)" } } },
    MuiCard: { styleOverrides: { root: { borderColor: "var(--mui-palette-divider)" } } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 650 } } },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          "&.Mui-selected": {
            backgroundColor: "rgba(var(--mui-palette-primary-mainChannel) / 0.12)",
            color: "var(--mui-palette-primary-main)",
            fontWeight: 650,
          },
        },
      },
    },
  },
});
