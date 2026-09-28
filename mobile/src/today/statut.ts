import { interpreterResultatStatutIntervention } from "../m4/interventions";
import type { StatutInterventionM4, VerdictServeurM4 } from "../m4/interventions";
import { lireInterventionEnCache } from "./cache";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

/**
 * Lecture du statut d'UN chantier (`job/[id]/index.tsx`) — même discipline que
 * `src/today/orchestrateur.ts` (lecture en ligne d'abord, repli sur le cache de `today.tsx` si
 * hors ligne ou en échec), mais pour `m4_statut_intervention` plutôt que
 * `m4_lister_interventions`. Fichier séparé de `orchestrateur.ts` : un seul chantier, un contrat
 * d'outil différent, pas de cache à ÉCRIRE ici (seul `today.tsx` alimente le cache lu).
 */
export interface ConfigurationStatutChantier {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
}

export type ResultatStatutChantier =
  | { readonly source: "serveur"; readonly statut: StatutInterventionM4 | null }
  | { readonly source: "cache"; readonly statut: StatutInterventionM4 | null; readonly raisonHorsLigne: VerdictServeurM4 }
  | { readonly source: "aucune"; readonly raisonHorsLigne: VerdictServeurM4 };

function verdictDepuisEchecAppel(echec: {
  readonly message: string;
  readonly erreur?: { readonly type: string; readonly message: string };
}): VerdictServeurM4 {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

export async function obtenirStatutChantier(
  config: ConfigurationStatutChantier,
  interventionId: string,
): Promise<ResultatStatutChantier> {
  async function depuisCache(raisonHorsLigne: VerdictServeurM4): Promise<ResultatStatutChantier> {
    const enCache = await lireInterventionEnCache(config.depot, interventionId);
    if (!enCache) {
      return { source: "aucune", raisonHorsLigne };
    }
    return { source: "cache", statut: enCache.statut, raisonHorsLigne };
  }

  const resultatAppel = await config.appelerOutil({
    fetchImpl: config.fetchImpl,
    urlBase: config.urlBase,
    jeton: config.jeton,
    requete: { tool: "m4_statut_intervention", args: { intervention_id: interventionId } },
  });

  if (!resultatAppel.ok) {
    return depuisCache(verdictDepuisEchecAppel(resultatAppel.echec));
  }

  const interpretation = interpreterResultatStatutIntervention(resultatAppel.result);
  if (!interpretation.ok) {
    return depuisCache(interpretation.verdict);
  }
  return { source: "serveur", statut: interpretation.statut };
}
