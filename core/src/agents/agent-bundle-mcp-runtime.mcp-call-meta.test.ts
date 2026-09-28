/**
 * OPSYS `_meta` propagation into the outbound MCP `tools/call` (docs/architecture/IDEMPOTENCE.md
 * §7 in OPSYS-AI): `ServerMcpRuntime.callTool` (`agent-bundle-mcp-runtime.ts`) must add the ambient
 * `withMcpCallMeta` payload as `_meta` on the real wire request when one is in scope, and send the
 * exact same request as before (no `_meta` key at all) otherwise. Verified over a real stdio
 * JSON-RPC child process (the same transport OPSYS MCP servers use), not a mocked SDK client, so
 * the assertion is on what the MCP server actually receives on the wire.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { testing } from "./agent-bundle-mcp-runtime.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const tempDirs: string[] = [];

afterEach(async () => {
  cleanupTempDirs(tempDirs);
  await testing.resetSessionMcpRuntimeManager();
});

/** A minimal stdio MCP server that echoes back the `_meta` it received on `tools/call`. */
async function startEchoMetaServer(): Promise<{ command: string; args: string[] }> {
  const workspaceDir = makeTempDir(tempDirs, "mcp-call-meta-");
  const serverPath = path.join(workspaceDir, "echo-meta-server.mjs");
  await fs.writeFile(
    serverPath,
    `
import readline from "node:readline";
async function handle(message) {
  let result;
  if (message.method === "initialize") {
    result = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "echo-meta", version: "1" } };
  }
  if (message.method === "tools/list") {
    result = { tools: [{ name: "echo_meta", inputSchema: { type: "object" } }] };
  }
  if (message.method === "tools/call") {
    const meta = message.params._meta ?? null;
    result = { content: [{ type: "text", text: JSON.stringify({ meta }) }] };
  }
  if (result) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\\n");
}
for await (const line of readline.createInterface({ input: process.stdin })) void handle(JSON.parse(line));
`,
  );
  return { command: process.execPath, args: [serverPath] };
}

async function callEchoMeta() {
  const server = await startEchoMetaServer();
  const runtime = await getOrCreateSessionMcpRuntime({
    sessionId: "session-mcp-call-meta",
    sessionKey: "agent:test:session-mcp-call-meta",
    workspaceDir: makeTempDir(tempDirs, "mcp-call-meta-workspace-"),
    manifestRegistry: { plugins: [] },
    cfg: { plugins: { enabled: false }, mcp: { servers: { echo: server } } },
  });
  const result = await runtime.callTool("echo", "echo_meta", {});
  const text = result.content.find((item) => item.type === "text")?.text;
  return JSON.parse(String(text)) as { meta: Record<string, unknown> | null };
}

describe("agent-bundle-mcp-runtime callTool OPSYS _meta", () => {
  it("sends no _meta at all when no OPSYS call is in scope (unchanged behavior)", async () => {
    const received = await callEchoMeta();
    expect(received.meta).toBeNull();
  });

  it("forwards the ambient withMcpCallMeta payload as _meta on the real tools/call request", async () => {
    const meta = {
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
    };
    const received = await withMcpCallMeta(meta, callEchoMeta);
    expect(received.meta).toEqual(meta);
  });
});
