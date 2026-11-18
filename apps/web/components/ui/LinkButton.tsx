"use client";

import Button, { type ButtonProps } from "@mui/material/Button";
import Chip, { type ChipProps } from "@mui/material/Chip";
import { useLocale } from "next-intl";

import { useRouter } from "@/i18n/navigation";

export function LinkButton({ href, ...props }: Omit<ButtonProps, "href"> & { href: string }) {
  const locale = useLocale();
  return <Button href={`/${locale}${href}`} {...props} />;
}

export function LinkChip({ href, ...props }: Omit<ChipProps, "onClick"> & { href: string }) {
  const router = useRouter();
  return <Chip clickable onClick={() => router.push(href)} {...props} />;
}
