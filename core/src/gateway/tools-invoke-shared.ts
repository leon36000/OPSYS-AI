// Gateway tool invocation engine.
// Shared implementation behind HTTP and RPC tool invocation adapters.
import {
  normalizeOptionalLowercaseString,
  normalizeOptionalString,
} from "@openclaw/normalization-core/string-coerce";
import { runBeforeToolCallHook } from "../agents/agent-tools.before-tool-call.js";
import { resolveToolLoopDetectionConfig } from "../agents/agent-tools.js";
import { getChannelAgentToolMeta } from "../agents/channel-tools.js";
import { withMcpCallMeta } from "../agents/mcp-call-meta.js";
import { isKnownCoreToolId } from "../agents/tool-catalog.js";
import {
  AUTOMATIONS_TOOL_NAME,
  isAutomationsToolName,
} from "../agents/tools/automations-tool-name.js";
import { ToolInputError, type AnyAgentTool } from "../agents/tools/common.js";
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
import { authorizeOpsysDeviceTool } from "./opsys-device-roles.js";
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
  let opsysDeviceIdentity: { personne: string; role: string } | undefined;
  if (authenticatedDeviceId !== undefined) {
    const authorization = authorizeOpsysDeviceTool(authenticatedDeviceId, toolName);
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
    opsysDeviceIdentity = { personne: authorization.personne, role: authorization.role };
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
  const argsRaw = params.input.args;
  const args =
    argsRaw && typeof argsRaw === "object" && !Array.isArray(argsRaw)
      ? (argsRaw as Record<string, unknown>)
      : {};
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
    // OPSYS `_meta` MCP (IDEMPOTENCE.md §7, §7 bis): `opsys/idempotencyKey`/`opsys/appareil`/
    // `opsys/horodatageAppareil` only when idempotencyKey is present (unchanged from T1.4-c1);
    // `opsys/personne`/`opsys/role` whenever a device identity was resolved above, independently
    // of idempotencyKey — a read-only lookup from a paired device carries no idempotencyKey but
    // still needs its caller's identity for a role-based projection. A caller with neither gets no
    // ambient `_meta` at all: the exact same `tools/call` as before either field existed.
    const mcpCallMeta: Record<string, unknown> = {};
    if (idempotencyKey !== undefined) {
      mcpCallMeta["opsys/idempotencyKey"] = idempotencyKey;
      if (deviceId !== undefined) {
        mcpCallMeta["opsys/appareil"] = deviceId;
      }
      if (deviceTimestamp !== undefined) {
        mcpCallMeta["opsys/horodatageAppareil"] = deviceTimestamp;
      }
    }
    if (opsysDeviceIdentity) {
      mcpCallMeta["opsys/personne"] = opsysDeviceIdentity.personne;
      mcpCallMeta["opsys/role"] = opsysDeviceIdentity.role;
    }
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
