import { fileURLToPath } from "node:url";
import type { Worker, WorkerOptions } from "node:worker_threads";
import { afterEach, expect, it, vi } from "vitest";

const createCpuTrackedWorker = vi.hoisted(() => vi.fn());
vi.mock("./worker-cpu.js", () => ({ createCpuTrackedWorker }));

import { createSqliteWorkerLifecycle } from "./sqlite-worker-broker-lifecycle.js";

afterEach(() => {
  createCpuTrackedWorker.mockReset();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function mockWorker(): Worker {
  return {
    on: vi.fn().mockReturnThis(),
    once: vi.fn().mockReturnThis(),
    unref: vi.fn(),
  } as unknown as Worker;
}

function makeLifecycle() {
  return createSqliteWorkerLifecycle({
    actors: new Map(),
    slots: new Set(),
    stores: new Map(),
    enqueueClose: async () => undefined,
    fail: () => undefined,
  });
}

function makeSlot(carrierUrl: URL) {
  const worker = mockWorker();
  createCpuTrackedWorker.mockReturnValue(worker);
  const lifecycle = makeLifecycle();
  lifecycle.createSlot(
    {
      carrierUrl,
      moduleUrl: new URL(import.meta.url),
      databasePath: "/synthetic/state.sqlite",
      input: Buffer.alloc(0),
      existingOnly: false,
    },
    false,
    () => ({ fail() {}, finish() {}, dispatch() {} }),
  );
  return worker;
}

function workerEnvironment(options: WorkerOptions | undefined) {
  const env = options?.env;
  if (!env || typeof env !== "object") {
    throw new Error("Expected an isolated worker environment");
  }
  return env;
}

it("pins TSX path resolution to the owner package for source workers", () => {
  vi.stubEnv("TSX_TSCONFIG_PATH", "/caller/cwd/tsconfig.json");
  vi.stubEnv(
    "OPENCLAW_CRON_AUTHORITY_KEY_ID",
    "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  );
  vi.stubEnv("NODE_COMPILE_CACHE", "/runtime/compile-cache");

  makeSlot(new URL("file:///checkout/core/src/infra/sqlite-store.worker.ts"));

  const options = createCpuTrackedWorker.mock.calls[0]?.[1] as WorkerOptions | undefined;
  const env = workerEnvironment(options);
  expect(options).toBeDefined();
  expect(options?.execArgv).toEqual(["--import", import.meta.resolve("tsx/esm")]);
  expect(env.TSX_TSCONFIG_PATH).toBe(
    fileURLToPath(new URL("../../tsconfig.json", import.meta.url)),
  );
  expect(env.NODE_COMPILE_CACHE).toBe("/runtime/compile-cache");
  expect(env.OPENCLAW_CRON_AUTHORITY_KEY_ID).toBe(
    "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  );
  expect(options?.resourceLimits).toEqual({ maxOldGenerationSizeMb: 512 });
});

it("leaves compiled JavaScript worker loader options unchanged", () => {
  vi.stubEnv("TSX_TSCONFIG_PATH", "/caller/cwd/tsconfig.json");

  makeSlot(new URL("file:///install/dist/infra/sqlite-store.worker.js"));

  const options = createCpuTrackedWorker.mock.calls[0]?.[1] as WorkerOptions | undefined;
  const env = workerEnvironment(options);
  expect(options).toBeDefined();
  expect(options?.execArgv).toEqual([]);
  expect(env.TSX_TSCONFIG_PATH).toBe("/caller/cwd/tsconfig.json");
});
