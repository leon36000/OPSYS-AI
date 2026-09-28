export const LANGUE_PAR_DEFAUT = "fr-CA" as const;
export const LANGUES_DISPONIBLES = ["fr-CA", "en-CA"] as const;
export type LangueDisponible = (typeof LANGUES_DISPONIBLES)[number];

/**
 * fr-CA par défaut (P12 AGENTS.md, R12 §3) ; en-CA seulement si l'appareil le demande
 * explicitement (premier tag `expo-localization` qui commence par "fr"/"en", dans l'ordre de
 * préférence de l'appareil). Fonction pure : aucun appel à `expo-localization` ici — c'est
 * `src/i18n/index.ts` qui lui fournit les tags réels de l'appareil, ce qui garde cette
 * résolution testable sans dépendance native.
 */
export function resoudreLangueDemarrage(tagsAppareil: readonly string[]): LangueDisponible {
  for (const tag of tagsAppareil) {
    const prefixe = tag.trim().toLowerCase().slice(0, 2);
    if (prefixe === "en") {
      return "en-CA";
    }
    if (prefixe === "fr") {
      return "fr-CA";
    }
  }
  return LANGUE_PAR_DEFAUT;
}
