import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * Lecture commune de la réponse d'un outil lu ou écrit par le vendeur (`m2_*`, `m3_lire_devis`), forme
 * confirmée dans `src/opsys/outils.py` (`executer`, `depuis_couple`) et `src/opsys/capacites.py`
 * (`_tronquer`) : un appel réussi de `/tools/invoke` rend `{ok: true, result: X}` où `X` est
 *  - `{ok: true, resultat: Y, rejoue?: bool}` avec `Y = {accepte: true, resultat: R}` ou
 *    `Y = {accepte: false, verdict: {code, statut, detail}}` (refus métier : une réponse normale) ;
 *  - `{ok: false, erreur, details}` (refus technique : `arguments_invalides`, `mutation_conflit`...) ;
 *  - `{ok: true, tronque: true, apercu}` quand la sortie dépasse la limite du socle (6 000 caractères) :
 *    la donnée n'est PAS là, et un aperçu coupé n'est jamais lu comme la donnée.
 *
 * Trois genres d'échec, que l'appelant ne confond jamais :
 *  - `refus` : le serveur a répondu et dit non (`accepte: false`) : le verdict est montré tel quel ;
 *  - `technique` : le serveur n'a pas pu répondre (`ok: false`, sortie tronquée) : la lecture peut
 *    retomber sur le cache, marqué comme tel ;
 *  - `illisible` : la réponse n'a pas la forme attendue : rien n'est affiché de ce que l'app ne comprend pas.
 */
export type LectureEnveloppe =
  | { readonly ok: true; readonly valeur: unknown }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

export function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null && !Array.isArray(valeur);
}

export function texteOuNull(valeur: unknown): string | null {
  return typeof valeur === "string" && valeur.trim() !== "" ? valeur : null;
}

export function entierOuNull(valeur: unknown): number | null {
  return typeof valeur === "number" && Number.isInteger(valeur) && valeur >= 0 ? valeur : null;
}

export const VERDICT_REPONSE_ILLISIBLE: VerdictServeur = {
  code: "reponse_illisible",
  detail: "Réponse du serveur illisible : rien n'est affiché de ce que l'app ne comprend pas.",
};

export const VERDICT_REPONSE_TRONQUEE: VerdictServeur = {
  code: "reponse_tronquee",
  detail: "La réponse dépasse la limite du serveur : elle n'est pas affichée, plutôt qu'un extrait coupé.",
};

/** `details` d'un refus technique : un texte, ou une liste (`arguments_invalides`) mise bout à bout. */
function detailsEnTexte(details: unknown): string {
  if (typeof details === "string") {
    return details;
  }
  if (Array.isArray(details)) {
    return details.filter((d): d is string => typeof d === "string").join(" ; ");
  }
  return "";
}

/** Le verdict `{code, detail}` d'un `Y = {accepte: false, verdict}` ; `statut` et le reste restent au
 * serveur, l'écran ne montre que le code et le détail, tels quels. */
export function lireVerdict(valeur: unknown, codeRepli: string): VerdictServeur {
  const v = estObjet(valeur) ? valeur : {};
  return {
    code: typeof v.code === "string" && v.code !== "" ? v.code : codeRepli,
    detail: typeof v.detail === "string" ? v.detail : "",
  };
}

/** Ouvre l'enveloppe et rend `R` (`valeur`) d'une réponse acceptée, ou l'échec et son genre. */
export function lireEnveloppeMetier(resultatBrut: unknown): LectureEnveloppe {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : null;
  if (enveloppe === null) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  if (enveloppe.ok === false) {
    return {
      ok: false,
      genre: "technique",
      verdict: {
        code: typeof enveloppe.erreur === "string" && enveloppe.erreur !== "" ? enveloppe.erreur : "erreur_inconnue",
        detail: detailsEnTexte(enveloppe.details),
      },
    };
  }
  if (enveloppe.tronque === true) {
    return { ok: false, genre: "technique", verdict: VERDICT_REPONSE_TRONQUEE };
  }
  const metier = estObjet(enveloppe.resultat) ? enveloppe.resultat : null;
  if (metier?.accepte === false) {
    return { ok: false, genre: "refus", verdict: lireVerdict(metier.verdict, "refus_inconnu") };
  }
  if (enveloppe.ok !== true || metier?.accepte !== true || metier.resultat === undefined || metier.resultat === null) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  return { ok: true, valeur: metier.resultat };
}
