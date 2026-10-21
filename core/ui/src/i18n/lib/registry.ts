// Control UI i18n module implements registry behavior.
import type { Locale, TranslationMap } from "./types.ts";

type LazyLocale = Exclude<Locale, "en">;
type LocaleModule = Record<string, TranslationMap>;

// English is the source catalog: it ships in the startup bundle and answers every missing key.
export const DEFAULT_LOCALE: Locale = "en";
// OPSYS ships in Quebec French. It loads on demand like every other catalog, so it costs the
// startup bundle nothing; it applies when the browser language names no supported locale.
export const PRODUCT_DEFAULT_LOCALE: Locale = "fr-CA";
// Region subtags (France, Belgium, Switzerland, Luxembourg, Monaco) that keep the plain French
// catalog. Bare "fr", "fr-CA" and every other French tag get Quebec French.
const EUROPEAN_FRENCH_REGIONS: ReadonlySet<string> = new Set(["fr", "be", "ch", "lu", "mc"]);

const LAZY_LOCALE_REGISTRY: Record<LazyLocale, () => Promise<LocaleModule>> = {
  "zh-CN": () => import("../locales/zh-CN.ts"),
  "zh-TW": () => import("../locales/zh-TW.ts"),
  "pt-BR": () => import("../locales/pt-BR.ts"),
  de: () => import("../locales/de.ts"),
  es: () => import("../locales/es.ts"),
  "ja-JP": () => import("../locales/ja-JP.ts"),
  ko: () => import("../locales/ko.ts"),
  fr: () => import("../locales/fr.ts"),
  "fr-CA": () => import("../locales/fr-CA.ts"),
  hi: () => import("../locales/hi.ts"),
  ar: () => import("../locales/ar.ts"),
  it: () => import("../locales/it.ts"),
  tr: () => import("../locales/tr.ts"),
  uk: () => import("../locales/uk.ts"),
  id: () => import("../locales/id.ts"),
  pl: () => import("../locales/pl.ts"),
  th: () => import("../locales/th.ts"),
  vi: () => import("../locales/vi.ts"),
  nl: () => import("../locales/nl.ts"),
  fa: () => import("../locales/fa.ts"),
  ru: () => import("../locales/ru.ts"),
};
// SAFETY: The record contract guarantees every own key is a LazyLocale.
const LAZY_LOCALES = Object.keys(LAZY_LOCALE_REGISTRY) as LazyLocale[];

export const SUPPORTED_LOCALES: ReadonlyArray<Locale> = [DEFAULT_LOCALE, ...LAZY_LOCALES];

export function isSupportedLocale(value: string | null | undefined): value is Locale {
  return value !== null && value !== undefined && SUPPORTED_LOCALES.includes(value as Locale);
}

function isLazyLocale(locale: Locale): locale is LazyLocale {
  return LAZY_LOCALES.includes(locale as LazyLocale);
}

export function resolveNavigatorLocale(browserLanguage: string): Locale {
  const navLang = browserLanguage.toLowerCase();
  if (navLang.startsWith("zh")) {
    const [, ...subtags] = navLang.split("-");
    if (subtags.includes("hant")) {
      return "zh-TW";
    }
    if (subtags.includes("hans")) {
      return "zh-CN";
    }
    return subtags.some((subtag) => subtag === "tw" || subtag === "hk" || subtag === "mo")
      ? "zh-TW"
      : "zh-CN";
  }
  if (navLang === "fr" || navLang.startsWith("fr-")) {
    const [, ...subtags] = navLang.split("-");
    return subtags.some((subtag) => EUROPEAN_FRENCH_REGIONS.has(subtag)) ? "fr" : "fr-CA";
  }
  if (navLang === "en" || navLang.startsWith("en-")) {
    return DEFAULT_LOCALE;
  }
  return (
    LAZY_LOCALES.find((locale) => navLang.startsWith(locale.split("-")[0]!.toLowerCase())) ??
    PRODUCT_DEFAULT_LOCALE
  );
}

export async function loadLazyLocaleTranslation(locale: Locale): Promise<TranslationMap | null> {
  if (!isLazyLocale(locale)) {
    return null;
  }
  const module = await LAZY_LOCALE_REGISTRY[locale]();
  return module[locale.replaceAll("-", "_")] ?? null;
}
