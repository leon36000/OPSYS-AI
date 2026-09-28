/**
 * Forme exacte de `POST /tools/invoke`, lue dans le fork (lecture seule — ADR-0008, le core ne
 * s'exécute jamais dans ce bac à sable) :
 *  - requête : `core/src/gateway/tools-invoke-shared.ts` (`ToolsInvokeInput` : `tool`/`name`,
 *    `args`, `action`, `sessionKey`, `agentId`, `idempotencyKey`) ; le champ `tool` est celui
 *    utilisé par les appels réels du fork (`core/src/gateway/tools-invoke-http.test.ts`,
 *    `postToolsInvoke`/`invokeAgentsListBearer`) — on s'y aligne plutôt que sur l'alias `name`.
 *  - authentification : en-tête `authorization: Bearer <jeton>` (même test, `invokeAgentsListBearer`).
 *  - réponse : `core/src/gateway/tools-invoke-http.ts` -> `sendJson(res, outcome.status, ...)` avec
 *    `{ ok: true, result }` (HTTP 200) ou `{ ok: false, error }` (HTTP 400/403/404/500), et le
 *    catalogue fermé d'erreurs de `core/src/gateway/tools-invoke-shared.ts` (`ToolsInvokeOutcome`).
 */
export interface RequeteOutilsInvoke {
  readonly tool: string;
  readonly args?: Record<string, unknown>;
  readonly action?: string;
  readonly sessionKey?: string;
  readonly agentId?: string;
  /** = `mutation_id` de src/outbox pour tout appel émis par la file sortante (R12 §4). */
  readonly idempotencyKey?: string;
}

/** Catalogue fermé lu dans `ToolsInvokeOutcome` (tools-invoke-shared.ts). */
export type TypeErreurOutilsInvoke = "invalid_request" | "not_found" | "tool_call_blocked" | "tool_error";

export interface ErreurOutilsInvoke {
  readonly type: TypeErreurOutilsInvoke;
  readonly message: string;
  readonly requiresApproval?: boolean;
}

export type CorpsReponseOutilsInvoke<R = unknown> =
  | { readonly ok: true; readonly result: R }
  | { readonly ok: false; readonly error: ErreurOutilsInvoke };
