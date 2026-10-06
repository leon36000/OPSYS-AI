import { execFile, spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../../test/helpers/opsys-context-test-config.js";
import { upsertSessionEntryCore } from "../../config/sessions/session-accessor.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import { opsysContexteGuardStore } from "../../context-engine/opsys-contexte-garde.js";
import { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import { createUserTurnTranscriptRecorder } from "../../sessions/user-turn-transcript.js";
import { createSqliteTranscriptTarget } from "../../sessions/user-turn-transcript.test-support.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { withOpenClawTestState } from "../../test-utils/openclaw-test-state.js";
import { cleanupSessionStateForTest } from "../../test-utils/session-state-cleanup.js";
import { getSessionMcpRuntimeManagerForTesting } from "../agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "../agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "../agent-bundle-mcp-runtime-shared.js";
import { buildAfterTurnRuntimeContext } from "../embedded-agent-runner/run/attempt-prompt-helpers.js";
import { OpsysPostflightCollector } from "./opsys-postflight-collector.js";
import { deliverOpsysPostflightLots } from "./opsys-postflight-delivery.js";
import {
  prepareWireCollector,
  writeSyntheticWireServers,
  WIRE_AGENT,
  WIRE_TOOL,
  WIRE_AFFAIRE,
  WIRE_ARGS,
} from "./opsys-postflight-mcp.test-support.js";
import {
  enqueueOpsysPostflightLots,
  listOpsysPostflightLots,
  listOpsysPostflightIntents,
} from "./opsys-postflight-outbox.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-postflight-fixture.py");
const PROFILE = { id: "it-postflight", revision: 2, departement: "m03-estimation" };
const PRIVATE = "synthetic-postflight-private-token-not-a-credential-2026";
const PUBLIC = "synthetic-postflight-public-token-not-a-credential-2026";
const runExecFile = promisify(execFile);
const MAX_OUTPUT = 64 * 1_024;

function pythonPath(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON required for real POSTFLIGHT TCP integration");
  }
  return python;
}

function pythonEnv(home: string): NodeJS.ProcessEnv {
  return {
    OPSYS_HOME: home,
    TMPDIR: home,
    OPSYS_DEPARTMENTS: resolve(REPO, "departments"),
    OPSYS_CONTEXT_MCP_JETON: PRIVATE,
    OPSYS_MCP_JETON: PUBLIC,
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    TZ: "UTC",
    LANG: "C.UTF-8",
    PYTHONPATH: [
      resolve(REPO, "src"),
      ...[
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
      ].map((dep) => resolve(REPO, `departments/${dep}/src`)),
    ].join(delimiter),
  };
}

async function action(name: string, env: NodeJS.ProcessEnv): Promise<unknown> {
  const { stdout } = await runExecFile(pythonPath(), [FIXTURE, name], {
    env,
    cwd: REPO,
    timeout: 10_000,
    maxBuffer: MAX_OUTPUT,
  });
  return stdout.trim() ? JSON.parse(stdout) : undefined;
}

function hasExited(child: ReturnType<typeof spawn>): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function waitExit(child: ReturnType<typeof spawn>): Promise<boolean> {
  if (hasExited(child)) {
    return true;
  }
  return await new Promise<boolean>((resolveExit) => {
    const finish = (closed: boolean) => {
      clearTimeout(timer);
      child.removeListener("close", onClose);
      resolveExit(closed || hasExited(child));
    };
    const onClose = () => finish(true);
    const timer = setTimeout(() => finish(false), 2_000);
    child.once("close", onClose);
    if (hasExited(child)) {
      finish(true);
    }
  });
}

async function stop(child: ReturnType<typeof spawn>): Promise<void> {
  if (hasExited(child)) {
    return;
  }
  child.kill("SIGTERM");
  if (await waitExit(child)) {
    return;
  }
  child.kill("SIGKILL");
  if (!(await waitExit(child))) {
    throw new Error("POSTFLIGHT Python child survived bounded cleanup");
  }
}

async function start(env: NodeJS.ProcessEnv) {
  const child = spawn(pythonPath(), [FIXTURE, "serve"], {
    env,
    cwd: REPO,
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    const port = await new Promise<number>((resolvePort, reject) => {
      let settled = false;
      let bytes = 0;
      let output = "";
      const finish = (readyPort?: number, error?: Error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        child.stdout?.removeListener("data", onData);
        child.stderr?.removeListener("data", onData);
        child.removeListener("error", onError);
        child.removeListener("exit", onExit);
        if (error) {
          reject(error);
        } else if (readyPort) {
          resolvePort(readyPort);
        }
      };
      const onError = () => finish(undefined, new Error("POSTFLIGHT Python could not start"));
      const onExit = () =>
        finish(undefined, new Error("POSTFLIGHT Python exited before readiness"));
      const onData = (chunk: Buffer) => {
        bytes += chunk.length;
        if (bytes > MAX_OUTPUT) {
          finish(undefined, new Error("POSTFLIGHT Python readiness output bound exceeded"));
          return;
        }
        output += chunk.toString("utf8");
        const match = /Uvicorn running on http:\/\/127\.0\.0\.1:(\d+)/u.exec(output);
        if (match) {
          finish(Number(match[1]));
        }
      };
      const timer = setTimeout(
        () => finish(undefined, new Error("POSTFLIGHT Python readiness deadline")),
        15_000,
      );
      child.stdout?.on("data", onData);
      child.stderr?.on("data", onData);
      child.once("error", onError);
      child.once("exit", onExit);
    });
    // Drain output after readiness; the fixture only writes bounded protocol/server diagnostics.
    child.stdout?.resume();
    child.stderr?.resume();
    return { child, port };
  } catch (error) {
    await stop(child);
    throw error;
  }
}

function config(port: number): OpenClawConfig {
  return {
    mcp: {
      servers: {
        [`opsys_runtime_${PROFILE.id}`]: {
          url: `http://127.0.0.1:${port}/mcp/runtime/${PROFILE.id}`,
          transport: "streamable-http",
          headers: { Authorization: `Bearer ${PRIVATE}` },
          connectionTimeoutMs: 4_000,
          requestTimeoutMs: 4_000,
        },
      },
    },
  };
}

async function withPython(
  run: (env: NodeJS.ProcessEnv, cfg: OpenClawConfig) => Promise<void>,
): Promise<void> {
  const home = await mkdtemp(resolve(tmpdir(), "opsys-postflight-python-"));
  const env = pythonEnv(home);
  let server: Awaited<ReturnType<typeof start>> | undefined;
  try {
    await action("prepare", env);
    server = await start(env);
    await run(env, config(server.port));
  } finally {
    if (server) {
      await stop(server.child);
    }
    await rm(home, { recursive: true, force: true });
  }
}

const fact = {
  cle: depositKey("synthetic-pf-session", "synthetic-pf-call"),
  outil: "m3_creer_devis",
  resultat: "ok" as const,
  code: null,
};
const lot = {
  affaireId: "LEAD-SYNTHETIC-PF",
  departementSource: PROFILE.departement,
  profilId: PROFILE.id,
  revision: PROFILE.revision,
  engineId: "opsys",
  facts: [fact],
};

function expectSingleFact(state: unknown): void {
  expect(state).toMatchObject({
    chain_valid: true,
    facts: [
      {
        cle_depot: fact.cle,
        affaire_id: lot.affaireId,
        departement_source: PROFILE.departement,
        outil: fact.outil,
        resultat: "ok",
      },
    ],
  });
  if (
    state === null ||
    typeof state !== "object" ||
    !("facts" in state) ||
    !Array.isArray(state.facts)
  ) {
    throw new Error("synthetic M10 inspection missing facts");
  }
  expect(state.facts).toHaveLength(1);
}

describe("OPSYS outbox delivery with real Python TCP/M10/SQLite", () => {
  it("keeps the lot on lost ACK and replays identical fact after canonical Core DB reopen", async () => {
    await withPython(async (env, cfg) => {
      await withOpenClawTestState({ label: "postflight-real-python-lost-ack" }, async (state) => {
        const options = { agentId: "opsys-agent-it-postflight" };
        let database = openOpenClawAgentDatabase(options);
        let now = Date.parse("2026-10-05T10:00:00Z");
        await enqueueOpsysPostflightLots({ database, options, lots: [lot], now });
        const delivery = () => ({
          database,
          options,
          config: cfg,
          timeoutMs: 4_000,
          profile: PROFILE,
          assertCurrent: () => undefined,
          signal: new AbortController().signal,
          nowMs: () => now,
        });
        let realCalls = 0;
        const lost = await deliverOpsysPostflightLots(delivery(), {
          callTool: async (request) => {
            realCalls += 1;
            await callOpsysMcpTool(request);
            throw new Error("synthetic lost ACK after real M10 commit");
          },
        });
        expect(realCalls).toBe(1);
        expect(lost).toMatchObject({ attempted: 1, delivered: 0, failed: 1 });
        expectSingleFact(await action("inspect", env));
        const pending = await listOpsysPostflightLots({ database, options, now });
        expect(pending).toHaveLength(1);
        expect(pending[0]).toMatchObject({ attemptCount: 1, state: "retry", facts: [fact] });
        await cleanupSessionStateForTest({ stateDir: state.stateDir });
        database = openOpenClawAgentDatabase(options);
        now += 60_000;
        const replay = await deliverOpsysPostflightLots(delivery());
        expect(replay).toMatchObject({
          attempted: 1,
          delivered: 1,
          failed: 0,
          acknowledgementFailures: 0,
        });
        expect(await listOpsysPostflightLots({ database, options, now })).toEqual([]);
        expectSingleFact(await action("inspect", env));
      });
    });
  }, 40_000);

  it("retains a durable lot when the Python profile is revoked before delivery", async () => {
    await withPython(async (env, cfg) => {
      await withOpenClawTestState({ label: "postflight-real-python-revocation" }, async () => {
        const options = { agentId: "opsys-agent-it-postflight" };
        const database = openOpenClawAgentDatabase(options);
        const now = Date.parse("2026-10-05T10:00:00Z");
        await enqueueOpsysPostflightLots({ database, options, lots: [lot], now });
        await action("revoke", env);
        const result = await deliverOpsysPostflightLots({
          database,
          options,
          config: cfg,
          timeoutMs: 4_000,
          profile: PROFILE,
          assertCurrent: () => undefined,
          signal: new AbortController().signal,
          nowMs: () => now,
        });
        expect(result).toMatchObject({ delivered: 0, failed: 1 });
        expect(await listOpsysPostflightLots({ database, options, now })).toHaveLength(1);
        expect(await action("inspect", env)).toMatchObject({
          facts: [],
          chain_valid: true,
          profile_active: false,
        });
      });
    });
  }, 40_000);

  it("joins an admitted real transcript collector to the real private TCP delivery", async () => {
    await withPython(async (env, cfg) => {
      await withOpenClawTestState(
        { label: "postflight-real-collector-to-python" },
        async (state) => {
          const sessionId = "synthetic-pf-session";
          const sessionKey = `agent:main:${sessionId}`;
          const target = createSqliteTranscriptTarget({
            dir: state.stateDir,
            sessionId,
            sessionKey,
          });
          const sessionEntry = await upsertSessionEntryCore(target, { sessionId, updatedAt: 1 });
          if (!sessionEntry) {
            throw new Error("synthetic session entry missing");
          }
          const recorder = createUserTurnTranscriptRecorder({
            message: { role: "user", content: "synthetic approved user input", timestamp: 2 },
            target: () => ({ ...target, sessionEntry }),
            updateMode: "none",
          });
          expect(await recorder.persistApproved()).toBeDefined();
          const collector = new OpsysPostflightCollector({
            runId: "synthetic-pf-run",
            sessionId,
            sessionKey,
            agentId: "main",
            recorder,
            depositTools: ["m3_creer_devis"],
            assertCurrent: () => undefined,
          });
          collector.recordRuntimeAdmission({
            runId: "synthetic-pf-run",
            agentId: "main",
            profileId: PROFILE.id,
            profileRevision: PROFILE.revision,
            departement: PROFILE.departement,
            attemptId: "synthetic-pf-attempt",
            cycleId: "synthetic-pf-cycle",
          });
          await collector.prepareBeforeProviderDispatch();
          const observer = collector.beginToolCall({
            toolCallId: "synthetic-pf-call",
            toolName: "m3_creer_devis",
            serverName: "opsys_m3",
          });
          if (!observer) {
            throw new Error("synthetic ticket tool observer missing");
          }
          await observer.assertBeforeEffect({
            agentId: "main",
            sessionKey,
            affaireId: lot.affaireId,
            serverName: "opsys_m3",
            toolName: "m3_creer_devis",
          });
          // A known synthetic tool response, not a real business effect or a provider execution.
          await observer.observe(
            {
              agentId: "main",
              sessionKey,
              affaireId: lot.affaireId,
              serverName: "opsys_m3",
              toolName: "m3_creer_devis",
            },
            {
              content: [
                { type: "text", text: JSON.stringify({ ok: true, resultat: { fictif: true } }) },
              ],
            },
            { authorityCurrent: true },
          );
          const hostContext = buildAfterTurnRuntimeContext({
            attempt: {
              sessionId,
              sessionKey,
              config: cfg,
              provider: "synthetic-provider",
              modelId: "synthetic-model",
              thinkLevel: "off",
              reasoningLevel: "on",
              skillsSnapshot: undefined,
              opsysPostflightCollector: collector,
            },
            workspaceDir: state.stateDir,
            agentDir: state.stateDir,
            activeAgentId: "main",
          });
          expect(hostContext.opsysDeferredPostflight).toEqual({
            sessionId,
            sessionKey,
            agentId: "main",
            factKeys: [fact.cle],
          });
          const receipt = recorder.getAdmissionReceipt();
          if (!receipt) {
            throw new Error("synthetic durable admission receipt missing");
          }
          const options = { agentId: receipt.agentId, path: receipt.storePath };
          const database = openOpenClawAgentDatabase(options);
          expect(
            await listOpsysPostflightLots({ database, options, now: Date.now() }),
          ).toHaveLength(1);
          const delivered = await collector.deliverPending({
            config: cfg,
            timeoutMs: 4_000,
            signal: new AbortController().signal,
          });
          expect(delivered).toMatchObject({
            attempted: 1,
            delivered: 1,
            failed: 0,
            acknowledgementFailures: 0,
          });
          expect(await listOpsysPostflightLots({ database, options, now: Date.now() })).toEqual([]);
          expectSingleFact(await action("inspect", env));
        },
      );
    });
  }, 40_000);
});

describe("actual MCP runtime -> collector -> SQLite -> Python M10; synthetic source/ticket", () => {
  for (const outcome of ["known", "disconnect"] as const) {
    it(`joins durable pre-effect reservation and ${outcome} source outcome`, async () => {
      await withPython(async (env, cfg) => {
        await withOpenClawTestState({ label: `postflight-wire-${outcome}` }, async (state) => {
          const sessionId = `synthetic-wire-${outcome}`;
          const sessionKey = `agent:${WIRE_AGENT}:${sessionId}`;
          const toolCallId = `synthetic-wire-call-${outcome}`;
          const key = depositKey(sessionId, toolCallId);
          let releaseContext: (() => Promise<void>) | undefined;
          await getSessionMcpRuntimeManagerForTesting().disposeAll();
          delete (globalThis as Record<PropertyKey, unknown>)[SESSION_MCP_RUNTIME_MANAGER_KEY];
          try {
            releaseContext = await acquireOpsysContextTestConfig();
            const harness = await prepareWireCollector({
              root: state.stateDir,
              sessionId,
              sessionKey,
              profileId: PROFILE.id,
              revision: PROFILE.revision,
            });
            const peer = await writeSyntheticWireServers({
              root: state.stateDir,
              databasePath: harness.database.path,
              factKey: key,
              outcome,
            });
            const wireConfig: OpenClawConfig = {
              ...cfg,
              plugins: { enabled: false },
              mcp: { servers: { ...cfg.mcp?.servers, ...peer.servers } },
            };
            const runtime = await getOrCreateSessionMcpRuntime({
              sessionId,
              sessionKey,
              workspaceDir: state.stateDir,
              cfg: wireConfig,
            });
            opsysContexteGuardStore.set(sessionKey, {
              kind: "ready",
              affaireId: WIRE_AFFAIRE,
              nbOuverts: 0,
              atMs: Date.now(),
            });
            const collector = await harness.createCollector("synthetic-wire-first");
            const observer = collector.beginToolCall({
              toolCallId,
              toolName: WIRE_TOOL,
              serverName: "opsys_m3",
            });
            expect(observer).toBeDefined();
            if (!observer) {
              throw new Error("actual collector observer missing");
            }
            if (outcome === "known") {
              const returned = await runtime.callTool("opsys_m3", WIRE_TOOL, WIRE_ARGS, observer);
              expect(returned.isError).not.toBe(true);
              expect(await collector.flushPending()).toMatchObject({ remaining: 0, failures: 0 });
              expect(await listOpsysPostflightIntents({ ...harness, now: Date.now() })).toEqual([]);
              const pending = await listOpsysPostflightLots({ ...harness, now: Date.now() });
              expect(pending).toHaveLength(1);
              expect(pending[0]).toMatchObject({
                affaireId: WIRE_AFFAIRE,
                profilId: PROFILE.id,
                revision: PROFILE.revision,
                facts: [{ cle: key, outil: WIRE_TOOL, resultat: "ok", code: null }],
              });
              expect(
                await collector.deliverPending({
                  config: wireConfig,
                  timeoutMs: 4_000,
                  signal: new AbortController().signal,
                }),
              ).toMatchObject({
                attempted: 1,
                delivered: 1,
                failed: 0,
                acknowledgementFailures: 0,
              });
              expect(await listOpsysPostflightLots({ ...harness, now: Date.now() })).toEqual([]);
              expect(await action("inspect", env)).toMatchObject({
                chain_valid: true,
                facts: [
                  {
                    cle_depot: key,
                    affaire_id: WIRE_AFFAIRE,
                    departement_source: WIRE_AGENT,
                    outil: WIRE_TOOL,
                    resultat: "ok",
                  },
                ],
              });
              const inspection = await action("inspect", env);
              expect(inspection).toHaveProperty("facts.length", 1);
            } else {
              await expect(
                runtime.callTool("opsys_m3", WIRE_TOOL, WIRE_ARGS, observer),
              ).rejects.toThrow(/closed|disconnect|connection/iu);
              expect(await collector.flushPending()).toMatchObject({ remaining: 0, failures: 1 });
              await expect(
                collector.deliverPending({
                  config: wireConfig,
                  timeoutMs: 4_000,
                  signal: new AbortController().signal,
                }),
              ).rejects.toThrow("capture is unresolved");
              // Reconnect the source peer so refusal is caused by the collector, not a dead socket.
              await getSessionMcpRuntimeManagerForTesting().disposeSession(sessionId);
              const recoveredRuntime = await getOrCreateSessionMcpRuntime({
                sessionId,
                sessionKey,
                workspaceDir: state.stateDir,
                cfg: wireConfig,
              });
              const next = collector.beginToolCall({
                toolCallId: "synthetic-wire-other-call",
                toolName: WIRE_TOOL,
                serverName: "opsys_m3",
              });
              if (!next) {
                throw new Error("next source observer missing");
              }
              await expect(
                recoveredRuntime.callTool("opsys_m3", WIRE_TOOL, WIRE_ARGS, next),
              ).rejects.toThrow("durable capture is unresolved");
              const reserved = await listOpsysPostflightIntents({ ...harness, now: Date.now() });
              expect(reserved).toHaveLength(1);
              expect(reserved[0]).toMatchObject({
                factKey: key,
                affaireId: WIRE_AFFAIRE,
                state: "uncertain",
              });
              expect(await listOpsysPostflightLots({ ...harness, now: Date.now() })).toEqual([]);
              await cleanupSessionStateForTest({ stateDir: state.stateDir });
              const reopened = openOpenClawAgentDatabase(harness.options);
              expect(
                await listOpsysPostflightIntents({
                  database: reopened,
                  options: harness.options,
                  now: Date.now(),
                }),
              ).toEqual(reserved);
              const retryCollector = await harness.createCollector("synthetic-wire-second");
              const retry = retryCollector.beginToolCall({
                toolCallId,
                toolName: WIRE_TOOL,
                serverName: "opsys_m3",
              });
              if (!retry) {
                throw new Error("retry source observer missing");
              }
              await expect(
                recoveredRuntime.callTool("opsys_m3", WIRE_TOOL, WIRE_ARGS, retry),
              ).rejects.toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
              expect(await action("inspect", env)).toMatchObject({ chain_valid: true, facts: [] });
            }
            // The source process itself observed durable intent before the response/transport loss.
            expect(await peer.readObservations()).toStrictEqual([
              { fictif: true, intents: [{ fact_key: key, state: "uncertain" }], pendingLots: 0 },
            ]);
          } finally {
            opsysContexteGuardStore.set(sessionKey, {
              kind: "unavailable",
              reason: "isolated wire test cleanup",
              atMs: Date.now(),
            });
            await getSessionMcpRuntimeManagerForTesting().disposeAll();
            delete (globalThis as Record<PropertyKey, unknown>)[SESSION_MCP_RUNTIME_MANAGER_KEY];
            await releaseContext?.();
          }
        });
      });
    }, 40_000);
  }
});
