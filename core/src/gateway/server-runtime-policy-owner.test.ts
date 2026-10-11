import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import {
  getRuntimeAuthProfileStoreCredentialsRevision,
  getRuntimeAuthProfileStoreSnapshotsRevision,
} from "../agents/auth-profiles/runtime-snapshots.js";
import {
  getRuntimeConfigSnapshot,
  publishRuntimeConfigSnapshotWithReceipt,
} from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PreparedSecretsRuntimeSnapshot } from "../secrets/runtime.js";
import { activateSecretsRuntimeSnapshot, clearSecretsRuntimeSnapshot } from "../secrets/runtime.js";
import type { GatewayReloadPlan } from "./config-reload.js";
import * as modelRuntimeReload from "./server-reload-model-runtime-scope.js";
import {
  assertNativeServingRead,
  captureNativeServingRead,
  closeNativeOwner,
  createManagedPolicyOwner,
  findOwner,
  finishNativeTransition,
  readNativeServingConfig,
  recordNativeServingCommit,
  reserveNativeTransition,
} from "./server-runtime-policy-owner.js";
import { createGatewaySecretsReloader } from "./server-secrets-reload.js";
import { SharedGatewaySessionGenerationState } from "./server-shared-auth-generation.js";
import { createTestRuntimeSecretsActivator } from "./server-startup-config.test-support.js";

function createSnapshot(config: OpenClawConfig): PreparedSecretsRuntimeSnapshot {
  return {
    config,
    sourceConfig: {},
    authStores: [],
    authStoreCredentialsRevision: getRuntimeAuthProfileStoreCredentialsRevision(),
    authStoreSnapshotsRevision: getRuntimeAuthProfileStoreSnapshotsRevision(),
    warnings: [],
    webTools: {
      search: { providerSource: "none", diagnostics: [] },
      fetch: { providerSource: "none", diagnostics: [] },
      diagnostics: [],
    },
  };
}

function activate(config: OpenClawConfig) {
  activateSecretsRuntimeSnapshot(createSnapshot(config));
}

function fixture() {
  const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
  const lifetime = new AbortController();
  const owner = createManagedPolicyOwner(state, lifetime.signal, () => true);
  const config: OpenClawConfig = { gateway: { port: 19103 } };
  activate(config);
  const ticket = reserveNativeTransition(owner);
  expect(recordNativeServingCommit(owner, config, ticket, state.capture())).toBe(true);
  finishNativeTransition(ticket);
  return { state, lifetime, owner, config };
}

let stateFixture: import("../test-utils/openclaw-test-state.js").OpenClawTestState | undefined;
beforeEach(async () => {
  const { createOpenClawTestState } = await import("../test-utils/openclaw-test-state.js");
  const modelRuntime = await import("./server-reload-model-runtime-scope.js");
  stateFixture = await createOpenClawTestState({ label: "native-serving-policy" });
  vi.spyOn(modelRuntime, "refreshModelRuntimeAfterHotReload").mockResolvedValue(undefined);
});
afterEach(async () => {
  clearSecretsRuntimeSnapshot();
  vi.restoreAllMocks();
  await stateFixture?.cleanup();
  stateFixture = undefined;
});

describe("native serving publication owner", () => {
  it("binds the actual activation clone and keeps old reads invalid after a settled failure", () => {
    const { owner } = fixture();
    expect(readNativeServingConfig(owner)).toBe(getRuntimeConfigSnapshot());
    const read = captureNativeServingRead(owner);
    expect(read).toBeDefined();
    const ticket = reserveNativeTransition(owner);
    expect(captureNativeServingRead(owner)).toBeUndefined();
    expect(() => assertNativeServingRead(read)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    finishNativeTransition(ticket);
    finishNativeTransition(ticket);
    expect(() => assertNativeServingRead(read)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    expect(captureNativeServingRead(owner)).toBeDefined();
  });

  it("does not upgrade an owner-absent reservation or an operation belonging to a replaced owner", () => {
    const state = new SharedGatewaySessionGenerationState({ current: undefined, required: null });
    const absent = reserveNativeTransition(state);
    const first = createManagedPolicyOwner(state, new AbortController().signal, () => true);
    const config: OpenClawConfig = { gateway: { port: 19104 } };
    activate(config);
    expect(recordNativeServingCommit(first, config, absent, state.capture())).toBe(false);
    finishNativeTransition(absent);
    const old = reserveNativeTransition(first);
    const second = createManagedPolicyOwner(state, new AbortController().signal, () => true);
    expect(findOwner(state)).toBe(second);
    expect(recordNativeServingCommit(first, config, old, state.capture())).toBe(false);
    expect(recordNativeServingCommit(second, config, old, state.capture())).toBe(false);
    expect(captureNativeServingRead(first)).toBeUndefined();
    finishNativeTransition(old);
  });

  it("refuses ordinary publication, copied handles and ownership from another native state", () => {
    const { owner, state, config } = fixture();
    const ticket = reserveNativeTransition(owner);
    const foreign = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    foreign.publish({ current: "B", required: null });
    expect(recordNativeServingCommit(owner, config, ticket, foreign.capture())).toBe(false);
    publishRuntimeConfigSnapshotWithReceipt(config);
    expect(recordNativeServingCommit(owner, config, ticket, state.capture())).toBe(false);
    finishNativeTransition(ticket);
    expect(readNativeServingConfig(owner)).toBeUndefined();
    expect(captureNativeServingRead({ ...owner })).toBeUndefined();
    expect(() => assertNativeServingRead({})).toThrow("NATIVE-SERVING-NOT-CURRENT");
  });

  it("keeps negative tickets pending across owner creation and refuses close or abort", () => {
    const { owner, state, lifetime, config } = fixture();
    const before = captureNativeServingRead(owner);
    const ticket = reserveNativeTransition(state);
    expect(readNativeServingConfig(owner)).toBe(getRuntimeConfigSnapshot());
    expect(captureNativeServingRead(owner)).toBeUndefined();
    lifetime.abort();
    expect(recordNativeServingCommit(owner, config, ticket, state.capture())).toBe(false);
    expect(readNativeServingConfig(owner)).toBeUndefined();
    finishNativeTransition(ticket);
    closeNativeOwner(owner);
    expect(() => assertNativeServingRead(before)).toThrow("NATIVE-SERVING-NOT-CURRENT");
  });
});

describe("native config entry before async validation", () => {
  it("settles a queued writer ticket consumed by the real plugin transaction", async () => {
    const { startGatewayConfigReloader } = await import("./config-reload.js");
    const { createDirectConfigWriteFixture, createConfigWriteNotification, publishConfigWrite } =
      await import("./server-reload-handlers.config.test-support.js");
    const { owner, config } = fixture();
    const old = captureNativeServingRead(owner);
    const io = createDirectConfigWriteFixture(config);
    const base = startGatewayConfigReloader(
      {
        initialConfig: config,
        initialPluginInstallRecords: {},
        initialSnapshotRawHash: "initial",
        initialAuthoredConfig: config,
        initialSnapshotValid: true,
        initialSnapshotIssues: [],
        readSnapshot: io.readSnapshot,
        subscribeToWrites: io.subscribeToWrites,
        onHotReload: async (plan, next, ownership) => {
          ownership.markRuntimeCommitted(next, plan);
          return {
            status: "applied",
            runtime: { operationId: "queued-native-fixture", generation: 1, pluginIds: [] },
          };
        },
        onNoopConfigCommit: async () => {},
        onRestart: async () => {},
        watchPath: "/tmp/openclaw.json",
        log: { info: () => {}, warn: () => {}, error: () => {} },
      },
      owner,
    );
    await base.ready;
    try {
      const listener = io.ref.current;
      if (!listener) {
        throw new Error("Missing native write subscription");
      }
      const completion = publishConfigWrite(
        listener,
        createConfigWriteNotification(config, "queued-plugin", 1, "A", "A"),
      );
      expect(captureNativeServingRead(owner)).toBeUndefined();
      const operation = base.applyPluginLifecycleChange({
        config,
        pluginIds: [],
        reason: "reload",
      });
      await operation;
      await completion;
      await vi.waitUntil(() => !base.isReloading());
      expect(() => assertNativeServingRead(old)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      expect(captureNativeServingRead(owner)).toBeDefined();
    } finally {
      await base.stop();
    }
  });

  it("retires a read for a failed plugin operation with no config publication", async () => {
    const { startGatewayConfigReloader } = await import("./config-reload.js");
    const { makeSnapshot } = await import("./config-reload.test-support.js");
    const { owner, config } = fixture();
    const before = captureNativeServingRead(owner);
    const base = startGatewayConfigReloader(
      {
        initialConfig: config,
        initialPluginInstallRecords: {},
        initialSnapshotRawHash: null,
        initialAuthoredConfig: {},
        initialSnapshotValid: true,
        initialSnapshotIssues: [],
        readSnapshot: async () => makeSnapshot({ config }),
        onHotReload: async () => "applied",
        onNoopConfigCommit: async () => {},
        onRestart: async () => {},
        watchPath: "/tmp/native-policy-config-test.json",
        log: { info: () => {}, warn: () => {}, error: () => {} },
      },
      owner,
    );
    await base.ready;
    const published = getRuntimeConfigSnapshot();
    try {
      const operation = base.applyPluginLifecycleChange({
        config,
        pluginIds: [],
        reason: "reload",
        assertInvokerOwned: () => {
          throw new Error("Expected denied native operation");
        },
      });
      expect(captureNativeServingRead(owner)).toBeUndefined();
      await expect(operation).rejects.toThrow("Expected denied native operation");
      expect(getRuntimeConfigSnapshot()).toBe(published);
      expect(() => assertNativeServingRead(before)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      expect(captureNativeServingRead(owner)).toBeDefined();
    } finally {
      await base.stop();
    }
  });

  it("fences the actual initial watcher scan before readSnapshot", async () => {
    const { startGatewayConfigReloader } = await import("./config-reload.js");
    const { makeSnapshot } = await import("./config-reload.test-support.js");
    const { owner, config } = fixture();
    let calls = 0;
    const observed: boolean[] = [];
    const base = startGatewayConfigReloader(
      {
        initialConfig: config,
        initialSnapshotRawHash: null,
        initialAuthoredConfig: {},
        initialSnapshotValid: true,
        initialSnapshotIssues: [],
        readSnapshot: async () => {
          calls++;
          observed.push(captureNativeServingRead(owner) === undefined);
          return makeSnapshot({ config, exists: false });
        },
        onHotReload: async () => "applied",
        onNoopConfigCommit: async () => {},
        onRestart: async () => {},
        watchPath: "/tmp/native-policy-initial-watch-test.json",
        log: { info: () => {}, warn: () => {}, error: () => {} },
      },
      owner,
    );
    try {
      await base.ready;
      await vi.waitUntil(() => calls > 0);
      expect(observed).toEqual([true]);
    } finally {
      await base.stop();
    }
  });
});

describe("native shared generation last-use ownership", () => {
  it.each(["publish", "replace", "finalize"] as const)(
    "refuses an old serving read after native %s without config publication",
    (operation) => {
      const { owner, state, config } = fixture();
      const read = captureNativeServingRead(owner);
      expect(read).toBeDefined();
      const publication = getRuntimeConfigSnapshot();
      if (operation === "publish") {
        state.publish({ current: "B", required: null });
      } else if (operation === "replace") {
        expect(state.replace(state.capture(), { current: "B", required: null })).toBe(true);
      } else {
        expect(state.finalize(state.capture())).toBe(true);
      }
      expect(getRuntimeConfigSnapshot()).toBe(publication);
      expect(() => assertNativeServingRead(read)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      expect(captureNativeServingRead(owner)).toBeUndefined();
      const ticket = reserveNativeTransition(owner);
      expect(recordNativeServingCommit(owner, config, ticket, state.capture())).toBe(true);
      finishNativeTransition(ticket);
      expect(captureNativeServingRead(owner)).toBeDefined();
      expect(() => assertNativeServingRead(read)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    },
  );
});

function createReloadPlan(): GatewayReloadPlan {
  return {
    changedPaths: [],
    restartGateway: false,
    restartReasons: [],
    hotReasons: [],
    reloadHooks: false,
    restartGmailWatcher: false,
    restartCron: false,
    restartHeartbeat: false,
    reloadPlugins: false,
    restartChannels: new Set(),
    disposeMcpRuntimes: false,
    noopPaths: [],
  };
}
function mockResolvedSecrets(config: OpenClawConfig) {
  return vi.fn().mockResolvedValue(createSnapshot(config));
}
function createSecretsReloadHarness(params: {
  prepareRuntimeSecretsSnapshot: Parameters<typeof createTestRuntimeSecretsActivator>[0];
  sharedGatewaySessionGenerationState: SharedGatewaySessionGenerationState;
  resolveSharedGatewaySessionGenerationForConfig?: (config: OpenClawConfig) => string | undefined;
  buildReloadPlan: () => GatewayReloadPlan;
}) {
  return {
    reload: createGatewaySecretsReloader({
      activateRuntimeSecrets: createTestRuntimeSecretsActivator(
        params.prepareRuntimeSecretsSnapshot,
      ),
      buildReloadPlan: params.buildReloadPlan,
      sharedGatewaySessionGenerationState: params.sharedGatewaySessionGenerationState,
      resolveSharedGatewaySessionGenerationForConfig:
        params.resolveSharedGatewaySessionGenerationForConfig ?? (() => undefined),
      clients: [],
      channelManager: {
        startChannel: async () => new Map(),
        stopChannel: async () => {},
        isManuallyStopped: () => false,
        resolveRuntimeAccountId: (_channel, id) => id,
      },
      logChannels: { info: vi.fn() },
    }),
  };
}
// The factories and publication/generation owners are real. Model publication,
// config I/O and channel services remain explicit local test doubles.
async function createNativeManagedServingFixture(
  sharedState: SharedGatewaySessionGenerationState,
  io?: Pick<
    Parameters<typeof import("./server-reload-managed.js").startManagedGatewayConfigReloader>[0],
    "readSnapshot" | "subscribeToWrites"
  > & {
    prepareRuntimeSecretsSnapshot?: Parameters<typeof createTestRuntimeSecretsActivator>[0];
  },
) {
  const { createDefaultDeps } = await import("../cli/deps.js");
  const { createTestRegistry } = await import("../test-utils/channel-plugins.js");
  const { createChannelManager } = await import("./server-channels.js");
  const { createDefaultGatewayReloadState, createValidConfigSnapshot } =
    await import("./server-reload-handlers.config.test-support.js");
  const { startManagedGatewayConfigReloader } = await import("./server-reload-managed.js");
  const initialConfig = getRuntimeConfigSnapshot();
  expect(initialConfig).not.toBeNull();
  if (!initialConfig) {
    throw new Error("Missing native activation fixture");
  }
  const registry = createTestRegistry([]);
  const channelManager = createChannelManager({
    getRuntimeConfig: () => initialConfig,
    getPluginRegistry: () => registry,
    channelLogs: {},
    channelRuntimeEnvs: {},
  });
  let state = createDefaultGatewayReloadState();
  const managed = startManagedGatewayConfigReloader({
    getPluginRegistry: () => registry,
    minimalTestGateway: false,
    initialConfig,
    initialCompareConfig: initialConfig,
    initialPluginInstallRecords: {},
    initialSnapshotRawHash: "initial",
    initialAuthoredConfig: initialConfig,
    initialSnapshotValid: true,
    initialSnapshotIssues: [],
    watchPath: "/tmp/openclaw.json",
    readSnapshot:
      io?.readSnapshot ?? (async () => createValidConfigSnapshot(initialConfig, "initial")),
    promoteSnapshot: async () => true,
    subscribeToWrites: io?.subscribeToWrites ?? (() => () => {}),
    deps: createDefaultDeps(),
    broadcast: vi.fn(),
    getState: () => state,
    setState: (next) => {
      state = next;
    },
    startChannel: channelManager.startChannel,
    stopChannel: channelManager.stopChannel,
    reloadPlugins: async () => ({
      runtime: { operationId: "native-serving-fixture", generation: 1, pluginIds: [] },
      activeChannels: new Set(),
    }),
    logHooks: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    logChannels: { info: vi.fn(), error: vi.fn() },
    logCron: { error: vi.fn() },
    logReload: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    channelManager,
    activateRuntimeSecrets: createTestRuntimeSecretsActivator(
      io?.prepareRuntimeSecretsSnapshot ?? mockResolvedSecrets(initialConfig),
    ),
    resolveSharedGatewaySessionGenerationForConfig: () => "A",
    sharedGatewaySessionGenerationState: sharedState,
    clients: [],
    reconcileRuntimePolicy: vi.fn(),
    commitRuntimePolicy: vi.fn(),
    acceptTerminalConfig: vi.fn(),
    prepareTerminalConfig: vi.fn(),
    cronReconciliation: { arm: () => ({ complete: async () => {} }), invalidate: vi.fn() },
    configRevisionProjector: {
      projectRawHash: (hash) => hash,
      projectResolvedHash: (hash) => hash,
    },
  });
  await managed.ready;
  return managed;
}

describe("native managed serving and direct secrets", () => {
  it("fences before preparation and binds the real committed clone after finalize", async () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 } });
    const managed = await createNativeManagedServingFixture(state);
    try {
      const oldRead = managed.captureNativeServingRead?.();
      expect(oldRead).toBeDefined();
      const held = createDeferred<PreparedSecretsRuntimeSnapshot>();
      const prepare = vi.fn(() => held.promise);
      const { reload } = createSecretsReloadHarness({
        prepareRuntimeSecretsSnapshot: prepare,
        sharedGatewaySessionGenerationState: state,
        resolveSharedGatewaySessionGenerationForConfig: () => "B",
        buildReloadPlan: () => createReloadPlan(),
      });
      const initial = managed.getCommittedRuntimeConfig?.();
      const operation = reload();
      await vi.waitUntil(() => prepare.mock.calls.length === 1);
      expect(managed.getCommittedRuntimeConfig?.()).toBe(initial);
      expect(managed.captureNativeServingRead?.()).toBeUndefined();
      expect(() => assertNativeServingRead(oldRead)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      held.resolve(createSnapshot({ gateway: { port: 19104 } }));
      await operation;
      expect(managed.getCommittedRuntimeConfig?.()).toBe(getRuntimeConfigSnapshot());
      expect(managed.getCommittedRuntimeConfig?.()?.gateway?.port).toBe(19104);
      const current = managed.captureNativeServingRead?.();
      expect(current).toBeDefined();
      expect(() => assertNativeServingRead(current)).not.toThrow();
      expect(() => assertNativeServingRead(oldRead)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    } finally {
      await managed.stop();
    }
  });

  it("never binds an old secrets operation to a replacement managed incarnation", async () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 } });
    const first = await createNativeManagedServingFixture(state);
    const held = createDeferred<PreparedSecretsRuntimeSnapshot>();
    const { reload } = createSecretsReloadHarness({
      prepareRuntimeSecretsSnapshot: () => held.promise,
      sharedGatewaySessionGenerationState: state,
      buildReloadPlan: () => createReloadPlan(),
    });
    const operation = reload();
    const second = await createNativeManagedServingFixture(state);
    try {
      held.resolve(createSnapshot({ gateway: { port: 19104 } }));
      await operation;
      expect(first.captureNativeServingRead?.()).toBeUndefined();
      expect(second.captureNativeServingRead?.()).toBeUndefined();
      expect(second.getCommittedRuntimeConfig?.()?.gateway?.port).toBe(19103);
    } finally {
      await first.stop();
      await second.stop();
    }
  });

  it("keeps a queued reservation closed between secrets completions and never upgrades absence", async () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 } });
    const first = createDeferred<PreparedSecretsRuntimeSnapshot>();
    const second = createDeferred<PreparedSecretsRuntimeSnapshot>();
    const prepare = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const reload = createGatewaySecretsReloader({
      activateRuntimeSecrets: createTestRuntimeSecretsActivator(prepare),
      buildReloadPlan: () => createReloadPlan(),
      sharedGatewaySessionGenerationState: state,
      resolveSharedGatewaySessionGenerationForConfig: () => "A",
      clients: [],
      channelManager: {
        startChannel: async () => new Map(),
        stopChannel: async () => {},
        isManuallyStopped: () => false,
        resolveRuntimeAccountId: (_channel, id) => id,
      },
      logChannels: { info: vi.fn() },
    });
    const absentOperation = reload();
    const managed = await createNativeManagedServingFixture(state);
    try {
      const queued = reload({ joinInFlight: false });
      first.resolve(createSnapshot({ gateway: { port: 19104 } }));
      await absentOperation;
      expect(managed.captureNativeServingRead?.()).toBeUndefined();
      expect(managed.getCommittedRuntimeConfig?.()?.gateway?.port).toBe(19103);
      second.resolve(createSnapshot({ gateway: { port: 19105 } }));
      await queued;
      expect(managed.getCommittedRuntimeConfig?.()?.gateway?.port).toBe(19105);
      expect(managed.captureNativeServingRead?.()).toBeDefined();
    } finally {
      await managed.stop();
    }
  });
});

describe("native managed serving rollback", () => {
  it("uses the actual restored clone after a model-tail rejection, without reviving an old read", async () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 } });
    const managed = await createNativeManagedServingFixture(state);
    const old = managed.captureNativeServingRead?.();
    vi.mocked(modelRuntimeReload.refreshModelRuntimeAfterHotReload).mockRejectedValueOnce(
      new Error("Expected local model-tail failure"),
    );
    const { reload } = createSecretsReloadHarness({
      prepareRuntimeSecretsSnapshot: mockResolvedSecrets({ gateway: { port: 19104 } }),
      sharedGatewaySessionGenerationState: state,
      resolveSharedGatewaySessionGenerationForConfig: () => "B",
      buildReloadPlan: () => createReloadPlan(),
    });
    try {
      await expect(reload()).rejects.toThrow("Expected local model-tail failure");
      expect(getRuntimeConfigSnapshot()?.gateway?.port).toBe(19103);
      expect(managed.getCommittedRuntimeConfig?.()).toBe(getRuntimeConfigSnapshot());
      expect(managed.captureNativeServingRead?.()).toBeDefined();
      expect(() => assertNativeServingRead(old)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    } finally {
      await managed.stop();
    }
  });
});

describe("native managed serving source-only", () => {
  it("does not mint serving when the real hot helper finalize returns false after legacy mark", async () => {
    const { createDirectConfigWriteFixture, createConfigWriteNotification, publishConfigWrite } =
      await import("./server-reload-handlers.config.test-support.js");
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 }, logging: { level: "info" } });
    const initial = getRuntimeConfigSnapshot();
    if (!initial) {
      throw new Error("Missing native activation fixture");
    }
    const io = createDirectConfigWriteFixture(initial);
    const managed = await createNativeManagedServingFixture(state, {
      ...io,
      prepareRuntimeSecretsSnapshot: async ({ config }) => createSnapshot(config),
    });
    const old = managed.captureNativeServingRead?.();
    // Controlled Core seam: no revision change from finalize(false). This
    // detects a premature record at the legacy mark, not a native race proof.
    const finalize = vi.spyOn(state, "finalize").mockReturnValue(false);
    try {
      const listener = io.ref.current;
      if (!listener) {
        throw new Error("Missing native managed write subscription");
      }
      const next: OpenClawConfig = { ...initial, logging: { level: "debug" } };
      await publishConfigWrite(
        listener,
        createConfigWriteNotification(next, "hot-finalize-false", 1, "hot-next", "hot-next"),
      );
      await vi.waitUntil(() => managed.isConfigReloadSettled());
      expect(finalize).toHaveBeenCalledOnce();
      expect(getRuntimeConfigSnapshot()?.logging?.level).toBe("debug");
      expect(managed.getCommittedRuntimeConfig?.()?.logging?.level).toBe("debug");
      const owner = findOwner(state);
      if (!owner) {
        throw new Error("Missing native managed owner");
      }
      expect(readNativeServingConfig(owner)).toBeUndefined();
      expect(managed.captureNativeServingRead?.()).toBeUndefined();
      expect(() => assertNativeServingRead(old)).toThrow("NATIVE-SERVING-NOT-CURRENT");
    } finally {
      await managed.stop();
    }
  });

  it("binds a settled hot reload only after its actual generation finalization", async () => {
    const { createDirectConfigWriteFixture, createConfigWriteNotification, publishConfigWrite } =
      await import("./server-reload-handlers.config.test-support.js");
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 }, logging: { level: "info" } });
    const initial = getRuntimeConfigSnapshot();
    if (!initial) {
      throw new Error("Missing native activation fixture");
    }
    const io = createDirectConfigWriteFixture(initial);
    const managed = await createNativeManagedServingFixture(state, {
      ...io,
      prepareRuntimeSecretsSnapshot: async ({ config }) => createSnapshot(config),
    });
    const old = managed.captureNativeServingRead?.();
    try {
      const listener = io.ref.current;
      if (!listener) {
        throw new Error("Missing native managed write subscription");
      }
      const next: OpenClawConfig = { ...initial, logging: { level: "debug" } };
      await publishConfigWrite(
        listener,
        createConfigWriteNotification(next, "hot-serving-edit", 1, "hot-next", "hot-next"),
      );
      await vi.waitUntil(() => managed.isConfigReloadSettled());
      expect(getRuntimeConfigSnapshot()?.logging?.level).toBe("debug");
      expect(managed.getCommittedRuntimeConfig?.()).toBe(getRuntimeConfigSnapshot());
      expect(() => assertNativeServingRead(old)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      const current = managed.captureNativeServingRead?.();
      expect(current).toBeDefined();
      expect(() => assertNativeServingRead(current)).not.toThrow();
    } finally {
      await managed.stop();
    }
  });

  it("binds a new source-only native serving successor without reviving the previous read", async () => {
    const { createDirectConfigWriteFixture, createConfigWriteNotification, publishConfigWrite } =
      await import("./server-reload-handlers.config.test-support.js");
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    activate({ gateway: { port: 19103 } });
    const initial = getRuntimeConfigSnapshot();
    if (!initial) {
      throw new Error("Missing native activation fixture");
    }
    const io = createDirectConfigWriteFixture(initial);
    const managed = await createNativeManagedServingFixture(state, io);
    const old = managed.captureNativeServingRead?.();
    try {
      const listener = io.ref.current;
      expect(listener).not.toBeNull();
      if (!listener) {
        throw new Error("Missing native managed write subscription");
      }
      const completion = publishConfigWrite(
        listener,
        createConfigWriteNotification(initial, "source-only-edit", 1, "A", "A"),
      );
      expect(managed.captureNativeServingRead?.()).toBeUndefined();
      await completion;
      await vi.waitUntil(() => managed.isConfigReloadSettled());
      expect(getRuntimeConfigSnapshot()).toBe(initial);
      expect(managed.getCommittedRuntimeConfig?.()).toBe(initial);
      expect(() => assertNativeServingRead(old)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      const current = managed.captureNativeServingRead?.();
      expect(current).toBeDefined();
      expect(() => assertNativeServingRead(current)).not.toThrow();
    } finally {
      await managed.stop();
    }
  });
});

describe("native serving ticket last use", () => {
  it("does not bind if a congruence getter finishes the actual ticket", () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    const owner = createManagedPolicyOwner(state, new AbortController().signal, () => true);
    const config: OpenClawConfig = { gateway: { port: 19106 } };
    activate(config);
    const ticket = reserveNativeTransition(owner);
    const native = state.capture();
    const congruence = {
      get revision() {
        finishNativeTransition(ticket);
        return native.revision;
      },
      generation: native.generation,
      previousGeneration: native.previousGeneration,
    };
    expect(recordNativeServingCommit(owner, config, ticket, congruence)).toBe(false);
    expect(readNativeServingConfig(owner)).toBeUndefined();
  });
});

describe("native reservation incarnation", () => {
  it("does not upgrade a reservation made through an old handle after replacement", () => {
    const state = new SharedGatewaySessionGenerationState({ current: "A", required: null });
    const first = createManagedPolicyOwner(state, new AbortController().signal, () => true);
    const second = createManagedPolicyOwner(state, new AbortController().signal, () => true);
    const config: OpenClawConfig = { gateway: { port: 19107 } };
    activate(config);
    const old = reserveNativeTransition(first);
    expect(recordNativeServingCommit(second, config, old, state.capture())).toBe(false);
    finishNativeTransition(old);
    expect(captureNativeServingRead(second)).toBeUndefined();
    const current = reserveNativeTransition(state);
    expect(recordNativeServingCommit(second, config, current, state.capture())).toBe(true);
    finishNativeTransition(current);
    expect(captureNativeServingRead(second)).toBeDefined();
  });
});
