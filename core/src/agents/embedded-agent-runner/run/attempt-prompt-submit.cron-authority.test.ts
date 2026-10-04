import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createAssistant,
  createAssistantResultStream,
  createTestSession,
  registerAgentSessionLoopTestLifecycle,
  testModel,
} from "../../sessions/agent-session-loop-correctness.test-support.js";
import {
  clearEmbeddedSessionPromptStates,
  getEmbeddedSessionPromptState,
} from "../session-prompt-state.js";
import { submitEmbeddedAttemptPrompt } from "./attempt-prompt-submit.js";

registerAgentSessionLoopTestLifecycle();
const sessionId = "cron-authority-dispatch";
afterEach(() => clearEmbeddedSessionPromptStates([sessionId]));

async function fixture(attempt: Parameters<typeof submitEmbeddedAttemptPrompt>[0]["attempt"]) {
  const { session: activeSession } = await createTestSession();
  const state = getEmbeddedSessionPromptState(sessionId);
  const provider = vi.fn<StreamFn>((model) =>
    createAssistantResultStream(createAssistant(model, [{ type: "text", text: "done" }])),
  );
  activeSession.agent.streamFn = provider;
  const persist = vi.fn(async () => {});
  const submit = (dispatch: () => Promise<void>) =>
    submitEmbeddedAttemptPrompt({
      attempt: { ...attempt, runId: "cron-authority-run", sessionId },
      activeSession,
      contextTokenBudget: 8_000,
      images: [],
      modelPrompt: "internal mandate",
      transcriptPrompt: "internal mandate",
      onFinalPromptText: () => {},
      onSteeringAcknowledged: () => {},
      runtimeOnly: false,
      sessionPromptState: state,
      systemPrompt: "test prompt",
      toolResultAggregateMaxChars: 8_000,
      toolResultMaxChars: 4_000,
      toolResultPromptProjectionState: state.toolResults,
      trajectoryRecorder: null,
      transcriptLeafId: null,
      persistToolResultProjections: persist,
      promptActiveSession: dispatch,
    });
  return { activeSession, provider, persist, submit };
}

describe("scheduled authority at the actual embedded provider boundary", () => {
  it("refuses a profiled cron turn without its host callback before any provider dispatch", async () => {
    const f = await fixture({
      runId: "cron-authority-run",
      sessionId,
      trigger: "cron",
      agentId: "opsys-agent-demo",
      getAdmissionCandidateIndex: () => 0,
      config: {
        agents: {
          entries: {
            "opsys-agent-demo": {
              opsysRuntimeAdmission: { profileId: "demo", profileRevision: 1 },
            },
          },
        },
      },
    });
    await expect(
      f.submit(async () => {
        await f.activeSession.agent.streamFn(testModel, { messages: [] });
      }),
    ).rejects.toThrow("requires live host authority validation");
    expect(f.persist).toHaveBeenCalledTimes(1);
    expect(f.provider).not.toHaveBeenCalled();
    expect(f.activeSession.agent.streamFn).toBe(f.provider);
  });

  it("rechecks on a continuation and restores the real session stream after revocation", async () => {
    const events: string[] = [];
    const validate = vi.fn(async (signal: AbortSignal) => {
      signal.throwIfAborted();
      events.push("authority");
      if (events.length === 2) throw new Error("revoked before continuation");
    });
    const f = await fixture({
      runId: "cron-authority-run",
      sessionId,
      trigger: "cron",
      validateScheduledRuntimeAuthority: validate,
    });
    await expect(
      f.submit(async () => {
        await f.activeSession.agent.streamFn(testModel, { messages: [] });
        expect(f.provider).toHaveBeenCalledTimes(1);
        await f.activeSession.agent.streamFn(testModel, { messages: [] });
      }),
    ).rejects.toThrow("revoked before continuation");
    expect(validate).toHaveBeenCalledTimes(2);
    expect(f.persist).toHaveBeenCalledTimes(2);
    expect(f.provider).toHaveBeenCalledTimes(1);
    expect(f.activeSession.agent.streamFn).toBe(f.provider);
  });
});
