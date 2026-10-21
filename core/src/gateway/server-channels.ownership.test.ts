import { readFile } from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { createAccountListHelpers } from "../channels/plugins/account-helpers.js";
import { resolveReadOnlyChannelPluginsForConfig } from "../channels/plugins/read-only.js";
import type { ChannelGatewayContext } from "../channels/plugins/types.adapters.js";
import type { ChannelPlugin } from "../channels/plugins/types.public.js";
import { applyLegacyDoctorMigrations } from "../commands/doctor/shared/legacy-config-compat.js";
import { prepareLegacyConfigMigrationRuntime } from "../commands/doctor/shared/legacy-config-migrate.test-support.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createSubsystemLogger, runtimeForLogger } from "../logging/subsystem.js";
import { setGatewayPluginMetadataSnapshot } from "../plugins/current-plugin-metadata-snapshot.js";
import {
  clearCurrentPluginMetadataSnapshot,
  getCurrentPluginMetadataSnapshotState,
  selectCurrentPluginMetadataCache,
} from "../plugins/current-plugin-metadata-state.js";
import { registerPluginHttpRoute } from "../plugins/http-registry.js";
import { createPluginCache, getProcessPluginCache } from "../plugins/plugin-cache.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import { createPluginMetadataSnapshotFixture } from "../plugins/plugin-metadata.test-support.js";
import { createEmptyPluginRegistry } from "../plugins/registry.js";
import { getActivePluginRegistry, setActivePluginRegistry } from "../plugins/runtime.js";
import { createRuntimeChannel } from "../plugins/runtime/runtime-channel.js";
import { createPluginRecord } from "../plugins/status.test-helpers.js";
import { resolveAgentRoute } from "../routing/resolve-route.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import {
  createOpenClawTestState,
  type OpenClawTestState,
} from "../test-utils/openclaw-test-state.js";
import { startChannelHealthMonitor } from "./channel-health-monitor.js";
import { channelReadyPatch } from "./channel-status-patches.js";
import * as smsHost from "./opsys-sms-host-authority.js";
import { createChannelManager, type ChannelManager } from "./server-channels.js";

describe("channel ownership startup", () => {
  let state: OpenClawTestState;
  let manager: ChannelManager;
  let registry: ReturnType<typeof createEmptyPluginRegistry>;
  let previousRegistry: ReturnType<typeof getActivePluginRegistry>;
  let previousMetadataCache: ReturnType<typeof getProcessPluginCache>;
  let previousMetadataState: ReturnType<typeof getCurrentPluginMetadataSnapshotState>;
  let restoreMigrationRuntime: (() => void) | undefined;
  const started = vi.fn<(accountId: string, ownerAgentId: string) => void>();
  const startAccount = vi.fn(async (ctx: ChannelGatewayContext) => {
    const route = resolveAgentRoute({ cfg: ctx.cfg, channel: "discord", accountId: ctx.accountId });
    started(ctx.accountId, route.agentId);
    ctx.setStatus(channelReadyPatch({ accountId: ctx.accountId }));
    await new Promise<void>((resolve) => {
      ctx.abortSignal.addEventListener("abort", () => resolve(), { once: true });
    });
  });

  beforeEach(async () => {
    previousMetadataCache = getProcessPluginCache();
    previousMetadataState = getCurrentPluginMetadataSnapshotState();
    selectCurrentPluginMetadataCache(createPluginCache());
    state = await createOpenClawTestState({ label: "channel-ownership" });
    restoreMigrationRuntime = await prepareLegacyConfigMigrationRuntime();
    previousRegistry = getActivePluginRegistry();
    registry = createEmptyPluginRegistry();
    const plugin: ChannelPlugin = {
      ...createChannelTestPluginBase({
        id: "discord",
        config: {
          listAccountIds: createAccountListHelpers("discord").listAccountIds,
          isConfigured: () => true,
        },
      }),
      gateway: { startAccount },
    };
    registry.channels.push({ pluginId: plugin.id, source: "test", plugin });
    setActivePluginRegistry(registry);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  });

  afterEach(async () => {
    await manager?.stopChannel("discord");
    vi.useRealTimers();
    vi.restoreAllMocks();
    started.mockClear();
    startAccount.mockClear();
    setActivePluginRegistry(previousRegistry ?? createEmptyPluginRegistry());
    restoreMigrationRuntime?.();
    clearCurrentPluginMetadataSnapshot();
    await state.cleanup();
    selectCurrentPluginMetadataCache(previousMetadataCache);
    expect(getCurrentPluginMetadataSnapshotState()).toEqual(previousMetadataState);
  });

  async function start(cfg: OpenClawConfig) {
    await state.writeConfig(cfg);
    // A restarted Gateway reads persisted config without the migration's in-memory owner.
    const runtimeConfig = JSON.parse(await readFile(state.configPath, "utf8")) as OpenClawConfig;
    const log = createSubsystemLogger("gateway/channel-ownership-test");
    manager = createChannelManager({
      getRuntimeConfig: () => runtimeConfig,
      getPluginRegistry: () => registry,
      channelLogs: { discord: log },
      channelRuntimeEnvs: { discord: runtimeForLogger(log) },
    });
    await manager.startChannels();
    await vi.advanceTimersByTimeAsync(0);
  }

  it("blocks an unowned account without retrying while its bound sibling stays online", async () => {
    await start({
      agents: { ownership: "explicit", list: [{ id: "main" }, { id: "patricia" }] },
      channels: {
        discord: {
          enabled: true,
          accounts: {
            default: {},
            patricia: {},
          },
        },
      },
      bindings: [{ agentId: "patricia", match: { channel: "discord", accountId: "patricia" } }],
    });
    const healthMonitor = startChannelHealthMonitor({ channelManager: manager });
    try {
      await vi.advanceTimersByTimeAsync(18 * 60_000);
      const accounts = manager.getRuntimeSnapshot().channelAccounts.discord;
      expect(startAccount, JSON.stringify(accounts)).toHaveBeenCalledTimes(2);
      expect(accounts).toMatchObject({
        default: {
          running: false,
          lifecycle: "blocked",
          terminalDisconnect: true,
          restartPending: false,
          reconnectAttempts: 0,
          lastError: expect.stringContaining(
            "discord account default routing has no explicit owner",
          ),
        },
        patricia: { running: true, connected: true, lifecycle: "ready" },
      });
      expect(accounts?.default?.lastError).toContain(
        '{"agentId":"<agentId>","match":{"channel":"discord","accountId":"default"}}',
      );
      expect(accounts?.default?.lastError).toContain("then restart the Gateway");
      expect(manager.isAutoRestartScheduled("discord", "default")).toBe(false);
      expect(started).toHaveBeenCalledExactlyOnceWith("patricia", "patricia");
    } finally {
      healthMonitor.stop();
      await healthMonitor.waitForIdle();
    }
  });

  it.each([
    { authored: "ops", owner: "ops", sibling: "main" },
    { authored: "Ops", owner: "ops", sibling: "main" },
    { authored: "main", owner: "main", sibling: "patricia" },
  ])(
    "preserves legacy account owner $authored across migration and a persisted restart",
    async ({ authored, owner, sibling }) => {
      const raw = {
        agents: { list: [{ id: authored }, { id: sibling }] },
        channels: { discord: { enabled: true } },
      };
      // A loaded test channel alone does not admit its configured presence. Supply its
      // fictitious manifest through the real metadata lifecycle before real repair.
      setGatewayPluginMetadataSnapshot(
        createPluginMetadataSnapshotFixture({
          plugins: [{ id: "discord", channels: ["discord"] }],
        }),
        { config: raw, compatibleConfigs: [raw] },
      );
      const inventory = resolveReadOnlyChannelPluginsForConfig(raw, {
        includePersistedAuthState: false,
        includeSetupFallbackPlugins: true,
      });
      expect(inventory.configuredChannelIds).toEqual(["discord"]);
      expect(
        inventory.manifestRecords.filter((entry) => entry.channels.includes("discord")),
      ).toMatchObject([{ id: "discord", origin: "bundled", channels: ["discord"] }]);
      expect(inventory.plugins.find((entry) => entry.id === "discord")).toBe(
        registry.channels[0]?.plugin,
      );
      const repaired = applyLegacyDoctorMigrations(raw, { sourceConfigBeforeMigrations: raw });
      await start(repaired.next as OpenClawConfig);
      expect(manager.getRuntimeSnapshot().channelAccounts.discord?.default).toMatchObject({
        running: true,
        connected: true,
        lifecycle: "ready",
        lastError: null,
      });
      expect(started).toHaveBeenCalledExactlyOnceWith("default", owner);
      expect(repaired.next?.bindings).toContainEqual({
        agentId: owner,
        match: { channel: "discord", accountId: "default" },
      });
    },
  );
});

describe("OPSYS SMS Host lifetime publication", () => {
  let smsInstance: PluginInstance;
  let manager: ReturnType<typeof createChannelManager>;
  let registry: ReturnType<typeof createEmptyPluginRegistry>;
  let cfg: OpenClawConfig;
  let previousRegistry: ReturnType<typeof getActivePluginRegistry>;
  const sid = `AC${"a".repeat(32)}`;
  const startAccount = vi.fn(async ({ abortSignal }: ChannelGatewayContext) => {
    await new Promise<void>((resolve) => {
      if (abortSignal.aborted) {
        resolve();
      } else {
        abortSignal.addEventListener("abort", () => resolve(), { once: true });
      }
    });
  });

  beforeEach(() => {
    previousRegistry = getActivePluginRegistry();
    cfg = {
      agents: {
        list: [
          {
            id: "opsys-agent-m01-sms-un",
            opsysRuntimeAdmission: {
              profileId: "m01-sms-un",
              profileRevision: 2,
              smsIngress: { version: 1, accountId: "default", accountSid: sid },
            },
          },
        ],
      },
      channels: {
        sms: {
          enabled: true,
          accountSid: sid,
          authToken: "fictif-test-token",
          fromNumber: "+15145550123",
          publicWebhookUrl: "https://fictif.invalid/webhooks/sms",
          dangerouslyDisableSignatureValidation: false,
        },
      },
      bindings: [
        { agentId: "opsys-agent-m01-sms-un", match: { channel: "sms", accountId: "default" } },
      ],
    };
    registry = createEmptyPluginRegistry();
    const rootDir = path.resolve("extensions/sms");
    const record = createPluginRecord({
      id: "sms",
      rootDir,
      source: path.join(rootDir, "index.ts"),
      origin: "bundled",
      imported: true,
    });
    registry.plugins.push(record);
    smsInstance = new PluginInstance("sms", { record, registry });
    // Loader leaf fixture; actual managed views, controller and carrier are exercised.
    smsInstance.bindModuleLoader(
      () => smsApi,
      (p) => [path.join(rootDir, "index.ts"), path.join(rootDir, "api.ts")].includes(p),
    );
    const nativeRuntime = createRuntimeChannel();
    const plugin: ChannelPlugin = {
      ...createChannelTestPluginBase({
        id: "sms",
        config: {
          listAccountIds: () => ["default"],
          resolveAccount: () => ({
            accountId: "default",
            accountSid: sid,
            enabled: true,
            authToken: "fictif-test-token",
            dangerouslyDisableSignatureValidation: false,
            fromNumber: "+15145550123",
            publicWebhookUrl: "https://fictif.invalid/webhooks/sms",
          }),
          isConfigured: () => true,
        },
      }),
      gateway: { startAccount },
    };
    registry.channels.push({
      pluginId: "sms",
      source: path.join(rootDir, "index.ts"),
      rootDir,
      plugin: smsInstance.wrap(plugin),
      resolveChannelRuntime: () => nativeRuntime,
      origin: "bundled",
      captureReadAuthority: () => () => true,
    });
    setActivePluginRegistry(registry);
    const log = createSubsystemLogger("gateway/opsys-sms-lifetime-test");
    manager = createChannelManager({
      getRuntimeConfig: () => cfg,
      getPluginRegistry: () => registry,
      channelLogs: { sms: log },
      channelRuntimeEnvs: { sms: runtimeForLogger(log) },
    });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  });

  afterEach(async () => {
    await manager?.stopChannel("sms");
    await smsInstance?.dispose();
    vi.useRealTimers();
    vi.restoreAllMocks();
    startAccount.mockClear();
    setActivePluginRegistry(previousRegistry ?? createEmptyPluginRegistry());
  });

  it("publishes the actual Host controller before plugin start and revokes it on stop", async () => {
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    let authorityAtStart = false;
    startAccount.mockImplementationOnce(async ({ abortSignal }) => {
      authorityAtStart = create.mock.results[0]?.value?.isCurrent() === true;
      await new Promise<void>((resolve) => {
        abortSignal.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    expect(create).toHaveBeenCalledTimes(1);
    const authority = create.mock.results[0]?.value;
    expect(authority?.isCurrent()).toBe(true);
    expect(authorityAtStart).toBe(true);
    await manager.stopChannel("sms", "default");
    expect(authority?.isCurrent()).toBe(false);
  });

  it("rechecks selected configuration after the deferred handoff before starting the plugin", async () => {
    let release!: () => void;
    const defer = new Promise<void>((resolve) => {
      release = resolve;
    });
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    await manager.startChannel("sms", "default", { deferAccountStartUntil: defer });
    const authority = create.mock.results[0]?.value;
    expect(authority?.isCurrent()).toBe(true);
    cfg = { ...cfg, agents: { list: [] } };
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(startAccount).not.toHaveBeenCalled();
    expect(authority?.isCurrent()).toBe(false);
    expect(manager.getRuntimeSnapshot().channelAccounts.sms.default).toMatchObject({
      lifecycle: "blocked",
      terminalDisconnect: true,
      lastError: smsHost.OPSYS_SMS_HOST_SELECTION_REFUSED,
    });
    expect(manager.isAutoRestartScheduled("sms", "default")).toBe(false);
    cfg.agents = {
      list: [
        {
          id: "opsys-agent-m01-sms-un",
          opsysRuntimeAdmission: {
            profileId: "m01-sms-un",
            profileRevision: 2,
            smsIngress: { version: 1, accountId: "default", accountSid: sid },
          },
        },
      ],
    };
    expect(authority?.isCurrent()).toBe(false);
  });

  it.each(["false", "throw"])(
    "closes a %s publication without running or orphaning the account task",
    async (mode) => {
      const revoke = vi.fn();
      const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority").mockReturnValue({
        publish: () => {
          if (mode === "throw") {
            throw new Error("fictif-private-publication-error");
          }
          return false;
        },
        isCurrent: () => false,
        revoke,
      });
      await expect(manager.startChannel("sms", "default")).rejects.toThrow(
        smsHost.OPSYS_SMS_HOST_SELECTION_REFUSED,
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(startAccount).not.toHaveBeenCalled();
      expect(revoke).toHaveBeenCalled();
      expect(manager.hasCurrentAccountTask("sms", "default")).toBe(false);
      expect(manager.isAutoRestartScheduled("sms", "default")).toBe(false);
      create.mockRestore();
      expect(await manager.startChannel("sms", "default")).toEqual(
        new Map([["default", { status: "handed-off" }]]),
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(startAccount).toHaveBeenCalledTimes(1);
    },
  );

  it("keeps a stopped authority closed when a successor account lifetime starts", async () => {
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    const old = create.mock.results[0]?.value;
    expect(old?.isCurrent()).toBe(true);
    await manager.stopChannel("sms", "default");
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    const current = create.mock.results[1]?.value;
    expect(current).not.toBe(old);
    expect(current?.isCurrent()).toBe(true);
    expect(old?.publish()).toBe(false);
    expect(old?.isCurrent()).toBe(false);
    old?.revoke();
    expect(current?.isCurrent()).toBe(true);
  });

  it("revokes a stopped preparation and permits a distinct later grant", async () => {
    let release!: () => void;
    const deferred = new Promise<void>((resolve) => {
      release = resolve;
    });
    let preparing = true;
    const log = createSubsystemLogger("gateway/opsys-sms-preparation-test");
    manager = createChannelManager({
      getRuntimeConfig: () => cfg,
      getPluginRegistry: () => registry,
      channelLogs: { sms: log },
      channelRuntimeEnvs: { sms: runtimeForLogger(log) },
      startupTrace: {
        measure: async (name, run) => {
          if (preparing && name === "channels.sms.runtime") {
            preparing = false;
            await deferred;
          }
          return await run();
        },
      },
    });
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    const pending = manager.startChannel("sms", "default").catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0);
    const old = create.mock.results[0]?.value;
    expect(old).toBeDefined();
    expect(old?.isCurrent()).toBe(false);
    await manager.stopChannel("sms", "default");
    release();
    expect(await pending).toEqual(
      new Map([["default", { status: "skipped", reason: "manual-stop" }]]),
    );
    expect(old?.publish()).toBe(false);
    expect(startAccount).not.toHaveBeenCalled();
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    expect(create.mock.results[1]?.value?.isCurrent()).toBe(true);
    expect(old?.isCurrent()).toBe(false);
  });

  it.each(["false", "throw"])(
    "retires parked ingress when successor publication returns %s",
    async (mode) => {
      startAccount.mockImplementationOnce(async ({ abortSignal }) => {
        const unregister = registerPluginHttpRoute({
          path: "/fictif/sms-host",
          auth: "plugin",
          match: "exact",
          pluginId: "sms",
          source: "fictif",
          handler: () => true,
        });
        await new Promise<void>((resolve) => {
          abortSignal.addEventListener("abort", () => resolve(), { once: true });
        });
        unregister();
      });
      await manager.startChannel("sms", "default");
      await vi.advanceTimersByTimeAsync(0);
      expect(registry.httpRoutes).toHaveLength(1);
      await manager.stopChannel("sms", "default", { manual: false, routeHandoff: true });
      expect(registry.httpRoutes.map((route) => route.handoff)).toEqual([true]);
      const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority").mockReturnValue({
        publish: () => {
          if (mode === "throw") {
            throw new Error("fictif-private-publication-error");
          }
          return false;
        },
        isCurrent: () => false,
        revoke: () => {},
      });
      await expect(manager.startChannel("sms", "default")).rejects.toThrow(
        smsHost.OPSYS_SMS_HOST_SELECTION_REFUSED,
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(startAccount).toHaveBeenCalledTimes(1);
      expect(registry.httpRoutes).toEqual([]);
      expect(manager.hasCurrentAccountTask("sms", "default")).toBe(false);
      create.mockRestore();
      expect(await manager.startChannel("sms", "default")).toEqual(
        new Map([["default", { status: "handed-off" }]]),
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(startAccount).toHaveBeenCalledTimes(2);
    },
  );

  it("installs the selected managed bridge after publication and before plugin entry", async () => {
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    let observed: unknown;
    startAccount.mockImplementationOnce(async ({ abortSignal }) => {
      expect(create.mock.results[0]?.value?.isCurrent()).toBe(true);
      observed = smsInstance.wrap(smsApi).getOpsysSmsHostBridge("default");
      await new Promise<void>((resolve) => {
        abortSignal.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    expect(observed).toBeDefined();
    await manager.stopChannel("sms", "default");
    expect(smsInstance.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
  });

  it("prepares the Task before publication and gives its alias-preserving runtime to the actual plugin", async () => {
    const requiredSmsTask = await import("../infra/opsys-sms-task-runtime.js");
    const realHost = smsHost.createOpsysSmsHostAuthority;
    const realTask = requiredSmsTask.createOpsysSmsRequiredTaskRuntime;
    let publish = vi.fn<() => boolean>();
    let current = vi.fn<() => boolean>();
    let selection = vi.fn<smsHost.OpsysSmsHostAuthority["captureSelection"]>();
    const createHost = vi
      .spyOn(smsHost, "createOpsysSmsHostAuthority")
      .mockImplementation((params) => {
        const host = realHost(params);
        if (!host) {
          return host;
        }
        publish = vi.fn(host.publish);
        current = vi.fn(host.isCurrent);
        selection = vi.fn(host.captureSelection);
        return Object.freeze({ ...host, publish, isCurrent: current, captureSelection: selection });
      });
    let wrapped: ReturnType<typeof realTask> | undefined;
    const createTask = vi
      .spyOn(requiredSmsTask, "createOpsysSmsRequiredTaskRuntime")
      .mockImplementation((params) => {
        expect(current).not.toHaveBeenCalled();
        expect(selection).not.toHaveBeenCalled();
        expect(publish).not.toHaveBeenCalled();
        wrapped = realTask(params);
        expect(current).not.toHaveBeenCalled();
        expect(selection).not.toHaveBeenCalled();
        return wrapped;
      });
    startAccount.mockImplementationOnce(async ({ abortSignal, channelRuntime }) => {
      expect(createHost.mock.results[0]?.value?.isCurrent()).toBe(true);
      expect(createTask).toHaveBeenCalledTimes(1);
      expect(channelRuntime).toBe(wrapped?.runtime);
      expect(channelRuntime?.inbound).toBe(channelRuntime?.turn);
      expect(createTask.mock.invocationCallOrder[0]).toBeLessThan(
        publish.mock.invocationCallOrder[0],
      );
      expect(publish.mock.invocationCallOrder[0]).toBeLessThan(
        startAccount.mock.invocationCallOrder[0],
      );
      await new Promise<void>((resolve) => {
        abortSignal.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    await manager.startChannel("sms", "default");
    expect(createTask).toHaveBeenCalledTimes(1);
    expect(publish).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(startAccount).toHaveBeenCalledTimes(1);
    await manager.stopChannel("sms", "default");
  });

  it("rejects an abort-ignoring predecessor after public recovery without touching its successor", async () => {
    let releaseFirst!: () => void;
    const firstDone = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let firstContext: ChannelGatewayContext | undefined;
    startAccount.mockImplementationOnce(async (context) => {
      firstContext = context;
      await firstDone;
    });
    try {
      await manager.startChannel("sms", "default");
      await vi.advanceTimersByTimeAsync(0);
      const stopped = manager.stopChannel("sms", "default", { manual: false });
      await vi.advanceTimersByTimeAsync(5_000);
      await stopped;
      expect(firstContext?.abortSignal.aborted).toBe(true);
      expect(await manager.startChannel("sms", "default")).toEqual(
        new Map([["default", { status: "retry", reason: "task-owned" }]]),
      );
      await manager.startChannel("sms", "default");
      await vi.advanceTimersByTimeAsync(0);
      expect(startAccount).toHaveBeenCalledTimes(2);
      const snapshot = manager.getRuntimeSnapshot();
      const record = vi.fn();
      const dispatch = vi.fn();
      expect(() =>
        firstContext?.channelRuntime?.inbound.run({
          channel: "sms",
          accountId: "default",
          raw: {},
          adapter: {
            ingest: () => ({ id: "fictif", rawText: "fictif" }),
            resolveTurn: () => ({
              channel: "sms",
              ctxPayload: {},
              routeSessionKey: "fictif",
              storePath: "fictif",
              recordInboundSession: record,
              runDispatch: dispatch,
            }),
          },
        } as never),
      ).toThrow(smsHost.OPSYS_SMS_HOST_SELECTION_REFUSED);
      expect(record).not.toHaveBeenCalled();
      expect(dispatch).not.toHaveBeenCalled();
      expect(manager.getRuntimeSnapshot()).toEqual(snapshot);
      releaseFirst();
      await vi.advanceTimersByTimeAsync(0);
      expect(manager.getRuntimeSnapshot()).toEqual(snapshot);
    } finally {
      releaseFirst();
    }
  });

  it("preserves the unselected SMS legacy path", async () => {
    cfg.agents = { list: [] };
    const create = vi.spyOn(smsHost, "createOpsysSmsHostAuthority");
    await manager.startChannel("sms", "default");
    await vi.advanceTimersByTimeAsync(0);
    expect(create).toHaveBeenCalledTimes(1);
    expect(create.mock.results[0]?.value).toBeUndefined();
    expect(startAccount).toHaveBeenCalledTimes(1);
  });
});
