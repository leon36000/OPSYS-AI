import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import { creerChargeurChantiers } from "./orchestrateur";
import type { ConfigurationChargeurChantiers, ResultatChargementChantiers } from "./orchestrateur";
import { obtenirStatutChantier as obtenirStatutChantierPur } from "./statut";
import type { ConfigurationStatutChantier, ResultatStatutChantier } from "./statut";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionLecture } from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";

/**
 * Câblage RÉEL du chargeur de chantiers (`today.tsx`) et de la lecture du statut (`job/[id]/index.tsx`). Même
 * philosophie que `src/vendeur/service.ts` et `src/admin/service.ts` : `null` tant qu'aucune session n'existe — jamais
 * une erreur, jamais une liste inventée.
 *
 * La session est `obtenirSessionEnvoi` : le jeton COURANT et la personne que le serveur a confirmée POUR CE JETON. Elle est
 * relue à chaque appel, jamais gardée (PLAN T1.4-n) : avant, le chargeur était construit une fois avec le jeton du moment
 * et le gardait jusqu'au redémarrage, donc après un nouvel appairage la liste se lisait encore avec l'ancien jeton (révoqué),
 * et le cache n'avait pas de personne.
 */
async function connexion(): Promise<(ConfigurationChargeurChantiers & ConfigurationStatutChantier) | null> {
  const capture = capturerSessionLecture();
  const session = capture.session;
  if (!session) {
    return null;
  }
  const depot = await obtenirDepotLocal();
  if (!capture.courante()) return null;
  return {
    depot: depotSousGardeLecture(depot, capture.courante),
    appelerOutil: invoquerOutil,
    fetchImpl: fetch,
    urlBase: session.urlBase,
    jeton: session.jeton,
    personne: session.personne,
    maintenant: () => new Date(),
  };
}

/** `null` uniquement si aucune session n'existe encore (pas d'appairage, ou personne pas encore confirmée pour le jeton
 * courant) — le cache local ne peut alors pas non plus être tenté (`today.tsx` distingue ce cas de `{source: "aucune"}`). */
export async function chargerChantiersAujourdhui(): Promise<ResultatChargementChantiers | null> {
  const config = await connexion();
  return config ? creerChargeurChantiers(config).chargerChantiersAujourdhui() : null;
}

/** `null` uniquement si aucune session n'existe encore — voir `chargerChantiersAujourdhui`, même philosophie
 * (`job/[id]/index.tsx`). */
export async function obtenirStatutChantier(interventionId: string): Promise<ResultatStatutChantier | null> {
  const config = await connexion();
  return config ? obtenirStatutChantierPur(config, interventionId) : null;
}
