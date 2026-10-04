import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);

import { createOpsysRuntimeAdmissionStreamFn } from "./opsys-runtime-admission.js";
import { runEmbeddedAgentEntry, setupRunEntryTestState } from "./run-entry.test-harness.js";
import { createDirectHarness, makeResult } from "./run-entry.test-support.js";

const state = setupRunEntryTestState();
const cfg = {
  agents: {
    entries: {
      "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 } },
    },
  },
} as never;

describe("run-entry runtime admission integration", () => {
  beforeEach(() => mocks.callOpsysMcpTool.mockReset());

  it("uses backend-consistent retry metadata when primary fails before admission", async () => {
    mocks.callOpsysMcpTool
      .mockResolvedValueOnce({
        ok: true,
        accord_neuf: true,
        resultat: { id: "reservation-0001" },
      })
      .mockResolvedValueOnce({
        ok: true,
        resultat: { id: "reservation-0001", statut: "conciliee", tokens_reels: 3 },
      });
    const provider = vi.fn(async () => ({
      result: async () => ({ usage: { totalTokens: 3 } }),
    })) as unknown as StreamFn;

    await runEmbeddedAgentEntry({
      selection: { cfg, provider: "primary-provider", model: "primary-model" },
      identity: {
        runId: "run-admission-ordinal",
        agentId: "opsys-agent-demo",
        sessionId: "session-1",
      },
      harness: createDirectHarness(),
      behavior: { kind: "command-rpc", hasCommittedSideEffect: () => false },
      sessionOverride: { kind: "preserve" },
      runCandidate: async (providerId, modelId, options) => {
        if (providerId === "primary-provider") {
          // The primary fails while preparing auth, before its first StreamFn call.
          return makeResult({ provider: providerId, model: modelId, classification: "empty" });
        }
        const guarded = createOpsysRuntimeAdmissionStreamFn({
          config: cfg,
          agentId: "opsys-agent-demo",
          runId: "run-admission-ordinal",
          getCandidateIndex: options.getAdmissionCandidateIndex!,
          streamFn: provider,
        });
        const stream = await guarded(
          { contextWindow: 64, maxTokens: 16 } as never,
          { messages: [] } as never,
        );
        await stream.result();
        return makeResult({ provider: providerId, model: modelId });
      },
    });

    expect(provider).toHaveBeenCalledOnce();
    expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0].args).toMatchObject({
      execution_id: "run-admission-ordinal",
      attempt_id: "run-admission-ordinal:0",
      cycle_id: "run-admission-ordinal:0:0",
      candidate_index: 0,
      stream_ordinal: 0,
      is_fallback_retry: false,
    });
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0].args).toMatchObject({
      reservation_id: "reservation-0001",
      tokens_reels: 3,
    });
  });
});
