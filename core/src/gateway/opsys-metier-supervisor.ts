// OPSYS business-engine supervisor (OPSYS-AI PLAN T0.10, ADR-0008).
//
// The Gateway launches the Python engine (`uv run opsys-mcp --http ...`), watches it and stops
// it with itself. It reuses what the fork already owns instead of adding a supervisor:
//   - `ProcessSupervisor` (`src/process/supervisor`) launches the child, relays its output and
//     ends its whole process tree, as `desktop/managed-linux.ts` does for its own children;
//   - `RetrySupervisor` (`packages/retry`) spaces restarts with a bounded exponential backoff,
//     as `server-channels.ts` does for channel accounts;
//   - the secret-redaction registry keeps the shared engine token out of every log line;
//   - the sidecar handle (`GatewayPostReadySidecarHandle`) ties its lifetime to the Gateway.
//
// Off by default: without `<config dir>/opsys/metier.json` carrying `"actif": true`
// (`opsys-metier-config.ts`) nothing here runs. State is published for the `health` and `status`
// RPCs through `opsys-metier-status.ts`.
import { randomUUID } from "node:crypto";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { RetrySupervisor } from "../../packages/retry/src/index.js";
import { type BackoffPolicy, sleepWithAbort } from "../infra/backoff.js";
import { formatErrorMessage } from "../infra/errors.js";
import {
  createSecretValueRedactor,
  redactRegisteredSecretValues,
  registerSecretValueForRedaction,
} from "../logging/secret-redaction-registry.js";
import { createSubsystemLogger } from "../logging/subsystem.js";
import { getProcessSupervisor } from "../process/supervisor/index.js";
import type { ManagedRun, ProcessSupervisor, RunExit } from "../process/supervisor/types.js";
import { isSensitiveEnvName } from "../secrets/secret-env-name.js";
import { OpsysCronPrivateClient } from "./opsys-cron-private-client.js";
import {
  OPSYS_CONTEXT_MCP_TOKEN_ENV,
  OPSYS_CRON_OPERATOR_TOKEN_ENV,
  OPSYS_MCP_TOKEN_ENV,
  readOpsysMetierConfig,
  type OpsysMetierConfig,
} from "./opsys-metier-config.js";
import { buildOpsysMetierChildEnv, resolveOpsysMcpToken } from "./opsys-metier-env.js";
import { setOpsysMetierStatus, type OpsysMetierStatus } from "./opsys-metier-status.js";
import type { GatewayPostReadySidecarHandle } from "./server-startup-sidecar-scheduler.js";

/** Subsystem name of the engine's lines in the Gateway journal. */
export const OPSYS_METIER_LOG_SUBSYSTEM = "opsys-metier";

const DEFAULT_BACKOFF: BackoffPolicy = { initialMs: 1_000, maxMs: 60_000, factor: 2, jitter: 0.1 };
const STARTUP_PROBE_INTERVAL_MS = 500;
const PROBE_TIMEOUT_MS = 2_000;
const MAX_LINE_CHARS = 4_000;
const OVERSIZED_LINE_NOTICE = "[oversized line omitted]";

function createChildEnvSecretRedactor(
  env: Readonly<Record<string, string>>,
): (text: string) => string {
  const values = new Set<string>();
  for (const [name, value] of Object.entries(env)) {
    const normalizedName = name.toUpperCase();
    if (
      !isSensitiveEnvName(name) &&
      normalizedName !== OPSYS_MCP_TOKEN_ENV &&
      normalizedName !== OPSYS_CONTEXT_MCP_TOKEN_ENV &&
      normalizedName !== OPSYS_CRON_OPERATOR_TOKEN_ENV
    ) {
      continue;
    }
    if (value.length < 6) {
      continue;
    }
    values.add(value);
    try {
      values.add(encodeURIComponent(value));
    } catch {
      // A malformed UTF-16 value has no URI encoding; raw and JSON-escaped forms remain covered.
    }
    values.add(JSON.stringify(value).slice(1, -1));
  }
  const redact = createSecretValueRedactor([...values]);
  return (text) => redact(text, () => "***");
}

export type OpsysMetierLog = {
  info: (message: string, meta?: Record<string, unknown>) => void;
  warn: (message: string, meta?: Record<string, unknown>) => void;
  error: (message: string, meta?: Record<string, unknown>) => void;
};

/** Seams for tests. Production passes none of them. */
export type OpsysMetierSupervisorDeps = {
  supervisor?: ProcessSupervisor;
  log?: OpsysMetierLog;
  /** Resolves true when the engine answered its health endpoint. */
  probe?: (url: string, signal: AbortSignal) => Promise<boolean>;
  /** Rejects when `signal` aborts. */
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  nowMs?: () => number;
  backoff?: BackoffPolicy;
  /** A healthy run at least this long resets the restart counter. Defaults to the backoff cap. */
  stableRunMs?: number;
  startupProbeIntervalMs?: number;
  publishStatus?: (status: OpsysMetierStatus | undefined) => void;
  /** Host-local notification for an already-successful health probe; never blocks supervision. */
  onHealthy?: () => void | Promise<void>;
  /** Environment the child env and the token are derived from. Defaults to `process.env`. */
  env?: NodeJS.ProcessEnv;
};

export type OpsysMetierSupervisor = {
  start: () => void;
  /** Stops supervision, then ends the engine's process tree. Safe to call twice. */
  stop: () => Promise<void>;
  status: () => OpsysMetierStatus;
  /** Returns the captured private client only while this same child is healthy. */
  getPrivateCronClient: () => OpsysCronPrivateClient | undefined;
};

export type OpsysMetierSidecarHandle = GatewayPostReadySidecarHandle & {
  getPrivateCronClient?: () => OpsysCronPrivateClient | undefined;
};

type RunCause = "stopped" | "exited" | "unhealthy" | "not-ready" | "spawn-failed";

type RunOutcome = {
  cause: RunCause;
  /** Longest continuous interval confirmed by successful probes, excluding startup. */
  healthyMs: number;
  detail: string;
};

/** Splits stdout/stderr into bounded journal lines, discarding overlong lines before redaction. */
function createLineRelay(emit: (line: string) => void) {
  let pending = "";
  let droppingOversizedLine = false;
  const emitLine = (raw: string): void => {
    const line = raw.replace(/\r$/u, "").trimEnd();
    if (line) {
      emit(line);
    }
  };
  return {
    push: (chunk: string): void => {
      let remaining = chunk;
      while (remaining.length > 0) {
        if (droppingOversizedLine) {
          const newline = remaining.indexOf("\n");
          if (newline === -1) {
            return;
          }
          remaining = remaining.slice(newline + 1);
          droppingOversizedLine = false;
          continue;
        }
        const newline = remaining.indexOf("\n");
        if (newline !== -1) {
          if (pending.length + newline > MAX_LINE_CHARS) {
            emit(OVERSIZED_LINE_NOTICE);
          } else {
            emitLine(pending + remaining.slice(0, newline));
          }
          pending = "";
          remaining = remaining.slice(newline + 1);
          continue;
        }
        if (pending.length + remaining.length > MAX_LINE_CHARS) {
          pending = "";
          droppingOversizedLine = true;
          emit(OVERSIZED_LINE_NOTICE);
          return;
        }
        pending += remaining;
        return;
      }
    },
    flush: (): void => {
      if (!droppingOversizedLine) {
        emitLine(pending);
      }
      pending = "";
      droppingOversizedLine = false;
    },
  };
}

async function probeHealth(url: string, signal: AbortSignal): Promise<boolean> {
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.any([signal, AbortSignal.timeout(PROBE_TIMEOUT_MS)]),
  });
  try {
    if (!response.ok) {
      return false;
    }
    // A different service on the same port must not pass for the engine.
    const body: unknown = await response.json();
    return isRecord(body) && body.statut === "ok";
  } finally {
    await response.body?.cancel().catch(() => undefined);
  }
}

function describeExit(exit: RunExit): string {
  if (exit.reason === "spawn-error") {
    return `engine process was lost: ${exit.stderr}`;
  }
  if (exit.exitSignal !== null) {
    return `engine was killed by signal ${String(exit.exitSignal)}`;
  }
  return `engine exited with code ${String(exit.exitCode)}`;
}

export function createOpsysMetierSupervisor(params: {
  config: OpsysMetierConfig;
  token: string;
  tokenSource: "env" | "generated";
  deps?: OpsysMetierSupervisorDeps;
}): OpsysMetierSupervisor {
  const { config } = params;
  const deps = params.deps ?? {};
  const supervisor = deps.supervisor ?? getProcessSupervisor();
  const log: OpsysMetierLog = deps.log ?? createSubsystemLogger(OPSYS_METIER_LOG_SUBSYSTEM);
  const probe = deps.probe ?? probeHealth;
  const sleep =
    deps.sleep ?? ((ms: number, signal: AbortSignal) => sleepWithAbort(ms, signal, { ref: false }));
  const nowMs = deps.nowMs ?? Date.now;
  const backoff = deps.backoff ?? DEFAULT_BACKOFF;
  const stableRunMs = deps.stableRunMs ?? backoff.maxMs;
  const startupProbeIntervalMs = deps.startupProbeIntervalMs ?? STARTUP_PROBE_INTERVAL_MS;
  const publishStatus = deps.publishStatus ?? setOpsysMetierStatus;
  const scopeKey = `opsys-metier:${randomUUID()}`;
  const childEnv = buildOpsysMetierChildEnv({
    base: deps.env ?? process.env,
    extra: config.env,
    token: params.token,
  });
  // Construct from the exact private child environment this supervisor will pass to spawn.
  // The Gateway receives only this client getter, never the environment or its credentials.
  let privateCronClient: OpsysCronPrivateClient | undefined;
  const operatorToken = childEnv[OPSYS_CRON_OPERATOR_TOKEN_ENV];
  const publicToken = childEnv[OPSYS_MCP_TOKEN_ENV];
  if (operatorToken && publicToken) {
    try {
      privateCronClient = new OpsysCronPrivateClient({
        healthUrl: config.healthUrl,
        operatorToken,
        publicMcpToken: publicToken,
        ...(childEnv[OPSYS_CONTEXT_MCP_TOKEN_ENV]
          ? { contextToken: childEnv[OPSYS_CONTEXT_MCP_TOKEN_ENV] }
          : {}),
      });
    } catch {
      // A collision or malformed audience credential disables private RPCs without logging it.
      privateCronClient = undefined;
    }
  }
  // Keep a per-child redactor independent of the process-wide bounded registry: later credentials
  // from unrelated subsystems must not evict this child’s active tokens before stdout/stderr logs.
  const redactChildSecrets = createChildEnvSecretRedactor(childEnv);
  for (const name of [OPSYS_CONTEXT_MCP_TOKEN_ENV, OPSYS_CRON_OPERATOR_TOKEN_ENV]) {
    const token = childEnv[name];
    if (token !== undefined) {
      registerSecretValueForRedaction(token);
    }
  }
  registerSecretValueForRedaction(params.token);
  const maskSecrets = (text: string): string =>
    redactRegisteredSecretValues(redactChildSecrets(text), () => "***");

  const abort = new AbortController();
  let active = true;
  let status: OpsysMetierStatus = {
    state: "starting",
    restarts: 0,
    healthUrl: config.healthUrl,
    tokenSource: params.tokenSource,
  };
  const setStatus = (patch: Partial<OpsysMetierStatus>): void => {
    status = { ...status, ...patch };
    publishStatus(status);
    if (patch.state === "running" && privateCronClient && active && deps.onHealthy) {
      try {
        const notification = deps.onHealthy();
        void Promise.resolve(notification).catch(() =>
          log.warn("OPSYS healthy-probe reconciliation callback failed."),
        );
      } catch {
        log.warn("OPSYS healthy-probe reconciliation callback failed.");
      }
    }
  };

  /** A sleep that ends early, without failing, when `signal` aborts. */
  const nap = async (ms: number, signal: AbortSignal): Promise<void> => {
    try {
      await sleep(ms, signal);
    } catch (error) {
      if (!signal.aborted) {
        throw error;
      }
    }
  };

  const runOnce = async (): Promise<RunOutcome> => {
    const startedAtMs = nowMs();
    setStatus({ state: "starting", pid: undefined, startedAtMs, error: undefined });
    const stdout = createLineRelay((line) => log.info(maskSecrets(line), { stream: "stdout" }));
    const stderr = createLineRelay((line) => log.info(maskSecrets(line), { stream: "stderr" }));
    let run: ManagedRun;
    try {
      run = await supervisor.spawn({
        mode: "child",
        argv: [...config.command],
        cwd: config.cwd,
        env: childEnv,
        scopeKey,
        stdinMode: "pipe-closed",
        captureOutput: false,
        assertCurrent: () => {
          if (abort.signal.aborted) {
            throw new Error("OPSYS engine supervision stopped during launch");
          }
        },
        onStdout: stdout.push,
        onStderr: stderr.push,
      });
    } catch (error) {
      return {
        cause: abort.signal.aborted ? "stopped" : "spawn-failed",
        healthyMs: 0,
        detail: `launch failed: ${formatErrorMessage(error)}`,
      };
    }
    setStatus({ pid: run.pid });
    log.info(`launched the OPSYS engine (pid ${String(run.pid ?? "unknown")})`);

    const runOver = new AbortController();
    const finished: { exit?: RunExit } = {};
    const exitOf = (): RunExit | undefined => finished.exit;
    const exited = run
      .wait()
      .then(
        (result) => {
          finished.exit = result;
        },
        (error: unknown) => {
          finished.exit = {
            reason: "spawn-error",
            exitCode: null,
            exitSignal: null,
            durationMs: nowMs() - startedAtMs,
            stdout: "",
            stderr: formatErrorMessage(error),
            timedOut: false,
            noOutputTimedOut: false,
          };
        },
      )
      .finally(() => {
        runOver.abort();
        stdout.flush();
        stderr.flush();
      });
    const napSignal = AbortSignal.any([abort.signal, runOver.signal]);
    const shouldStop = (): boolean => abort.signal.aborted || exitOf() !== undefined;
    const probeOnce = async (): Promise<boolean> => {
      try {
        return await probe(config.healthUrl, napSignal);
      } catch {
        return false;
      }
    };

    let cause: RunCause = "exited";
    let detail = "";
    let becameReady = false;
    let healthySinceMs: number | undefined;
    let healthyMs = 0;
    const readyDeadlineMs = startedAtMs + config.readyTimeoutMs;
    while (!shouldStop()) {
      if (await probeOnce()) {
        becameReady = true;
        healthySinceMs = nowMs();
        break;
      }
      if (shouldStop()) {
        break;
      }
      if (nowMs() >= readyDeadlineMs) {
        cause = "not-ready";
        detail = `no healthy probe within ${String(config.readyTimeoutMs)} ms of the launch`;
        break;
      }
      await nap(startupProbeIntervalMs, napSignal);
    }

    if (becameReady) {
      setStatus({ state: "running", lastHealthyAtMs: nowMs(), error: undefined });
      log.info(`the OPSYS engine is healthy (${String(nowMs() - startedAtMs)} ms after launch)`);
      let failures = 0;
      while (!shouldStop()) {
        await nap(config.probeIntervalMs, napSignal);
        if (shouldStop()) {
          break;
        }
        if (await probeOnce()) {
          if (failures > 0) {
            log.info(`the OPSYS engine answers again after ${String(failures)} failed probe(s)`);
          }
          failures = 0;
          healthySinceMs ??= nowMs();
          healthyMs = Math.max(healthyMs, nowMs() - healthySinceMs);
          setStatus({ state: "running", lastHealthyAtMs: nowMs(), error: undefined });
        } else if (!shouldStop()) {
          healthySinceMs = undefined;
          failures += 1;
          const progress = `${String(failures)}/${String(config.maxProbeFailures)}`;
          setStatus({ state: "unhealthy", error: `health probe failed (${progress})` });
          log.warn(`health probe of the OPSYS engine failed (${progress})`);
          if (failures >= config.maxProbeFailures) {
            cause = "unhealthy";
            detail = `${String(failures)} consecutive failed health probes`;
            break;
          }
        }
      }
    }

    if (abort.signal.aborted) {
      cause = "stopped";
    }
    if (exitOf() === undefined) {
      // Still alive: stopping, unhealthy or never ready. End the whole process tree and join it
      // before anyone may launch a replacement on the same port.
      run.cancel("manual-cancel");
    }
    await exited;
    const finalExit = exitOf();
    if (finalExit && cause === "exited") {
      detail = describeExit(finalExit);
    }
    const exitSignal = finalExit?.exitSignal ?? null;
    setStatus({
      pid: undefined,
      lastExit: {
        reason: cause,
        code: finalExit?.exitCode ?? null,
        signal: exitSignal === null ? null : String(exitSignal),
        atMs: nowMs(),
      },
    });
    return { cause, healthyMs, detail };
  };

  const superviseLoop = async (): Promise<void> => {
    const retry = new RetrySupervisor(backoff, config.maxRestarts);
    for (;;) {
      const outcome = await runOnce();
      if (abort.signal.aborted) {
        return;
      }
      // Only a run that was healthy for a while proves the engine can stay up: a crash loop
      // keeps counting toward giving up.
      if (outcome.healthyMs >= stableRunMs) {
        retry.reset();
      }
      const next = retry.next(abort.signal);
      if (!next) {
        const giveUp = `gave up after ${String(config.maxRestarts)} consecutive restarts (last: ${outcome.detail})`;
        log.error(giveUp);
        setStatus({ state: "failed", error: giveUp });
        return;
      }
      const seconds = String(Math.round(next.delayMs / 1000));
      log.warn(
        `${outcome.detail}; restart ${String(next.attempt)}/${String(config.maxRestarts)} in ${seconds} s`,
      );
      setStatus({ state: "restarting", restarts: status.restarts + 1, error: outcome.detail });
      try {
        await sleep(next.delayMs, next.signal);
      } catch (error) {
        if (abort.signal.aborted) {
          return;
        }
        throw error;
      }
    }
  };

  let loop: Promise<void> | undefined;
  let closeScope: (() => Promise<void>) | undefined;
  let stopping: Promise<void> | undefined;

  const start = (): void => {
    if (loop) {
      return;
    }
    closeScope = supervisor.acquireScopeCleanup(scopeKey, { processTree: "required-all" });
    log.info(
      `supervising the OPSYS engine: ${config.command.join(" ")} (cwd ${config.cwd}, health ${config.healthUrl})`,
    );
    loop = superviseLoop().catch((error: unknown) => {
      if (abort.signal.aborted) {
        return;
      }
      const message = `supervision failed: ${formatErrorMessage(error)}`;
      log.error(message);
      setStatus({ state: "failed", error: message });
    });
  };

  const stop = (): Promise<void> => {
    if (stopping) {
      return stopping;
    }
    const pending = (async () => {
      active = false;
      abort.abort();
      await loop;
      try {
        await closeScope?.();
      } finally {
        publishStatus(undefined);
      }
    })();
    stopping = pending;
    void pending.catch(() => {
      // A failed stop stays retryable: the sidecar owner calls it again.
      if (stopping === pending) {
        stopping = undefined;
      }
    });
    return pending;
  };

  return {
    start,
    stop,
    status: () => status,
    getPrivateCronClient: () =>
      active && status.state === "running" ? privateCronClient : undefined,
  };
}

type SidecarParams = {
  /** Overrides `<config dir>/opsys` (tests only). */
  dir?: string;
  env?: NodeJS.ProcessEnv;
  log?: OpsysMetierLog;
  deps?: OpsysMetierSupervisorDeps;
  /** Called without awaiting after first and periodic successful health probes. */
  onHealthy?: () => void | Promise<void>;
};

/** Launches nothing, says why in the journal and in the health payloads, and stops cleanly. */
function refuseSupervision(
  log: OpsysMetierLog,
  publishStatus: (status: OpsysMetierStatus | undefined) => void,
  reason: string,
): GatewayPostReadySidecarHandle {
  log.error(`OPSYS engine supervision refused: ${reason}`);
  publishStatus({ state: "failed", restarts: 0, error: reason });
  return {
    stop: () => {
      publishStatus(undefined);
    },
  };
}

function resolveSidecarLog(params: SidecarParams): OpsysMetierLog {
  return params.log ?? createSubsystemLogger(OPSYS_METIER_LOG_SUBSYSTEM);
}

function startConfiguredSidecar(
  params: SidecarParams,
  publishStatus: (status: OpsysMetierStatus | undefined) => void,
): OpsysMetierSidecarHandle | undefined {
  const env = params.env ?? process.env;
  const configured = readOpsysMetierConfig({ dir: params.dir, env });
  if (configured.kind === "absent" || configured.kind === "disabled") {
    return undefined;
  }
  const log = resolveSidecarLog(params);
  if (configured.kind === "invalid") {
    return refuseSupervision(log, publishStatus, configured.reason);
  }
  const token = resolveOpsysMcpToken({ env });
  if (!token.ok) {
    return refuseSupervision(log, publishStatus, token.reason);
  }
  if (token.source === "generated") {
    // The Gateway's own MCP client reads the same variable when its config is (re)loaded.
    env[OPSYS_MCP_TOKEN_ENV] = token.token;
  }
  const supervisor = createOpsysMetierSupervisor({
    config: configured.config,
    token: token.token,
    tokenSource: token.source,
    deps: { ...params.deps, onHealthy: params.onHealthy, log, env, publishStatus },
  });
  supervisor.start();
  return {
    stop: () => supervisor.stop(),
    getPrivateCronClient: supervisor.getPrivateCronClient,
  };
}

/**
 * Starts the engine supervisor when `opsys/metier.json` enables it, and returns the sidecar
 * handle that ties it to the Gateway lifetime. Returns `undefined` when supervision is off.
 * A configuration that asks for supervision but cannot be trusted launches nothing, is logged,
 * and shows as `failed` in the health payloads. It never throws: the engine is optional, and no
 * defect in its supervision may keep the Gateway from starting.
 */
export function startOpsysMetierSidecar(
  params: SidecarParams = {},
): OpsysMetierSidecarHandle | undefined {
  const publishStatus = params.deps?.publishStatus ?? setOpsysMetierStatus;
  try {
    return startConfiguredSidecar(params, publishStatus);
  } catch (error) {
    return refuseSupervision(
      resolveSidecarLog(params),
      publishStatus,
      `unexpected failure: ${formatErrorMessage(error)}`,
    );
  }
}
