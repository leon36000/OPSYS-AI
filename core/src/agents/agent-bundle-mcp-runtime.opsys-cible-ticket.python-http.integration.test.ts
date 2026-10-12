import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolResultSchema, type CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-target-ticket-fixture.py");
const SESSION = "agent:m02-revenue-crm:webchat:direct:core-c02";
const M3_SESSION = "agent:m03-estimation:webchat:direct:core-c02-n4";
const TOOL = "m2_enregistrer_interaction";
const M3_TOOL = "m3_demander_envoi_devis";
const ARGS = {
  lead_id: "LEAD-CORE-C02",
  auteur: "nathan-fixture",
  resume: "mutation synthétique via Core et MCP Python",
  horodatage: "2026-09-30T12:00:00+00:00",
};
const M3_ARGS = { devis_id: "DEV-CORE-C02-N4", contexte_revue: null };
const M3_REVOKED_ARGS = { devis_id: "DEV-CORE-C02-N4-REVOKED", contexte_revue: null };
const PRIVATE_TOKEN = "synthetic-target-ticket-private-token-2026";
const PUBLIC_TOKEN = "synthetic-target-ticket-public-token-2026";
const children: ChildProcess[] = [];
const tempDirs: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

async function resetSessionMcpRuntimeManagerGeneration(): Promise<void> {
  await getSessionMcpRuntimeManagerForTesting().disposeAll();
  Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
}

beforeEach(async () => {
  await resetSessionMcpRuntimeManagerGeneration();
  releaseContextConfig = await acquireOpsysContextTestConfig();
});

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the Python HTTP ticket integration test");
  }
  return python;
}

function childExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (childExited(child)) {
    return;
  }
  child.kill("SIGTERM");
  const exited = await new Promise<boolean>((resolveExit) => {
    const timeout = setTimeout(() => resolveExit(false), 2_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveExit(true);
    });
  });
  if (exited || childExited(child)) {
    return;
  }
  child.kill("SIGKILL");
  await new Promise<void>((resolveExit, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("Python MCP process survived SIGKILL")),
      2_000,
    );
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveExit();
    });
  });
}

function pythonEnv(home: string): NodeJS.ProcessEnv {
  const departments = [
    "m01-front-office",
    "m02-revenue-crm",
    "m03-estimation",
    "m04-field-ops",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
  ];
  return {
    OPSYS_HOME: home,
    OPSYS_BASE_URL: `sqlite:///${resolve(home, "opsys.db")}`,
    OPSYS_MCP_JETON: PUBLIC_TOKEN,
    OPSYS_CONTEXT_MCP_JETON: PRIVATE_TOKEN,
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    PYTHONPATH: [
      resolve(REPO, "src"),
      ...departments.map((name) => resolve(REPO, `departments/${name}/src`)),
    ].join(":"),
  };
}

async function runFixture(
  python: string,
  home: string,
  command: string,
  extraArgs: string[] = [],
): Promise<string> {
  const child = spawn(python, [FIXTURE, command, ...extraArgs], {
    cwd: REPO,
    env: pythonEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  let stdout = "";
  let stderr = "";
  child.stdout?.setEncoding("utf8").on("data", (chunk: string) => (stdout += chunk));
  child.stderr?.setEncoding("utf8").on("data", (chunk: string) => (stderr += chunk));
  const code = await new Promise<number>((resolveExit, reject) => {
    child.once("error", reject);
    child.once("exit", (value) => resolveExit(value ?? 1));
  });
  if (code !== 0) {
    throw new Error(`Python target ticket fixture failed (${code}): ${stderr.slice(-2_000)}`);
  }
  return stdout.trim();
}

async function reservePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not allocate loopback port");
  }
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  return address.port;
}

async function startPythonMcp(python: string, home: string, port: number): Promise<ChildProcess> {
  const child = spawn(
    python,
    ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
    {
      cwd: REPO,
      env: pythonEnv(home),
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  children.push(child);
  let output = "";
  await new Promise<void>((resolveReady, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`Python MCP startup timed out: ${output.slice(-2_000)}`)),
      15_000,
    );
    const onData = (chunk: string) => {
      output += chunk;
      if (output.includes("Uvicorn running on")) {
        clearTimeout(timeout);
        resolveReady();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", onData);
    child.stderr?.setEncoding("utf8").on("data", onData);
    child.once("error", reject);
    child.once("exit", (code) =>
      reject(new Error(`Python MCP exited during startup (${code}): ${output.slice(-2_000)}`)),
    );
  });
  return child;
}

function opsysConfig(port: number): OpenClawConfig {
  return {
    mcp: {
      servers: {
        opsys_m2: {
          url: `http://127.0.0.1:${port}/mcp/m02-revenue-crm`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
        "opsys_context_m02-revenue-crm": {
          url: `http://127.0.0.1:${port}/mcp/contexte/m02-revenue-crm`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PRIVATE_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
        opsys_m3: {
          url: `http://127.0.0.1:${port}/mcp/m03-estimation`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
        "opsys_context_m03-estimation": {
          url: `http://127.0.0.1:${port}/mcp/contexte/m03-estimation`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PRIVATE_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
      },
    },
  } as OpenClawConfig;
}

async function callRealPythonMcp(
  port: number,
  path: string,
  bearer: string,
  tool: string,
  args: Record<string, unknown>,
  meta?: Record<string, unknown>,
): Promise<CallToolResult> {
  const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}${path}`), {
    requestInit: { headers: { Authorization: `Bearer ${bearer}` } },
  });
  const client = new Client({ name: "opsys-c02-http-proof", version: "1.0.0" });
  await client.connect(transport);
  try {
    return (await client.callTool(
      { name: tool, arguments: args, ...(meta ? { _meta: meta } : {}) },
      CallToolResultSchema,
    )) as CallToolResult;
  } finally {
    await client.close();
  }
}

afterEach(async () => {
  const manager = getSessionMcpRuntimeManagerForTesting();
  await manager.disposeSession("opsys-real-python-cible-ticket");
  await manager.disposeSession("opsys-real-python-m3-n4-device");
  for (const child of children.splice(0)) {
    await stopChild(child);
  }
  await Promise.all(
    tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
  await releaseContextConfig?.();
  releaseContextConfig = undefined;
  await resetSessionMcpRuntimeManagerGeneration();
});

describe("OPSYS target ticket through Core and the real Python HTTP MCP", () => {
  it("mutates a canonical M2 lead once and refuses after the active M10 link is revoked", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-cible-ticket-http-"));
    tempDirs.push(home);
    await runFixture(python, home, "prepare");
    const port = await reservePort();
    await startPythonMcp(python, home, port);
    const runtime = await getOrCreateSessionMcpRuntime({
      sessionId: "opsys-real-python-cible-ticket",
      sessionKey: SESSION,
      workspaceDir: home,
      cfg: { plugins: { enabled: false }, ...opsysConfig(port) },
    });
    opsysContexteGuardStore.set(SESSION, {
      kind: "ready",
      affaireId: "LEAD-CORE-C02",
      nbOuverts: 0,
      atMs: Date.now(),
    });

    const deviceArgs = { ...ARGS, resume: "interaction par appareil humain authentifié" };
    const deviceCall = await withMcpCallMeta(
      {
        "opsys/idempotencyKey": "synthetic-device-idempotency-001",
        "opsys/appareil": "synthetic-device-001",
        "opsys/horodatageAppareil": "2026-09-30T12:00:00Z",
        "opsys/personne": "nathan-fixture",
        "opsys/role": "admin",
      },
      () => runtime.callTool("opsys_m2", TOOL, deviceArgs),
    );
    expect(deviceCall.isError).not.toBe(true);
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 1,
      linked: true,
    });

    const withoutIdempotency = await withMcpCallMeta(
      { "opsys/personne": "nathan-fixture", "opsys/role": "admin" },
      () => runtime.callTool("opsys_m2", TOOL, { ...ARGS, resume: "mutation sans idempotence" }),
    );
    expect(withoutIdempotency.isError).toBe(true);
    const refusedText = withoutIdempotency.content.find((item) => item.type === "text")?.text;
    expect(JSON.parse(refusedText ?? "null")).toMatchObject({
      ok: false,
      erreur: "idempotence_appareil_requise",
    });
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 1,
      linked: true,
    });
    await expect(
      withMcpCallMeta({ "opsys/personne": "nathan-fixture" }, () =>
        runtime.callTool("opsys_m2", TOOL, { ...ARGS, resume: "identité partielle" }),
      ),
    ).rejects.toThrow(/authenticated metadata is incomplete/i);
    const forged = await withMcpCallMeta(
      {
        "opsys/idempotencyKey": "synthetic-device-idempotency-forged",
        "opsys/appareil": "synthetic-device-forged",
        "opsys/horodatageAppareil": "2026-09-30T12:00:00Z",
        "opsys/personne": "personne.inconnue",
        "opsys/role": "admin",
      },
      () => runtime.callTool("opsys_m2", TOOL, { ...ARGS, resume: "appel identité inexistante" }),
    );
    const forgedText = forged.content.find((item) => item.type === "text")?.text;
    expect(JSON.parse(forgedText ?? "null")).toMatchObject({
      ok: false,
      erreur: "ticket_cible_requis",
    });
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 1,
      linked: true,
    });

    const success = await runtime.callTool("opsys_m2", TOOL, ARGS);
    const responseText = success.content.find((item) => item.type === "text")?.text;
    const response = JSON.parse(responseText ?? "null") as Record<string, unknown>;
    expect(response).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    expect(typeof response.demande_id).toBe("string");
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 1,
      linked: true,
    });

    const approval = JSON.parse(
      await runFixture(python, home, "approve", ["--request-id", String(response.demande_id)]),
    ) as Record<string, unknown>;
    expect(approval).toMatchObject({ statut: "executee" });
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 2,
      linked: true,
    });

    // The Python authority's same-ticket replay returns its durable response and cannot create a
    // second pending approval. The raw synthetic ticket stays in memory and is never logged.
    const replayArgs = { ...ARGS, resume: "rejeu synthétique du ticket à usage unique" };
    const issued = await callRealPythonMcp(
      port,
      "/mcp/contexte/m02-revenue-crm",
      PRIVATE_TOKEN,
      "opsys_contexte_creer_ticket_cible",
      {
        agent_id: "m02-revenue-crm",
        cle_session: SESSION,
        affaire_id: "LEAD-CORE-C02",
        origine_affaire: "session",
        outil: TOOL,
        arguments: replayArgs,
      },
    );
    const issueText = issued.content.find((item) => item.type === "text")?.text;
    const ticketEnvelope = JSON.parse(issueText ?? "null") as {
      ok?: boolean;
      resultat?: { ticket?: string };
    };
    expect(ticketEnvelope.ok).toBe(true);
    expect(typeof ticketEnvelope.resultat?.ticket).toBe("string");
    const ticket = ticketEnvelope.resultat?.ticket;
    if (!ticket) {
      throw new Error("real Python target ticket issuer returned no ticket");
    }
    const firstReplayCall = await callRealPythonMcp(
      port,
      "/mcp/m02-revenue-crm",
      PUBLIC_TOKEN,
      TOOL,
      replayArgs,
      { "opsys/cibleTicket": ticket },
    );
    const secondReplayCall = await callRealPythonMcp(
      port,
      "/mcp/m02-revenue-crm",
      PUBLIC_TOKEN,
      TOOL,
      replayArgs,
      { "opsys/cibleTicket": ticket },
    );
    const firstReplayText = firstReplayCall.content.find((item) => item.type === "text")?.text;
    const secondReplayText = secondReplayCall.content.find((item) => item.type === "text")?.text;
    const firstReplayResponse = JSON.parse(firstReplayText ?? "null") as Record<string, unknown>;
    const secondReplayResponse = JSON.parse(secondReplayText ?? "null") as Record<string, unknown>;
    expect(firstReplayResponse).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    expect(secondReplayResponse).toMatchObject({
      ok: true,
      statut: "en_attente_approbation",
      demande_id: firstReplayResponse.demande_id,
      rejoue: true,
    });
    const replayApproval = JSON.parse(
      await runFixture(python, home, "approve", [
        "--request-id",
        String(firstReplayResponse.demande_id),
      ]),
    ) as Record<string, unknown>;
    expect(replayApproval).toMatchObject({ statut: "executee" });
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 3,
      linked: true,
    });

    await runFixture(python, home, "revoke");
    await expect(runtime.callTool("opsys_m2", TOOL, ARGS)).rejects.toThrow(/target ticket/i);
    expect(JSON.parse(await runFixture(python, home, "inspect"))).toStrictEqual({
      interactions: 3,
      linked: false,
    });
  });

  it("lets a paired seller request M3 N4 in autonomous mode, then revalidates role before a new request", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-c02-m3-n4-http-"));
    tempDirs.push(home);
    await runFixture(python, home, "prepare-m3");
    const before = JSON.parse(await runFixture(python, home, "inspect-m3")) as {
      quote_statuses: Record<string, string>;
      requests: unknown[];
      tickets: number;
    };
    expect(before).toStrictEqual({
      quote_statuses: {
        "DEV-CORE-C02-N4": "brouillon",
        "DEV-CORE-C02-N4-REVOKED": "brouillon",
      },
      requests: [],
      tickets: 0,
    });

    const port = await reservePort();
    await startPythonMcp(python, home, port);
    const runtime = await getOrCreateSessionMcpRuntime({
      sessionId: "opsys-real-python-m3-n4-device",
      sessionKey: M3_SESSION,
      workspaceDir: home,
      cfg: { plugins: { enabled: false }, ...opsysConfig(port) },
    });
    opsysContexteGuardStore.set(M3_SESSION, {
      kind: "ready",
      affaireId: "LEAD-CORE-C02",
      nbOuverts: 0,
      atMs: Date.now(),
    });

    const request = await withMcpCallMeta(
      {
        "opsys/idempotencyKey": "synthetic-m3-n4-seller-request-001",
        "opsys/appareil": "synthetic-m3-seller-device",
        "opsys/horodatageAppareil": "2026-09-30T12:00:00Z",
        "opsys/personne": "seller-fixture",
        "opsys/role": "seller",
      },
      () => runtime.callTool("opsys_m3", M3_TOOL, M3_ARGS),
    );
    const requestText = request.content.find((item) => item.type === "text")?.text;
    const requestResponse = JSON.parse(requestText ?? "null") as Record<string, unknown>;
    expect(requestResponse).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    expect(typeof requestResponse.demande_id).toBe("string");
    expect(JSON.parse(await runFixture(python, home, "inspect-m3"))).toStrictEqual({
      quote_statuses: {
        "DEV-CORE-C02-N4": "brouillon",
        "DEV-CORE-C02-N4-REVOKED": "brouillon",
      },
      requests: [{ status: "en_attente", devis_id: "DEV-CORE-C02-N4" }],
      tickets: 0,
    });

    const approval = JSON.parse(
      await runFixture(python, home, "approve", [
        "--request-id",
        String(requestResponse.demande_id),
      ]),
    ) as Record<string, unknown>;
    expect(approval).toMatchObject({ statut: "executee" });
    expect(JSON.parse(await runFixture(python, home, "inspect-m3"))).toStrictEqual({
      quote_statuses: {
        "DEV-CORE-C02-N4": "envoye",
        "DEV-CORE-C02-N4-REVOKED": "brouillon",
      },
      requests: [{ status: "executee", devis_id: "DEV-CORE-C02-N4" }],
      tickets: 0,
    });

    await runFixture(python, home, "revoke-seller-role");
    const refused = await withMcpCallMeta(
      {
        "opsys/idempotencyKey": "synthetic-m3-n4-seller-request-after-revoke",
        "opsys/appareil": "synthetic-m3-seller-device",
        "opsys/horodatageAppareil": "2026-09-30T12:02:00Z",
        "opsys/personne": "seller-fixture",
        "opsys/role": "seller",
      },
      () => runtime.callTool("opsys_m3", M3_TOOL, M3_REVOKED_ARGS),
    );
    expect(refused.isError).toBe(true);
    expect(
      JSON.parse(refused.content.find((item) => item.type === "text")?.text ?? "null"),
    ).toMatchObject({
      ok: false,
      erreur: "ticket_cible_requis",
    });
    expect(JSON.parse(await runFixture(python, home, "inspect-m3"))).toStrictEqual({
      quote_statuses: {
        "DEV-CORE-C02-N4": "envoye",
        "DEV-CORE-C02-N4-REVOKED": "brouillon",
      },
      requests: [{ status: "executee", devis_id: "DEV-CORE-C02-N4" }],
      tickets: 0,
    });
  });
});
