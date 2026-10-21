import { chargerSession, coffreExpoSecureStore, type CoffreAppairage } from "../appairage/stockage";
import type { ConfigurationAppel } from "../protocole/configuration";
import { lireIdentiteServeur } from "./client";
import type { ResultatLectureIdentite } from "./contrat";
import { decider, restaurerEtat, type EtatIdentite } from "./etat";
import {
  chargerIdentiteMemorisee,
  effacerIdentiteMemorisee,
  sauvegarderIdentiteMemorisee,
  type IdentiteMemorisee,
} from "./stockage";

/**
 * Câblage de l'identité de l'appareil (PLAN T1.4-c5) : lecture du coffre au démarrage, lecture auprès du
 * serveur, décision (`etat.ts`, pure), et écriture de la dernière identité confirmée. Rien ici ne lève
 * pour une raison de réseau ou de coffre : un échec est un état (`indisponible`, `stockage_illisible`),
 * jamais un profil deviné ni une application figée.
 */

function signaler(message: string, erreur: unknown): void {
  // Aucun secret dans le message : ni jeton, ni clé, seulement le nom de l'opération et l'erreur.
  // eslint-disable-next-line no-console
  console.error(`opsys: ${message}`, erreur);
}

export interface RestaurationSession {
  /** `null` : pas d'appairage, ou coffre illisible. */
  readonly configuration: ConfigurationAppel | null;
  readonly etat: EtatIdentite;
}

/**
 * Relit la session appairée et la dernière identité confirmée. Un coffre illisible n'est PAS « non
 * appairé » (on ne renvoie pas la personne à l'appairage pour une panne passagère du Keychain ou du
 * Keystore) : c'est une erreur, qu'on peut réessayer.
 */
export async function restaurerSession(coffre: CoffreAppairage = coffreExpoSecureStore): Promise<RestaurationSession> {
  try {
    const session = await chargerSession(coffre);
    if (!session) {
      return { configuration: null, etat: { genre: "non_appairee" } };
    }
    const memorisee = await chargerIdentiteMemorisee(session.appareilId, coffre);
    return {
      configuration: { urlBase: session.urlBase, jeton: session.jeton, appareilId: session.appareilId },
      etat: restaurerEtat(session, memorisee),
    };
  } catch (erreur) {
    signaler("coffre sécurisé illisible au démarrage", erreur);
    return { configuration: null, etat: { genre: "erreur", motif: "stockage_illisible" } };
  }
}

export interface OptionsLectureIdentite {
  readonly configuration: ConfigurationAppel;
  readonly coffre?: CoffreAppairage;
  /** Injecté pour les tests ; en production, `GET /opsys/identite` par `fetch`. */
  readonly lire?: (configuration: ConfigurationAppel) => Promise<ResultatLectureIdentite>;
  readonly maintenant?: () => Date;
}

/**
 * Lit l'identité auprès du serveur, décide du nouvel état et met à jour la dernière identité confirmée
 * (gardée si confirmée, effacée si le serveur refuse l'appareil). Ne lève jamais.
 */
export async function lireEtMemoriserIdentite(options: OptionsLectureIdentite): Promise<EtatIdentite> {
  const { configuration } = options;
  const coffre = options.coffre ?? coffreExpoSecureStore;
  const lire =
    options.lire ??
    ((c: ConfigurationAppel) =>
      lireIdentiteServeur({ fetchImpl: fetch, urlBase: c.urlBase, jeton: c.jeton, appareilId: c.appareilId }));
  const maintenant = options.maintenant ?? (() => new Date());

  let memorisee: IdentiteMemorisee | null = null;
  try {
    memorisee = await chargerIdentiteMemorisee(configuration.appareilId, coffre);
  } catch (erreur) {
    signaler("identité gardée illisible", erreur);
  }

  let resultat: ResultatLectureIdentite;
  try {
    resultat = await lire(configuration);
  } catch (erreur) {
    signaler("lecture de l'identité impossible", erreur);
    resultat = { genre: "indisponible", message: "lecture impossible" };
  }
  const decision = decider(memorisee, resultat, maintenant());

  try {
    if (decision.ecriture?.genre === "memoriser") {
      await sauvegarderIdentiteMemorisee(decision.ecriture.identite, coffre);
    } else if (decision.ecriture?.genre === "effacer") {
      await effacerIdentiteMemorisee(coffre);
    }
  } catch (erreur) {
    signaler("identité confirmée non enregistrée", erreur);
  }
  return decision.etat;
}

/** Un nouvel appairage repart de zéro : l'identité gardée d'avant ne vaut plus rien. */
export async function oublierIdentiteMemorisee(coffre: CoffreAppairage = coffreExpoSecureStore): Promise<void> {
  try {
    await effacerIdentiteMemorisee(coffre);
  } catch (erreur) {
    signaler("identité gardée non effacée", erreur);
  }
}
