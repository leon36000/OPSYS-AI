/**
 * The call the OPSYS context engine makes to the business engine (OPSYS-AI PLAN T3.3-suite), verified
 * over a real MCP stdio child process, like `agent-bundle-mcp-runtime.mcp-call-meta.test.ts`: the
 * assertion is on what the MCP server actually receives and what `callOpsysMcpTool` returns from the
 * real SDK client, not on a mocked client. The server answers with the OPSYS envelope
 * (`{ok, resultat | erreur}`, `src/opsys/serveur_mcp.py`); production reaches the same tools over
 * streamable HTTP with the token header of `mcp.servers.opsys_m10` (same `resolveMcpTransport`).
 */
import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { callOpsysMcpTool, OpsysContexteMcpError } from "./opsys-contexte-mcp.js";

const tempDirs: string[] = [];

afterEach(() => {
  cleanupTempDirs(tempDirs);
});

/** A minimal stdio MCP server that echoes the `tools/call` it received as an OPSYS envelope. */
async function startEchoServer(): Promise<{ command: string; args: string[] }> {
  const dir = makeTempDir(tempDirs, "opsys-contexte-mcp-");
  const serverPath = path.join(dir, "echo-m10-server.mjs");
  await fs.writeFile(
    serverPath,
    `
import readline from "node:readline";
async function handle(message) {
  let result;
  if (message.method === "initialize") {
    result = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "fake-m10", version: "1" } };
  }
  if (message.method === "tools/list") {
    result = { tools: [] };
  }
  if (message.method === "tools/call") {
    const { name, arguments: args } = message.params;
    const envelope = name === "m10_refuse" ? { ok: false, erreur: "refus_metier" } : { ok: true, resultat: { echo: name, args } };
    result = { content: [{ type: "text", text: JSON.stringify(envelope) }], isError: !envelope.ok };
  }
  if (result) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\\n");
}
for await (const line of readline.createInterface({ input: process.stdin })) void handle(JSON.parse(line));
`,
  );
  return { command: process.execPath, args: [serverPath] };
}

function configWith(server: { command: string; args: string[] }): OpenClawConfig {
  return { plugins: { enabled: false }, mcp: { servers: { opsys_m10: server } } };
}

describe("callOpsysMcpTool", () => {
  it("calls the tool on the configured server and returns the parsed OPSYS answer", async () => {
    const server = await startEchoServer();

    const answer = await callOpsysMcpTool({
      config: configWith(server),
      server: "opsys_m10",
      tool: "m10_paquet_contexte_affaire",
      args: { affaire_id: "LEAD-001", horodatage: "2026-09-28T10:15:00.000+00:00" },
      timeoutMs: 10_000,
      signal: new AbortController().signal,
    });

    expect(answer).toStrictEqual({
      ok: true,
      resultat: {
        echo: "m10_paquet_contexte_affaire",
        args: { affaire_id: "LEAD-001", horodatage: "2026-09-28T10:15:00.000+00:00" },
      },
    });
  });

  it("returns a refusal of the tool as an answer, for the engine to judge, instead of throwing", async () => {
    const server = await startEchoServer();

    const answer = await callOpsysMcpTool({
      config: configWith(server),
      server: "opsys_m10",
      tool: "m10_refuse",
      args: {},
      timeoutMs: 10_000,
      signal: new AbortController().signal,
    });

    expect(answer).toStrictEqual({ ok: false, erreur: "refus_metier" });
  });

  it("rejects, naming the entry, when the server is not configured", async () => {
    await expect(
      callOpsysMcpTool({
        config: configWith({ command: process.execPath, args: [] }),
        server: "opsys_absent",
        tool: "m10_paquet_contexte_affaire",
        args: {},
        timeoutMs: 10_000,
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("mcp.servers.opsys_absent is not configured");
  });

  it("rejects with the module's own error when there is no configuration at all", async () => {
    await expect(
      callOpsysMcpTool({
        config: undefined,
        server: "opsys_m10",
        tool: "m10_paquet_contexte_affaire",
        args: {},
        timeoutMs: 10_000,
        signal: new AbortController().signal,
      }),
    ).rejects.toBeInstanceOf(OpsysContexteMcpError);
  });

  it("rejects when the entry cannot be turned into a transport", async () => {
    await expect(
      callOpsysMcpTool({
        config: { plugins: { enabled: false }, mcp: { servers: { opsys_m10: {} } } },
        server: "opsys_m10",
        tool: "m10_paquet_contexte_affaire",
        args: {},
        timeoutMs: 10_000,
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("cannot be resolved to a transport");
  });
});
