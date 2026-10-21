/**
 * Gateway request context construction tests.
 */
import { describe, expect, it, onTestFinished, vi } from "vitest";
import {
  GATEWAY_CLIENT_CAPS,
  GATEWAY_CLIENT_IDS,
  GATEWAY_CLIENT_MODES,
} from "../../packages/gateway-protocol/src/client-info.js";
import {
  getRuntimeAuthProfileStoreCredentialsRevision,
  getRuntimeAuthProfileStoreSnapshotsRevision,
} from "../agents/auth-profiles/runtime-snapshots.js";
import { getRuntimeConfigSnapshot } from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PreparedSecretsRuntimeSnapshot } from "../secrets/runtime.js";
import { activateSecretsRuntimeSnapshot, clearSecretsRuntimeSnapshot } from "../secrets/runtime.js";
import * as userProfileCatalog from "../state/user-profile-list.js";
import { ensureProfileForEmail, linkEmail } from "../state/user-profiles.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import { captureGatewayDeviceRevocation } from "./device-revocation.js";
import { prepareGatewayRecipientProfile } from "./expected-profile.js";
import { createGatewayBroadcaster } from "./server-broadcast.js";
import {
  createChatRunState,
  createSessionEventSubscriberRegistry,
  createSessionMessageSubscriberRegistry,
} from "./server-chat-state.js";
import type { GatewayRequestContext } from "./server-methods/types.js";
import * as requestContextModule from "./server-request-context.js";
import {
  assertGatewayCommittedRuntimePolicyRead,
  createGatewayRequestContext,
} from "./server-request-context.js";
import {
  makeContextParams,
  makeCronState,
  makeGatewayClient,
  type RequestRuntime,
} from "./server-request-context.test-support.js";
import {
  assertNativeServingRead,
  captureNativeServingRead,
  closeNativeOwner,
  createManagedPolicyOwner,
  findOwner,
  finishNativeTransition,
  readNativeServingReadConfig,
  recordNativeServingCommit,
  reserveNativeTransition,
} from "./server-runtime-policy-owner.js";
import { startGatewayEventSubscriptions } from "./server-runtime-subscriptions.js";
import { SharedGatewaySessionGenerationState } from "./server-shared-auth-generation.js";
import { createTestRuntimeSecretsActivator } from "./server-startup-config.test-support.js";
import { GatewayClientRegistry } from "./server/client-registry.js";
import type { GatewayWsClient } from "./server/ws-types.js";

vi.mock("./server/health-state.js", () => ({
  getHealthCache: vi.fn(() => null),
  getHealthVersion: vi.fn(() => 1),
  incrementPresenceVersion: vi.fn(() => 1),
}));

function makeDeviceClient(connId: string, deviceId: string, role = "primary") {
  return {
    connId,
    connect: { device: { id: deviceId }, role },
    socket: { close: vi.fn() },
  };
}

function prepareL0Snapshot(config: OpenClawConfig): PreparedSecretsRuntimeSnapshot {
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

// Managed/publication/generation owners are real; model publication, channels,
// and config I/O remain explicit local doubles, as in the policy-owner fixture.
async function createL0NativeFixture(authored: OpenClawConfig = { gateway: { port: 19103 } }) {
  const sharedState = new SharedGatewaySessionGenerationState({ current: "A", required: null });
  const params = makeContextParams({ sharedGatewaySessionGenerationState: sharedState });
  const context = createGatewayRequestContext(params);
  expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
  activateSecretsRuntimeSnapshot(prepareL0Snapshot(authored));
  const published = getRuntimeConfigSnapshot();
  if (!published) {
    throw new Error("Missing native activation fixture");
  }
  expect(published).not.toBe(authored);
  const { createDefaultDeps } = await import("../cli/deps.js");
  const { createTestRegistry } = await import("../test-utils/channel-plugins.js");
  const { createChannelManager } = await import("./server-channels.js");
  const { createDefaultGatewayReloadState, createValidConfigSnapshot } =
    await import("./server-reload-handlers.config.test-support.js");
  const { startManagedGatewayConfigReloader } = await import("./server-reload-managed.js");
  const modelRuntime = await import("./server-reload-model-runtime-scope.js");
  const modelPublication = vi
    .spyOn(modelRuntime, "refreshModelRuntimeAfterHotReload")
    .mockResolvedValue(undefined);
  onTestFinished(() => modelPublication.mockRestore());
  const registry = createTestRegistry([]);
  const channelManager = createChannelManager({
    getRuntimeConfig: () => published,
    getPluginRegistry: () => registry,
    channelLogs: {},
    channelRuntimeEnvs: {},
  });
  let state = createDefaultGatewayReloadState();
  const managed = startManagedGatewayConfigReloader({
    getPluginRegistry: () => registry,
    minimalTestGateway: false,
    initialConfig: published,
    initialCompareConfig: published,
    initialPluginInstallRecords: {},
    initialSnapshotRawHash: "initial",
    initialAuthoredConfig: published,
    initialSnapshotValid: true,
    initialSnapshotIssues: [],
    watchPath: "/tmp/openclaw.json",
    readSnapshot: async () => createValidConfigSnapshot(published, "initial"),
    promoteSnapshot: async () => true,
    subscribeToWrites: () => () => {},
    deps: createDefaultDeps(),
    broadcast: vi.fn(),
    getState: () => state,
    setState: (next) => {
      state = next;
    },
    startChannel: channelManager.startChannel,
    stopChannel: channelManager.stopChannel,
    reloadPlugins: async () => ({
      runtime: { operationId: "l0-native-fixture", generation: 1, pluginIds: [] },
      activeChannels: new Set(),
    }),
    logHooks: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    logChannels: { info: vi.fn(), error: vi.fn() },
    logCron: { error: vi.fn() },
    logReload: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    channelManager,
    activateRuntimeSecrets: createTestRuntimeSecretsActivator(async (config) =>
      prepareL0Snapshot(config),
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
  onTestFinished(async () => {
    await managed.stop();
    clearSecretsRuntimeSnapshot();
  });
  await managed.ready;
  params.runtime.runtimeState.configReloader = managed;
  return { sharedState, params, context, published, managed };
}

function captureL0Read(context: GatewayRequestContext) {
  const read = context.getCommittedRuntimePolicyRead?.();
  if (!read) {
    throw new Error("Missing native context read fixture");
  }
  return read;
}

// This smaller fixture exercises private Core callback contracts, not managed
// startup reachability. Positive integration cases use createL0NativeFixture.
function createL0NativeCallbackFixture(settled: () => boolean) {
  const sharedState = new SharedGatewaySessionGenerationState({ current: "A", required: null });
  const params = makeContextParams({ sharedGatewaySessionGenerationState: sharedState });
  const context = createGatewayRequestContext(params);
  const lifetime = new AbortController();
  const owner = createManagedPolicyOwner(sharedState, lifetime.signal, settled);
  activateSecretsRuntimeSnapshot(prepareL0Snapshot({ gateway: { port: 19103 } }));
  const published = getRuntimeConfigSnapshot();
  if (!published) {
    throw new Error("Missing native callback publication");
  }
  const ticket = reserveNativeTransition(owner);
  expect(recordNativeServingCommit(owner, published, ticket, sharedState.capture())).toBe(true);
  finishNativeTransition(ticket);
  onTestFinished(() => {
    closeNativeOwner(owner);
    clearSecretsRuntimeSnapshot();
  });
  return { sharedState, params, context, lifetime, owner, published };
}

describe("L0-NATIVE-WITNESS contextual lifetime after native capture", () => {
  it("keeps the real native read current when only its Gateway prelude closes", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { sharedState, params, context, published, managed } = await createL0NativeFixture();
      try {
        const read = context.getCommittedRuntimePolicyRead?.();
        expect(read).toBeDefined();
        const owner = findOwner(sharedState);
        const generation = sharedState.capture();
        expect(() => assertNativeServingRead(read)).not.toThrow();
        params.runtime.lifecycle.closePreludeStarted = true;
        expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
        expect(() => assertNativeServingRead(read)).not.toThrow();
        expect(findOwner(sharedState)).toBe(owner);
        expect(sharedState.capture()).toEqual(generation);
        expect(managed.isConfigReloadSettled()).toBe(true);
        expect(managed.getCommittedRuntimeConfig?.()).toBe(published);
        expect(getRuntimeConfigSnapshot()).toBe(published);
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("requires the exact context assertion to reject that still-current captured read", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { params, context, managed } = await createL0NativeFixture();
      try {
        const read = context.getCommittedRuntimePolicyRead?.();
        expect(read).toBeDefined();
        expect(() => assertNativeServingRead(read)).not.toThrow();
        const assertContext = Reflect.get(
          requestContextModule,
          "assertGatewayCommittedRuntimePolicyRead",
        );
        if (typeof assertContext !== "function") {
          throw new Error("CAPABILITY_GAP: native G/R contextual assertion is not implemented");
        }
        expect(() => assertContext(context, read)).not.toThrow();
        params.runtime.lifecycle.closePreludeStarted = true;
        expect(() => assertNativeServingRead(read)).not.toThrow();
        expect(() => assertContext(context, read)).toThrow("NATIVE-SERVING-NOT-CURRENT");
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });
});

describe("L0 exact native context/read association", () => {
  it("repeats a healthy assertion and projects only the original serving clone without mutation", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { sharedState, context, published, managed } = await createL0NativeFixture();
      try {
        const read = captureL0Read(context);
        const generation = sharedState.capture();
        const owner = findOwner(sharedState);
        assertGatewayCommittedRuntimePolicyRead(context, read);
        expect(readNativeServingReadConfig(read)).toBe(published);
        assertGatewayCommittedRuntimePolicyRead(context, read);
        expect(sharedState.capture()).toEqual(generation);
        expect(findOwner(sharedState)).toBe(owner);
        expect(getRuntimeConfigSnapshot()).toBe(published);
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("keeps an OLD refusal sticky after the fixture prelude reopens while NativeR remains current", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { params, context, managed } = await createL0NativeFixture();
      try {
        const read = captureL0Read(context);
        params.runtime.lifecycle.closePreludeStarted = true;
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
        params.runtime.lifecycle.closePreludeStarted = false;
        expect(() => assertNativeServingRead(read)).not.toThrow();
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("refuses foreign real and lookalike contexts without invoking callbacks or poisoning G", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      let reads = 0;
      const config: OpenClawConfig = {
        gateway: { port: 19103 },
        get logging() {
          reads += 1;
          return { level: "info" };
        },
      };
      const { sharedState, context, managed } = await createL0NativeFixture(config);
      try {
        const read = captureL0Read(context);
        const foreign = createGatewayRequestContext(
          makeContextParams({ sharedGatewaySessionGenerationState: sharedState }),
        );
        const foreignRead = captureL0Read(foreign);
        const getter = vi.fn(() => read);
        const lookalike = { ...context, getCommittedRuntimePolicyRead: getter };
        reads = 0;
        for (const caller of [foreign, lookalike, { ...context }]) {
          expect(() => assertGatewayCommittedRuntimePolicyRead(caller, read)).toThrow(
            "NATIVE-SERVING-NOT-CURRENT",
          );
        }
        expect(reads).toBe(0);
        expect(getter).not.toHaveBeenCalled();
        assertGatewayCommittedRuntimePolicyRead(context, read);
        assertGatewayCommittedRuntimePolicyRead(foreign, foreignRead);
        expect(reads).toBeGreaterThan(0);
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("does not associate a genuine NativeR captured outside the constructor getter", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { sharedState, context, managed } = await createL0NativeFixture();
      try {
        const owner = findOwner(sharedState);
        if (!owner) {
          throw new Error("Missing real managed owner");
        }
        const direct = captureNativeServingRead(owner);
        if (!direct) {
          throw new Error("Missing direct native read");
        }
        assertNativeServingRead(direct);
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, direct)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
        assertGatewayCommittedRuntimePolicyRead(context, captureL0Read(context));
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("refuses copied and Proxy reads or contexts with zero traps and preserves the original pair", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { context, managed } = await createL0NativeFixture();
      try {
        const read = captureL0Read(context);
        const trap = vi.fn(() => {
          throw new Error("Unexpected proxy trap");
        });
        const handler = {
          get: trap,
          ownKeys: trap,
          getOwnPropertyDescriptor: trap,
          getPrototypeOf: trap,
        };
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, { ...read })).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
        expect(() =>
          assertGatewayCommittedRuntimePolicyRead(context, new Proxy(read, handler)),
        ).toThrow("NATIVE-SERVING-NOT-CURRENT");
        expect(() =>
          assertGatewayCommittedRuntimePolicyRead(new Proxy(context, handler), read),
        ).toThrow("NATIVE-SERVING-NOT-CURRENT");
        expect(trap).not.toHaveBeenCalled();
        assertGatewayCommittedRuntimePolicyRead(context, read);
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("rejects last-use closure from the real managed activation fingerprint getter", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      let closePrelude = () => {};
      const config: OpenClawConfig = {
        gateway: { port: 19103 },
        get logging() {
          closePrelude();
          return { level: "info" };
        },
      };
      const { sharedState, params, context, published, managed } =
        await createL0NativeFixture(config);
      try {
        const read = captureL0Read(context);
        const owner = findOwner(sharedState);
        assertGatewayCommittedRuntimePolicyRead(context, read);
        closePrelude = () => {
          params.runtime.lifecycle.closePreludeStarted = true;
        };
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
        expect(params.runtime.lifecycle.closePreludeStarted).toBe(true);
        expect(managed.isConfigReloadSettled()).toBe(true);
        expect(findOwner(sharedState)).toBe(owner);
        expect(getRuntimeConfigSnapshot()).toBe(published);
        closePrelude = () => {};
        params.runtime.lifecycle.closePreludeStarted = false;
        assertNativeServingRead(read);
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });

  it("rechecks a private Core settled predicate that closes G while NativeR stays healthy", () => {
    let closePrelude = () => {};
    const { params, context, lifetime } = createL0NativeCallbackFixture(() => {
      closePrelude();
      return true;
    });
    const read = captureL0Read(context);
    assertGatewayCommittedRuntimePolicyRead(context, read);
    closePrelude = () => {
      params.runtime.lifecycle.closePreludeStarted = true;
    };
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
      "NATIVE-SERVING-NOT-CURRENT",
    );
    expect(lifetime.signal.aborted).toBe(false);
    closePrelude = () => {};
    params.runtime.lifecycle.closePreludeStarted = false;
    assertNativeServingRead(read);
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
      "NATIVE-SERVING-NOT-CURRENT",
    );
  });

  it("contains a native callback exception and does not revive OLD after recovery", () => {
    let fail = false;
    const { context } = createL0NativeCallbackFixture(() => {
      if (fail) {
        throw new Error("fixture native callback unavailable");
      }
      return true;
    });
    const read = captureL0Read(context);
    fail = true;
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
      "NATIVE-SERVING-NOT-CURRENT",
    );
    fail = false;
    assertNativeServingRead(read);
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
      "NATIVE-SERVING-NOT-CURRENT",
    );
    assertGatewayCommittedRuntimePolicyRead(context, captureL0Read(context));
  });

  it("refuses after real managed stop and native lifetime abort without borrowing a replacement", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { context, managed } = await createL0NativeFixture();
      const read = captureL0Read(context);
      await managed.stop();
      expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
        "NATIVE-SERVING-NOT-CURRENT",
      );
      expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
      clearSecretsRuntimeSnapshot();
    });
    const { context, lifetime } = createL0NativeCallbackFixture(() => true);
    const read = captureL0Read(context);
    lifetime.abort();
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).toThrow(
      "NATIVE-SERVING-NOT-CURRENT",
    );
    expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
  });

  it("keeps OLD terminal but admits a NEW capture after a native epoch on the same healthy owner", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const { sharedState, context, published, managed } = await createL0NativeFixture();
      try {
        const old = captureL0Read(context);
        const owner = findOwner(sharedState);
        if (!owner) {
          throw new Error("Missing real managed owner");
        }
        const ticket = reserveNativeTransition(owner);
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, old)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
        expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
        finishNativeTransition(ticket);
        expect(findOwner(sharedState)).toBe(owner);
        const fresh = captureL0Read(context);
        expect(fresh).not.toBe(old);
        assertGatewayCommittedRuntimePolicyRead(context, fresh);
        assertGatewayCommittedRuntimePolicyRead(context, fresh);
        expect(readNativeServingReadConfig(fresh)).toBe(published);
        expect(() => assertGatewayCommittedRuntimePolicyRead(context, old)).toThrow(
          "NATIVE-SERVING-NOT-CURRENT",
        );
      } finally {
        await managed.stop();
        clearSecretsRuntimeSnapshot();
      }
    });
  });
});

describe("createGatewayRequestContext", () => {
  it("C4 does not turn legacy committed config and settled callbacks into a native policy read", () => {
    const fallback = { gateway: { port: 19103 } };
    const params = makeContextParams();
    params.runtime.runtimeState.configReloader = {
      getCommittedRuntimeConfig: () => fallback,
      isConfigReloadSettled: () => true,
    };
    const context = createGatewayRequestContext(params);
    expect(context.getCommittedRuntimeConfig?.()).toBe(fallback);
    expect(context.isConfigReloadSettled()).toBe(true);
    const capture = context.getCommittedRuntimePolicyRead;
    if (!capture) {
      throw new Error("Missing native context policy reader");
    }
    expect(capture()).toBeUndefined();
    params.runtime.lifecycle.closePreludeStarted = true;
    expect(capture()).toBeUndefined();
    expect(context.getCommittedRuntimeConfig?.()).toBe(fallback);
    expect(context.isConfigReloadSettled()).toBe(false);
  });

  it("prepares every recipient before the real merge's first notification and contains resolution failure", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const source = ensureProfileForEmail("event-source@example.test");
      const target = ensureProfileForEmail("event-target@example.test");
      const third = ensureProfileForEmail("event-third@example.test");
      const frames: Array<{ connId: string; event: string; recipientProfileId?: string }> = [];
      const clients = new GatewayClientRegistry();
      for (const [index, profile] of [source, target, third].entries()) {
        clients.add({
          ...makeGatewayClient({
            connId: `event-${index}`,
            clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
            scopes: ["operator.admin"],
          }),
          usesSharedGatewayAuth: false,
          presenceKey: `event-${index}`,
          authenticatedUserProfile: {
            profileId: profile.id,
            displayName: null,
            avatarRevision: "1",
            hasAvatar: false,
            updatedAt: profile.updatedAt,
          },
          socket: {
            readyState: 1,
            bufferedAmount: 0,
            close: vi.fn(),
            send: (wire: string, done?: () => void) => {
              frames.push({ connId: `event-${index}`, ...JSON.parse(wire) });
              done?.();
            },
          } as unknown as GatewayWsClient["socket"],
        });
      }
      const peers = [...clients];
      const broadcaster = createGatewayBroadcaster({
        clients,
        preparePresenceProjection: (presence) => () => presence,
      });
      const params = makeContextParams({ clients, ...broadcaster });
      const context = createGatewayRequestContext(params);
      for (const peer of peers) {
        prepareGatewayRecipientProfile(peer);
      }
      const subscribers = createSessionEventSubscriberRegistry();
      for (const peer of peers) {
        subscribers.subscribe(peer.connId);
      }
      const chatRunState = createChatRunState();
      const subscriptions = startGatewayEventSubscriptions({
        ...broadcaster,
        signal: new AbortController().signal,
        log: params.log,
        nodeHasSessionSubscribers: () => false,
        nodeSendToSession: vi.fn(),
        agentRunSeq: new Map(),
        chatRunState,
        toolEventRecipients: chatRunState.toolEventRecipients,
        sessionEventSubscribers: subscribers,
        sessionMessageSubscribers: createSessionMessageSubscriberRegistry(),
        chatAbortControllers: new Map(),
        restartRecoveryCandidates: new Map(),
        terminalSessions: { closeTaskSessions: vi.fn() },
        refreshConnectedUserProfiles: () => context.refreshConnectedUserProfile?.(),
      });
      try {
        linkEmail("event-source@example.test", target.id);
        for (const [index, profileId] of [target.id, target.id, third.id].entries()) {
          const first = frames.find((frame) => frame.connId === `event-${index}`);
          expect(first).toMatchObject({ recipientProfileId: profileId });
          expect(
            frames
              .filter((frame) => frame.connId === `event-${index}`)
              .every((frame) => frame.recipientProfileId === profileId),
          ).toBe(true);
        }
        expect(frames.some((frame) => frame.event === "sessions.changed")).toBe(true);
        const authenticated = peers.map((peer) => peer.authenticatedUserProfile);
        const resolve = vi
          .spyOn(userProfileCatalog, "readUserProfileIdentity")
          .mockImplementationOnce(() => {
            throw new Error("fixture storage unavailable");
          });
        try {
          context.refreshConnectedUserProfile?.();
          expect(peers[0]!.preparedRecipientProfileId).toBeUndefined();
          expect(peers[1]!.preparedRecipientProfileId).toBe(target.id);
          expect(peers[2]!.preparedRecipientProfileId).toBe(third.id);
          peers.forEach((peer, index) => {
            expect(peer.authenticatedUserProfile).toBe(authenticated[index]);
            expect(peer.invalidated).not.toBe(true);
          });
        } finally {
          resolve.mockRestore();
        }
      } finally {
        subscriptions.lifecycleUnsub();
        subscriptions.heartbeatUnsub();
        subscriptions.transcriptUnsub();
        await subscriptions.agentUnsub();
        await subscriptions.taskUnsub();
      }
    });
  });

  it("reuses the canonical connection liveness predicate", () => {
    const isConnectionActive = vi.fn(() => true);
    const params = makeContextParams();
    Object.assign(params.runtime, { isConnectionActive });

    const context = createGatewayRequestContext(params);

    expect(context.isConnectionActive).toBe(isConnectionActive);
  });

  it("cleans connection-scoped replace-sets with the other session subscriptions", () => {
    const order: string[] = [];
    const unsubscribeAllSessionEvents = vi.fn(() => order.push("session-events"));
    const unsubscribeMessages = vi.fn(() => order.push("messages"));
    const removeObserver = vi.fn(() => order.push("observer"));
    const unsubscribePullRequests = vi.fn(() => order.push("pull-requests"));
    const unsubscribeViewerPresence = vi.fn(() => order.push("presence"));
    const params = makeContextParams();
    params.runtime.sessionEventSubscribers.unsubscribe = unsubscribeAllSessionEvents;
    params.runtime.sessionMessageSubscribers.unsubscribeAll = unsubscribeMessages;
    params.runtime.sessionObserver.removeConnection = removeObserver;
    params.runtime.runtimeState.controlUiSessionPullRequests = {
      unsubscribe: unsubscribePullRequests,
    } as never;
    params.runtime.runtimeState.sessionViewerPresence = {
      unsubscribe: unsubscribeViewerPresence,
    } as never;
    const context = createGatewayRequestContext(params);

    context.unsubscribeAllSessionEvents("conn-control-ui");

    expect(unsubscribeAllSessionEvents).toHaveBeenCalledWith("conn-control-ui");
    expect(unsubscribeMessages).toHaveBeenCalledWith("conn-control-ui");
    expect(removeObserver).toHaveBeenCalledWith("conn-control-ui");
    expect(unsubscribePullRequests).toHaveBeenCalledWith("conn-control-ui");
    expect(unsubscribeViewerPresence).toHaveBeenCalledWith("conn-control-ui");
    expect(order).toEqual(["session-events", "messages", "observer", "pull-requests", "presence"]);
  });

  it("reads the portal service after its transport becomes available", () => {
    let portalService: GatewayRequestContext["portalService"];
    const params = makeContextParams();
    params.runtime.transportBridge.getPortalService = () => portalService;
    const context = createGatewayRequestContext(params);

    expect(context.portalService).toBeUndefined();
    portalService = {
      open: vi.fn(async () => {
        throw new Error("unused");
      }),
      list: vi.fn(() => []),
      listWorkerPortals: vi.fn(() => []),
      close: vi.fn(async () => {}),
      closeWorkerPortals: vi.fn(async () => {}),
      closeAll: vi.fn(async () => {}),
    };
    expect(context.portalService).toBe(portalService);
    portalService = undefined;
    expect(context.portalService).toBeUndefined();
  });

  it("reads cron state live from runtime state", () => {
    const cronA = { start: vi.fn(), stop: vi.fn() } as never;
    const cronB = { start: vi.fn(), stop: vi.fn() } as never;
    const runtimeState: RequestRuntime["runtimeState"] = {
      cronState: makeCronState({ cron: cronA, storePath: "/tmp/cron-a" }),
      configReloader: { isConfigReloadSettled: () => true },
    };

    const context = createGatewayRequestContext(makeContextParams({ runtimeState }));

    expect(context.cron).toBe(cronA);
    expect(context.cronStorePath).toBe("/tmp/cron-a");

    runtimeState.cronState = makeCronState({ cron: cronB, storePath: "/tmp/cron-b" });

    expect(context.cron).toBe(cronB);
    expect(context.cronStorePath).toBe("/tmp/cron-b");
  });

  it("reads config reload status and readiness through the live kernel bridge", () => {
    let status: "active" | "disabled" | undefined;
    let settled = true;
    const params = makeContextParams();
    params.runtime.kernel.getConfigReloaderHotReloadStatus = () => status;
    params.runtime.runtimeState.configReloader.isConfigReloadSettled = () => settled;
    const context = createGatewayRequestContext(params);

    expect(context.getConfigReloaderHotReloadStatus?.()).toBeUndefined();
    expect(context.getDeferredChannelReloads?.()).toEqual([]);

    status = "active";
    expect(context.getConfigReloaderHotReloadStatus?.()).toBe("active");
    expect(context.isConfigReloadSettled()).toBe(true);
    settled = false;
    expect(context.isConfigReloadSettled()).toBe(false);

    status = "disabled";
    expect(context.getConfigReloaderHotReloadStatus?.()).toBe("disabled");

    const deferred = [{ channel: "discord", publicationPending: true }];
    params.runtime.runtimeState.configReloader = {
      isConfigReloadSettled: () => false,
      getDeferredChannelReloads: () => deferred,
    };
    expect(context.getDeferredChannelReloads?.()).toEqual(deferred);

    params.runtime.lifecycle.closePreludeStarted = true;
    expect(context.getDeferredChannelReloads?.()).toEqual([]);
  });

  it("publishes worker services through the kernel bridge", () => {
    const workerPlacementDiskSpaceReader = { read: vi.fn(), version: vi.fn(() => 1) };
    const repositoryWorkspaceMutationService = { mutate: vi.fn() };
    const context = createGatewayRequestContext(
      makeContextParams({
        workerPlacementRuntime: {
          diskSpace: workerPlacementDiskSpaceReader,
          runnerAvailability: undefined,
          repositoryWorkspaceMutationService,
        },
      }),
    );

    expect(context.workerPlacementDiskSpaceReader).toBe(workerPlacementDiskSpaceReader);
    expect(context.workerRepositoryWorkspaceMutationService).toBe(
      repositoryWorkspaceMutationService,
    );
  });

  it("does not treat scoped CLI or backend callers as approval delivery routes", () => {
    const clients = new Set([
      makeGatewayClient({
        connId: "cli",
        clientId: GATEWAY_CLIENT_IDS.CLI,
        scopes: ["operator.admin"],
      }),
      makeGatewayClient({
        connId: "backend",
        clientId: GATEWAY_CLIENT_IDS.GATEWAY_CLIENT,
        mode: GATEWAY_CLIENT_MODES.BACKEND,
        scopes: ["operator.approvals"],
      }),
    ]) as never;
    const context = createGatewayRequestContext(makeContextParams({ clients }));

    expect(context.hasExecApprovalClients?.()).toBe(false);
    expect(context.getApprovalClientConnIds?.()).toEqual(new Set());
    expect(context.getApprovalClientConnIds?.({ approvalKind: "plugin" })).toEqual(new Set());
  });

  it("preserves only clients that handle each approval kind", () => {
    const clients = new Set([
      makeGatewayClient({
        connId: "control-ui",
        clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
        mode: GATEWAY_CLIENT_MODES.WEBCHAT,
        scopes: ["operator.approvals"],
      }),
      makeGatewayClient({
        connId: "ios",
        clientId: GATEWAY_CLIENT_IDS.IOS_APP,
        mode: GATEWAY_CLIENT_MODES.UI,
        scopes: ["operator.admin"],
      }),
      makeGatewayClient({
        connId: "bridge",
        clientId: GATEWAY_CLIENT_IDS.CLI,
        scopes: ["operator.approvals"],
        caps: [GATEWAY_CLIENT_CAPS.APPROVALS],
      }),
      makeGatewayClient({
        connId: "acp",
        clientId: GATEWAY_CLIENT_IDS.CLI,
        scopes: ["operator.approvals"],
        caps: [GATEWAY_CLIENT_CAPS.EXEC_APPROVALS],
      }),
      makeGatewayClient({
        connId: "tui",
        clientId: GATEWAY_CLIENT_IDS.TUI,
        scopes: ["operator.approvals"],
      }),
      makeGatewayClient({
        connId: "plugin-bridge",
        clientId: GATEWAY_CLIENT_IDS.CLI,
        scopes: ["operator.approvals"],
        caps: [GATEWAY_CLIENT_CAPS.PLUGIN_APPROVALS],
      }),
      makeGatewayClient({
        connId: "runtime",
        clientId: GATEWAY_CLIENT_IDS.GATEWAY_CLIENT,
        mode: GATEWAY_CLIENT_MODES.BACKEND,
        scopes: ["operator.approvals"],
        approvalRuntime: true,
      }),
      makeGatewayClient({
        connId: "invalidated-ui",
        clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
        scopes: ["operator.approvals"],
        invalidated: true,
      }),
      makeGatewayClient({
        connId: "unscoped-ui",
        clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
      }),
    ]) as never;
    const context = createGatewayRequestContext(makeContextParams({ clients }));

    expect(context.hasExecApprovalClients?.()).toBe(true);
    expect(context.getApprovalClientConnIds?.()).toEqual(
      new Set(["control-ui", "ios", "bridge", "acp", "runtime"]),
    );
    expect(context.getApprovalClientConnIds?.({ approvalKind: "plugin" })).toEqual(
      new Set(["control-ui", "bridge", "tui", "plugin-bridge", "runtime"]),
    );
    expect(context.getApprovalClientConnIds?.({ approvalKind: "system-agent" })).toEqual(
      new Set(["control-ui", "bridge", "runtime"]),
    );
    expect(context.hasExecApprovalClients?.("control-ui")).toBe(true);
    expect(
      context.getApprovalClientConnIds?.({
        excludeConnId: "control-ui",
        filter: (client) => client.connect.client.id === GATEWAY_CLIENT_IDS.IOS_APP,
      }),
    ).toEqual(new Set(["ios"]));
  });

  it("invalidateClientsForDevice sets the flag on matching clients without closing the socket", () => {
    const target = makeDeviceClient("conn-target", "device-1");
    const unrelated = makeDeviceClient("conn-unrelated", "device-2");
    const clients = new Set([target, unrelated]) as never;
    const invalidateDeviceTransports = vi.fn();
    const invalidateConnectionForPairingChange = vi.fn();

    const context = createGatewayRequestContext(
      makeContextParams({
        clients,
        watchNodeHttpRuntime: {
          invalidateSessionsForDevice: invalidateDeviceTransports,
          disconnectSessionsForDevice: vi.fn(),
        },
        nodeRegistry: { invalidateConnectionForPairingChange } as never,
      }),
    );
    const detached = captureGatewayDeviceRevocation(context, { deviceId: "device-1" }, () => true);
    onTestFinished(detached.release);
    expect(detached.isCurrent()).toBe(true);
    context.invalidateClientsForDevice?.("device-1", { reason: "device-token-rotated" });
    expect(detached.isCurrent()).toBe(false);

    expect((target as { invalidated?: boolean }).invalidated).toBe(true);
    expect((target as { invalidatedReason?: string }).invalidatedReason).toBe(
      "device-token-rotated",
    );
    expect(target.socket.close).not.toHaveBeenCalled();
    expect(invalidateConnectionForPairingChange).toHaveBeenCalledWith(
      "conn-target",
      "device-token-rotated",
    );

    expect((unrelated as { invalidated?: boolean }).invalidated).toBeUndefined();
    expect(unrelated.socket.close).not.toHaveBeenCalled();
    expect(invalidateDeviceTransports).toHaveBeenCalledWith("device-1", {
      reason: "device-token-rotated",
    });
  });

  it("disconnectClientsForDevice also marks the invalidated flag before closing", () => {
    const target = makeDeviceClient("conn-target", "device-1");
    const clients = new Set([target]) as never;
    const disconnectDeviceTransports = vi.fn();

    const context = createGatewayRequestContext(
      makeContextParams({
        clients,
        watchNodeHttpRuntime: {
          invalidateSessionsForDevice: vi.fn(),
          disconnectSessionsForDevice: disconnectDeviceTransports,
        },
      }),
    );
    const detached = captureGatewayDeviceRevocation(context, { deviceId: "device-1" }, () => true);
    onTestFinished(detached.release);
    expect(detached.isCurrent()).toBe(true);
    context.disconnectClientsForDevice?.("device-1");
    expect(detached.isCurrent()).toBe(false);

    expect((target as { invalidated?: boolean }).invalidated).toBe(true);
    expect((target as { invalidatedReason?: string }).invalidatedReason).toBe("device-removed");
    expect(target.socket.close).toHaveBeenCalledWith(4001, "device removed");
    expect(disconnectDeviceTransports).toHaveBeenCalledWith("device-1", undefined);
  });

  it.each(["live", "disconnected"])(
    "disconnects only authority for the reassigned durable profile (%s transport)",
    (transport) => {
      const target = {
        ...makeGatewayClient({
          connId: "profile-target",
          clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
          scopes: ["operator.admin"],
        }),
        authenticatedUserProfile: {
          profileId: "profile-ada",
          displayName: "Ada",
          hasAvatar: false,
          updatedAt: 1,
        },
      };
      const unrelated = {
        ...makeGatewayClient({
          connId: "profile-unrelated",
          clientId: GATEWAY_CLIENT_IDS.CONTROL_UI,
        }),
        authenticatedUserProfile: {
          profileId: "profile-grace",
          displayName: "Grace",
          hasAvatar: false,
          updatedAt: 1,
        },
      };
      const unidentified = makeGatewayClient({
        connId: "shared-secret",
        clientId: GATEWAY_CLIENT_IDS.CLI,
        scopes: ["operator.admin"],
      });
      const clients = new GatewayClientRegistry([target, unrelated, unidentified] as never);
      const releases = Array.from(clients, (peer) => clients.retainRequest(peer));
      onTestFinished(() => {
        releases.forEach((release) => release());
        expect([...clients.authorityClients]).toEqual([...clients]);
      });
      if (transport === "disconnected") {
        clients.clear();
      }
      const context = createGatewayRequestContext(makeContextParams({ clients }));
      target.socket.close.mockImplementation(() => {
        expect((target as { invalidated?: boolean }).invalidated).toBe(true);
      });

      if (transport === "disconnected") {
        expect(context.getClientConnIds?.()).toEqual(new Set());
        expect(context.hasExecApprovalClients?.()).toBe(false);
      }
      context.disconnectClientsForUserProfile?.("profile-ada");

      expect((target as { invalidated?: boolean }).invalidated).toBe(true);
      expect((target as { invalidatedReason?: string }).invalidatedReason).toBe(
        "operator-role-changed",
      );
      expect(target.socket.close).toHaveBeenCalledWith(4001, "operator role changed");
      expect(unrelated.socket.close).not.toHaveBeenCalled();
      expect(unidentified.socket.close).not.toHaveBeenCalled();
    },
  );

  it("invalidateClientsForDevice filters by role when provided", () => {
    const primary = makeDeviceClient("conn-primary", "device-1");
    const secondary = makeDeviceClient("conn-secondary", "device-1", "secondary");
    const clients = new Set([primary, secondary]) as never;

    const context = createGatewayRequestContext(makeContextParams({ clients }));
    context.invalidateClientsForDevice?.("device-1", { role: "primary" });

    expect((primary as { invalidated?: boolean }).invalidated).toBe(true);
    expect((secondary as { invalidated?: boolean }).invalidated).toBeUndefined();
  });
});
