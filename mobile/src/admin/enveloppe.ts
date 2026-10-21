import type { VerdictServeur } from "../outbox/vidangeur";
import {
  ERREURS_PASSAGERES,
  estObjet,
  lireVerdict,
  VERDICT_REPONSE_ILLISIBLE,
  VERDICT_REPONSE_TRONQUEE,
} from "../protocole/enveloppeOutil";

// La liste des pannes passagères est celle du socle, écrite une fois dans `src/protocole/enveloppeOutil.ts` : le vendeur
// suit la même règle (PLAN T1.4-n). Elle reste importable d'ici.
export { ERREURS_PASSAGERES };

/**
 * Ouverture de l'enveloppe OPSYS d'un outil de lecture du profil admin (PLAN T4.20). Un appel réussi de
 * `/tools/invoke` rend `{ok: true, result: X}` ; `X` est l'enveloppe du socle (`src/opsys/outils.py`, `capacites.py`),
 * et c'est elle que ce module ouvre. Deux formes de réponse existent chez les départements :
 *  - `couple` (`depuis_couple`) : `X = {ok: true, resultat: {accepte: true, resultat: R}}` ou
 *    `{accepte: false, verdict}` (M4 digest et préparation, M5 prévision et échéances, M9 demandes) ;
 *  - `directe` : `X = {ok: true, resultat: V}` où `V` est la valeur elle-même (M8 vue exécutive, M4 liste des
 *    interventions, M5 état de trésorerie), ou `V = {accepte: false, verdict}` quand l'outil refuse (M5).
 *
 * Trois genres d'échec, que l'appelant ne confond jamais (c'est ce qui décide si un cache peut servir) :
 *  - `refus` : le serveur a répondu et dit non (`accepte: false`, ou une enveloppe `ok: false` qui n'est pas une panne
 *    passagère : `refus_metier`, `arguments_invalides`, `hors_portee_role`...). Son verdict est montré tel quel, et
 *    aucun cache ne le remplace ;
 *  - `technique` : le serveur n'a pas pu répondre en entier (sortie tronquée, panne passagère de l'instance) : un
 *    cache, marqué comme tel, peut servir ;
 *  - `illisible` : la réponse n'a pas la forme attendue : rien n'est affiché de ce que l'app ne comprend pas ; un cache
 *    peut servir (le serveur n'a pas dit non, l'app n'a pas compris).
 */
export type LectureSection<T> =
  | { readonly ok: true; readonly valeur: T }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

export type FormeReponse = "couple" | "directe";

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

export type EnveloppeOuverte =
  | { readonly ok: true; readonly valeur: unknown }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

export function ouvrirEnveloppe(resultatBrut: unknown, forme: FormeReponse): EnveloppeOuverte {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : null;
  if (enveloppe === null) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  if (enveloppe.ok === false) {
    const erreur = typeof enveloppe.erreur === "string" && enveloppe.erreur !== "" ? enveloppe.erreur : "erreur_inconnue";
    return {
      ok: false,
      genre: ERREURS_PASSAGERES.includes(erreur) ? "technique" : "refus",
      verdict: { code: erreur, detail: detailsEnTexte(enveloppe.details) },
    };
  }
  if (enveloppe.tronque === true) {
    return { ok: false, genre: "technique", verdict: VERDICT_REPONSE_TRONQUEE };
  }
  if (enveloppe.ok !== true) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  const contenu = enveloppe.resultat;
  const metier = estObjet(contenu) ? contenu : null;
  if (metier?.accepte === false) {
    return { ok: false, genre: "refus", verdict: lireVerdict(metier.verdict, "refus_inconnu") };
  }
  if (forme === "couple") {
    if (metier?.accepte !== true || metier.resultat === undefined || metier.resultat === null) {
      return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
    }
    return { ok: true, valeur: metier.resultat };
  }
  if (contenu === undefined || contenu === null) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  return { ok: true, valeur: contenu };
}

/** Un lecteur de valeur : `null` quand la forme n'est pas celle qu'il exige (la réponse est alors illisible). */
export type LecteurDeValeur<T> = (valeur: unknown) => T | null;

/** Ouvre l'enveloppe puis lit la valeur avec `lire` : une valeur que `lire` ne comprend pas est illisible, jamais devinée. */
export function interpreter<T>(resultatBrut: unknown, forme: FormeReponse, lire: LecteurDeValeur<T>): LectureSection<T> {
  const ouverte = ouvrirEnveloppe(resultatBrut, forme);
  if (!ouverte.ok) {
    return ouverte;
  }
  const lue = lire(ouverte.valeur);
  return lue === null ? { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE } : { ok: true, valeur: lue };
}
