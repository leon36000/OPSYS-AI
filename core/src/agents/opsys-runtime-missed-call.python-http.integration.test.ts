import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { createHostMissedCallImporterV1 } from "./opsys-runtime-missed-call.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-runtime-admission-fixture.py");
const PROFILE_ID = "it-m1-missed-call";
const AGENT_ID = `opsys-agent-${PROFILE_ID}`;
const PRIVATE_TOKEN = "synthetic-m1-private-token-not-a-production-credential-2026";
const PUBLIC_TOKEN = "synthetic-m1-public-token-not-a-production-credential-2026";
const MAX_STREAM_BYTES = 64 * 1_024;
const READY_TIMEOUT_MS = 15_000;
const OPERATION_TIMEOUT_MS = 8_000;
const input = {
  provider: "mock" as const,
  eventId: "synthetic-missed-event-01",
  callId: "synthetic-missed-call-01",
  startedAt: "2026-10-03T15:00:00.000Z",
  from: "+15145550142",
  terminal: "no-answer" as const,
};
const expectedAck = {
  ok: true,
  source: "voice-call:mock",
  call_id: input.callId,
  status: "manque",
};

type ManagedPython = {
  child: ReturnType<typeof spawn>;
  closed: boolean;
  stdout: Buffer[];
  stderr: Buffer[];
  stdoutBytes: number;
  stderrBytes: number;
  failure?: Error;
};
const children: ManagedPython[] = [];
const tempDirs: string[] = [];

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the real M1 HTTP integration companion");
  }
  return python;
}

function isolatedEnvironment(directory: string): NodeJS.ProcessEnv {
  // Closed environment: no inherited provider credentials, database URL or HOME override.
  return {
    OPSYS_HOME: directory,
    TMPDIR: directory,
    OPSYS_DEPARTMENTS: resolve(REPO, "departments"),
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
    ].join(delimiter),
    LANG: "C.UTF-8",
    TZ: "UTC",
  };
}

function startPython(python: string, args: string[], env: NodeJS.ProcessEnv): ManagedPython {
  const child = spawn(python, args, { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] });
  const processState: ManagedPython = {
    child,
    closed: false,
    stdout: [],
    stderr: [],
    stdoutBytes: 0,
    stderrBytes: 0,
  };
  const capture = (stream: "stdout" | "stderr", chunk: Buffer) => {
    const previous = stream === "stdout" ? processState.stdoutBytes : processState.stderrBytes;
    const available = Math.max(0, MAX_STREAM_BYTES - previous);
    if (available > 0) {
      processState[stream].push(chunk.subarray(0, available));
    }
    if (stream === "stdout") {
      processState.stdoutBytes = Math.min(MAX_STREAM_BYTES, previous + chunk.length);
    } else {
      processState.stderrBytes = Math.min(MAX_STREAM_BYTES, previous + chunk.length);
    }
    if (chunk.length > available && !processState.failure) {
      processState.failure = new Error(
        "Python integration output exceeded its per-stream byte bound",
      );
      child.kill("SIGTERM");
    }
  };
  const onStdout = (chunk: Buffer) => capture("stdout", chunk);
  const onStderr = (chunk: Buffer) => capture("stderr", chunk);
  child.stdout?.on("data", onStdout);
  child.stderr?.on("data", onStderr);
  child.once("error", () => {
    processState.failure = new Error("Python integration process could not start");
  });
  child.once("close", () => {
    processState.closed = true;
    child.stdout?.removeListener("data", onStdout);
    child.stderr?.removeListener("data", onStderr);
  });
  children.push(processState);
  return processState;
}

function waitForPython(processState: ManagedPython, mode: "ready" | "complete"): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    const { child } = processState;
    let settled = false;
    const timeout = setTimeout(
      () => finish(new Error(`Python integration ${mode} deadline exceeded`)),
      mode === "ready" ? READY_TIMEOUT_MS : OPERATION_TIMEOUT_MS,
    );
    const finish = (error?: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      child.stdout?.removeListener("data", onProgress);
      child.stderr?.removeListener("data", onProgress);
      child.removeListener("error", onError);
      child.removeListener("close", onProgress);
      if (error) {
        reject(error);
      } else {
        resolveOutput(Buffer.concat(processState.stdout).toString("utf8"));
      }
    };
    const onProgress = () => {
      if (processState.failure) {
        finish(processState.failure);
        return;
      }
      if (mode === "ready") {
        const output = Buffer.concat([...processState.stdout, ...processState.stderr]).toString(
          "utf8",
        );
        if (!processState.closed && output.includes("Uvicorn running on")) {
          finish();
          return;
        }
      }
      if (processState.closed) {
        finish(
          mode === "complete" && child.exitCode === 0
            ? undefined
            : new Error("Python integration process closed before a successful result"),
        );
      }
    };
    const onError = () => finish(new Error("Python integration process could not start"));
    child.stdout?.on("data", onProgress);
    child.stderr?.on("data", onProgress);
    child.once("error", onError);
    child.once("close", onProgress);
    onProgress();
  });
}

async function waitForClose(processState: ManagedPython): Promise<boolean> {
  if (processState.closed) {
    return true;
  }
  return await new Promise<boolean>((resolveClosed) => {
    const finish = (closed: boolean) => {
      clearTimeout(timeout);
      processState.child.removeListener("close", onClose);
      resolveClosed(closed || processState.closed);
    };
    const onClose = () => finish(true);
    const timeout = setTimeout(() => finish(false), 2_000);
    processState.child.once("close", onClose);
    if (processState.closed) {
      finish(true);
    }
  });
}

async function stopPython(processState: ManagedPython): Promise<void> {
  if (processState.closed) {
    return;
  }
  processState.child.kill("SIGTERM");
  if (await waitForClose(processState)) {
    return;
  }
  processState.child.kill("SIGKILL");
  if (!(await waitForClose(processState))) {
    throw new Error("Owned Python process remained alive after bounded TERM and KILL cleanup");
  }
}

async function runFixture(python: string, action: string, env: NodeJS.ProcessEnv): Promise<string> {
  const processState = startPython(python, [FIXTURE, action], env);
  try {
    return await waitForPython(processState, "complete");
  } finally {
    await stopPython(processState);
  }
}

afterEach(async () => {
  const cleanup = await Promise.allSettled(children.splice(0).map(stopPython));
  const failures = cleanup.filter((result) => result.status === "rejected");
  if (failures.length > 0) {
    // Preserve synthetic state for diagnosis if any owned process could not be reaped.
    throw new Error("Owned Python cleanup failed; temporary integration state was preserved");
  }
  await Promise.all(
    tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function reserveEphemeralPort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    const onError = (error: Error) => reject(error);
    server.once("error", onError);
    server.listen(0, "127.0.0.1", () => {
      server.removeListener("error", onError);
      resolveListen();
    });
  });
  const address = server.address();
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  if (!address || typeof address === "string") {
    throw new Error("Could not reserve a loopback port for the real Python MCP server");
  }
  return address.port;
}

function runtimeConfig(port: number, token: string): OpenClawConfig {
  return {
    agents: {
      entries: {
        [AGENT_ID]: { opsysRuntimeAdmission: { profileId: PROFILE_ID, profileRevision: 2 } },
      },
    },
    mcp: {
      servers: {
        [`opsys_runtime_${PROFILE_ID}`]: {
          url: `http://127.0.0.1:${port}/mcp/runtime/${PROFILE_ID}`,
          transport: "streamable-http",
          headers: { Authorization: `Bearer ${token}` },
          connectionTimeoutMs: OPERATION_TIMEOUT_MS,
          requestTimeoutMs: OPERATION_TIMEOUT_MS,
        },
      },
    },
  };
}

function importer(port: number, token = PRIVATE_TOKEN) {
  const config = runtimeConfig(port, token);
  return createHostMissedCallImporterV1({
    config,
    getCurrentConfig: () => config,
    // A synthetic current host service scope; Python independently checks the durable M1 profile.
    isServiceScopeCurrent: () => true,
    isStopping: () => false,
    signal: new AbortController().signal,
    agentId: AGENT_ID,
    lease: createPluginRuntimeCapabilityLease("M1 real HTTP integration host scope"),
    // No callTool override: the helper must load and use the native callOpsysMcpTool.
  });
}

type DurableState = {
  state_sha256: string;
  table_counts: Record<string, number>;
  m1_chain_size: number;
  host_signals: number;
  host_transfers: number;
  manual_signals: number;
  host_imports: number;
  profile_revision: number;
  profile_active: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readState(text: string): DurableState {
  const value: unknown = JSON.parse(text);
  if (!isRecord(value) || !isRecord(value.table_counts)) {
    throw new Error("Synthetic M1 inspector returned an invalid state");
  }
  const expectedTables = [
    "agents_configurables",
    "cles_chiffrement",
    "evenements_recus",
    "evenements_sortants",
    "mutations_appliquees",
    "registres_maillons",
  ];
  expect(Object.keys(value.table_counts).toSorted()).toEqual(expectedTables);
  const counts: Record<string, number> = {};
  for (const [name, count] of Object.entries(value.table_counts)) {
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0 || count > 1_024) {
      throw new Error("Synthetic M1 inspector returned invalid row counts");
    }
    counts[name] = count;
  }
  const counter = (name: string): number => {
    const number = value[name];
    if (typeof number !== "number" || !Number.isSafeInteger(number) || number < 0) {
      throw new Error("Synthetic M1 inspector returned an invalid counter");
    }
    return number;
  };
  if (typeof value.state_sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(value.state_sha256)) {
    throw new Error("Synthetic M1 inspector returned an invalid digest");
  }
  if (typeof value.profile_active !== "boolean") {
    throw new Error("Synthetic M1 inspector returned an invalid profile state");
  }
  return {
    state_sha256: value.state_sha256,
    table_counts: counts,
    m1_chain_size: counter("m1_chain_size"),
    host_signals: counter("host_signals"),
    host_transfers: counter("host_transfers"),
    manual_signals: counter("manual_signals"),
    host_imports: counter("host_imports"),
    profile_revision: counter("profile_revision"),
    profile_active: value.profile_active,
  };
}

async function setup() {
  const python = requiredPython();
  const directory = await mkdtemp(resolve(tmpdir(), "opsys-missed-call-http-it-"));
  tempDirs.push(directory);
  const env = isolatedEnvironment(directory);
  await runFixture(python, "prepare-missed-call", env);
  const port = await reserveEphemeralPort();
  const server = startPython(
    python,
    ["-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
    env,
  );
  await waitForPython(server, "ready");
  return {
    server,
    port,
    inspect: async () => readState(await runFixture(python, "inspect-missed-call", env)),
    revoke: async () => await runFixture(python, "revoke-missed-call", env),
  };
}

describe("host missed-call importer through native MCP transport and real Python HTTP", () => {
  it("returns the exact ACK, commits M1 follow-up, and replays without changing six durable owners", async () => {
    const fixture = await setup();
    const importCall = importer(fixture.port);
    await expect(importCall(input)).resolves.toEqual(expectedAck);
    const committed = await fixture.inspect();
    expect(committed.profile_active).toBe(true);
    expect(committed.profile_revision).toBe(2);
    expect(committed.host_imports).toBe(1);
    expect(committed.host_signals).toBe(1);
    expect(committed.host_transfers).toBe(1);
    expect(committed.manual_signals).toBe(0);
    expect(committed.m1_chain_size).toBeGreaterThanOrEqual(3);

    await expect(
      importCall({ ...input, eventId: "synthetic-redelivery-event-02" }),
    ).resolves.toEqual(expectedAck);
    expect(await fixture.inspect()).toEqual(committed);
    expect(fixture.server.failure).toBeUndefined();
    expect(fixture.server.closed).toBe(false);
  }, 60_000);

  it("refuses the public token and a withdrawn live profile, including an old receipt, without mutation", async () => {
    const fixture = await setup();
    const initial = await fixture.inspect();
    await expect(importer(fixture.port, PUBLIC_TOKEN)(input)).rejects.toThrow();
    expect(await fixture.inspect()).toEqual(initial);

    const privateImport = importer(fixture.port);
    await expect(privateImport(input)).resolves.toEqual(expectedAck);
    await fixture.revoke();
    const withdrawn = await fixture.inspect();
    expect(withdrawn.profile_active).toBe(false);
    expect(withdrawn.profile_revision).toBe(3);
    await expect(
      privateImport({
        ...input,
        eventId: "synthetic-after-revoke-event",
        callId: "synthetic-after-revoke-call",
      }),
    ).rejects.toThrow();
    expect(await fixture.inspect()).toEqual(withdrawn);
    await expect(privateImport(input)).rejects.toThrow();
    expect(await fixture.inspect()).toEqual(withdrawn);
    expect(fixture.server.failure).toBeUndefined();
    expect(fixture.server.closed).toBe(false);
  }, 60_000);
});
