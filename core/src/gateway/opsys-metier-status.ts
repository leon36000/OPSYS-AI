// Live state of the OPSYS business engine (Python) that the Gateway launches and supervises
// (OPSYS-AI PLAN T0.10, `opsys-metier-supervisor.ts`).
//
// Process-global holder read by the `health` and `status` RPC handlers, on the model of
// `agents/prepared-model-runtime.startup-status.ts`. It stays `undefined` while supervision is
// off (the default), so the wire payloads of an unconfigured Gateway do not change. It never
// carries the engine token: only where the token came from.

export type OpsysMetierState =
  /** Process launched; the first successful health probe has not been seen yet. */
  | "starting"
  /** The last health probe answered. */
  | "running"
  /** Probes are failing but the restart threshold is not reached yet. */
  | "unhealthy"
  /** Waiting out the backoff before the next launch. */
  | "restarting"
  /** Supervision gave up or refused to start: an operator has to act. */
  | "failed";

export type OpsysMetierLastExit = Readonly<{
  /** Why the run ended: `exited`, `unhealthy`, `not-ready` or `spawn-failed`. */
  reason: string;
  code: number | null;
  signal: string | null;
  atMs: number;
}>;

export type OpsysMetierStatus = Readonly<{
  state: OpsysMetierState;
  /** Restarts scheduled since the Gateway started supervising. */
  restarts: number;
  /** Health probe URL. Absent when the configuration was refused before it was resolved. */
  healthUrl?: string;
  /** Where the shared engine token came from. The token itself is never exposed. */
  tokenSource?: "env" | "generated";
  pid?: number;
  startedAtMs?: number;
  lastHealthyAtMs?: number;
  lastExit?: OpsysMetierLastExit;
  /** Operator-facing reason for `unhealthy`, `restarting` and `failed`. */
  error?: string;
}>;

let current: OpsysMetierStatus | undefined;

/** Diagnostic projection of the supervisor; `undefined` when supervision is off. */
export function getOpsysMetierStatus(): OpsysMetierStatus | undefined {
  return current;
}

export function setOpsysMetierStatus(value: OpsysMetierStatus | undefined): void {
  current = value;
}
