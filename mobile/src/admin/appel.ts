import type { HorlogeAppareil } from "../outbox/mutation";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { EchecAppelOutil, ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { DepotCleValeur } from "../stockage/depotCleValeur";

/**
 * Ce que tout chargeur du profil admin reçoit (PLAN T4.20) : le dépôt de cache, le transport, la session et l'horloge,
 * TOUT injecté (aucune horloge, aucun réseau, aucun stockage en dur). `src/admin/service.ts` fournit le câblage réel ;
 * les tests, un faux transport et un dépôt mémoire. Même patron que `src/vendeur/appel.ts`, recopié plutôt que partagé :
 * le profil vendeur (T4.8) reste intact, et chaque profil garde ses propres règles de cache.
 *
 * `personne` est celle que le serveur a confirmée pour ce jeton (`obtenirSessionEnvoi`) : elle préfixe chaque clé du
 * cache, et n'est JAMAIS envoyée au serveur (il la tient du jeton d'appareil).
 */
export interface ConfigurationChargeurAdmin {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
  readonly personne: string;
  /** L'heure de l'appareil, avec son décalage : le jour de référence que M5 et M4 demandent, et la date d'un cache. */
  readonly horloge: () => HorlogeAppareil;
}

/**
 * Trois issues d'un appel de lecture, que rien ne confond :
 *  - `reponse` : le serveur a répondu (par une donnée, ou par un refus de l'outil : c'est à l'enveloppe de le dire) ;
 *  - `injoignable` : le serveur n'a PAS pu répondre (réseau, délai, 408, 429, 5xx, réponse qui n'est pas celle du
 *    core) : un cache, marqué comme tel, peut servir ;
 *  - `refuse` : le serveur a répondu NON à cet appareil ou à cette requête (401, 403 de la porte d'appareil, 400 ou
 *    404 du core) : un cache ne dit pas ce que le serveur refuse aujourd'hui, il ne remplace JAMAIS ce refus.
 */
export type AppelLecture =
  | { readonly genre: "reponse"; readonly resultat: unknown }
  | { readonly genre: "injoignable"; readonly verdict: VerdictServeur }
  | { readonly genre: "refuse"; readonly verdict: VerdictServeur };

/**
 * Le serveur a-t-il dit non, ou n'a-t-il pas pu répondre ? Fail-closed du côté du cache :
 *  - réseau et délai : injoignable ;
 *  - 408, 429 et 5xx (`reessayable`) : injoignable ;
 *  - 401 et 403 : refus, quel que soit le corps (la porte d'appareil dit non à cet appareil, ou l'outil est hors de sa
 *    portée : montrer des chiffres gardés à un appareil qu'on vient de refuser serait pire qu'un écran vide) ;
 *  - autre 4xx : refus SEULEMENT si le corps est celui du core (`erreur` structurée) ; sinon la réponse n'est pas du
 *    core (une page de connexion d'un réseau d'hôtel, un mandataire) : injoignable.
 */
export function classerEchec(echec: EchecAppelOutil): "refuse" | "injoignable" {
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

/**
 * UNE lecture (`/tools/invoke`), sans clé d'idempotence : rien n'est écrit. Ne lève jamais pour une raison réseau ou
 * HTTP : elle devient `injoignable` ou `refuse`, avec le verdict de l'échec.
 */
export async function appelerLecture(
  config: ConfigurationChargeurAdmin,
  tool: string,
  args: Readonly<Record<string, unknown>>,
): Promise<AppelLecture> {
  const resultatAppel = await config.appelerOutil({
    fetchImpl: config.fetchImpl,
    urlBase: config.urlBase,
    jeton: config.jeton,
    requete: { tool, args: { ...args } },
  });
  if (!resultatAppel.ok) {
    return { genre: classerEchec(resultatAppel.echec), verdict: verdictDepuisEchec(resultatAppel.echec) };
  }
  return { genre: "reponse", resultat: resultatAppel.result };
}

/** Un cache est un mieux-que-rien : si l'écrire échoue (SQLite), la lecture qui vient de réussir n'est pas perdue. */
export async function ecrireSansEchouer(ecriture: () => Promise<void>): Promise<void> {
  try {
    await ecriture();
  } catch (erreur) {
    // eslint-disable-next-line no-console
    console.error("opsys: écriture du cache admin impossible (la lecture reste valable)", erreur);
  }
}
