import { isPromise } from "node:util/types";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { callOpsysMcpTool, OpsysContexteMcpError } from "./opsys-contexte-mcp.js";

const HISTORY_TOOL = "opsys_contexte_lire_succes_m9";
const MAX_RESPONSE_BYTES = 16 * 1024;

/** Retained correlation only; neither an authority token nor proof of a committed Core intent. */
export type OpsysM9HistoryReference = Readonly<{
  contextServerName: string;
  agentId: string;
  sessionKey: string;
  affaireId: string;
  ticketHash: string;
  nativeInstanceId: string;
  requestId: string;
  toolName: string;
}>;

function boundedString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength;
}

/**
 * Reads one retained Native success reference. False remains unresolved, never permission to replay.
 * The caller must separately establish a current reconciliation purpose and authorized route.
 * No caller or closing-binding producer is installed by this module; closing inputs are fixture-only
 * until Core gains that producer. Acceptance here does not grant a database commit or settle an intent.
 */
export async function readOpsysM9HistoryConfirmation(params: {
  config: OpenClawConfig | undefined;
  expected: OpsysM9HistoryReference;
  timeoutMs: number;
  signal: AbortSignal;
  assertCurrent: () => void;
}): Promise<boolean> {
  const { config, timeoutMs, signal, assertCurrent } = params;
  // Capture every primitive once before connection; never consult the caller's expected object later.
  const {
    contextServerName,
    agentId,
    sessionKey,
    affaireId,
    ticketHash,
    nativeInstanceId,
    requestId,
    toolName,
  } = params.expected;
  if (
    typeof contextServerName !== "string" ||
    contextServerName.length === 0 ||
    !boundedString(agentId, 64) ||
    !boundedString(sessionKey, 256) ||
    !sessionKey.startsWith(`agent:${agentId}:`) ||
    !boundedString(affaireId, 197) ||
    typeof ticketHash !== "string" ||
    ticketHash.length !== 64 ||
    !/^[0-9a-f]{64}$/u.test(ticketHash) ||
    typeof nativeInstanceId !== "string" ||
    nativeInstanceId.length !== 36 ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(nativeInstanceId) ||
    typeof requestId !== "string" ||
    requestId.length !== 12 ||
    !/^[0-9a-f]{12}$/u.test(requestId) ||
    (toolName !== "m9_ouvrir_suivi_decision" && toolName !== "m9_clore_suivi_decision") ||
    typeof assertCurrent !== "function"
  ) {
    throw new OpsysContexteMcpError("OPSYS M9 history reference is invalid");
  }

  const checkCurrent = () => {
    try {
      signal.throwIfAborted();
      const result: unknown = assertCurrent();
      if (result !== undefined) {
        if (isPromise(result)) {
          void Promise.prototype.then.call(result, undefined, () => undefined);
        }
        throw new Error("invalid synchronous assertion");
      }
      signal.throwIfAborted();
    } catch {
      // Current-owner failures can contain private business data; keep this boundary nonsensitive.
      throw new OpsysContexteMcpError("OPSYS M9 history current authority rejected");
    }
  };
  const envelope = await callOpsysMcpTool({
    config,
    server: contextServerName,
    tool: HISTORY_TOOL,
    args: {
      agent_id: agentId,
      cle_session: sessionKey,
      affaire_id: affaireId,
      empreinte_ticket: ticketHash,
      demande_id: requestId,
      outil: toolName,
    },
    timeoutMs,
    signal,
    beforeRequest: checkCurrent,
    maxResponseBytes: MAX_RESPONSE_BYTES,
    awaitCleanup: true,
    requireSuccessfulResult: true,
  });
  // Cleanup is part of the awaited transport; its completion must not extend expired authority.
  checkCurrent();
  if (!isRecord(envelope) || envelope.ok !== true || !isRecord(envelope.resultat)) {
    throw new OpsysContexteMcpError("OPSYS M9 history service returned an invalid confirmation");
  }
  const confirmation = envelope.resultat;
  if (
    confirmation.schema !== 1 ||
    typeof confirmation.confirme !== "boolean" ||
    confirmation.instance_id !== nativeInstanceId ||
    confirmation.demande_id !== requestId ||
    confirmation.outil !== toolName
  ) {
    throw new OpsysContexteMcpError("OPSYS M9 history service returned an invalid confirmation");
  }
  return confirmation.confirme;
}
