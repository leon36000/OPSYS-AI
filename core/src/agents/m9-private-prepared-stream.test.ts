import { createHash } from "node:crypto";
import { createApiRegistry, createLlmRuntime, type ApiProvider } from "@openclaw/ai";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PrivateM9AuditSource } from "../gateway/m9-private-audit-source.js";
import { bindModelCompletionOwner, bindModelLlmRuntime } from "../llm/model-runtime-binding.js";
import type { AssistantMessage, Model } from "../llm/types.js";
import { createAssistantMessageEventStream } from "../llm/utils/event-stream.js";
import { trackAsyncWork } from "../shared/async-work-scope.js";
import {
  createAdmittedRunOperatorAuthority,
  createOperationalRunInstanceRef,
} from "./admitted-run-context.js";
import { getOpsysRuntimeCompletionReceipt } from "./embedded-agent-runner/opsys-runtime-admission.js";
import * as runtimeAdmission from "./embedded-agent-runner/opsys-runtime-admission.js";
import { preparePrivateM9AdmissionBinding } from "./m9-private-admission-binding.js";
import {
  runPrivateM9PreparedStream,
  type PrivateM9PreparedStreamOptions,
} from "./m9-private-prepared-stream.js";
import { capturePrivateProviderRequestFence } from "./private-single-provider-request.js";

const edge = vi.hoisted(() => ({
  callOpsysMcpTool:
    vi.fn<(request: { tool: string; args: Record<string, unknown> }) => Promise<unknown>>(),
}));
vi.mock("../context-engine/opsys-contexte-mcp.js", () => edge);
// Only setup-port import is inert here. This suite does not qualify real provider-port initialization.
vi.mock("./ai-transport-runtime-host.js", () => ({}));

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
    resultFailure: new Error("fictitious provider failure"),
    disposalFailure: new Error("fictitious disposal failure"),
  };
  const refusal = new Error("fictitious original source revoked");
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
  const transport: Model<"openai-responses"> = {
    id: "fictitious-model",
    provider: "openai",
    name: "Fictitious",
    api: "openai-responses",
    baseUrl: "https://public.example/v1",
    input: ["text"],
    reasoning: false,
    contextWindow: 16000,
    maxTokens: 128,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
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
        throw behavior.resultFailure;
      }
      if (behavior.missingUsage) {
        message.usage.totalTokens = 0;
      }
      return message;
    };
    return stream;
  };
  const registry = createApiRegistry();
  registry.registerApiProvider({
    api: "openai-responses",
    stream: provider,
    streamSimple: provider,
  });
  const runtime = createLlmRuntime(registry);
  const logical = bindModelCompletionOwner(
    bindModelLlmRuntime({ ...transport, api: "fictitious-logical-api" }, runtime, transport),
    {
      assertCurrent: assertSource,
      run: async (run) => {
        calls.ownerEnter++;
        try {
          return await run();
        } finally {
          calls.ownerExit++;
        }
      },
    },
  );
  let disposed = false;
  const dispose = async () => {
    if (!disposed) {
      disposed = true;
      calls.dispose++;
      if (behavior.failDispose) {
        throw behavior.disposalFailure;
      }
    }
  };
  const options: PrivateM9PreparedStreamOptions = {
    prepared: {
      model: logical,
      auth: { apiKey: "fictitious-not-secret", source: "fixture", mode: "api-key" },
      selection: { provider: "openai", modelId: transport.id, agentDir: "/fictitious" },
      [Symbol.asyncDispose]: dispose,
    },
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
    await dispose();
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

async function withFixture(run: (value: Awaited<ReturnType<typeof fixture>>) => Promise<void>) {
  const value = await fixture();
  try {
    await run(value);
  } finally {
    await value.cleanup();
  }
}

describe("private M9 prepared stream owner", () => {
  it("preserves exact prepared transport runtime model and credential with no default dispatch", async () =>
    withFixture(async (f) => {
      const completion = f.launch();
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
      expect(() => f.options.admission.claim(f.options.context)).toThrow("ALREADY_CLAIMED");
      const result = await completion;
      expect(f.observed.model).toBe(f.transport);
      expect(f.observed.context).toBe(f.options.completion.context);
      expect(f.observed.options?.apiKey).toBe("fictitious-not-secret");
      expect(f.observed.options?.transport).toBe("sse");
      expect(f.calls.dispatch).toBe(1);
      expect(f.calls.ownerEnter).toBe(1);
      expect(f.calls.ownerExit).toBe(1);
      expect(f.calls.effects).toBe(1);
      expect(JSON.parse(result.payloadJSON)).toEqual(f.message);
      expect(f.calls.dispose).toBe(1);
    }));
  it("refuses a missing runtime before reservation without defaults", async () =>
    withFixture(async (f) => {
      f.options.prepared.model = bindModelCompletionOwner(
        { ...f.transport },
        { run: (run) => run(), assertCurrent: () => {} },
      );
      await expect(f.launch()).rejects.toThrow("BINDINGS_REQUIRED");
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
      expect(f.calls.dispatch).toBe(0);
    }));
  it("refuses a missing completion transport before reservation", async () =>
    withFixture(async (f) => {
      f.options.prepared.model = bindModelCompletionOwner(
        bindModelLlmRuntime(f.transport, f.runtime),
        { run: (run) => run(), assertCurrent: () => {} },
      );
      await expect(f.launch()).rejects.toThrow("BINDINGS_REQUIRED");
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
    }));
  it("refuses a missing completion owner before reservation", async () =>
    withFixture(async (f) => {
      f.options.prepared.model = bindModelLlmRuntime(f.transport, f.runtime, f.transport);
      await expect(f.launch()).rejects.toThrow("BINDINGS_REQUIRED");
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
    }));
  it("rejects a cloned canonical context before any reservation", async () =>
    withFixture(async (f) => {
      await expect(f.launch({ ...f.options, context: { ...f.options.context } })).rejects.toThrow();
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
      expect(f.calls.effects).toBe(0);
    }));
  it("rejects a different branded operator source before any reservation", async () =>
    withFixture(async (f) => {
      const foreign = createAdmittedRunOperatorAuthority({
        profileId: "foreign",
        scopes: ["operator.admin"],
        assertCurrent: () => {},
      });
      await expect(
        f.launch({ ...f.options, source: { ...f.options.source, operatorAuthority: foreign } }),
      ).rejects.toThrow("SOURCE_IDENTITY");
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
    }));
  it("checks revoked source immediately on ownership transfer", async () =>
    withFixture(async (f) => {
      f.behavior.current = false;
      await expect(f.launch()).rejects.toThrow();
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
      expect(f.calls.dispose).toBe(1);
    }));
  it("rechecks source after setup await before invoking the dispatcher", async () =>
    withFixture(async (f) => {
      const result = f.launch();
      f.behavior.current = false;
      await expect(result).rejects.toThrow();
      expect(f.calls.dispatch).toBe(0);
      expect(edge.callOpsysMcpTool).not.toHaveBeenCalled();
    }));
  it("refuses an effect after source revocation while result is pending", async () =>
    withFixture(async (f) => {
      f.behavior.holdResult = true;
      const result = f.launch();
      await waitForEntry(f.resultEntered.promise, result);
      f.behavior.current = false;
      f.resultGate.resolve();
      await expect(result).rejects.toThrow();
      expect(f.calls.effects).toBe(0);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(0);
    }));
  it("consumes the exact reconciled original once and snapshots its bytes", async () =>
    withFixture(async (f) => {
      const result = await f.launch();
      expect(f.calls.results).toBe(1);
      expect(result.receipt.streamOrdinal).toBe(0);
      expect(result.receipt.resultSHA256).toBe(
        createHash("sha256").update(JSON.stringify(f.message)).digest("hex"),
      );
      expect(getOpsysRuntimeCompletionReceipt(f.message, result.receipt)).toBe(result.receipt);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_admettre",
        ),
      ).toHaveLength(1);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(1);
    }));
  it("names the refusal for a fictitious sparse custody batch and consumes only once", async () =>
    withFixture(async (f) => {
      // Defensive boundary only: the real custody producer pushes a dense frozen batch.
      const sparse: never[] = [];
      sparse.length = 1;
      const consume = vi
        .spyOn(runtimeAdmission, "consumeOpsysRuntimeCompletionCustody")
        .mockReturnValueOnce(sparse);
      try {
        await expect(f.launch()).rejects.toThrow("ORIGINAL_REQUIRED");
        expect(consume).toHaveBeenCalledTimes(1);
        expect(f.calls.results).toBe(1);
        expect(f.calls.dispose).toBe(1);
        expect(f.calls.ownerExit).toBe(1);
      } finally {
        consume.mockRestore();
      }
    }));
  it("keeps fence and model owner alive until cooperating work drains", async () =>
    withFixture(async (f) => {
      f.behavior.holdTail = true;
      const result = f.launch();
      await waitForEntry(f.tailEntered.promise, result);
      await waitForEntry(f.resultEntered.promise, result);
      expect(f.calls.dispose).toBe(0);
      expect(f.calls.ownerExit).toBe(0);
      f.tailGate.resolve();
      await result;
      expect(f.calls.ownerExit).toBe(1);
      expect(f.calls.dispose).toBe(1);
      expect(f.calls.tailChecks).toBe(1);
    }));
  it("refuses concurrent reuse without closing the first live owner", async () =>
    withFixture(async (f) => {
      f.behavior.holdResult = true;
      const first = f.launch();
      await waitForEntry(f.resultEntered.promise, first);
      await expect(f.launch()).rejects.toThrow("ALREADY_OWNED");
      f.resultGate.resolve();
      await first;
      expect(f.calls.dispatch).toBe(1);
      expect(f.calls.dispose).toBe(1);
    }));
  it("keeps unreliable usage terminal without replay or reconciliation", async () =>
    withFixture(async (f) => {
      f.behavior.missingUsage = true;
      await expect(f.launch()).rejects.toThrow("reliable token usage");
      expect(f.calls.dispatch).toBe(1);
      expect(f.calls.results).toBe(1);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(0);
    }));
  it("retains primary and disposal failures together without retry", async () =>
    withFixture(async (f) => {
      f.behavior.failResult = true;
      f.behavior.failDispose = true;
      const result = await Promise.allSettled([f.launch()]);
      const outcome = result[0];
      if (outcome.status !== "rejected") {
        throw new Error("expected both failures");
      }
      expect(outcome.reason).toBeInstanceOf(AggregateError);
      expect(outcome.reason.errors).toHaveLength(2);
      expect(f.calls.dispatch).toBe(1);
      expect(f.calls.dispose).toBe(1);
    }));
  it("retains distinct same-message failures in order without retry", async () =>
    withFixture(async (f) => {
      const primary = new Error("fictitious same failure");
      const disposal = new Error("fictitious same failure");
      f.behavior.resultFailure = primary;
      f.behavior.disposalFailure = disposal;
      f.behavior.failResult = true;
      f.behavior.failDispose = true;
      const [outcome] = await Promise.allSettled([f.launch()]);
      if (outcome.status !== "rejected") {
        throw new Error("expected both distinct failures");
      }
      expect(outcome.reason).toBeInstanceOf(AggregateError);
      expect(outcome.reason.errors).toHaveLength(2);
      expect(outcome.reason.errors[0]).toBe(primary);
      expect(outcome.reason.errors[1]).toBe(disposal);
      expect(outcome.reason.cause).toBe(primary);
      expect(f.calls).toMatchObject({ dispatch: 1, effects: 1, results: 1, dispose: 1 });
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(0);
    }));
  it("rejects an exact shared source before taking a distinct second lease or binding", async () => {
    const first = await fixture("-shared-source-first");
    let second: Awaited<ReturnType<typeof fixture>> | undefined;
    try {
      first.behavior.holdResult = true;
      const original = first.launch();
      await waitForEntry(first.resultEntered.promise, original);
      second = await fixture("-shared-source-second");
      expect(second.options.prepared).not.toBe(first.options.prepared);
      expect(second.options.admission).not.toBe(first.options.admission);
      const outcomes = await Promise.allSettled([
        second.launch({
          ...second.options,
          source: first.options.source,
          context: { ...first.options.context },
        }),
      ]);
      expect(outcomes[0].status).toBe("rejected");
      // These ownership assertions, rather than a refusal message, discriminate the old cleanup path.
      expect(first.calls.sourceClose).toBe(0);
      expect(first.calls.ownerExit).toBe(0);
      expect(first.calls.dispose).toBe(0);
      expect(second.calls.dispose).toBe(0);
      expect(second.calls.ownerEnter).toBe(0);
      expect(second.calls.sourceClose).toBe(0);
      const callerReceipt = second.options.admission.claim(second.options.context);
      expect(callerReceipt.context).toBe(second.options.context);
      expect(callerReceipt.assertCurrent).not.toThrow();
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_admettre",
        ),
      ).toHaveLength(1);
      first.resultGate.resolve();
      const result = await original;
      expect(first.calls.effects).toBe(1);
      expect(first.calls.results).toBe(1);
      expect(first.calls.dispose).toBe(1);
      expect(first.calls.sourceClose).toBe(1);
      expect(getOpsysRuntimeCompletionReceipt(first.message, result.receipt)).toBe(result.receipt);
      expect(JSON.parse(result.payloadJSON)).toEqual(first.message);
      expect(
        edge.callOpsysMcpTool.mock.calls.filter(
          ([r]: [EdgeRequest]) => r.tool === "opsys_runtime_concilier",
        ),
      ).toHaveLength(1);
    } finally {
      try {
        await second?.cleanup(); // Original sourceB, leaseB and real bindingB remain the caller's responsibility.
      } finally {
        await first.cleanup(); // Resolves the held result even if an ownership assertion failed.
      }
    }
    if (!second) {
      throw new Error("second caller fixture missing");
    }
    expect(second.calls.dispose).toBe(1);
    expect(second.calls.sourceClose).toBe(1);
    expect(second.options.source.assertSourceCurrent).toThrow();
    expect(() => second.options.admission.claim(second.options.context)).toThrow();
  });
});
