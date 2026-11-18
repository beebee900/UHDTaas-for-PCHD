import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["en", "yo", "ha", "ig", "pcm"],
  defaultLocale: "en",
});

export type Locale = (typeof routing.locales)[number];
