// OPSYS business-engine supervisor (OPSYS-AI PLAN T0.10): launch, health, restart with backoff,
// journal relay, token secrecy and shutdown. No real process, timer or network: the process
// supervisor, the health probe and the sleeps are fakes driven step by step by the test.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import {
  isSecretValueRegisteredForRedaction,
  registerSecretValueForRedaction,
} from "../logging/secret-redaction-registry.js";
import type {
  ManagedRun,
  ProcessSupervisor,
  RunExit,
  SpawnInput,
} from "../process/supervisor/types.js";
import type { OpsysMetierConfig } from "./opsys-metier-config.js";
import type { OpsysMetierStatus } from "./opsys-metier-status.js";
import {
  createOpsysMetierSupervisor,
  startOpsysMetierSidecar,
  type OpsysMetierSupervisorDeps,
} from "./opsys-metier-supervisor.js";

const TOKEN = "jeton-de-test-suffisamment-long-0123456789";
const tempDirs = useAutoCleanupTempDirTracker(afterEach);

const CONFIG: OpsysMetierConfig = {
  cwd: "/opt/opsys",
  command: ["uv", "run", "opsys-mcp", "--http", "--hote", "127.0.0.1", "--port", "8765"],
  healthUrl: "http://127.0.0.1:8765/sante",
  env: { OPSYS_HOME: "/var/lib/opsys" },
  readyTimeoutMs: 60_000,
  probeIntervalMs: 10_000,
  maxProbeFailures: 3,
  maxRestarts: 3,
};

const NO_JITTER_BACKOFF = { initialMs: 1_000, maxMs: 8_000, factor: 2, jitter: 0 };

function runExit(
  code: number | null,
  signal: NodeJS.Signals | null,
  reason: RunExit["reason"],
): RunExit {
  return {
    reason,
    exitCode: code,
    exitSignal: signal,
    durationMs: 1,
    stdout: "",
    stderr: "",
    timedOut: false,
    noOutputTimedOut: false,
  };
}

/** Values the fake hands to the test in the order the supervisor produced them. */
function createMailbox<T>() {
  const items: T[] = [];
  const waiting: Array<(item: T) => void> = [];
  return {
    push(item: T): void {
      const waiter = waiting.shift();
      if (waiter) {
        waiter(item);
      } else {
        items.push(item);
      }
    },
    next(): Promise<T> {
      const item = items.shift();
      if (item !== undefined) {
        return Promise.resolve(item);
      }
      return new Promise<T>((resolve) => {
        waiting.push(resolve);
      });
    },
  };
}

type FakeRun = {
  input: SpawnInput;
  managed: ManagedRun;
  settled: boolean;
  cancelled: boolean;
  settle: (exit: RunExit) => void;
};

function childInput(run: FakeRun | undefined): Extract<SpawnInput, { mode: "child" }> {
  if (!run) {
    throw new Error("expected a launched run");
  }
  const { input } = run;
  if (input.mode !== "child") {
    throw new Error("expected a child process input");
  }
  return input;
}

type FakeLogFn = (message: string, meta?: Record<string, unknown>) => void;

function createFixture(
  options: {
    config?: Partial<OpsysMetierConfig>;
    backoff?: OpsysMetierSupervisorDeps["backoff"];
    stableRunMs?: number;
    env?: OpsysMetierSupervisorDeps["env"];
  } = {},
) {
  let now = 0;
  const runs: FakeRun[] = [];
  const scopes: string[] = [];
  const closed: string[] = [];
  const spawnFailures: Error[] = [];
  const published: Array<OpsysMetierStatus | undefined> = [];
  const sleeps = createMailbox<{ ms: number; release: () => void }>();
  const gaveUp = createDeferred();
  const log = {
    info: vi.fn<FakeLogFn>(),
    warn: vi.fn<FakeLogFn>(),
    error: vi.fn<FakeLogFn>(() => {
      gaveUp.resolve();
    }),
  };
  const probe = vi.fn<(url: string, signal: AbortSignal) => Promise<boolean>>(async () => true);

  const cancelRun = (run: FakeRun): void => {
    run.cancelled = true;
    run.settle(runExit(null, "SIGTERM", "manual-cancel"));
  };
  const supervisor: ProcessSupervisor = {
    acquireScopeCleanup(scopeKey) {
      scopes.push(scopeKey);
      return async () => {
        supervisor.cancelScope(scopeKey);
        await Promise.all(runs.map((run) => run.managed.wait()));
        closed.push(scopeKey);
      };
    },
    async spawn(input) {
      input.assertCurrent?.();
      const failure = spawnFailures.shift();
      if (failure) {
        throw failure;
      }
      const index = runs.length;
      const exit = createDeferred<RunExit>();
      const run: FakeRun = {
        input,
        settled: false,
        cancelled: false,
        settle: (value) => {
          if (!run.settled) {
            run.settled = true;
            exit.resolve(value);
          }
        },
        managed: {
          activity: { resultSettled: false, lastOutputAtMs: 0 },
          runId: `run-${String(index)}`,
          startedAtMs: 0,
          pid: 4200 + index,
          wait: async () => await exit.promise,
          cancel: () => {
            cancelRun(run);
          },
        },
      };
      runs.push(run);
      return run.managed;
    },
    cancel(runId) {
      for (const run of runs) {
        if (run.managed.runId === runId) {
          cancelRun(run);
        }
      }
    },
    cancelScope() {
      for (const run of runs) {
        cancelRun(run);
      }
    },
  };

  const sleep = (ms: number, signal: AbortSignal): Promise<void> =>
    new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        reject(new Error("aborted"));
      };
      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener("abort", onAbort, { once: true });
      sleeps.push({
        ms,
        release: () => {
          signal.removeEventListener("abort", onAbort);
          now += ms;
          resolve();
        },
      });
    });

  const deps: OpsysMetierSupervisorDeps = {
    supervisor,
    log,
    probe,
    sleep,
    nowMs: () => now,
    backoff: options.backoff ?? NO_JITTER_BACKOFF,
    stableRunMs: options.stableRunMs ?? 5_000,
    publishStatus: (status) => {
      published.push(status);
    },
    env: options.env ?? { PATH: "/usr/bin" },
  };
  const instance = createOpsysMetierSupervisor({
    config: { ...CONFIG, ...options.config },
    token: TOKEN,
    tokenSource: "env",
    deps,
  });
  return {
    instance,
    deps,
    supervisor,
    runs,
    scopes,
    closed,
    spawnFailures,
    published,
    sleeps,
    gaveUp,
    log,
    probe,
  };
}

describe("OPSYS business engine supervisor", () => {
  it("launches the engine in its folder with the shared token and reports it healthy", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValueOnce(false);

    fixture.instance.start();
    const startupNap = await fixture.sleeps.next();

    expect(startupNap.ms).toBe(500);
    expect(fixture.instance.status()).toMatchObject({
      state: "starting",
      pid: 4200,
      restarts: 0,
      healthUrl: CONFIG.healthUrl,
      tokenSource: "env",
    });
    startupNap.release();
    const monitoringNap = await fixture.sleeps.next();

    expect(monitoringNap.ms).toBe(10_000);
    expect(fixture.instance.status()).toMatchObject({
      state: "running",
      pid: 4200,
      lastHealthyAtMs: 500,
    });
    const input = childInput(fixture.runs[0]);
    expect(input.argv).toStrictEqual(CONFIG.command);
    expect(input.cwd).toBe("/opt/opsys");
    expect(input.env).toStrictEqual({
      PATH: "/usr/bin",
      PYTHONUNBUFFERED: "1",
      OPSYS_HOME: "/var/lib/opsys",
      OPSYS_MCP_JETON: TOKEN,
    });
    expect(input.stdinMode).toBe("pipe-closed");
    expect(input.captureOutput).toBe(false);
    expect(input.scopeKey).toBe(fixture.scopes[0]);
    expect(fixture.probe).toHaveBeenCalledWith(CONFIG.healthUrl, expect.any(AbortSignal));
    await fixture.instance.stop();
  });

  it("notifies on first and periodic healthy probes without waiting and withdraws the client on stop", async () => {
    const operatorToken = "operator-cron-token-that-is-long-enough-123456";
    const fixture = createFixture({
      env: { PATH: "/usr/bin", OPSYS_CRON_OPERATEUR_JETON: operatorToken },
    });
    const callbackGate = createDeferred<void>();
    fixture.deps.onHealthy = vi.fn(() => callbackGate.promise);

    fixture.instance.start();
    const firstProbeSleep = await fixture.sleeps.next();
    expect(fixture.instance.status().state).toBe("running");
    expect(fixture.deps.onHealthy).toHaveBeenCalledOnce();
    expect(fixture.instance.getPrivateCronClient()).toBeDefined();

    firstProbeSleep.release();
    await fixture.sleeps.next();
    expect(fixture.deps.onHealthy).toHaveBeenCalledTimes(2);
    await fixture.instance.stop();
    expect(fixture.instance.getPrivateCronClient()).toBeUndefined();
    callbackGate.resolve();
  });

  it("relays the engine's output line by line to the journal and masks the token", async () => {
    const fixture = createFixture();
    fixture.instance.start();
    await fixture.sleeps.next();
    const { onStdout, onStderr } = childInput(fixture.runs[0]);

    onStdout?.("INFO:     Started server");
    onStdout?.(" process\r\nINFO:     Waiting\n\n");
    onStderr?.(`Authorization: Bearer ${TOKEN} refused\n`);
    onStdout?.("last line without a newline");
    fixture.runs[0]?.settle(runExit(0, null, "exit"));
    await fixture.sleeps.next();

    expect(fixture.log.info).toHaveBeenCalledWith("INFO:     Started server process", {
      stream: "stdout",
    });
    expect(fixture.log.info).toHaveBeenCalledWith("INFO:     Waiting", { stream: "stdout" });
    expect(fixture.log.info).toHaveBeenCalledWith("Authorization: Bearer *** refused", {
      stream: "stderr",
    });
    expect(fixture.log.info).toHaveBeenCalledWith("last line without a newline", {
      stream: "stdout",
    });
    const everything = JSON.stringify([
      fixture.log.info.mock.calls,
      fixture.log.warn.mock.calls,
      fixture.log.error.mock.calls,
      fixture.published,
    ]);
    expect(everything).not.toContain(TOKEN);
    await fixture.instance.stop();
  });

  it("keeps child secrets masked after global eviction and drops oversized lines before truncation can leak them", async () => {
    const contextToken = 'context-"quoted\\path-secret-value-012345';
    const operatorToken = "operator+percent%secret/value-012345";
    const configuredProviderSecret = "provider-secret-519-0123456789";
    const providerEnv = Object.fromEntries(
      Array.from({ length: 520 }, (_, index) => [
        `LITELLM_${String(index)}_API_KEY`,
        `provider-secret-${String(index)}-0123456789`,
      ]),
    );
    const fixture = createFixture({
      config: { env: providerEnv },
      env: {
        PATH: "/usr/bin",
        OPSYS_CONTEXT_MCP_JETON: contextToken,
        OPSYS_CRON_OPERATEUR_JETON: operatorToken,
      },
    });

    fixture.instance.start();
    await fixture.sleeps.next();
    expect(childInput(fixture.runs[0]).env).toMatchObject({
      OPSYS_MCP_JETON: TOKEN,
      OPSYS_CONTEXT_MCP_JETON: contextToken,
      OPSYS_CRON_OPERATEUR_JETON: operatorToken,
      LITELLM_519_API_KEY: configuredProviderSecret,
    });
    for (let index = 0; index < 600; index += 1) {
      registerSecretValueForRedaction(`unrelated-global-secret-${String(index)}-0123456789`);
    }
    expect(isSecretValueRegisteredForRedaction(contextToken)).toBe(false);
    expect(isSecretValueRegisteredForRedaction(operatorToken)).toBe(false);
    expect(isSecretValueRegisteredForRedaction(TOKEN)).toBe(false);

    const { onStdout, onStderr } = childInput(fixture.runs[0]);
    onStdout?.(`raw:${contextToken}|json:${JSON.stringify(contextToken).slice(1, -1)}|${TOKEN}\n`);
    onStderr?.(
      `uri:${encodeURIComponent(operatorToken)}|raw:${operatorToken}|provider:${configuredProviderSecret}\n`,
    );
    onStdout?.("x".repeat(3_990));
    onStdout?.(`${contextToken} suffix\n`);

    expect(fixture.log.info).toHaveBeenCalledWith("raw:***|json:***|***", { stream: "stdout" });
    expect(fixture.log.info).toHaveBeenCalledWith("uri:***|raw:***|provider:***", {
      stream: "stderr",
    });
    expect(fixture.log.info).toHaveBeenCalledWith("[oversized line omitted]", { stream: "stdout" });
    const everything = JSON.stringify([
      fixture.log.info.mock.calls,
      fixture.log.warn.mock.calls,
      fixture.log.error.mock.calls,
    ]);
    expect(everything).not.toContain(contextToken);
    expect(everything).not.toContain(operatorToken);
    expect(everything).not.toContain(TOKEN);
    expect(everything).not.toContain(configuredProviderSecret);
    expect(everything).not.toContain(contextToken.slice(0, 10));
    await fixture.instance.stop();
  });

  it("restarts a crashing engine with a growing backoff, then gives up and reports failure", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValue(false);
    const delays: number[] = [];

    fixture.instance.start();
    for (const index of [0, 1, 2]) {
      await fixture.sleeps.next();
      fixture.runs[index]?.settle(runExit(1, null, "exit"));
      const backoffNap = await fixture.sleeps.next();
      delays.push(backoffNap.ms);
      expect(fixture.instance.status()).toMatchObject({
        state: "restarting",
        restarts: index + 1,
        error: "engine exited with code 1",
      });
      backoffNap.release();
    }
    await fixture.sleeps.next();
    fixture.runs[3]?.settle(runExit(1, null, "exit"));
    await fixture.gaveUp.promise;

    expect(delays).toStrictEqual([1_000, 2_000, 4_000]);
    expect(fixture.instance.status()).toMatchObject({
      state: "failed",
      restarts: 3,
      error: "gave up after 3 consecutive restarts (last: engine exited with code 1)",
    });
    expect(fixture.runs).toHaveLength(4);
    await fixture.instance.stop();
  });

  it("starts the backoff over once the engine had been healthy for a while", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValueOnce(false).mockResolvedValue(true);

    fixture.instance.start();
    await fixture.sleeps.next();
    fixture.runs[0]?.settle(runExit(1, null, "exit"));
    const first = await fixture.sleeps.next();
    expect(first.ms).toBe(1_000);
    first.release();
    const firstMonitoring = await fixture.sleeps.next();
    firstMonitoring.release();
    await fixture.sleeps.next();
    fixture.runs[1]?.settle(runExit(137, null, "exit"));
    const second = await fixture.sleeps.next();

    expect(second.ms).toBe(1_000);
    expect(fixture.instance.status()).toMatchObject({ state: "restarting", restarts: 2 });
    await fixture.instance.stop();
  });

  it("does not count a slow startup followed by an immediate crash as stable health", async () => {
    const fixture = createFixture();
    const delays: number[] = [];
    fixture.instance.start();
    try {
      for (const index of [0, 1]) {
        // The probe stays unready for six seconds, beyond the five-second stability threshold.
        // A single good answer then ends the startup, but proves no healthy interval.
        fixture.probe.mockReset();
        for (let probe = 0; probe < 12; probe += 1) {
          fixture.probe.mockResolvedValueOnce(false);
        }
        fixture.probe.mockResolvedValue(true);
        for (let probe = 0; probe < 12; probe += 1) {
          (await fixture.sleeps.next()).release();
        }
        const monitoring = await fixture.sleeps.next();
        expect(monitoring.ms).toBe(CONFIG.probeIntervalMs);
        fixture.runs[index]?.settle(runExit(1, null, "exit"));
        const backoffNap = await fixture.sleeps.next();
        delays.push(backoffNap.ms);
        if (index === 0) {
          backoffNap.release();
        }
      }
      expect(delays).toStrictEqual([1_000, 2_000]);
    } finally {
      await fixture.instance.stop();
    }
  });

  it("restarts an engine that stays alive but stops answering its health probe", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValueOnce(true).mockResolvedValue(false);

    fixture.instance.start();
    (await fixture.sleeps.next()).release();
    const secondNap = await fixture.sleeps.next();
    expect(fixture.instance.status()).toMatchObject({
      state: "unhealthy",
      error: "health probe failed (1/3)",
    });
    secondNap.release();
    const thirdNap = await fixture.sleeps.next();
    expect(fixture.instance.status()).toMatchObject({
      state: "unhealthy",
      error: "health probe failed (2/3)",
    });
    thirdNap.release();
    const backoffNap = await fixture.sleeps.next();

    expect(backoffNap.ms).toBe(1_000);
    expect(fixture.runs[0]?.cancelled).toBe(true);
    expect(fixture.instance.status()).toMatchObject({
      state: "restarting",
      error: "3 consecutive failed health probes",
      lastExit: { reason: "unhealthy", signal: "SIGTERM" },
    });
    await fixture.instance.stop();
  });

  it("recovers from a failed probe without restarting", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValueOnce(true).mockResolvedValueOnce(false).mockResolvedValue(true);

    fixture.instance.start();
    (await fixture.sleeps.next()).release();
    (await fixture.sleeps.next()).release();
    await fixture.sleeps.next();

    expect(fixture.instance.status()).toMatchObject({ state: "running", restarts: 0 });
    expect(fixture.runs).toHaveLength(1);
    expect(fixture.runs[0]?.cancelled).toBe(false);
    expect(fixture.log.info).toHaveBeenCalledWith(
      "the OPSYS engine answers again after 1 failed probe(s)",
    );
    await fixture.instance.stop();
  });

  it("gives a slow engine its whole ready delay, then ends it and restarts", async () => {
    const fixture = createFixture({ config: { readyTimeoutMs: 1_000 } });
    fixture.probe.mockResolvedValue(false);

    fixture.instance.start();
    (await fixture.sleeps.next()).release();
    (await fixture.sleeps.next()).release();
    const backoffNap = await fixture.sleeps.next();

    expect(backoffNap.ms).toBe(1_000);
    expect(fixture.runs[0]?.cancelled).toBe(true);
    expect(fixture.instance.status()).toMatchObject({
      state: "restarting",
      error: "no healthy probe within 1000 ms of the launch",
      lastExit: { reason: "not-ready" },
    });
    await fixture.instance.stop();
  });

  it("retries with a backoff when the engine cannot even be launched", async () => {
    const fixture = createFixture();
    fixture.spawnFailures.push(new Error("spawn uv ENOENT"));

    fixture.instance.start();
    const backoffNap = await fixture.sleeps.next();

    expect(backoffNap.ms).toBe(1_000);
    expect(fixture.instance.status()).toMatchObject({
      state: "restarting",
      restarts: 1,
      error: expect.stringContaining("launch failed: spawn uv ENOENT"),
    });
    expect(fixture.log.warn).toHaveBeenCalledWith(expect.stringContaining("spawn uv ENOENT"));
    backoffNap.release();
    await fixture.sleeps.next();

    expect(fixture.instance.status()).toMatchObject({ state: "running" });
    await fixture.instance.stop();
  });

  it("stops waiting for the next launch when the Gateway shuts down", async () => {
    const fixture = createFixture();
    fixture.probe.mockResolvedValue(false);

    fixture.instance.start();
    await fixture.sleeps.next();
    fixture.runs[0]?.settle(runExit(1, null, "exit"));
    await fixture.sleeps.next();
    await fixture.instance.stop();

    expect(fixture.runs).toHaveLength(1);
    expect(fixture.closed).toStrictEqual(fixture.scopes);
    expect(fixture.published.at(-1)).toBeUndefined();
  });

  it("ends the engine's process tree once, however many times it is stopped", async () => {
    const fixture = createFixture();
    fixture.instance.start();
    await fixture.sleeps.next();

    const first = fixture.instance.stop();
    const second = fixture.instance.stop();
    await first;

    expect(second).toBe(first);
    expect(fixture.runs[0]?.cancelled).toBe(true);
    expect(fixture.closed).toHaveLength(1);
    expect(fixture.published.at(-1)).toBeUndefined();
  });

  it("launches once however many times it is started", async () => {
    const fixture = createFixture();

    fixture.instance.start();
    fixture.instance.start();
    await fixture.sleeps.next();

    expect(fixture.scopes).toHaveLength(1);
    expect(fixture.runs).toHaveLength(1);
    await fixture.instance.stop();
  });

  it("launches nothing when it is stopped before it ever started", async () => {
    const fixture = createFixture();

    await fixture.instance.stop();

    expect(fixture.scopes).toHaveLength(0);
    expect(fixture.runs).toHaveLength(0);
    expect(fixture.published.at(-1)).toBeUndefined();
  });
});

describe("startOpsysMetierSidecar", () => {
  function writeConfig(dir: string, content: unknown): void {
    fs.writeFileSync(path.join(dir, "metier.json"), JSON.stringify(content));
  }

  it("does nothing without opsys/metier.json", () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: {},
      log: fixture.log,
      deps: fixture.deps,
    });

    expect(sidecar).toBeUndefined();
    expect(fixture.published).toHaveLength(0);
    expect(fixture.scopes).toHaveLength(0);
    expect(fixture.runs).toHaveLength(0);
  });

  it("does nothing when opsys/metier.json does not enable supervision", () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    writeConfig(dir, { actif: false, dossier: tempDirs.make("opsys-metier-engine-") });

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: {},
      log: fixture.log,
      deps: fixture.deps,
    });

    expect(sidecar).toBeUndefined();
    expect(fixture.published).toHaveLength(0);
    expect(fixture.runs).toHaveLength(0);
  });

  it("launches nothing and reports failure when the configuration cannot be trusted", async () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    writeConfig(dir, { actif: true });

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: {},
      log: fixture.log,
      deps: fixture.deps,
    });

    expect(sidecar).toBeDefined();
    expect(fixture.published[0]).toMatchObject({
      state: "failed",
      restarts: 0,
      error: expect.stringContaining('"dossier"'),
    });
    expect(fixture.log.error).toHaveBeenCalledWith(
      expect.stringContaining("OPSYS engine supervision refused"),
    );
    expect(fixture.scopes).toHaveLength(0);
    expect(fixture.runs).toHaveLength(0);
    await sidecar?.stop();
    expect(fixture.published.at(-1)).toBeUndefined();
  });

  it("launches nothing when OPSYS_MCP_JETON is set but unusable", async () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    writeConfig(dir, { actif: true, dossier: tempDirs.make("opsys-metier-engine-") });

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: { OPSYS_MCP_JETON: "court" },
      log: fixture.log,
      deps: fixture.deps,
    });

    expect(fixture.published[0]).toMatchObject({
      state: "failed",
      error: expect.stringContaining("at least 24 characters"),
    });
    expect(fixture.runs).toHaveLength(0);
    await sidecar?.stop();
  });

  it("never lets a defect in its own supervision keep the Gateway from starting", async () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    writeConfig(dir, { actif: true, dossier: tempDirs.make("opsys-metier-engine-") });

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: { OPSYS_MCP_JETON: TOKEN },
      log: fixture.log,
      deps: {
        ...fixture.deps,
        supervisor: {
          ...fixture.supervisor,
          acquireScopeCleanup: () => {
            throw new Error("scope registry unavailable");
          },
        },
      },
    });

    expect(sidecar).toBeDefined();
    expect(fixture.published[0]).toMatchObject({
      state: "failed",
      error: "unexpected failure: scope registry unavailable",
    });
    expect(fixture.runs).toHaveLength(0);
    await sidecar?.stop();
    expect(fixture.published.at(-1)).toBeUndefined();
  });

  it("supervises the engine with the operator's token until the sidecar stops", async () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    const dossier = tempDirs.make("opsys-metier-engine-");
    writeConfig(dir, { actif: true, dossier });

    const sidecar = startOpsysMetierSidecar({
      dir,
      env: { OPSYS_MCP_JETON: TOKEN },
      log: fixture.log,
      deps: fixture.deps,
    });
    await fixture.sleeps.next();

    expect(fixture.published.at(-1)).toMatchObject({ state: "running", tokenSource: "env" });
    const input = childInput(fixture.runs[0]);
    expect(input.cwd).toBe(dossier);
    expect(input.env?.OPSYS_MCP_JETON).toBe(TOKEN);
    await sidecar?.stop();
    expect(fixture.runs[0]?.cancelled).toBe(true);
    expect(fixture.published.at(-1)).toBeUndefined();
  });

  it("generates the token when absent, shares it through the environment and never reports it", async () => {
    const fixture = createFixture();
    const dir = tempDirs.make("opsys-metier-sidecar-");
    writeConfig(dir, { actif: true, dossier: tempDirs.make("opsys-metier-engine-") });
    const env: NodeJS.ProcessEnv = {};

    const sidecar = startOpsysMetierSidecar({ dir, env, log: fixture.log, deps: fixture.deps });
    await fixture.sleeps.next();

    const generated = env.OPSYS_MCP_JETON;
    expect(generated).toMatch(/^[0-9a-f]{64}$/u);
    expect(childInput(fixture.runs[0]).env?.OPSYS_MCP_JETON).toBe(generated);
    expect(fixture.published.at(-1)).toMatchObject({ state: "running", tokenSource: "generated" });
    const everything = JSON.stringify([
      fixture.published,
      fixture.log.info.mock.calls,
      fixture.log.warn.mock.calls,
      fixture.log.error.mock.calls,
    ]);
    expect(everything).not.toContain(generated);
    await sidecar?.stop();
  });
});
