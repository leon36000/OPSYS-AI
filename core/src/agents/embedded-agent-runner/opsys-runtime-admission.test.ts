import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { AssistantMessage, Context } from "openclaw/plugin-sdk/llm";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../test-helpers/usage-fixtures.js";

const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);

import {
  createOpsysRuntimeAdmissionStreamFn,
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

function released(id: string, run: string, candidate = 0, ordinal = 0) {
  return envelope({
    id,
    statut: "liberee",
    agent_id: "demo",
    execution_id: run,
    attempt_id: `${run}:${candidate}`,
    cycle_id: `${run}:${candidate}:${ordinal}`,
    candidate_index: candidate,
    stream_ordinal: ordinal,
  });
}

describe("OPSYS runtime provider admission", () => {
  beforeEach(() => mocks.callOpsysMcpTool.mockReset());

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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-0001" }, true))
      .mockResolvedValueOnce(
        envelope({ id: "reservation-0001", statut: "conciliee", tokens_reels: 9 }),
      );
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
      args: { reservation_id: "reservation-0001", tokens_reels: 9 },
    });
  });

  it("keeps an existing cycle from authorizing a second provider dispatch", async () => {
    mocks.callOpsysMcpTool.mockResolvedValueOnce(envelope({ id: "reservation-0001" }, false));
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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-0001" }, true))
      .mockResolvedValueOnce(
        envelope({ id: "reservation-0001", statut: "conciliee", tokens_reels: 2 }),
      )
      .mockResolvedValueOnce(envelope({ id: "reservation-0002" }, true))
      .mockResolvedValueOnce(
        envelope({ id: "reservation-0002", statut: "conciliee", tokens_reels: 2 }),
      );
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
    mocks.callOpsysMcpTool.mockResolvedValueOnce(envelope({ id: "reservation-unknown-1" }, true));
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
  beforeEach(() => mocks.callOpsysMcpTool.mockReset());

  it("revalidates host authority after budget admission and before provider dispatch", async () => {
    const order: string[] = [];
    mocks.callOpsysMcpTool.mockImplementation(async () => {
      order.push("budget");
      return envelope({ id: "reservation-final-0001" }, true);
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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-final-0002" }, true))
      .mockResolvedValueOnce(released("reservation-final-0002", "run-final-0002"));
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
        reservation_id: "reservation-final-0002",
        execution_id: "run-final-0002",
        attempt_id: "run-final-0002:0",
        cycle_id: "run-final-0002:0:0",
        candidate_index: 0,
        stream_ordinal: 0,
        revision_profil: 1,
      },
    });
  });

  it("checks authority again for every stream and fallback candidate", async () => {
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-final-0003" }, true))
      .mockResolvedValueOnce(envelope({ id: "reservation-fallback-0003" }, true))
      .mockResolvedValueOnce(released("reservation-fallback-0003", "run-final-0003", 1, 1));
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
      args: { reservation_id: "reservation-fallback-0003", candidate_index: 1, stream_ordinal: 1 },
    });
  });

  it("does not dispatch when the host aborts during final authority validation", async () => {
    const controller = new AbortController();
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-final-0004" }, true))
      .mockResolvedValueOnce(released("reservation-final-0004", "run-final-0004"));
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
  beforeEach(() => mocks.callOpsysMcpTool.mockReset());
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
      mocks.callOpsysMcpTool.mockResolvedValueOnce(
        envelope({ id: "reservation-unknown-provider" }, true),
      );
      const provider = vi.fn<StreamFn>(() => {
        if (mode === "sync") throw failure;
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
    mocks.callOpsysMcpTool.mockResolvedValueOnce(
      envelope({ id: "reservation-unknown-result" }, true),
    );
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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-release-lost" }, true))
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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-captured" }, true))
      .mockResolvedValueOnce(released("reservation-captured", "run-captured"));
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
        reservation_id: "reservation-captured",
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
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce(envelope({ id: "reservation-conciliation-captured" }, true))
      .mockResolvedValueOnce(
        envelope({ id: "reservation-conciliation-captured", statut: "conciliee", tokens_reels: 3 }),
      );
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
      args: { reservation_id: "reservation-conciliation-captured", tokens_reels: 3 },
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
