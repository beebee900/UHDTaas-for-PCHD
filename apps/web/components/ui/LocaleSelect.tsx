"use client";

import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import { useLocale, useTranslations } from "next-intl";

import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

export function LocaleSelect() {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  return (
    <TextField
      select
      size="small"
      label={t("app.language")}
      value={locale}
      onChange={(e) => router.replace(pathname, { locale: e.target.value })}
      sx={{
        minWidth: 140,
        "& .MuiInputBase-root, & .MuiSvgIcon-root": { color: "primary.contrastText" },
        "& .MuiOutlinedInput-notchedOutline, & .MuiInputBase-root:hover .MuiOutlinedInput-notchedOutline":
          { borderColor: "primary.contrastText" },
        "& .MuiInputLabel-root, & .MuiInputLabel-root.Mui-focused": { color: "primary.contrastText" },
      }}
    >
      {routing.locales.map((l) => (
        <MenuItem key={l} value={l}>
          {t(`locale.${l}`)}
        </MenuItem>
      ))}
    </TextField>
  );
}
