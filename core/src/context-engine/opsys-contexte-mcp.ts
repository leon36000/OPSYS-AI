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
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { connectMcpClient, disposeMcpClient } from "../agents/mcp-client-lifecycle.js";
import { redactMcpDiagnosticError } from "../agents/mcp-error.js";
import { resolveMcpTransport } from "../agents/mcp-transport.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";

const DISPOSE_TIMEOUT_MS = 1_000;

export class OpsysContexteMcpError extends Error {}

/** Parses the JSON text the OPSYS MCP server returns (`{ok, resultat | erreur, ...}`). */
function readEnvelope(result: unknown): unknown {
  const content = isRecord(result) ? result.content : undefined;
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
}): Promise<unknown> {
  const rawServer = params.config?.mcp?.servers?.[params.server];
  if (rawServer === undefined) {
    throw new OpsysContexteMcpError(`mcp.servers.${params.server} is not configured`);
  }
  const resolved = resolveMcpTransport(params.server, rawServer, { cfg: params.config });
  if (!resolved) {
    throw new OpsysContexteMcpError(`mcp.servers.${params.server} cannot be resolved to a transport`);
  }
  const client = new Client({ name: "opsys-context-engine", version: "0.0.0" });
  try {
    await connectMcpClient({
      client,
      transport: resolved.transport,
      timeoutMs: params.timeoutMs,
      signal: params.signal,
    });
    const result: unknown = await client.callTool(
      { name: params.tool, arguments: params.args },
      undefined,
      { timeout: params.timeoutMs, signal: params.signal },
    );
    return readEnvelope(result);
  } catch (error) {
    // The SDK puts response bodies in some errors: only the redacted form leaves this module.
    throw error instanceof OpsysContexteMcpError
      ? error
      : new OpsysContexteMcpError(redactMcpDiagnosticError(error), { cause: error });
  } finally {
    void disposeMcpClient(
      {
        client,
        transport: resolved.transport,
        transportType: resolved.transportType,
        detachStderr: resolved.detachStderr,
      },
      DISPOSE_TIMEOUT_MS,
    ).catch(() => undefined);
  }
}
