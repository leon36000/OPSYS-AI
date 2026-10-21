/**
 * Classement des échecs HTTP de `/tools/invoke` (PLAN T1.4-a item 5) : 408 (délai serveur) et
 * 429 (débit) sont transitoires côté serveur, tout comme une 5xx (panne/erreur d'exécution
 * d'outil, `tool_error` du fork) ; les autres 4xx (400 `invalid_request`, 403
 * `tool_call_blocked`, 404 `not_found`) sont des refus définitifs pour cette requête telle
 * quelle — la réessayer sans changement ne changerait pas l'issue.
 */
export function estStatutReessayable(status: number): boolean {
  if (status === 408 || status === 429) {
    return true;
  }
  return status >= 500 && status <= 599;
}

/** Ce que l'app a besoin de lire d'un échec de `/tools/invoke` pour savoir si c'est l'APPAREIL qui est
 * refusé (et non la mutation). Forme minimale, pour ne pas dépendre de `client.ts`. */
export interface EchecLisibleParClassification {
  readonly status?: number;
  readonly erreur?: { readonly message: string };
}

/**
 * Le serveur refuse-t-il l'APPAREIL lui-même, quelle que soit la mutation ? Deux cas, lus dans le fork
 * (lecture seule, ADR-0008) :
 *  - 401 : jeton d'appareil inconnu ou révoqué (`sendUnauthorized`, `http-common.ts` ; corps
 *    `{ error: { type: "unauthorized" } }`, sans `ok`) ;
 *  - 403 `tool_call_blocked` dont le message nomme `device_unknown` (appareil sans attribution OPSYS :
 *    jamais faite, ou révoquée) ou `role_unknown` (rôle que la passerelle ne déclare pas) —
 *    `tools-invoke-shared.ts`, `OPSYS device is not authorized to call "<outil>" (<raison>).`
 *
 * Tout autre refus reste un refus de LA mutation, jamais de l'appareil : `tool_out_of_scope` et
 * `server_unknown` (cet outil n'est pas permis à ce rôle), `deviceId` du corps différent de celui du
 * jeton, 400, 404. Les traiter comme un refus d'appareil bloquerait toute la file derrière une seule
 * mutation refusée pour son outil. Fail-closed dans l'autre sens : un 403 dont le message ne nomme aucune
 * de ces deux raisons N'EST PAS lu comme un refus d'appareil.
 */
export function estRefusAppareil(echec: EchecLisibleParClassification): boolean {
  if (echec.status === 401) {
    return true;
  }
  if (echec.status === 403) {
    const message = echec.erreur?.message ?? "";
    return message.includes("(device_unknown)") || message.includes("(role_unknown)");
  }
  return false;
}
