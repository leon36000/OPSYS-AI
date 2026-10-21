import { describe, expect, it, vi } from "vitest";
import type { BuildChannelInboundEventContextParams } from "../channels/inbound-event/context.js";
import { createHostChannelInboundEventContextBuilder } from "../channels/inbound-event/host-context-builder.js";
import {
  prepareHostChannelContextAdmissionEvidence,
  readChannelContextAdmissionEvidence,
  readChannelContextGatewayContextResolver,
} from "../channels/message-access/admission-evidence.js";
import type { ChannelIngressHostOwner } from "../channels/message-access/ingress-host-owner.js";
import { bindChannelParticipantInput } from "../channels/message-access/participant-input.js";
import type {
  ChannelIngressIdentityDescriptor,
  ChannelIngressIdentitySubjectInput,
  ResolveChannelMessageIngressParams,
  ResolveStableChannelMessageIngressParams,
} from "../channels/message-access/runtime-types.js";
import * as ingressModule from "../channels/message-access/runtime.js";
import {
  sessionParticipantInput,
  type SessionParticipantInputContext,
} from "../sessions/session-participant-input.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import {
  getPluginInstance,
  getPluginValueInstance,
  type PluginInstanceHandle,
} from "./plugin-instance-scope.js";
import * as lifecycle from "./registry-lifecycle.js";
import { createPluginRuntimeResolver } from "./registry-runtime.js";
import * as stateModule from "./registry-state.js";
import type { PluginRegistryState } from "./registry-state.js";
import { createPluginRegistry } from "./registry.js";
import type { PluginRegistry } from "./registry.js";
import { bindGatewayContextResolver } from "./runtime/gateway-request-scope.js";
import { createPluginRuntime } from "./runtime/index.js";
import { createPluginRecord } from "./status.test-fixtures.js";

const FOREIGN = "Channel ingress host owner origin is unavailable.";
const MISMATCH = "Channel ingress host owner does not match the requested channel.";
const fixtureMetadata = Object.freeze({ fictif: true, channelId: "h3-native-fictif" });
const CHANNEL = fixtureMetadata.channelId;
const logger = { info() {}, warn() {}, error() {}, debug() {} };

type PrimaryFailure = { error: unknown } | undefined;

async function cleanupNative(params: {
  restore: readonly (() => void)[];
  registries: readonly (PluginRegistry | undefined)[];
  instances: readonly (PluginInstanceHandle | undefined)[];
  primaryFailure: PrimaryFailure;
}) {
  const errors: unknown[] = [];
  // Restore every observation first; one restoration failure does not skip the others.
  for (const restore of params.restore) {
    try {
      restore();
    } catch (error) {
      errors.push(error);
    }
  }
  for (const registry of new Set(params.registries)) {
    if (registry) {
      try {
        lifecycle.markPluginRegistryRetired(registry);
      } catch (error) {
        errors.push(error);
      }
    }
  }
  // A drain deadline is a returned outcome. Attempt ALL exact instances before failing.
  for (const instance of new Set(params.instances)) {
    if (instance) {
      try {
        const result = await instance.drain({ includeConsumers: true });
        errors.push(...result.errors);
      } catch (error) {
        errors.push(error);
      }
    }
  }
  if (errors.length > 0) {
    if (params.primaryFailure) {
      throw new AggregateError(
        [params.primaryFailure.error, ...errors],
        "HARNESS_NONQUAL: native cleanup failed after an initial failure.",
        { cause: params.primaryFailure.error },
      );
    }
    throw new AggregateError(errors, "HARNESS_NONQUAL: native cleanup did not complete.");
  }
}

// Observation only: real creator/state factories and their exact return values.
function observeNativeFactories() {
  const hosts: ChannelIngressHostOwner[] = [];
  const states: PluginRegistryState[] = [];
  const originalHost = ingressModule.createHostChannelIngressRuntime;
  const originalState = stateModule.createPluginRegistryState;
  let observationsClosed = false;
  const hostSpy = (() => {
    try {
      return vi
        .spyOn(ingressModule, "createHostChannelIngressRuntime")
        .mockImplementation(function (this: unknown, ...args: Parameters<typeof originalHost>) {
          hosts.push(args[0]);
          return originalHost.apply(this, args);
        });
    } catch (error) {
      throw new Error("HARNESS_BLOCKED: native host creator cannot be observed.", { cause: error });
    }
  })();
  try {
    const stateSpy = vi
      .spyOn(stateModule, "createPluginRegistryState")
      .mockImplementation(function (this: unknown, ...args: Parameters<typeof originalState>) {
        const state = originalState.apply(this, args);
        states.push(state);
        return state;
      });
    return {
      hosts,
      states,
      close() {
        if (observationsClosed) {
          return;
        }
        observationsClosed = true;
        const errors: unknown[] = [];
        for (const restore of [() => stateSpy.mockRestore(), () => hostSpy.mockRestore()]) {
          try {
            restore();
          } catch (error) {
            errors.push(error);
          }
        }
        if (errors.length > 0) {
          throw new AggregateError(
            errors,
            "HARNESS_NONQUAL: native observation restoration failed.",
          );
        }
      },
    };
  } catch (error) {
    try {
      hostSpy.mockRestore();
    } catch (cleanupError) {
      throw new AggregateError(
        [error, cleanupError],
        "HARNESS_BLOCKED: native observation failed.",
        {
          cause: cleanupError,
        },
      );
    }
    throw new Error("HARNESS_BLOCKED: canonical ESM namespace cannot be observed.", {
      cause: error,
    });
  }
}

async function nativeFixture(observation: ReturnType<typeof observeNativeFactories>) {
  const runtime = createPluginRuntime();
  // Real runtime, deliberately NO Gateway. This does not prove G/R or Host assignment.
  bindGatewayContextResolver(runtime.subagent, () => undefined);
  const builder = createPluginRegistry({ logger, runtime, activateGlobalSideEffects: false });
  const record = createPluginRecordForFixture();
  try {
    const api = builder.createApi(record, { config: {}, registrationMode: "full" });
    const instance = getPluginInstance(record);
    if (!instance) {
      throw new Error("Native API did not retain its plugin instance.");
    }
    instance.run(() =>
      api.registerChannel({ plugin: createChannelTestPluginBase({ id: CHANNEL }) }),
    );
    builder.registry.plugins.push(record);
    lifecycle.markPluginRegistryActive(builder.registry);
    const registration = builder.registry.channels.find((entry) => entry.pluginId === record.id);
    const resolve = registration?.resolveChannelRuntime;
    if (!registration || !resolve) {
      throw new Error("Native channel registration has no resolver.");
    }
    const channel = resolve();
    const host = observation.hosts.at(-1);
    const state = observation.states.at(-1);
    if (!host || !state) {
      throw new Error("HARNESS_BLOCKED: native factory observation missing.");
    }
    expect(state.registry).toBe(builder.registry);
    expect(getPluginValueInstance(registration.plugin)).toBe(instance);
    return { runtime, builder, record, instance, registration, resolve, channel, host, state };
  } catch (error) {
    await cleanupNative({
      restore: [observation.close],
      registries: [builder.registry],
      instances: [getPluginInstance(record)],
      primaryFailure: { error },
    });
    throw error;
  }
}

// Metadata is fictitious; registry/runtime/instance/slot are actual production factories.
function createPluginRecordForFixture() {
  return createPluginRecord({ id: CHANNEL, origin: "bundled" });
}

function stableParams(channelId: string = CHANNEL) {
  return {
    channelId,
    accountId: "default",
    identity: {},
    subject: { stableId: "h3-person-fictif" },
    conversation: { kind: "direct", id: "h3-dm-fictif" },
    dmPolicy: "allowlist",
    allowFrom: ["h3-person-fictif"],
    useDefaultPairingStore: false,
    readStoreAllowFrom: async () => [],
    contextBinding: {
      agentId: "main",
      sessionKey: "agent:main:h3-native-fictif:dm:h3-person-fictif",
      messageId: "h3-message-fictif",
      inboundEventKind: "user_request",
    },
  } satisfies ResolveStableChannelMessageIngressParams;
}

function participantParams(
  identity: ChannelIngressIdentityDescriptor,
  subject: ChannelIngressIdentitySubjectInput,
): ResolveChannelMessageIngressParams & {
  contextBinding: NonNullable<ResolveChannelMessageIngressParams["contextBinding"]>;
} {
  return {
    ...stableParams(),
    identity,
    subject,
    event: { kind: "message", authMode: "inbound", mayPair: false },
    policy: { dmPolicy: "open", groupPolicy: "disabled" },
    allowFrom: ["*"],
  };
}

function buildParams(): BuildChannelInboundEventContextParams {
  return {
    channel: CHANNEL,
    accountId: "default",
    from: "h3:dm:fictif",
    sender: { id: "h3-person-fictif" },
    conversation: { kind: "direct", id: "h3-dm-fictif" },
    route: {
      agentId: "main",
      routeSessionKey: "agent:main:h3-native-fictif:dm:h3-person-fictif",
    },
    reply: { to: "h3:dm:fictif" },
    messageId: "h3-message-fictif",
    message: { rawBody: "hello H3 fictif", inboundEventKind: "user_request" },
  };
}

function counters() {
  return {
    ownerGetters: 0,
    ownerCalls: 0,
    traps: 0,
    nativeLiveness: 0,
    params: 0,
    identity: 0,
    participant: 0,
    store: 0,
    builder: 0,
  };
}

type Counts = ReturnType<typeof counters>;
type ForeignMode = "literal" | "copy" | "proxy";

function observeLiveness(count: Counts) {
  const originalActive = lifecycle.isPluginRecordActive;
  return vi.spyOn(lifecycle, "isPluginRecordActive").mockImplementation(function (
    this: unknown,
    ...args: Parameters<typeof originalActive>
  ) {
    count.nativeLiveness += 1;
    return originalActive.apply(this, args);
  });
}

function foreignOwner(mode: ForeignMode, host: ChannelIngressHostOwner, count: Counts) {
  if (mode === "literal") {
    return {
      get channelId() {
        count.ownerGetters += 1;
        return CHANNEL;
      },
      get isLive() {
        count.ownerGetters += 1;
        return () => {
          count.ownerCalls += 1;
          return host.isLive();
        };
      },
      get resolveGatewayContext() {
        count.ownerGetters += 1;
        return () => {
          count.ownerCalls += 1;
          return host.resolveGatewayContext?.();
        };
      },
    } satisfies ChannelIngressHostOwner;
  }
  if (mode === "copy") {
    return { ...host };
  }
  return new Proxy(host, {
    get(target, key, receiver) {
      count.traps += 1;
      return Reflect.get(target, key, receiver);
    },
    getPrototypeOf(target) {
      count.traps += 1;
      return Reflect.getPrototypeOf(target);
    },
    ownKeys(target) {
      count.traps += 1;
      return Reflect.ownKeys(target);
    },
    getOwnPropertyDescriptor(target, key) {
      count.traps += 1;
      return Reflect.getOwnPropertyDescriptor(target, key);
    },
  });
}

function guardedParams(count: Counts): ResolveStableChannelMessageIngressParams {
  const plain = stableParams();
  return {
    ...plain,
    get channelId() {
      count.params += 1;
      return CHANNEL;
    },
    get identity() {
      count.identity += 1;
      return {
        get resolveParticipant() {
          count.participant += 1;
          return () => {
            count.participant += 1;
            return undefined;
          };
        },
      };
    },
    readStoreAllowFrom: async () => {
      count.store += 1;
      return [];
    },
  };
}

describe("H3 native host slot provenance — local fictitious messages, no G/R claim", () => {
  it("retains one authentic cached H through repeated native use", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    try {
      fixture = await nativeFixture(observation);
      expect(fixture.host.isLive()).toBe(true);
      expect(fixture.resolve()).toBe(fixture.channel);
      expect(observation.hosts).toHaveLength(1);
      for (let index = 0; index < 2; index += 1) {
        const result = await ingressModule
          .createHostChannelIngressRuntime(fixture.host)
          .resolveStable(stableParams());
        expect(result.ingress.admission).toBe("dispatch");
        expect(fixture.host.isLive()).toBe(true);
      }
      // Policy dispatch is not model/device dispatch or a Gateway grant.
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [fixture?.builder.registry],
        instances: [fixture?.instance],
        primaryFailure,
      });
    }
  });

  it.each<ForeignMode>(["literal", "copy", "proxy"])(
    "refuses %s H before any owner/params/identity/participant/store access",
    async (mode) => {
      const observation = observeNativeFactories();
      let primaryFailure: PrimaryFailure;
      let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      let nativeSpy: ReturnType<typeof observeLiveness> | undefined;
      try {
        fixture = await nativeFixture(observation);
        expect(fixture.host.isLive()).toBe(true);
        const count = counters();
        nativeSpy = observeLiveness(count);
        expect(fixture.host.isLive()).toBe(true);
        if (count.nativeLiveness === 0) {
          throw new Error(
            "HARNESS_BLOCKED: native liveness observation has no call-through witness.",
          );
        }
        count.nativeLiveness = 0;
        const foreign = foreignOwner(mode, fixture.host, count);
        let failure: unknown;
        try {
          await ingressModule
            .createHostChannelIngressRuntime(foreign)
            .resolveStable(guardedParams(count));
        } catch (error) {
          failure = error;
        }
        expect(count).toEqual(counters());
        expect(failure).toEqual(new Error(FOREIGN));
        nativeSpy.mockRestore();
        nativeSpy = undefined;
        expect(fixture.host.isLive()).toBe(true);
        expect(
          (await fixture.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
        ).toBe("dispatch");
      } catch (error) {
        primaryFailure = { error };
        throw error;
      } finally {
        await cleanupNative({
          restore: [observation.close, () => nativeSpy?.mockRestore()],
          registries: [fixture?.builder.registry],
          instances: [fixture?.instance],
          primaryFailure,
        });
      }
    },
  );

  it.each<ForeignMode>(["literal", "copy", "proxy"])(
    "refuses %s H at builder entry before params or ordinary builder",
    async (mode) => {
      const observation = observeNativeFactories();
      let primaryFailure: PrimaryFailure;
      let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      let nativeSpy: ReturnType<typeof observeLiveness> | undefined;
      try {
        fixture = await nativeFixture(observation);
        const count = counters();
        nativeSpy = observeLiveness(count);
        expect(fixture.host.isLive()).toBe(true);
        if (count.nativeLiveness === 0) {
          throw new Error(
            "HARNESS_BLOCKED: native liveness observation has no call-through witness.",
          );
        }
        count.nativeLiveness = 0;
        const plain = buildParams();
        const guarded = {
          ...plain,
          get channel() {
            count.params += 1;
            return CHANNEL;
          },
          get sender() {
            count.identity += 1;
            return plain.sender;
          },
        } satisfies BuildChannelInboundEventContextParams;
        let failure: unknown;
        try {
          const build = createHostChannelInboundEventContextBuilder(
            (_params: BuildChannelInboundEventContextParams) => {
              count.builder += 1;
              return {};
            },
            foreignOwner(mode, fixture.host, count),
          );
          await build(guarded);
        } catch (error) {
          failure = error;
        }
        expect(count).toEqual(counters());
        expect(failure).toEqual(new Error(FOREIGN));
        nativeSpy.mockRestore();
        nativeSpy = undefined;
        expect(fixture.host.isLive()).toBe(true);
      } catch (error) {
        primaryFailure = { error };
        throw error;
      } finally {
        await cleanupNative({
          restore: [observation.close, () => nativeSpy?.mockRestore()],
          registries: [fixture?.builder.registry],
          instances: [fixture?.instance],
          primaryFailure,
        });
      }
    },
  );

  it("refuses a wrong channel locally then preserves a healthy native request", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    try {
      fixture = await nativeFixture(observation);
      const count = counters();
      const wrong = {
        ...stableParams("h3-other-fictif"),
        get identity() {
          count.identity += 1;
          return {
            resolveParticipant: () => {
              count.participant += 1;
              return undefined;
            },
          };
        },
        readStoreAllowFrom: async () => {
          count.store += 1;
          return [];
        },
      } satisfies ResolveStableChannelMessageIngressParams;
      let failure: unknown;
      try {
        await ingressModule.createHostChannelIngressRuntime(fixture.host).resolveStable(wrong);
      } catch (error) {
        failure = error;
      }
      expect(count).toEqual(counters());
      expect(failure).toEqual(new Error(MISMATCH));
      expect(fixture.host.isLive()).toBe(true);
      expect(
        (await fixture.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [fixture?.builder.registry],
        instances: [fixture?.instance],
        primaryFailure,
      });
    }
  });

  it("keeps two native resolver slots healthy for the same state and record", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    try {
      fixture = await nativeFixture(observation);
      const second = createPluginRuntimeResolver(fixture.state).resolveRegisteredChannelRuntime(
        fixture.record,
      );
      const secondHost = observation.hosts.at(-1);
      if (!secondHost) {
        throw new Error("Second native creator was not observed.");
      }
      expect(secondHost).not.toBe(fixture.host);
      expect(secondHost.isLive()).toBe(true);
      expect(fixture.host.isLive()).toBe(true);
      expect((await second.inbound.ingress.resolveStable(stableParams())).ingress.admission).toBe(
        "dispatch",
      );
      expect(
        (await fixture.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
      const foreignHandoff = await fixture.channel.inbound.ingress.resolveStable(stableParams());
      const refusedContext = await second.inbound.buildContext({
        ...buildParams(),
        channelIngress: foreignHandoff,
      });
      expect(readChannelContextGatewayContextResolver(refusedContext)).toBeUndefined();
      expect(secondHost.isLive()).toBe(true);
      expect(fixture.host.isLive()).toBe(true);
      for (const channel of [fixture.channel, second]) {
        const ownHandoff = await channel.inbound.ingress.resolveStable(stableParams());
        const ownContext = await channel.inbound.buildContext({
          ...buildParams(),
          channelIngress: ownHandoff,
        });
        // This is only a native resolver carrier: invoking it still returns NO Gateway.
        const resolver = readChannelContextGatewayContextResolver(ownContext);
        expect(typeof resolver).toBe("function");
        expect(resolver?.()).toBeUndefined();
      }
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [fixture?.builder.registry],
        instances: [fixture?.instance],
        primaryFailure,
      });
    }
  });

  it("follows actual same-record adoption and keeps H alive after birth A retires", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    let successor: ReturnType<typeof createPluginRegistry> | undefined;
    try {
      fixture = await nativeFixture(observation);
      successor = createPluginRegistry({
        logger,
        runtime: fixture.runtime,
        activateGlobalSideEffects: false,
      });
      successor.registry.plugins.push(fixture.record);
      successor.registry.channels.push(fixture.registration);
      lifecycle.markPluginRegistryActive(successor.registry);
      expect(lifecycle.getPluginRecordRegistry(fixture.builder.registry, fixture.record)).toBe(
        successor.registry,
      );
      const currentEntry = successor.registry.channels[0];
      if (!currentEntry) {
        throw new Error("Adopted native registration is absent.");
      }
      expect(getPluginValueInstance(currentEntry.plugin)).toBe(fixture.instance);
      lifecycle.markPluginRegistryRetired(fixture.builder.registry);
      expect(fixture.host.isLive()).toBe(true);
      expect(
        (await fixture.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
      successor.registry.channels.splice(0);
      expect(fixture.host.isLive()).toBe(false);
      successor.registry.channels.push(currentEntry);
      expect(fixture.host.isLive()).toBe(false);
      const renewedChannel = fixture.resolve();
      const renewedHost = observation.hosts.at(-1);
      if (!renewedHost) {
        throw new Error("Renewed adopted H was not observed.");
      }
      expect(renewedHost).not.toBe(fixture.host);
      expect(renewedHost.isLive()).toBe(true);
      expect(
        (await renewedChannel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [successor?.registry, fixture?.builder.registry],
        instances: [fixture?.instance],
        primaryFailure,
      });
    }
  });

  it("closes the old local slot when the native API replaces the same id", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    let replacement: ReturnType<typeof createPluginRecord> | undefined;
    try {
      fixture = await nativeFixture(observation);
      replacement = createPluginRecordForFixture();
      const api = fixture.builder.createApi(replacement, { config: {}, registrationMode: "full" });
      const replacementInstance = getPluginInstance(replacement);
      if (!replacementInstance) {
        throw new Error("Replacement native instance is absent.");
      }
      replacementInstance.run(() =>
        api.registerChannel({
          plugin: createChannelTestPluginBase({ id: CHANNEL }),
        }),
      );
      fixture.builder.registry.plugins.splice(
        fixture.builder.registry.plugins.indexOf(fixture.record),
        1,
        replacement,
      );
      lifecycle.markPluginRegistryActive(fixture.builder.registry);
      const entry = fixture.builder.registry.channels.find(
        (item) => item.pluginId === replacement?.id,
      );
      const resolve = entry?.resolveChannelRuntime;
      if (!entry || !resolve) {
        throw new Error("Replacement native resolver is absent.");
      }
      const channel = resolve();
      const newHost = observation.hosts.at(-1);
      if (!newHost) {
        throw new Error("Replacement native H was not observed.");
      }
      expect(getPluginValueInstance(entry.plugin)).toBe(replacementInstance);
      expect(newHost).not.toBe(fixture.host);
      expect(fixture.host.isLive()).toBe(false);
      expect(newHost.isLive()).toBe(true);
      expect((await channel.inbound.ingress.resolveStable(stableParams())).ingress.admission).toBe(
        "dispatch",
      );
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [fixture?.builder.registry],
        instances: [fixture?.instance, replacement ? getPluginInstance(replacement) : undefined],
        primaryFailure,
      });
    }
  });

  it("rejects a current channel value from another authentic native instance without poisoning B", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let a: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    let b: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    try {
      a = await nativeFixture(observation);
      b = await nativeFixture(observation);
      expect(a.host.isLive()).toBe(true);
      expect(b.host.isLive()).toBe(true);
      expect(a.record.id).toBe(b.record.id);
      expect(a.record).not.toBe(b.record);
      expect(a.instance).not.toBe(b.instance);
      expect(getPluginValueInstance(b.registration.plugin)).toBe(b.instance);
      const originalAPlugin = a.registration.plugin;
      a.registration.plugin = b.registration.plugin;
      expect(lifecycle.getPluginRecordRegistry(a.builder.registry, a.record)).toBe(
        a.builder.registry,
      );
      expect(lifecycle.isPluginRecordActive(a.builder.registry, a.record)).toBe(true);
      expect(a.builder.registry.channels).toContain(a.registration);
      expect(getPluginValueInstance(a.registration.plugin)).toBe(b.instance);
      expect(a.host.isLive()).toBe(false);
      expect(b.host.isLive()).toBe(true);
      a.registration.plugin = originalAPlugin;
      expect(getPluginValueInstance(a.registration.plugin)).toBe(a.instance);
      expect(a.host.isLive()).toBe(false);
      const renewedChannel = a.resolve();
      const renewedHost = observation.hosts.at(-1);
      if (!renewedHost) {
        throw new Error("Renewed native A host was not observed.");
      }
      expect(renewedHost).not.toBe(a.host);
      expect(renewedHost.isLive()).toBe(true);
      expect(
        (await renewedChannel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
      expect(
        (await b.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
      ).toBe("dispatch");
      expect(b.host.isLive()).toBe(true);
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [a?.builder.registry, b?.builder.registry],
        instances: [a?.instance, b?.instance],
        primaryFailure,
      });
    }
  });

  it("clears only ContextAdmission on a reused ordinary context after authentic H closes", async () => {
    const observation = observeNativeFactories();
    let primaryFailure: PrimaryFailure;
    let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
    try {
      fixture = await nativeFixture(observation);
      const ingress = await fixture.channel.inbound.ingress.resolveStable(stableParams());
      const context = await fixture.channel.inbound.buildContext({
        ...buildParams(),
        channelIngress: ingress,
      });
      expect(typeof readChannelContextGatewayContextResolver(context)).toBe("function");
      lifecycle.markPluginRegistryRetired(fixture.builder.registry);
      expect(fixture.host.isLive()).toBe(false);
      let ordinaryCalls = 0;
      const passiveBuild = createHostChannelInboundEventContextBuilder(
        (_params: BuildChannelInboundEventContextParams) => {
          ordinaryCalls += 1;
          return context;
        },
        fixture.host,
      );
      expect(await passiveBuild(buildParams())).toBe(context);
      expect(ordinaryCalls).toBe(1);
      expect(readChannelContextGatewayContextResolver(context)).toBeUndefined();
      expect(readChannelContextAdmissionEvidence(context)).toBeUndefined();
      // No claim that old participant/command-owner carriers are removed, or that a Task is authorized.
    } catch (error) {
      primaryFailure = { error };
      throw error;
    } finally {
      await cleanupNative({
        restore: [observation.close],
        registries: [fixture?.builder.registry],
        instances: [fixture?.instance],
        primaryFailure,
      });
    }
  });

  it.each(["retire", "revoke", "rollback"])(
    "never revives H after observed native %s, while a new native H is healthy",
    async (action) => {
      const observation = observeNativeFactories();
      let primaryFailure: PrimaryFailure;
      let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      let fresh: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      try {
        fixture = await nativeFixture(observation);
        if (action === "retire") {
          lifecycle.markPluginRegistryRetired(fixture.builder.registry);
        } else if (action === "revoke") {
          lifecycle.revokePluginRecord(fixture.builder.registry, fixture.record);
        } else {
          fixture.builder.rollbackPluginGlobalSideEffects(fixture.record.id, fixture.record);
        }
        expect(fixture.host.isLive()).toBe(false);
        lifecycle.markPluginRegistryActive(fixture.builder.registry);
        const closed = await fixture.channel.inbound.ingress.resolveStable(stableParams());
        const context = await fixture.channel.inbound.buildContext({
          ...buildParams(),
          channelIngress: closed,
        });
        expect(readChannelContextGatewayContextResolver(context)).toBeUndefined();
        expect(readChannelContextAdmissionEvidence(context)).toBeUndefined();
        expect(fixture.host.isLive()).toBe(false);
        fresh = await nativeFixture(observation);
        expect(fresh.host.isLive()).toBe(true);
        expect(
          (await fresh.channel.inbound.ingress.resolveStable(stableParams())).ingress.admission,
        ).toBe("dispatch");
      } catch (error) {
        primaryFailure = { error };
        throw error;
      } finally {
        await cleanupNative({
          restore: [observation.close],
          registries: [fresh?.builder.registry, fixture?.builder.registry],
          instances: [fresh?.instance, fixture?.instance],
          primaryFailure,
        });
      }
    },
  );

  // H3-P2-REENTRANT-19: three additional cases; the sixteen preceding cases are unchanged.
  it.each(["healthy", "resolveParticipant-getter-retires", "subject-getter-retires"])(
    "rechecks native H after participant operand getters before calling: %s",
    async (mode) => {
      const observation = observeNativeFactories();
      let primaryFailure: PrimaryFailure;
      let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      try {
        fixture = await nativeFixture(observation);
        const native = fixture;
        expect(native.host.isLive()).toBe(true);
        const rawSubject: ChannelIngressIdentitySubjectInput = stableParams().subject;
        const order: string[] = [];
        let calls = 0;
        let callbackReads = 0;
        let subjectReads = 0;
        const callback = function (
          this: ChannelIngressIdentityDescriptor,
          supplied: ChannelIngressIdentitySubjectInput,
        ) {
          order.push("call");
          calls += 1;
          expect(this).toBe(identity);
          expect(supplied).toBe(rawSubject);
          return { domain: "h3-fictif", idKind: "user-id", id: "h3-person-fictif" };
        };
        const identity: ChannelIngressIdentityDescriptor = {
          primary: {},
          get resolveParticipant() {
            order.push("resolveParticipant");
            callbackReads += 1;
            if (mode === "resolveParticipant-getter-retires") {
              lifecycle.markPluginRegistryRetired(native.builder.registry);
            }
            return callback;
          },
        };
        const params: ResolveChannelMessageIngressParams = {
          ...participantParams(identity, rawSubject),
          get subject() {
            order.push("subject");
            subjectReads += 1;
            if (mode === "subject-getter-retires") {
              lifecycle.markPluginRegistryRetired(native.builder.registry);
            }
            return rawSubject;
          },
        };
        // Direct .resolve preserves the operand getter seam; resolveStable snapshots identity.
        const result = await native.channel.inbound.ingress.resolve(params);
        expect(callbackReads).toBe(1);
        expect(subjectReads).toBeGreaterThan(0);
        expect(order.slice(0, 2)).toEqual(["resolveParticipant", "subject"]);
        expect(calls).toBe(mode === "healthy" ? 1 : 0);
        if (mode === "healthy") {
          expect(order.slice(0, 3)).toEqual(["resolveParticipant", "subject", "call"]);
        } else {
          expect(order).not.toContain("call");
        }
        expect(native.host.isLive()).toBe(mode === "healthy");
        // Closed H keeps ordinary policy evaluation passive; dispatch is not a G/R grant.
        expect(result.ingress.admission).toBe("dispatch");
        const context = await native.channel.inbound.buildContext({
          ...buildParams(),
          channelIngress: result,
        });
        if (mode === "healthy") {
          const resolver = readChannelContextGatewayContextResolver(context);
          expect(typeof resolver).toBe("function");
          expect(resolver?.()).toBeUndefined();
        } else {
          expect(readChannelContextGatewayContextResolver(context)).toBeUndefined();
          expect(readChannelContextAdmissionEvidence(context)).toBeUndefined();
          expect(native.host.isLive()).toBe(false);
        }
        // NO Gateway was created: prior participant/authority carriers and G/R/P/M are outside scope.
      } catch (error) {
        primaryFailure = { error };
        throw error;
      } finally {
        await cleanupNative({
          restore: [observation.close],
          registries: [fixture?.builder.registry],
          instances: [fixture?.instance],
          primaryFailure,
        });
      }
    },
  );

  // H3-P2-CONTEXT-GETTER-21: actual accepted participant carrier, NO Gateway.
  it.each(["healthy", "context-getter-retires"])(
    "rechecks native H after the context getter before participant mutation: %s",
    async (mode) => {
      const observation = observeNativeFactories();
      let primaryFailure: PrimaryFailure;
      let fixture: Awaited<ReturnType<typeof nativeFixture>> | undefined;
      try {
        fixture = await nativeFixture(observation);
        const native = fixture;
        expect(native.host.isLive()).toBe(true);
        const rawSubject: ChannelIngressIdentitySubjectInput = stableParams().subject;
        let participantCalls = 0;
        const identity: ChannelIngressIdentityDescriptor = {
          primary: {},
          resolveParticipant(
            this: ChannelIngressIdentityDescriptor,
            subject: ChannelIngressIdentitySubjectInput,
          ) {
            participantCalls += 1;
            expect(this).toBe(identity);
            expect(subject).toBe(rawSubject);
            return { domain: "h3-fictif", idKind: "user-id", id: "h3-person-fictif" };
          },
        };
        const params = participantParams(identity, rawSubject);
        const binding = params.contextBinding;
        const ingress = await native.channel.inbound.ingress.resolve(params);
        expect(participantCalls).toBe(1);
        expect(ingress.ingress.admission).toBe("dispatch");
        // Accept the actual private handoff before the binder can take its participant.
        const preparation = prepareHostChannelContextAdmissionEvidence({
          owner: native.host,
          channelId: CHANNEL,
          accountId: "default",
          ingress,
          rawPrincipalRef: rawSubject.stableId,
          contextParams: buildParams(),
        });
        expect(preparation).toBeDefined();
        expect(native.host.isLive()).toBe(true);
        const context: SessionParticipantInputContext = {};
        expect(context[sessionParticipantInput]).toBeUndefined();
        let contextReads = 0;
        bindChannelParticipantInput({
          get context() {
            contextReads += 1;
            if (mode === "context-getter-retires") {
              lifecycle.markPluginRegistryRetired(native.builder.registry);
            }
            return context;
          },
          channelId: CHANNEL,
          ingress,
          binding,
          owner: native.host,
        });
        expect(contextReads).toBe(1);
        if (mode === "healthy") {
          // The real prepareSessionParticipantInput append, not an observation stub.
          expect(context[sessionParticipantInput]).toEqual([
            {
              identity: {
                type: "remote",
                pluginId: CHANNEL,
                domain: "h3-fictif",
                idKind: "user-id",
                id: "h3-person-fictif",
              },
              promptedAt: expect.any(Number),
              recorded: false,
            },
          ]);
          expect(native.host.isLive()).toBe(true);
        } else {
          expect(context[sessionParticipantInput]).toBeUndefined();
          expect(native.host.isLive()).toBe(false);
        }
        // No Gateway, command authority, model/device effect or ordinary-builder exploit claim.
      } catch (error) {
        primaryFailure = { error };
        throw error;
      } finally {
        await cleanupNative({
          restore: [observation.close],
          registries: [fixture?.builder.registry],
          instances: [fixture?.instance],
          primaryFailure,
        });
      }
    },
  );
});
