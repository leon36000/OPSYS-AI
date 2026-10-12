import { onTestFinished, vi } from "vitest";
import type { ChannelIngressHostOwner } from "../../src/channels/message-access/ingress-host-owner.js";
import * as ingressModule from "../../src/channels/message-access/runtime.js";
import type { GatewayContextResolver } from "../../src/gateway/server-methods/types.js";
import {
  getPluginInstance,
  getPluginValueInstance,
  type PluginInstanceHandle,
} from "../../src/plugins/plugin-instance-scope.js";
import {
  markPluginRegistryActive,
  markPluginRegistryRetired,
  revokePluginRecord,
} from "../../src/plugins/registry-lifecycle.js";
import { createPluginRegistry, type PluginRegistry } from "../../src/plugins/registry.js";
import { bindGatewayContextResolver } from "../../src/plugins/runtime/gateway-request-scope.js";
import { createPluginRuntime } from "../../src/plugins/runtime/index.js";
import { createPluginRecord } from "../../src/plugins/status.test-fixtures.js";
import { createChannelTestPluginBase } from "../../src/test-utils/channel-plugins.js";

/** A fictitious channel with actual native runtime/registry/instance/slot ownership, never a G/R grant. */
export function createNativeChannelIngressOwner(params: {
  channelId: string;
  resolveGatewayContext?: GatewayContextResolver;
}) {
  const fixtureMetadata = { fictif: true, channelId: params.channelId };
  const resolveGatewayContext = params.resolveGatewayContext;
  const record = createPluginRecord({ id: fixtureMetadata.channelId, origin: "bundled" });
  let registry: PluginRegistry | undefined;
  let instance: PluginInstanceHandle | undefined;
  let constructionFailure: { error: unknown } | undefined;
  let cleanup: Promise<void> | undefined;
  const close = () => {
    cleanup ??= (async () => {
      const errors: unknown[] = [];
      try {
        markPluginRegistryRetired(registry);
      } catch (error) {
        errors.push(error);
      }
      const retained = instance ?? getPluginInstance(record);
      if (retained) {
        try {
          const result = await retained.drain({ includeConsumers: true });
          errors.push(...result.errors);
        } catch (error) {
          errors.push(error);
        }
      }
      if (errors.length > 0) {
        if (constructionFailure) {
          throw new AggregateError(
            [constructionFailure.error, ...errors],
            "HARNESS_NONQUAL: native channel fixture cleanup failed after construction failure.",
            { cause: constructionFailure.error },
          );
        }
        throw new AggregateError(errors, "HARNESS_NONQUAL: native channel fixture cleanup failed.");
      }
    })();
    return cleanup;
  };
  // Register before native allocation, including failed construction; never silently ignore drain.errors.
  onTestFinished(close);
  try {
    const runtime = createPluginRuntime();
    // This resolver may expose a synthetic Gateway for an existing test, not native serving authority.
    bindGatewayContextResolver(runtime.subagent, resolveGatewayContext);
    const builder = createPluginRegistry({
      logger: { info() {}, warn() {}, error() {}, debug() {} },
      runtime,
      activateGlobalSideEffects: false,
    });
    registry = builder.registry;
    const api = builder.createApi(record, { config: {}, registrationMode: "full" });
    instance = getPluginInstance(record);
    if (!instance) {
      throw new Error("Native channel fixture instance is unavailable.");
    }
    instance.run(() =>
      api.registerChannel({
        plugin: createChannelTestPluginBase({ id: fixtureMetadata.channelId }),
      }),
    );
    builder.registry.plugins.push(record);
    markPluginRegistryActive(builder.registry);
    const registration = builder.registry.channels.find((entry) => entry.pluginId === record.id);
    const resolve = registration?.resolveChannelRuntime;
    if (!registration || !resolve) {
      throw new Error("Native channel fixture resolver is unavailable.");
    }
    if (getPluginValueInstance(registration.plugin) !== instance) {
      throw new Error("Native channel fixture contribution does not retain its exact instance.");
    }
    const retainedInstance = instance;
    let observed: ChannelIngressHostOwner | undefined;
    let observedCount = 0;
    const original = ingressModule.createHostChannelIngressRuntime;
    const spy = (() => {
      try {
        return vi.spyOn(ingressModule, "createHostChannelIngressRuntime");
      } catch (error) {
        throw new Error("HARNESS_BLOCKED: native channel creator cannot be observed.", {
          cause: error,
        });
      }
    })();
    const resolveObserved = () => {
      spy.mockImplementation(function (this: unknown, ...args: Parameters<typeof original>) {
        observed = args[0];
        observedCount += 1;
        return original.apply(this, args);
      });
      const channel = resolve();
      const owner = observed;
      if (!owner || observedCount !== 1) {
        throw new Error("HARNESS_BLOCKED: exact native channel owner was not observed once.");
      }
      if (owner.channelId !== fixtureMetadata.channelId || !owner.isLive()) {
        throw new Error("Native channel fixture owner is not current for its channel.");
      }
      return {
        owner,
        channel,
        runtime,
        record,
        instance: retainedInstance,
        registry: builder.registry,
        retire: () => markPluginRegistryRetired(builder.registry),
        revoke: () => revokePluginRecord(builder.registry, record),
        close,
      };
    };
    let resolved: ReturnType<typeof resolveObserved> | undefined;
    let resolutionFailure: { error: unknown } | undefined;
    try {
      resolved = resolveObserved();
    } catch (error) {
      resolutionFailure = { error };
    }
    try {
      spy.mockRestore();
    } catch (error) {
      if (resolutionFailure) {
        throw new AggregateError(
          [resolutionFailure.error, error],
          "HARNESS_NONQUAL: observation restoration failed.",
          { cause: error },
        );
      }
      throw error;
    }
    if (resolutionFailure) {
      throw resolutionFailure.error;
    }
    if (!resolved) {
      throw new Error("HARNESS_BLOCKED: native channel resolution returned no fixture.");
    }
    return resolved;
  } catch (error) {
    constructionFailure = { error };
    throw error;
  }
}
