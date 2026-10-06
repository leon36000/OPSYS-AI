import fs from "node:fs/promises";
import path from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { runWithSessionMcpRequestSignal } from "./agent-bundle-mcp-request-context.js";
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
  vi.restoreAllMocks();
});

async function writeServer(params: {
  root: string;
  serverName: string;
  toolName: string;
  response: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  structuredContent?: Record<string, unknown>;
}): Promise<{ command: string; args: string[]; env: Record<string, string> }> {
  const scriptPath = path.join(params.root, `${params.serverName}.mjs`);
  const logPath = path.join(params.root, `${params.serverName}.calls.jsonl`);
  const toolSpec = JSON.stringify({
    name: params.toolName,
    inputSchema: { type: "object", additionalProperties: true },
    ...(params.outputSchema ? { outputSchema: params.outputSchema } : {}),
  });
  const toolResult = JSON.stringify({
    content: [{ type: "text", text: JSON.stringify(params.response) }],
    ...(params.structuredContent ? { structuredContent: params.structuredContent } : {}),
  });
  await fs.writeFile(
    scriptPath,
    `import fs from "node:fs";\nimport readline from "node:readline";\n` +
      `async function handle(message) {\n` +
      `  let result;\n` +
      `  if (message.method === "initialize") {\n` +
      `    result = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} },\n` +
      `      serverInfo: { name: "${params.serverName}", version: "1" } };\n` +
      `  }\n` +
      `  if (message.method === "tools/list") result = { tools: [${toolSpec}] };\n` +
      `  if (message.method === "tools/call") {\n` +
      `    fs.appendFileSync(process.env.OPSYS_PROBE_CALLS, JSON.stringify(message.params) + "\\n");\n` +
      `    result = ${toolResult};\n` +
      `  }\n` +
      `  if (result) {\n` +
      `    const reply = JSON.stringify({ jsonrpc: "2.0", id: message.id, result });\n` +
      `    process.stdout.write(reply + "\\n");\n` +
      `  }\n` +
      `}\n` +
      `for await (const line of readline.createInterface({ input: process.stdin })) {\n` +
      `  void handle(JSON.parse(line));\n` +
      `}\n`,
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
  options: {
    businessOutputSchema?: Record<string, unknown>;
    businessStructuredContent?: Record<string, unknown>;
  } = {},
) {
  const root = makeTempDir(tempDirs, "opsys-cible-ticket-wire-");
  const business = await writeServer({
    root,
    serverName: "opsys_m3",
    toolName: TOOL,
    response: { ok: true, resultat: { accepted: true } },
    ...(options.businessOutputSchema ? { outputSchema: options.businessOutputSchema } : {}),
    ...(options.businessStructuredContent
      ? { structuredContent: options.businessStructuredContent }
      : {}),
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
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };

    const result = await runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight);
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
    expect(postflight.observe).toHaveBeenCalledExactlyOnceWith(
      {
        agentId: "m03-estimation",
        sessionKey: SESSION,
        affaireId: "LEAD-001",
        serverName: "opsys_m3",
        toolName: TOOL,
      },
      result,
      { authorityCurrent: true },
    );
    expect(JSON.stringify(postflight.observe.mock.calls)).not.toContain("synthetic-opaque-ticket");
  });

  it("waits for durable reservation and refuses dispatch on reservation failure", async () => {
    const { root, runtime } = await setup();
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(async () => {
        throw new Error("SYNTHETIC_DURABLE_QUOTA_REFUSED");
      }),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };
    await expect(runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight)).rejects.toThrow(
      "SYNTHETIC_DURABLE_QUOTA_REFUSED",
    );
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
    expect(postflight.observe).not.toHaveBeenCalled();
  });

  it("checks authority again after an awaited durable reservation", async () => {
    const { root, runtime } = await setup();
    let current = true;
    const postflight = {
      checkCurrent: vi.fn(() => {
        if (!current) {
          throw new Error("SYNTHETIC_REVOKED_DURING_RESERVE");
        }
      }),
      assertBeforeEffect: vi.fn(async () => {
        current = false;
      }),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };
    await expect(runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight)).rejects.toThrow(
      "SYNTHETIC_REVOKED_DURING_RESERVE",
    );
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
    expect(postflight.observe).not.toHaveBeenCalled();
  });

  it("does not dispatch the business tool when the private ticket authority refuses", async () => {
    const { root, runtime } = await setup({
      ok: false,
      erreur: "refus_metier",
      details: "REJ-LIAISON-CIBLE",
    });
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };

    await expect(runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight)).rejects.toThrow(
      /target ticket/i,
    );

    expect(await readCalls(root, "opsys_context_m03-estimation")).toHaveLength(1);
    expect(await readCalls(root, "opsys_m3")).toHaveLength(0);
    expect(postflight.observe).not.toHaveBeenCalled();
  });

  it("observes a decodable result before a later output-schema validator rejects it", async () => {
    const { root, runtime } = await setup(undefined, {
      businessOutputSchema: {
        type: "object",
        properties: { accepted: { type: "string" } },
        required: ["accepted"],
      },
      businessStructuredContent: { accepted: 42 },
    });
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };

    await expect(runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight)).rejects.toThrow(
      /output schema/i,
    );
    expect(postflight.observe).toHaveBeenCalledOnce();
    expect(postflight.observe.mock.calls[0]?.[1].content[0]).toMatchObject({
      type: "text",
      text: JSON.stringify({ ok: true, resultat: { accepted: true } }),
    });
    expect(await readCalls(root, "opsys_m3")).toHaveLength(1);
  });

  it("observes the resolved MCP result before propagating an abort at the return boundary", async () => {
    const { root, runtime } = await setup();
    const controller = new AbortController();
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => controller.abort(new Error("abort after remote result"))),
    };

    await expect(
      runWithSessionMcpRequestSignal(controller.signal, () =>
        runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight),
      ),
    ).rejects.toThrow(/abort after remote result/);

    expect(await readCalls(root, "opsys_m3")).toHaveLength(1);
    expect(postflight.observe).toHaveBeenCalledOnce();
    expect(postflight.assertBeforeEffect).toHaveBeenCalledOnce();
  });

  it("observes a structured result returned by client.callTool after that client aborts", async () => {
    const { runtime } = await setup();
    const controller = new AbortController();
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };
    const originalCallTool = Client.prototype.callTool;
    let businessEffects = 0;
    const clientCall = vi
      .spyOn(Client.prototype, "callTool")
      .mockImplementation(async function (request, resultSchema, options) {
        if (request.name === TOOL) {
          businessEffects += 1;
          controller.abort(new Error("abort before client resolves"));
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({ ok: true, resultat: { accepted: true } }),
              },
            ],
          };
        }
        return await originalCallTool.call(this, request, resultSchema, options);
      });

    await expect(
      runWithSessionMcpRequestSignal(controller.signal, () =>
        runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight),
      ),
    ).rejects.toThrow(/abort before client resolves/);

    expect(businessEffects).toBe(1);
    expect(clientCall).toHaveBeenCalledTimes(2);
    expect(postflight.observe).toHaveBeenCalledOnce();
  });

  it("does not invent a fact when callTool aborts before returning a result", async () => {
    const { runtime } = await setup();
    const controller = new AbortController();
    const postflight = {
      checkCurrent: vi.fn(),
      assertBeforeEffect: vi.fn(),
      recordUnknownOutcome: vi.fn(),
      observe: vi.fn(async () => undefined),
    };
    const originalCallTool = Client.prototype.callTool;
    let businessEffects = 0;
    vi.spyOn(Client.prototype, "callTool").mockImplementation(
      async function (request, resultSchema, options) {
        if (request.name === TOOL) {
          businessEffects += 1;
          controller.abort(new Error("abort with unknown tool outcome"));
          throw controller.signal.reason;
        }
        return await originalCallTool.call(this, request, resultSchema, options);
      },
    );

    await expect(
      runWithSessionMcpRequestSignal(controller.signal, () =>
        runtime.callTool("opsys_m3", TOOL, FINAL_ARGS, postflight),
      ),
    ).rejects.toThrow(/abort with unknown tool outcome/);

    expect(businessEffects).toBe(1);
    expect(postflight.observe).not.toHaveBeenCalled();
    expect(postflight.recordUnknownOutcome).toHaveBeenCalledOnce();
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
      "opsys/appareil": "",
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
