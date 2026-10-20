import { setImmediate as nextTurn } from "node:timers/promises";
import { createApiRegistry, createLlmRuntime, type LlmRuntime } from "@openclaw/ai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getModelCompletionOwner,
  getModelCompletionTransport,
  getModelLlmRuntime,
} from "../llm/model-runtime-binding.js";
import type { Model } from "../llm/types.js";
import { createPluginMetadataSnapshotFixture } from "../plugins/plugin-metadata.test-support.js";
import { AsyncWorkScope, trackAsyncWork } from "../shared/async-work-scope.js";
import { createDeferredCore } from "../shared/deferred.js";
import type { ResolvedProviderAuth } from "./model-auth.js";
import type { PreparedModelRuntimeSnapshot } from "./prepared-model-runtime.js";
import { AuthStorage } from "./sessions/auth-storage.js";
import { ModelRegistry } from "./sessions/model-registry.js";
import type { SimpleCompletionModelResolver } from "./simple-completion-scope.js";

// Only the unused default resolver is replaced. These sentinels must never execute.
// Do not reset these spies: even a caught fallback attempt invalidates the fixture.
const defaultResolvers = vi.hoisted(() => ({
  resolveModelAsync: vi.fn<typeof import("./embedded-agent-runner/model.js").resolveModelAsync>(
    () => {
      throw new Error("M9_DEFAULT_RESOLVER_FORBIDDEN");
    },
  ),
  createEmptyAgentDiscoveryStores: vi.fn<
    typeof import("./embedded-agent-runner/model.js").createEmptyAgentDiscoveryStores
  >(() => {
    throw new Error("M9_DEFAULT_RESOLVER_FORBIDDEN");
  }),
  resolveModelWithRegistry: vi.fn<
    typeof import("./embedded-agent-runner/model.js").resolveModelWithRegistry
  >(() => {
    throw new Error("M9_DEFAULT_RESOLVER_FORBIDDEN");
  }),
}));
vi.mock("./embedded-agent-runner/model.js", () => ({
  resolveModelAsync: defaultResolvers.resolveModelAsync,
  createEmptyAgentDiscoveryStores: defaultResolvers.createEmptyAgentDiscoveryStores,
  resolveModelWithRegistry: defaultResolvers.resolveModelWithRegistry,
}));

// Fictitious final infrastructure only. Acquirer, model binding and AsyncWorkScope stay real.
const edges = vi.hoisted(() => ({
  acquireRuntimeLease:
    vi.fn<() => Promise<{ snapshot: PreparedModelRuntimeSnapshot } & AsyncDisposable>>(),
  disposeRuntime: vi.fn<() => Promise<void>>(),
  auth: vi.fn<() => Promise<ResolvedProviderAuth>>(),
  prepareProviderRuntimeAuth: vi.fn<() => Promise<undefined>>(),
  metadata: vi.fn<() => ReturnType<typeof createPluginMetadataSnapshotFixture>>(),
  runtime: vi.fn<() => LlmRuntime>(),
  injectedResolver: vi.fn<SimpleCompletionModelResolver>(),
  current: true,
}));
// Provider-port initialization is fictitious; acquisition, bindings and ownership stay real.
vi.mock("./ai-transport-runtime-host.js", () => ({}));
vi.mock("./prepared-model-runtime.js", () => ({
  acquireAgentRunPreparedModelRuntime: edges.acquireRuntimeLease,
}));
vi.mock("../plugins/plugin-metadata-snapshot.js", async (original) => ({
  ...(await original<typeof import("../plugins/plugin-metadata-snapshot.js")>()),
  resolvePluginMetadataSnapshot: edges.metadata,
}));
vi.mock("./model-auth.js", () => ({
  applySecretRefHeaderSentinels: (model: Model) => model,
  applyLocalNoAuthHeaderOverride: (model: Model) => model,
  formatMissingAuthError: () => "fictitious auth missing",
  getApiKeyForModelCore: edges.auth,
  resolveApiKeyForProviderCore: edges.auth,
}));
vi.mock("../plugins/provider-runtime.runtime.js", () => ({
  prepareProviderRuntimeAuth: edges.prepareProviderRuntimeAuth,
}));
vi.mock("./sessions/model-registry-runtime.js", () => ({
  initializeModelRegistryRuntime: () => {},
  getModelRegistryRuntime: () => {
    const runtime = edges.runtime();
    return { apiRegistry: runtime.registry, llmRuntime: runtime };
  },
}));

import {
  acquireSimpleCompletionModelForAgent,
  acquireSimpleCompletionModelWithSelection,
} from "./simple-completion-runtime.js";

const resolvedModel: Model<"ollama"> = {
  provider: "ollama",
  id: "fictitious-lease-model",
  name: "Fictitious lease model",
  api: "ollama",
  baseUrl: "http://127.0.0.1:11434",
  reasoning: false,
  input: ["text"],
  contextWindow: 8192,
  maxTokens: 128,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
let snapshot: PreparedModelRuntimeSnapshot;
let resolver: SimpleCompletionModelResolver;
beforeEach(() => {
  edges.current = true;
  edges.acquireRuntimeLease.mockReset();
  edges.disposeRuntime.mockReset();
  edges.auth.mockReset();
  edges.prepareProviderRuntimeAuth.mockReset();
  edges.metadata.mockReset();
  edges.runtime.mockReset();
  edges.injectedResolver.mockReset();
  edges.disposeRuntime.mockResolvedValue(undefined);
  edges.auth.mockResolvedValue({
    apiKey: "fictitious-not-a-secret",
    source: "fictitious infrastructure",
    mode: "api-key",
  });
  edges.prepareProviderRuntimeAuth.mockResolvedValue(undefined);
  edges.metadata.mockReturnValue(createPluginMetadataSnapshotFixture());
  const authStorage = AuthStorage.inMemory({});
  const modelRegistry = ModelRegistry.inMemory(authStorage);
  const runtime = createLlmRuntime(createApiRegistry());
  edges.runtime.mockReturnValue(runtime);
  snapshot = {
    catalogOwner: undefined,
    observationConfig: {},
    isCurrent: () => edges.current,
    agentDir: "/fictitious/agent",
    workspaceDir: "/fictitious/workspace",
    config: {},
    authModes: {},
    metadataSnapshot: createPluginMetadataSnapshotFixture(),
    allowGatewaySubagentBinding: false,
    modelCatalog: { entries: [], routeVariants: [] },
    configuredRuntimeModels: [],
    findConfiguredRuntimeModel: () => undefined,
    inlineProviderModels: [],
    activeProjectKeys: [],
    createStores: () => ({ authStorage, modelRegistry }),
  };
  edges.acquireRuntimeLease.mockResolvedValue({
    snapshot,
    [Symbol.asyncDispose]: edges.disposeRuntime,
  });
  resolver = edges.injectedResolver.mockImplementation(
    async (_provider, _modelId, _agentDir, _cfg, options) => ({
      model: resolvedModel,
      authStorage: options?.authStorage ?? authStorage,
      modelRegistry: options?.modelRegistry ?? modelRegistry,
    }),
  );
});

afterEach(() => {
  // A fallback throw can be swallowed by auth; its occurrence must still fail this test.
  expect(defaultResolvers.resolveModelAsync).not.toHaveBeenCalled();
  expect(defaultResolvers.createEmptyAgentDiscoveryStores).not.toHaveBeenCalled();
  expect(defaultResolvers.resolveModelWithRegistry).not.toHaveBeenCalled();
  const stores = snapshot.createStores();
  expect(edges.injectedResolver).toHaveBeenCalled();
  expect(
    edges.injectedResolver.mock.calls.some(
      ([_provider, _modelId, _agentDir, _cfg, options]) =>
        options?.authStorage === stores.authStorage &&
        options?.modelRegistry === stores.modelRegistry &&
        options?.preparedModelRuntime === snapshot &&
        options?.workspaceDir === snapshot.workspaceDir,
    ),
  ).toBe(true);
});

function params(signal?: AbortSignal) {
  return {
    cfg: {},
    agentId: "main",
    agentDir: "/fictitious/agent",
    modelResolver: resolver,
    signal,
  };
}
function selection() {
  return { selection: { provider: "ollama", modelId: "fictitious-lease-model" } };
}
async function acquirePrivate(parent?: AsyncWorkScope, signal?: AbortSignal) {
  const acquire = () =>
    acquireSimpleCompletionModelWithSelection(params(signal), selection, {
      privateCompletionOwner: true,
    });
  // The projected third argument is intentionally new: old JS ignores it; Vitest must reach owner assertion.
  const acquired = await (parent ? parent.run(acquire) : acquire());
  if ("error" in acquired) {
    throw new Error(acquired.error);
  }
  return acquired;
}
function requireOwner(model: Model) {
  const owner = getModelCompletionOwner(model);
  expect(
    owner,
    "canonical private completion owner after successful real acquisition",
  ).toBeDefined();
  if (!owner) {
    throw new Error("M9_CANONICAL_COMPLETION_OWNER_MISSING");
  }
  return owner;
}
function observe<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => {});
  return promise;
}

describe("canonical private completion lease owner", () => {
  it("keeps ordinary caller-selected acquisition unchanged without the internal opt-in", async () => {
    const acquired = await acquireSimpleCompletionModelWithSelection(params(), selection);
    if ("error" in acquired) {
      throw new Error(acquired.error);
    }
    try {
      expect(getModelCompletionOwner(acquired.model)).toBeUndefined();
      expect(getModelLlmRuntime(acquired.model)).toBe(edges.runtime());
    } finally {
      await acquired[Symbol.asyncDispose]();
    }
    expect(edges.disposeRuntime).toHaveBeenCalledOnce();
  });
  it("keeps ordinary for-agent acquisition unchanged without the internal opt-in", async () => {
    const acquired = await acquireSimpleCompletionModelForAgent({
      ...params(),
      modelRef: "ollama/fictitious-lease-model",
    });
    if ("error" in acquired) {
      throw new Error(acquired.error);
    }
    try {
      expect(getModelCompletionOwner(acquired.model)).toBeUndefined();
    } finally {
      await acquired[Symbol.asyncDispose]();
    }
    expect(edges.disposeRuntime).toHaveBeenCalledOnce();
  });
  it("publishes a canonical owner only after successful real opt-in acquisition", async () => {
    const acquired = await acquirePrivate();
    try {
      expect(edges.acquireRuntimeLease).toHaveBeenCalledOnce();
      expect(acquired.auth.apiKey).toBe("fictitious-not-a-secret");
      const owner = requireOwner(acquired.model);
      expect(owner.assertCurrent).not.toThrow();
      expect(await owner.run(async () => "fictitious owned result")).toBe(
        "fictitious owned result",
      );
    } finally {
      await acquired[Symbol.asyncDispose]();
    }
  });
  it("preserves exact runtime transport and auth references through the owned projection", async () => {
    const acquired = await acquirePrivate();
    try {
      const owner = requireOwner(acquired.model),
        runtime = getModelLlmRuntime(acquired.model),
        transport = getModelCompletionTransport(acquired.model),
        auth = acquired.auth;
      expect(runtime).toBe(edges.runtime());
      expect(transport).toBeDefined();
      await owner.run(async () => {
        expect(getModelLlmRuntime(acquired.model)).toBe(runtime);
        expect(getModelCompletionTransport(acquired.model)).toBe(transport);
        expect(acquired.auth).toBe(auth);
      });
      expect(acquired.model).not.toBe(resolvedModel); // Binding is a view, never an identity claim for the original model.
    } finally {
      await acquired[Symbol.asyncDispose]();
    }
  });
  it("closes admission before the first disposal await and prevents a second callback", async () => {
    const acquired = await acquirePrivate();
    const releaseEntered = createDeferredCore(),
      releaseGate = createDeferredCore();
    let closing: Promise<void> | undefined, second: Promise<unknown> | undefined;
    edges.disposeRuntime.mockImplementation(async () => {
      releaseEntered.resolve();
      await releaseGate.promise;
    });
    try {
      const owner = requireOwner(acquired.model),
        callback = vi.fn(async () => "must not start");
      closing = observe(acquired[Symbol.asyncDispose]());
      expect(owner.assertCurrent).toThrow();
      try {
        second = observe(owner.run(callback));
      } catch {
        second = Promise.reject(new Error("synchronous refusal"));
        observe(second);
      }
      expect(callback).not.toHaveBeenCalled();
      await releaseEntered.promise;
      expect(callback).not.toHaveBeenCalled();
      releaseGate.resolve();
      await closing;
      await expect(second).rejects.toBeDefined();
      expect(edges.disposeRuntime).toHaveBeenCalledOnce();
    } finally {
      releaseGate.resolve();
      await Promise.allSettled([
        ...(closing ? [closing] : []),
        ...(second ? [second] : []),
        acquired[Symbol.asyncDispose](),
      ]);
    }
  });
  it("joins a held result and descendant after an independent setup-idle witness before release", async () => {
    const setupParent = new AsyncWorkScope();
    const acquired = await acquirePrivate(setupParent);
    const resultGate = createDeferredCore(),
      resultDone = createDeferredCore(),
      tailGate = createDeferredCore(),
      bodyEntered = createDeferredCore(),
      tailEntered = createDeferredCore();
    const releaseGate = createDeferredCore(),
      releaseEntered = createDeferredCore();
    const events: string[] = [];
    let body: Promise<unknown> | undefined,
      tail: Promise<void> | undefined,
      closing: Promise<void> | undefined;
    edges.disposeRuntime.mockImplementation(async () => {
      events.push("releaseEntered");
      releaseEntered.resolve();
      await releaseGate.promise;
      events.push("releaseDone");
    });
    try {
      const owner = requireOwner(acquired.model);
      // The real acquirer's captureAsyncWorkTracker retained setupParent until onAcquired.release finished.
      await setupParent.runWhenIdle(() => {
        events.push("setupIdleWitness");
      });
      body = observe(
        owner.run(async () => {
          bodyEntered.resolve();
          tail = observe(
            trackAsyncWork(async () => {
              tailEntered.resolve();
              await tailGate.promise;
              events.push("tailDone");
            }),
          );
          await resultGate.promise;
          events.push("resultDone");
          resultDone.resolve();
        }),
      );
      await bodyEntered.promise;
      await tailEntered.promise;
      closing = observe(
        acquired[Symbol.asyncDispose]().then(() => {
          events.push("disposeSettled");
        }),
      );
      expect(owner.assertCurrent).toThrow();
      const rejectedCallback = vi.fn(async () => "forbidden");
      let second: Promise<unknown>;
      try {
        second = observe(owner.run(rejectedCallback));
      } catch {
        second = observe(Promise.reject(new Error("synchronous refusal")));
      }
      expect(rejectedCallback).not.toHaveBeenCalled();
      resultGate.resolve();
      await resultDone.promise;
      // Observe the actual owner result while its tracked descendant remains held.
      await body;
      expect(events).not.toContain("tailDone");
      await nextTurn();
      expect(edges.disposeRuntime).not.toHaveBeenCalled();
      tailGate.resolve();
      await releaseEntered.promise;
      expect(events.indexOf("setupIdleWitness")).toBeLessThan(events.indexOf("resultDone"));
      expect(events.indexOf("tailDone")).toBeGreaterThan(-1);
      expect(events.indexOf("tailDone")).toBeLessThan(events.indexOf("releaseEntered"));
      releaseGate.resolve();
      await closing;
      await Promise.allSettled([body]);
      await expect(second).rejects.toBeDefined();
      expect(events.indexOf("releaseDone")).toBeLessThan(events.indexOf("disposeSettled"));
      expect(edges.disposeRuntime).toHaveBeenCalledOnce();
    } finally {
      resultGate.resolve();
      tailGate.resolve();
      releaseGate.resolve();
      await Promise.allSettled([
        ...(body ? [body] : []),
        ...(tail ? [tail] : []),
        ...(closing ? [closing] : []),
        acquired[Symbol.asyncDispose](),
      ]);
      await setupParent.drain();
    }
  });
  it("refuses disposal from its own active scope without losing external cleanup", async () => {
    const acquired = await acquirePrivate();
    let reentrant: Promise<void> | undefined, run: Promise<unknown> | undefined;
    try {
      const owner = requireOwner(acquired.model);
      run = observe(
        owner.run(async () => {
          reentrant = observe(acquired[Symbol.asyncDispose]());
        }),
      );
      await Promise.allSettled([run]);
      if (!reentrant) {
        throw new Error("reentrant disposer was not invoked");
      }
      await expect(reentrant).rejects.toBeDefined();
    } finally {
      await Promise.allSettled([
        ...(run ? [run] : []),
        ...(reentrant ? [reentrant] : []),
        acquired[Symbol.asyncDispose](),
      ]);
    }
    expect(edges.disposeRuntime).toHaveBeenCalledOnce();
  });
  it("retains a runtime disposal failure and releases its resource only once", async () => {
    const acquired = await acquirePrivate();
    const failure = new Error("fictitious physical release failed");
    edges.disposeRuntime.mockRejectedValue(failure);
    try {
      requireOwner(acquired.model);
      const first = observe(acquired[Symbol.asyncDispose]());
      await expect(first).rejects.toBe(failure);
      await expect(acquired[Symbol.asyncDispose]()).rejects.toBe(failure);
      expect(edges.disposeRuntime).toHaveBeenCalledOnce();
    } finally {
      await Promise.allSettled([acquired[Symbol.asyncDispose]()]);
    }
  });
  it("keeps a shared callback and release failure by exact identity", async () => {
    const acquired = await acquirePrivate();
    const failure = new Error("fictitious shared completion and release failure");
    edges.disposeRuntime.mockRejectedValue(failure);
    try {
      const owner = requireOwner(acquired.model);
      await expect(
        owner.run(async () => {
          throw failure;
        }),
      ).rejects.toBe(failure);
      const closing = observe(acquired[Symbol.asyncDispose]());
      await expect(closing).rejects.toBe(failure);
      await expect(acquired[Symbol.asyncDispose]()).rejects.toBe(failure);
      expect(edges.disposeRuntime).toHaveBeenCalledOnce();
    } finally {
      await Promise.allSettled([acquired[Symbol.asyncDispose]()]);
    }
  });
  it("retains distinct callback and release failures with a memoized aggregate", async () => {
    const acquired = await acquirePrivate();
    const callbackFailure = new Error("fictitious callback failure");
    const releaseFailure = new Error("fictitious independent release failure");
    edges.disposeRuntime.mockRejectedValue(releaseFailure);
    try {
      const owner = requireOwner(acquired.model);
      await expect(
        owner.run(async () => {
          throw callbackFailure;
        }),
      ).rejects.toBe(callbackFailure);
      const closing = observe(acquired[Symbol.asyncDispose]());
      let seen: unknown;
      try {
        await closing;
      } catch (error) {
        seen = error;
      }
      expect(seen).toBeInstanceOf(AggregateError);
      if (!(seen instanceof AggregateError)) {
        throw new Error("expected retained completion and release errors");
      }
      expect(seen.errors).toHaveLength(2);
      expect(seen.errors[0]).toBe(callbackFailure);
      expect(seen.errors[1]).toBe(releaseFailure);
      await expect(acquired[Symbol.asyncDispose]()).rejects.toBe(seen);
      expect(edges.disposeRuntime).toHaveBeenCalledOnce();
    } finally {
      await Promise.allSettled([acquired[Symbol.asyncDispose]()]);
    }
  });
});
