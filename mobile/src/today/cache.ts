import { ecrireCacheSousGarde } from "../stockage/lecturesEnVol";
import { estInterventionM4 } from "../m4/interventions";
import type { InterventionM4 } from "../m4/interventions";
import { cleDeCachePersonne, PREFIXE_CACHE_EMPLOYE } from "../stockage/cles";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ChantiersCache } from "./types";

/**
 * Le cache des chantiers de l'employé, **une clé par PERSONNE** (PLAN T1.4-n) : `employe:<personne>:chantiers_v1`, comme
 * ceux du vendeur et de l'admin. Avant, c'était une seule clé (`today_chantiers_v1`) pour tout l'appareil : après un
 * nouvel appairage pour quelqu'un d'autre, sa liste de chantiers relisait celle de la personne d'avant. Versionnée
 * (`_v1`) pour pouvoir changer la forme du cache plus tard sans relire une valeur d'une forme différente comme si elle
 * était valide. Effacé, avec les autres caches par personne, quand l'identité de l'appareil change
 * (`src/identite/caches.ts`).
 */
function cle(personne: string): string {
  return cleDeCachePersonne(PREFIXE_CACHE_EMPLOYE, personne, "chantiers_v1");
}

function estChantiersCacheValide(valeur: unknown): valeur is ChantiersCache {
  return (
    typeof valeur === "object" &&
    valeur !== null &&
    Array.isArray((valeur as { interventions?: unknown }).interventions) &&
    (valeur as { interventions: unknown[] }).interventions.every(estInterventionM4) &&
    typeof (valeur as { misAJourLe?: unknown }).misAJourLe === "string"
  );
}

/** `null` si aucun cache n'existe encore pour cette personne (premier lancement hors ligne) OU si la valeur stockée
 * est corrompue/d'un format inconnu — fail-closed (AGENTS.md), même discipline que
 * `src/appairage/stockage.ts` `chargerSession` : jamais un cache partiel ou deviné. */
export async function lireCacheChantiers(depot: DepotCleValeur, personne: string): Promise<ChantiersCache | null> {
  const brut = await depot.lire(cle(personne));
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

export async function ecrireCacheChantiers(depot: DepotCleValeur, personne: string, cache: ChantiersCache): Promise<void> {
  await ecrireCacheSousGarde(depot, () => depot.ecrire(cle(personne), JSON.stringify(cache)));
}

/** Cherche une intervention précise dans le dernier cache écrit pour cette personne (`job/[id]/index.tsx`, repli
 * hors ligne pour l'affichage du statut — voir `src/today/statut.ts`). `null` si aucun cache n'existe encore, ou si ce
 * chantier n'y figure pas (le cache ne garde que les statuts que l'écran montre, voir `types.ts` : cette absence n'est
 * pas celle d'un chantier inexistant). */
export async function lireInterventionEnCache(
  depot: DepotCleValeur,
  personne: string,
  interventionId: string,
): Promise<InterventionM4 | null> {
  const cache = await lireCacheChantiers(depot, personne);
  if (!cache) {
    return null;
  }
  return cache.interventions.find((intervention) => intervention.intervention_id === interventionId) ?? null;
}
