// Gateway tool invocation engine.
import { createHash, createHmac, randomBytes } from "node:crypto";
// Shared implementation behind HTTP and RPC tool invocation adapters.
import {
  normalizeOptionalLowercaseString,
  normalizeOptionalString,
} from "@openclaw/normalization-core/string-coerce";
import { runBeforeToolCallHook } from "../agents/agent-tools.before-tool-call.js";
import { resolveToolLoopDetectionConfig } from "../agents/agent-tools.js";
import { getChannelAgentToolMeta } from "../agents/channel-tools.js";
import { withMcpCallMeta } from "../agents/mcp-call-meta.js";
import {
  resolveOpsysDeviceMcpTarget,
  type OpsysDeviceMcpResolution,
} from "../agents/opsys-device-mcp-target.js";
import { isKnownCoreToolId } from "../agents/tool-catalog.js";
import { isTrustedToolInputError, ToolAuthorizationError } from "../agents/tool-input-error.js";
import {
  AUTOMATIONS_TOOL_NAME,
  isAutomationsToolName,
} from "../agents/tools/automations-tool-name.js";
import { asToolParamsRecord, ToolInputError, type AnyAgentTool } from "../agents/tools/common.js";
import {
  normalizeConversationReadInvocationOrigin,
  type ConversationReadInvocationOrigin,
} from "../channels/plugins/conversation-read-origin.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { formatErrorMessage } from "../infra/errors.js";
import { logWarn } from "../logger.js";
import { isTestDefaultMemorySlotDisabled } from "../plugins/config-state.js";
import { defaultSlotIdForKey } from "../plugins/slots.js";
import { getPluginToolMeta } from "../plugins/tool-metadata.js";
import {
  AGENT_HARNESS_SESSION_KEY_RESERVED_MESSAGE,
  isAgentHarnessSessionKey,
  isAgentHarnessSessionStoreEntryProtected,
} from "../sessions/agent-harness-session-key.js";
import { ADMIN_SCOPE } from "./method-scopes.js";
import { authorizeGatewaySessionCreation } from "./operator-role-policy.js";
import { authorizeOpsysDeviceToolFresh } from "./opsys-device-roles.js";
import type { GatewayClient } from "./server-methods/shared-types.js";
import { withOperatorToolGatewayAuthority } from "./server-plugin-in-process-dispatch.js";
import { createSyntheticPluginRuntimeClient } from "./server-plugin-runtime-client.js";
import { resolveRequestedSessionAgentId } from "./session-request-agent.js";
import { authorizeSessionAgentRun } from "./session-sharing-policy.js";
import {
  authorizeResolvedSessionMutation,
  resolveSessionSharingTarget,
} from "./session-sharing.js";
import { resolveStoredSessionKeyForAgentStore } from "./session-store-key.js";
import { loadGatewaySessionEntryReadOnly } from "./session-utils.js";
import { resolveGatewayScopedTools } from "./tool-resolution.js";

const MEMORY_TOOL_NAMES = new Set(["memory_search", "memory_get"]);

/** Protocol input shape accepted by gateway tool invocation surfaces. */
export type ToolsInvokeInput = {
  tool?: unknown;
  name?: unknown;
  action?: unknown;
  args?: unknown;
  sessionKey?: unknown;
  agentId?: unknown;
  idempotencyKey?: unknown;
  /**
   * OPSYS device identity (OPSYS-AI docs/architecture/IDEMPOTENCE.md §7): the paired device that
   * created this mutation, and its local clock at creation time (ISO 8601 with a UTC offset —
   * never used for a calculation, only for display; the receiving instant is what OPSYS's
   * business engine treats as authoritative). Both travel unverified from the wire, exactly like
   * `idempotencyKey` itself; OPSYS's business engine is the one that gives them meaning, in its
   * own MCP `_meta` contract (`opsys/appareil`, `opsys/horodatageAppareil`) once `idempotencyKey`
   * is present. Same field names as the mobile client (`mobile/src/protocole/types.ts`). Never a
   * source of OPSYS identity by itself (PLAN T1.4-c4): a device-token caller whose body `deviceId`
   * disagrees with its authenticated device is refused outright rather than trusted either way.
   */
  deviceId?: unknown;
  deviceTimestamp?: unknown;
  dryRun?: unknown;
};

type ToolsInvokeErrorType = "invalid_request" | "not_found" | "tool_call_blocked" | "tool_error";

type ToolsInvokeOutcome =
  | {
      ok: true;
      status: 200;
      toolName: string;
      source: "core" | "plugin" | "channel";
      result: unknown;
    }
  | {
      ok: false;
      status: 400 | 403 | 404 | 500;
      toolName: string;
      error: {
        type: ToolsInvokeErrorType;
        message: string;
        requiresApproval?: boolean;
      };
    };

function resolveSessionTarget(params: { cfg: OpenClawConfig; input: ToolsInvokeInput }) {
  const rawSessionKey = normalizeOptionalString(params.input.sessionKey) ?? "main";
  const resolved = resolveRequestedSessionAgentId(
    params.cfg,
    rawSessionKey,
    normalizeOptionalString(params.input.agentId),
  );
  if (!resolved.ok) {
    return resolved;
  }
  return {
    ok: true as const,
    agentId: resolved.agentId,
    sessionKey: resolveStoredSessionKeyForAgentStore({
      cfg: params.cfg,
      agentId: resolved.agentId,
      sessionKey: rawSessionKey,
    }),
  };
}

function resolveMemoryToolDisableReasons(cfg: OpenClawConfig): string[] {
  if (!process.env.VITEST) {
    return [];
  }
  const reasons: string[] = [];
  const plugins = cfg.plugins;
  const slotRaw = plugins?.slots?.memory;
  const slotDisabled = slotRaw === null || normalizeOptionalLowercaseString(slotRaw) === "none";
  const pluginsDisabled = plugins?.enabled === false;
  const defaultDisabled = isTestDefaultMemorySlotDisabled(cfg);

  if (pluginsDisabled) {
    reasons.push("plugins.enabled=false");
  }
  if (slotDisabled) {
    reasons.push(slotRaw === null ? "plugins.slots.memory=null" : 'plugins.slots.memory="none"');
  }
  if (!pluginsDisabled && !slotDisabled && defaultDisabled) {
    reasons.push("memory plugin disabled by test default");
  }
  return reasons;
}

function mergeActionIntoArgsIfSupported(params: {
  toolSchema: unknown;
  action: string | undefined;
  args: Record<string, unknown>;
}): Record<string, unknown> {
  const { toolSchema, action, args } = params;
  if (!action || args.action !== undefined) {
    return args;
  }
  const schemaObj = toolSchema as { properties?: Record<string, unknown> } | null;
  const hasAction = Boolean(
    schemaObj &&
    typeof schemaObj === "object" &&
    schemaObj.properties &&
    "action" in schemaObj.properties,
  );
  return hasAction ? { ...args, action } : args;
}

function resolveToolInputErrorStatus(err: unknown): number | null {
  if (err instanceof ToolInputError) {
    const status = (err as { status?: unknown }).status;
    return typeof status === "number" ? status : 400;
  }
  if (typeof err !== "object" || err === null || !("name" in err)) {
    return null;
  }
  const name = (err as { name?: unknown }).name;
  if (name !== "ToolInputError" && name !== "ToolAuthorizationError") {
    return null;
  }
  const status = (err as { status?: unknown }).status;
  if (typeof status === "number") {
    return status;
  }
  return name === "ToolAuthorizationError" ? 403 : 400;
}

function resolveToolSource(tool: AnyAgentTool): "core" | "plugin" | "channel" {
  if (getPluginToolMeta(tool)) {
    return "plugin";
  }
  if (getChannelAgentToolMeta(tool as never)) {
    return "channel";
  }
  return "core";
}

function readInvokeArgs(argsRaw: unknown): Record<string, unknown> {
  return argsRaw && typeof argsRaw === "object" && !Array.isArray(argsRaw)
    ? (argsRaw as Record<string, unknown>)
    : {};
}

/**
 * OPSYS `_meta` MCP (IDEMPOTENCE.md §7, §7 bis), one place for every key name:
 * `opsys/idempotencyKey`/`opsys/appareil`/`opsys/horodatageAppareil` only when an idempotency key is
 * present (T1.4-c1); `opsys/personne`/`opsys/role` only when `identity` is given, which the caller
 * does solely for a device authenticated by its own token (T1.4-c4). Empty when neither applies: the
 * exact same `tools/call` as before either field existed.
 */
function buildOpsysMcpCallMeta(params: {
  idempotencyKey?: string;
  deviceId?: string;
  deviceTimestamp?: string;
  authenticatedDeviceId?: string;
  toolName?: string;
  generation?: string;
  toolArgs?: Record<string, unknown>;
  identity?: { personne: string; role: string };
}): Record<string, unknown> {
  const meta: Record<string, unknown> = {};
  if (params.idempotencyKey !== undefined) {
    meta["opsys/idempotencyKey"] = params.idempotencyKey;
    if (params.deviceId !== undefined) {
      meta["opsys/appareil"] = params.deviceId;
    }
    if (params.deviceTimestamp !== undefined) {
      meta["opsys/horodatageAppareil"] = params.deviceTimestamp;
    }
  }
  if (params.identity) {
    if (!params.authenticatedDeviceId) {
      throw new Error("OPSYS authenticated device identity is incomplete");
    }
    const secret = process.env.OPSYS_MCP_DEVICE_ATTESTATION_SECRET;
    const args = params.toolArgs;
    const values = [
      params.authenticatedDeviceId,
      params.identity.personne,
      params.identity.role,
      params.toolName,
    ];
    if (
      params.toolName === "m3_lire_apprentissage_chantier" &&
      params.identity.role === "admin" &&
      typeof secret === "string" &&
      /^[A-Za-z0-9_-]{32,256}$/.test(secret) &&
      typeof params.generation === "string" &&
      /^[0-9a-f]{32}$/.test(params.generation) &&
      args &&
      Object.keys(args).toSorted().join(",") === "coupure_utc,wct_id" &&
      typeof args.wct_id === "string" &&
      /^[0-9a-f]{64}$/.test(args.wct_id) &&
      typeof args.coupure_utc === "string" &&
      /^[A-Za-z0-9_.:@/+-]{1,256}$/.test(args.coupure_utc) &&
      values.every(
        (value) => typeof value === "string" && /^[A-Za-z0-9_.:@/+-]{1,256}$/.test(value),
      )
    ) {
      const argsHash = createHash("sha256")
        .update(JSON.stringify([args.wct_id, args.coupure_utc]))
        .digest("hex");
      const content = Buffer.from(
        JSON.stringify([
          1,
          params.generation,
          params.authenticatedDeviceId,
          params.identity.personne,
          params.identity.role,
          params.toolName,
          argsHash,
          Date.now(),
          randomBytes(16).toString("hex"),
        ]),
      ).toString("base64url");
      const signature = createHmac("sha256", secret).update(content).digest("hex");
      meta["opsys/attestationAppareil"] = `${content}.${signature}`;
    }
    meta["opsys/personne"] = params.identity.personne;
    meta["opsys/role"] = params.identity.role;
  }
  return meta;
}

/** QA-only preflight: a configured loopback verifier yields its current boot generation.
 * No secret/configuration means the original read remains unchanged and unqualified. */
async function deviceVerifierGeneration(signal: AbortSignal): Promise<string | undefined> {
  const secret = process.env.OPSYS_MCP_DEVICE_ATTESTATION_SECRET;
  const token = process.env.OPSYS_MCP_JETON;
  const endpoint = process.env.OPSYS_MCP_DEVICE_GENERATION_URL;
  if (
    !secret ||
    !/^[A-Za-z0-9_-]{32,256}$/.test(secret) ||
    !token ||
    token === secret ||
    !endpoint
  ) {
    return undefined;
  }
  try {
    const url = new URL(endpoint);
    if (
      url.protocol !== "http:" ||
      !["127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.pathname !== "/internal/opsys-device-generation" ||
      url.search ||
      url.hash ||
      url.username ||
      url.password
    ) {
      return undefined;
    }
    const proof = createHmac("sha256", secret).update("opsys.device.generation.v1").digest("hex");
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, "x-opsys-gateway-proof": proof },
      redirect: "error",
      signal: AbortSignal.any([signal, AbortSignal.timeout(1000)]),
    });
    if (
      !response.ok ||
      (Number(response.headers.get("content-length")) || 0) > 1024 ||
      !response.body
    ) {
      return undefined;
    }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        total += value.length;
        if (total > 1024) {
          await reader.cancel();
          return undefined;
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
    const payload: unknown = JSON.parse(raw);
    if (typeof payload !== "object" || payload === null || !("generation" in payload)) {
      return undefined;
    }
    const generation = payload.generation;
    return typeof generation === "string" && /^[0-9a-f]{32}$/.test(generation)
      ? generation
      : undefined;
  } catch {
    return undefined;
  }
}

type InvokeGatewayToolParams = {
  cfg: OpenClawConfig;
  input: ToolsInvokeInput;
  messageChannel?: string;
  accountId?: string;
  agentTo?: string;
  agentThreadId?: string;
  authenticatedUserProfile?: GatewayClient["authenticatedUserProfile"];
  /** Host-minted authority from the calling connection; never derived from wire params. */
  operatorRoleActor?: NonNullable<GatewayClient["internal"]>["operatorRoleActor"];
  /**
   * The OPSYS-AI paired device that authenticated this call by ITS OWN device token (OPSYS-AI
   * PLAN T1.4-c4), resolved by the HTTP boundary (`tools-invoke-http.ts`) from the verified
   * bearer — host-minted, exactly like `operatorRoleActor`, and for the same reason: never derived
   * from `input.deviceId`, which is client-supplied wire data a compromised or buggy caller can
   * set to any string. Undefined for every caller that did not authenticate with a device token
   * (a dashboard operator, the CLI, an OpenAI-compatible API client, or the trusted shared
   * secret): OPSYS device-role scoping and `opsys/personne`/`opsys/role` never apply to them.
   */
  authenticatedDeviceId?: string;
  operatorScopes?: readonly string[];
  senderIsOwner?: boolean;
  clientCaps?: string[];
  conversationReadOrigin?: ConversationReadInvocationOrigin;
  toolCallIdPrefix: string;
  approvalMode?: "request" | "report";
  signal?: AbortSignal;
  assertInvocationCurrent?: () => void;
};

/**
 * The OPSYS device door (PLAN T1.4-c6, docs/architecture/MOBILE.md "Nom d'un outil de l'app au
 * moteur"): a paired device, already authenticated by its own token and already authorized for the
 * BARE `toolName` by its role, reaches that tool on the one department MCP server `identity.serveur`.
 *
 * Deliberately NOT the agent path. The agent tool list holds core, plugin and channel tools (never
 * a configured MCP server's tools), a device call needs neither an owning agent nor a session (with
 * several department agents and no default one, `resolveSessionTarget` refuses a body without
 * `agentId`), and nothing a device sends may select a core tool or another department's server. So:
 * - the role check, the server lookup and the MCP call all use the same bare name;
 * - a native core tool can never answer, whatever its name;
 * - per-agent `tools.deny` does not apply (it filters what a MODEL may call); the operator's
 *   `gateway.tools.deny` does, on the bare name and on the `server__tool` form its globs use.
 *
 * Failure statuses follow the app's retry rule (`mobile/src/protocole/classification.ts`): a server
 * that cannot be reached is a 500, retried under the same idempotency key; a missing tool or a
 * denied one is a 4xx, permanent.
 */
async function invokeOpsysDeviceTool(params: {
  invoke: InvokeGatewayToolParams & { signal: AbortSignal };
  toolName: string;
  identity: { personne: string; role: string; serveur: string };
  deviceId: string | undefined;
  conversationReadOrigin: ConversationReadInvocationOrigin;
  assertInvocationCurrent: () => void;
}): Promise<ToolsInvokeOutcome> {
  const { invoke, toolName, identity, assertInvocationCurrent } = params;
  const authenticatedDeviceId = invoke.authenticatedDeviceId;
  const failure = (
    status: 403 | 404 | 500,
    type: ToolsInvokeErrorType,
    message: string,
  ): ToolsInvokeOutcome => ({ ok: false, status, toolName, error: { type, message } });
  const assertDeviceAuthorityCurrent = () => {
    assertInvocationCurrent();
    if (authenticatedDeviceId === undefined) {
      throw new ToolAuthorizationError("OPSYS device identity is unavailable.");
    }
    const authorization = authorizeOpsysDeviceToolFresh(authenticatedDeviceId, toolName);
    if (!authorization.ok) {
      throw new ToolAuthorizationError(
        `OPSYS device is not authorized to call "${toolName}" (${authorization.reason}).`,
      );
    }
    if (
      authorization.personne !== identity.personne ||
      authorization.role !== identity.role ||
      authorization.serveur !== identity.serveur
    ) {
      throw new ToolAuthorizationError("OPSYS device authority changed during the tool call.");
    }
  };

  const gatewayDeny = invoke.cfg.gateway?.tools?.deny;
  if (Array.isArray(gatewayDeny) && gatewayDeny.length > 0) {
    const [{ createToolPolicyMatcher }, { TOOL_NAME_SEPARATOR }] = await Promise.all([
      import("../agents/tool-policy-match.js"),
      import("../agents/agent-bundle-mcp-names.js"),
    ]);
    const allowed = createToolPolicyMatcher({ deny: gatewayDeny });
    if (!allowed(toolName) || !allowed(`${identity.serveur}${TOOL_NAME_SEPARATOR}${toolName}`)) {
      return failure(
        403,
        "tool_call_blocked",
        `Tool "${toolName}" is denied by gateway.tools.deny.`,
      );
    }
  }

  const { resolveDefaultAgentWorkspaceDir } = await import("../agents/workspace-default-path.js");
  const workspaceDir = resolveDefaultAgentWorkspaceDir();
  let resolution: OpsysDeviceMcpResolution;
  try {
    resolution = await resolveOpsysDeviceMcpTarget({
      cfg: invoke.cfg,
      workspaceDir,
      serverName: identity.serveur,
      toolName,
      signal: invoke.signal,
    });
  } catch (err) {
    // A configuration the MCP layer cannot load is an outage to retry, not a crash of the request.
    if (!invoke.signal.aborted) {
      logWarn(`tools-invoke: OPSYS device tool could not be resolved: ${String(err)}`);
    }
    return failure(500, "tool_error", `OPSYS department server is unavailable for "${toolName}".`);
  }
  if (resolution.kind === "not_found") {
    return failure(404, "not_found", `Tool not available: ${toolName}`);
  }
  if (resolution.kind === "unavailable") {
    return failure(500, "tool_error", `OPSYS department server is unavailable for "${toolName}".`);
  }
  const target = resolution.target;

  try {
    const idempotencyKey = normalizeOptionalString(invoke.input.idempotencyKey);
    const deviceTimestamp = normalizeOptionalString(invoke.input.deviceTimestamp);
    const toolCallId = idempotencyKey
      ? `${invoke.toolCallIdPrefix}-${params.conversationReadOrigin}-${idempotencyKey}`
      : `${invoke.toolCallIdPrefix}-${params.conversationReadOrigin}-${Date.now()}`;
    assertInvocationCurrent();
    const hookResult = await runBeforeToolCallHook({
      toolName,
      params: readInvokeArgs(invoke.input.args),
      toolCallId,
      ctx: { config: invoke.cfg, workspaceDir },
      signal: invoke.signal,
      approvalMode: invoke.approvalMode,
    });
    if (hookResult.blocked) {
      return {
        ok: false,
        status: 403,
        toolName,
        error: {
          type: "tool_call_blocked",
          message: hookResult.reason,
          requiresApproval: hookResult.deniedReason === "plugin-approval",
        },
      };
    }
    const toolParams = asToolParamsRecord(hookResult.params);
    const generation =
      toolName === "m3_lire_apprentissage_chantier" && identity.role === "admin"
        ? await deviceVerifierGeneration(invoke.signal)
        : undefined;
    const mcpCallMeta = buildOpsysMcpCallMeta({
      idempotencyKey,
      deviceId: params.deviceId,
      deviceTimestamp,
      authenticatedDeviceId: params.deviceId,
      toolName,
      generation,
      toolArgs: toolParams,
      identity,
    });
    // Fence after hooks and again after the transport's own awaited preparation.
    // An in-flight mutation keeps its admitted person, role, and department target.
    assertDeviceAuthorityCurrent();
    const result = await withMcpCallMeta(
      mcpCallMeta,
      async () => await target.call(toolParams, invoke.signal),
      assertDeviceAuthorityCurrent,
    );
    return { ok: true, status: 200, toolName, source: "plugin", result };
  } catch (err) {
    if (isTrustedToolInputError(err) && err instanceof ToolAuthorizationError) {
      return failure(403, "tool_call_blocked", err.message);
    }
    if (!invoke.signal.aborted) {
      logWarn(`tools-invoke: OPSYS device tool execution failed: ${String(err)}`);
    }
    return failure(500, "tool_error", "tool execution failed");
  } finally {
    await target.dispose();
  }
}

async function invokeGatewayToolWithSignal(
  params: InvokeGatewayToolParams & { signal: AbortSignal },
): Promise<ToolsInvokeOutcome> {
  const assertInvocationCurrent = () => {
    params.signal.throwIfAborted();
    params.assertInvocationCurrent?.();
  };
  const conversationReadOrigin = normalizeConversationReadInvocationOrigin(
    params.conversationReadOrigin,
  );
  const requestedToolName = normalizeOptionalString(params.input.name ?? params.input.tool) ?? "";
  // "cron" is a permanently accepted inbound alias for the scheduler tool
  // (owner decision, RFC 0026; same contract as bash -> exec). Canonicalize
  // before core-id checks and exact-name dispatch below.
  const toolName = isAutomationsToolName(requestedToolName)
    ? AUTOMATIONS_TOOL_NAME
    : requestedToolName;
  if (!toolName) {
    return {
      ok: false,
      status: 400,
      toolName: "",
      error: { type: "invalid_request", message: "tools.invoke requires name" },
    };
  }

  // OPSYS named device roles (IDEMPOTENCE.md §7 bis, hardened by PLAN T1.4-c4): the OPSYS identity
  // check runs ONLY off `params.authenticatedDeviceId` — set by the HTTP boundary exclusively from
  // a verified device token, never off `input.deviceId` (client-supplied wire data). A caller with
  // no authenticated device identity at all (dashboard operator, CLI, an OpenAI-compatible API
  // client, or the trusted shared secret) is completely unaffected: the existing shared-secret-is-
  // full-access model for this endpoint, minus the identity fields, which such a caller can now
  // never attach (`opsys/personne`/`opsys/role` are only ever set from an authenticated device
  // below). A device-token caller is NEVER unaffected: once authenticated as a device, the OPSYS
  // role check is mandatory and closed by default — an unrecognized device, an unrecognized role,
  // or a tool outside the role's declared list are all a refusal, never an implicit full-access
  // grant, and a request body `deviceId` that disagrees with the authenticated device is refused
  // outright rather than silently ignored or silently preferred either way.
  const bodyDeviceId = normalizeOptionalString(params.input.deviceId);
  const authenticatedDeviceId = params.authenticatedDeviceId;
  if (
    authenticatedDeviceId !== undefined &&
    bodyDeviceId !== undefined &&
    bodyDeviceId !== authenticatedDeviceId
  ) {
    return {
      ok: false,
      status: 403,
      toolName,
      error: {
        type: "tool_call_blocked",
        message: "Request body deviceId does not match the authenticated device.",
      },
    };
  }
  // Idempotence bookkeeping (`opsys/appareil`, IDEMPOTENCE.md §7) only ever needs SOME deviceId
  // label, authenticated or not — the authenticated one takes precedence once it exists (it is
  // also the more reliable of the two: unlike a client-generated `input.deviceId`, it cannot be
  // omitted by a buggy caller once a device token was actually presented).
  const deviceId = authenticatedDeviceId ?? bodyDeviceId;
  if (authenticatedDeviceId !== undefined) {
    const authorization = authorizeOpsysDeviceToolFresh(authenticatedDeviceId, toolName);
    if (!authorization.ok) {
      return {
        ok: false,
        status: 403,
        toolName,
        error: {
          type: "tool_call_blocked",
          message: `OPSYS device is not authorized to call "${toolName}" (${authorization.reason}).`,
        },
      };
    }
    // PLAN T1.4-c6: an authorized device call never enters the agent tool list below. `toolName` is
    // the BARE name the app sent; the role scope was just checked on it, and the SAME string is looked
    // up in `roles.json` for the one department server that carries it and called on that server.
    return await invokeOpsysDeviceTool({
      invoke: params,
      toolName,
      identity: {
        personne: authorization.personne,
        role: authorization.role,
        serveur: authorization.serveur,
      },
      deviceId,
      conversationReadOrigin,
      assertInvocationCurrent,
    });
  }

  if (process.env.VITEST && MEMORY_TOOL_NAMES.has(toolName)) {
    const reasons = resolveMemoryToolDisableReasons(params.cfg);
    if (reasons.length > 0) {
      const suffix = ` (${reasons.join(", ")})`;
      return {
        ok: false,
        status: 400,
        toolName,
        error: {
          type: "invalid_request",
          message:
            `memory tools are disabled in tests${suffix}. ` +
            `Enable by setting plugins.slots.memory="${defaultSlotIdForKey("memory")}" (and ensure plugins.enabled is not false).`,
        },
      };
    }
  }

  const knownCoreTool = isKnownCoreToolId(toolName);
  const gatewayRequestedTools = knownCoreTool ? [] : [toolName];

  const action = normalizeOptionalString(params.input.action);
  const args = readInvokeArgs(params.input.args);
  const sessionTarget = resolveSessionTarget({ cfg: params.cfg, input: params.input });
  if (!sessionTarget.ok) {
    return {
      ok: false,
      status: 400,
      toolName,
      error: { type: "invalid_request", message: sessionTarget.error.message },
    };
  }
  const { agentId: selectedAgentId, sessionKey } = sessionTarget;
  const authenticatedUserProfile = params.cfg.gateway?.roles
    ? params.authenticatedUserProfile
    : undefined;
  // HTTP and RPC auth boundaries supply authority independently of profile attribution.
  const client = createSyntheticPluginRuntimeClient({
    ...(authenticatedUserProfile ? { authenticatedUserProfile } : {}),
    operatorRoleActor: params.operatorRoleActor,
    scopes: params.senderIsOwner ? [ADMIN_SCOPE] : [...(params.operatorScopes ?? [])],
  });
  const sessionEntry = loadGatewaySessionEntryReadOnly(sessionKey, {
    agentId: selectedAgentId,
  }).entry;
  const primarySessionAuthorizationError =
    authorizeResolvedSessionMutation({
      cfg: params.cfg,
      client,
      sessionKey,
      agentId: selectedAgentId,
    }) ??
    // Standalone calls cannot create the sandbox provenance a normal session run records.
    (!sessionEntry
      ? authorizeSessionAgentRun({
          cfg: params.cfg,
          client,
          target: { agentId: selectedAgentId, canonicalKey: sessionKey },
        })
      : null);
  if (primarySessionAuthorizationError) {
    return {
      ok: false,
      status: 403,
      toolName,
      error: {
        type: "tool_call_blocked",
        message: primarySessionAuthorizationError.message,
      },
    };
  }
  if (authenticatedUserProfile && (toolName === "sessions_spawn" || toolName === "sessions_send")) {
    const nestedSessionKey = normalizeOptionalString(args.sessionKey);
    const nestedAgentId = normalizeOptionalString(args.agentId);
    const targetAgent = nestedSessionKey
      ? resolveRequestedSessionAgentId(params.cfg, nestedSessionKey, nestedAgentId)
      : undefined;
    if (targetAgent && !targetAgent.ok) {
      return {
        ok: false,
        status: 400,
        toolName,
        error: { type: "invalid_request", message: targetAgent.error.message },
      };
    }
    const targetAgentId = targetAgent?.agentId ?? nestedAgentId ?? selectedAgentId;
    const existingTarget =
      toolName === "sessions_send" && nestedSessionKey
        ? resolveSessionSharingTarget({
            cfg: params.cfg,
            sessionKey: nestedSessionKey,
            agentId: targetAgentId,
          })
        : null;
    const authorizationError =
      (toolName === "sessions_send" && nestedSessionKey
        ? authorizeResolvedSessionMutation({
            cfg: params.cfg,
            client,
            sessionKey: nestedSessionKey,
            agentId: targetAgentId,
          })
        : null) ??
      (!existingTarget
        ? authorizeGatewaySessionCreation({
            cfg: params.cfg,
            client,
            agentId: targetAgentId,
          })
        : null);
    if (authorizationError) {
      return {
        ok: false,
        status: 403,
        toolName,
        error: { type: "tool_call_blocked", message: authorizationError.message },
      };
    }
  }
  if (
    isAgentHarnessSessionKey(sessionKey) &&
    (!sessionEntry || isAgentHarnessSessionStoreEntryProtected(sessionKey, sessionEntry))
  ) {
    return {
      ok: false,
      status: 400,
      toolName,
      error: {
        type: "invalid_request",
        message: AGENT_HARNESS_SESSION_KEY_RESERVED_MESSAGE,
      },
    };
  }
  const resolveTools = (disablePluginTools: boolean) =>
    resolveGatewayScopedTools({
      cfg: params.cfg,
      sessionKey,
      sessionId: sessionEntry?.sessionId,
      agentId: selectedAgentId,
      messageProvider: params.messageChannel,
      accountId: params.accountId,
      agentTo: params.agentTo,
      agentThreadId: params.agentThreadId,
      senderIsOwner: params.senderIsOwner,
      clientCaps: params.clientCaps,
      conversationReadOrigin,
      allowGatewaySubagentBinding: true,
      allowMediaInvokeCommands: true,
      surface: "http",
      assertInvocationCurrent,
      disablePluginTools,
      gatewayRequestedTools,
    });

  let { agentId, tools, workspaceDir } = resolveTools(knownCoreTool);
  if (knownCoreTool && !tools.some((candidate) => candidate.name === toolName)) {
    ({ agentId, tools, workspaceDir } = resolveTools(false));
  }
  const requestedAgentId = normalizeOptionalString(params.input.agentId);
  if (requestedAgentId && agentId && requestedAgentId !== agentId) {
    return {
      ok: false,
      status: 400,
      toolName,
      error: {
        type: "invalid_request",
        message: `agent id "${requestedAgentId}" does not match session agent "${agentId}"`,
      },
    };
  }
  const tool = tools.find((candidate) => candidate.name === toolName);
  if (!tool) {
    return {
      ok: false,
      status: 404,
      toolName,
      error: { type: "not_found", message: `Tool not available: ${toolName}` },
    };
  }

  try {
    const gatewayTool: AnyAgentTool = tool;
    const idempotencyKey = normalizeOptionalString(params.input.idempotencyKey);
    const deviceTimestamp = normalizeOptionalString(params.input.deviceTimestamp);
    const toolCallId = idempotencyKey
      ? `${params.toolCallIdPrefix}-${conversationReadOrigin}-${idempotencyKey}`
      : `${params.toolCallIdPrefix}-${conversationReadOrigin}-${Date.now()}`;
    const toolArgs = mergeActionIntoArgsIfSupported({
      toolSchema: gatewayTool.parameters,
      action,
      args,
    });
    assertInvocationCurrent();
    const hookResult = await runBeforeToolCallHook({
      toolName,
      params: toolArgs,
      toolCallId,
      ctx: {
        agentId,
        config: params.cfg,
        sessionKey,
        workspaceDir,
        loopDetection: resolveToolLoopDetectionConfig({ cfg: params.cfg, agentId }),
      },
      signal: params.signal,
      approvalMode: params.approvalMode,
    });
    if (hookResult.blocked) {
      return {
        ok: false,
        status: 403,
        toolName,
        error: {
          type: "tool_call_blocked",
          message: hookResult.reason,
          requiresApproval: hookResult.deniedReason === "plugin-approval",
        },
      };
    }
    const executeGatewayTool = async () =>
      await gatewayTool.execute?.(toolCallId, hookResult.params, params.signal);
    // No device identity here: an authenticated device never reaches this path (see the device
    // door above), so `opsys/personne`/`opsys/role` are never attached for a shared-secret, CLI or
    // dashboard caller, whatever its body says.
    const mcpCallMeta = buildOpsysMcpCallMeta({ idempotencyKey, deviceId, deviceTimestamp });
    const hasMcpCallMeta = Object.keys(mcpCallMeta).length > 0;
    const result = await withOperatorToolGatewayAuthority(
      {
        authenticatedUserProfile,
        operatorRoleActor: params.operatorRoleActor,
        scopes: client.connect.scopes ?? [],
        assertCurrent: assertInvocationCurrent,
      },
      async () => {
        assertInvocationCurrent();
        return hasMcpCallMeta
          ? await withMcpCallMeta(mcpCallMeta, executeGatewayTool)
          : await executeGatewayTool();
      },
    );
    return {
      ok: true,
      status: 200,
      toolName,
      source: resolveToolSource(gatewayTool),
      result,
    };
  } catch (err) {
    const inputStatus = resolveToolInputErrorStatus(err);
    if (inputStatus !== null) {
      return {
        ok: false,
        status: inputStatus === 403 ? 403 : 400,
        toolName,
        error: {
          type: "tool_error",
          message: formatErrorMessage(err) || "invalid tool arguments",
        },
      };
    }
    if (!params.signal?.aborted) {
      logWarn(`tools-invoke: tool execution failed: ${String(err)}`);
    }
    return {
      ok: false,
      status: 500,
      toolName,
      error: { type: "tool_error", message: "tool execution failed" },
    };
  }
}

/** Resolves, authorizes, and invokes one gateway-visible core/plugin/channel tool. */
export async function invokeGatewayTool(
  params: InvokeGatewayToolParams,
): Promise<ToolsInvokeOutcome> {
  const requestAbort = new AbortController();
  const signal = params.signal
    ? AbortSignal.any([params.signal, requestAbort.signal])
    : requestAbort.signal;
  try {
    return await invokeGatewayToolWithSignal({ ...params, signal });
  } finally {
    requestAbort.abort();
  }
}
