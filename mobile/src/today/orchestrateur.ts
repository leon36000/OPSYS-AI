import { capturerGardeLecture, depotSousGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import { interpreterResultatListerInterventions } from "../m4/interventions";
import type { InterventionM4, StatutInterventionM4, VerdictServeurM4 } from "../m4/interventions";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { classerEchec, verdictDepuisEchec } from "../protocole/echec";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { ecrireCacheChantiers, lireCacheChantiers } from "./cache";
import { ETATS_ACTIFS_AUJOURDHUI, filtrerChantiersActifs } from "./selection";

/**
 * Chargeur de « chantiers du jour » (`today.tsx`, mission T1.4-e item 1 : « lecture, cache local
 * lisible hors ligne, jamais inventé »). Même discipline que `src/outbox/vidangeur.ts` :
 * orchestration PURE (aucune horloge/réseau/stockage en dur, tout injecté par
 * `ConfigurationChargeurChantiers`), testable avec un faux transport et un dépôt mémoire
 * (`src/today/orchestrateur.test.ts`) ; `src/today/service.ts` fournit le câblage réel.
 *
 * **Un appel par statut** (PLAN T1.4-n), comme l'admin (`src/admin/chantiers.ts`) : la réponse de
 * `m4_lister_interventions` n'a pas de pagination, et le socle la COUPE au-delà de 6 000 caractères. Sans filtre, la liste
 * d'un employé comprend tout son historique (terminé, annulé) et finit par dépasser la borne : la réponse tronquée était
 * lue comme une liste vide, et le cache vide s'écrivait par-dessus la vraie liste. On ne demande que ce que l'écran montre
 * (`ETATS_ACTIFS_AUJOURDHUI`), un statut à la fois : chaque groupe est petit, et l'historique n'est jamais demandé.
 *
 * CINQ issues, jamais confondues :
 *  - `serveur` : les quatre groupes sont lus en entier ; le cache est écrit ;
 *  - `cache` : le serveur n'a pas pu répondre (réseau, délai, 5xx, panne passagère, forme illisible) et un cache de CETTE
 *    personne existe : il est rendu avec sa date et la raison, l'écran le dit ;
 *  - `incomplet` : le socle a coupé la réponse d'un groupe. La liste montrée n'est ni vide ni complète : l'écran le dit, et
 *    le cache n'est JAMAIS écrit par une lecture incomplète ;
 *  - `refus` : le serveur a répondu NON (401, 403, refus technique : jeton révoqué, personne désactivée, rôle retiré).
 *    Le cache ne remplace jamais un refus, et rien n'est écrit (même règle que l'admin et le vendeur) ;
 *  - `aucune` : ni serveur ni cache. Jamais une liste inventée.
 */
export interface ConfigurationChargeurChantiers {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
  /** La personne que le serveur a confirmée POUR CE JETON : elle préfixe la clé du cache, et n'est jamais envoyée. */
  readonly personne: string;
  readonly maintenant: () => Date;
}

export type ResultatChargementChantiers =
  | { readonly source: "serveur"; readonly items: readonly InterventionM4[]; readonly misAJourLe: string }
  | {
      readonly source: "cache";
      readonly items: readonly InterventionM4[];
      readonly misAJourLe: string;
      readonly raisonHorsLigne: VerdictServeurM4;
    }
  | {
      readonly source: "incomplet";
      /** Ce qui a été lu en entier : les autres groupes, jamais un extrait coupé. */
      readonly items: readonly InterventionM4[];
      /** Les statuts dont le serveur n'a pas pu donner la liste en entier. */
      readonly groupesIncomplets: readonly StatutInterventionM4[];
      readonly misAJourLe: string;
    }
  | { readonly source: "refus"; readonly verdict: VerdictServeurM4 }
  | { readonly source: "aucune"; readonly raisonHorsLigne: VerdictServeurM4 | null };

export interface ChargeurChantiers {
  /** Toujours tenté en ligne d'abord ; retombe sur le cache (si présent) SEULEMENT quand le serveur n'a pas pu répondre —
   * jamais quand il a dit non — et ne lève pas pour une raison réseau (même esprit que
   * `src/outbox/service.ts::declencherVidange`). Le filtrage « actif » (`selection.ts`) s'applique aux deux sources,
   * jamais seulement à l'une des deux. */
  chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers>;
}

type Groupe =
  | { readonly genre: "lu"; readonly interventions: readonly InterventionM4[] }
  | { readonly genre: "tronque" }
  | { readonly genre: "refuse"; readonly verdict: VerdictServeurM4 }
  | { readonly genre: "injoignable"; readonly verdict: VerdictServeurM4 };

/** Les groupes lus, réunis : un statut n'est lu qu'une fois, une intervention n'apparaît qu'une fois. */
function reunir(groupes: readonly Groupe[]): readonly InterventionM4[] {
  const parId = new Map<string, InterventionM4>();
  for (const groupe of groupes) {
    if (groupe.genre === "lu") {
      for (const intervention of groupe.interventions) {
        parId.set(intervention.intervention_id, intervention);
      }
    }
  }
  return [...parId.values()];
}

function creerChargeurChantiersInterne(config: ConfigurationChargeurChantiers): ChargeurChantiers {
  async function depuisCache(raisonHorsLigne: VerdictServeurM4): Promise<ResultatChargementChantiers> {
    const cache = await lireCacheChantiers(config.depot, config.personne);
    if (!cache) {
      return { source: "aucune", raisonHorsLigne };
    }
    return {
      source: "cache",
      items: filtrerChantiersActifs(cache.interventions),
      misAJourLe: cache.misAJourLe,
      raisonHorsLigne,
    };
  }

  /** UN statut : sa liste, ou pourquoi elle n'est pas là (tronquée, refusée, ou le serveur n'a pas pu répondre). */
  async function lireGroupe(statut: StatutInterventionM4): Promise<Groupe> {
    const resultatAppel = await config.appelerOutil({
      fetchImpl: config.fetchImpl,
      urlBase: config.urlBase,
      jeton: config.jeton,
      requete: { tool: "m4_lister_interventions", args: { statut } },
    });
    if (!resultatAppel.ok) {
      const verdict = verdictDepuisEchec(resultatAppel.echec);
      return classerEchec(resultatAppel.echec) === "refuse" ? { genre: "refuse", verdict } : { genre: "injoignable", verdict };
    }
    const lue = interpreterResultatListerInterventions(resultatAppel.result);
    if (lue.ok) {
      return { genre: "lu", interventions: lue.interventions };
    }
    switch (lue.genre) {
      case "refus":
        return { genre: "refuse", verdict: lue.verdict };
      case "tronquee":
        return { genre: "tronque" };
      default:
        // `technique` (panne passagère de l'instance) et `illisible` : le serveur n'a pas dit non, il n'a pas pu dire.
        return { genre: "injoignable", verdict: lue.verdict };
    }
  }

  return {
    async chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers> {
      const groupes = await Promise.all(ETATS_ACTIFS_AUJOURDHUI.map(lireGroupe));

      const refuse = groupes.find((groupe) => groupe.genre === "refuse");
      if (refuse?.genre === "refuse") {
        return { source: "refus", verdict: refuse.verdict };
      }
      const injoignable = groupes.find((groupe) => groupe.genre === "injoignable");
      if (injoignable?.genre === "injoignable") {
        return depuisCache(injoignable.verdict);
      }

      const interventions = reunir(groupes);
      const misAJourLe = config.maintenant().toISOString();
      const groupesIncomplets = ETATS_ACTIFS_AUJOURDHUI.filter((_statut, rang) => groupes[rang].genre === "tronque");
      if (groupesIncomplets.length > 0) {
        return { source: "incomplet", items: filtrerChantiersActifs(interventions), groupesIncomplets, misAJourLe };
      }

      await ecrireCacheChantiers(config.depot, config.personne, { interventions, misAJourLe });
      return { source: "serveur", items: filtrerChantiersActifs(interventions), misAJourLe };
    },
  };
}

export function creerChargeurChantiers(config: ConfigurationChargeurChantiers): ChargeurChantiers {
  const garde = capturerGardeLecture(config.depot);
  const chargeur = creerChargeurChantiersInterne({ ...config, depot: depotSousGardeLecture(config.depot, garde.courante) });
  return {
    async chargerChantiersAujourdhui() {
      if (!garde.courante()) return { source: "aucune", raisonHorsLigne: VERDICT_LECTURE_REMPLACEE };
      const result = await chargeur.chargerChantiersAujourdhui();
      return garde.courante() ? result : { source: "aucune", raisonHorsLigne: VERDICT_LECTURE_REMPLACEE };
    },
  };
}
