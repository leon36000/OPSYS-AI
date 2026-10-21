import fs from "node:fs";
import path from "node:path";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import {
  readOpsysContexteConfig,
  type OpsysContexteConfigResult,
} from "../context-engine/opsys-contexte-config.js";
import { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import { resolveOpsysDir } from "../gateway/opsys-metier-config.js";
import { resolveAgentIdFromSessionKey } from "../routing/session-key.js";

export const OPSYS_MEMOIRE_META = "opsys/memoireLectureTicket";
type Binding = { departement: string; mode: "global" | "client_session" };
type Policy = {
  version: 1;
  departements: Record<string, Binding["mode"]>;
  agents: Record<string, Binding>;
  procedures_globales: ["procedures"];
};
type Issuer = (params: {
  config: OpenClawConfig | undefined;
  server: string;
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
}) => Promise<unknown>;
export type OpsysMemoireDeps = {
  readPolicy?: () => unknown;
  readContext?: () => OpsysContexteConfigResult;
  callTool?: Issuer;
  nowMs?: () => number;
};

function readPolicy(): unknown {
  const fd = fs.openSync(
    path.join(resolveOpsysDir(), "memoire-autorites.json"),
    fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW,
  );
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > 131072) {
      throw new Error("Invalid OPSYS memory authority file");
    }
    const bytes = Buffer.alloc(131073);
    const count = fs.readSync(fd, bytes, 0, bytes.length, null);
    if (count > 131072) {
      throw new Error("Oversized OPSYS memory authority file");
    }
    return JSON.parse(bytes.subarray(0, count).toString("utf8"));
  } finally {
    fs.closeSync(fd);
  }
}

export function parseOpsysMemoirePolicy(raw: unknown): Policy {
  if (
    !isRecord(raw) ||
    Object.keys(raw).toSorted().join(",") !== "agents,departements,procedures_globales,version" ||
    raw.version !== 1 ||
    !isRecord(raw.departements) ||
    !isRecord(raw.agents) ||
    !Array.isArray(raw.procedures_globales) ||
    raw.procedures_globales.length !== 1 ||
    raw.procedures_globales[0] !== "procedures"
  ) {
    throw new Error("OPSYS memory refused: explicit server classification is unavailable");
  }
  for (const [department, mode] of Object.entries(raw.departements)) {
    if (!department.startsWith("m") || (mode !== "global" && mode !== "client_session")) {
      throw new Error("OPSYS memory refused: invalid department classification");
    }
  }
  for (const [agent, binding] of Object.entries(raw.agents)) {
    if (
      !agent ||
      agent.length > 96 ||
      !isRecord(binding) ||
      Object.keys(binding).toSorted().join(",") !== "departement,mode" ||
      typeof binding.departement !== "string" ||
      !Object.hasOwn(raw.departements, binding.departement) ||
      binding.mode !== raw.departements[binding.departement]
    ) {
      throw new Error("OPSYS memory refused: invalid agent classification");
    }
  }
  return raw as Policy;
}

function snapshotArguments(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error("OPSYS memory refused: final arguments must be an object");
  }
  let snapshot: unknown;
  try {
    // JSON wire snapshot, as for CFO; structuredClone would preserve non-JSON values.
    // oxlint-disable-next-line unicorn/prefer-structured-clone -- preserve the exact JSON MCP wire snapshot
    snapshot = JSON.parse(JSON.stringify(value));
  } catch {
    throw new Error("OPSYS memory refused: final arguments are not serializable");
  }
  if (!isRecord(snapshot)) {
    throw new Error("OPSYS memory refused: final arguments must be a JSON object");
  }
  return snapshot;
}

/** Final arguments are sealed by Python against the live M10 session and canonical M2 client. */
export async function createOpsysMemoireLectureMeta(
  params: {
    config: OpenClawConfig | undefined;
    serverName: string;
    toolName: string;
    toolParams: unknown;
    sessionKey: string | undefined;
    signal: AbortSignal;
  },
  deps: OpsysMemoireDeps = {},
): Promise<{ arguments: Record<string, unknown>; meta: Record<string, string> } | undefined> {
  if (params.toolName !== "opsys_memoire_rechercher") {
    return undefined;
  }
  const policy = parseOpsysMemoirePolicy((deps.readPolicy ?? readPolicy)());
  if (!params.sessionKey) {
    throw new Error("OPSYS memory refused: current session is unavailable");
  }
  const agent = resolveAgentIdFromSessionKey(params.sessionKey);
  const binding = Object.hasOwn(policy.agents, agent) ? policy.agents[agent] : undefined;
  if (!binding || params.serverName !== `opsys_m${Number(binding.departement.slice(1, 3))}`) {
    throw new Error("OPSYS memory refused: agent/server classification mismatch");
  }
  const args = snapshotArguments(params.toolParams);
  if (binding.mode === "global") {
    return { arguments: args, meta: {} };
  }
  // Procedures have a separate SQL gate; no client record can pass that global-only branch.
  if (
    Array.isArray(args.portees) &&
    args.portees.length === 1 &&
    args.portees[0] === "procedures"
  ) {
    return { arguments: args, meta: {} };
  }
  const context = (deps.readContext ?? readOpsysContexteConfig)();
  if (context.kind !== "enabled") {
    throw new Error("OPSYS memory refused: private session authority is unavailable");
  }
  const contextServer = context.config.contextServers.get(agent);
  if (!contextServer || !context.config.agents.has(agent)) {
    throw new Error("OPSYS memory refused: private session authority is unavailable");
  }
  const envelope = await (deps.callTool ?? callOpsysMcpTool)({
    config: params.config,
    server: contextServer,
    tool: "opsys_contexte_creer_ticket_memoire",
    args: { agent_id: agent, cle_session: params.sessionKey, arguments: args },
    timeoutMs: context.config.timeoutMs,
    signal: params.signal,
  });
  const result = isRecord(envelope) && isRecord(envelope.resultat) ? envelope.resultat : undefined;
  const ticket = result?.ticket;
  const expiry = typeof result?.expire_le === "string" ? Date.parse(result.expire_le) : Number.NaN;
  const now = (deps.nowMs ?? Date.now)();
  if (
    !isRecord(envelope) ||
    envelope.ok !== true ||
    typeof ticket !== "string" ||
    !ticket ||
    ticket.length > 4096 ||
    !Number.isFinite(expiry) ||
    expiry <= now ||
    expiry - now > 125000
  ) {
    throw new Error("OPSYS memory refused: invalid or expired read authority");
  }
  return { arguments: args, meta: { [OPSYS_MEMOIRE_META]: ticket } };
}
