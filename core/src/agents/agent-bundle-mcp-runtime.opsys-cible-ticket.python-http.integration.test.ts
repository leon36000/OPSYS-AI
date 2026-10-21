import { spawn, type ChildProcess } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolResultSchema, type CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import { upsertSessionEntryCore } from "../config/sessions/session-accessor.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { depositKey } from "../context-engine/opsys-contexte-depot.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import { createUserTurnTranscriptRecorder } from "../sessions/user-turn-transcript.js";
import {
  closeOpenClawAgentDatabaseByPathAsync,
  openOpenClawAgentDatabase,
} from "../state/openclaw-agent-db.js";
import { cleanupSessionStateForTest } from "../test-utils/session-state-cleanup.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import {
  type OpsysPostflightCallObserver,
  OpsysPostflightCollector,
} from "./harness/opsys-postflight-collector.js";
import {
  listOpsysPostflightIntents,
  listOpsysPostflightLots,
} from "./harness/opsys-postflight-outbox.js";
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

async function startPythonMcp(
  python: string,
  home: string,
  port: number,
  intentDatabase?: string,
  loseM9Response = false,
): Promise<ChildProcess> {
  const child = spawn(
    python,
    intentDatabase
      ? [
          FIXTURE,
          "serve-m9-observed",
          "--port",
          String(port),
          "--intent-db",
          intentDatabase,
          ...(loseM9Response ? ["--lose-m9-response"] : []),
        ]
      : ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
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

function m9OpsysConfig(port: number): OpenClawConfig {
  return {
    mcp: {
      servers: {
        opsys_m9: {
          url: `http://127.0.0.1:${port}/mcp/m09-strategic-intelligence`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
        "opsys_context_m09-strategic-intelligence": {
          url: `http://127.0.0.1:${port}/mcp/contexte/m09-strategic-intelligence`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PRIVATE_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
      },
    },
  };
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
  await manager.disposeSession("opsys-real-python-m9-followup");
  await manager.disposeSession("opsys-real-python-m9-pending-intent");
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
  it("retains M9 uncertainty after SQLite reopen and distinguishes fresh proposals from an owner-approved followup", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m9-pending-intent-http-"));
    tempDirs.push(home);
    const prepared = JSON.parse(
      await runFixture(python, home, "prepare-m9", ["--postflight-depot"]),
    ) as {
      fictif: boolean;
      session_key: string;
      affairs: Record<"A" | "B", string>;
      arguments: Record<"A" | "B", Record<string, unknown>>;
      generated_context: { agent: { depot: string[] } };
    };
    const agentId = "m09-strategic-intelligence";
    const tool = "m9_ouvrir_suivi_decision";
    const sessionId = "opsys-real-python-m9-pending-intent";
    const toolCallId = "m9-fictif-pending-call";
    expect(prepared.fictif).toBe(true);
    // Actual native generation with an explicitly selected deposit tool; shared config is untouched.
    expect(prepared.generated_context.agent.depot).toEqual([tool]);
    const coreState = resolve(home, "core-state");
    const target = {
      agentId,
      cwd: coreState,
      sessionId,
      sessionKey: prepared.session_key,
      storePath: resolve(coreState, "agents", agentId, "sessions", "sessions.json"),
    };
    await mkdir(dirname(target.storePath), { recursive: true });
    const authority = new AbortController();
    try {
      const sessionEntry = await upsertSessionEntryCore(target, { sessionId, updatedAt: 1 });
      if (!sessionEntry) {
        throw new Error("fictive M9 transcript entry was not persisted");
      }
      const recorder = createUserTurnTranscriptRecorder({
        message: {
          role: "user",
          content: "fictif: true; revoir la durée du chantier",
          timestamp: 2,
        },
        target: () => ({ ...target, sessionEntry }),
        updateMode: "none",
      });
      expect(await recorder.persistApproved()).toBeDefined();
      const receipt = recorder.getAdmissionReceipt();
      if (!receipt || receipt.agentId !== agentId || receipt.sessionId !== sessionId) {
        throw new Error("canonical M9 transcript admission absent");
      }
      const options = { agentId: receipt.agentId, path: receipt.storePath };
      const database = openOpenClawAgentDatabase(options);
      const createCollector = async (runId: string) => {
        const collector = new OpsysPostflightCollector({
          runId,
          sessionId,
          sessionKey: prepared.session_key,
          agentId,
          recorder,
          depositTools: prepared.generated_context.agent.depot,
          assertCurrent: () => authority.signal.throwIfAborted(),
        });
        // This provider/model admission is synthetic; the user transcript above is really persisted.
        collector.recordRuntimeAdmission({
          runId,
          agentId,
          profileId: "m9-fictif-pending-profile",
          profileRevision: 1,
          departement: agentId,
          attemptId: `${runId}-attempt`,
          cycleId: `${runId}-cycle`,
        });
        await collector.prepareBeforeProviderDispatch();
        return collector;
      };
      const collector = await createCollector("m9-fictif-pending-run");
      expect(await listOpsysPostflightIntents({ database, options, now: Date.now() })).toEqual([]);
      expect(await listOpsysPostflightLots({ database, options, now: Date.now() })).toEqual([]);
      const port = await reservePort();
      await startPythonMcp(python, home, port, database.path);
      const runtime = await getOrCreateSessionMcpRuntime({
        sessionId,
        sessionKey: prepared.session_key,
        workspaceDir: home,
        cfg: { plugins: { enabled: false }, ...m9OpsysConfig(port) },
      });
      opsysContexteGuardStore.set(prepared.session_key, {
        kind: "ready",
        affaireId: prepared.affairs.A,
        nbOuverts: 0,
        atMs: Date.now(),
      });
      const observer = collector.beginToolCall({
        toolCallId,
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!observer) {
        throw new Error("M9 postflight observer must be attached to the actual Core call");
      }
      const result = await runtime.callTool("opsys_m9", tool, prepared.arguments.A, observer);
      expect(result.isError).not.toBe(true);
      expect(
        JSON.parse(result.content.find((item) => item.type === "text")?.text ?? "null"),
      ).toMatchObject({
        ok: true,
        statut: "en_attente_approbation",
        demande_id: expect.any(String),
      });
      const readDispatches = async () =>
        (await readFile(resolve(home, "m9-business-dispatches.jsonl"), "utf8"))
          .trim()
          .split("\n")
          .filter(Boolean)
          .map((row) => JSON.parse(row));
      const expectedDispatch = [
        {
          fictif: true,
          intents: [{ fact_key: depositKey(sessionId, toolCallId), state: "uncertain" }],
          outbox_count: 0,
        },
      ];
      // The native business endpoint observed the committed reservation before its own effect.
      expect(await readDispatches()).toEqual(expectedDispatch);
      const pending = await listOpsysPostflightIntents({ database, options, now: Date.now() });
      expect(pending).toHaveLength(1);
      expect(pending[0]).toMatchObject({
        factKey: depositKey(sessionId, toolCallId),
        affaireId: prepared.affairs.A,
        departementSource: agentId,
        outil: tool,
        state: "uncertain",
      });
      expect(await listOpsysPostflightLots({ database, options, now: Date.now() })).toEqual([]);
      expect(await collector.flushPending()).toMatchObject({ remaining: 0, failures: 1 });
      const inspect = async () => JSON.parse(await runFixture(python, home, "inspect-m9"));
      const nativePending = await inspect();
      expect(nativePending).toMatchObject({ owner_active: true, followups: [] });
      expect(nativePending.requests).toHaveLength(1);
      const next = collector.beginToolCall({
        toolCallId: "m9-fictif-next-call",
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!next) {
        throw new Error("expected the same live collector's next-call observer");
      }
      await expect(runtime.callTool("opsys_m9", tool, prepared.arguments.A, next)).rejects.toThrow(
        "durable capture is unresolved",
      );
      expect(await readDispatches()).toEqual(expectedDispatch);
      expect(await listOpsysPostflightIntents({ database, options, now: Date.now() })).toEqual(
        pending,
      );

      // Drain the actual scoped worker/owner and prove its native handle really closed.
      await closeOpenClawAgentDatabaseByPathAsync(database.path, agentId);
      expect(database.db.isOpen).toBe(false);
      const disk = new DatabaseSync(database.path, { readOnly: true });
      try {
        expect(disk.prepare("SELECT fact_key, state FROM opsys_postflight_intents").all()).toEqual([
          { fact_key: depositKey(sessionId, toolCallId), state: "uncertain" },
        ]);
        expect(
          disk.prepare("SELECT COUNT(*) AS count FROM opsys_postflight_outbox").get()?.count,
        ).toBe(0);
      } finally {
        disk.close();
      }
      const replayCollector = await createCollector("m9-fictif-reopened-run");
      const reopened = openOpenClawAgentDatabase(options);
      expect(reopened).not.toBe(database);
      expect(
        await listOpsysPostflightIntents({ database: reopened, options, now: Date.now() }),
      ).toEqual(pending);
      const replay = replayCollector.beginToolCall({
        toolCallId,
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!replay) {
        throw new Error("expected the reopened collector's exact-key observer");
      }
      await expect(
        runtime.callTool("opsys_m9", tool, prepared.arguments.A, replay),
      ).rejects.toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
      expect(await readDispatches()).toEqual(expectedDispatch);
      expect(
        await listOpsysPostflightIntents({ database: reopened, options, now: Date.now() }),
      ).toEqual(pending);
      expect(
        await listOpsysPostflightLots({ database: reopened, options, now: Date.now() }),
      ).toEqual([]);
      // Private tickets may be issued before reservation refusal; business requests must stay unchanged.
      const finalNative = await inspect();
      expect(finalNative).toMatchObject({ owner_active: true, followups: [] });
      expect(finalNative.requests).toEqual(nativePending.requests);

      // Characterize the documented boundary, not a cross-key replay guarantee:
      // a new call ID has no durable business-operation identity in the current intent.
      // Use a separate collector so the failed exact-key attempt cannot mask this path.
      const freshCollector = await createCollector("m9-fictif-reopened-fresh-key-run");
      const freshCallId = "m9-fictif-reopened-fresh-key-call";
      const fresh = freshCollector.beginToolCall({
        toolCallId: freshCallId,
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!fresh) {
        throw new Error("expected an independent reopened collector's fresh-key observer");
      }
      const freshResult = await runtime.callTool("opsys_m9", tool, prepared.arguments.A, fresh);
      expect(freshResult.isError).not.toBe(true);
      const freshRequest = JSON.parse(
        freshResult.content.find((item) => item.type === "text")?.text ?? "null",
      );
      expect(freshRequest).toMatchObject({
        ok: true,
        statut: "en_attente_approbation",
        demande_id: expect.any(String),
      });
      const originalRequestId = nativePending.requests[0].id;
      expect(freshRequest.demande_id).not.toBe(originalRequestId);
      const freshPending = await listOpsysPostflightIntents({
        database: reopened,
        options,
        now: Date.now(),
      });
      expect(freshPending).toHaveLength(2);
      expect(
        freshPending.find((intent) => intent.factKey === depositKey(sessionId, toolCallId)),
      ).toStrictEqual(pending[0]);
      expect(
        freshPending.find((intent) => intent.factKey === depositKey(sessionId, freshCallId)),
      ).toMatchObject({
        affaireId: prepared.affairs.A,
        departementSource: agentId,
        outil: tool,
        state: "uncertain",
      });
      const twoDispatches = [
        ...expectedDispatch,
        {
          fictif: true,
          intents: [depositKey(sessionId, toolCallId), depositKey(sessionId, freshCallId)]
            .sort()
            .map((fact_key) => ({ fact_key, state: "uncertain" })),
          outbox_count: 0,
        },
      ];
      expect(await readDispatches()).toStrictEqual(twoDispatches);
      const twoProposals = await inspect();
      expect(twoProposals).toMatchObject({
        owner_active: true,
        followups: [],
        decision_audits: [],
      });
      expect(twoProposals.requests).toHaveLength(2);
      expect(twoProposals.requests).toEqual(
        expect.arrayContaining([
          { id: originalRequestId, status: "en_attente" },
          { id: freshRequest.demande_id, status: "en_attente" },
        ]),
      );
      expect(nativePending.approval_bindings).toHaveLength(1);
      expect(twoProposals.approval_bindings).toHaveLength(2);
      const originalBinding = twoProposals.approval_bindings.find(
        (binding: { demande_id: string }) => binding.demande_id === originalRequestId,
      );
      expect(originalBinding).toStrictEqual(nativePending.approval_bindings[0]);
      // A missing hash would skip the native sealed-ticket revalidation branch.
      expect(originalBinding.ticket_cible_hash).toMatch(/^[a-f0-9]{64}$/);
      expect(originalBinding.arguments).toStrictEqual(prepared.arguments.A);
      expect(originalBinding.ticket).toMatchObject({
        ticket_hash: originalBinding.ticket_cible_hash,
        demande_id: originalRequestId,
        statut: "scelle",
        departement: agentId,
        outil: tool,
        affaire_id: prepared.affairs.A,
        cle_session: prepared.session_key,
        empreinte_arguments: expect.stringMatching(/^[a-f0-9]{64}$/),
      });

      // This existing helper injects the fictive owner's choice into the real native
      // approval guard; paired Core-device authentication is qualified separately.
      const decision = JSON.parse(
        await runFixture(python, home, "approve", ["--request-id", originalRequestId]),
      );
      expect(decision).toMatchObject({ statut: "executee" });
      const approvedOriginal = await inspect();
      expect(approvedOriginal.owner_active).toBe(true);
      expect(approvedOriginal.requests).toHaveLength(2);
      expect(approvedOriginal.requests).toEqual(
        expect.arrayContaining([
          { id: originalRequestId, status: "executee" },
          { id: freshRequest.demande_id, status: "en_attente" },
        ]),
      );
      expect(approvedOriginal.followups).toHaveLength(1);
      expect(approvedOriginal.followups[0]).toMatchObject({
        suivi_id: originalRequestId,
        statut: "planifiee",
        decision: { decide_par: "nathan-fixture", decide_role: "nathan_owner" },
      });
      expect(approvedOriginal.decision_audits).toHaveLength(1);
      // Native approval cannot silently reconcile either Core intent or dispatch M9 again.
      expect(
        await listOpsysPostflightIntents({ database: reopened, options, now: Date.now() }),
      ).toStrictEqual(freshPending);
      expect(
        await listOpsysPostflightLots({ database: reopened, options, now: Date.now() }),
      ).toEqual([]);
      expect(await readDispatches()).toStrictEqual(twoDispatches);
    } finally {
      authority.abort();
      await cleanupSessionStateForTest({ stateDir: coreState });
    }
  }, 90_000);

  it("blocks a fresh M9 effect after a committed response is lost and SQLite reopens", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m9-network-loss-http-"));
    tempDirs.push(home);
    const prepared = JSON.parse(
      await runFixture(python, home, "prepare-m9", ["--postflight-depot"]),
    ) as {
      fictif: boolean;
      session_key: string;
      affairs: Record<"A" | "B", string>;
      arguments: Record<"A" | "B", Record<string, unknown>>;
      generated_context: { agent: { depot: string[] } };
    };
    const agentId = "m09-strategic-intelligence";
    const tool = "m9_ouvrir_suivi_decision";
    const sessionId = "opsys-real-python-m9-network-loss";
    const toolCallId = "m9-fictif-network-loss-call";
    expect(prepared.fictif).toBe(true);
    // Actual native generation with an explicitly selected deposit tool; shared config is untouched.
    expect(prepared.generated_context.agent.depot).toEqual([tool]);
    const coreState = resolve(home, "core-state");
    const target = {
      agentId,
      cwd: coreState,
      sessionId,
      sessionKey: prepared.session_key,
      storePath: resolve(coreState, "agents", agentId, "sessions", "sessions.json"),
    };
    await mkdir(dirname(target.storePath), { recursive: true });
    const authority = new AbortController();
    try {
      const sessionEntry = await upsertSessionEntryCore(target, { sessionId, updatedAt: 1 });
      if (!sessionEntry) {
        throw new Error("fictive M9 transcript entry was not persisted");
      }
      const recorder = createUserTurnTranscriptRecorder({
        message: {
          role: "user",
          content: "fictif: true; revoir la durée du chantier",
          timestamp: 2,
        },
        target: () => ({ ...target, sessionEntry }),
        updateMode: "none",
      });
      expect(await recorder.persistApproved()).toBeDefined();
      const receipt = recorder.getAdmissionReceipt();
      if (!receipt || receipt.agentId !== agentId || receipt.sessionId !== sessionId) {
        throw new Error("canonical M9 transcript admission absent");
      }
      const options = { agentId: receipt.agentId, path: receipt.storePath };
      const database = openOpenClawAgentDatabase(options);
      const createCollector = async (runId: string) => {
        const collector = new OpsysPostflightCollector({
          runId,
          sessionId,
          sessionKey: prepared.session_key,
          agentId,
          recorder,
          depositTools: prepared.generated_context.agent.depot,
          assertCurrent: () => authority.signal.throwIfAborted(),
        });
        // This provider/model admission is synthetic; the user transcript above is really persisted.
        collector.recordRuntimeAdmission({
          runId,
          agentId,
          profileId: "m9-fictif-pending-profile",
          profileRevision: 1,
          departement: agentId,
          attemptId: `${runId}-attempt`,
          cycleId: `${runId}-cycle`,
        });
        await collector.prepareBeforeProviderDispatch();
        return collector;
      };
      const collector = await createCollector("m9-fictif-network-loss-run");
      expect(await listOpsysPostflightIntents({ database, options, now: Date.now() })).toEqual([]);
      expect(await listOpsysPostflightLots({ database, options, now: Date.now() })).toEqual([]);
      const port = await reservePort();
      const server = await startPythonMcp(python, home, port, database.path, true);
      const runtime = await getOrCreateSessionMcpRuntime({
        sessionId,
        sessionKey: prepared.session_key,
        workspaceDir: home,
        cfg: { plugins: { enabled: false }, ...m9OpsysConfig(port) },
      });
      opsysContexteGuardStore.set(prepared.session_key, {
        kind: "ready",
        affaireId: prepared.affairs.A,
        nbOuverts: 0,
        atMs: Date.now(),
      });
      const observer = collector.beginToolCall({
        toolCallId,
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!observer) {
        throw new Error("M9 postflight observer must be attached to the actual Core call");
      }
      // Actual native handler commits its sealed request, but its transport loses all result bytes.
      await expect(
        runtime.callTool("opsys_m9", tool, prepared.arguments.A, observer),
      ).rejects.toThrow();
      const lost = JSON.parse(await readFile(resolve(home, "m9-response-lost.json"), "utf8"));
      expect(lost).toMatchObject({
        fictif: true,
        owner_active: true,
        affaire_id: prepared.affairs.A,
        cle_session: prepared.session_key,
        ticket_hash: expect.stringMatching(/^[a-f0-9]{64}$/),
        independent_committed_read_before_headers: true,
        original_headers_forwarded: true,
        response_body_forwarded_bytes: 0,
      });
      expect(lost.native_response_bytes_buffered).toBeGreaterThan(0);
      const inspect = async () => JSON.parse(await runFixture(python, home, "inspect-m9"));
      const nativePending = await inspect();
      expect(nativePending).toMatchObject({
        owner_active: true,
        requests: [{ id: lost.request_id, status: "en_attente" }],
        followups: [],
        decision_audits: [],
      });
      expect(nativePending.approval_bindings).toHaveLength(1);
      expect(nativePending.approval_bindings[0]).toMatchObject({
        demande_id: lost.request_id,
        ticket_cible_hash: lost.ticket_hash,
        arguments: prepared.arguments.A,
        ticket: { ticket_hash: lost.ticket_hash, demande_id: lost.request_id, statut: "scelle" },
      });
      const pending = await listOpsysPostflightIntents({ database, options, now: Date.now() });
      expect(pending).toHaveLength(1);
      expect(pending[0]).toMatchObject({
        factKey: depositKey(sessionId, toolCallId),
        state: "uncertain",
      });
      const readDispatches = async () =>
        (await readFile(resolve(home, "m9-business-dispatches.jsonl"), "utf8"))
          .trim()
          .split("\n")
          .filter(Boolean)
          .map((row) => JSON.parse(row));
      const expectedDispatch = [
        {
          fictif: true,
          intents: [{ fact_key: depositKey(sessionId, toolCallId), state: "uncertain" }],
          outbox_count: 0,
        },
      ];
      expect(await readDispatches()).toStrictEqual(expectedDispatch);
      // Reset the actual manager and establish healthy transport on the SAME owned server.
      expect(server.exitCode).toBeNull();
      expect(server.signalCode).toBeNull();
      await resetSessionMcpRuntimeManagerGeneration();
      const recoveredRuntime = await getOrCreateSessionMcpRuntime({
        sessionId,
        sessionKey: prepared.session_key,
        workspaceDir: home,
        cfg: { plugins: { enabled: false }, ...m9OpsysConfig(port) },
      });
      const healthy = await recoveredRuntime.listTools("opsys_m9");
      expect(healthy.tools.map((item) => item.name)).toContain(tool);
      const liveReplay = collector.beginToolCall({
        toolCallId: "m9-fictif-network-loss-live-replay",
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!liveReplay) throw new Error("expected the unresolved live collector's observer");
      await expect(
        recoveredRuntime.callTool("opsys_m9", tool, prepared.arguments.A, liveReplay),
      ).rejects.toThrow("durable capture is unresolved");
      expect(await readDispatches()).toStrictEqual(expectedDispatch);
      await closeOpenClawAgentDatabaseByPathAsync(database.path, agentId);
      expect(database.db.isOpen).toBe(false);
      const disk = new DatabaseSync(database.path, { readOnly: true });
      try {
        expect(disk.prepare("SELECT fact_key, state FROM opsys_postflight_intents").all()).toEqual([
          { fact_key: depositKey(sessionId, toolCallId), state: "uncertain" },
        ]);
        expect(
          disk.prepare("SELECT COUNT(*) AS count FROM opsys_postflight_outbox").get()?.count,
        ).toBe(0);
      } finally {
        disk.close();
      }
      const exactCollector = await createCollector("m9-fictif-network-loss-exact-run");
      const reopened = openOpenClawAgentDatabase(options);
      expect(reopened).not.toBe(database);
      const exact = exactCollector.beginToolCall({
        toolCallId,
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!exact) throw new Error("expected the reopened exact-key observer");
      await expect(
        recoveredRuntime.callTool("opsys_m9", tool, prepared.arguments.A, exact),
      ).rejects.toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
      expect(
        await listOpsysPostflightIntents({ database: reopened, options, now: Date.now() }),
      ).toStrictEqual(pending);
      expect(await readDispatches()).toStrictEqual(expectedDispatch);
      // A third collector prevents the rejected exact-key call's RAM failure from masking the fence.
      const freshCollector = await createCollector("m9-fictif-network-loss-fresh-run");
      const fresh = freshCollector.beginToolCall({
        toolCallId: "m9-fictif-network-loss-fresh-call",
        toolName: tool,
        serverName: "opsys_m9",
      });
      if (!fresh) throw new Error("expected an independent fresh-key observer");
      let rejected = false;
      let resultReceived = false;
      let freshBoundaryReached = false;
      let freshReceiptValid = false;
      let freshBoundaryError: unknown;
      let freshOuterError: unknown;
      // Delegate to the real frozen observer. A failed issuer, storage fault, or stale
      // authority must not masquerade as the durable unresolved-intent fence.
      const witnessedFresh: OpsysPostflightCallObserver = {
        ...fresh,
        async assertBeforeEffect(target) {
          freshBoundaryReached = true;
          expect(target).toMatchObject({
            agentId,
            sessionKey: prepared.session_key,
            affaireId: prepared.affairs.A,
            serverName: "opsys_m9",
            toolName: tool,
          });
          freshReceiptValid = true;
          try {
            await fresh.assertBeforeEffect(target);
          } catch (error) {
            freshBoundaryError = error;
            throw error;
          }
        },
      };
      try {
        await recoveredRuntime.callTool("opsys_m9", tool, prepared.arguments.A, witnessedFresh);
        resultReceived = true;
      } catch (error) {
        rejected = true;
        freshOuterError = error;
      }
      const beforeChoice = await inspect();
      const afterIntents = await listOpsysPostflightIntents({
        database: reopened,
        options,
        now: Date.now(),
      });
      const afterLots = await listOpsysPostflightLots({
        database: reopened,
        options,
        now: Date.now(),
      });
      const dispatches = await readDispatches();
      expect(
        afterIntents.find((intent) => intent.factKey === depositKey(sessionId, toolCallId)),
      ).toStrictEqual(pending[0]);
      expect(beforeChoice.owner_active).toBe(true);
      expect(beforeChoice.followups).toEqual([]);
      expect(beforeChoice.decision_audits).toEqual([]);
      const originalBinding = beforeChoice.approval_bindings.find(
        (binding: { demande_id: string }) => binding.demande_id === lost.request_id,
      );
      expect(originalBinding).toStrictEqual(nativePending.approval_bindings[0]);
      expect(originalBinding.ticket_cible_hash).toMatch(/^[a-f0-9]{64}$/);
      // An explicit fixture owner choice remains possible; this is not Core-device authentication.
      expect(
        JSON.parse(await runFixture(python, home, "approve", ["--request-id", lost.request_id])),
      ).toMatchObject({ statut: "executee" });
      const afterChoice = await inspect();
      expect(afterChoice.owner_active).toBe(true);
      expect(afterChoice.followups).toHaveLength(1);
      expect(afterChoice.followups[0]).toMatchObject({
        suivi_id: lost.request_id,
        statut: "planifiee",
      });
      expect(afterChoice.decision_audits).toHaveLength(1);
      expect(
        await listOpsysPostflightIntents({ database: reopened, options, now: Date.now() }),
      ).toStrictEqual(afterIntents);
      // Capture every discriminant before this final assertion so a red preserves its actual cause.
      expect({
        healthyTransport: healthy.tools.some((item) => item.name === tool),
        originalOwnerValid: beforeChoice.owner_active,
        freshBoundaryReached,
        freshReceiptValid,
        freshErrorCameFromBoundary:
          freshBoundaryError !== undefined && freshOuterError === freshBoundaryError,
        freshDurableRefusal:
          freshBoundaryError instanceof Error &&
          freshBoundaryError.message.includes("POSTFLIGHT_UNRESOLVED_INTENT"),
        freshCallRejected: rejected,
        freshResultReceived: resultReceived,
        nativeRequestsBeforeOwnerChoice: beforeChoice.requests.length,
        businessDispatchesBeforeOwnerChoice: dispatches.length,
        durableIntentCount: afterIntents.length,
        outboxCount: afterLots.length,
      }).toStrictEqual({
        healthyTransport: true,
        originalOwnerValid: true,
        freshBoundaryReached: true,
        freshReceiptValid: true,
        freshErrorCameFromBoundary: true,
        freshDurableRefusal: true,
        freshCallRejected: true,
        freshResultReceived: false,
        nativeRequestsBeforeOwnerChoice: 1,
        businessDispatchesBeforeOwnerChoice: 1,
        durableIntentCount: 1,
        outboxCount: 0,
      });
    } finally {
      authority.abort();
      await cleanupSessionStateForTest({ stateDir: coreState });
    }
  }, 90_000);

  it("refuses stale M9 approval after affair replacement with the owner valid and opens fresh B", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m9-cible-ticket-http-"));
    tempDirs.push(home);
    const prepared = JSON.parse(await runFixture(python, home, "prepare-m9")) as {
      fictif: boolean;
      session_key: string;
      affairs: Record<"A" | "B", string>;
      arguments: Record<"A" | "B", Record<string, unknown>>;
      generated_context: {
        agent: unknown;
        niveaux: Record<string, string>;
        cibles: Record<string, unknown>;
      };
    };
    expect(prepared.fictif).toBe(true);
    const configPath = process.env.OPENCLAW_CONFIG_PATH;
    if (!configPath) {
      throw new Error("The shared OPSYS context fixture must be admitted before real M9 HTTP");
    }
    const consumed = JSON.parse(
      await readFile(resolve(dirname(configPath), "opsys/contexte.json"), "utf8"),
    ) as {
      agents: Record<string, unknown>;
      niveaux: Record<string, string>;
      cibles: Record<string, unknown>;
    };
    const tools = [
      "m9_ouvrir_suivi_decision",
      "m9_preparer_suivi_decision",
      "m9_lire_suivi_decision",
    ];
    // Verify the consumed shared contract, without racing other files by replacing its path.
    expect({
      agent: consumed.agents["m09-strategic-intelligence"],
      niveaux: Object.fromEntries(tools.map((name) => [name, consumed.niveaux[name]])),
      cibles: Object.fromEntries(
        tools
          .filter((name) => Object.hasOwn(consumed.cibles, name))
          .map((name) => [name, consumed.cibles[name]]),
      ),
    }).toStrictEqual(prepared.generated_context);
    const inspect = async () =>
      JSON.parse(await runFixture(python, home, "inspect-m9")) as {
        owner_active: boolean;
        linked_affair: string;
        requests: { id: string; status: string }[];
        followups: {
          suivi_id: string;
          source: Record<string, unknown>;
          decision: Record<string, unknown>;
        }[];
        tickets: number;
        tables_digest: string;
      };
    expect(await inspect()).toMatchObject({
      owner_active: true,
      requests: [],
      followups: [],
      tickets: 0,
    });
    const port = await reservePort();
    await startPythonMcp(python, home, port);
    const runtime = await getOrCreateSessionMcpRuntime({
      sessionId: "opsys-real-python-m9-followup",
      sessionKey: prepared.session_key,
      workspaceDir: home,
      cfg: { plugins: { enabled: false }, ...m9OpsysConfig(port) },
    });
    opsysContexteGuardStore.set(prepared.session_key, {
      kind: "ready",
      affaireId: prepared.affairs.A,
      nbOuverts: 0,
      atMs: Date.now(),
    });
    // No authenticated device metadata: the actual Core private issuer must be used.
    const resultA = await runtime.callTool(
      "opsys_m9",
      "m9_ouvrir_suivi_decision",
      prepared.arguments.A,
    );
    expect(resultA.isError).not.toBe(true);
    const a = JSON.parse(resultA.content.find((item) => item.type === "text")?.text ?? "null") as {
      demande_id: string;
      statut: string;
    };
    expect(a).toMatchObject({ statut: "en_attente_approbation", demande_id: expect.any(String) });
    expect(await inspect()).toMatchObject({
      owner_active: true,
      linked_affair: prepared.affairs.A,
      requests: [{ id: a.demande_id, status: "en_attente" }],
      followups: [],
      tickets: 1,
    });
    // The durable pending proposal is the synchronization point before the N3 effect.
    await runFixture(python, home, "switch-m9-b");
    const beforeRefusal = await inspect();
    expect(beforeRefusal).toMatchObject({
      owner_active: true,
      linked_affair: prepared.affairs.B,
      followups: [],
    });
    const refusal = JSON.parse(
      await runFixture(python, home, "refuse-m9-approval", ["--request-id", a.demande_id]),
    );
    expect(refusal).toMatchObject({
      refused: true,
      owner_active: true,
      reason: expect.stringMatching(/révoquée|remplacée/),
    });
    expect(await inspect()).toStrictEqual(beforeRefusal);

    opsysContexteGuardStore.set(prepared.session_key, {
      kind: "ready",
      affaireId: prepared.affairs.B,
      nbOuverts: 0,
      atMs: Date.now(),
    });
    const resultB = await runtime.callTool(
      "opsys_m9",
      "m9_ouvrir_suivi_decision",
      prepared.arguments.B,
    );
    expect(resultB.isError).not.toBe(true);
    const b = JSON.parse(resultB.content.find((item) => item.type === "text")?.text ?? "null") as {
      demande_id: string;
      statut: string;
    };
    expect(b).toMatchObject({ statut: "en_attente_approbation", demande_id: expect.any(String) });
    expect(b.demande_id).not.toBe(a.demande_id);
    const approval = JSON.parse(
      await runFixture(python, home, "approve", ["--request-id", b.demande_id]),
    );
    expect(approval).toMatchObject({ statut: "executee" });
    const final = await inspect();
    expect(final.owner_active).toBe(true);
    expect(final.linked_affair).toBe(prepared.affairs.B);
    expect(final.tickets).toBe(2);
    expect(final.requests).toEqual(
      expect.arrayContaining([
        { id: a.demande_id, status: "en_attente" },
        { id: b.demande_id, status: "executee" },
      ]),
    );
    expect(final.requests).toHaveLength(2);
    expect(final.followups).toHaveLength(1);
    expect(final.followups[0]).toMatchObject({
      suivi_id: b.demande_id,
      source: {
        evenement_id: prepared.arguments.B.evenement_id,
        empreinte_source: prepared.arguments.B.empreinte_source,
      },
      decision: { decide_par: "nathan-fixture", decide_role: "nathan_owner" },
    });
  });

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
