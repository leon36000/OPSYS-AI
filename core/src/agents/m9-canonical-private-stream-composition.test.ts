import {
  createApiRegistry,
  createLlmRuntime,
  type ApiProvider,
  type LlmRuntime,
} from "@openclaw/ai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PrivateM9AuditSource } from "../gateway/m9-private-audit-source.js";
import {
  getModelCompletionOwner,
  getModelCompletionTransport,
  getModelLlmRuntime,
} from "../llm/model-runtime-binding.js";
import type { AssistantMessage, Model } from "../llm/types.js";
import { createAssistantMessageEventStream } from "../llm/utils/event-stream.js";
import { createPluginMetadataSnapshotFixture } from "../plugins/plugin-metadata.test-support.js";
import { AsyncWorkScope, trackAsyncWork } from "../shared/async-work-scope.js";
import {
  createAdmittedRunOperatorAuthority,
  createOperationalRunInstanceRef,
} from "./admitted-run-context.js";
import { getOpsysRuntimeCompletionReceipt } from "./embedded-agent-runner/opsys-runtime-admission.js";
import { preparePrivateM9AdmissionBinding } from "./m9-private-admission-binding.js";
import {
  runPrivateM9PreparedStream,
  type PrivateM9PreparedStreamOptions,
} from "./m9-private-prepared-stream.js";
import type { ResolvedProviderAuth } from "./model-auth.js";
import type { PreparedModelRuntimeSnapshot } from "./prepared-model-runtime.js";
import { capturePrivateProviderRequestFence } from "./private-single-provider-request.js";
import { AuthStorage } from "./sessions/auth-storage.js";
import { ModelRegistry } from "./sessions/model-registry.js";
import { acquireSimpleCompletionModelWithSelection } from "./simple-completion-runtime.js";
import type { SimpleCompletionModelResolver } from "./simple-completion-scope.js";

const edge = vi.hoisted(() => ({
  callOpsysMcpTool:
    vi.fn<(request: { tool: string; args: Record<string, unknown> }) => Promise<unknown>>(),
}));
vi.mock("../context-engine/opsys-contexte-mcp.js", () => edge);

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
  ensureAuthProfileStore:
    vi.fn<typeof import("./auth-profiles/store-runtime.js").ensureAuthProfileStore>(),
  reconcileAuthProfileQuotaBlocks:
    vi.fn<typeof import("./auth-profiles/usage.js").reconcileAuthProfileQuotaBlocks>(),
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
// Final auth infrastructure is synthetic: never read a native profile store or probe quota.
// Canonical acquisition, in-memory stores, runtime scope and private stream remain real.
vi.mock("./auth-profiles/store-runtime.js", () => ({
  ensureAuthProfileStore: edges.ensureAuthProfileStore,
}));
vi.mock("./auth-profiles/usage.js", () => ({
  reconcileAuthProfileQuotaBlocks: edges.reconcileAuthProfileQuotaBlocks,
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

const resolvedModel: Model<"openai-responses"> = {
  provider: "openai",
  id: "fictitious-model",
  name: "Fictitious lease model",
  api: "openai-responses",
  baseUrl: "https://public.example/v1",
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
  edges.ensureAuthProfileStore.mockReset();
  edges.reconcileAuthProfileQuotaBlocks.mockReset();
  edges.auth.mockReset();
  edges.prepareProviderRuntimeAuth.mockReset();
  edges.metadata.mockReset();
  edges.runtime.mockReset();
  edges.injectedResolver.mockReset();
  edges.disposeRuntime.mockResolvedValue(undefined);
  edges.ensureAuthProfileStore.mockReturnValue({ version: 1, profiles: {} });
  edges.reconcileAuthProfileQuotaBlocks.mockResolvedValue(undefined);
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

function deferred() {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const config: OpenClawConfig = {
  agents: {
    entries: {
      "fictitious-m9": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 } },
    },
  },
  mcp: { servers: { opsys_runtime_demo: { url: "http://localhost/mcp/runtime/demo" } } },
};

type EdgeRequest = { tool: string; args: Record<string, unknown> };
beforeEach(() => {
  const reservations = new Map<string, Record<string, unknown>>();
  edge.callOpsysMcpTool.mockReset();
  edge.callOpsysMcpTool.mockImplementation(async ({ tool, args }: EdgeRequest) => {
    const id = "0123456789abcdef0123456789abcdef";
    if (tool === "opsys_runtime_admettre") {
      const receipt = {
        id,
        agent_id: "demo",
        departement: "m09-strategic-intelligence",
        cle_idempotence: args.cle_idempotence,
        tokens_plafond: args.tokens_plafond,
        tokens_reels: null,
        execution_id: args.execution_id,
        tours: args.tours,
        reessais: args.candidate_index,
        statut: "reservee",
        attempt_id: args.attempt_id,
        cycle_id: args.cycle_id,
        candidate_index: args.candidate_index,
        stream_ordinal: args.stream_ordinal,
        is_fallback_retry: args.is_fallback_retry,
      };
      reservations.set(id, receipt);
      return { ok: true, accord_neuf: true, resultat: receipt };
    }
    const receipt =
      typeof args.reservation_id === "string" ? reservations.get(args.reservation_id) : undefined;
    if (!receipt) {
      throw new Error("fictitious reservation missing");
    }
    if (tool === "opsys_runtime_concilier") {
      return {
        ok: true,
        resultat: { ...receipt, statut: "conciliee", tokens_reels: args.tokens_reels },
      };
    }
    if (tool === "opsys_runtime_liberer_avant_dispatch") {
      return { ok: true, resultat: { ...receipt, statut: "liberee" } };
    }
    throw new Error("unexpected fictitious MCP edge");
  });
});

// Real canonical admission + registry + runtime + stream. Provider effects/MCP are fictional edges only.
async function fixture(label = "") {
  const signal = new AbortController();
  const resultEntered = deferred(),
    resultGate = deferred(),
    tailGate = deferred(),
    tailEntered = deferred();
  const calls = {
    dispatch: 0,
    effects: 0,
    results: 0,
    dispose: 0,
    sourceClose: 0,
    ownerEnter: 0,
    ownerExit: 0,
    tailChecks: 0,
  };
  const behavior = {
    current: true,
    holdResult: false,
    holdTail: false,
    missingUsage: false,
    failResult: false,
    failDispose: false,
  };
  const refusal = new Error("fictitious original source revoked");
  const failure = new Error("fictitious exact provider result failure");
  const events: string[] = [];
  const assertSource = () => {
    signal.signal.throwIfAborted();
    if (!behavior.current) {
      throw refusal;
    }
  };
  const operatorAuthority = createAdmittedRunOperatorAuthority({
    profileId: "fictitious-operator",
    scopes: ["operator.admin"],
    signal: signal.signal,
    assertCurrent: assertSource,
  });
  let sourceClosed = false;
  const source: PrivateM9AuditSource = {
    operatorAuthority,
    signal: signal.signal,
    assertSourceCurrent: assertSource,
    close: () => {
      if (!sourceClosed) {
        sourceClosed = true;
        calls.sourceClose++;
        behavior.current = false;
      }
    },
  };
  const runId = "fictitious-private-prepared-run" + label;
  const admission = preparePrivateM9AdmissionBinding({
    cfg: {},
    facts: {
      runId,
      agentId: "fictitious-m9",
      ingress: { kind: "system", boundary: "private-prepared-fixture", state: "present" },
    },
    operationalRunInstance: createOperationalRunInstanceRef(runId),
    signal: signal.signal,
    operatorAuthority,
    assertSourceCurrent: assertSource,
  });
  const context = await admission.admit("gateway", "fictitious-private-runtime");
  const transport = resolvedModel;
  const message: AssistantMessage = {
    role: "assistant",
    api: "openai-responses",
    provider: "openai",
    model: transport.id,
    content: [{ type: "text", text: "fictitious draft only" }],
    stopReason: "stop",
    timestamp: 1,
    usage: {
      input: 1,
      output: 2,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 3,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
  };
  const observed: {
    model?: Model;
    context?: Parameters<ApiProvider["streamSimple"]>[1];
    options?: Parameters<ApiProvider["streamSimple"]>[2];
  } = {};
  const provider: ApiProvider<"openai-responses">["streamSimple"] = (
    model,
    providerContext,
    options,
  ) => {
    calls.dispatch++;
    observed.model = model;
    observed.context = providerContext;
    observed.options = options;
    const fence = capturePrivateProviderRequestFence();
    if (!fence) {
      throw new Error("fictitious provider requires actual private fence");
    }
    const stream = createAssistantMessageEventStream();
    stream.end(message);
    if (behavior.holdTail) {
      void trackAsyncWork(async () => {
        tailEntered.resolve();
        await tailGate.promise;
        fence.validateFetch(model, "https://public.example/v1/responses", {
          method: "POST",
          body: "{}",
        });
        calls.tailChecks++;
        events.push("tailDone");
      }).catch(() => {});
    }
    stream.result = async () => {
      calls.results++;
      resultEntered.resolve();
      if (behavior.holdResult) {
        await resultGate.promise;
      }
      fence.validateFetch(model, "https://public.example/v1/responses", {
        method: "POST",
        body: "{}",
      });
      fence.claim();
      calls.effects++;
      if (behavior.failResult) {
        throw failure;
      }
      if (behavior.missingUsage) {
        message.usage.totalTokens = 0;
      }
      return message;
    };
    return stream;
  };
  const runtime = edges.runtime();
  runtime.registry.registerApiProvider({
    api: "openai-responses",
    stream: provider,
    streamSimple: provider,
  });
  const setupParent = new AsyncWorkScope();
  edges.disposeRuntime.mockImplementation(async () => {
    calls.dispose++;
    events.push("physicalRelease");
  });
  const acquired = await setupParent.run(() =>
    acquireSimpleCompletionModelWithSelection(
      {
        cfg: config,
        agentId: "fictitious-m9",
        agentDir: "/fictitious/agent",
        modelResolver: resolver,
        signal: signal.signal,
      },
      () => ({ selection: { provider: "openai", modelId: transport.id } }),
      { privateCompletionOwner: true },
    ),
  );
  if ("error" in acquired) {
    throw new Error(acquired.error);
  }
  const logical = acquired.model;
  // Independent setup witness precedes admission of any completion work.
  await setupParent.runWhenIdle(() => {
    events.push("setupIdle");
  });
  const options: PrivateM9PreparedStreamOptions = {
    prepared: acquired,
    source,
    admission,
    context,
    config,
    custodyBinding: {
      agentId: "fictitious-m9",
      profileId: "demo",
      profileRevision: 1,
      departement: "m09-strategic-intelligence",
      runId,
      candidateIndex: 0,
      streamOrdinals: [0],
    },
    route: {
      provider: "openai",
      modelId: transport.id,
      sourceApi: "openai-responses",
      url: "https://public.example/v1/responses",
    },
    completion: {
      context: {
        messages: [{ role: "user", content: "fictitious draft", timestamp: 1 }],
        tools: [],
      },
      options: { maxTokens: 16 },
    },
  };
  const owned: ReturnType<typeof runPrivateM9PreparedStream>[] = [];
  const launch = (input = options) => {
    const promise = runPrivateM9PreparedStream(input);
    owned.push(promise);
    void promise.catch(() => {});
    return promise;
  };
  const cleanup = async () => {
    resultGate.resolve();
    tailGate.resolve();
    await Promise.allSettled(owned);
    admission.close();
    source.close();
    await Promise.allSettled([acquired[Symbol.asyncDispose]()]);
    await setupParent.drain();
  };
  return {
    options,
    launch,
    cleanup,
    calls,
    behavior,
    signal,
    resultEntered,
    resultGate,
    tailEntered,
    tailGate,
    observed,
    transport,
    runtime,
    logical,
    message,
    refusal,
    failure,
    events,
  };
}

async function waitForEntry(entry: Promise<void>, completion: Promise<unknown>): Promise<void> {
  await Promise.race([
    entry,
    completion.then(() => {
      throw new Error("fictitious operation settled before its expected entry");
    }),
  ]);
}

describe("real canonical lease and private M9 stream composition", () => {
  it("preserves the exact provider result error through real acquisition and private stream disposal", async () => {
    const f = await fixture();
    let completion: ReturnType<typeof runPrivateM9PreparedStream> | undefined;
    let publication: Promise<void> | undefined;
    let published = 0;
    try {
      expect(getModelCompletionOwner(f.logical)).toBeDefined();
      expect(getModelLlmRuntime(f.logical)).toBe(f.runtime);
      expect(getModelCompletionTransport(f.logical)).toBe(f.transport);
      f.behavior.holdResult = true;
      f.behavior.holdTail = true;
      f.behavior.failResult = true;
      completion = f.launch();
      publication = completion.then(
        () => {
          published++;
        },
        () => {},
      );
      await waitForEntry(f.resultEntered.promise, completion);
      await waitForEntry(f.tailEntered.promise, completion);
      expect(f.calls.dispose).toBe(0);
      f.resultGate.resolve();
      f.tailGate.resolve();
      const [outcome] = await Promise.allSettled([completion]);
      await publication;
      expect(outcome.status).toBe("rejected");
      if (outcome.status !== "rejected") {
        throw new Error("fictitious failed result unexpectedly published");
      }
      expect(edges.ensureAuthProfileStore).toHaveBeenCalledTimes(1);
      expect(edges.ensureAuthProfileStore).toHaveBeenCalledWith("/fictitious/agent", {
        readOnly: true,
        allowKeychainPrompt: false,
        config,
        profileId: undefined,
      });
      expect(edges.reconcileAuthProfileQuotaBlocks).toHaveBeenCalledTimes(1);
      expect(edges.reconcileAuthProfileQuotaBlocks).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "openai",
          authProfileStore: { version: 1, profiles: {} },
          agentDir: "/fictitious/agent",
        }),
      );
      expect(f.calls.results).toBe(1);
      expect(f.calls.effects).toBe(1);
      expect(f.calls.tailChecks).toBe(1);
      expect(f.calls.dispose).toBe(1);
      expect(f.events.indexOf("setupIdle")).toBeLessThan(f.events.indexOf("physicalRelease"));
      expect(f.events.indexOf("tailDone")).toBeLessThan(f.events.indexOf("physicalRelease"));
      expect(published).toBe(0);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([request]) => request.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(0);
      const admissionCalls = edge.callOpsysMcpTool.mock.calls.filter(
        ([request]) => request.tool === "opsys_runtime_admettre",
      );
      expect(admissionCalls).toHaveLength(1);
      const admissionRequest = admissionCalls[0]?.[0];
      if (
        !admissionRequest ||
        typeof admissionRequest.args.attempt_id !== "string" ||
        typeof admissionRequest.args.cycle_id !== "string"
      ) {
        throw new Error("fictitious captured admission tuple is missing");
      }
      const expectedReceipt = {
        agentId: f.options.custodyBinding.agentId,
        profileId: f.options.custodyBinding.profileId,
        profileRevision: f.options.custodyBinding.profileRevision,
        departement: f.options.custodyBinding.departement,
        runId: f.options.custodyBinding.runId,
        attemptId: admissionRequest.args.attempt_id,
        cycleId: admissionRequest.args.cycle_id,
      };
      expect(getOpsysRuntimeCompletionReceipt(f.message, expectedReceipt)).toBeUndefined();
      // Primary discriminator: current static trace predicts AggregateError([E,E]), not this identity.
      expect(outcome.reason).toBe(f.failure);
    } finally {
      f.resultGate.resolve();
      f.tailGate.resolve();
      await Promise.allSettled([
        ...(completion ? [completion] : []),
        ...(publication ? [publication] : []),
      ]);
      await f.cleanup();
    }
  });
});
