import { capturerGardeLecture, commencerTransitionCaches, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import type { VerdictServeur } from "../outbox/vidangeur";
import { appelerLecture, ecrireSansEchouer } from "./appel";
import type { ConfigurationChargeurAdmin } from "./appel";
import { ecrireCacheSection, lireCacheSection } from "./cache";
import type { LectureSection } from "./enveloppe";

/**
 * La lecture d'UNE section d'écran du profil admin, avec ses quatre issues (PLAN T4.20). C'est ici, et ici seulement,
 * que se décide quand un cache peut servir : chaque chargeur (`chargeurAVoir`, `chargeurChiffres`, `chargeurChantiers`)
 * ne fait que nommer l'outil, ses arguments et son lecteur. Orchestration PURE, testée avec un faux transport et un
 * dépôt mémoire (`lecture.test.ts`).
 *
 * QUATRE issues, jamais confondues :
 *  - `serveur` : la lecture a réussi ; le cache est écrit (facultatif : sa panne ne cache pas une lecture réussie) ;
 *  - `cache` : le serveur n'a pas pu répondre (réseau, délai, 5xx, sortie tronquée, réponse illisible) et un cache de
 *    CETTE section pour CETTE personne existe : il est rendu avec sa date et la raison, l'écran le dit ;
 *  - `refus` : le serveur a répondu NON (403 de la porte d'appareil, refus de l'outil, personne désactivée, argument
 *    refusé). Un cache ne dit pas ce que le serveur refuse aujourd'hui : il ne remplace JAMAIS un refus ;
 *  - `aucune` : ni serveur ni cache. Jamais une valeur inventée, jamais un zéro.
 */
export type ResultatSection<T> =
  | { readonly source: "serveur"; readonly valeur: T; readonly misAJourLe: string }
  | {
      readonly source: "cache";
      readonly valeur: T;
      readonly misAJourLe: string;
      readonly raisonHorsLigne: VerdictServeur;
    }
  | { readonly source: "refus"; readonly verdict: VerdictServeur }
  | { readonly source: "aucune"; readonly raison: VerdictServeur };

export interface DefinitionSection<T> {
  /** Le nom nu de l'outil (jamais préfixé par un serveur). */
  readonly outil: string;
  /** Les arguments EXACTS : aucune personne, aucun rôle, aucun montant. */
  readonly args: Readonly<Record<string, unknown>>;
  /** Le nom de la section dans le cache (la personne s'y ajoute, `cache.ts`). */
  readonly cache: string;
  /** Lit l'enveloppe du serveur ; sert aussi à relire le cache : mêmes règles en ligne et hors ligne. */
  readonly interpreter: (resultatBrut: unknown) => LectureSection<T>;
  /** Option explicite pour un cache épuré avec ses arguments d'origine. Jamais utilisée pour une réponse HTTP. */
  readonly interpreterCache?: (resultatBrut: unknown) => LectureSection<T>;
  /** Une copie informative devient inutilisable dès un refus connu. Défaut historique conservé. */
  readonly invaliderCacheSurRefus?: boolean;
  /** Retire de l'enveloppe ce que l'écran ne montre pas avant de la garder (minimisation : Loi 25). Le résultat doit
   * rester lisible par `interpreter`. */
  readonly epurerPourLeCache?: (resultatBrut: unknown) => unknown;
}

export async function lireSection<T>(
  config: ConfigurationChargeurAdmin,
  section: DefinitionSection<T>,
): Promise<ResultatSection<T>> {
  const garde = capturerGardeLecture(config.depot);
  const remplacee = (): ResultatSection<T> => ({ source: "aucune", raison: VERDICT_LECTURE_REMPLACEE });
  if (!garde.courante()) return remplacee();
  async function refus(verdict: VerdictServeur): Promise<ResultatSection<T>> {
    if (section.invaliderCacheSurRefus) {
      try { await ecrireCacheSection(config.depot, config.personne, section.cache, null, config.horloge().maintenant.toISOString()); }
      catch {
        if (!garde.courante()) return remplacee();
        const terminer = commencerTransitionCaches(config.depot); terminer(false);
        return { source: "refus", verdict };
      }
    }
    return garde.courante() ? { source: "refus", verdict } : remplacee();
  }
  async function depuisCache(raisonHorsLigne: VerdictServeur): Promise<ResultatSection<T>> {
    if (!garde.cachePermis()) return remplacee();
    const gardee = await lireCacheSection(config.depot, config.personne, section.cache);
    if (!garde.cachePermis()) return remplacee();
    if (gardee === null) {
      return { source: "aucune", raison: raisonHorsLigne };
    }
    const relue = (section.interpreterCache ?? section.interpreter)(gardee.resultat);
    return relue.ok
      ? { source: "cache", valeur: relue.valeur, misAJourLe: gardee.misAJourLe, raisonHorsLigne }
      : { source: "aucune", raison: raisonHorsLigne };
  }

  if (config.enLigne?.() === false) return depuisCache({ code: "hors_ligne", detail: "" });
  const appel = await appelerLecture(config, section.outil, section.args);
  if (!garde.courante()) return remplacee();
  if (appel.genre === "refuse") {
    return refus(appel.verdict);
  }
  if (appel.genre === "injoignable") {
    return depuisCache(appel.verdict);
  }
  const lue = section.interpreter(appel.resultat);
  if (!lue.ok) {
    return lue.genre === "refus" ? refus(lue.verdict) : depuisCache(lue.verdict);
  }
  const misAJourLe = config.horloge().maintenant.toISOString();
  const agarder = section.epurerPourLeCache ? section.epurerPourLeCache(appel.resultat) : appel.resultat;
  await ecrireSansEchouer(() => ecrireCacheSection(config.depot, config.personne, section.cache, agarder, misAJourLe));
  if (!garde.courante()) return remplacee();
  return { source: "serveur", valeur: lue.valeur, misAJourLe };
}
