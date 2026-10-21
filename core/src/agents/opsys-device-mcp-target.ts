// OPSYS device door to a department's MCP server (OPSYS-AI PLAN T1.4-c6, docs/architecture/
// MOBILE.md "Nom d'un outil de l'app au moteur").
//
// A paired device names an OPSYS tool by its BARE name (`m4_pointer`): the name the department's MCP
// server itself knows, the name the app sends, and the name `opsys/roles.json` scopes. This module
// reaches that tool the direct way, on the ONE server `roles.json` (`serveurs`) says carries it:
//
// - it never consults the agent tool list. The materialized name a model sees (`opsys_m4__m4_pointer`,
//   built by `buildSafeToolName`, truncated or suffixed when needed) is not a contract an app or a
//   generated file can rely on, and a native core tool can never answer to a device call;
// - it starts a private, single-server runtime (`includeServerNames`): no other department server is
//   connected, let alone called, whatever the request says;
// - it checks the tool is really listed by that server, then calls it with the RAW MCP tool name, so
//   the name that was authorized is the name that goes on the wire;
// - it hands back the OPSYS envelope (`{ok, resultat | erreur, ...}`) the department server wrote, not
//   the model-facing projection of it: that is the answer the app reads (`mobile/src/m4/pointage.ts`).
//
// The ambient `_meta` (`mcp-call-meta.ts`: idempotency key, device, person, role) is set by the
// caller, exactly as for every other `/tools/invoke` tool; `ServerMcpRuntime.callTool` forwards it.
// Heavy modules are imported on first use so that loading `tools-invoke-shared.ts` costs nothing for
// callers that never present a device token.
import { randomUUID } from "node:crypto";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { formatErrorMessage } from "../infra/errors.js";
import { logWarn } from "../logger.js";
import type { McpToolCatalog } from "./agent-bundle-mcp-types.js";

/** A resolved department tool, ready to call; `dispose` closes its private MCP session. */
export type OpsysDeviceMcpTarget = {
  /**
   * Calls the tool with `args` and returns the OPSYS envelope. Rejects when the server cannot be
   * reached or answers something that is not an OPSYS envelope: never a guessed success.
   */
  call: (args: Record<string, unknown>, signal?: AbortSignal) => Promise<Record<string, unknown>>;
  dispose: () => Promise<void>;
};

export type OpsysDeviceMcpResolution =
  /** The server is up and lists the tool. */
  | { kind: "resolved"; target: OpsysDeviceMcpTarget }
  /** The server is configured and up (or not configured at all), and does not list the tool. */
  | { kind: "not_found" }
  /** The server is configured but could not be reached: a retryable condition, not a missing tool. */
  | { kind: "unavailable" };

/**
 * Reads the OPSYS envelope out of a raw MCP `tools/call` result. The department server
 * (`src/opsys/serveur_mcp.py`) answers exactly one text block holding the JSON envelope, with an
 * `ok` boolean. Any other shape is refused: the core does not invent a verdict.
 */
export function readOpsysEnvelope(result: { content?: unknown }): Record<string, unknown> {
  const content = result.content;
  const block: unknown = Array.isArray(content) && content.length === 1 ? content[0] : undefined;
  const text = isRecord(block) && block.type === "text" ? block.text : undefined;
  if (typeof text !== "string") {
    throw new Error("OPSYS department server did not answer a single text block");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("OPSYS department server answered text that is not JSON");
  }
  if (!isRecord(parsed) || typeof parsed.ok !== "boolean") {
    throw new Error("OPSYS department server answered JSON that is not an OPSYS envelope");
  }
  return parsed;
}

/**
 * Connects to the one department server `serverName` and checks it lists `toolName`, both taken
 * from `opsys/roles.json` for a device whose role was just authorized for exactly that tool name.
 */
export async function resolveOpsysDeviceMcpTarget(params: {
  cfg: OpenClawConfig;
  workspaceDir: string;
  serverName: string;
  toolName: string;
  signal?: AbortSignal;
}): Promise<OpsysDeviceMcpResolution> {
  const { serverName, toolName } = params;
  const [{ createSessionMcpRuntime }, { runWithSessionMcpRequestSignal }] = await Promise.all([
    import("./agent-bundle-mcp-runtime.js"),
    import("./agent-bundle-mcp-request-context.js"),
  ]);
  // `includeServerNames` keeps every other department server out of this runtime: none is started,
  // connected, or callable through it. Safe server names are still assigned from the full declared
  // set, inside the runtime, so nothing else about the configuration changes.
  const runtime = createSessionMcpRuntime({
    sessionId: `opsys-device:${randomUUID()}`,
    workspaceDir: params.workspaceDir,
    cfg: params.cfg,
    includeServerNames: new Set([serverName]),
  });
  let disposal: Promise<void> | undefined;
  const dispose = (): Promise<void> => {
    disposal ??= (async () => {
      try {
        await runtime.dispose();
        await runtime.joinCleanup?.();
      } catch (error) {
        logWarn(
          `opsys-device: closing the MCP session of "${serverName}" failed: ${formatErrorMessage(error)}`,
        );
      }
    })();
    return disposal;
  };

  let catalog: McpToolCatalog;
  try {
    catalog = await runWithSessionMcpRequestSignal(params.signal, () => runtime.getCatalog());
  } catch (error) {
    await dispose();
    if (!params.signal?.aborted) {
      logWarn(
        `opsys-device: MCP server "${serverName}" is unavailable: ${formatErrorMessage(error)}`,
      );
    }
    return { kind: "unavailable" };
  }

  const listed = catalog.tools.some(
    (tool) => tool.serverName === serverName && tool.toolName === toolName,
  );
  if (!listed) {
    await dispose();
    // The runtime reports a server it could not start as a diagnostic, with no tools: that is an
    // outage to retry, not a tool that does not exist.
    return (catalog.diagnostics?.length ?? 0) > 0 ? { kind: "unavailable" } : { kind: "not_found" };
  }

  return {
    kind: "resolved",
    target: {
      call: async (args, signal) => {
        const result = await runWithSessionMcpRequestSignal(signal, () =>
          runtime.callTool(serverName, toolName, args),
        );
        return readOpsysEnvelope(result);
      },
      dispose,
    },
  };
}
