import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

type Messages = { [key: string]: string | Messages };

// Messages a locale file does not translate yet are shown in English.
function merge(base: Messages, override: Messages): Messages {
  const out: Messages = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const current = out[key];
    out[key] =
      typeof value === "object" && typeof current === "object" ? merge(current, value) : value;
  }
  return out;
}

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  const english = (await import("../messages/en.json")).default as Messages;
  const own = (await import(`../messages/${locale}.json`)).default as Messages;
  return { locale, messages: merge(english, own) };
});
