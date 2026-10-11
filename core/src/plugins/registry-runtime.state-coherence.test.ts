import { describe, expect, it } from "vitest";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import { markPluginRegistryActive, markPluginRegistryRetired } from "./registry-lifecycle.js";
import { getPluginRegistryRuntime } from "./registry-runtime-binding.js";
import { createPluginRuntimeResolver } from "./registry-runtime.js";
import { createPluginRegistryState } from "./registry-state.js";
import { createPluginRuntime } from "./runtime/index.js";
import { createPluginRecord } from "./status.test-fixtures.js";

// L1 first slice: real constructor/resolver, local typed runtime data, no model/provider call.
describe("L1-H-FIRST constructor/resolver runtime coherence", () => {
  it.each(["stable-data", "switching-getter"] as const)(
    "retains the exact runtime originally bound to its registry: %s",
    (mode) => {
      const originalRuntime = createPluginRuntime();
      const replacementRuntime = createPluginRuntime();
      let runtimeReads = 0;
      const logger = { info() {}, warn() {}, error() {}, debug() {} };
      const params =
        mode === "stable-data"
          ? { logger, runtime: originalRuntime, activateGlobalSideEffects: false }
          : {
              logger,
              get runtime() {
                runtimeReads += 1;
                return runtimeReads === 1 ? originalRuntime : replacementRuntime;
              },
              activateGlobalSideEffects: false,
            };
      const state = createPluginRegistryState(params);
      const record = createPluginRecord({ id: "l1-local-fixture", origin: "bundled" });
      state.registry.plugins.push(record);
      state.registry.channels.push({
        pluginId: record.id,
        plugin: createChannelTestPluginBase({ id: record.id }),
        source: record.source,
        rootDir: record.rootDir,
      });
      markPluginRegistryActive(state.registry);
      try {
        // Existing binding is the baseline witness, not a claimed permission.
        expect(getPluginRegistryRuntime(state.registry)).toBe(originalRuntime);
        if (mode === "switching-getter") {
          expect(runtimeReads).toBe(1);
        }
        const resolver = createPluginRuntimeResolver(state);
        const channel = resolver.resolveRegisteredChannelRuntime(record);
        // Inbound/turn are intentionally scoped wrappers. reply remains the selected native facade.
        expect(channel.reply).toBe(originalRuntime.channel.reply);
        if (mode === "switching-getter") {
          expect(runtimeReads).toBe(1);
        }
      } finally {
        markPluginRegistryRetired(state.registry);
      }
    },
  );
});
