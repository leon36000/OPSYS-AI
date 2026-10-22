import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { AssistantMessage, Context, Model } from "openclaw/plugin-sdk/llm";
import { afterEach, expect, it } from "vitest";
import { resolveConfigEnvVars } from "../../config/env-substitution.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { OpenClawSchema } from "../../config/zod-schema.js";
import { createSessionMcpRuntime } from "../agent-bundle-mcp-runtime.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../test-helpers/usage-fixtures.js";
import { createOpsysRuntimeAdmissionStreamFn } from "./opsys-runtime-admission.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-base-runtime-admission-fixture.py");
const DEP = "m09-strategic-intelligence";
const PROFILE = `base-${DEP}`;
const children: ReturnType<typeof spawn>[] = [];
const homes: string[] = [];

function exited(child: ReturnType<typeof spawn>): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function stop(child: ReturnType<typeof spawn>): Promise<void> {
  if (exited(child)) {
    return;
  }
  const wait = new Promise<void>((resolveExit) => {
    child.once("exit", () => resolveExit());
  });
  child.kill("SIGTERM");
  await wait;
}

afterEach(async () => {
  for (const child of children.splice(0)) {
    await stop(child);
  }
  await Promise.all(homes.splice(0).map((home) => rm(home, { recursive: true, force: true })));
});

function pythonRun(python: string, args: string[], env: NodeJS.ProcessEnv): Promise<string> {
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
        reject(new Error(`Python QA fixture exited ${code}: ${stderr.slice(-2_000)}`));
      }
    });
  });
}

async function port(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolveListen());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("QA loopback port unavailable");
  }
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  return address.port;
}

function ready(child: ReturnType<typeof spawn>): Promise<void> {
  return new Promise((resolveReady, reject) => {
    let output = "";
    let done = false;
    const finish = (error?: Error) => {
      if (done) {
        return;
      }
      done = true;
      clearTimeout(timeout);
      child.removeListener("exit", onExit);
      child.removeListener("error", onError);
      if (error) {
        reject(error);
      } else {
        resolveReady();
      }
    };
    const onExit = (code: number | null) =>
      finish(new Error(`Python MCP exited before ready (${code})`));
    const onError = (error: Error) => finish(error);
    const timeout = setTimeout(
      () => finish(new Error(`Python MCP readiness timeout: ${output.slice(-2_000)}`)),
      15_000,
    );
    const collect = (chunk: string) => {
      output += chunk;
      if (output.includes("Uvicorn running on")) {
        finish();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", collect);
    child.stderr?.setEncoding("utf8").on("data", collect);
    child.once("exit", onExit);
    child.once("error", onError);
  });
}

function provider(counter: { calls: number }): StreamFn {
  return async (_model: Model, _context: Context) => {
    counter.calls += 1;
    const message: AssistantMessage = {
      role: "assistant",
      content: [],
      api: "openai-completions",
      provider: "openai",
      model: "qa-no-provider",
      usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
      stopReason: "stop",
      timestamp: 1,
    };
    return { result: async () => message, async *[Symbol.asyncIterator]() {} };
  };
}

it("admits an exported durable base agent through native HTTP, reconciles once and refuses replay and budget", async () => {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the real Python MCP integration test");
  }
  const home = await mkdtemp(resolve(tmpdir(), "opsys-base-http-"));
  homes.push(home);
  const evidence = process.env.OPSYS_BASE_RUNTIME_EVIDENCE ?? resolve(home, "evidence");
  await mkdir(evidence, { recursive: true });
  for (const directory of ["config", "cache", "data", "tmp"]) {
    await mkdir(resolve(home, directory));
  }
  const env: NodeJS.ProcessEnv = {
    HOME: home,
    OPSYS_HOME: home,
    XDG_CONFIG_HOME: resolve(home, "config"),
    XDG_CACHE_HOME: resolve(home, "cache"),
    XDG_DATA_HOME: resolve(home, "data"),
    TMPDIR: resolve(home, "tmp"),
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    OPSYS_CONTEXT_MCP_JETON: "qa-base-private-token-not-production-2026",
    OPSYS_MCP_JETON: "qa-base-public-token-not-production-2026",
    OPSYS_BASE_RUNTIME_EVIDENCE: evidence,
  };
  const localPort = await port();
  await pythonRun(python, [FIXTURE, "prepare", String(localPort)], env);
  const generated = JSON.parse(await readFile(resolve(home, "base-runtime-export.json"), "utf8"));
  expect(generated.profile).toMatchObject({
    id: PROFILE,
    departement: DEP,
    actif: true,
    revision: 2,
    budget_jour: 32,
  });
  const config: OpenClawConfig = OpenClawSchema.parse(
    resolveConfigEnvVars({ agents: generated.agents, mcp: generated.mcp }, env),
  );
  expect(config.agents?.entries?.[DEP]?.opsysRuntimeAdmission).toEqual({
    profileId: PROFILE,
    profileRevision: 2,
  });
  const nativeServer = config.mcp?.servers?.[`opsys_runtime_${PROFILE}`];
  expect(nativeServer?.url).toBe(`http://127.0.0.1:${localPort}/mcp/runtime/${PROFILE}`);
  const server = spawn(python, [FIXTURE, "serve", String(localPort)], {
    cwd: REPO,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(server);
  await ready(server);
  const provenance = JSON.parse(
    await readFile(resolve(evidence, "PYTHON-SERVER-PROVENANCE.json"), "utf8"),
  );
  expect(provenance["opsys.admission_agents"].path).toBe(
    resolve(REPO, "src/opsys/admission_agents.py"),
  );
  expect(provenance["opsys.capacites"].path).toBe(resolve(REPO, "src/opsys/capacites.py"));
  const calls = { calls: 0 };
  const streamFor = (runId: string) =>
    createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: DEP,
      runId,
      getCandidateIndex: () => 0,
      streamFn: provider(calls),
    });
  const model = makeProviderModelFixture({
    id: "qa-no-provider",
    provider: "openai",
    api: "openai-completions",
    baseUrl: "https://no-provider-qa.invalid/v1",
    contextWindow: 256,
    maxTokens: 16,
  });
  const context: Context = { messages: [] };
  const stream = await streamFor("base-http-success-qa-001")(model, context);
  const message = await stream.result();
  expect(message.usage?.totalTokens).toBe(3);
  expect(calls.calls).toBe(1);
  await expect(streamFor("base-http-success-qa-001")(model, context)).rejects.toThrow(
    "cycle déjà admis",
  );
  expect(calls.calls).toBe(1);
  await expect(streamFor("base-http-budget-qa-002")(model, context)).rejects.toThrow(
    "budget agent insuffisant",
  );
  expect(calls.calls).toBe(1);
  const business = createSessionMcpRuntime({
    sessionId: "base-common-native-qa",
    sessionKey: `agent:${DEP}:base-common-native-qa`,
    workspaceDir: home,
    manifestRegistry: { plugins: [] },
    cfg: config,
  });
  let commonBudget: unknown;
  let revokedCommon: unknown;
  try {
    const read = async () => {
      const result = await business.callTool("opsys_m9", "opsys_etat_budget", {});
      return JSON.parse(String(result.content.find((item) => item.type === "text")?.text));
    };
    commonBudget = await read();
    await writeFile(
      resolve(evidence, "COMMON-PRIMARY.json"),
      JSON.stringify(commonBudget, null, 2),
    );
    expect(commonBudget).toMatchObject({ ok: true, resultat: [{ departement: DEP }] });
    await pythonRun(python, [FIXTURE, "deactivate"], env);
    revokedCommon = await read();
    expect(revokedCommon).toMatchObject({ ok: false, erreur: "admission_profil_refusee" });
  } finally {
    await business.dispose();
  }
  await writeFile(
    resolve(evidence, "NATIVE-BASE-COMMON-LEDGER.json"),
    JSON.stringify(
      {
        profile: PROFILE,
        revision: 2,
        commonBudget,
        revokedCommon,
        checks: [
          "real Core metadata to Python SQL dispatch",
          "same runtime refuses current SQL deactivation",
        ],
      },
      null,
      2,
    ),
  );
  await stop(server);
  const state = JSON.parse(await pythonRun(python, [FIXTURE, "inspect"], env));
  expect(state.reservations).toEqual([
    expect.objectContaining({
      agent_id: PROFILE,
      execution_id: "base-http-success-qa-001",
      cycle_id: "base-http-success-qa-001:0:0",
      statut: "conciliee",
      tokens_reels: 3,
    }),
  ]);
  expect(state.reservations[0].tokens_plafond).toBeGreaterThan(0);
  expect(state.reservations[0].tokens_plafond).toBeLessThanOrEqual(32);
  expect(state.usage_tokens).toBe(3);
  expect(state.reservations[0].tokens_plafond).toBeGreaterThan(32 - state.usage_tokens);
  await writeFile(
    resolve(evidence, "NATIVE-BASE-BUDGET-LEDGER.json"),
    JSON.stringify(
      {
        controls: [
          "base provision/export/native admission/reconciliation",
          "cycle replay refused",
          "remaining budget refusal before provider",
        ],
        department: DEP,
        profile_id: PROFILE,
        profile_revision: 2,
        fake_provider_calls: calls.calls,
        real_provider_calls: 0,
        token_usage_is_qa_not_invoice: true,
        state,
      },
      null,
      2,
    ),
  );
}, 45_000);
