import { describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createPluginCache, withPluginCache } from "../plugins/plugin-cache.js";
import { resolvePluginMetadataSnapshot } from "../plugins/plugin-metadata-snapshot.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { captureAsyncWorkTracker } from "../shared/async-work-scope.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { SystemAgentConfiguredRoute } from "./inference-route.js";
import {
  loadSetupInferencePluginGeneration,
  revalidateStableSetupInferenceOwner,
  runSetupInferenceTurn,
} from "./setup-inference-turn.js";
import { createSystemAgentVerifiedInferenceTestFixture } from "./system-agent.test-helpers.js";

const mocks = vi.hoisted(() => ({ loadAgentRuntimePluginRegistryHandle: vi.fn() }));
vi.mock("../agents/runtime-plugins.js", () => ({
  loadAgentRuntimePluginRegistryHandle: mocks.loadAgentRuntimePluginRegistryHandle,
}));

function embeddedRoute(): SystemAgentConfiguredRoute {
  const config: OpenClawConfig = {
    agents: {
      entries: { main: { default: true, agentDir: "/tmp/openclaw-agent" } },
      defaults: {
        model: "openai/gpt-5.6-sol",
        models: { "openai/gpt-5.6-sol": { agentRuntime: { id: "codex" } } },
        workspace: "/tmp/openclaw-workspace",
      },
    },
  };
  return {
    runner: "embedded",
    provider: "openai",
    model: "gpt-5.6-sol",
    modelLabel: "openai/gpt-5.6-sol",
    agentId: "main",
    agentDir: "/tmp/openclaw-agent",
    agentHarnessRuntimeOverride: "codex",
    sourceConfig: config,
    runConfig: config,
  };
}

describe("setup inference plugin ownership", () => {
  it("waits for the isolated probe runtime to release its plugin work", async () => {
    const route = embeddedRoute();
    const cleanupStarted = createDeferred();
    const releaseCleanup = createDeferred();
    const removeTempDir = vi.fn(async () => {});
    const runEmbeddedAgent = vi.fn(async () => {
      const trackOwner = captureAsyncWorkTracker();
      void trackOwner(async () => {
        cleanupStarted.resolve();
        await releaseCleanup.promise;
      });
      return {
        payloads: [{ text: "OK" }],
        meta: {
          durationMs: 1,
          executionTrace: {
            winnerProvider: route.provider,
            winnerModel: route.model,
          },
        },
      };
    });

    let settled = false;
    const turn = runSetupInferenceTurn({
      route,
      deps: {
        createTempDir: async () => "/tmp/openclaw-setup-inference-test",
        removeTempDir,
        runEmbeddedAgent,
      },
      requireExecutionOwner: false,
    }).finally(() => {
      settled = true;
    });

    await cleanupStarted.promise;
    try {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      expect(settled).toBe(false);
      expect(removeTempDir).not.toHaveBeenCalled();
    } finally {
      releaseCleanup.resolve();
    }
    await expect(turn).resolves.toMatchObject({ ok: true, text: "OK" });
    expect(removeTempDir).toHaveBeenCalledOnce();
  });

  it("loads newly installed package facts after the install lease cached their absence", async () => {
    await withOpenClawTestState(
      { label: "setup-plugin-generation", env: { OPENCLAW_DISABLE_BUNDLED_PLUGINS: "1" } },
      async (state) => {
        const config = {
          plugins: {
            allow: ["fixture-runtime"],
            load: { paths: [state.statePath("plugin")] },
            entries: { "fixture-runtime": { enabled: true } },
          },
        };
        await withPluginCache(createPluginCache(), async () => {
          const input = { config, workspaceDir: state.workspaceDir, allowCurrent: false };
          const before = resolvePluginMetadataSnapshot(input);
          expect(before.byPluginId.has("fixture-runtime")).toBe(false);
          await state.writeJson("plugin/package.json", {
            name: "@fixture/runtime",
            version: "1.0.0",
            openclaw: { extensions: ["./index.js"] },
          });
          await state.writeJson("plugin/openclaw.plugin.json", {
            id: "fixture-runtime",
            agentHarnesses: ["fixture-runtime"],
            configSchema: { type: "object" },
          });
          await state.writeText("plugin/index.js", 'throw new Error("metadata must not execute");');
          mocks.loadAgentRuntimePluginRegistryHandle.mockReturnValueOnce(
            createEmptyPluginRegistry(),
          );
          await using generationCache = createPluginCache();
          const generation = loadSetupInferencePluginGeneration({
            cache: generationCache,
            config,
            workspaceDir: state.workspaceDir,
            selection: { provider: "fixture", modelId: "model", runtime: "fixture-runtime" },
          });
          expect(generation.metadataSnapshot.byPluginId.has("fixture-runtime")).toBe(true);
          expect(resolvePluginMetadataSnapshot(input)).toBe(before);
        });
      },
    );
  });

  // Le scénario « probing registry artifact preference » exerçait un harnais embarqué
  // porté par un plugin (`agentHarnesses` dans un manifeste). Codex était la seule
  // extension à déclarer ce contrat ; aucune extension conservée ne le porte
  // (`rg agentHarnesses extensions/*/openclaw.plugin.json` ne retourne rien). Le test
  // n'a donc plus d'objet et est supprimé plutôt qu'affaibli avec un fournisseur qui
  // ne porte pas le même contrat (règle de décision T0.6, fournisseur élagué).

  it("does not load plugins for a direct custom provider using the built-in OpenClaw harness", async () => {
    const config: OpenClawConfig = {
      agents: {
        entries: { main: { default: true, agentDir: "/tmp/openclaw-agent" } },
        defaults: {
          model: "fixture/direct-model",
          models: { "fixture/direct-model": { agentRuntime: { id: "openclaw" } } },
          workspace: "/tmp/openclaw-workspace",
        },
      },
      models: {
        providers: {
          fixture: {
            api: "openai-completions",
            baseUrl: "https://provider.example/v1",
            models: [],
          },
        },
      },
    };
    const { binding } = await createSystemAgentVerifiedInferenceTestFixture(config);
    expect(binding.ownerPluginIds).toEqual([]);
    mocks.loadAgentRuntimePluginRegistryHandle.mockClear();

    await expect(
      revalidateStableSetupInferenceOwner({
        route: binding.execution,
        auth: binding.auth,
        stagedOwnerPluginArtifacts: binding,
        deps: {
          createSystemAgentVerifiedInferenceBinding: vi.fn(async () => binding),
        },
      }),
    ).resolves.toBe(binding);

    expect(mocks.loadAgentRuntimePluginRegistryHandle).not.toHaveBeenCalled();
  });
});
