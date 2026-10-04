import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import { resolveAgentIdFromSessionKey } from "../routing/session-key.js";

export const OPSYS_CFO_MCP_SERVER = "opsys_m5";

const OPSYS_CFO_GRANT_TOOLS = new Set([
  "m5_preparer_dossier_decision_cfo",
  "m5_preparer_decision_capital",
]);
const MAX_TICKET_LIFETIME_MS = 95_000;

type TicketIssuer = (params: {
  config: OpenClawConfig | undefined;
  server: string;
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
}) => Promise<unknown>;

export type OpsysCfoGrantTicketDeps = {
  callTool?: TicketIssuer;
  nowMs?: () => number;
};

function snapshotArguments(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error("OPSYS CFO grant refused: final arguments must be an object");
  }
  let snapshot: unknown;
  try {
    snapshot = JSON.parse(JSON.stringify(value));
  } catch {
    throw new Error("OPSYS CFO grant refused: final arguments are not serializable");
  }
  if (!isRecord(snapshot)) {
    throw new Error("OPSYS CFO grant refused: final arguments must be a JSON object");
  }
  return snapshot;
}

/** Issues a CFO grant ticket through the route bound to the active generated agent profile. */
export async function createOpsysCfoGrantTicketMeta(
  params: {
    config: OpenClawConfig | undefined;
    serverName: string;
    toolName: string;
    toolParams: unknown;
    sessionKey: string | undefined;
    signal: AbortSignal;
  },
  deps: OpsysCfoGrantTicketDeps = {},
): Promise<{ arguments: Record<string, unknown>; meta: Record<string, string> } | undefined> {
  if (!OPSYS_CFO_GRANT_TOOLS.has(params.toolName)) {
    return undefined;
  }
  if (params.serverName !== OPSYS_CFO_MCP_SERVER) {
    throw new Error("OPSYS CFO grant refused: business tool/server mismatch");
  }
  if (!params.sessionKey) {
    throw new Error("OPSYS CFO grant refused: current profile session is unavailable");
  }

  let agentId: string;
  try {
    agentId = resolveAgentIdFromSessionKey(params.sessionKey);
  } catch {
    throw new Error("OPSYS CFO grant refused: current profile session is invalid");
  }
  const matched = /^opsys-agent-([a-z][a-z0-9-]{1,63})$/u.exec(agentId);
  if (!matched) {
    throw new Error("OPSYS CFO grant refused: an OPSYS finance agent profile is required");
  }
  const profileId = matched[1];
  const entries = params.config?.agents?.entries;
  const entry = entries && Object.hasOwn(entries, agentId) ? entries[agentId] : undefined;
  const binding = entry?.opsysRuntimeAdmission;
  if (
    !binding ||
    binding.profileId !== profileId ||
    !Number.isSafeInteger(binding.profileRevision) ||
    (binding.profileRevision ?? 0) <= 0
  ) {
    throw new Error("OPSYS CFO grant refused: active generated profile revision is unavailable");
  }

  const args = snapshotArguments(params.toolParams);
  const value = await (deps.callTool ?? callOpsysMcpTool)({
    config: params.config,
    server: `opsys_runtime_${profileId}`,
    tool: "opsys_runtime_cfo_ticket",
    args: {
      outil: params.toolName,
      arguments: args,
      revision_profil: binding.profileRevision,
    },
    timeoutMs: 10_000,
    signal: params.signal,
  });
  const envelope = isRecord(value) ? value : undefined;
  const result = isRecord(envelope?.resultat) ? envelope.resultat : undefined;
  const ticket = result?.ticket;
  const expiresAt =
    typeof result?.expire_le === "string" ? Date.parse(result.expire_le) : Number.NaN;
  const responseAt = (deps.nowMs ?? Date.now)();
  if (
    envelope?.ok !== true ||
    typeof ticket !== "string" ||
    ticket.length === 0 ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= responseAt ||
    expiresAt - responseAt > MAX_TICKET_LIFETIME_MS
  ) {
    throw new Error("OPSYS CFO grant issuer returned an invalid or expired ticket");
  }
  return { arguments: args, meta: { "opsys/cfoGrantTicket": ticket } };
}
