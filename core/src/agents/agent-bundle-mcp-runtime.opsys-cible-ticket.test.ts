import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const SESSION = "agent:m03-estimation:main";
const TOOL = "m3_marquer_devis_accepte";
const FINAL_ARGS = {
  devis_id: "DEV-FINAL-002",
  approbateur: "personne.synthetic",
  horodatage: "2026-09-30T12:00:00Z",
};
const tempDirs: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

async function resetSessionMcpRuntimeManagerGeneration(): Promise<void> {
  await getSessionMcpRuntimeManagerForTesting().disposeAll();
  delete (globalThis as Record<PropertyKey, unknown>)[SESSION_MCP_RUNTIME_MANAGER_KEY];
}

beforeEach(async () => {
  await resetSessionMcpRuntimeManagerGeneration();
  releaseContextConfig = await acquireOpsysContextTestConfig();
});

afterEach(async () => {
  opsysContexteGuardStore.set(SESSION, {
    kind: "unavailable",
    reason: "test fixture cleanup",
    atMs: Date.now(),
  });
  await getSessionMcpRuntimeManagerForTesting().disposeSession("opsys-cible-ticket-session");
  cleanupTempDirs(tempDirs);
  await releaseContextConfig?.();
  releaseContextConfig = undefined;
  await resetSessionMcpRuntimeManagerGeneration();
});

async function writeServer(params: {
  root: string;
  serverName: string;
  toolName: string;
  response: Record<string, unknown>;
}): Promise<{ command: string; args: string[]; env: Record<string, string> }> {
  const scriptPath = path.join(params.root, `${params.serverName}.mjs`);
  const logPath = path.join(params.root, `${params.serverName}.calls.jsonl`);
  const responseJson = JSON.stringify(params.response);
  const toolName = JSON.stringify(params.toolName);
  await fs.writeFile(
    scriptPath,
    `import fs from "node:fs";\nimport readline from "node:readline";\n` +
      `const toolName = ${toolName};\nconst answer = ${responseJson};\n` +
      `async function handle(message) { let result; ` +
      `if (message.method === "initialize") result = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "${params.serverName}", version: "1" } }; ` +
      `if (message.method === "tools/list") result = { tools: [{ name: toolName, inputSchema: { type: "object", additionalProperties: true } }] }; ` +
      `if (message.method === "tools/call") { fs.appendFileSync(process.env.OPSYS_PROBE_CALLS, JSON.stringify(message.params) + "\\n"); result = { content: [{ type: "text", text: JSON.stringify(answer) }] }; } ` +
      `if (result) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\\n"); }\n` +
      `for await (const line of readline.createInterface({ input: process.stdin })) void handle(JSON.parse(line));\n`,
    { mode: 0o600 },
  );
  return { command: process.execPath, args: [scriptPath], env: { OPSYS_PROBE_CALLS: logPath } };
}

async function setup(
  response: Record<string, unknown> = {
    ok: true,
    resultat: {
      ticket: "synthetic-opaque-ticket",
      expire_le: new Date(Date.now() + 120_000).toISOString(),
    },
  },
) {
  const root = makeTempDir(tempDirs, "opsys-cible-ticket-wire-");
  const business = await writeServer({
    root,
    serverName: "opsys_m3",
    toolName: TOOL,
    response: { ok: true, resultat: { accepted: true } },
  });
  const context = await writeServer({
    root,
    serverName: "opsys_context_m03-estimation",
    toolName: "opsys_contexte_creer_ticket_cible",
    response,
  });
  const runtime = await getOrCreateSessionMcpRuntime({
    sessionId: "opsys-cible-ticket-session",
    sessionKey: SESSION,
    workspaceDir: root,
    cfg: {
      plugins: { enabled: false },
      mcp: { servers: { opsys_m3: business, "opsys_context_m03-estimation": context } },
    },
  });
  opsysContexteGuardStore.set(SESSION, {
    kind: "ready",
    affaireId: "LEAD-001",
    nbOuverts: 0,
    atMs: Date.now(),
  });
  return { root, runtime };
}

async function readCalls(root: string, serverName: string): Promise<Record<string, unknown>[]> {
  const logPath = path.join(root, `${serverName}.calls.jsonl`);
  const text = await fs.readFile(logPath, "utf8").catch(() => "");
  return text
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

describe("OPSYS target tickets on the final MCP call boundary", () => {
  it("issues against the canonical case and attaches the opaque ticket only to business _meta", async () => {
    const { root, runtime } = await setup();

    const result = await runtime.callTool("opsys_m3", TOOL, FINAL_ARGS);
    const ticketCalls = await readCalls(root, "opsys_context_m03-estimation");
    const businessCalls = await readCalls(root, "opsys_m3");
    const ticketArgs = ticketCalls[0]?.arguments as Record<string, unknown>;
    const businessArgs = businessCalls[0]?.arguments as Record<string, unknown>;
    const businessMeta = businessCalls[0]?._meta as Record<string, unknown>;

    expect(ticketCalls).toHaveLength(1);
    expect(ticketArgs).toStrictEqual({
      agent_id: "m03-estimation",
      cle_session: SESSION,
      affaire_id: "LEAD-001",
      origine_affaire: "demande",
      outil: TOOL,
      arguments: FINAL_ARGS,
    });
    expect(businessArgs).toStrictEqual(FINAL_ARGS);
    expect(Object.keys(businessMeta ?? {})).toStrictEqual(["opsys/cibleTicket"]);
    expect(businessMeta?.["opsys/cibleTicket"] === "synthetic-opaque-ticket").toBe(true);
    expect(JSON.stringify(result)).not.toContain("synthetic-opaque-ticket");
  });

  it("does not dispatch the business tool when the private ticket authority refuses", async () => {
    const { root, runtime } = await setup({
      ok: false,
      erreur: "refus_metier",
      details: "REJ-LIAISON-CIBLE",
    });

    await expect(runtime.callTool("opsys_m3", TOOL, FINAL_ARGS)).rejects.toThrow(/target ticket/i);

    expect(await readCalls(root, "opsys_context_m03-estimation")).toHaveLength(1);
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
  });

  it("rejects tool/server mismatch before issuing a private ticket or dispatching", async () => {
    const { root, runtime } = await setup();

    await expect(
      runtime.callTool("opsys_context_m03-estimation", TOOL, FINAL_ARGS),
    ).rejects.toThrow(/server mismatch/i);

    expect(await readCalls(root, "opsys_context_m03-estimation")).toHaveLength(0);
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
  });

  it("preserves a host-authenticated device call for Python's live identity and role checks", async () => {
    const { root, runtime } = await setup();
    const deviceMeta = {
      "opsys/idempotencyKey": "synthetic-device-idempotency-key-001",
      "opsys/appareil": "synthetic-device-001",
      "opsys/horodatageAppareil": "2026-09-30T12:00:00Z",
      "opsys/personne": "personne.synthetic",
      "opsys/role": "admin",
    };

    await withMcpCallMeta(deviceMeta, () => runtime.callTool("opsys_m3", TOOL, FINAL_ARGS));

    const businessCalls = await readCalls(root, "opsys_m3");
    expect(await readCalls(root, "opsys_context_m03-estimation")).toHaveLength(0);
    expect(businessCalls).toHaveLength(1);
    expect(businessCalls[0]?._meta).toStrictEqual(deviceMeta);
  });

  it.each([
    { "opsys/personne": "personne.synthetic" },
    { "opsys/role": "admin" },
    { "opsys/personne": "personne.synthetic", "opsys/role": "" },
    {
      "opsys/personne": "personne.synthetic",
      "opsys/role": "admin",
      "opsys/idempotencyKey": "key",
    },
    { "opsys/personne": "personne.synthetic", "opsys/role": "admin", "opsys/appareil": "device" },
    {
      "opsys/idempotencyKey": "key",
      "opsys/appareil": "device",
      "opsys/horodatageAppareil": "2026-10-04T00:00:00Z",
    },
  ])("refuses incomplete purported device metadata before either MCP call: %j", async (meta) => {
    const { root, runtime } = await setup();

    await expect(
      withMcpCallMeta(meta, () => runtime.callTool("opsys_m3", TOOL, FINAL_ARGS)),
    ).rejects.toThrow(/device call refused: authenticated metadata is incomplete/i);

    expect(await readCalls(root, "opsys_context_m03-estimation")).toHaveLength(0);
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
  });
});
