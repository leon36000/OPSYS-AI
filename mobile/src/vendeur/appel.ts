import type { HorlogeAppareil } from "../outbox/mutation";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
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

/** Le serveur n'a pas pu répondre (réseau, délai, HTTP) : la lecture peut retomber sur le cache. */
export type AppelLecture =
  | { readonly genre: "reponse"; readonly resultat: unknown }
  | { readonly genre: "injoignable"; readonly verdict: VerdictServeur };

function verdictDepuisEchecAppel(echec: {
  readonly message: string;
  readonly erreur?: { readonly type: string; readonly message: string };
}): VerdictServeur {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

/**
 * UNE lecture (`/tools/invoke`), sans clé d'idempotence : rien n'est écrit. Ne lève jamais pour une raison réseau ou
 * HTTP : elle devient `injoignable` avec le verdict de l'échec (`erreur_reseau`, `tool_call_blocked`...).
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
    return { genre: "injoignable", verdict: verdictDepuisEchecAppel(resultatAppel.echec) };
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
