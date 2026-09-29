import { interpreterAVoir } from "../admin/aVoir";
import { reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import type { FormeReponse, LecteurDeValeur } from "../admin/enveloppe";
import type { ResultatSection } from "../admin/lecture";
import type { ListeApprobations } from "../approbations/contrat";
import { lireDigest, lireInterventions, lirePreparation } from "../m4/dispatch";
import type { DigestDuJour, InterventionsLues, Preparation } from "../m4/dispatch";
import { lireEcheancesFiscales, lireEtatTresorerie, lirePrevisionTresorerie } from "../m5/tresorerie";
import type { EcheancesFiscales, EtatTresorerie, PrevisionLue } from "../m5/tresorerie";
import { lireVueExecutive } from "../m8/vueExecutive";
import type { VueExecutive } from "../m8/vueExecutive";

/**
 * Outillage des tests des modèles de vue du profil admin : une réponse RÉELLE du moteur (`admin/fixtures`), lue par le
 * lecteur de son outil, mise dans la forme qu'un chargeur rend (`ResultatSection`). Ce n'est pas du code de production.
 */

/** Ce qu'un chargeur rend pour une lecture faite au serveur à cet instant. */
export function duServeur<T>(valeur: T, misAJourLe = "2026-09-29T18:03:22.000Z"): ResultatSection<T> {
  return { source: "serveur", valeur, misAJourLe };
}

/** Ce qu'un chargeur rend quand le serveur n'a pas répondu et qu'une copie gardée existe. */
export function duCache<T>(valeur: T, code = "erreur_reseau", misAJourLe = "2026-09-28T13:30:00.000Z"): ResultatSection<T> {
  return { source: "cache", valeur, misAJourLe, raisonHorsLigne: { code, detail: "Network request failed" } };
}

function lue<T>(nom: string, forme: FormeReponse, lire: LecteurDeValeur<T>): T {
  const resultat = interpreter(reponse(nom), forme, lire);
  if (!resultat.ok) {
    throw new Error(`la réponse « ${nom} » de la fixture devrait être lisible : ${resultat.verdict.code}`);
  }
  return resultat.valeur;
}

export const tresorerieDe = (nom: string): EtatTresorerie => lue(nom, "directe", lireEtatTresorerie);
export const previsionDe = (nom: string): PrevisionLue => lue(nom, "couple", lirePrevisionTresorerie);
export const echeancesDe = (nom: string): EcheancesFiscales => lue(nom, "couple", lireEcheancesFiscales);
export const vueExecutiveDe = (nom: string): VueExecutive => lue(nom, "directe", lireVueExecutive);
export const digestDe = (nom: string): DigestDuJour => lue(nom, "couple", lireDigest);
export const preparationDe = (nom: string): Preparation => lue(nom, "couple", lirePreparation);
export const interventionsDe = (nom: string, statut: string): InterventionsLues =>
  lue(nom, "directe", (valeur) => lireInterventions(valeur, statut));

export function aVoirDe(nom: string): ListeApprobations {
  const lu = interpreterAVoir(reponse(nom));
  if (!lu.ok) {
    throw new Error(`la réponse « ${nom} » de la fixture devrait être lisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}
