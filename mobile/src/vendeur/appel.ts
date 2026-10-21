import type { HorlogeAppareil } from "../outbox/mutation";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { classerEchec, verdictDepuisEchec } from "../protocole/echec";
import type { DepotCleValeur } from "../stockage/depotCleValeur";

/**
 * Ce que tout chargeur du profil vendeur reçoit (PLAN T4.8) : le dépôt de cache, le transport, la session et
 * l'horloge, TOUT injecté (mission : aucune horloge, aucun réseau, aucun stockage en dur). `src/vendeur/service.ts`
 * fournit le câblage réel ; les tests, un faux transport et un dépôt mémoire.
 *
 * `personne` est celle que le serveur a confirmée pour ce jeton (`obtenirSessionEnvoi`) : elle préfixe chaque clé du
 * cache, et n'est JAMAIS envoyée au serveur (il la tient du jeton d'appareil).
 */
export interface ConfigurationChargeurVendeur {
  readonly depot: DepotCleValeur;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
  readonly personne: string;
  /** L'heure de l'appareil, avec son décalage : l'instant de référence de `m2_lister_leads` et de
   * `m2_suggerer_prochaine_action`, et la date d'un cache. */
  readonly horloge: () => HorlogeAppareil;
}

/**
 * Trois issues d'un appel de lecture, que rien ne confond (même règle que le profil admin, `src/protocole/echec.ts`) :
 *  - `reponse` : le serveur a répondu (par une donnée, ou par un refus de l'outil : c'est à l'enveloppe de le dire) ;
 *  - `injoignable` : le serveur n'a PAS pu répondre (réseau, délai, 408, 429, 5xx, réponse qui n'est pas celle du
 *    core) : un cache, marqué comme tel, peut servir ;
 *  - `refuse` : le serveur a répondu NON à cet appareil ou à cette requête (401, 403 de la porte d'appareil, autre 4xx
 *    du core) : un appareil dont le jeton est révoqué, la personne désactivée ou le rôle retiré NE RELIT PAS ses leads
 *    gardés. Un cache ne dit pas ce que le serveur refuse aujourd'hui : il ne remplace JAMAIS ce refus, et rien n'est
 *    écrit (PLAN T1.4-n ; avant, toute panne HTTP, 401 et 403 compris, retombait sur le cache).
 */
export type AppelLecture =
  | { readonly genre: "reponse"; readonly resultat: unknown }
  | { readonly genre: "injoignable"; readonly verdict: VerdictServeur }
  | { readonly genre: "refuse"; readonly verdict: VerdictServeur };

/**
 * UNE lecture (`/tools/invoke`), sans clé d'idempotence : rien n'est écrit. Ne lève jamais pour une raison réseau ou
 * HTTP : elle devient `injoignable` (`erreur_reseau`, `delai_depasse`, `tool_error`...) ou `refuse`
 * (`tool_call_blocked`, `http_401`...), avec le verdict de l'échec.
 */
export async function appelerLecture(
  config: ConfigurationChargeurVendeur,
  tool: string,
  args: Record<string, unknown>,
): Promise<AppelLecture> {
  const resultatAppel = await config.appelerOutil({
    fetchImpl: config.fetchImpl,
    urlBase: config.urlBase,
    jeton: config.jeton,
    requete: { tool, args },
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
    console.error("opsys: écriture du cache vendeur impossible (la lecture reste valable)", erreur);
  }
}
