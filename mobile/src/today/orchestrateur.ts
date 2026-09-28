import { interpreterResultatListerInterventions } from "../m4/interventions";
import type { InterventionM4, VerdictServeurM4 } from "../m4/interventions";
import { ecrireCacheChantiers, lireCacheChantiers } from "./cache";
import { filtrerChantiersActifs } from "./selection";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

/**
 * Chargeur de « chantiers du jour » (`today.tsx`, mission T1.4-e item 1 : « lecture, cache local
 * lisible hors ligne, jamais inventé »). Même discipline que `src/outbox/vidangeur.ts` :
 * orchestration PURE (aucune horloge/réseau/stockage en dur, tout injecté par
 * `ConfigurationChargeurChantiers`), testable avec un faux transport et un dépôt mémoire
 * (`src/today/orchestrateur.test.ts`) ; `src/today/service.ts` fournit le câblage réel.
 */
export interface ConfigurationChargeurChantiers {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
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
  | { readonly source: "aucune"; readonly raisonHorsLigne: VerdictServeurM4 | null };

export interface ChargeurChantiers {
  /** Toujours tenté en ligne d'abord ; retombe sur le cache (si présent) en cas d'échec réseau,
   * HTTP ou technique — ne lève jamais pour une raison réseau (même esprit que
   * `src/outbox/service.ts::declencherVidange`). Le filtrage « actif » (`selection.ts`)
   * s'applique aux deux sources, jamais seulement à l'une des deux. */
  chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers>;
}

function verdictDepuisEchecAppel(echec: {
  readonly message: string;
  readonly erreur?: { readonly type: string; readonly message: string };
}): VerdictServeurM4 {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

export function creerChargeurChantiers(config: ConfigurationChargeurChantiers): ChargeurChantiers {
  async function depuisCache(raisonHorsLigne: VerdictServeurM4): Promise<ResultatChargementChantiers> {
    const cache = await lireCacheChantiers(config.depot);
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

  return {
    async chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers> {
      const resultatAppel = await config.appelerOutil({
        fetchImpl: config.fetchImpl,
        urlBase: config.urlBase,
        jeton: config.jeton,
        requete: { tool: "m4_lister_interventions", args: {} },
      });

      if (!resultatAppel.ok) {
        return depuisCache(verdictDepuisEchecAppel(resultatAppel.echec));
      }

      const interpretation = interpreterResultatListerInterventions(resultatAppel.result);
      if (!interpretation.ok) {
        return depuisCache(interpretation.verdict);
      }

      const misAJourLe = config.maintenant().toISOString();
      await ecrireCacheChantiers(config.depot, { interventions: interpretation.interventions, misAJourLe });
      return { source: "serveur", items: filtrerChantiersActifs(interpretation.interventions), misAJourLe };
    },
  };
}
