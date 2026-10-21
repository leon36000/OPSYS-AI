import type { VerdictServeur } from "../outbox/vidangeur";
import type { EchecAppelOutil } from "./client";

/**
 * Ce qu'un échec de `/tools/invoke` dit d'une LECTURE (PLAN T4.20, repris par le profil vendeur et l'employé, PLAN
 * T1.4-n) : le serveur a-t-il dit non, ou n'a-t-il pas pu répondre ? La règle est écrite ici, une seule fois, pour les
 * trois profils : c'est elle qui décide si un cache peut servir.
 *
 *  - `injoignable` : le serveur n'a PAS pu répondre (réseau, délai, 408, 429, 5xx, réponse qui n'est pas celle du core).
 *    Un cache, marqué comme tel (date, raison), peut servir ;
 *  - `refuse` : le serveur a répondu NON à cet appareil ou à cette requête (401, 403, autre 4xx du core). Un cache ne dit
 *    pas ce que le serveur refuse aujourd'hui : il ne remplace JAMAIS ce refus, et rien n'est écrit.
 */
export type GenreEchec = "refuse" | "injoignable";

/**
 * Fail-closed du côté du cache :
 *  - réseau et délai : injoignable ;
 *  - 408, 429 et 5xx (`reessayable`) : injoignable ;
 *  - 401 et 403 : refus, quel que soit le corps (la porte d'appareil dit non à cet appareil, ou l'outil est hors de sa
 *    portée : montrer des données gardées à un appareil qu'on vient de refuser serait pire qu'un écran vide) ;
 *  - autre 4xx : refus SEULEMENT si le corps est celui du core (`erreur` structurée) ; sinon la réponse n'est pas du
 *    core (une page de connexion d'un réseau d'hôtel, un mandataire) : injoignable.
 */
export function classerEchec(echec: EchecAppelOutil): GenreEchec {
  if (echec.origine !== "http" || echec.reessayable) {
    return "injoignable";
  }
  if (echec.status === 401 || echec.status === 403) {
    return "refuse";
  }
  return echec.erreur !== undefined ? "refuse" : "injoignable";
}

/** Le verdict d'un échec d'appel : le mot du core quand il en a un, sinon le fait (HTTP, délai, réseau). */
export function verdictDepuisEchec(echec: EchecAppelOutil): VerdictServeur {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  if (echec.status !== undefined) {
    return { code: `http_${echec.status}`, detail: echec.message };
  }
  return { code: echec.origine === "delai" ? "delai_depasse" : "erreur_reseau", detail: echec.message };
}
