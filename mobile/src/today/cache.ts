import { estInterventionM4 } from "../m4/interventions";
import type { InterventionM4 } from "../m4/interventions";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ChantiersCache } from "./types";

/** Clé de stockage (`src/stockage/depotCleValeur.ts`) — versionnée (`_v1`) pour pouvoir changer
 * la forme du cache plus tard sans relire une valeur d'une forme différente comme si elle était
 * valide. */
const CLE_CACHE = "today_chantiers_v1";

function estChantiersCacheValide(valeur: unknown): valeur is ChantiersCache {
  return (
    typeof valeur === "object" &&
    valeur !== null &&
    Array.isArray((valeur as { interventions?: unknown }).interventions) &&
    (valeur as { interventions: unknown[] }).interventions.every(estInterventionM4) &&
    typeof (valeur as { misAJourLe?: unknown }).misAJourLe === "string"
  );
}

/** `null` si aucun cache n'existe encore (premier lancement hors ligne) OU si la valeur stockée
 * est corrompue/d'un format inconnu — fail-closed (AGENTS.md), même discipline que
 * `src/appairage/stockage.ts` `chargerSession` : jamais un cache partiel ou deviné. */
export async function lireCacheChantiers(depot: DepotCleValeur): Promise<ChantiersCache | null> {
  const brut = await depot.lire(CLE_CACHE);
  if (!brut) {
    return null;
  }
  try {
    const valeur: unknown = JSON.parse(brut);
    return estChantiersCacheValide(valeur) ? valeur : null;
  } catch {
    return null;
  }
}

export async function ecrireCacheChantiers(depot: DepotCleValeur, cache: ChantiersCache): Promise<void> {
  await depot.ecrire(CLE_CACHE, JSON.stringify(cache));
}

/** Cherche une intervention précise dans le dernier cache écrit (`job/[id]/index.tsx`, repli
 * hors ligne pour l'affichage du statut — voir `src/today/statut.ts`). `null` si aucun cache
 * n'existe encore, ou si ce chantier n'y figure pas (ex. il n'était plus « actif » à la dernière
 * lecture réussie — le cache garde TOUTES les interventions reçues, pas seulement les actives,
 * voir `types.ts`, donc cette absence est une vraie absence, pas un effet du filtrage). */
export async function lireInterventionEnCache(
  depot: DepotCleValeur,
  interventionId: string,
): Promise<InterventionM4 | null> {
  const cache = await lireCacheChantiers(depot);
  if (!cache) {
    return null;
  }
  return cache.interventions.find((intervention) => intervention.intervention_id === interventionId) ?? null;
}
