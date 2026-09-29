import { interpreterResultatStatutIntervention } from "../m4/interventions";
import type { StatutInterventionM4, VerdictServeurM4 } from "../m4/interventions";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { classerEchec, verdictDepuisEchec } from "../protocole/echec";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { lireInterventionEnCache } from "./cache";

/**
 * Lecture du statut d'UN chantier (`job/[id]/index.tsx`) — même discipline que
 * `src/today/orchestrateur.ts` (lecture en ligne d'abord, repli sur le cache de `today.tsx` si le serveur n'a pas pu
 * répondre), mais pour `m4_statut_intervention` plutôt que `m4_lister_interventions`. Fichier séparé de
 * `orchestrateur.ts` : un seul chantier, un contrat d'outil différent, pas de cache à ÉCRIRE ici (seul `today.tsx`
 * alimente le cache lu, pour CETTE personne).
 *
 * Quatre issues (PLAN T1.4-n) : `serveur`, `cache` (le serveur n'a pas pu répondre : réseau, délai, 5xx, panne
 * passagère), `refus` (le serveur dit NON : 401, 403, refus technique ; le cache ne remplace jamais un refus) et
 * `aucune`.
 */
export interface ConfigurationStatutChantier {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
  /** La personne que le serveur a confirmée POUR CE JETON : le cache lu est le sien, jamais celui d'une autre. */
  readonly personne: string;
}

export type ResultatStatutChantier =
  | { readonly source: "serveur"; readonly statut: StatutInterventionM4 | null }
  | { readonly source: "cache"; readonly statut: StatutInterventionM4 | null; readonly raisonHorsLigne: VerdictServeurM4 }
  | { readonly source: "refus"; readonly verdict: VerdictServeurM4 }
  | { readonly source: "aucune"; readonly raisonHorsLigne: VerdictServeurM4 };

/**
 * Le statut que l'écran peut montrer et dont il peut dériver ses boutons : celui du serveur, ou celui du cache marqué.
 * `null` : aucun (rien lu, ou le serveur a refusé) — l'écran ne propose alors aucune transition.
 */
export function statutAffichable(resultat: ResultatStatutChantier | null): StatutInterventionM4 | null {
  return resultat !== null && (resultat.source === "serveur" || resultat.source === "cache") ? resultat.statut : null;
}

export async function obtenirStatutChantier(
  config: ConfigurationStatutChantier,
  interventionId: string,
): Promise<ResultatStatutChantier> {
  async function depuisCache(raisonHorsLigne: VerdictServeurM4): Promise<ResultatStatutChantier> {
    const enCache = await lireInterventionEnCache(config.depot, config.personne, interventionId);
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
    const verdict = verdictDepuisEchec(resultatAppel.echec);
    return classerEchec(resultatAppel.echec) === "refuse" ? { source: "refus", verdict } : depuisCache(verdict);
  }

  const interpretation = interpreterResultatStatutIntervention(resultatAppel.result);
  if (!interpretation.ok) {
    return interpretation.genre === "refus" ? { source: "refus", verdict: interpretation.verdict } : depuisCache(interpretation.verdict);
  }
  return { source: "serveur", statut: interpretation.statut };
}
