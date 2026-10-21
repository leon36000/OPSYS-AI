import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);

import { createOpsysRuntimeAdmissionStreamFn } from "./opsys-runtime-admission.js";
import { runEmbeddedAgentEntry, setupRunEntryTestState } from "./run-entry.test-harness.js";
import { createDirectHarness, makeResult } from "./run-entry.test-support.js";

setupRunEntryTestState();
const cfg = {
  agents: {
    entries: {
      "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 } },
    },
  },
} as never;

describe("run-entry runtime admission integration", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });

  it("uses backend-consistent retry metadata when primary fails before admission", async () => {
    const reservationId = "4e66faedf8a702dc9e534b3ffe91e2e8";
    let receipt: Record<string, unknown> | undefined;
    mocks.callOpsysMcpTool.mockImplementation(
      async ({ tool, args }: { tool: string; args: Record<string, unknown> }) => {
        if (tool === "opsys_runtime_admettre") {
          expect(receipt).toBeUndefined();
          receipt = {
            id: reservationId,
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
            revision_profil: args.revision_profil,
          };
          return { ok: true, accord_neuf: true, resultat: receipt };
        }
        if (tool !== "opsys_runtime_concilier" || !receipt) {
          throw new Error("unexpected runtime request in fictitious admission fixture");
        }
        expect(args.reservation_id).toBe(reservationId);
        return {
          ok: true,
          resultat: { ...receipt, statut: "conciliee", tokens_reels: args.tokens_reels },
        };
      },
    );
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
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledTimes(2);
    expect(mocks.callOpsysMcpTool.mock.calls[0]?.[0].args).toMatchObject({
      execution_id: "run-admission-ordinal",
      attempt_id: "run-admission-ordinal:0",
      cycle_id: "run-admission-ordinal:0:0",
      candidate_index: 0,
      stream_ordinal: 0,
      is_fallback_retry: false,
    });
    expect(mocks.callOpsysMcpTool.mock.calls[1]?.[0].args).toMatchObject({
      reservation_id: reservationId,
      tokens_reels: 3,
    });
  });
});
