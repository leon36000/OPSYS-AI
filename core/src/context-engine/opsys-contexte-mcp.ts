// One call to a tool of the OPSYS business engine through its MCP server (OPSYS-AI PLAN T3.3-suite).
//
// The context engine never reads the enterprise database: it asks M10 through the road that already
// exists, the `mcp.servers.opsys_m10` entry `src/opsys/openclaw.py` writes (streamable HTTP,
// `Authorization: Bearer ${OPSYS_MCP_JETON}`, one server per department). It reuses the agents'
// transport factory and client lifecycle (`mcp-transport.ts`, `mcp-client-lifecycle.ts`) instead of
// adding a client, so URL, token header, TLS and timeouts follow the same configuration.
//
// The connection is opened for the call and closed after it: nothing is kept between two turns
// (ADR-0010, the "RAM" is composed at every turn and never stored). Closing is bounded and not
// awaited, so the turn never waits for it.
import { isPromise } from "node:util/types";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { connectMcpClient, disposeMcpClient } from "../agents/mcp-client-lifecycle.js";
import { redactMcpDiagnosticError } from "../agents/mcp-error.js";
import { resolveMcpTransport } from "../agents/mcp-transport.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";

const DISPOSE_TIMEOUT_MS = 1_000;
const MAX_RESPONSE_BYTES = 16 * 1024 * 1024;

export class OpsysContexteMcpError extends Error {}

/** Parses the JSON text the OPSYS MCP server returns (`{ok, resultat | erreur, ...}`). */
function readEnvelope(result: unknown, maxResponseBytes?: number): unknown {
  const content = isRecord(result) ? result.content : undefined;
  if (maxResponseBytes !== undefined) {
    if (
      !Array.isArray(content) ||
      content.length !== 1 ||
      !isRecord(content[0]) ||
      content[0].type !== "text" ||
      typeof content[0].text !== "string" ||
      Buffer.byteLength(content[0].text, "utf8") > maxResponseBytes
    ) {
      throw new OpsysContexteMcpError("MCP response boundary rejected");
    }
  }
  const parts: string[] = [];
  if (Array.isArray(content)) {
    for (const block of content) {
      if (isRecord(block) && block.type === "text" && typeof block.text === "string") {
        parts.push(block.text);
      }
    }
  }
  if (parts.length === 0) {
    throw new OpsysContexteMcpError("the MCP answer carries no text");
  }
  try {
    return JSON.parse(parts.join(""));
  } catch {
    throw new OpsysContexteMcpError("the MCP answer is not JSON");
  }
}

/**
 * Calls `tool` on `mcp.servers.<server>` and returns the parsed answer of the OPSYS server. Rejects
 * when the server is not configured, cannot be reached, does not answer in `timeoutMs`, or answers
 * with something that is not the OPSYS envelope; `signal` cancels the call.
 */
export async function callOpsysMcpTool(params: {
  config: OpenClawConfig | undefined;
  server: string;
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
  /** Revalidate live authority synchronously after connection, immediately before sending. */
  beforeRequest?: () => void;
  /** Bounds decoded text before JSON parsing, not the SDK's underlying network allocation. */
  maxResponseBytes?: number;
  /** Require confirmed cleanup even when a response has already arrived. */
  awaitCleanup?: boolean;
}): Promise<unknown> {
  const { beforeRequest, maxResponseBytes, awaitCleanup } = params;
  if (
    maxResponseBytes !== undefined &&
    (!Number.isSafeInteger(maxResponseBytes) ||
      maxResponseBytes <= 0 ||
      maxResponseBytes > MAX_RESPONSE_BYTES)
  ) {
    throw new OpsysContexteMcpError("MCP response limit is invalid");
  }
  const rawServer = params.config?.mcp?.servers?.[params.server];
  if (rawServer === undefined) {
    throw new OpsysContexteMcpError(`mcp.servers.${params.server} is not configured`);
  }
  const resolved = resolveMcpTransport(params.server, rawServer, { cfg: params.config });
  if (!resolved) {
    throw new OpsysContexteMcpError(
      `mcp.servers.${params.server} cannot be resolved to a transport`,
    );
  }
  const client = new Client({ name: "opsys-context-engine", version: "0.0.0" });
  try {
    await connectMcpClient({
      client,
      transport: resolved.transport,
      timeoutMs: params.timeoutMs,
      signal: params.signal,
    });
    if (beforeRequest !== undefined || maxResponseBytes !== undefined || awaitCleanup === true) {
      try {
        params.signal.throwIfAborted();
        const guardResult: unknown = beforeRequest?.();
        if (guardResult !== undefined) {
          // Refuse async guards without leaving a native Promise rejection unobserved.
          if (isPromise(guardResult)) {
            void Promise.prototype.then.call(guardResult, undefined, () => undefined);
          }
          throw new Error("invalid synchronous guard");
        }
        params.signal.throwIfAborted();
      } catch {
        throw new OpsysContexteMcpError("MCP request boundary rejected");
      }
    }
    const result: unknown = await client.callTool(
      { name: params.tool, arguments: params.args },
      undefined,
      { timeout: params.timeoutMs, signal: params.signal },
    );
    return readEnvelope(result, maxResponseBytes);
  } catch (error) {
    // The SDK puts response bodies in some errors: only the redacted form leaves this module.
    throw error instanceof OpsysContexteMcpError
      ? error
      : new OpsysContexteMcpError(redactMcpDiagnosticError(error), { cause: error });
  } finally {
    const cleanup = disposeMcpClient(
      {
        client,
        transport: resolved.transport,
        transportType: resolved.transportType,
        detachStderr: resolved.detachStderr,
      },
      DISPOSE_TIMEOUT_MS,
    );
    if (awaitCleanup === true) {
      if ((await cleanup.catch(() => "uncertain")) !== "closed") {
        // oxlint-disable-next-line no-unsafe-finally -- Explicit awaited cleanup must fail closed even after an ACK or another failure.
        throw new OpsysContexteMcpError("MCP cleanup is uncertain");
      }
    } else {
      void cleanup.catch(() => undefined);
    }
  }
}
