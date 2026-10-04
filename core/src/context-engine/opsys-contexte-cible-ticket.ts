import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { resolveAgentIdFromSessionKey } from "../routing/session-key.js";
import { OPSYS_CIBLE_TICKET_SERVERS, isOpsysCibleTicketTool } from "./opsys-contexte-cibles.js";
import {
  readOpsysContexteConfig,
  type OpsysContexteConfigResult,
} from "./opsys-contexte-config.js";
import {
  evaluateGuard,
  OPSYS_GUARD_MAX_AGE_MS,
  opsysContexteGuardStore,
  type OpsysContexteGuardStore,
} from "./opsys-contexte-garde.js";
import { callOpsysMcpTool } from "./opsys-contexte-mcp.js";

const PRIVATE_TOOL = "opsys_contexte_creer_ticket_cible";
const MAX_TICKET_LIFETIME_MS = 125_000;

type TicketIssuer = (params: {
  config: OpenClawConfig | undefined;
  server: string;
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
}) => Promise<unknown>;

export type OpsysCibleTicketDeps = {
  readConfig?: () => OpsysContexteConfigResult;
  guardStore?: OpsysContexteGuardStore;
  callTool?: TicketIssuer;
  nowMs?: () => number;
};

function record(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

function snapshotToolArguments(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error("OPSYS target ticket requires a JSON object of final tool arguments");
  }
  let snapshot: unknown;
  try {
    snapshot = JSON.parse(JSON.stringify(value));
  } catch {
    throw new Error("OPSYS target ticket cannot serialize final tool arguments");
  }
  if (!isRecord(snapshot)) {
    throw new Error("OPSYS target ticket requires a JSON object of final tool arguments");
  }
  return snapshot;
}

/**
 * Issues a one-use Python-authorized target ticket immediately before the final MCP dispatch.
 * The business args are snapshotted once and that same snapshot must be sent to the business tool.
 */
export async function createOpsysCibleTicketMeta(
  params: {
    cfg: OpenClawConfig | undefined;
    serverName: string;
    toolName: string;
    toolParams: unknown;
    sessionKey: string | undefined;
    signal: AbortSignal;
  },
  deps: OpsysCibleTicketDeps = {},
): Promise<{ arguments: Record<string, unknown>; meta: Record<string, string> } | undefined> {
  if (!isOpsysCibleTicketTool(params.toolName)) {
    return undefined;
  }
  if (params.serverName !== OPSYS_CIBLE_TICKET_SERVERS[params.toolName]) {
    throw new Error("OPSYS target ticket refused: business tool/server mismatch");
  }
  const sessionKey = params.sessionKey;
  if (!sessionKey) {
    throw new Error("OPSYS target ticket refused: the current agent session is unavailable");
  }
  let agentId: string;
  try {
    agentId = resolveAgentIdFromSessionKey(sessionKey);
  } catch {
    throw new Error("OPSYS target ticket refused: the current agent session is invalid");
  }
  if (agentId === "main") {
    throw new Error("OPSYS target ticket refused: a department agent session is required");
  }

  const result = (deps.readConfig ?? readOpsysContexteConfig)();
  if (result.kind !== "enabled") {
    throw new Error("OPSYS target ticket refused: the active context configuration is unavailable");
  }
  const { config } = result;
  if (!config.agents.has(agentId)) {
    throw new Error("OPSYS target ticket refused: this agent has no active M10 context profile");
  }
  const contextServer = config.contextServers.get(agentId);
  if (!contextServer) {
    throw new Error("OPSYS target ticket refused: this agent has no private context server");
  }
  const target = config.targets.get(params.toolName);
  if (target?.kind !== "ticket") {
    throw new Error("OPSYS target ticket refused: no case-bound target contract is configured");
  }

  const args = snapshotToolArguments(params.toolParams);
  const nowMs = (deps.nowMs ?? Date.now)();
  const state = (deps.guardStore ?? opsysContexteGuardStore).get(sessionKey);
  const guard = evaluateGuard({
    toolName: params.toolName,
    sessionKey,
    agentId,
    config: result,
    state,
    toolParams: args,
    nowMs,
  });
  if (guard.block) {
    throw new Error(guard.reason);
  }
  if (state?.kind !== "ready" || nowMs - state.atMs > OPSYS_GUARD_MAX_AGE_MS) {
    throw new Error("OPSYS target ticket refused: the M10 case context is unavailable or stale");
  }
  const envelope = await (deps.callTool ?? callOpsysMcpTool)({
    config: params.cfg,
    server: contextServer,
    tool: PRIVATE_TOOL,
    args: {
      agent_id: agentId,
      cle_session: sessionKey,
      affaire_id: state.affaireId,
      origine_affaire: config.affaireFromSession.has(agentId) ? "session" : "demande",
      outil: params.toolName,
      arguments: args,
    },
    timeoutMs: config.timeoutMs,
    signal: params.signal,
  });
  const response = record(envelope);
  const payload = record(response?.resultat);
  const ticket = payload?.ticket;
  const expiresAt =
    typeof payload?.expire_le === "string" ? Date.parse(payload.expire_le) : Number.NaN;
  const responseAt = (deps.nowMs ?? Date.now)();
  if (
    response?.ok !== true ||
    typeof ticket !== "string" ||
    ticket.length === 0 ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= responseAt ||
    expiresAt - responseAt > MAX_TICKET_LIFETIME_MS
  ) {
    throw new Error("OPSYS target ticket service returned an invalid or expired ticket");
  }
  return { arguments: args, meta: { "opsys/cibleTicket": ticket } };
}
