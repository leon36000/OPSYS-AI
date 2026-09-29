import { construireArgumentsListerLeads, lirePageLeads, OUTIL_LISTER_LEADS } from "../m2/listeLeads";
import type { FiltreLeads } from "../m2/listeLeads";
import { formaterHorodatageLocal } from "../outbox/mutation";
import type { VerdictServeur } from "../outbox/vidangeur";
import { lireEnveloppeMetier, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import { appelerLecture, ecrireSansEchouer } from "./appel";
import type { ConfigurationChargeurVendeur } from "./appel";
import { ecrireCacheLeads, lireCacheLeads } from "./cache";
import { demarrerLecture, fusionnerPage } from "./lectureLeads";
import type { LeadsLus, RaisonRelecture } from "./lectureLeads";

/**
 * Chargeur de la liste des leads (`(seller)/leads.tsx`, PLAN T4.8) : lecture d'abord, cache hors ligne marqué comme
 * tel. Orchestration PURE (tout est injecté, `ConfigurationChargeurVendeur`), testée avec un faux transport et un
 * dépôt mémoire (`chargeurLeads.test.ts`) ; `src/vendeur/service.ts` fournit le câblage réel.
 *
 * QUATRE issues, jamais confondues :
 *  - `serveur` : la lecture a réussi ; le cache est écrit ;
 *  - `cache` : le serveur n'a pas pu répondre (réseau, délai, sortie tronquée, réponse illisible) et un cache de CE
 *    filtre existe pour CETTE personne : il est rendu avec sa date et la raison, l'écran le dit ;
 *  - `refus` : le serveur a répondu et dit non (un segment non calculable, une identité invalide). Le cache ne remplace
 *    JAMAIS un refus : un cache ne dit pas ce que le serveur refuse aujourd'hui ;
 *  - `aucune` : ni serveur ni cache. Jamais une liste inventée.
 */
export type ResultatLeads =
  | { readonly source: "serveur"; readonly lus: LeadsLus }
  | { readonly source: "cache"; readonly lus: LeadsLus; readonly raisonHorsLigne: VerdictServeur }
  | { readonly source: "refus"; readonly verdict: VerdictServeur }
  | { readonly source: "aucune"; readonly raison: VerdictServeur };

/** Ce que devient la liste après « Voir plus ». */
export type SuiteLeads =
  | { readonly genre: "fusionnee"; readonly lus: LeadsLus }
  /** Les rangs ont glissé : ce qui est affiché reste, l'écran relit depuis le début et le dit. */
  | { readonly genre: "a_relire"; readonly raison: RaisonRelecture }
  /** Le serveur n'a pas pu être lu ou a refusé : ce qui est affiché reste, et le verdict est dit. */
  | { readonly genre: "echec"; readonly verdict: VerdictServeur }
  /** Rien à demander : rien ne suit. */
  | { readonly genre: "sans_suite" };

export interface ChargeurLeads {
  /** Ne lève jamais pour une raison réseau ou HTTP. */
  chargerLeads(filtre: FiltreLeads): Promise<ResultatLeads>;
  chargerSuite(lues: LeadsLus): Promise<SuiteLeads>;
}

type LecturePage =
  | { readonly genre: "page"; readonly page: NonNullable<ReturnType<typeof lirePageLeads>>; readonly brute: unknown }
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  | { readonly genre: "indisponible"; readonly verdict: VerdictServeur };

export function creerChargeurLeads(config: ConfigurationChargeurVendeur): ChargeurLeads {
  /** Une page du serveur : sa lecture, son refus, ou l'impossibilité de la lire (cache possible). */
  async function lirePage(filtre: FiltreLeads, decalage: number): Promise<LecturePage> {
    const appel = await appelerLecture(
      config,
      OUTIL_LISTER_LEADS,
      construireArgumentsListerLeads(formaterHorodatageLocal(config.horloge()), filtre, decalage),
    );
    if (appel.genre === "injoignable") {
      return { genre: "indisponible", verdict: appel.verdict };
    }
    const lecture = lireEnveloppeMetier(appel.resultat);
    if (!lecture.ok) {
      return lecture.genre === "refus"
        ? { genre: "refus", verdict: lecture.verdict }
        : { genre: "indisponible", verdict: lecture.verdict };
    }
    const page = lirePageLeads(lecture.valeur);
    return page === null
      ? { genre: "indisponible", verdict: VERDICT_REPONSE_ILLISIBLE }
      : { genre: "page", page, brute: lecture.valeur };
  }

  async function depuisCache(filtre: FiltreLeads, raisonHorsLigne: VerdictServeur): Promise<ResultatLeads> {
    const lus = await lireCacheLeads(config.depot, config.personne, filtre);
    return lus === null ? { source: "aucune", raison: raisonHorsLigne } : { source: "cache", lus, raisonHorsLigne };
  }

  return {
    async chargerLeads(filtre: FiltreLeads): Promise<ResultatLeads> {
      const lecture = await lirePage(filtre, 0);
      if (lecture.genre === "refus") {
        return { source: "refus", verdict: lecture.verdict };
      }
      if (lecture.genre === "indisponible") {
        return depuisCache(filtre, lecture.verdict);
      }
      const lus = demarrerLecture(filtre, lecture.page, lecture.brute, config.horloge().maintenant.toISOString());
      if (lus === null) {
        // Le serveur n'a pas répondu pour ce filtre, ou pas pour la première page : ce n'est pas la liste demandée.
        return depuisCache(filtre, VERDICT_REPONSE_ILLISIBLE);
      }
      await ecrireSansEchouer(() => ecrireCacheLeads(config.depot, config.personne, lus));
      return { source: "serveur", lus };
    },

    async chargerSuite(lues: LeadsLus): Promise<SuiteLeads> {
      if (lues.suivant === null) {
        return { genre: "sans_suite" };
      }
      const lecture = await lirePage(lues.filtre, lues.suivant);
      if (lecture.genre !== "page") {
        return { genre: "echec", verdict: lecture.verdict };
      }
      const fusion = fusionnerPage(lues, lecture.page, lecture.brute);
      if (fusion.genre === "a_relire") {
        return fusion;
      }
      await ecrireSansEchouer(() => ecrireCacheLeads(config.depot, config.personne, fusion.lus));
      return fusion;
    },
  };
}
