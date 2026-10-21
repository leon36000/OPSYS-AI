import { createHostChannelInboundEventContextBuilder } from "../channels/inbound-event/host-context-builder.js";
import { createHostChannelIngressRuntime } from "../channels/message-access/runtime.js";
import { createChannelIngressDrain } from "../channels/message/ingress-drain.js";
import { createChannelIngressQueue } from "../channels/message/ingress-queue.js";
import { getRuntimeConfig } from "../config/config.js";
import { createPluginBlobStore } from "../plugin-state/plugin-blob-store.js";
import {
  createPluginStateKeyedStore,
  createPluginStateSyncKeyedStore,
} from "../plugin-state/plugin-state-store.js";
import { createLazyRuntimeSurface } from "../shared/lazy-runtime.js";
import { getPluginInstance, getPluginValueInstance } from "./plugin-instance-scope.js";
import { PluginTrustRefusalError } from "./plugin-trust.js";
import {
  capturePluginLifecycleAuthority,
  getPluginRecordRegistry,
  getPluginRegistryResourceOwner,
  isPluginRecordActive,
  isPluginRegistryPreparing,
  revokePluginRecord,
} from "./registry-lifecycle.js";
import type * as RuntimeTypes from "./registry-runtime.types.js";
import { readPluginRegistryStateRuntime, type PluginRegistryState } from "./registry-state.js";
import {
  bindGatewayContextResolver,
  getCanonicalGatewayContextResolver,
  getGatewayContextResolver,
  getPluginRuntimeGatewayRequestScope,
  withPluginRuntimePluginScope,
} from "./runtime/gateway-request-scope.js";

// Only resolveRecordChannelRuntime writes this exact native owner association.
const nativeIngressHostOwners = new WeakMap<object, () => boolean>();

/** Negative Core lookup; caller data can never register a host owner. */
export function readNativeChannelIngressHostOwner(
  owner: RuntimeTypes.ChannelIngressHostOwner | undefined,
): "absent" | "live" | "closed" {
  // An ownerless builder is constructed while this module's ESM cycle initializes.
  if (owner === undefined) {
    return "absent";
  }
  const isLive = nativeIngressHostOwners.get(owner);
  if (!isLive) {
    throw new Error("Channel ingress host owner origin is unavailable.");
  }
  return isLive() ? "live" : "closed";
}

export function createPluginRuntimeResolver(state: PluginRegistryState) {
  const registryRuntime = readPluginRegistryStateRuntime(state);
  if (!registryRuntime) {
    throw new Error("Plugin registry runtime origin is unavailable.");
  }
  const { registry, registryParams } = state;
  const pluginRuntimes = new WeakMap<RuntimeTypes.PluginRecord, RuntimeTypes.PluginRuntime>();
  const registeredChannelRuntime = new WeakMap<
    RuntimeTypes.PluginRecord,
    RuntimeTypes.ChannelRuntime
  >();
  const registeredRuntimeRecordById = new Map<string, RuntimeTypes.PluginRecord>();
  const registeredAdmissionOwnerByRecord = new WeakMap<
    RuntimeTypes.PluginRecord,
    RuntimeTypes.AdmissionOwnerLifetime
  >();

  const addPluginRuntimeResolutionContext = (params: RuntimeTypes.ResolutionFailure): never => {
    const { error, record, prop } = params;
    if (
      error instanceof Error &&
      error.message.startsWith("Unable to resolve plugin runtime module") &&
      !error.message.includes("pluginRuntimeContext=")
    ) {
      const propName =
        typeof prop === "symbol" ? (prop.description ?? prop.toString()) : String(prop);
      error.message = [
        error.message,
        `pluginRuntimeContext=pluginId:${record.id}`,
        `property:${propName}`,
        ...(record.source ? [`source:${record.source}`] : []),
      ].join("; ");
    }
    throw error;
  };

  const resolveRecordChannelRuntime = (
    record: RuntimeTypes.PluginRecord,
  ): RuntimeTypes.ChannelRuntime => {
    const cached = registeredChannelRuntime.get(record);
    const cachedOwner = registeredAdmissionOwnerByRecord.get(record);
    if (cached && cachedOwner?.isLive() === true) {
      return cached;
    }
    if (cachedOwner) {
      cachedOwner.dispose();
      registeredAdmissionOwnerByRecord.delete(record);
    }
    const channel = (() => {
      try {
        return Reflect.get(
          registryRuntime,
          "channel",
          registryRuntime,
        ) as RuntimeTypes.ChannelRuntime;
      } catch (error) {
        return addPluginRuntimeResolutionContext({
          error,
          record,
          prop: "channel",
        });
      }
    })();
    const nativeInstance = getPluginInstance(record);
    const channelId = record.id;
    const currentRegistry = getPluginRecordRegistry(registry, record);
    if (
      (record.origin !== "bundled" && record.trustedOfficialInstall !== true) ||
      !nativeInstance ||
      !currentRegistry.channels.some(
        (entry) =>
          entry.pluginId === channelId && getPluginValueInstance(entry.plugin) === nativeInstance,
      ) ||
      !isPluginRecordActive(currentRegistry, record)
    ) {
      return channel;
    }
    let closed = false;
    const ownsLiveRegistrySlot = () => {
      if (closed) {
        return false;
      }
      const current = getPluginRecordRegistry(registry, record);
      const live =
        record.id === channelId &&
        (record.origin === "bundled" || record.trustedOfficialInstall === true) &&
        registeredRuntimeRecordById.get(channelId) === record &&
        getPluginInstance(record) === nativeInstance &&
        !nativeInstance.disposing &&
        isPluginRecordActive(current, record) &&
        current.channels.some(
          (entry) =>
            entry.pluginId === channelId && getPluginValueInstance(entry.plugin) === nativeInstance,
        );
      if (
        !live ||
        closed ||
        getPluginRecordRegistry(registry, record) !== current ||
        registeredRuntimeRecordById.get(channelId) !== record ||
        getPluginInstance(record) !== nativeInstance
      ) {
        closed = true;
      }
      return !closed;
    };
    const previousRecord = registeredRuntimeRecordById.get(channelId);
    if (previousRecord && previousRecord !== record) {
      registeredAdmissionOwnerByRecord.get(previousRecord)?.dispose();
      registeredAdmissionOwnerByRecord.delete(previousRecord);
      revokePluginRecord(registry, previousRecord);
    }
    registeredRuntimeRecordById.set(channelId, record);
    const resolveGatewayContext = getGatewayContextResolver(registryRuntime.subagent);
    const scopedGatewayContext = resolveGatewayContext
      ? () => {
          if (!ownsLiveRegistrySlot()) {
            return undefined;
          }
          const context = resolveGatewayContext();
          return ownsLiveRegistrySlot() ? context : undefined;
        }
      : undefined;
    if (scopedGatewayContext && resolveGatewayContext) {
      bindGatewayContextResolver(
        scopedGatewayContext,
        getCanonicalGatewayContextResolver(resolveGatewayContext),
      );
    }
    const owner = Object.freeze({
      channelId,
      resolveGatewayContext: scopedGatewayContext,
      isLive: ownsLiveRegistrySlot,
    });
    nativeIngressHostOwners.set(owner, ownsLiveRegistrySlot);
    registeredAdmissionOwnerByRecord.set(record, {
      isLive: owner.isLive,
      dispose: () => {
        closed = true;
      },
    });
    const buildHostContext = createHostChannelInboundEventContextBuilder(
      channel.inbound.buildContext,
      owner,
    );
    const buildContext = ((params: RuntimeTypes.InboundContextParams) => {
      // Audit provenance is passive: stale closures still build the message context,
      // but only the exact live trusted owner may attach participant evidence.
      return buildHostContext(params as never);
    }) as unknown as RuntimeTypes.InboundContextBuilder;
    const inbound = {
      ...channel.inbound,
      ingress: createHostChannelIngressRuntime(owner),
      buildContext,
    };
    const scoped = {
      ...channel,
      inbound,
      turn: inbound,
    } satisfies RuntimeTypes.ChannelRuntime;
    registeredChannelRuntime.set(record, scoped);
    return scoped;
  };

  const resolvePluginRuntime = (record: RuntimeTypes.PluginRecord): RuntimeTypes.PluginRuntime => {
    const pluginId = record.id;
    const cached = pluginRuntimes.get(record);
    if (cached) {
      return cached;
    }
    const currentRegistry = () => getPluginRecordRegistry(registry, record);
    const currentDecisionRegistry = () => {
      const owner = currentRegistry();
      const invocationView = getPluginRuntimeGatewayRequestScope()?.pluginRegistry;
      // An admitted prepared view may borrow a Gateway provider. Keep that exact
      // composition without accepting an unrelated ambient registry or global owner.
      return invocationView?.plugins.includes(record) &&
        getPluginRegistryResourceOwner(invocationView) === owner
        ? invocationView
        : owner;
    };
    const resolveDelegatedRuntime = (ownerPluginId: string) => {
      const owner = currentRegistry().plugins.find((entry) => entry.id === ownerPluginId);
      if (!owner) {
        throw new Error(`Plugin "${ownerPluginId}" runtime is no longer active.`);
      }
      return resolvePluginRuntime(owner);
    };
    const assertRuntimeCurrent = () => {
      if (
        !capturePluginLifecycleAuthority(currentRegistry(), record, {
          scopedRuntime: registryParams.activateGlobalSideEffects === false,
          registration: true,
          admittedRuntime: true,
        })?.()
      ) {
        throw new Error(`Plugin "${pluginId}" runtime is no longer active.`);
      }
    };
    // Cache checks, not config or row facts; actions resolve ownership after the import settles.
    const loadSessionOwnership = createLazyRuntimeSurface(
      () => import("./registry-runtime-session-ownership.js"),
      (module) => module.createPluginSessionOwnership(state, pluginId, currentRegistry),
    );
    let scopedAgentRuntime: RuntimeTypes.PluginRuntime["agent"] | undefined;
    const assertTrustedPluginRuntime = (methodName: RuntimeTypes.TrustedMethod) => {
      if (record.origin !== "bundled" && record.trustedOfficialInstall !== true) {
        throw new PluginTrustRefusalError({
          methodName,
          pluginId,
          source: record.source,
          origin: record.origin,
          trust: record.trust,
        });
      }
    };
    const runtime = new Proxy(registryRuntime, {
      get(target, prop, receiver) {
        const runWithPluginScope = <T>(run: () => T, requireActive = true): T => {
          if (requireActive) {
            assertRuntimeCurrent();
          }
          const scopedRegistry = currentRegistry();
          return withPluginRuntimePluginScope(
            {
              pluginId,
              pluginSource: record.source,
              pluginOrigin: record.origin,
              pluginTrustedOfficialInstall: record.trustedOfficialInstall,
            },
            run,
            scopedRegistry,
          );
        };
        const getRuntimeProperty = () => {
          try {
            return Reflect.get(target, prop, receiver);
          } catch (error) {
            return addPluginRuntimeResolutionContext({ error, record, prop });
          }
        };
        if (prop === "state") {
          const baseState = getRuntimeProperty();
          return {
            ...baseState,
            openBlobStore: <TMetadata>(options: RuntimeTypes.OpenBlobStoreOptions) => {
              assertTrustedPluginRuntime("openBlobStore");
              return createPluginBlobStore<TMetadata>(pluginId, options);
            },
            openKeyedStore: <T>(options: RuntimeTypes.OpenAsyncKeyedStoreOptions) => {
              assertTrustedPluginRuntime("openKeyedStore");
              if (options.retention === "retained") {
                assertRuntimeCurrent();
              }
              return createPluginStateKeyedStore<T>(pluginId, options, assertRuntimeCurrent);
            },
            openSyncKeyedStore: <T>(options: RuntimeTypes.OpenKeyedStoreOptions) => {
              assertTrustedPluginRuntime("openSyncKeyedStore");
              return createPluginStateSyncKeyedStore<T>(pluginId, options);
            },
            openChannelIngressQueue: <TPayload, TMetadata = unknown, TCompletedMetadata = unknown>(
              options?: Omit<Parameters<typeof createChannelIngressQueue>[0], "channelId">,
            ) => {
              assertTrustedPluginRuntime("openChannelIngressQueue");
              const stateDir = options?.stateDir ?? baseState.resolveStateDir();
              return createChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>({
                ...options,
                channelId: pluginId,
                stateDir,
              });
            },
            openChannelIngressDrain: <TPayload, TMetadata = unknown, TCompletedMetadata = unknown>(
              options: RuntimeTypes.IngressDrainOptions<TPayload, TMetadata, TCompletedMetadata>,
            ) => {
              assertTrustedPluginRuntime("openChannelIngressDrain");
              const stateDir = options.stateDir ?? baseState.resolveStateDir();
              const queue =
                options.queue ??
                createChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>({
                  channelId: pluginId,
                  accountId: options.accountId,
                  stateDir,
                });
              const {
                queue: _queue,
                accountId: _accountId,
                stateDir: _stateDir,
                ...drainOptions
              } = options;
              return createChannelIngressDrain<TPayload, TMetadata, TCompletedMetadata>({
                ...drainOptions,
                queue,
              });
            },
          } satisfies RuntimeTypes.PluginRuntime["state"];
        }
        if (prop === "config") {
          const config: RuntimeTypes.PluginRuntime["config"] = getRuntimeProperty();
          return {
            ...config,
            current: () => runWithPluginScope(() => config.current(), false),
            mutateConfigFile: (params) => runWithPluginScope(() => config.mutateConfigFile(params)),
            replaceConfigFile: (params) =>
              runWithPluginScope(() => config.replaceConfigFile(params)),
          } satisfies RuntimeTypes.PluginRuntime["config"];
        }
        if (prop === "system") {
          const system: RuntimeTypes.PluginRuntime["system"] = getRuntimeProperty();
          const route = <T>(run: () => T): T => {
            assertRuntimeCurrent();
            if (isPluginRegistryPreparing(registry) && !isPluginRecordActive(registry, record)) {
              throw new Error(
                `Plugin "${pluginId}" cannot route system events during replacement preparation.`,
              );
            }
            return runWithPluginScope(run);
          };
          return {
            ...system,
            enqueueSystemEvent: (...args) => route(() => system.enqueueSystemEvent(...args)),
            requestHeartbeat: (...args) => route(() => system.requestHeartbeat(...args)),
            requestHeartbeatNow: (...args) => route(() => system.requestHeartbeatNow(...args)),
            runHeartbeatOnce: (...args) => route(() => system.runHeartbeatOnce(...args)),
            runCommandWithTimeout: (...args) =>
              runWithPluginScope(() => system.runCommandWithTimeout(...args)),
          } satisfies RuntimeTypes.PluginRuntime["system"];
        }
        if (prop === "channel") {
          return resolveRecordChannelRuntime(record);
        }
        if (prop === "decisions") {
          return {
            evaluate: async (batch, options) => {
              assertRuntimeCurrent();
              const { evaluateDecisionInRegistry } = await import("../decisions/runtime.js");
              assertRuntimeCurrent();
              const result = await evaluateDecisionInRegistry(
                batch,
                options,
                currentDecisionRegistry(),
                getRuntimeConfig(),
                record.id,
              );
              assertRuntimeCurrent();
              options.signal.throwIfAborted();
              return result;
            },
          } satisfies RuntimeTypes.PluginRuntime["decisions"];
        }
        if (prop === "llm") {
          const llm = getRuntimeProperty();
          return {
            acquireLocalService: (...args) =>
              runWithPluginScope(() => llm.acquireLocalService(...args)),
            complete: (params) => runWithPluginScope(() => llm.complete(params)),
          } satisfies RuntimeTypes.PluginRuntime["llm"];
        }
        if (prop === "gateway") {
          const gateway = getRuntimeProperty();
          return {
            isAvailable: () => runWithPluginScope(() => gateway.isAvailable(), false),
            request: async (method, params, options) => {
              const { assertGatewaySessionRequestOwned } = await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                assertGatewaySessionRequestOwned(method, params);
                return await gateway.request(method, params, options);
              });
            },
          } satisfies RuntimeTypes.PluginRuntime["gateway"];
        }
        if (prop === "hooks") {
          const hooks: RuntimeTypes.PluginRuntime["hooks"] = getRuntimeProperty();
          return {
            dispatchHookAgentTurn: async (params) => {
              assertTrustedPluginRuntime("dispatchHookAgentTurn");
              return await runWithPluginScope(() => hooks.dispatchHookAgentTurn(params));
            },
          } satisfies RuntimeTypes.PluginRuntime["hooks"];
        }
        if (prop === "nodes") {
          const nodes = getRuntimeProperty();
          return {
            list: (params) => runWithPluginScope(() => nodes.list(params)),
            invoke: (params) => runWithPluginScope(() => nodes.invoke(params)),
            openDuplex: (params) => runWithPluginScope(() => nodes.openDuplex(params)),
          } satisfies RuntimeTypes.PluginRuntime["nodes"];
        }
        if (prop === "agent") {
          if (scopedAgentRuntime) {
            return scopedAgentRuntime;
          }
          const agent: RuntimeTypes.PluginRuntime["agent"] = getRuntimeProperty();
          const session = agent.session;
          const scopedSession = {
            resolveStorePath: session.resolveStorePath,
            getSessionEntry: session.getSessionEntry,
            listSessionEntries: session.listSessionEntries,
            createSessionEntry: async (params) => {
              const { assertOwnedHarness, assertReservedSessionKeyOwned } =
                await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                const runtimeOwnerCount = [
                  "agentHarnessId" in params.initialEntry,
                  "cliBackendId" in params.initialEntry,
                  "acpSessionBinding" in params.initialEntry,
                ].filter(Boolean).length;
                if (runtimeOwnerCount !== 1) {
                  throw new Error(
                    `Plugin "${pluginId}" session creation requires exactly one runtime owner.`,
                  );
                }
                if ("agentHarnessId" in params.initialEntry) {
                  // Session ownership follows the registered harness capability,
                  // independently of whether the caller chooses its reserved namespace.
                  assertOwnedHarness(params.initialEntry.agentHarnessId, "create its sessions");
                  assertReservedSessionKeyOwned(params.key, "create");
                  return await session.createSessionEntry(params);
                }
                const initialEntry = params.initialEntry;
                if (!("acpSessionBinding" in initialEntry)) {
                  const backend = currentRegistry().cliBackends.find(
                    (entry) => entry.backend.id === initialEntry.cliBackendId,
                  );
                  if (!backend || backend.pluginId !== pluginId) {
                    throw new Error(
                      `Plugin "${pluginId}" must own CLI backend "${initialEntry.cliBackendId}" to create its sessions.`,
                    );
                  }
                }
                // Plugin-owned sessions stay inside a namespace that no other plugin can claim.
                if (!params.key.startsWith(`plugin:${pluginId}:`)) {
                  throw new Error(
                    `Plugin "${pluginId}" session keys must start with "plugin:${pluginId}:".`,
                  );
                }
                return await session.createSessionEntry({
                  ...params,
                  initialEntry: { ...initialEntry, pluginOwnerId: pluginId },
                });
              });
            },
            patchSessionEntry: async (params) => {
              const { assertStoredSessionEntryOwned, assertStoreEntryOwned } =
                await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                assertStoredSessionEntryOwned({
                  action: "patch",
                  sessionKey: params.sessionKey,
                  ...(params.agentId !== undefined ? { agentId: params.agentId } : {}),
                  ...(params.env !== undefined ? { env: params.env } : {}),
                  ...(params.storePath !== undefined ? { storePath: params.storePath } : {}),
                });
                return await session.patchSessionEntry({
                  ...params,
                  update: async (entry, context) => {
                    const patch = await params.update(entry, context);
                    assertRuntimeCurrent();
                    if (!patch) {
                      return patch;
                    }
                    const next = params.replaceEntry
                      ? (patch as RuntimeTypes.SessionEntry)
                      : ({ ...entry, ...patch } satisfies RuntimeTypes.SessionEntry);
                    assertStoreEntryOwned({
                      action: "patch",
                      before: context.existingEntry ?? entry,
                      entry: next,
                      sessionKey: params.sessionKey,
                    });
                    return patch;
                  },
                });
              });
            },
            upsertSessionEntry: async (params) => {
              const { assertStoredSessionEntryOwned, assertStoreEntryOwned } =
                await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                const before = assertStoredSessionEntryOwned({
                  action: "upsert",
                  sessionKey: params.sessionKey,
                  ...(params.agentId !== undefined ? { agentId: params.agentId } : {}),
                  ...(params.env !== undefined ? { env: params.env } : {}),
                  ...(params.storePath !== undefined ? { storePath: params.storePath } : {}),
                });
                assertStoreEntryOwned({
                  action: "upsert",
                  before,
                  entry: params.entry,
                  sessionKey: params.sessionKey,
                });
                await session.upsertSessionEntry(params);
              });
            },
            runWithWorkAdmission: async (params, run) => {
              const { resolveStoredSessionExecutionOwner } = await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                const resolveCurrentExecutionOwner = () =>
                  resolveStoredSessionExecutionOwner({
                    action: "admit work on",
                    sessionKey: params.sessionKey,
                    storePath: params.storePath,
                  });
                const ownerPluginId = resolveCurrentExecutionOwner();
                const admissionSession = ownerPluginId
                  ? resolveDelegatedRuntime(ownerPluginId).agent.session
                  : session;
                return await admissionSession.runWithWorkAdmission(params, async (signal) => {
                  // Admission can wait behind another run that changes ownership.
                  // Recheck delegation inside the admitted callback before plugin work starts.
                  if (resolveCurrentExecutionOwner() !== ownerPluginId) {
                    throw new Error(
                      `Session "${params.sessionKey}" changed execution ownership while starting work.`,
                    );
                  }
                  // The owner supplies the admission primitive, but the caller's
                  // callback must not inherit the owner's plugin identity.
                  return await runWithPluginScope(() => run(signal));
                });
              });
            },
            updateSessionStoreEntry: async (params) => {
              const { assertStoredSessionEntryOwned, assertStoreEntryOwned } =
                await loadSessionOwnership();
              return await runWithPluginScope(async () => {
                assertStoredSessionEntryOwned({
                  action: "update",
                  sessionKey: params.sessionKey,
                  storePath: params.storePath,
                });
                return await session.updateSessionStoreEntry({
                  ...params,
                  update: async (entry) => {
                    const patch = await params.update(entry);
                    assertRuntimeCurrent();
                    if (!patch) {
                      return patch;
                    }
                    assertStoreEntryOwned({
                      action: "update",
                      before: entry,
                      entry: { ...entry, ...patch },
                      sessionKey: params.sessionKey,
                    });
                    return patch;
                  },
                });
              });
            },
          } satisfies RuntimeTypes.PluginRuntime["agent"]["session"];
          const runEmbeddedAgent: RuntimeTypes.EmbeddedAgentRun = async (params) => {
            const runParams = { ...params };
            const { prepareRunSessionExecution } = await loadSessionOwnership();
            return await runWithPluginScope(async () => {
              const { ownerPluginId, agentHarnessRuntimeOverride } =
                prepareRunSessionExecution(runParams);
              if (agentHarnessRuntimeOverride !== undefined) {
                runParams.agentHarnessRuntimeOverride = agentHarnessRuntimeOverride;
              }
              if (ownerPluginId) {
                return await resolveDelegatedRuntime(ownerPluginId).agent.runEmbeddedAgent(
                  runParams,
                );
              }
              // The public runtime adapter owns admission preparation. Passing
              // host authority through this plugin wrapper is rejected by design.
              return await agent.runEmbeddedAgent(runParams);
            });
          };
          const runCommandFromIngress: RuntimeTypes.IngressRun = async (params, commandRuntime) => {
            const { senderIsOwner: claimedOwner, messageChannel, ...remainingParams } = params;
            const senderIsOwner = claimedOwner === true;
            // Validate and dispatch the same host-owned values; never re-read plugin-owned authority.
            const ingressParams = { ...remainingParams, senderIsOwner, messageChannel };
            if (
              // Community channels may admit guests; trusted provenance is required only for owner elevation.
              (senderIsOwner &&
                record.origin !== "bundled" &&
                record.trustedOfficialInstall !== true) ||
              currentRegistry().plugins.find((entry) => entry.id === pluginId) !== record ||
              !isPluginRecordActive(registry, record) ||
              !currentRegistry().channels.some(
                (channel) => channel.pluginId === pluginId && channel.plugin.id === messageChannel,
              )
            ) {
              throw new Error(
                `Plugin "${pluginId}" cannot admit authenticated owner authority for channel "${messageChannel ?? "unknown"}".`,
              );
            }
            return await runWithPluginScope(() =>
              agent.runCommandFromIngress(ingressParams, commandRuntime),
            );
          };
          const scopedAgent = Object.create(
            Object.getPrototypeOf(agent),
            Object.getOwnPropertyDescriptors(agent),
          ) as RuntimeTypes.PluginRuntime["agent"];
          Object.defineProperties(scopedAgent, {
            runCommandFromIngress: {
              configurable: true,
              enumerable: true,
              value: runCommandFromIngress,
            },
            runEmbeddedAgent: {
              configurable: true,
              enumerable: true,
              value: runEmbeddedAgent,
            },
            session: {
              configurable: true,
              enumerable: true,
              value: scopedSession,
            },
          });
          scopedAgentRuntime = scopedAgent;
          return scopedAgentRuntime;
        }
        if (prop !== "subagent") {
          return getRuntimeProperty();
        }
        const subagent = getRuntimeProperty();
        return {
          complete: (params) => runWithPluginScope(() => subagent.complete(params)),
          run: async (params) => {
            const { assertSessionIdentitiesOwned } = await loadSessionOwnership();
            return await runWithPluginScope(async () => {
              assertSessionIdentitiesOwned({
                action: "run",
                sessionKeys: [params.sessionKey],
              });
              return await subagent.run(params);
            });
          },
          waitForRun: (params) => runWithPluginScope(() => subagent.waitForRun(params)),
          getSessionMessages: (params) =>
            runWithPluginScope(() => subagent.getSessionMessages(params)),
          deleteSession: async (params) => {
            const { assertStoredSessionEntryOwned } = await loadSessionOwnership();
            return await runWithPluginScope(async () => {
              assertStoredSessionEntryOwned({ action: "delete", sessionKey: params.sessionKey });
              await subagent.deleteSession(params);
            });
          },
        } satisfies RuntimeTypes.PluginRuntime["subagent"];
      },
    });
    pluginRuntimes.set(record, runtime);
    return runtime;
  };

  return {
    resolvePluginRuntime,
    resolveRegisteredChannelRuntime: (record: RuntimeTypes.PluginRecord) =>
      resolveRecordChannelRuntime(record),
    revokePluginRuntimeRecord: (pluginId: string, record: RuntimeTypes.PluginRecord) => {
      revokePluginRecord(registry, record);
      registeredAdmissionOwnerByRecord.get(record)?.dispose();
      registeredAdmissionOwnerByRecord.delete(record);
      if (registeredRuntimeRecordById.get(pluginId) === record) {
        registeredRuntimeRecordById.delete(pluginId);
      }
    },
  };
}

export type PluginRuntimeResolver = ReturnType<typeof createPluginRuntimeResolver>;
