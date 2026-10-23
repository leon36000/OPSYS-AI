import { createHash } from "node:crypto";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { AssistantMessage, Context } from "openclaw/plugin-sdk/llm";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import { isRecordedModelFallbackStop } from "../model-fallback-stop.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../test-helpers/usage-fixtures.js";
import * as owner from "./opsys-runtime-admission.js";

// Private, fictional provider/MCP fixtures; they establish no current authority.
const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn<typeof callOpsysMcpTool>() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);
type Binding = {
  agentId: string;
  profileId: string;
  profileRevision: number;
  departement: string;
  runId: string;
  candidateIndex: number;
  streamOrdinals: readonly number[];
};
type CustodyAPI = {
  create: (binding: Binding) => unknown;
  consume: (
    handle: unknown,
  ) =>
    | readonly Readonly<{ message: unknown; receipt: owner.OpsysRuntimeCompletionReceipt }>[]
    | undefined;
  close: (handle: unknown) => void;
};
function custodyAPI(): CustodyAPI {
  const create: unknown = Reflect.get(owner, "createOpsysRuntimeCompletionCustody");
  if (typeof create !== "function") {
    throw new Error("M9_CUSTODY_FACTORY_MISSING");
  }
  const consume: unknown = Reflect.get(owner, "consumeOpsysRuntimeCompletionCustody");
  const close: unknown = Reflect.get(owner, "closeOpsysRuntimeCompletionCustody");
  if (typeof consume !== "function" || typeof close !== "function") {
    throw new Error("M9_CUSTODY_API_MISSING");
  }
  return {
    create: create as CustodyAPI["create"],
    consume: consume as CustodyAPI["consume"],
    close: close as CustodyAPI["close"],
  };
}
const config: OpenClawConfig = {
  agents: {
    entries: {
      "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 } },
    },
  },
  mcp: { servers: { opsys_runtime_demo: { url: "http://localhost/mcp/runtime/demo" } } },
};
const model = makeProviderModelFixture({
  id: "custody-fictional",
  provider: "openai",
  api: "openai-completions",
  baseUrl: "https://example.invalid",
  contextWindow: 64,
  maxTokens: 16,
});
const context: Context = { messages: [] };
function binding(ordinals: readonly number[] = [0], patch: Partial<Binding> = {}): Binding {
  return {
    agentId: "opsys-agent-demo",
    profileId: "demo",
    profileRevision: 1,
    departement: "m01-front-office",
    runId: "custody-fictional",
    candidateIndex: 2,
    streamOrdinals: ordinals,
    ...patch,
  };
}
function message(text = "Fictional historical result"): AssistantMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    api: "openai-completions",
    provider: "openai",
    model: "custody-fictional",
    usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
    stopReason: "stop",
    timestamp: 1,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function installReplies() {
  let ordinal = 0;
  const records = new Map<string, Record<string, unknown>>();
  mocks.callOpsysMcpTool.mockImplementation(async (request) => {
    const args = request.args;
    if (request.tool === "opsys_runtime_admettre") {
      const id = (++ordinal).toString(16).padStart(32, "0");
      const record = {
        id,
        agent_id: "demo",
        departement: "m01-front-office",
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
      records.set(id, record);
      return { ok: true, resultat: record, accord_neuf: true };
    }
    const record =
      typeof args.reservation_id === "string" ? records.get(args.reservation_id) : undefined;
    if (!record) {
      throw new Error("FICTIONAL_UNKNOWN_RESERVATION");
    }
    if (request.tool === "opsys_runtime_concilier") {
      return {
        ok: true,
        resultat: { ...record, statut: "conciliee", tokens_reels: args.tokens_reels },
      };
    }
    if (request.tool === "opsys_runtime_liberer_avant_dispatch") {
      return { ok: true, resultat: { ...record, statut: "liberee" } };
    }
    throw new Error("FICTIONAL_UNEXPECTED_TOOL");
  });
}
function reconciliations() {
  return mocks.callOpsysMcpTool.mock.calls.filter(
    ([request]) => request.tool === "opsys_runtime_concilier",
  );
}
function streams(
  handle: unknown,
  results: readonly (() => Promise<AssistantMessage>)[],
  patch: Partial<Parameters<typeof owner.createOpsysRuntimeAdmissionStreamFn>[0]> = {},
) {
  let index = 0;
  const provider = vi.fn<StreamFn>(async () => {
    const result = results[index++];
    if (!result) {
      throw new Error("FICTIONAL_UNEXPECTED_PROVIDER");
    }
    return { result, async *[Symbol.asyncIterator]() {} };
  });
  const parameters: Parameters<typeof owner.createOpsysRuntimeAdmissionStreamFn>[0] = {
    config,
    agentId: "opsys-agent-demo",
    runId: "custody-fictional",
    getCandidateIndex: () => 2,
    streamFn: provider,
    ...patch,
  };
  // Explicit fixture boundary: handles can deliberately be malformed or unbranded unknown values.
  Reflect.set(parameters, "completionCustody", handle);
  const guarded = owner.createOpsysRuntimeAdmissionStreamFn(parameters);
  return { provider, open: () => guarded(model, context), parameters };
}
async function complete(
  handle: unknown,
  value = message(),
  patch: Partial<Parameters<typeof owner.createOpsysRuntimeAdmissionStreamFn>[0]> = {},
) {
  const result = vi.fn(async () => value);
  const fixture = streams(handle, [result], patch);
  const stream = await fixture.open();
  const first = stream.result();
  expect(stream.result()).toBe(first);
  expect(await first).toBe(value);
  return { ...fixture, stream, value, result };
}

describe("OPSYS private completion custody owner contract", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockClear();
    installReplies();
  });
  it("returns original A then B by upfront ordinal when B completes first", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([1, 0]));
    const a = message("A"),
      b = message("B");
    const pendingA = deferred<AssistantMessage>(),
      pendingB = deferred<AssistantMessage>();
    const resultA = vi.fn(() => pendingA.promise),
      resultB = vi.fn(() => pendingB.promise);
    const fixture = streams(handle, [resultA, resultB]);
    const streamA = await fixture.open(),
      streamB = await fixture.open();
    const pa = streamA.result(),
      pb = streamB.result();
    expect(streamA.result()).toBe(pa);
    expect(streamB.result()).toBe(pb);
    pendingB.resolve(b);
    expect(await pb).toBe(b);
    pendingA.resolve(a);
    expect(await pa).toBe(a);
    const batch = api.consume(handle);
    expect(batch?.map((entry) => entry.message)).toEqual([a, b]);
    expect(batch?.[0]?.message).toBe(a);
    expect(batch?.[1]?.message).toBe(b);
    expect(batch?.map((entry) => entry.receipt)).toEqual(
      [0, 1].map((streamOrdinal) => ({
        agentId: "opsys-agent-demo",
        profileId: "demo",
        profileRevision: 1,
        departement: "m01-front-office",
        runId: "custody-fictional",
        attemptId: "custody-fictional:2",
        cycleId: "custody-fictional:2:" + streamOrdinal,
        candidateIndex: 2,
        streamOrdinal,
        tokensReels: 3,
        resultSHA256: createHash("sha256")
          .update(JSON.stringify(streamOrdinal === 0 ? a : b), "utf8")
          .digest("hex"),
      })),
    );
    expect(Object.isFrozen(batch)).toBe(true);
    for (const entry of batch ?? []) {
      expect(Object.isFrozen(entry)).toBe(true);
      expect(Object.isFrozen(entry.receipt)).toBe(true);
      const receipt = entry.receipt;
      expect(receipt).toBe(owner.getOpsysRuntimeCompletionReceipt(entry.message, receipt));
      expect(Object.keys(entry).toSorted()).toEqual(["message", "receipt"]);
    }
    expect(resultA).toHaveBeenCalledOnce();
    expect(resultB).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(2);
    expect(api.consume(handle)).toBeUndefined();
  });

  it("B alone cannot authorize the batch and late A cannot resurrect consumed custody", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const a = message("A"),
      b = message("B");
    const pendingA = deferred<AssistantMessage>();
    const resultA = vi.fn(() => pendingA.promise),
      resultB = vi.fn(async () => b);
    const fixture = streams(handle, [resultA, resultB]);
    const sa = await fixture.open(),
      sb = await fixture.open();
    const pa = sa.result(),
      pb = sb.result();
    expect(await pb).toBe(b);
    expect(api.consume(handle)).toBeUndefined();
    pendingA.resolve(a);
    expect(await pa).toBe(a);
    expect(sa.result()).toBe(pa);
    expect(sb.result()).toBe(pb);
    expect(api.consume(handle)).toBeUndefined();
    expect(resultA).toHaveBeenCalledOnce();
    expect(resultB).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(2);
  });

  it("declared but never started ordinal prevents a complete batch", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("consumption before reconciliation is sticky even after successful sealing", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const release = deferred<void>(),
      entered = deferred<void>();
    const original = mocks.callOpsysMcpTool.getMockImplementation();
    if (!original) {
      throw new Error("FIXTURE_MISSING");
    }
    mocks.callOpsysMcpTool.mockImplementation(async (request) => {
      if (request.tool === "opsys_runtime_concilier") {
        entered.resolve(undefined);
        await release.promise;
      }
      return original(request);
    });
    const value = message();
    const fixture = streams(handle, [async () => value]);
    const stream = await fixture.open();
    const pending = stream.result();
    await entered.promise;
    expect(api.consume(handle)).toBeUndefined();
    release.resolve(undefined);
    expect(await pending).toBe(value);
    expect(api.consume(handle)).toBeUndefined();
  });

  it("explicit close is idempotent and late completion preserves provider success without resurrection", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const pendingResult = deferred<AssistantMessage>();
    const value = message();
    const fixture = streams(handle, [() => pendingResult.promise]);
    const stream = await fixture.open();
    const pending = stream.result();
    api.close(handle);
    api.close(handle);
    pendingResult.resolve(value);
    expect(await pending).toBe(value);
    expect(stream.result()).toBe(pending);
    expect(api.consume(handle)).toBeUndefined();
    expect(reconciliations()).toHaveLength(1);
  });

  it("complete batch is consumed exactly once and close after consumption is harmless", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const done = await complete(handle);
    const batch = api.consume(handle);
    expect(batch).toHaveLength(1);
    expect(batch?.[0]?.message).toBe(done.value);
    expect(api.consume(handle)).toBeUndefined();
    api.close(handle);
    expect(api.consume(handle)).toBeUndefined();
  });

  it("copies validated binding primitives and ordinal list before any stream call", async () => {
    const api = custodyAPI();
    const ordinals = [0];
    const input = binding(ordinals);
    const handle = api.create(input);
    input.runId = "mutated";
    input.profileRevision = 9;
    ordinals.push(1);
    const done = await complete(handle);
    expect(api.consume(handle)?.[0]?.message).toBe(done.value);
  });

  it("rejects custody capture for mismatched agentId", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { agentId: "other-agent" }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("rejects custody capture for mismatched profileId", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { profileId: "other-profile" }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("rejects custody capture for mismatched profileRevision", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { profileRevision: 2 }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("rejects custody capture for mismatched departement", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { departement: "m09-strategic-intelligence" }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("rejects custody capture for mismatched runId", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { runId: "other-run" }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("rejects custody capture for mismatched candidateIndex", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0], { candidateIndex: 3 }));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("unexpected stream ordinal invalidates custody without a provider fallback", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([1]));
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("duplicate cycle from two factories cannot replace the first captured original", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    await complete(handle, message("A"));
    const b = await complete(handle, message("B"));
    expect(api.consume(handle)).toBeUndefined();
    expect(b.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(2);
  });

  it("same original across two cycles cannot forge the second receipt", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const value = message();
    const fixture = streams(handle, [async () => value, async () => value]);
    await (await fixture.open()).result();
    await (await fixture.open()).result();
    expect(api.consume(handle)).toBeUndefined();
    expect(reconciliations()).toHaveLength(2);
    expect(
      owner.getOpsysRuntimeCompletionReceipt(value, {
        agentId: "opsys-agent-demo",
        profileId: "demo",
        profileRevision: 1,
        departement: "m01-front-office",
        runId: "custody-fictional",
        attemptId: "custody-fictional:2",
        cycleId: "custody-fictional:2:1",
      }),
    ).toBeUndefined();
  });

  it("mutation after completion invalidates consumption permanently", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const done = await complete(handle);
    const original = done.value.content;
    done.value.content = [{ type: "text", text: "mutated" }];
    expect(api.consume(handle)).toBeUndefined();
    done.value.content = original;
    expect(api.consume(handle)).toBeUndefined();
  });

  it("serialization failure cyclic preserves reconciled result but records no custody", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    Object.assign(value, { self: value });
    const done = await complete(handle, value);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("serialization failure bigint preserves reconciled result but records no custody", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    Object.assign(value, { extra: 1n });
    const done = await complete(handle, value);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("serialization failure throwing toJSON preserves reconciled result but records no custody", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    Object.assign(value, {
      toJSON: () => {
        throw new Error("FICTIONAL_SERIALIZATION");
      },
    });
    const done = await complete(handle, value);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("producer captures the sealed receipt without an extra JSON serialization", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const plain = { ...value };
    const serialize = vi.fn(() => plain);
    Object.assign(value, { toJSON: serialize });
    const done = await complete(handle, value);
    expect(serialize).toHaveBeenCalledTimes(1);
    expect(api.consume(handle)).toBeUndefined();
    expect(serialize).toHaveBeenCalledTimes(1);
    Reflect.deleteProperty(value, "toJSON");
    expect(api.consume(handle)).toBeUndefined();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("consumption closes before a reentrant serialization callback and never exposes partial records", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const plain = { ...value };
    let consuming = false;
    let nested: unknown = "unset";
    const serialize = vi.fn(() => {
      if (consuming) {
        nested = api.consume(handle);
      }
      return plain;
    });
    Object.assign(value, { toJSON: serialize });
    const done = await complete(handle, value);
    expect(serialize).toHaveBeenCalledTimes(1);
    consuming = true;
    const batch = api.consume(handle);
    expect(nested).toBe("unset");
    expect(batch).toBeUndefined();
    expect(serialize).toHaveBeenCalledTimes(1);
    Reflect.deleteProperty(value, "toJSON");
    expect(api.consume(handle)).toBeUndefined();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("admission failure cannot yield a complete batch or retry automatically", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const failure = new Error("FICTIONAL_ADMISSION");
    const result = vi.fn(async () => value);
    mocks.callOpsysMcpTool.mockRejectedValueOnce(failure);
    const fixture = streams(handle, [result]);
    await expect(fixture.open()).rejects.toBe(failure);
    expect(fixture.provider).not.toHaveBeenCalled();
    expect(api.consume(handle)).toBeUndefined();
    expect(api.consume(handle)).toBeUndefined();
  });

  it("result failure cannot yield a complete batch or retry automatically", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const failure = new Error("FICTIONAL_RESULT");
    const result = vi.fn(async () => value);
    result.mockRejectedValue(failure);
    const fixture = streams(handle, [result]);
    const stream = await fixture.open();
    const pending = stream.result();
    expect(stream.result()).toBe(pending);
    await expect(pending).rejects.toBe(failure);
    await expect(stream.result()).rejects.toBe(failure);
    expect(result).toHaveBeenCalledOnce();
    expect(api.consume(handle)).toBeUndefined();
    expect(api.consume(handle)).toBeUndefined();
  });

  it("reconciliation failure cannot yield a complete batch or retry automatically", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const failure = new Error("FICTIONAL_RECONCILIATION");
    const result = vi.fn(async () => value);
    const original = mocks.callOpsysMcpTool.getMockImplementation();
    if (!original) {
      throw new Error("FIXTURE_MISSING");
    }
    mocks.callOpsysMcpTool.mockImplementation(async (request) => {
      if (request.tool === "opsys_runtime_concilier") {
        throw failure;
      }
      return original(request);
    });
    const fixture = streams(handle, [result]);
    const stream = await fixture.open();
    const pending = stream.result();
    expect(stream.result()).toBe(pending);
    const terminal = await pending.catch((error: unknown) => error);
    expect(terminal).toBeInstanceOf(Error);
    if (!(terminal instanceof Error)) {
      throw new Error("FICTIONAL_RECONCILIATION_TERMINAL_MISSING");
    }
    expect(terminal).not.toBe(failure);
    expect(terminal.cause).toBe(failure);
    expect(isRecordedModelFallbackStop(terminal)).toBe(true);
    expect(isRecordedModelFallbackStop(failure)).toBe(false);
    await expect(stream.result()).rejects.toBe(terminal);
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
    expect(api.consume(handle)).toBeUndefined();
    expect(api.consume(handle)).toBeUndefined();
  });

  it("rejects empty agentId before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { agentId: "" }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects empty profileId before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { profileId: "" }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects empty runId before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { runId: "" }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects unknown department before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { departement: "invented" }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects noncanonical department before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { departement: " M01-FRONT-OFFICE " }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects zero revision before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { profileRevision: 0 }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects fractional revision before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { profileRevision: 1.5 }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects unsafe revision before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() =>
      api.create(binding([0], { profileRevision: Number.MAX_SAFE_INTEGER + 1 })),
    ).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects negative candidate before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { candidateIndex: -1 }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects fractional candidate before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { candidateIndex: 0.5 }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects unsafe candidate before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() =>
      api.create(binding([0], { candidateIndex: Number.MAX_SAFE_INTEGER + 1 })),
    ).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects empty ordinals before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { streamOrdinals: [] }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects seventeen ordinals before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() =>
      api.create(binding([0], { streamOrdinals: Array.from({ length: 17 }, (_, index) => index) })),
    ).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects duplicate ordinal before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { streamOrdinals: [0, 0] }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects negative ordinal before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { streamOrdinals: [-1] }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects fractional ordinal before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { streamOrdinals: [0.5] }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects unsafe ordinal before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() =>
      api.create(binding([0], { streamOrdinals: [Number.MAX_SAFE_INTEGER + 1] })),
    ).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("rejects NaN ordinal before any provider or MCP operation", async () => {
    const api = custodyAPI();
    expect(() => api.create(binding([0], { streamOrdinals: [Number.NaN] }))).toThrow();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("accepts all sixteen unique safe ordinals but refuses an incomplete batch", async () => {
    const api = custodyAPI();
    const handle = api.create(binding(Array.from({ length: 16 }, (_, index) => index)));
    expect(handle).toBeDefined();
    expect(api.consume(handle)).toBeUndefined();
  });

  it("refuses unbranded undefined handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    });
    const fake = undefined;
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("refuses unbranded null handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    });
    const fake = null;
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("refuses unbranded primitive handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    });
    const fake = "wire-handle";
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("refuses unbranded lookalike handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    });
    const fake = { streamOrdinals: [0], records: [] };
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("refuses unbranded JSON clone handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    }); // Deliberate wire JSON encode/decode tests loss of private host provenance.
    const encodedHandle = JSON.stringify(api.create(binding()));
    if (typeof encodedHandle !== "string") {
      throw new Error("FIXTURE_EXPECTED_WIRE_JSON");
    }
    const fake: unknown = JSON.parse(encodedHandle);
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("refuses unbranded proxy wrapper handle without invoking supplied callbacks", async () => {
    const api = custodyAPI();
    const callback = vi.fn(() => {
      throw new Error("UNTRUSTED_CALLBACK");
    });
    const originalHandle = api.create(binding());
    if (originalHandle === null || typeof originalHandle !== "object") {
      throw new Error("FIXTURE_EXPECTED_OBJECT_HANDLE");
    }
    const fake = new Proxy(originalHandle, {});
    if (
      fake &&
      typeof fake === "object" &&
      Object.getPrototypeOf(fake) === Object.prototype &&
      !Object.isFrozen(fake)
    ) {
      Object.assign(fake, { capture: callback, consume: callback, close: callback });
    }
    expect(api.consume(fake)).toBeUndefined();
    api.close(fake);
    api.close(fake);
    expect(callback).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });

  it("unknown handle is unrecorded while ordinary result memoization and reconciliation survive", async () => {
    const api = custodyAPI();
    const fake = {
      capture: vi.fn(() => {
        throw new Error("UNTRUSTED_CALLBACK");
      }),
    };
    const done = await complete(fake);
    expect(done.stream.result()).toBe(done.stream.result());
    expect(done.result).toHaveBeenCalledOnce();
    expect(fake.capture).not.toHaveBeenCalled();
    expect(api.consume(fake)).toBeUndefined();
    expect(reconciliations()).toHaveLength(1);
  });

  it("ordinary absent custody preserves the existing result and one reconciliation", async () => {
    custodyAPI();
    const done = await complete(undefined);
    expect(await done.stream.result()).toBe(done.value);
    expect(done.provider).toHaveBeenCalledOnce();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("zero usage leaves custody incomplete and preserves one cached result rejection", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    value.usage.totalTokens = 0;
    const result = vi.fn(async () => value);
    const fixture = streams(handle, [result]);
    const stream = await fixture.open();
    const pending = stream.result();
    expect(stream.result()).toBe(pending);
    await expect(pending).rejects.toThrow("no reliable token usage");
    expect(api.consume(handle)).toBeUndefined();
    expect(result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(0);
  });

  it("immutable admission capture survives mutable factory parameters after admission", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const fixture = streams(handle, [async () => value], {
      onAdmitted: () => {
        fixture.parameters.agentId = "other-agent";
        fixture.parameters.runId = "changed-run";
        fixture.parameters.getCandidateIndex = () => 99;
      },
    });
    const stream = await fixture.open();
    expect(await stream.result()).toBe(value);
    expect(api.consume(handle)?.[0]?.message).toBe(value);
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("close before dispatch never resurrects custody or changes ordinary provider success", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    api.close(handle);
    const done = await complete(handle);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("captures custody handle before awaited admission instead of mutable factory parameters", async () => {
    const api = custodyAPI();
    const originalHandle = api.create(binding());
    const replacementHandle = api.create(binding());
    const value = message();
    const result = vi.fn(async () => value);
    const fixture = streams(originalHandle, [result], {
      onAdmitted: () => {
        Reflect.set(fixture.parameters, "completionCustody", replacementHandle);
      },
    });
    const stream = await fixture.open();
    const pending = stream.result();
    expect(stream.result()).toBe(pending);
    expect(await pending).toBe(value);
    expect(api.consume(originalHandle)?.[0]?.message).toBe(value);
    expect(api.consume(replacementHandle)).toBeUndefined();
    expect(result).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("refuses B toJSON cross-mutation of already validated A without invoking consumer code", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const a = message("A original"),
      b = message("B original");
    const originalContent = a.content;
    const plainB = { ...b };
    let consuming = false;
    const serializeB = vi.fn(() => {
      if (consuming) {
        a.content = [{ type: "text", text: "A changed by B" }];
      }
      return plainB;
    });
    Object.assign(b, { toJSON: serializeB });
    const resultA = vi.fn(async () => a),
      resultB = vi.fn(async () => b);
    const fixture = streams(handle, [resultA, resultB]);
    const streamA = await fixture.open(),
      streamB = await fixture.open();
    const promiseA = streamA.result(),
      promiseB = streamB.result();
    expect(streamA.result()).toBe(promiseA);
    expect(streamB.result()).toBe(promiseB);
    expect(await promiseA).toBe(a);
    expect(await promiseB).toBe(b);
    expect(serializeB).toHaveBeenCalledTimes(1);
    serializeB.mockClear();
    consuming = true;
    expect(api.consume(handle)).toBeUndefined();
    expect(serializeB).not.toHaveBeenCalled();
    expect(a.content).toBe(originalContent);
    expect(resultA).toHaveBeenCalledOnce();
    expect(resultB).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledTimes(2);
    expect(reconciliations()).toHaveLength(2);
    expect(api.consume(handle)).toBeUndefined();
  });

  it("refuses a nested getter cross-mutation without reading the accessor during consumption", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const a = message("A original"),
      b = message("B original");
    const originalContent = a.content;
    let consuming = false;
    const read = vi.fn(() => {
      if (consuming) {
        a.content = [{ type: "text", text: "A changed by nested getter" }];
      }
      return "stable";
    });
    const nested = {};
    Object.defineProperty(nested, "field", { enumerable: true, configurable: true, get: read });
    Object.assign(b, { extra: nested });
    const resultA = vi.fn(async () => a),
      resultB = vi.fn(async () => b);
    const fixture = streams(handle, [resultA, resultB]);
    const streamA = await fixture.open(),
      streamB = await fixture.open();
    const promiseA = streamA.result(),
      promiseB = streamB.result();
    expect(streamA.result()).toBe(promiseA);
    expect(streamB.result()).toBe(promiseB);
    expect(await promiseA).toBe(a);
    expect(await promiseB).toBe(b);
    expect(read).toHaveBeenCalledTimes(1);
    read.mockClear();
    consuming = true;
    expect(api.consume(handle)).toBeUndefined();
    expect(read).not.toHaveBeenCalled();
    expect(a.content).toBe(originalContent);
    expect(resultA).toHaveBeenCalledOnce();
    expect(resultB).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledTimes(2);
    expect(reconciliations()).toHaveLength(2);
    expect(api.consume(handle)).toBeUndefined();
  });

  it("refuses root and nested Proxies before any consumer reflection trap", async () => {
    const api = custodyAPI();
    {
      const handle = api.create(binding());
      const traps = vi.fn<(operation: string) => void>();
      const value = new Proxy(message(), {
        get(target, key, receiver) {
          traps("get");
          return Reflect.get(target, key, receiver);
        },
        ownKeys(target) {
          traps("ownKeys");
          return Reflect.ownKeys(target);
        },
        getOwnPropertyDescriptor(target, key) {
          traps("getOwnPropertyDescriptor");
          return Reflect.getOwnPropertyDescriptor(target, key);
        },
        getPrototypeOf(target) {
          traps("getPrototypeOf");
          return Reflect.getPrototypeOf(target);
        },
      });
      const done = await complete(handle, value);
      traps.mockClear();
      expect(api.consume(handle)).toBeUndefined();
      expect(traps).not.toHaveBeenCalled();
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(1);
    }
    {
      const handle = api.create(binding());
      const traps = vi.fn<(operation: string) => void>();
      const nested = new Proxy(
        { plain: "nested" },
        {
          get(target, key, receiver) {
            traps("get");
            return Reflect.get(target, key, receiver);
          },
          ownKeys(target) {
            traps("ownKeys");
            return Reflect.ownKeys(target);
          },
          getOwnPropertyDescriptor(target, key) {
            traps("getOwnPropertyDescriptor");
            return Reflect.getOwnPropertyDescriptor(target, key);
          },
          getPrototypeOf(target) {
            traps("getPrototypeOf");
            return Reflect.getPrototypeOf(target);
          },
        },
      );
      const value = message();
      Object.assign(value, { extra: nested });
      const done = await complete(handle, value);
      traps.mockClear();
      expect(api.consume(handle)).toBeUndefined();
      expect(traps).not.toHaveBeenCalled();
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(2);
    }
  });

  it("refuses inherited toJSON on a custom prototype without calling it during consumption", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const plain = { ...value };
    const serialize = vi.fn(() => plain);
    Object.setPrototypeOf(value, { toJSON: serialize });
    const done = await complete(handle, value);
    expect(serialize).toHaveBeenCalledTimes(1);
    serialize.mockClear();
    expect(api.consume(handle)).toBeUndefined();
    expect(serialize).not.toHaveBeenCalled();
    expect(done.result).toHaveBeenCalledOnce();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("refuses a function value with callable toJSON without invoking it during consumption", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const serialize = vi.fn(() => "stable-function-json");
    const callable = Object.assign(() => "not called", { toJSON: serialize });
    const value = message();
    Object.assign(value, { extra: callable });
    const done = await complete(handle, value);
    expect(serialize).toHaveBeenCalledTimes(1);
    serialize.mockClear();
    expect(api.consume(handle)).toBeUndefined();
    expect(serialize).not.toHaveBeenCalled();
    expect(done.result).toHaveBeenCalledOnce();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("refuses a sparse array without changing the successful provider result", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const value = message();
    const sparse = [1, 2, 3];
    Reflect.deleteProperty(sparse, "1");
    Object.assign(value, { extra: sparse });
    const done = await complete(handle, value);
    expect(1 in sparse).toBe(false);
    expect(api.consume(handle)).toBeUndefined();
    expect(done.result).toHaveBeenCalledOnce();
    expect(done.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("accepts null-prototype data and shared acyclic aliases in separate custody scenarios", async () => {
    const api = custodyAPI();
    {
      const handle = api.create(binding());
      const value = message();
      Object.setPrototypeOf(value, null);
      const nested = { field: "null-prototype data" };
      Object.setPrototypeOf(nested, null);
      const array = [1, null];
      Object.setPrototypeOf(array, null);
      Object.assign(nested, {
        array,
        undefinedValue: undefined,
        positiveInfinity: Number.POSITIVE_INFINITY,
        negativeInfinity: Number.NEGATIVE_INFINITY,
        notANumber: Number.NaN,
        symbolValue: Symbol("custody-fictional"),
      });
      Object.assign(value, { extra: nested });
      const done = await complete(handle, value);
      const batch = api.consume(handle);
      expect(batch?.[0]?.message).toBe(value);
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(1);
    }
    {
      const handle = api.create(binding());
      const value = message();
      const shared = { nested: { field: "shared data" } };
      Object.assign(value, { extra: { left: shared, right: shared } });
      const done = await complete(handle, value);
      const batch = api.consume(handle);
      expect(batch?.[0]?.message).toBe(value);
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(2);
    }
  });

  it("refuses disguised shared typed views DataView and SharedArrayBuffer despite Object prototype", async () => {
    const api = custodyAPI();
    {
      // Uint8Array backed by SharedArrayBuffer: internal binary slots survive this local prototype camouflage.
      const handle = api.create(binding());
      const buffer = new SharedArrayBuffer(4);
      const binary = new Uint8Array(buffer);
      binary[0] = 1;
      Object.setPrototypeOf(binary, Object.prototype);
      const value = message();
      Object.assign(value, { extra: binary });
      const done = await complete(handle, value);
      expect(api.consume(handle)).toBeUndefined();
      expect(done.value).toBe(value);
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(1);
      expect(api.consume(handle)).toBeUndefined();
    }
    {
      // DataView backed by SharedArrayBuffer: internal binary slots survive this local prototype camouflage.
      const handle = api.create(binding());
      const buffer = new SharedArrayBuffer(4);
      const binary = new DataView(buffer);
      Object.setPrototypeOf(binary, Object.prototype);
      const value = message();
      Object.assign(value, { extra: binary });
      const done = await complete(handle, value);
      expect(api.consume(handle)).toBeUndefined();
      expect(done.value).toBe(value);
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(2);
      expect(api.consume(handle)).toBeUndefined();
    }
    {
      // SharedArrayBuffer: internal binary slots survive this local prototype camouflage.
      const handle = api.create(binding());
      const binary = new SharedArrayBuffer(4);
      Object.setPrototypeOf(binary, Object.prototype);
      const value = message();
      Object.assign(value, { extra: binary });
      const done = await complete(handle, value);
      expect(api.consume(handle)).toBeUndefined();
      expect(done.value).toBe(value);
      expect(done.result).toHaveBeenCalledOnce();
      expect(done.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(3);
      expect(api.consume(handle)).toBeUndefined();
    }
  });
});
