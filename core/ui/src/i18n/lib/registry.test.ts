// @vitest-environment node

import { describe, expect, it } from "vitest";
import { de } from "../locales/de.ts";
import { es } from "../locales/es.ts";
import { fr } from "../locales/fr.ts";
import { fr_CA } from "../locales/fr-CA.ts";
import { hi } from "../locales/hi.ts";
import { pt_BR } from "../locales/pt-BR.ts";
import { ru } from "../locales/ru.ts";
import { th } from "../locales/th.ts";
import { zh_CN } from "../locales/zh-CN.ts";
import {
  DEFAULT_LOCALE,
  loadLazyLocaleTranslation,
  PRODUCT_DEFAULT_LOCALE,
  resolveNavigatorLocale,
  SUPPORTED_LOCALES,
} from "./registry.ts";

describe("resolveNavigatorLocale", () => {
  it.each([
    ["zh", "zh-CN"],
    ["zh-CN", "zh-CN"],
    ["zh-SG", "zh-CN"],
    ["zh-Hans", "zh-CN"],
    ["zh-Hans-CN", "zh-CN"],
    ["zh-Hans-SG", "zh-CN"],
    ["zh-Hans-HK", "zh-CN"],
    ["zh-Hans-TW", "zh-CN"],
    ["zh-Hant", "zh-TW"],
    ["zh-Hant-TW", "zh-TW"],
    ["zh-Hant-HK", "zh-TW"],
    ["zh-Hant-MO", "zh-TW"],
    ["zh-TW", "zh-TW"],
    ["zh-HK", "zh-TW"],
    ["zh-MO", "zh-TW"],
    ["ZH-hAnT-hK", "zh-TW"],
    ["ZH-hAnS-hK", "zh-CN"],
    ["en-US", "en"],
    ["pt-PT", "pt-BR"],
    ["PT-br", "pt-BR"],
    ["de-DE", "de"],
    ["DE-at", "de"],
    ["es-MX", "es"],
    ["ja-JP", "ja-JP"],
    ["ko-KR", "ko"],
    ["fr-CA", "fr-CA"],
    ["FR-ca", "fr-CA"],
    ["fr", "fr-CA"],
    ["fr-FR", "fr"],
    ["fr-BE", "fr"],
    ["fr-CH", "fr"],
    ["fr-Latn-FR", "fr"],
    ["fr-Latn", "fr-CA"],
    ["hi-IN", "hi"],
    ["ar-EG", "ar"],
    ["it-IT", "it"],
    ["tr-TR", "tr"],
    ["uk-UA", "uk"],
    ["id-ID", "id"],
    ["pl-PL", "pl"],
    ["th-TH", "th"],
    ["vi-VN", "vi"],
    ["nl-NL", "nl"],
    ["fa-IR", "fa"],
    ["ru-RU", "ru"],
    ["en", "en"],
    ["en-CA", "en"],
    ["EN-gb", "en"],
    ["sv-SE", "fr-CA"],
    ["", "fr-CA"],
  ] as const)("maps browser language %s to %s", (browserLanguage, expectedLocale) => {
    expect(resolveNavigatorLocale(browserLanguage)).toBe(expectedLocale);
  });
});

describe("lazy locale registry", () => {
  it("keeps English as the source catalog and Quebec French as the product default", () => {
    expect(DEFAULT_LOCALE).toBe("en");
    expect(PRODUCT_DEFAULT_LOCALE).toBe("fr-CA");
    expect(SUPPORTED_LOCALES).toContain(PRODUCT_DEFAULT_LOCALE);
    expect(SUPPORTED_LOCALES.indexOf("fr-CA")).toBe(SUPPORTED_LOCALES.indexOf("fr") + 1);
  });

  it("materializes every registered foreign catalog", async () => {
    expect(SUPPORTED_LOCALES).toHaveLength(22);
    expect(await loadLazyLocaleTranslation("en")).toBeNull();

    const catalogs = await Promise.all(
      SUPPORTED_LOCALES.slice(1).map(
        async (locale) => [locale, await loadLazyLocaleTranslation(locale)] as const,
      ),
    );
    for (const [locale, catalog] of catalogs) {
      expect(catalog?.common, locale).toHaveProperty("health");
    }
    const byLocale = Object.fromEntries(catalogs);
    for (const [locale, expected] of Object.entries({
      de,
      es,
      fr,
      "fr-CA": fr_CA,
      "pt-BR": pt_BR,
      "zh-CN": zh_CN,
      hi,
      th,
      ru,
    })) {
      expect(byLocale[locale], locale).toEqual(expected);
    }
  });
});
