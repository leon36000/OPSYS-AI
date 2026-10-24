import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { AssistantMessage, Context, Model } from "openclaw/plugin-sdk/llm";
import { afterEach, describe, expect, it } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { runBeforeToolCallHook } from "../agent-tools.before-tool-call.policy.js";
import { hasModelFallbackStop } from "../failover-error.js";
import { runWithModelFallback } from "../model-fallback-runner.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../test-helpers/usage-fixtures.js";
import { createOpsysRuntimeAdmissionStreamFn } from "./opsys-runtime-admission.js";
import { startReconciliationProxy } from "./opsys-runtime-reconciliation-loss.test-support.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-runtime-admission-fixture.py");
const PRIVATE_TOKEN = "synthetic-integration-token-not-a-credential-2026";
const PUBLIC_TOKEN = "synthetic-public-token-not-a-credential-2026";
const children: ReturnType<typeof spawn>[] = [];
const tempDirs: string[] = [];

function childHasExited(child: ReturnType<typeof spawn>): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function waitForChildExit(
  child: ReturnType<typeof spawn>,
  timeoutMs: number,
): Promise<boolean> {
  if (childHasExited(child)) {
    return true;
  }
  return await new Promise<boolean>((resolveExit) => {
    const onExit = () => finish(true);
    const timeout = setTimeout(() => finish(false), timeoutMs);
    const finish = (exited: boolean) => {
      clearTimeout(timeout);
      child.removeListener("exit", onExit);
      resolveExit(exited || childHasExited(child));
    };
    child.once("exit", onExit);
    if (childHasExited(child)) {
      finish(true);
    }
  });
}

async function stopChild(child: ReturnType<typeof spawn>): Promise<void> {
  if (childHasExited(child)) {
    return;
  }
  child.kill("SIGTERM");
  if (await waitForChildExit(child, 2_000)) {
    return;
  }
  child.kill("SIGKILL");
  if (!(await waitForChildExit(child, 2_000))) {
    throw new Error("Python MCP process remained alive after SIGTERM and SIGKILL");
  }
}

afterEach(async () => {
  for (const child of children.splice(0)) {
    await stopChild(child);
  }
  await Promise.all(
    tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the real Python MCP integration test");
  }
  return python;
}

function isolatedEnvironment(home: string): NodeJS.ProcessEnv {
  for (const name of ["config", "data", "cache", "tmp"]) {
    mkdirSync(resolve(home, name), { recursive: true, mode: 0o700 });
  }
  return {
    HOME: home,
    OPSYS_HOME: home,
    XDG_CONFIG_HOME: resolve(home, "config"),
    XDG_DATA_HOME: resolve(home, "data"),
    XDG_CACHE_HOME: resolve(home, "cache"),
    TMPDIR: resolve(home, "tmp"),
    OPSYS_CONTEXT_MCP_JETON: PRIVATE_TOKEN,
    OPSYS_MCP_JETON: PUBLIC_TOKEN,
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
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
      ].map((department) => resolve(REPO, `departments/${department}/src`)),
    ].join(":"),
  };
}

function runPython(python: string, args: string[], env: NodeJS.ProcessEnv): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    const child = spawn(python, args, { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] });
    children.push(child);
    let stdout = "";
    let stderr = "";
    child.stdout?.setEncoding("utf8").on("data", (chunk: string) => (stdout += chunk));
    child.stderr?.setEncoding("utf8").on("data", (chunk: string) => (stderr += chunk));
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolveOutput(stdout);
      } else {
        reject(new Error(`Python fixture exited ${code}: ${stderr.slice(-2_000)}`));
      }
    });
  });
}

async function reserveEphemeralPort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolveListen());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("could not reserve a local port");
  }
  const { port } = address;
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  return port;
}

function waitUntilListening(child: ReturnType<typeof spawn>): Promise<void> {
  return new Promise((resolveListening, reject) => {
    let output = "";
    const timeout = setTimeout(
      () => reject(new Error(`Python MCP startup timed out: ${output.slice(-2_000)}`)),
      15_000,
    );
    const finish = (error?: Error) => {
      clearTimeout(timeout);
      if (error) {
        reject(error);
      } else {
        resolveListening();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", (chunk: string) => {
      output += chunk;
      if (output.includes("Uvicorn running on")) {
        finish();
      }
    });
    child.stderr?.setEncoding("utf8").on("data", (chunk: string) => {
      output += chunk;
      if (output.includes("Uvicorn running on")) {
        finish();
      }
    });
    child.once("error", (error) => finish(error));
    child.once("exit", (code) =>
      finish(new Error(`Python MCP exited before readiness (${code}): ${output.slice(-2_000)}`)),
    );
  });
}

function runtimeConfig(
  port: number,
  profileId: string,
  token = PRIVATE_TOKEN,
  profileRevision = 2,
): OpenClawConfig {
  return {
    agents: {
      entries: {
        [`opsys-agent-${profileId}`]: { opsysRuntimeAdmission: { profileId, profileRevision } },
      },
    },
    mcp: {
      servers: {
        [`opsys_runtime_${profileId}`]: {
          url: `http://127.0.0.1:${port}/mcp/runtime/${profileId}`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${token}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
      },
    },
  } as OpenClawConfig;
}

function fakeProvider(
  counter: { calls: number },
  onResult?: (message: AssistantMessage) => void,
): StreamFn {
  return async (_model: Model, _context: Context) => {
    counter.calls += 1;
    const message: AssistantMessage = {
      role: "assistant",
      content: [],
      api: "openai-completions",
      provider: "openai",
      model: "integration-fake",
      usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
      stopReason: "stop",
      timestamp: 1,
    };
    return {
      result: async () => {
        onResult?.(message);
        return message;
      },
      async *[Symbol.asyncIterator]() {},
    };
  };
}

describe("OPSYS runtime admission against the real Python MCP CLI", () => {
  it("reserves, dispatches once, reconciles real usage, and denies low budget and replay", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-runtime-mcp-it-"));
    tempDirs.push(home);
    const env = isolatedEnvironment(home);
    await runPython(python, [FIXTURE, "prepare"], env);

    const port = await reserveEphemeralPort();
    const server = spawn(
      python,
      ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
      { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    children.push(server);
    await waitUntilListening(server);

    const controller = new AbortController();
    const successCalls = { calls: 0 };
    const success = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-success-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(successCalls),
    });
    const context: Context = { messages: [] };
    const model = makeProviderModelFixture({
      id: "integration-fake",
      provider: "openai",
      api: "openai-completions",
      baseUrl: "https://api.openai.com/v1",
      contextWindow: 64,
      maxTokens: 16,
    });
    const stream = await success(model, context, { signal: controller.signal });
    const message = await stream.result();
    expect(message.usage?.totalTokens).toBe(3);
    expect(successCalls.calls).toBe(1);

    const replayCalls = { calls: 0 };
    const replay = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-success-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(replayCalls),
    });
    await expect(replay(model, context, { signal: controller.signal })).rejects.toThrow(
      "cycle déjà admis",
    );
    expect(replayCalls.calls).toBe(0);

    const wrongTokenCalls = { calls: 0 };
    const wrongToken = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok", PUBLIC_TOKEN),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-wrong-token-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(wrongTokenCalls),
    });
    await expect(wrongToken(model, context, { signal: controller.signal })).rejects.toThrow();
    expect(wrongTokenCalls.calls).toBe(0);

    const lowBudgetCalls = { calls: 0 };
    const lowBudget = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-low"),
      agentId: "opsys-agent-it-runtime-low",
      runId: "integration-low-budget-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(lowBudgetCalls),
    });
    await expect(lowBudget(model, context, { signal: controller.signal })).rejects.toThrow(
      "budget agent insuffisant",
    );
    expect(lowBudgetCalls.calls).toBe(0);

    // Fictif: real private MCP + canonical SQL; authority refuses before fake provider invocation.
    const deniedCalls = { calls: 0 };
    const authorityFailure = new Error("synthetic authority withdrawn before dispatch");
    const denied = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-pre-dispatch-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(deniedCalls),
      beforeProviderDispatch: async () => {
        throw authorityFailure;
      },
    });
    await expect(denied(model, context)).rejects.toBe(authorityFailure);
    expect(deniedCalls.calls).toBe(0);
    const deniedReplay = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-pre-dispatch-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(deniedCalls),
    });
    await expect(deniedReplay(model, context)).rejects.toThrow("cycle déjà admis");
    expect(deniedCalls.calls).toBe(0);

    const abortedCalls = { calls: 0 };
    const abort = new AbortController();
    const aborted = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-abort-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(abortedCalls),
      signal: abort.signal,
      beforeProviderDispatch: async () => {
        abort.abort();
      },
    });
    await expect(aborted(model, context)).rejects.toThrow();
    expect(abort.signal.aborted).toBe(true);
    expect(abortedCalls.calls).toBe(0);

    await stopChild(server);
    const inspected = JSON.parse(await runPython(python, [FIXTURE, "inspect"], env)) as {
      reservations: Array<{
        agent_id: string;
        execution_id: string;
        cycle_id: string;
        statut: string;
        tokens_plafond: number;
        tokens_reels: number | null;
      }>;
      usage_tokens: number;
    };
    expect(inspected.reservations).toEqual([
      expect.objectContaining({
        agent_id: "it-runtime-ok",
        execution_id: "integration-abort-run-001",
        cycle_id: "integration-abort-run-001:0:0",
        statut: "liberee",
        tokens_reels: null,
      }),
      expect.objectContaining({
        agent_id: "it-runtime-ok",
        execution_id: "integration-pre-dispatch-run-001",
        cycle_id: "integration-pre-dispatch-run-001:0:0",
        statut: "liberee",
        tokens_reels: null,
      }),
      expect.objectContaining({
        agent_id: "it-runtime-ok",
        execution_id: "integration-success-run-001",
        cycle_id: "integration-success-run-001:0:0",
        statut: "conciliee",
        tokens_reels: 3,
      }),
    ]);
    expect(inspected.usage_tokens).toBe(3);
  }, 30_000);

  it("reconciles known provider usage after the run is aborted at the response boundary", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-runtime-known-usage-abort-it-"));
    tempDirs.push(home);
    const env = isolatedEnvironment(home);
    await runPython(python, [FIXTURE, "prepare"], env);

    const port = await reserveEphemeralPort();
    const server = spawn(
      python,
      ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
      { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    children.push(server);
    await waitUntilListening(server);

    const controller = new AbortController();
    const providerCalls = { calls: 0 };
    let providerResults = 0;
    const gate = createOpsysRuntimeAdmissionStreamFn({
      config: runtimeConfig(port, "it-runtime-ok"),
      agentId: "opsys-agent-it-runtime-ok",
      runId: "integration-known-usage-abort-run-001",
      getCandidateIndex: () => 0,
      signal: controller.signal,
      streamFn: fakeProvider(providerCalls, (message) => {
        providerResults += 1;
        expect(message.usage?.totalTokens).toBe(3);
        controller.abort(new Error("synthetic cancellation after known provider response"));
      }),
    });
    const model = makeProviderModelFixture({
      id: "integration-fake",
      provider: "openai",
      api: "openai-completions",
      baseUrl: "http://127.0.0.1:1/fictif-no-provider-network",
      contextWindow: 64,
      maxTokens: 16,
    });
    const stream = await gate(model, { messages: [] }, { signal: controller.signal });
    const message = await stream.result();

    expect(controller.signal.aborted).toBe(true);
    expect(providerCalls.calls).toBe(1);
    expect(providerResults).toBe(1);
    expect(message.usage?.totalTokens).toBe(3);

    await stopChild(server);
    const inspected: unknown = JSON.parse(await runPython(python, [FIXTURE, "inspect"], env));
    expect(inspected).toEqual({
      reservations: [
        expect.objectContaining({
          agent_id: "it-runtime-ok",
          execution_id: "integration-known-usage-abort-run-001",
          cycle_id: "integration-known-usage-abort-run-001:0:0",
          statut: "conciliee",
          tokens_reels: 3,
        }),
      ],
      usage_tokens: 3,
    });
  }, 30_000);

  it("blocks a configured tool revoked after the host loaded its older profile revision", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-runtime-revision-it-"));
    tempDirs.push(home);
    const env = isolatedEnvironment(home);
    await runPython(python, [FIXTURE, "prepare"], env);
    await runPython(python, [FIXTURE, "revoke-tool"], env);

    const port = await reserveEphemeralPort();
    const server = spawn(
      python,
      ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
      { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    children.push(server);
    await waitUntilListening(server);

    const staleConfig = runtimeConfig(port, "it-runtime-revision", PRIVATE_TOKEN, 2);
    const controller = new AbortController();
    const staleProvider = { calls: 0 };
    const staleStream = createOpsysRuntimeAdmissionStreamFn({
      config: staleConfig,
      agentId: "opsys-agent-it-runtime-revision",
      runId: "integration-stale-profile-run-001",
      getCandidateIndex: () => 0,
      streamFn: fakeProvider(staleProvider),
    });
    let staleAdmissionRefused = false;
    try {
      const model = makeProviderModelFixture({
        id: "integration-fake",
        provider: "openai",
        api: "openai-completions",
        baseUrl: "https://api.openai.com/v1",
        contextWindow: 64,
        maxTokens: 16,
      });
      const stream = await staleStream(model, { messages: [] }, { signal: controller.signal });
      await stream.result();
    } catch {
      staleAdmissionRefused = true;
    }

    let fakeHandlerDispatches = 0;
    const policy = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: staleConfig },
    });
    if (!policy.blocked) {
      fakeHandlerDispatches += 1;
    }

    expect({
      staleAdmissionRefused,
      staleProviderDispatches: staleProvider.calls,
      toolPolicyBlocked: policy.blocked,
      fakeHandlerDispatches,
    }).toEqual({
      staleAdmissionRefused: true,
      staleProviderDispatches: 0,
      toolPolicyBlocked: true,
      fakeHandlerDispatches: 0,
    });

    const currentConfig = runtimeConfig(port, "it-runtime-revision", PRIVATE_TOKEN, 3);
    const removedTool = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: currentConfig },
    });
    expect(removedTool.blocked).toBe(true);

    const currentTool = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: currentConfig },
    });
    expect(currentTool.blocked, JSON.stringify(currentTool)).toBe(false);

    const wrongNamespace = await runBeforeToolCallHook({
      toolName: "opsys_m8__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: currentConfig },
    });
    expect(wrongNamespace.blocked).toBe(true);

    const missingRevision = runtimeConfig(port, "it-runtime-revision");
    missingRevision.agents!.entries![
      "opsys-agent-it-runtime-revision"
    ]!.opsysRuntimeAdmission!.profileRevision = undefined;
    const legacyBinding = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: missingRevision },
    });
    expect(legacyBinding.blocked).toBe(true);

    await runPython(python, [FIXTURE, "deactivate-profile"], env);
    const inactiveProfile = runtimeConfig(port, "it-runtime-revision", PRIVATE_TOKEN, 4);
    const inactiveTool = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: inactiveProfile },
    });
    expect(inactiveTool.blocked).toBe(true);

    const expiredPositive = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "opsys-agent-it-runtime-revision", config: currentConfig },
    });
    expect(expiredPositive.blocked).toBe(true);

    const unavailable = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: {
        agentId: "opsys-agent-it-runtime-revision",
        config: runtimeConfig(1, "it-runtime-revision", PRIVATE_TOKEN, 4),
      },
    });
    expect(unavailable.blocked).toBe(true);

    const unprofiled = await runBeforeToolCallHook({
      toolName: "opsys_m9__m9_lire_etat_consolide",
      params: { fictif: true },
      ctx: { agentId: "m09-historique", config: {} as OpenClawConfig },
    });
    expect(unprofiled.blocked).toBe(false);
  }, 30_000);

  for (const loseResponse of [false, true]) {
    it(
      loseResponse
        ? "does not dispatch a fallback after known usage and a lost real reconciliation response"
        : "returns the first candidate after real fallback-gate reconciliation",
      async () => {
        const python = requiredPython();
        const home = await mkdtemp(resolve(tmpdir(), "opsys-runtime-fallback-known-usage-it-"));
        tempDirs.push(home);
        const env = isolatedEnvironment(home);
        await runPython(python, [FIXTURE, "prepare"], env);
        const port = await reserveEphemeralPort();
        const server = spawn(
          python,
          ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
          { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] },
        );
        children.push(server);
        await waitUntilListening(server);
        const proxy = await startReconciliationProxy(port, loseResponse);
        let primary: unknown;
        let cleanupError: unknown;
        try {
          let providerCalls = 0;
          let providerResults = 0;
          let candidateCalls = 0;
          let resultError: unknown;
          let returnedTokens: number | undefined;
          const runId = `integration-known-usage-fallback-${loseResponse ? "loss" : "nominal"}`;
          try {
            const result = await runWithModelFallback<AssistantMessage>({
              cfg: undefined,
              provider: "fixture-primary",
              model: "fixture-model",
              manifestPlugins: [],
              fallbacksOverride: ["fixture-next/fixture-model"],
              skipAuthProfileRuntime: true,
              run: async (providerName, modelName) => {
                const index = candidateCalls++;
                if (index > 1) {
                  throw new Error("Unexpected third candidate in bounded integration fixture");
                }
                const model = makeProviderModelFixture({
                  id: modelName,
                  provider: providerName,
                  api: "openai-completions",
                  baseUrl: "http://127.0.0.1:1/fictif-no-provider-network",
                  contextWindow: 64,
                  maxTokens: 16,
                });
                const provider: StreamFn = async () => {
                  providerCalls += 1;
                  const message: AssistantMessage = {
                    role: "assistant",
                    content: [],
                    api: "openai-completions",
                    provider: providerName,
                    model: modelName,
                    usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
                    stopReason: "stop",
                    timestamp: 1,
                  };
                  return {
                    result: async () => {
                      providerResults += 1;
                      return message;
                    },
                    async *[Symbol.asyncIterator]() {},
                  };
                };
                const gate = createOpsysRuntimeAdmissionStreamFn({
                  config: runtimeConfig(proxy.port, "it-runtime-ok"),
                  agentId: "opsys-agent-it-runtime-ok",
                  runId,
                  getCandidateIndex: () => index,
                  streamFn: provider,
                });
                return await (await gate(model, { messages: [] }, { maxTokens: 16 })).result();
              },
            });
            returnedTokens = result.result.usage?.totalTokens;
          } catch (error) {
            resultError = error;
          }
          await stopChild(server);
          const inspected: unknown = JSON.parse(await runPython(python, [FIXTURE, "inspect"], env));
          expect(proxy.errors).toEqual([]);
          expect(proxy.droppedResponses()).toBe(loseResponse ? 1 : 0);
          expect(candidateCalls).toBe(1);
          expect(providerCalls).toBe(1);
          expect(providerResults).toBe(1);
          if (loseResponse && resultError !== undefined) {
            expect(hasModelFallbackStop(resultError)).toBe(true);
          } else {
            expect(resultError).toBeUndefined();
            expect(returnedTokens).toBe(3);
          }
          expect(inspected).toEqual({
            reservations: [
              expect.objectContaining({
                agent_id: "it-runtime-ok",
                execution_id: runId,
                cycle_id: `${runId}:0:0`,
                statut: "conciliee",
                tokens_reels: 3,
              }),
            ],
            usage_tokens: 3,
          });
        } catch (error) {
          primary = error;
        } finally {
          try {
            await proxy.close();
          } catch (error) {
            cleanupError = error;
          }
        }
        if (primary !== undefined) {
          throw primary instanceof Error
            ? primary
            : new Error("QA fallback integration failed", { cause: primary });
        }
        if (cleanupError !== undefined) {
          throw cleanupError instanceof Error
            ? cleanupError
            : new Error("QA reconciliation proxy cleanup failed", { cause: cleanupError });
        }
      },
      60_000,
    );
  }
});
