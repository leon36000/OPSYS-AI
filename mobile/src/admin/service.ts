import { creerChargeurStock } from "./stock";
import { creerChargeurComptes } from "./comptes";
import { creerChargeurBriefing } from "./briefing";
import type { SectionBriefing } from "../m9/briefing";
import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import type { EcheancesFiscales, EtatTresorerie, PrevisionLue, PrevisionTresorerie } from "../m5/tresorerie";
import type { DigestDuJour, Preparation } from "../m4/dispatch";
import type { VueExecutive } from "../m8/vueExecutive";
import type { ListeApprobations } from "../approbations/contrat";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionLecture } from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";
import type { ConfigurationChargeurAdmin } from "./appel";
import { creerChargeurAVoir } from "./aVoir";
import { creerChargeurChantiers } from "./chantiers";
import type { GroupeInterventions } from "./chantiers";
import { creerChargeurChiffres } from "./chiffres";
import type { SuitePrevision } from "./chiffres";
import type { ResultatSection } from "./lecture";

/**
 * Câblage RÉEL des chargeurs du profil admin (`(admin)/admin.tsx`, `chiffres.tsx`, `chantiers.tsx`, PLAN T4.20) :
 * `fetch`, le dépôt clé/valeur local (`expo-sqlite`) et la session de l'appareil. Même philosophie que
 * `src/vendeur/service.ts` : `null` tant qu'aucune session n'existe — jamais une lecture inventée. Non testé (pas de
 * SQLite natif ni de réseau sous Jest) : tout ce qu'il assemble est testé dans `src/admin/*.test.ts`.
 *
 * La session est `obtenirSessionEnvoi` : le jeton COURANT et la personne que le serveur a confirmée POUR CE JETON. Elle
 * est relue à chaque appel (jamais gardée) : après un nouvel appairage, le cache d'une autre personne n'est plus lu.
 */
async function configuration(): Promise<ConfigurationChargeurAdmin | null> {
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

export async function chargerAVoir(): Promise<ResultatSection<ListeApprobations> | null> {
  const config = await configuration();
  return config ? creerChargeurAVoir(config).chargerAVoir() : null;
}

export async function chargerVueExecutive(): Promise<ResultatSection<VueExecutive> | null> {
  const config = await configuration();
  return config ? creerChargeurChiffres(config).chargerVueExecutive() : null;
}

export async function chargerTresorerie(): Promise<ResultatSection<EtatTresorerie> | null> {
  const config = await configuration();
  return config ? creerChargeurChiffres(config).chargerTresorerie() : null;
}

export async function chargerPrevision(): Promise<ResultatSection<PrevisionLue> | null> {
  const config = await configuration();
  return config ? creerChargeurChiffres(config).chargerPrevision() : null;
}

export async function chargerEcheances(): Promise<ResultatSection<EcheancesFiscales> | null> {
  const config = await configuration();
  return config ? creerChargeurChiffres(config).chargerEcheances() : null;
}

export async function chargerSuitePrevision(lue: PrevisionTresorerie): Promise<SuitePrevision | null> {
  const config = await configuration();
  return config ? creerChargeurChiffres(config).chargerSuitePrevision(lue) : null;
}

export async function chargerGroupesDeChantiers(): Promise<readonly GroupeInterventions[] | null> {
  const config = await configuration();
  return config ? creerChargeurChantiers(config).chargerGroupes() : null;
}

export async function chargerDigestDuJour(): Promise<ResultatSection<DigestDuJour> | null> {
  const config = await configuration();
  return config ? creerChargeurChantiers(config).chargerDigest() : null;
}

export async function chargerPreparation(interventionId: string): Promise<ResultatSection<Preparation> | null> {
  const config = await configuration();
  return config ? creerChargeurChantiers(config).chargerPreparation(interventionId) : null;
}

export async function chargerBriefingM9(maintenant: string) {
  const config = await configuration();
  return config ? creerChargeurBriefing(config).chargerBriefing(maintenant) : null;
}
export async function chargerSuiteBriefingM9(maintenant: string, section: SectionBriefing, depart: number) {
  const config = await configuration();
  return config ? creerChargeurBriefing(config).chargerSuite(maintenant, section, depart) : null;
}
export async function chargerAlertesM9(depart = 0) {
  const config = await configuration();
  return config ? creerChargeurBriefing(config).chargerAlertes(depart) : null;
}
export async function chargerEtatConsolideM9() {
  const config = await configuration();
  return config ? creerChargeurBriefing(config).chargerEtat() : null;
}

export async function chargerCreancesM5() {
  const config = await configuration();
  return config ? creerChargeurComptes(config).chargerCreances() : null;
}
export async function chargerComptesAPM5(sansPO = false, depart = 0) {
  const config = await configuration();
  return config ? creerChargeurComptes(config).chargerAP(sansPO, depart) : null;
}
export async function chargerAttentesFacturationM5() {
  const config = await configuration();
  return config ? creerChargeurComptes(config).chargerAttentes() : null;
}

export async function chargerDisponibiliteM6() {
  const config = await configuration();
  return config ? creerChargeurStock(config).chargerDisponibilite() : null;
}
export async function chargerDigestM6() {
  const config = await configuration();
  return config ? creerChargeurStock(config).chargerDigest() : null;
}
