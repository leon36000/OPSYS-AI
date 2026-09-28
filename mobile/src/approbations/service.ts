import { creerChargeurApprobations } from "./chargeur";
import type { ResultatChargementApprobations } from "./chargeur";
import { invoquerOutil } from "../protocole/client";
import { obtenirConfigurationAppel } from "../protocole/configuration";

/**
 * Câblage RÉEL du chargeur d'approbations (`(admin)/approvals.tsx`) : `fetch` et la configuration de
 * connexion de la session appairée. Même philosophie que `src/today/service.ts` : `null` tant
 * qu'aucun appairage n'a eu lieu — jamais une liste inventée.
 */
export async function chargerDemandesApprobation(): Promise<ResultatChargementApprobations | null> {
  const configuration = obtenirConfigurationAppel();
  if (!configuration) {
    return null;
  }
  return creerChargeurApprobations({
    appelerOutil: invoquerOutil,
    fetchImpl: fetch,
    urlBase: configuration.urlBase,
    jeton: configuration.jeton,
  }).chargerDemandes();
}
