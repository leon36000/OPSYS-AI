import { expect, it, onTestFinished, vi } from "vitest";
import { createNativeChannelIngressOwner } from "../../../test/helpers/native-channel-ingress-owner.js";
import {
  getRuntimeAuthProfileStoreCredentialsRevision,
  getRuntimeAuthProfileStoreSnapshotsRevision,
} from "../../agents/auth-profiles/runtime-snapshots.js";
import { getRuntimeConfigSnapshot } from "../../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { GatewayRequestContext } from "../../gateway/server-methods/types.js";
import {
  assertGatewayCommittedRuntimePolicyRead,
  createGatewayRequestContext,
} from "../../gateway/server-request-context.js";
import { makeContextParams } from "../../gateway/server-request-context.test-support.js";
import {
  assertNativeServingRead,
  readNativeServingReadConfig,
} from "../../gateway/server-runtime-policy-owner.js";
import { SharedGatewaySessionGenerationState } from "../../gateway/server-shared-auth-generation.js";
import { createTestRuntimeSecretsActivator } from "../../gateway/server-startup-config.test-support.js";
import type { PreparedSecretsRuntimeSnapshot } from "../../secrets/runtime.js";
import {
  activateSecretsRuntimeSnapshot,
  clearSecretsRuntimeSnapshot,
} from "../../secrets/runtime.js";
import { recordAcceptedSessionParticipantInput } from "../../sessions/session-participant-input-recording.js";
import {
  sessionParticipantInput,
  type SessionParticipantInputContext,
} from "../../sessions/session-participant-input.js";
import { withOpenClawTestState } from "../../test-utils/openclaw-test-state.js";
import {
  buildChannelInboundEventContext,
  type BuildChannelInboundEventContextParams,
} from "../inbound-event/context.js";
import { createHostChannelInboundEventContextBuilder } from "../inbound-event/host-context-builder.js";
import {
  consumeChannelAdmissionEvidence,
  createChannelAdmissionAudit,
  prepareHostChannelContextAdmissionEvidence,
  readChannelContextAdmissionEvidence,
  readChannelContextGatewayContextResolver,
} from "./admission-evidence.js";
import { bindChannelParticipantInput } from "./participant-input.js";
import type { ChannelIngressContextBinding } from "./runtime-types.js";
import { createHostChannelIngressRuntime } from "./runtime.js";

const recordParticipant = vi.hoisted(() => vi.fn());
vi.mock("../../sessions/session-participant-recording.js", () => ({
  recordSessionParticipantBestEffort: recordParticipant,
}));

it.each([
  "qualified",
  "mixed",
  "stale",
  "retargeted",
  "denied",
  "gateway-replaced-during-ingress",
  "gateway-replaced-during-context",
  "retired-during-context",
] as const)(
  "preserves accepted product identity and exact host ownership: %s",
  async (scenario) => {
    recordParticipant.mockClear();
    const auditEnabled = scenario.includes("during");
    const audit = createChannelAdmissionAudit({ enabled: auditEnabled });
    let gateway = {
      getRuntimeConfig: () => ({}),
      channelAdmissionAudit: audit,
    } as GatewayRequestContext;
    const nativeFixture = createNativeChannelIngressOwner({
      channelId: "test",
      resolveGatewayContext: () => gateway,
    });
    const owner = nativeFixture.owner;
    const resolveIngress = createHostChannelIngressRuntime(owner).resolveStable;
    const key = "agent:main:test:dm:conversation";
    const resolveParticipant = vi.fn((subject: { stableId?: string | number | null }) =>
      subject.stableId === "unknown"
        ? undefined
        : {
            domain: "workspace-one",
            idKind: "user-id",
            id: String(subject.stableId),
          },
    );
    try {
      const sources =
        scenario === "mixed" ? ["profile-collision", "unknown"] : ["profile-collision"];
      const ingress = [];
      const startedAt = Date.now();
      for (const sender of sources) {
        ingress.push(
          await resolveIngress({
            channelId: "test",
            accountId: "local",
            identity: { resolveParticipant },
            subject: { stableId: sender },
            conversation: { kind: "direct", id: "conversation" },
            contextBinding: {
              agentId: "main",
              sessionKey: key,
              messageId: sender,
              inboundEventKind: "user_request",
            },
            dmPolicy: scenario === "gateway-replaced-during-ingress" ? "pairing" : "open",
            groupPolicy: "disabled",
            allowFrom: scenario === "denied" ? [] : ["*"],
            useDefaultPairingStore: false,
            readStoreAllowFrom: async () => {
              await Promise.resolve();
              if (scenario === "gateway-replaced-during-ingress") {
                gateway = Object.assign({}, gateway);
              }
              return [];
            },
          }),
        );
      }
      expect(resolveParticipant).toHaveBeenCalledTimes(sources.length);
      expect(ingress[0]?.ingress.admission).toBe(scenario === "denied" ? "drop" : "dispatch");
      if (scenario === "stale") {
        nativeFixture.retire();
      }
      const context = await createHostChannelInboundEventContextBuilder(
        async (params: BuildChannelInboundEventContextParams) => {
          await Promise.resolve();
          if (scenario === "gateway-replaced-during-context") {
            gateway = Object.assign({}, gateway);
          }
          if (scenario === "retired-during-context") {
            nativeFixture.retire();
          }
          return buildChannelInboundEventContext(params);
        },
        owner,
      )({
        channel: "test",
        accountId: "local",
        messageId: sources.at(-1),
        from: "test:conversation",
        sender: { id: sources.at(-1) },
        conversation: { kind: "direct", id: "conversation" },
        route: {
          agentId: "main",
          routeSessionKey: scenario === "retargeted" ? "agent:main:other" : key,
        },
        reply: { to: "test:conversation" },
        message: { rawBody: "hello" },
        channelIngress: ingress,
      });
      const target = { agentId: "main", sessionKey: key, storePath: "/unused" };
      recordAcceptedSessionParticipantInput({ ...context }, target);
      recordAcceptedSessionParticipantInput(context, target);
      if (scenario === "qualified" || scenario === "mixed") {
        expect(recordParticipant).toHaveBeenCalledTimes(sources.length);
        expect(recordParticipant).toHaveBeenNthCalledWith(1, {
          ...target,
          identity: {
            type: "remote",
            pluginId: "test",
            domain: "workspace-one",
            idKind: "user-id",
            id: "profile-collision",
          },
          promptedAt: expect.any(Number),
        });
        expect(recordParticipant.mock.calls[0]?.[0].promptedAt).toBeGreaterThanOrEqual(startedAt);
        if (scenario === "mixed") {
          expect(recordParticipant).toHaveBeenNthCalledWith(2, {
            ...target,
            identity: {
              type: "observation",
              pluginId: "test",
              accountId: "local",
              senderKind: "unknown",
              id: "unknown",
            },
            promptedAt: expect.any(Number),
          });
        }
      } else {
        expect(recordParticipant).not.toHaveBeenCalled();
      }
      if (auditEnabled) {
        expect(
          consumeChannelAdmissionEvidence(readChannelContextAdmissionEvidence(context)),
        ).toMatchObject({ ingressState: "unknown" });
        expect(readChannelContextGatewayContextResolver(context)).toBeUndefined();
      } else {
        expect(readChannelContextAdmissionEvidence(context)).toBeUndefined();
      }
      expect(ingress[0]).not.toHaveProperty("participant");
    } finally {
      nativeFixture.retire();
      audit.close();
    }
  },
);

function prepareL1WitnessSnapshot(config: OpenClawConfig): PreparedSecretsRuntimeSnapshot {
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
async function createL1NativeWitnessFixture(
  authored: OpenClawConfig = { gateway: { port: 19103 } },
) {
  const sharedState = new SharedGatewaySessionGenerationState({ current: "A", required: null });
  const params = makeContextParams({ sharedGatewaySessionGenerationState: sharedState });
  const context = createGatewayRequestContext(params);
  expect(context.getCommittedRuntimePolicyRead?.()).toBeUndefined();
  activateSecretsRuntimeSnapshot(prepareL1WitnessSnapshot(authored));
  const published = getRuntimeConfigSnapshot();
  if (!published) {
    throw new Error("Missing native activation fixture");
  }
  expect(published).not.toBe(authored);
  const { createDefaultDeps } = await import("../../cli/deps.js");
  const { createTestRegistry } = await import("../../test-utils/channel-plugins.js");
  const { createChannelManager } = await import("../../gateway/server-channels.js");
  const { createDefaultGatewayReloadState, createValidConfigSnapshot } =
    await import("../../gateway/server-reload-handlers.config.test-support.js");
  const { startManagedGatewayConfigReloader } =
    await import("../../gateway/server-reload-managed.js");
  const modelRuntime = await import("../../gateway/server-reload-model-runtime-scope.js");
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
      prepareL1WitnessSnapshot(config),
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

// L1 native control precedes any future API: real StageA/managed/G/R, no keeper grant.
it("L1-NATIVE-WITNESS retains an actual managed publication before keeper APIs", async () => {
  await withOpenClawTestState({ scenario: "minimal" }, async () => {
    const { context, published, managed } = await createL1NativeWitnessFixture();
    const read = context.getCommittedRuntimePolicyRead?.();
    expect(read).toBeDefined();
    expect(managed.isConfigReloadSettled()).toBe(true);
    expect(managed.getCommittedRuntimeConfig?.()).toBe(published);
    expect(() => assertNativeServingRead(read)).not.toThrow();
    if (!read) {
      throw new Error("Native witness read missing");
    }
    expect(() => assertGatewayCommittedRuntimePolicyRead(context, read)).not.toThrow();
    expect(readNativeServingReadConfig(read)).toBe(published);
    expect(getRuntimeConfigSnapshot()).toBe(published);
  });
});

// G-only view coherence: H is native; request-context support services remain test doubles.
// These cases prove neither a serving publication/grant nor command-owner authority.
async function prepareGOnlyParticipantHandoff(
  fixture: ReturnType<typeof createNativeChannelIngressOwner>,
  resolveParticipant: (subject: { stableId?: string | number | null }) => {
    domain: string;
    idKind: string;
    id: string;
  },
  messageId: string,
) {
  const binding: ChannelIngressContextBinding = {
    agentId: "main",
    sessionKey: "agent:main:test:dm:g-only-conversation",
    messageId,
    inboundEventKind: "user_request",
  };
  const ingress = await fixture.channel.inbound.ingress.resolveStable({
    channelId: "test",
    accountId: "local",
    identity: { authentication: "asserted", resolveParticipant },
    subject: { stableId: "g-only-person" },
    conversation: { kind: "direct", id: "g-only-conversation" },
    contextBinding: binding,
    dmPolicy: "open",
    groupPolicy: "disabled",
    allowFrom: ["*"],
    useDefaultPairingStore: false,
    readStoreAllowFrom: async () => [],
  });
  expect(ingress.ingress.admission).toBe("dispatch");
  const contextParams: BuildChannelInboundEventContextParams = {
    channel: "test",
    accountId: "local",
    messageId,
    from: "test:g-only-conversation",
    sender: { id: "g-only-person" },
    conversation: { kind: "direct", id: "g-only-conversation" },
    route: { agentId: "main", routeSessionKey: binding.sessionKey },
    reply: { to: "test:g-only-conversation" },
    message: { rawBody: "hello", inboundEventKind: "user_request" },
  };
  // Accept the real one-use private handoff. Merely resolving would not authorize takeParticipant.
  const preparation = prepareHostChannelContextAdmissionEvidence({
    owner: fixture.owner,
    channelId: "test",
    accountId: "local",
    ingress,
    rawPrincipalRef: "g-only-person",
    contextParams,
  });
  expect(preparation).toBeDefined();
  expect(fixture.owner.isLive()).toBe(true);
  return { ingress, binding };
}

it("G-ONLY binds one real participant while the exact Gateway view remains A", async () => {
  const gatewayA = createGatewayRequestContext(makeContextParams());
  const fixture = createNativeChannelIngressOwner({
    channelId: "test",
    resolveGatewayContext: () => gatewayA,
  });
  // The existing native helper registers onTestFinished before allocation and checks drain.errors.
  expect(fixture.owner.resolveGatewayContext?.()).toBe(gatewayA);
  const resolveParticipant = vi.fn((subject: { stableId?: string | number | null }) => ({
    domain: "g-only-A",
    idKind: "user-id",
    id: String(subject.stableId),
  }));
  const { ingress, binding } = await prepareGOnlyParticipantHandoff(
    fixture,
    resolveParticipant,
    "g-only-healthy-A",
  );
  const context: SessionParticipantInputContext = {};
  expect(context[sessionParticipantInput]).toBeUndefined();
  let contextReads = 0;
  bindChannelParticipantInput({
    get context() {
      contextReads += 1;
      return context;
    },
    channelId: "test",
    ingress,
    binding,
    owner: fixture.owner,
  });
  expect(contextReads).toBe(1);
  expect(resolveParticipant).toHaveBeenCalledTimes(1);
  expect(fixture.owner.isLive()).toBe(true);
  expect(fixture.owner.resolveGatewayContext?.()).toBe(gatewayA);
  expect(context[sessionParticipantInput]).toEqual([
    {
      identity: {
        type: "remote",
        pluginId: "test",
        domain: "g-only-A",
        idKind: "user-id",
        id: "g-only-person",
      },
      promptedAt: expect.any(Number),
      recorded: false,
    },
  ]);
});

it("G-ONLY rejects a context getter switch to B without poisoning H or a new B handoff", async () => {
  const gatewayA = createGatewayRequestContext(makeContextParams());
  const gatewayB = createGatewayRequestContext(makeContextParams());
  expect(gatewayB).not.toBe(gatewayA);
  let currentGateway = gatewayA;
  const fixture = createNativeChannelIngressOwner({
    channelId: "test",
    resolveGatewayContext: () => currentGateway,
  });
  const resolveParticipant = vi.fn((subject: { stableId?: string | number | null }) => ({
    domain: currentGateway === gatewayA ? "g-only-A" : "g-only-B",
    idKind: "user-id",
    id: String(subject.stableId),
  }));
  const acceptedA = await prepareGOnlyParticipantHandoff(
    fixture,
    resolveParticipant,
    "g-only-rejected-A",
  );
  expect(fixture.owner.resolveGatewayContext?.()).toBe(gatewayA);
  const rejectedContext: SessionParticipantInputContext = {};
  expect(rejectedContext[sessionParticipantInput]).toBeUndefined();
  let rejectedContextReads = 0;
  bindChannelParticipantInput({
    get context() {
      rejectedContextReads += 1;
      currentGateway = gatewayB;
      return rejectedContext;
    },
    channelId: "test",
    ingress: acceptedA.ingress,
    binding: acceptedA.binding,
    owner: fixture.owner,
  });
  expect(rejectedContextReads).toBe(1);
  expect(fixture.owner.isLive()).toBe(true);
  expect(fixture.owner.resolveGatewayContext?.()).toBe(gatewayB);

  // acceptedA has been consumed. Resolve and accept a NEW result under B, never reuse it.
  const acceptedB = await prepareGOnlyParticipantHandoff(
    fixture,
    resolveParticipant,
    "g-only-new-B",
  );
  const contextB: SessionParticipantInputContext = {};
  let contextBReads = 0;
  bindChannelParticipantInput({
    get context() {
      contextBReads += 1;
      return contextB;
    },
    channelId: "test",
    ingress: acceptedB.ingress,
    binding: acceptedB.binding,
    owner: fixture.owner,
  });
  expect(contextBReads).toBe(1);
  expect(resolveParticipant).toHaveBeenCalledTimes(2);
  expect(fixture.owner.isLive()).toBe(true);
  expect(fixture.owner.resolveGatewayContext?.()).toBe(gatewayB);
  expect(contextB[sessionParticipantInput]).toEqual([
    {
      identity: {
        type: "remote",
        pluginId: "test",
        domain: "g-only-B",
        idKind: "user-id",
        id: "g-only-person",
      },
      promptedAt: expect.any(Number),
      recorded: false,
    },
  ]);
  // Last so the fresh-B positive is actually observed even when current production exposes RED.
  expect(rejectedContext[sessionParticipantInput]).toBeUndefined();
});
