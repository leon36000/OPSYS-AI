import { createHash } from "node:crypto";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import {
  createAssistantMessageEventStream,
  type AssistantMessage,
  type Context,
} from "openclaw/plugin-sdk/llm";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { hasModelFallbackStop, resolveModelFallbackError } from "../failover-error.js";
import { isRecordedModelFallbackStop } from "../model-fallback-stop.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../test-helpers/usage-fixtures.js";
import * as runtimeAdmission from "./opsys-runtime-admission.js";

const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);

import {
  createOpsysRuntimeAdmissionStreamFn,
  type OpsysRuntimeAdmissionReceipt,
  opsysRuntimeCompactionRefusal,
} from "./opsys-runtime-admission.js";

const config = {
  agents: {
    entries: {
      "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 } },
    },
  },
  mcp: { servers: { opsys_runtime_demo: { url: "http://localhost/mcp/runtime/demo" } } },
} as never;

function envelope(resultat: Record<string, unknown>, accord_neuf?: boolean) {
  return { ok: true, resultat, ...(accord_neuf === undefined ? {} : { accord_neuf }) };
}

type RuntimeRequest = { tool: string; args: Record<string, unknown> };

function runtimeReceipt(
  request: RuntimeRequest,
  id: string,
  statut: string,
  tokensReels: number | null,
): Record<string, unknown> {
  const args = request.args;
  return {
    id,
    agent_id: "demo",
    departement: "m01-front-office",
    cle_idempotence: args.cle_idempotence,
    tokens_plafond: args.tokens_plafond,
    tokens_reels: tokensReels,
    execution_id: args.execution_id,
    tours: args.tours,
    reessais: args.candidate_index,
    statut,
    attempt_id: args.attempt_id,
    cycle_id: args.cycle_id,
    candidate_index: args.candidate_index,
    stream_ordinal: args.stream_ordinal,
    is_fallback_retry: args.is_fallback_retry,
  };
}

function installRuntimeReplies(ids: string[]): void {
  let nextId = 0;
  const receipts = new Map<string, Record<string, unknown>>();
  mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
    if (request.tool === "opsys_runtime_admettre") {
      const id = ids[nextId++];
      if (!id) {
        throw new Error("unexpected admission request in test fixture");
      }
      const receipt = runtimeReceipt(request, id, "reservee", null);
      receipts.set(id, receipt);
      return envelope(receipt, true);
    }
    const id = request.args.reservation_id;
    const previous = typeof id === "string" ? receipts.get(id) : undefined;
    if (!previous) {
      throw new Error("unexpected reservation id in test fixture");
    }
    if (request.tool === "opsys_runtime_concilier") {
      return envelope({
        ...previous,
        statut: "conciliee",
        tokens_reels: request.args.tokens_reels,
      });
    }
    if (request.tool === "opsys_runtime_liberer_avant_dispatch") {
      return envelope({ ...previous, statut: "liberee" });
    }
    throw new Error(`unexpected runtime tool in test fixture: ${request.tool}`);
  });
}

describe("OPSYS runtime provider admission", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });

  it("refuses generic compaction only for agents with configured runtime admission", () => {
    expect(opsysRuntimeCompactionRefusal(config, "opsys-agent-demo")).toContain(
      "cannot use generic compaction",
    );
    expect(opsysRuntimeCompactionRefusal(config, "unprofiled-agent")).toBeUndefined();
  });

  it("refuses before dispatch when the private server denies the budget", async () => {
    mocks.callOpsysMcpTool.mockRejectedValueOnce(new Error("budget insuffisant"));
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 4 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-demo-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("budget insuffisant");
    expect(provider).not.toHaveBeenCalled();
  });

  it("dispatches only on a fresh grant, then reconciles normalized usage", async () => {
    installRuntimeReplies(["4e66faedf8a702dc9e534b3ffe91e2e8"]);
    const message = { usage: { totalTokens: 9 } };
    const provider = vi.fn(async () => ({ result: async () => message })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-demo-0001",
      getCandidateIndex: () => 2,
      streamFn: provider,
    });

    const stream = await guarded(
      { contextWindow: 64, maxTokens: 16 } as never,
      { messages: [] } as never,
    );
    await expect(stream.result()).resolves.toBe(message);
    expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0]).toMatchObject({
      server: "opsys_runtime_demo",
      tool: "opsys_runtime_admettre",
      args: {
        execution_id: "run-demo-0001",
        revision_profil: 1,
        cle_idempotence: "run-demo-0001:2:0",
        attempt_id: "run-demo-0001:2",
        cycle_id: "run-demo-0001:2:0",
        candidate_index: 2,
        stream_ordinal: 0,
        tours: 1,
        is_fallback_retry: true,
      },
    });
    const requestedEnvelope = mocks.callOpsysMcpTool.mock.calls[0]?.[0].args.tokens_plafond;
    expect(Number.isSafeInteger(requestedEnvelope)).toBe(true);
    expect(requestedEnvelope).toBeGreaterThan(0);
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0]).toMatchObject({
      tool: "opsys_runtime_concilier",
      args: { reservation_id: "4e66faedf8a702dc9e534b3ffe91e2e8", tokens_reels: 9 },
    });
  });

  it("keeps an existing cycle from authorizing a second provider dispatch", async () => {
    mocks.callOpsysMcpTool.mockResolvedValueOnce(
      envelope({ id: "4e66faedf8a702dc9e534b3ffe91e2e8" }, false),
    );
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 1 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-demo-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("did not return a reservation id");
    expect(provider).not.toHaveBeenCalled();
  });

  it.each([
    ["execution_id", "another-run"],
    ["agent_id", "another-profile"],
    ["cycle_id", "another-cycle"],
    ["attempt_id", "another-attempt"],
    ["cle_idempotence", "another-cycle-key"],
    ["is_fallback_retry", true],
    ["tokens_plafond", 1],
    ["stream_ordinal", 99],
  ])("refuses a fresh receipt whose %s differs from the captured request", async (field, value) => {
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 1 } }),
    })) as unknown as StreamFn;
    mocks.callOpsysMcpTool.mockImplementationOnce(async (request: RuntimeRequest) =>
      envelope(
        {
          ...runtimeReceipt(request, "e1331a2dd75c467e8fe891e5d7525a57", "reservee", null),
          [field]: value,
        },
        true,
      ),
    );
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-receipt-check-001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("receipt does not match");
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
    expect(provider).not.toHaveBeenCalled();
  });

  it("refuses an admission receipt whose identifier is not 32-character truncated SHA-256 hex", async () => {
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 1 } }),
    })) as unknown as StreamFn;
    mocks.callOpsysMcpTool.mockImplementationOnce(async (request: RuntimeRequest) =>
      envelope(runtimeReceipt(request, "not-a-uuid", "reservee", null), true),
    );
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-receipt-id-001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("did not return a reservation id");
    expect(provider).not.toHaveBeenCalled();
  });

  it("rejects a reconciliation receipt bound to a different admitted profile", async () => {
    let admitted: Record<string, unknown> | undefined;
    mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
      if (request.tool === "opsys_runtime_admettre") {
        admitted = runtimeReceipt(request, "6a86117288b4f9ed098ef7c83218fca4", "reservee", null);
        return envelope(admitted, true);
      }
      return envelope({
        ...admitted,
        agent_id: "other-profile",
        statut: "conciliee",
        tokens_reels: request.args.tokens_reels,
      });
    });
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 1 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-reconcile-check-001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    const stream = await guarded(
      { contextWindow: 64, maxTokens: 16 } as never,
      { messages: [] } as never,
    );
    await expect(stream.result()).rejects.toMatchObject({
      message: "OPSYS runtime reconciliation failed after known provider usage; fallback is unsafe",
      cause: expect.objectContaining({
        message: "OPSYS runtime admission could not verify the reconciled provider usage",
      }),
    });
    expect(provider).toHaveBeenCalledOnce();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
  });

  it("fails closed on a legacy profile marker without a host-owned revision", async () => {
    const configWithoutRevision = {
      agents: {
        entries: { "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo" } } },
      },
      mcp: { servers: { opsys_runtime_demo: { url: "http://localhost/mcp/runtime/demo" } } },
    } as never;
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 1 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config: configWithoutRevision,
      agentId: "opsys-agent-demo",
      runId: "run-missing-revision-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("profile revision is required");
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
    expect(provider).not.toHaveBeenCalled();
  });

  it("counts tool-continuation streams as new cycles for the same candidate", async () => {
    installRuntimeReplies(["4e66faedf8a702dc9e534b3ffe91e2e8", "bbdd3f841ce0bb004a0a8a45e12b2f51"]);
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 2 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-demo-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    const first = await guarded(
      { contextWindow: 64, maxTokens: 16 } as never,
      { messages: [] } as never,
    );
    await first.result();
    const second = await guarded(
      { contextWindow: 64, maxTokens: 16 } as never,
      { messages: [] } as never,
    );
    await second.result();
    expect(provider).toHaveBeenCalledTimes(2);
    expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0].args).toMatchObject({
      attempt_id: "run-demo-0001:0",
      cycle_id: "run-demo-0001:0:0",
      stream_ordinal: 0,
    });
    expect(mocks.callOpsysMcpTool.mock.calls[2]?.[0].args).toMatchObject({
      attempt_id: "run-demo-0001:0",
      cycle_id: "run-demo-0001:0:1",
      stream_ordinal: 1,
    });
  });

  it("keeps the reservation open when provider usage is missing or zero", async () => {
    installRuntimeReplies(["f324814ccb38d729f542746a1b00680c"]);
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 0 } }),
    })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-demo-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });

    const stream = await guarded(
      { contextWindow: 64, maxTokens: 16 } as never,
      { messages: [] } as never,
    );
    await expect(stream.result()).rejects.toThrow("no reliable token usage");
    expect(provider).toHaveBeenCalledTimes(1);
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
  });
});

describe("OPSYS scheduled final provider authority", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });

  it("revalidates host authority after budget admission and before provider dispatch", async () => {
    const order: string[] = [];
    mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
      order.push("budget");
      return envelope(
        runtimeReceipt(request, "505b943d84d673119ac48e46b15d35dc", "reservee", null),
        true,
      );
    });
    const provider = vi.fn(async () => {
      order.push("provider");
      return { result: async () => ({ usage: { totalTokens: 4 } }) };
    }) as unknown as StreamFn;
    const beforeProviderDispatch = vi.fn(async (signal: AbortSignal) => {
      expect(signal.aborted).toBe(false);
      order.push("authority");
    });
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-final-0001",
      getCandidateIndex: () => 0,
      streamFn: provider,
      beforeProviderDispatch,
    });
    await guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never);
    expect(order).toEqual(["budget", "authority", "provider"]);
    expect(beforeProviderDispatch).toHaveBeenCalledTimes(1);
    expect(provider).toHaveBeenCalledTimes(1);
  });

  it("releases only the fresh pre-dispatch reservation when live authority is withdrawn", async () => {
    installRuntimeReplies(["d5277750b2d68d76da0e06a293cea344"]);
    const provider = vi.fn() as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-final-0002",
      getCandidateIndex: () => 0,
      streamFn: provider,
      beforeProviderDispatch: async () => {
        throw new Error("authority withdrawn");
      },
    });
    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("authority withdrawn");
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0].tool).toBe("opsys_runtime_admettre");
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0]).toMatchObject({
      server: "opsys_runtime_demo",
      tool: "opsys_runtime_liberer_avant_dispatch",
      args: {
        reservation_id: "d5277750b2d68d76da0e06a293cea344",
        execution_id: "run-final-0002",
        attempt_id: "run-final-0002:0",
        cycle_id: "run-final-0002:0:0",
        candidate_index: 0,
        stream_ordinal: 0,
        revision_profil: 1,
      },
    });
  });

  it("releases an admitted reservation when collector receipt publication fails before provider", async () => {
    const order: string[] = [];
    installRuntimeReplies(["71d2f9a60f5e86d4283c02d18fa794f3"]);
    const runtimeReply = mocks.callOpsysMcpTool.getMockImplementation();
    if (!runtimeReply) {
      throw new Error("expected runtime admission mock implementation");
    }
    mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
      if (request.tool === "opsys_runtime_admettre") {
        order.push("admission");
      } else if (request.tool === "opsys_runtime_liberer_avant_dispatch") {
        order.push("release");
      }
      return await runtimeReply(request);
    });
    const provider = vi.fn<StreamFn>(() => {
      order.push("provider");
      throw new Error("unexpected provider dispatch");
    });
    const receiptFailure = new Error("collector rejected malformed admission");
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-collector-receipt-failure",
      getCandidateIndex: () => 0,
      streamFn: provider,
      onAdmitted: () => {
        order.push("collector");
        throw receiptFailure;
      },
    });

    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toBe(receiptFailure);

    expect(order).toEqual(["admission", "collector", "release"]);
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0].tool).toBe(
      "opsys_runtime_liberer_avant_dispatch",
    );
  });

  it("checks authority again for every stream and fallback candidate", async () => {
    installRuntimeReplies(["a7ac07e9cd061d8a32af466d86351e0c", "fc78aec1ba5409e1bf83374cd0a337af"]);
    let candidateIndex = 0;
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 4 } }),
    })) as unknown as StreamFn;
    const beforeProviderDispatch = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("authority withdrawn for fallback"));
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-final-0003",
      getCandidateIndex: () => candidateIndex,
      streamFn: provider,
      beforeProviderDispatch,
    });
    await guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never);
    candidateIndex = 1;
    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow("authority withdrawn for fallback");
    expect(beforeProviderDispatch).toHaveBeenCalledTimes(2);
    expect(provider).toHaveBeenCalledTimes(1);
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0].args).toMatchObject({
      candidate_index: 1,
      stream_ordinal: 1,
      is_fallback_retry: true,
    });
    expect(mocks.callOpsysMcpTool.mock.calls[2]?.[0]).toMatchObject({
      tool: "opsys_runtime_liberer_avant_dispatch",
      args: {
        reservation_id: "fc78aec1ba5409e1bf83374cd0a337af",
        candidate_index: 1,
        stream_ordinal: 1,
      },
    });
  });

  it("does not dispatch when the host aborts during final authority validation", async () => {
    const controller = new AbortController();
    installRuntimeReplies(["b8809c51bcc82e596cc123b3380976a5"]);
    const provider = vi.fn() as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-final-0004",
      getCandidateIndex: () => 0,
      streamFn: provider,
      signal: controller.signal,
      beforeProviderDispatch: async () => {
        controller.abort();
      },
    });
    await expect(
      guarded({ contextWindow: 64, maxTokens: 16 } as never, { messages: [] } as never),
    ).rejects.toThrow();
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    const cleanup = mocks.callOpsysMcpTool.mock.calls[1]?.[0];
    expect(cleanup.tool).toBe("opsys_runtime_liberer_avant_dispatch");
    expect(cleanup.signal).not.toBe(controller.signal);
    expect(cleanup.signal.aborted).toBe(false);
    expect(cleanup.timeoutMs).toBe(10_000);
  });
});

describe("OPSYS provider cleanup certainty boundary", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });
  const model = makeProviderModelFixture({
    id: "fictif",
    provider: "openai",
    api: "openai-completions",
    baseUrl: "https://example.invalid",
    contextWindow: 64,
    maxTokens: 16,
  });
  const context: Context = { messages: [] };

  it.each(["sync", "async"])(
    "retains admission when the invoked provider throws %s",
    async (mode) => {
      const failure = new Error("provider result unknown fictif");
      installRuntimeReplies(["bb003591bfb3fd7048c6ff6ab4aed72b"]);
      const provider = vi.fn<StreamFn>(() => {
        if (mode === "sync") {
          throw failure;
        }
        return Promise.reject(failure);
      });
      const guarded = createOpsysRuntimeAdmissionStreamFn({
        config,
        agentId: "opsys-agent-demo",
        runId: "run-unknown-provider",
        getCandidateIndex: () => 0,
        streamFn: provider,
      });
      await expect(guarded(model, context)).rejects.toBe(failure);
      expect(provider).toHaveBeenCalledOnce();
      expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
    },
  );

  it("retains admission when the dispatched stream result rejects", async () => {
    const failure = new Error("provider stream lost fictif");
    installRuntimeReplies(["833bf4bf41a6aa54f594403a6c488842"]);
    const provider = vi.fn<StreamFn>(async () => ({
      result: async () => {
        throw failure;
      },
      async *[Symbol.asyncIterator]() {},
    }));
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-unknown-result",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });
    const stream = await guarded(model, context);
    await expect(stream.result()).rejects.toBe(failure);
    expect(provider).toHaveBeenCalledOnce();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
  });

  it("preserves the exact authority error when cleanup cannot be confirmed, without retry", async () => {
    const failure = new Error("authority withdrawn fictif");
    installRuntimeReplies(["25a443de3492a3f98c45dd8d7698944b"]);
    const validReplies = mocks.callOpsysMcpTool.getMockImplementation();
    mocks.callOpsysMcpTool
      .mockImplementationOnce(validReplies!)
      .mockRejectedValueOnce(new Error("private cleanup reply lost fictif"));
    const provider = vi.fn<StreamFn>(() => {
      throw new Error("unexpected dispatch");
    });
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-release-lost",
      getCandidateIndex: () => 0,
      streamFn: provider,
      beforeProviderDispatch: async () => {
        throw failure;
      },
    });
    await expect(guarded(model, context)).rejects.toBe(failure);
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
  });

  it("never attempts cleanup after an admission reply is lost", async () => {
    const failure = new Error("private admission result unknown fictif");
    mocks.callOpsysMcpTool.mockRejectedValueOnce(failure);
    const provider = vi.fn<StreamFn>(() => {
      throw new Error("unexpected dispatch");
    });
    const beforeProviderDispatch = vi.fn(async () => {});
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "run-admission-lost",
      getCandidateIndex: () => 0,
      streamFn: provider,
      beforeProviderDispatch,
    });
    await expect(guarded(model, context)).rejects.toBe(failure);
    expect(beforeProviderDispatch).not.toHaveBeenCalled();
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
  });

  it("captures the admitted profile/run/revision rather than mutable post-await configuration", async () => {
    const binding = { profileId: "demo", profileRevision: 1 };
    const server = {
      url: "http://localhost/mcp/runtime/demo",
      headers: { Authorization: "Bearer synthetic-original-not-a-credential" },
    };
    const changingConfig: OpenClawConfig = {
      agents: { entries: { "opsys-agent-demo": { opsysRuntimeAdmission: binding } } },
      mcp: { servers: { opsys_runtime_demo: server } },
    };
    const failure = new Error("authority withdrawn after config update fictif");
    installRuntimeReplies(["c7bf02ef74b89975ffdff334a04b4a64"]);
    const provider = vi.fn<StreamFn>(() => {
      throw new Error("unexpected dispatch");
    });
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config: changingConfig,
      agentId: "opsys-agent-demo",
      runId: "run-captured",
      getCandidateIndex: () => 0,
      streamFn: provider,
      beforeProviderDispatch: async () => {
        binding.profileId = "other";
        binding.profileRevision = 2;
        server.url = "http://localhost/mcp/runtime/other";
        server.headers.Authorization = "Bearer synthetic-replacement-not-a-credential";
        throw failure;
      },
    });
    await expect(guarded(model, context)).rejects.toBe(failure);
    expect(provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0]).toMatchObject({
      server: "opsys_runtime_demo",
      args: {
        reservation_id: "c7bf02ef74b89975ffdff334a04b4a64",
        revision_profil: 1,
        cycle_id: "run-captured:0:0",
      },
    });
    const reservedConfig = mocks.callOpsysMcpTool.mock.calls[0]?.[0].config;
    const cleanupConfig = mocks.callOpsysMcpTool.mock.calls[1]?.[0].config;
    expect(cleanupConfig).toBe(reservedConfig);
    expect(cleanupConfig).not.toBe(changingConfig);
    expect(cleanupConfig.mcp.servers.opsys_runtime_demo).toEqual({
      url: "http://localhost/mcp/runtime/demo",
      headers: { Authorization: "Bearer synthetic-original-not-a-credential" },
    });
  });

  it("reconciles usage on the admitted route when config and agent identity change during stream/result", async () => {
    const binding = { profileId: "demo", profileRevision: 1 };
    const server = {
      url: "http://localhost/mcp/runtime/demo",
      headers: { Authorization: "Bearer synthetic-original-not-a-credential" },
    };
    const changingConfig: OpenClawConfig = {
      agents: { entries: { "opsys-agent-demo": { opsysRuntimeAdmission: binding } } },
      mcp: { servers: { opsys_runtime_demo: server } },
    };
    const message: AssistantMessage = {
      role: "assistant",
      content: [],
      api: "openai-completions",
      provider: "openai",
      model: "fictif",
      usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
      stopReason: "stop",
      timestamp: 1,
    };
    installRuntimeReplies(["c603623e2286db59e60ff1a2f1a2f8a0"]);
    const provider = vi.fn<StreamFn>(async () => {
      binding.profileId = "other";
      binding.profileRevision = 2;
      server.url = "http://localhost/mcp/runtime/other";
      server.headers.Authorization = "Bearer synthetic-replacement-not-a-credential";
      return {
        result: async () => {
          parameters.agentId = "other-agent";
          return message;
        },
        async *[Symbol.asyncIterator]() {},
      };
    });
    const parameters: Parameters<typeof createOpsysRuntimeAdmissionStreamFn>[0] = {
      config: changingConfig,
      agentId: "opsys-agent-demo",
      runId: "run-conciliation-captured",
      getCandidateIndex: () => 0,
      streamFn: provider,
    };
    const stream = await createOpsysRuntimeAdmissionStreamFn(parameters)(model, context);
    await expect(stream.result()).resolves.toBe(message);
    expect(provider).toHaveBeenCalledOnce();
    expect(parameters.agentId).toBe("other-agent");
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0]).toMatchObject({
      server: "opsys_runtime_demo",
      tool: "opsys_runtime_concilier",
      args: { reservation_id: "c603623e2286db59e60ff1a2f1a2f8a0", tokens_reels: 3 },
    });
    const reservedConfig = mocks.callOpsysMcpTool.mock.calls[0]?.[0].config;
    const reconciledConfig = mocks.callOpsysMcpTool.mock.calls[1]?.[0].config;
    expect(reconciledConfig).toBe(reservedConfig);
    expect(reconciledConfig).not.toBe(changingConfig);
    expect(reconciledConfig.agents.entries["opsys-agent-demo"].opsysRuntimeAdmission).toEqual({
      profileId: "demo",
      profileRevision: 1,
    });
    expect(reconciledConfig.mcp.servers.opsys_runtime_demo).toEqual({
      url: "http://localhost/mcp/runtime/demo",
      headers: { Authorization: "Bearer synthetic-original-not-a-credential" },
    });
  });
});

// Private contract additions. All providers and MCP replies below are fictional;
// these assertions are NOT execution evidence until the admitted Native run.
describe("OPSYS host-owned completion receipt contract", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });

  const model = makeProviderModelFixture({
    id: "completion-fictif",
    provider: "openai",
    api: "openai-completions",
    baseUrl: "https://example.invalid",
    contextWindow: 64,
    maxTokens: 16,
  });
  const context: Context = { messages: [] };
  const reservationA = "11111111111111111111111111111111";
  const reservationB = "22222222222222222222222222222222";

  function messageFixture(): AssistantMessage {
    return {
      role: "assistant",
      content: [{ type: "text", text: "Réponse fictive de conseil, non validée." }],
      api: "openai-completions",
      provider: "openai",
      model: "completion-fictif",
      usage: { ...createZeroUsageFixture(), output: 3, totalTokens: 3 },
      stopReason: "stop",
      timestamp: 1,
    };
  }

  function expected(
    runId = "completion-A",
    candidateIndex = 2,
    ordinal = 0,
  ): OpsysRuntimeAdmissionReceipt {
    return {
      agentId: "opsys-agent-demo",
      profileId: "demo",
      profileRevision: 1,
      departement: "m01-front-office",
      runId,
      attemptId: `${runId}:${candidateIndex}`,
      cycleId: `${runId}:${candidateIndex}:${ordinal}`,
    };
  }

  function streamFixture(message: AssistantMessage, runId = "completion-A", candidateIndex = 2) {
    const originalResult = vi.fn(async () => message);
    const provider = vi.fn(async () => ({ result: originalResult })) as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId,
      getCandidateIndex: () => candidateIndex,
      streamFn: provider,
    });
    return { originalResult, provider, open: () => guarded(model, context) };
  }

  function getCompletion(message: unknown, hostExpected: OpsysRuntimeAdmissionReceipt): unknown {
    const getter: unknown = Reflect.get(runtimeAdmission, "getOpsysRuntimeCompletionReceipt");
    expect(getter, "contractual completion getter must be exported").toBeTypeOf("function");
    if (typeof getter !== "function") {
      throw new Error("contractual completion getter is absent");
    }
    return getter(message, hostExpected);
  }

  function reconciliations() {
    return mocks.callOpsysMcpTool.mock.calls.filter(([r]) => r.tool === "opsys_runtime_concilier");
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((done) => {
      resolve = done;
    });
    return { promise, resolve };
  }

  it("binds exact result bytes only after result and verified reconciliation, with sanitized frozen receipt", async () => {
    installRuntimeReplies([reservationA]);
    const reply = mocks.callOpsysMcpTool.getMockImplementation()!;
    const reconcileStarted = deferred<void>();
    const allowReconcile = deferred<void>();
    mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
      if (request.tool === "opsys_runtime_concilier") {
        reconcileStarted.resolve(undefined);
        await allowReconcile.promise;
      }
      return reply(request);
    });
    const message = messageFixture();
    const fixture = streamFixture(message);
    expect(getCompletion(message, expected())).toBeUndefined();
    const stream = await fixture.open();
    expect(getCompletion(message, expected())).toBeUndefined();
    const pending = stream.result();
    await reconcileStarted.promise;
    expect(getCompletion(message, expected())).toBeUndefined();
    allowReconcile.resolve(undefined);
    await expect(pending).resolves.toBe(message);
    const receipt = getCompletion(message, expected());
    expect(receipt).toEqual({
      ...expected(),
      candidateIndex: 2,
      streamOrdinal: 0,
      tokensReels: 3,
      resultSHA256: createHash("sha256").update(JSON.stringify(message), "utf8").digest("hex"),
    });
    expect(Object.isFrozen(receipt)).toBe(true);
    if (receipt === null || typeof receipt !== "object") {
      throw new Error("successful completion must expose an object receipt");
    }
    expect(Object.keys(receipt).toSorted()).toEqual(
      [
        ...Object.keys(expected()),
        "candidateIndex",
        "streamOrdinal",
        "tokensReels",
        "resultSHA256",
      ].toSorted(),
    );
    expect(receipt).not.toHaveProperty("reservationId");
    expect(receipt).not.toHaveProperty("config");
    expect(fixture.originalResult).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it.each([
    ["agentId", "other-agent"],
    ["profileId", "other-profile"],
    ["profileRevision", 2],
    ["departement", "m09-strategic-intelligence"],
    ["runId", "other-run"],
    ["attemptId", "other-attempt"],
    ["cycleId", "other-cycle"],
  ])("refuses lookup when the host expected tuple field %s differs", async (field, value) => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    await (await streamFixture(message).open()).result();
    expect(getCompletion(message, { ...expected(), [field]: value })).toBeUndefined();
    expect(getCompletion(message, expected())).toBeDefined();
  });

  it("refuses an incomplete expected tuple even when a model supplies identical tuple and receipt JSON", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    const forged = message as unknown as Record<string, unknown>;
    forged.hostReceipt = {
      ...expected(),
      candidateIndex: 2,
      streamOrdinal: 0,
      tokensReels: 3,
      resultSHA256: "f".repeat(64),
    };
    await (await streamFixture(message).open()).result();
    const incomplete = { ...expected() } as Partial<OpsysRuntimeAdmissionReceipt>;
    delete incomplete.cycleId;
    expect(getCompletion(message, incomplete as OpsysRuntimeAdmissionReceipt)).toBeUndefined();
    // Exercise an untrusted wire JSON copy rather than cloning a host object.
    const wireMessage = JSON.stringify(message);
    const copied = JSON.parse(wireMessage);
    expect(getCompletion(copied, expected())).toBeUndefined();
    expect(getCompletion(forged.hostReceipt, expected())).toBeUndefined();
    expect(getCompletion(message, expected())).toBeDefined();
  });

  it("memoizes concurrent and repeated result calls without rereading or reconciling", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    const fixture = streamFixture(message);
    const pendingMessage = deferred<AssistantMessage>();
    fixture.originalResult.mockImplementation(() => pendingMessage.promise);
    const stream = await fixture.open();
    const calls = [stream.result(), stream.result(), stream.result()];
    expect(getCompletion(message, expected())).toBeUndefined();
    pendingMessage.resolve(message);
    const results = await Promise.all(calls);
    expect(results.every((r) => r === message)).toBe(true);
    await expect(stream.result()).resolves.toBe(message);
    expect(fixture.originalResult).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
    expect(getCompletion(message, expected())).toBeDefined();
  });

  it("same object and same bytes across cycles retain only A binding while each stream reconciles once", async () => {
    installRuntimeReplies([reservationA, reservationB]);
    const message = messageFixture();
    const originalBytes = JSON.stringify(message);
    const a = streamFixture(message, "completion-A", 2);
    const streamA = await a.open();
    await Promise.all([streamA.result(), streamA.result()]);
    const receiptA = getCompletion(message, expected());
    expect(receiptA).toBeDefined();
    const b = streamFixture(message, "completion-B", 0);
    const streamB = await b.open();
    const resultsB = await Promise.all([streamB.result(), streamB.result()]);
    expect(resultsB[0]).toBe(message);
    expect(resultsB[1]).toBe(message);
    expect(JSON.stringify(message)).toBe(originalBytes);
    expect(getCompletion(message, expected("completion-B", 0))).toBeUndefined();
    expect(getCompletion(message, expected())).toEqual(receiptA);
    await Promise.all([streamA.result(), streamB.result()]);
    expect(a.originalResult).toHaveBeenCalledOnce();
    expect(b.originalResult).toHaveBeenCalledOnce();
    expect(a.provider).toHaveBeenCalledOnce();
    expect(b.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(2);
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(4);
  });

  it("rejects lookup for mutation of content or usage and permits only current original serialized bytes", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    await (await streamFixture(message).open()).result();
    const originalBytes = JSON.stringify(message);
    const receipt = getCompletion(message, expected());
    message.content = [{ type: "text", text: "Valeur fictive modifiée après résultat" }];
    expect(getCompletion(message, expected())).toBeUndefined();
    Object.assign(message, JSON.parse(originalBytes));
    message.usage.totalTokens = 4;
    expect(getCompletion(message, expected())).toBeUndefined();
    Object.assign(message, JSON.parse(originalBytes));
    expect(getCompletion(message, expected())).toEqual(receipt);
    expect(reconciliations()).toHaveLength(1);
  });

  it.each(["cyclic", "bigint", "toJSON throws"])(
    "sealing failure %s after successful reconciliation gives no proof and no new rejection/retry",
    async (cause) => {
      installRuntimeReplies([reservationA]);
      const message = messageFixture();
      const raw = message as unknown as Record<string, unknown>;
      if (cause === "cyclic") {
        raw.self = message;
      } else if (cause === "bigint") {
        raw.extra = BigInt(1);
      } else {
        raw.toJSON = () => {
          throw new Error("fictional serialization failure");
        };
      }
      const fixture = streamFixture(message);
      const stream = await fixture.open();
      const results = await Promise.all([stream.result(), stream.result()]);
      expect(results[0]).toBe(message);
      expect(results[1]).toBe(message);
      await expect(stream.result()).resolves.toBe(message);
      expect(() => getCompletion(message, expected())).not.toThrow();
      expect(getCompletion(message, expected())).toBeUndefined();
      expect(fixture.originalResult).toHaveBeenCalledOnce();
      expect(fixture.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(1);
    },
  );

  it("lookup serialization failure never throws and never overwrites the original association", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    await (await streamFixture(message).open()).result();
    const receipt = getCompletion(message, expected());
    const raw = message as unknown as Record<string, unknown>;
    raw.self = message;
    expect(() => getCompletion(message, expected())).not.toThrow();
    expect(getCompletion(message, expected())).toBeUndefined();
    delete raw.self;
    expect(getCompletion(message, expected())).toEqual(receipt);
  });

  it("pre-dispatch withdrawal publishes no completion and calls no provider", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    const provider = vi.fn() as unknown as StreamFn;
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId: "completion-A",
      getCandidateIndex: () => 2,
      streamFn: provider,
      beforeProviderDispatch: async () => {
        throw new Error("authority withdrawn fictif");
      },
    });
    await expect(guarded(model, context)).rejects.toThrow("authority withdrawn fictif");
    expect(provider).not.toHaveBeenCalled();
    expect(getCompletion(message, expected())).toBeUndefined();
    expect(reconciliations()).toHaveLength(0);
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
  });

  it("provider result rejection is cached without proof, reconciliation or automatic retry", async () => {
    installRuntimeReplies([reservationA]);
    const message = messageFixture();
    const fixture = streamFixture(message);
    const failure = new Error("fictional provider result UNKNOWN");
    fixture.originalResult.mockRejectedValue(failure);
    const stream = await fixture.open();
    const results = await Promise.allSettled([stream.result(), stream.result()]);
    expect(results).toEqual([
      { status: "rejected", reason: failure },
      { status: "rejected", reason: failure },
    ]);
    await expect(stream.result()).rejects.toBe(failure);
    expect(getCompletion(message, expected())).toBeUndefined();
    expect(fixture.originalResult).toHaveBeenCalledOnce();
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(0);
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
  });

  it.each([0, undefined, Number.NaN])(
    "unreliable usage %s is cached as rejection with no completion",
    async (usage) => {
      installRuntimeReplies([reservationA]);
      const message = messageFixture();
      (message.usage as unknown as Record<string, unknown>).totalTokens = usage;
      const fixture = streamFixture(message);
      const stream = await fixture.open();
      await expect(stream.result()).rejects.toThrow("no reliable token usage");
      await expect(stream.result()).rejects.toThrow("no reliable token usage");
      expect(getCompletion(message, expected())).toBeUndefined();
      expect(fixture.originalResult).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(0);
      expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["rpc failure", "wrong tuple"])(
    "reconciliation %s leaves no completion and is never retried",
    async (cause) => {
      const transportFailure = new Error("fictional reconciliation outcome UNKNOWN");
      installRuntimeReplies([reservationA]);
      const original = mocks.callOpsysMcpTool.getMockImplementation()!;
      mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
        const reply = await original(request);
        if (request.tool !== "opsys_runtime_concilier") {
          return reply;
        }
        if (cause === "rpc failure") {
          throw transportFailure;
        }
        return { ...reply, resultat: { ...reply.resultat, agent_id: "other-profile" } };
      });
      const message = messageFixture();
      const fixture = streamFixture(message);
      const stream = await fixture.open();
      const results = await Promise.allSettled([stream.result(), stream.result()]);
      expect(results[0].status).toBe("rejected");
      expect(results[1]).toEqual(results[0]);
      const rejected = results[0];
      if (rejected.status !== "rejected" || !(rejected.reason instanceof Error)) {
        throw new Error("Expected the terminal reconciliation wrapper");
      }
      const terminal = rejected.reason;
      expect(isRecordedModelFallbackStop(terminal)).toBe(true);
      expect(resolveModelFallbackError(terminal).kind).toBe("terminal");
      expect(hasModelFallbackStop(new Error("outer caller", { cause: terminal }))).toBe(true);
      if (cause === "rpc failure") {
        expect(terminal).not.toBe(transportFailure);
        expect(terminal.cause).toBe(transportFailure);
        expect(isRecordedModelFallbackStop(transportFailure)).toBe(false);
        expect(hasModelFallbackStop(transportFailure)).toBe(false);
      }
      await expect(stream.result()).rejects.toBe(terminal);
      expect(getCompletion(message, expected())).toBeUndefined();
      expect(fixture.originalResult).toHaveBeenCalledOnce();
      expect(fixture.provider).toHaveBeenCalledOnce();
      expect(reconciliations()).toHaveLength(1);
      expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    },
  );

  it("reconciles native done before delivery after run abort and shares later results", async () => {
    installRuntimeReplies([reservationA]);
    const runId = "completion-native-event-abort";
    const hostExpected = expected(runId, 0);
    const custody = runtimeAdmission.createOpsysRuntimeCompletionCustody({
      ...hostExpected,
      candidateIndex: 0,
      streamOrdinals: [0],
    });
    const message = messageFixture();
    const native = createAssistantMessageEventStream();
    const nativeResult = native.result.bind(native);
    let providerResultCalls = 0;
    native.result = () => {
      providerResultCalls += 1;
      return nativeResult();
    };
    native.push({ type: "start", partial: message });
    native.push({ type: "done", reason: "stop", message });
    native.end();
    let providerDispatches = 0;
    const provider: StreamFn = () => {
      providerDispatches += 1;
      return native;
    };
    const controller = new AbortController();
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId,
      getCandidateIndex: () => 0,
      signal: controller.signal,
      completionCustody: custody,
      streamFn: provider,
    });
    try {
      const stream = await guarded(model, context, { signal: controller.signal });
      expect(stream).toBe(native);
      controller.abort(new Error("fictional run cancellation after admitted native response"));
      const eventTypes: string[] = [];
      // Do not consume result() until the complete event-only drain has finished.
      for await (const event of stream) {
        eventTypes.push(event.type);
        if (event.type === "done") {
          expect(event.message).toBe(message);
          expect(reconciliations()).toHaveLength(1);
          expect(reconciliations()[0]?.[0]).toMatchObject({
            server: "opsys_runtime_demo",
            tool: "opsys_runtime_concilier",
            args: { reservation_id: "11111111111111111111111111111111", tokens_reels: 3 },
          });
          expect(
            runtimeAdmission.getOpsysRuntimeCompletionReceipt(message, hostExpected),
          ).toMatchObject({
            ...hostExpected,
            candidateIndex: 0,
            streamOrdinal: 0,
            tokensReels: 3,
          });
          const custodyAtDone = runtimeAdmission.consumeOpsysRuntimeCompletionCustody(custody);
          expect(custodyAtDone).toHaveLength(1);
          expect(custodyAtDone?.[0]?.message).toBe(message);
        }
      }
      expect(eventTypes).toEqual(["start", "done"]);
      const first = stream.result();
      const second = stream.result();
      expect(first).toBe(second);
      const results = await Promise.all([first, second]);
      expect(results[0]).toBe(message);
      expect(results[1]).toBe(message);
      expect(controller.signal.aborted).toBe(true);
      expect(providerDispatches).toBe(1);
      expect(providerResultCalls).toBe(1);
      expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
      expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0]).toMatchObject({
        server: "opsys_runtime_demo",
        tool: "opsys_runtime_admettre",
        args: {
          execution_id: "completion-native-event-abort",
          revision_profil: 1,
          cle_idempotence: "completion-native-event-abort:0:0",
          tours: 1,
          attempt_id: "completion-native-event-abort:0",
          cycle_id: "completion-native-event-abort:0:0",
          candidate_index: 0,
          stream_ordinal: 0,
          is_fallback_retry: false,
        },
      });
      const reconcileRequest = reconciliations()[0]?.[0];
      expect(reconcileRequest?.args).toEqual({
        reservation_id: "11111111111111111111111111111111",
        tokens_reels: 3,
      });
      expect(reconcileRequest?.signal).not.toBe(controller.signal);
      expect(reconcileRequest?.signal.aborted).toBe(false);
      expect(runtimeAdmission.consumeOpsysRuntimeCompletionCustody(custody)).toBeUndefined();
    } finally {
      runtimeAdmission.closeOpsysRuntimeCompletionCustody(custody);
    }
  });

  it("withholds native known-usage error when reconciliation fails and shares the marked failure", async () => {
    installRuntimeReplies([reservationA]);
    const rpc = mocks.callOpsysMcpTool.getMockImplementation()!;
    const transportFailure = new Error("fictional reconciliation transport rejected");
    mocks.callOpsysMcpTool.mockImplementation(async (request: RuntimeRequest) => {
      if (request.tool === "opsys_runtime_concilier") {
        throw transportFailure;
      }
      return rpc(request);
    });
    const runId = "completion-native-error-reconcile-failure";
    const hostExpected = expected(runId, 0);
    const custody = runtimeAdmission.createOpsysRuntimeCompletionCustody({
      ...hostExpected,
      candidateIndex: 0,
      streamOrdinals: [0],
    });
    const message: AssistantMessage = {
      ...messageFixture(),
      stopReason: "error",
      errorMessage: "fictional known-usage native error",
    };
    const native = createAssistantMessageEventStream();
    const nativeResult = native.result.bind(native);
    let providerResultCalls = 0;
    native.result = () => {
      providerResultCalls += 1;
      return nativeResult();
    };
    native.push({ type: "start", partial: message });
    native.push({ type: "error", reason: "error", error: message });
    native.end();
    let providerDispatches = 0;
    const provider: StreamFn = () => {
      providerDispatches += 1;
      return native;
    };
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config,
      agentId: "opsys-agent-demo",
      runId,
      getCandidateIndex: () => 0,
      completionCustody: custody,
      streamFn: provider,
    });
    try {
      const stream = await guarded(model, context);
      expect(stream).toBe(native);
      const eventTypes: string[] = [];
      const drain = (async () => {
        for await (const event of stream) {
          eventTypes.push(event.type);
        }
      })();
      const results = await Promise.allSettled([drain, stream.result()]);
      const drained = results[0];
      const terminalResult = results[1];
      expect(drained.status).toBe("rejected");
      expect(terminalResult.status).toBe("rejected");
      if (
        drained.status !== "rejected" ||
        terminalResult.status !== "rejected" ||
        !(drained.reason instanceof Error)
      ) {
        throw new Error("Expected both consumers to reject the terminal reconciliation failure");
      }
      const terminal = drained.reason;
      expect(terminalResult.reason).toBe(terminal);
      expect(terminal).not.toBe(transportFailure);
      expect(terminal.cause).toBe(transportFailure);
      expect(isRecordedModelFallbackStop(terminal)).toBe(true);
      expect(hasModelFallbackStop(terminal)).toBe(true);
      expect(resolveModelFallbackError(terminal).kind).toBe("terminal");
      expect(isRecordedModelFallbackStop(transportFailure)).toBe(false);
      expect(hasModelFallbackStop(transportFailure)).toBe(false);
      expect(eventTypes).toEqual(["start"]);
      expect(
        runtimeAdmission.getOpsysRuntimeCompletionReceipt(message, hostExpected),
      ).toBeUndefined();
      expect(runtimeAdmission.consumeOpsysRuntimeCompletionCustody(custody)).toBeUndefined();
      expect(providerDispatches).toBe(1);
      expect(providerResultCalls).toBe(1);
      expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
      expect(reconciliations()).toHaveLength(1);
      expect(reconciliations()[0]?.[0]).toMatchObject({
        server: "opsys_runtime_demo",
        tool: "opsys_runtime_concilier",
        args: { reservation_id: "11111111111111111111111111111111", tokens_reels: 3 },
      });
      expect(reconciliations()[0]?.[0].args).toEqual({
        reservation_id: "11111111111111111111111111111111",
        tokens_reels: 3,
      });
    } finally {
      runtimeAdmission.closeOpsysRuntimeCompletionCustody(custody);
    }
  });
});
