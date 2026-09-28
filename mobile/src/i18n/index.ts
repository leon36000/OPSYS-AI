import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import * as Localization from "expo-localization";

import enCA from "./locales/en-CA";
import frCA from "./locales/fr-CA";
import { LANGUE_PAR_DEFAUT, resoudreLangueDemarrage } from "./langue";

const tagsAppareil = Localization.getLocales().map((locale) => locale.languageTag);

/** Initialise i18next pour toute l'app (importé une fois depuis app/_layout.tsx, avant le
 * premier rendu). fr-CA par défaut, en-CA en réserve (R12 §3, P12 AGENTS.md). */
void i18n.use(initReactI18next).init({
  resources: {
    "fr-CA": { commun: frCA },
    "en-CA": { commun: enCA },
  },
  lng: resoudreLangueDemarrage(tagsAppareil),
  fallbackLng: LANGUE_PAR_DEFAUT,
  defaultNS: "commun",
  interpolation: { escapeValue: false },
});

export default i18n;
