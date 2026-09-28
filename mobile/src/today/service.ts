import { creerChargeurChantiers } from "./orchestrateur";
import type { ChargeurChantiers, ResultatChargementChantiers } from "./orchestrateur";
import { obtenirStatutChantier as obtenirStatutChantierPur } from "./statut";
import type { ResultatStatutChantier } from "./statut";
import { invoquerOutil } from "../protocole/client";
import { obtenirConfigurationAppel } from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";

/**
 * Câblage RÉEL du chargeur de chantiers (`today.tsx`). Même philosophie que
 * `src/outbox/service.ts::declencherVidange` : `null` (via `ResultatChargementChantiers` source
 * `"aucune"` sans configuration) tant qu'aucun appairage n'a eu lieu — jamais une erreur, jamais
 * une liste inventée.
 */
let chargeurCache: ChargeurChantiers | null = null;

async function obtenirChargeur(): Promise<ChargeurChantiers | null> {
  const configuration = obtenirConfigurationAppel();
  if (!configuration) {
    return null;
  }
  if (!chargeurCache) {
    chargeurCache = creerChargeurChantiers({
      depot: await obtenirDepotLocal(),
      appelerOutil: invoquerOutil,
      fetchImpl: fetch,
      urlBase: configuration.urlBase,
      jeton: configuration.jeton,
      maintenant: () => new Date(),
    });
  }
  return chargeurCache;
}

/** `null` uniquement si aucune configuration de connexion n'existe encore (pas d'appairage) — le
 * cache local ne peut alors pas non plus être tenté puisqu'aucune session n'a jamais permis de
 * l'alimenter (voir `today.tsx`, qui distingue ce cas de `{source: "aucune"}`). */
export async function chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers | null> {
  const chargeur = await obtenirChargeur();
  if (!chargeur) {
    return null;
  }
  return chargeur.chargerChantiersAujourdhui();
}

/** `null` uniquement si aucune configuration de connexion n'existe encore — voir
 * `chargerChantiersAujourdhui` ci-dessus, même philosophie (`job/[id]/index.tsx`). */
export async function obtenirStatutChantier(interventionId: string): Promise<ResultatStatutChantier | null> {
  const configuration = obtenirConfigurationAppel();
  if (!configuration) {
    return null;
  }
  return obtenirStatutChantierPur(
    {
      depot: await obtenirDepotLocal(),
      appelerOutil: invoquerOutil,
      fetchImpl: fetch,
      urlBase: configuration.urlBase,
      jeton: configuration.jeton,
    },
    interventionId,
  );
}
