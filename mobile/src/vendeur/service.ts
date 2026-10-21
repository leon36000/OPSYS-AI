import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import { creerChargeurDevis } from "./chargeurDevis";
import type { EntreeDevis, ResultatInventaireDevis } from "./chargeurDevis";
import { creerChargeurFiche } from "./chargeurFiche";
import type { ResultatFiche } from "./chargeurFiche";
import {
  chargerReadiness as chargerReadinessSansCache,
  memeSessionReadiness,
  resultatSiMemeSession,
} from "./chargeurReadiness";
import type { ResultatReadiness } from "../m2/readiness";
import { creerChargeurLeads } from "./chargeurLeads";
import type { ResultatLeads, SuiteLeads } from "./chargeurLeads";
import type { LeadsLus } from "./lectureLeads";
import type { ConfigurationChargeurVendeur } from "./appel";
import type { FiltreLeads } from "../m2/listeLeads";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionLecture, obtenirSessionEnvoi } from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";
import { supprimerCacheDevis, purgerCachesDevis } from "./cache";

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

/** Lecture fraîche de la gate M2 : aucun cache local ne peut affirmer qu'une tête de registre est encore valide. */
export async function chargerReadiness(leadId: string, personneAttendue: string): Promise<ResultatReadiness | null> {
  try {
    const config = await configuration();
    if (config === null || config.personne !== personneAttendue || !memeSessionReadiness(config, obtenirSessionEnvoi())) {
      return null;
    }
    const resultat = await chargerReadinessSansCache(config, leadId);
    return resultatSiMemeSession(config, obtenirSessionEnvoi(), resultat);
  } catch {
    return null;
  }
}

export async function chargerDevis(): Promise<ResultatInventaireDevis | null> {
  try {
    const config = await configuration();
    if (config === null) {
      return null;
    }
    const resultat = await creerChargeurDevis(config).chargerInventaire();
    return resultatSiMemeSession(config, obtenirSessionEnvoi(), resultat);
  } catch {
    return null;
  }
}

/** Charge une suite seulement sous la même personne que celle qui a reçu le curseur précédent. */
export async function chargerSuiteDevis(
  curseur: string,
  personneAttendue: string,
): Promise<ResultatInventaireDevis | null> {
  try {
    const config = await configuration();
    if (config === null || config.personne !== personneAttendue) {
      return null;
    }
    const resultat = await creerChargeurDevis(config).chargerInventaire(curseur);
    return resultatSiMemeSession(config, obtenirSessionEnvoi(), resultat);
  } catch {
    return null;
  }
}

/** `undefined` : pas de session. `null` : numéro vide, rien n'a été demandé. */
export async function ouvrirDevisParNumero(numero: string): Promise<EntreeDevis | null | undefined> {
  try {
    const config = await configuration();
    if (config === null) {
      return undefined;
    }
    const entree = await creerChargeurDevis(config).ouvrirParNumero(numero);
    if (!memeSessionReadiness(config, obtenirSessionEnvoi())) {
      return undefined;
    }
    if (entree?.etat.genre === "refus") {
      const { code } = entree.etat.verdict;
      if (code === "REJ-DEVIS-INTROUVABLE") {
        await supprimerCacheDevis(config.depot, config.personne, entree.connu.devisId);
      } else if ([
        "REJ-IDENTITE-APPAREIL-INVALIDE",
        "tool_call_blocked",
        "http_401",
        "http_403",
        "hors_portee_role",
        "refus_metier",
      ].includes(code)) {
        await purgerCachesDevis(config.depot, config.personne);
      }
    }
    return entree;
  } catch {
    return undefined;
  }
}
