import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { AssistantMessage, Context } from "openclaw/plugin-sdk/llm";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../../../context-engine/opsys-contexte-mcp.js";
import { makeProviderModelFixture } from "../../test-helpers/provider-model-fixture.js";
import { createZeroUsageFixture } from "../../test-helpers/usage-fixtures.js";
import * as owner from "../opsys-runtime-admission.js";

// Private, fictional provider/MCP fixtures; they establish no current authority.
const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn<typeof callOpsysMcpTool>() }));
vi.mock("../../../context-engine/opsys-contexte-mcp.js", () => mocks);
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
import { agentSessionQueuePromptContext } from "../../sessions/agent-session-prompting.js";
import { submitEmbeddedAttemptPrompt } from "./attempt-prompt-submit.js";

// Explicitly isolate persistence, transcript, steering, compaction and prompt transforms.
// Owner admission/result/reconciliation and submitEmbeddedAttemptPrompt remain real.
vi.mock("../../sessions/agent-session-prompting.js", () => ({
  agentSessionQueuePromptContext: Symbol.for("custody.fixture.queue"),
}));
vi.mock("../../sessions/compaction/request-budget.js", () => ({
  attachPromptCompactionRequestBudget: () => undefined,
}));
vi.mock("../../sessions/session-manager-write-admission.js", () => ({
  withSessionManagerWrite: async (_manager: unknown, operation: () => unknown) => operation(),
}));
vi.mock("../../subagents/registry/subagent-registry.js", () => ({
  ackPendingAgentSteeringItems: () => undefined,
}));
vi.mock("../prompt-cache-observability.js", () => ({ recordAggregateTruncation: () => undefined }));
vi.mock("../runs.js", () => ({ updateActiveEmbeddedRunSnapshot: () => undefined }));
vi.mock("../session-prompt-state.js", () => ({
  hasSessionUserTurnBeenSent: () => true,
  markSessionUserTurnsSent: () => undefined,
}));
vi.mock("../tool-result-truncation.js", () => ({
  truncateOversizedToolResultsInMessages: (messages: unknown[]) => ({
    messages,
    aggregateTruncatedCount: 0,
  }),
}));
vi.mock("./attempt-context-summary.js", () => ({
  snapshotRecentMessages: (messages: unknown[]) => messages,
}));
vi.mock("./attempt-llm-boundary.js", () => ({
  installModelPromptTransform: () => () => undefined,
  installRuntimeContextMessageForPrompt: () => () => undefined,
}));
vi.mock("./attempt-sessions-yield.js", () => ({
  isSessionsYieldAbortError: () => false,
  persistSessionsYieldContextMessage: async () => undefined,
  stripSessionsYieldArtifacts: () => false,
  waitForSessionsYieldAbortSettle: async () => undefined,
}));
vi.mock("./midturn-precheck.js", () => ({ isMidTurnPrecheckSignal: () => false }));
vi.mock("./message-transform-stream-wrapper.js", () => ({
  wrapStreamFnWithMessageTransform: (stream: StreamFn) => stream,
}));

type SubmitInput = Parameters<typeof submitEmbeddedAttemptPrompt>[0];
function submission(handle: unknown) {
  const value = message();
  const result = vi.fn(async () => value);
  const provider = vi.fn<StreamFn>(async () => ({ result, async *[Symbol.asyncIterator]() {} }));
  const activeSession: SubmitInput["activeSession"] = {
    messages: [],
    [agentSessionQueuePromptContext]: () => () => undefined,
    agent: { state: { messages: [] }, streamFn: provider },
  };
  const attempt: SubmitInput["attempt"] = {
    runId: "custody-fictional",
    sessionId: "custody-private-session",
    agentId: "opsys-agent-demo",
    config,
    getAdmissionCandidateIndex: () => 2,
  };
  // Explicit fixture boundary, without widening the future opaque production parameter type.
  if (handle !== undefined) {
    Reflect.set(attempt, "opsysCompletionCustody", handle);
  }
  const projection: SubmitInput["toolResultPromptProjectionState"] = {
    replacements: new Map(),
    frozen: new Set(),
    ambiguousBaseKeys: new Set(),
    sourceHashByKey: new Map(),
    restoredCacheTtl: new Map(),
  };
  const input: SubmitInput = {
    attempt,
    activeSession,
    contextTokenBudget: 64,
    images: [],
    modelPrompt: "Fictional prompt",
    onFinalPromptText: () => undefined,
    onSteeringAcknowledged: () => undefined,
    persistToolResultProjections: async () => undefined,
    promptActiveSession: async () => {
      await (await activeSession.agent.streamFn(model, context)).result();
    },
    runtimeOnly: false,
    sessionPromptState: {
      activeProjectKeys: [],
      sentUserTurnIds: new Set(),
      toolResults: projection,
    },
    systemPrompt: "Fictional system",
    toolResultAggregateMaxChars: 2048,
    toolResultMaxChars: 1024,
    toolResultPromptProjectionState: projection,
    trajectoryRecorder: null,
    transcriptLeafId: null,
    transcriptPrompt: "Fictional prompt",
  };
  return { input, activeSession, provider, result, value };
}

describe("OPSYS private completion custody prompt submission plumbing", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockClear();
    installReplies();
  });
  it("refuses a legacy department without a durable profile before provider dispatch", async () => {
    const fixture = submission(undefined);
    fixture.input.attempt.agentId = "m02-revenue-crm";
    fixture.input.attempt.getAdmissionCandidateIndex = () => 0;
    fixture.input.attempt.config = {
      agents: { entries: { "m02-revenue-crm": { opsysIsolation: { exec: "sandbox-required" } } } },
    };
    await expect(submitEmbeddedAttemptPrompt(fixture.input)).rejects.toThrow(
      "OPSYS runtime admission is required but missing for agent m02-revenue-crm",
    );
    expect(fixture.provider).not.toHaveBeenCalled();
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
    expect(fixture.activeSession.agent.streamFn).toBe(fixture.provider);
  });
  it("forwards the private handle through one installed factory across two provider streams and restores the base", async () => {
    const api = custodyAPI();
    const handle = api.create(binding([0, 1]));
    const fixture = submission(handle);
    const a = message("A"),
      b = message("B");
    fixture.result.mockResolvedValueOnce(a).mockResolvedValueOnce(b);
    fixture.input.promptActiveSession = async () => {
      expect(fixture.activeSession.agent.streamFn).not.toBe(fixture.provider);
      await (await fixture.activeSession.agent.streamFn(model, context)).result();
      await (await fixture.activeSession.agent.streamFn(model, context)).result();
    };
    await submitEmbeddedAttemptPrompt(fixture.input);
    expect(fixture.activeSession.agent.streamFn).toBe(fixture.provider);
    const batch = api.consume(handle);
    expect(batch?.map((entry) => entry.message)).toEqual([a, b]);
    expect(batch?.[0]?.message).toBe(a);
    expect(batch?.[1]?.message).toBe(b);
    expect(batch?.map((entry) => entry.receipt.streamOrdinal)).toEqual([0, 1]);
    expect(fixture.provider).toHaveBeenCalledTimes(2);
    expect(reconciliations()).toHaveLength(2);
  });

  it("restores the base stream on prompt rejection without losing already captured historical completion", async () => {
    const api = custodyAPI();
    const handle = api.create(binding());
    const fixture = submission(handle);
    const failure = new Error("FICTIONAL_PROMPT_FAILURE");
    fixture.input.promptActiveSession = async () => {
      await (await fixture.activeSession.agent.streamFn(model, context)).result();
      throw failure;
    };
    await expect(submitEmbeddedAttemptPrompt(fixture.input)).rejects.toBe(failure);
    expect(fixture.activeSession.agent.streamFn).toBe(fixture.provider);
    expect(api.consume(handle)?.[0]?.message).toBe(fixture.value);
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
  });

  it("keeps ordinary prompt submission without a private custody handle and restores the original stream", async () => {
    const api = custodyAPI();
    const fixture = submission(undefined);
    await submitEmbeddedAttemptPrompt(fixture.input);
    expect(fixture.activeSession.agent.streamFn).toBe(fixture.provider);
    expect(fixture.provider).toHaveBeenCalledOnce();
    expect(fixture.result).toHaveBeenCalledOnce();
    expect(reconciliations()).toHaveLength(1);
    expect(api.consume(undefined)).toBeUndefined();
  });
});
