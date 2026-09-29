import { creerChargeurDevis } from "./chargeurDevis";
import type { EntreeDevis, ResultatDevis } from "./chargeurDevis";
import { creerChargeurFiche } from "./chargeurFiche";
import type { ResultatFiche } from "./chargeurFiche";
import { creerChargeurLeads } from "./chargeurLeads";
import type { ResultatLeads, SuiteLeads } from "./chargeurLeads";
import type { LeadsLus } from "./lectureLeads";
import type { ConfigurationChargeurVendeur } from "./appel";
import type { FiltreLeads } from "../m2/listeLeads";
import { invoquerOutil } from "../protocole/client";
import { obtenirSessionEnvoi } from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";

/**
 * Câblage RÉEL des chargeurs du profil vendeur (`(seller)/leads.tsx`, `lead/[id].tsx`, `quotes.tsx`, PLAN T4.8) :
 * `fetch`, le dépôt clé/valeur local (`expo-sqlite`) et la session de l'appareil. Même philosophie que
 * `src/today/service.ts` : `null` tant qu'aucune session n'existe — jamais une lecture inventée. Non testé (pas de
 * SQLite natif ni de réseau sous Jest, même limite que `src/outbox/service.ts`) : tout ce qu'il assemble est testé
 * dans `src/vendeur/*.test.ts`.
 *
 * La session est `obtenirSessionEnvoi` : le jeton COURANT et la personne que le serveur a confirmée POUR CE JETON. Elle
 * est relue à chaque appel (jamais gardée) : après un nouvel appairage, le cache d'une autre personne n'est plus lu.
 */
async function configuration(): Promise<ConfigurationChargeurVendeur | null> {
  const session = obtenirSessionEnvoi();
  if (!session) {
    return null;
  }
  return {
    depot: await obtenirDepotLocal(),
    appelerOutil: invoquerOutil,
    fetchImpl: fetch,
    urlBase: session.urlBase,
    jeton: session.jeton,
    personne: session.personne,
    horloge: () => ({ maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() }),
  };
}

export async function chargerLeads(filtre: FiltreLeads): Promise<ResultatLeads | null> {
  const config = await configuration();
  return config ? creerChargeurLeads(config).chargerLeads(filtre) : null;
}

export async function chargerSuiteLeads(lues: LeadsLus): Promise<SuiteLeads | null> {
  const config = await configuration();
  return config ? creerChargeurLeads(config).chargerSuite(lues) : null;
}

export async function chargerFiche(leadId: string): Promise<ResultatFiche | null> {
  const config = await configuration();
  return config ? creerChargeurFiche(config).chargerFiche(leadId) : null;
}

export async function chargerDevis(): Promise<ResultatDevis | null> {
  const config = await configuration();
  return config ? creerChargeurDevis(config).chargerDevis() : null;
}

/** `undefined` : pas de session. `null` : numéro vide, rien n'a été demandé. */
export async function ouvrirDevisParNumero(numero: string): Promise<EntreeDevis | null | undefined> {
  const config = await configuration();
  return config ? creerChargeurDevis(config).ouvrirParNumero(numero) : undefined;
}
