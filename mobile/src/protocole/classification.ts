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
