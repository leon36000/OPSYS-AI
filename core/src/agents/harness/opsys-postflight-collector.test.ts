import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  openDatabase: vi.fn(),
  reserve: vi.fn(),
  complete: vi.fn(),
  observePending: vi.fn(),
  deliver: vi.fn(),
}));

vi.mock("../../state/openclaw-agent-db.js", () => ({
  openOpenClawAgentDatabase: mocks.openDatabase,
}));
vi.mock("./opsys-postflight-outbox.js", () => ({
  reserveOpsysPostflightIntent: mocks.reserve,
  completeOpsysPostflightIntent: mocks.complete,
  observeOpsysM9ApprovalPending: mocks.observePending,
}));

vi.mock("./opsys-postflight-delivery.js", () => ({ deliverOpsysPostflightLots: mocks.deliver }));

import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import { OpsysPostflightCollector } from "./opsys-postflight-collector.js";

const admission = {
  runId: "run-1",
  agentId: "m03-estimation",
  profileId: "profile-m03",
  profileRevision: 7,
  departement: "m03-estimation",
  attemptId: "attempt-1",
  cycleId: "cycle-1",
};
const target = {
  agentId: "m03-estimation",
  sessionKey: "agent:m03-estimation:main",
  affaireId: "LEAD-1",
  serverName: "opsys_m3",
  toolName: "m3_creer_devis",
};
const success: CallToolResult = {
  content: [{ type: "text", text: JSON.stringify({ ok: true, resultat: { devis_id: "D-1" } }) }],
};
const refusal: CallToolResult = {
  content: [{ type: "text", text: JSON.stringify({ ok: false, erreur: "refus_metier" }) }],
};

function setup(
  params: {
    receipt?: { agentId: string; sessionId: string; sessionKey: string; storePath: string } | null;
    admissionValue?: typeof admission;
    assertCurrent?: () => void;
    depositTools?: readonly string[];
  } = {},
) {
  const database = { agentId: "m03-estimation", path: "/private/agent.sqlite", db: {} };
  mocks.openDatabase.mockReturnValue(database);
  mocks.complete.mockResolvedValue([]);
  mocks.reserve.mockImplementation(async (p) => ({
    ...p.intent,
    state: "uncertain",
    createdAt: p.now,
  }));
  const recorder = {
    waitForRuntimePersistence: vi.fn().mockResolvedValue(undefined),
    getAdmissionReceipt: vi.fn().mockReturnValue(
      Object.hasOwn(params, "receipt") && !params.receipt
        ? undefined
        : {
            agentId: "m03-estimation",
            sessionId: "session-1",
            sessionKey: "agent:m03-estimation:main",
            storePath: "/private/agent.sqlite",
            generation: "synthetic-generation",
            entryId: "synthetic-entry",
            rawSeq: 1,
            effectiveParentId: null,
            activeMessagePosition: 0,
            logicalTurnId: "synthetic-logical-turn",
            role: "user",
            ...params.receipt,
          },
    ),
  };
  const collector = new OpsysPostflightCollector({
    runId: "run-1",
    sessionId: "session-1",
    sessionKey: "agent:m03-estimation:main",
    agentId: "m03-estimation",
    recorder,
    depositTools: params.depositTools ?? ["m3_creer_devis", "m3_estimer_projet"],
    assertCurrent: params.assertCurrent ?? (() => undefined),
  });
  collector.recordRuntimeAdmission(params.admissionValue ?? admission);
  return { collector, recorder, database };
}

beforeEach(() => {
  mocks.openDatabase.mockReset();
  mocks.complete.mockReset();
  mocks.observePending.mockReset();
  mocks.observePending.mockResolvedValue(undefined);
  mocks.reserve.mockReset();
  mocks.deliver.mockReset();
  mocks.deliver.mockResolvedValue({
    selected: 1,
    attempted: 1,
    delivered: 1,
    failed: 0,
    acknowledgementFailures: 0,
  });
});

describe("OPSYS postflight collector", () => {
  it("opens only the database named by the matching persisted transcript receipt", async () => {
    const { collector, recorder } = setup();
    await collector.prepareBeforeProviderDispatch();
    expect(recorder.waitForRuntimePersistence).toHaveBeenCalledOnce();
    expect(mocks.openDatabase).toHaveBeenCalledExactlyOnceWith({
      agentId: "m03-estimation",
      path: "/private/agent.sqlite",
    });
  });

  it("waits for transcript persistence before opening its database", async () => {
    const { collector, recorder } = setup();
    let resolvePersistence!: () => void;
    recorder.waitForRuntimePersistence.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolvePersistence = resolve;
        }),
    );
    const pending = collector.prepareBeforeProviderDispatch();
    await Promise.resolve();
    expect(mocks.openDatabase).not.toHaveBeenCalled();
    resolvePersistence();
    await pending;
    expect(mocks.openDatabase).toHaveBeenCalledOnce();
  });

  it.each([
    ["absent receipt", { receipt: null }],
    [
      "cross-session receipt",
      {
        receipt: {
          agentId: "m03-estimation",
          sessionId: "other",
          sessionKey: "agent:m03-estimation:main",
          storePath: "/private/agent.sqlite",
        },
      },
    ],
    [
      "cross-agent receipt",
      {
        receipt: {
          agentId: "m02-revenue-crm",
          sessionId: "session-1",
          sessionKey: "agent:m03-estimation:main",
          storePath: "/private/other.sqlite",
        },
      },
    ],
  ])("refuses %s before dispatch", async (_label, options) => {
    const { collector } = setup({ receipt: options.receipt });
    await expect(collector.prepareBeforeProviderDispatch()).rejects.toThrow(
      /matching persisted transcript admission/,
    );
    expect(mocks.openDatabase).not.toHaveBeenCalled();
  });

  it("honors abort while waiting for the transcript receipt", async () => {
    const controller = new AbortController();
    const { collector, recorder } = setup();
    recorder.waitForRuntimePersistence.mockImplementation(async () => {
      controller.abort();
    });
    await expect(collector.prepareBeforeProviderDispatch(controller.signal)).rejects.toThrow();
    expect(mocks.openDatabase).not.toHaveBeenCalled();
  });

  it("stores a known business refusal from the authenticated ticket target", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const call = collector.beginToolCall({
      toolCallId: "call-1",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    expect(call).toBeDefined();
    await call?.assertBeforeEffect(target);
    await call?.observe(target, refusal, { authorityCurrent: true });
    expect(mocks.complete).toHaveBeenCalledOnce();
    expect(mocks.complete.mock.calls[0]?.[0].fact).toMatchObject({
      outil: "m3_creer_devis",
      resultat: "refus",
      code: "refus_metier",
    });
  });

  it("excludes non-ticket, transport-error, approval-pending, and unreadable results", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    expect(
      collector.beginToolCall({
        toolCallId: "list",
        toolName: "m3_estimer_projet",
        serverName: "opsys_m3",
      }),
    ).toBeUndefined();
    const call = collector.beginToolCall({
      toolCallId: "call-2",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await call?.assertBeforeEffect(target);
    await call?.observe(target, { ...success, isError: true }, { authorityCurrent: true });
    await call?.observe(
      target,
      {
        content: [
          {
            type: "text",
            text: JSON.stringify({ ok: true, statut: "en_attente_approbation" }),
          },
        ],
      },
      { authorityCurrent: true },
    );
    await call?.observe(
      target,
      { content: [{ type: "text", text: "not-json" }] },
      { authorityCurrent: true },
    );
    expect(mocks.complete).not.toHaveBeenCalled();
  });

  it("reserves unique call ids and capacity before any effect", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const first = collector.beginToolCall({
      toolCallId: "dup",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    const racingDuplicate = collector.beginToolCall({
      toolCallId: "dup",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await first?.assertBeforeEffect(target);
    await expect(racingDuplicate?.assertBeforeEffect(target)).rejects.toThrow(/duplicate/i);
    for (let index = 1; index < 20; index += 1) {
      await collector
        .beginToolCall({
          toolCallId: `call-${index}`,
          toolName: target.toolName,
          serverName: target.serverName,
        })
        ?.assertBeforeEffect(target);
    }
    const overflow = collector.beginToolCall({
      toolCallId: "call-20",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await expect(overflow?.assertBeforeEffect(target)).rejects.toThrow(/capacity/i);
    expect(mocks.complete).not.toHaveBeenCalled();
  });

  it("blocks new effects until a pending known result is durable", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const first = collector.beginToolCall({
      toolCallId: "call-pending",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await first?.assertBeforeEffect(target);
    mocks.complete.mockRejectedValue(new Error("sqlite persistently busy"));
    await first?.observe(target, success, { authorityCurrent: true });
    expect(mocks.complete).toHaveBeenCalledTimes(2);

    const blocked = collector.beginToolCall({
      toolCallId: "call-blocked",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await expect(blocked?.assertBeforeEffect(target)).rejects.toThrow(
      /durable capture is unresolved/i,
    );
    expect(mocks.complete).toHaveBeenCalledTimes(2);

    mocks.complete.mockResolvedValue([]);
    expect(await collector.flushPending()).toMatchObject({ remaining: 0, failures: 0 });
    await blocked?.assertBeforeEffect(target);
  });

  it("captures already-reserved calls after an earlier result becomes pending", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const first = collector.beginToolCall({
      toolCallId: "call-first",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    const alreadyInFlight = collector.beginToolCall({
      toolCallId: "call-in-flight",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await first?.assertBeforeEffect(target);
    await alreadyInFlight?.assertBeforeEffect(target);
    mocks.complete.mockRejectedValueOnce(new Error("sqlite unavailable"));
    mocks.complete.mockRejectedValueOnce(new Error("sqlite unavailable"));
    mocks.complete.mockResolvedValue([]);
    await first?.observe(target, success, { authorityCurrent: false });
    await alreadyInFlight?.observe(target, refusal, { authorityCurrent: true });
    expect(mocks.complete).toHaveBeenCalledTimes(3);
    expect(mocks.complete.mock.calls[2]?.[0].fact).toMatchObject({ resultat: "refus" });
    expect(await collector.flushPending()).toMatchObject({ remaining: 0, revokedAfterEffect: 1 });
    expect(mocks.complete).toHaveBeenCalledTimes(4);
    expect(mocks.complete.mock.calls[3]?.[0].fact).toMatchObject({ resultat: "ok" });
  });

  it("invalidates an earlier admission instead of retaining it after a malformed update", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    expect(() => collector.recordRuntimeAdmission({ ...admission, profileId: "" })).toThrow(
      /invalid or stale/,
    );
    expect(() =>
      collector.beginToolCall({
        toolCallId: "call-stale",
        toolName: target.toolName,
        serverName: target.serverName,
      }),
    ).toThrow(/authority is incomplete/);
  });

  it("keeps a known result through bounded retries and reports post-effect revocation", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const call = collector.beginToolCall({
      toolCallId: "call-retry",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await call?.assertBeforeEffect(target);
    mocks.complete.mockRejectedValueOnce(new Error("sqlite busy")).mockResolvedValue([]);
    await call?.observe(target, success, { authorityCurrent: false });
    expect(mocks.complete).toHaveBeenCalledTimes(2);
    expect(await collector.flushPending()).toMatchObject({ remaining: 0, revokedAfterEffect: 1 });
    expect(mocks.complete).toHaveBeenCalledTimes(2);
  });
});

describe("OPSYS postflight lifecycle handoff", () => {
  it("exposes only the actual reserved call keys from this admitted session", async () => {
    const { collector } = setup();
    expect(collector.getDeferredDepositReceipt()).toBeUndefined();
    await collector.prepareBeforeProviderDispatch();
    const before = collector.getDeferredDepositReceipt();
    expect(before).toMatchObject({
      sessionId: "session-1",
      sessionKey: target.sessionKey,
      agentId: "m03-estimation",
      factKeys: [],
    });
    const observer = collector.beginToolCall({
      toolCallId: "owned-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    expect(observer).toBeDefined();
    await observer?.assertBeforeEffect(target);
    expect(collector.getDeferredDepositReceipt()).toMatchObject({
      factKeys: [depositKey("session-1", "owned-call")],
    });
    expect(before?.factKeys).toEqual([]);
    expect(Object.isFrozen(collector.getDeferredDepositReceipt()?.factKeys)).toBe(true);
  });

  it("delivers through the admitted collector DB and exact profile, after local flush", async () => {
    const { collector, database } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "delivery-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await observer?.assertBeforeEffect(target);
    await observer?.observe(target, success, { authorityCurrent: true });
    const signal = new AbortController().signal;
    expect(
      await collector.deliverPending({ config: undefined, timeoutMs: 4_000, signal }),
    ).toMatchObject({ delivered: 1 });
    expect(mocks.deliver).toHaveBeenCalledOnce();
    expect(mocks.deliver).toHaveBeenCalledWith(
      expect.objectContaining({
        database,
        options: { agentId: "m03-estimation", path: "/private/agent.sqlite" },
        profile: { id: "profile-m03", revision: 7, departement: "m03-estimation" },
        timeoutMs: 4_000,
        signal,
      }),
    );
  });

  it("does not deliver when persistence is missing or authority has been revoked", async () => {
    let current = true;
    const { collector } = setup({
      assertCurrent: () => {
        if (!current) {
          throw new Error("revoked");
        }
      },
    });
    const input = { config: undefined, timeoutMs: 4_000, signal: new AbortController().signal };
    await expect(collector.deliverPending(input)).rejects.toThrow("incomplete");
    expect(mocks.deliver).not.toHaveBeenCalled();
    await collector.prepareBeforeProviderDispatch();
    current = false;
    await expect(collector.deliverPending(input)).rejects.toThrow("revoked");
    expect(mocks.deliver).not.toHaveBeenCalled();
  });
});

describe("OPSYS durable reservation before source effect", () => {
  it("records only a received native M9 pending request and keeps the live uncertainty fence", async () => {
    const tool = "m9_ouvrir_suivi_decision";
    const m9Target = { ...target, toolName: tool, serverName: "opsys_m9" };
    const { collector } = setup({ depositTools: [tool] });
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "m9-pending",
      toolName: tool,
      serverName: "opsys_m9",
    });
    await observer?.assertBeforeEffect(m9Target);
    await observer?.observe(
      m9Target,
      {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              ok: true,
              statut: "en_attente_approbation",
              demande_id: "abcdef123456",
            }),
          },
        ],
      },
      { authorityCurrent: true },
    );
    expect(mocks.observePending).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        expected: expect.objectContaining({
          factKey: depositKey("session-1", "m9-pending"),
          outil: tool,
        }),
        requestId: "abcdef123456",
      }),
    );
    expect(mocks.complete).not.toHaveBeenCalled();
    await expect(
      collector
        .beginToolCall({
          toolCallId: "m9-next",
          toolName: tool,
          serverName: "opsys_m9",
        })
        ?.assertBeforeEffect(m9Target),
    ).rejects.toThrow("durable capture is unresolved");
  });

  it.each([
    {
      title: "an error result",
      isError: true,
      body: { ok: true, statut: "en_attente_approbation", demande_id: "abcdef123456" },
    },
    {
      title: "a missing native request id",
      isError: false,
      body: { ok: true, statut: "en_attente_approbation" },
    },
    {
      title: "an invalid native request id",
      isError: false,
      body: { ok: true, statut: "en_attente_approbation", demande_id: "model-chosen" },
    },
  ])("does not release M9 uncertainty for $title", async ({ isError, body }) => {
    const tool = "m9_ouvrir_suivi_decision";
    const m9Target = { ...target, toolName: tool, serverName: "opsys_m9" };
    const { collector } = setup({ depositTools: [tool] });
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "m9-invalid",
      toolName: tool,
      serverName: "opsys_m9",
    });
    await observer?.assertBeforeEffect(m9Target);
    await observer?.observe(
      m9Target,
      { isError, content: [{ type: "text", text: JSON.stringify(body) }] },
      { authorityCurrent: true },
    );
    expect(mocks.observePending).not.toHaveBeenCalled();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(await collector.flushPending()).toMatchObject({ remaining: 0, failures: 1 });
  });

  it("retains M9 uncertainty if persisting the received approval request fails", async () => {
    const tool = "m9_ouvrir_suivi_decision";
    const m9Target = { ...target, toolName: tool, serverName: "opsys_m9" };
    const { collector } = setup({ depositTools: [tool] });
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "m9-write-fails",
      toolName: tool,
      serverName: "opsys_m9",
    });
    await observer?.assertBeforeEffect(m9Target);
    mocks.observePending.mockRejectedValueOnce(new Error("fictive commit refused"));
    await observer?.observe(
      m9Target,
      {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              ok: true,
              statut: "en_attente_approbation",
              demande_id: "abcdef123456",
            }),
          },
        ],
      },
      { authorityCurrent: true },
    );
    expect(mocks.observePending).toHaveBeenCalledOnce();
    expect(mocks.complete).not.toHaveBeenCalled();
    await expect(
      collector
        .beginToolCall({
          toolCallId: "m9-after-write-failure",
          toolName: tool,
          serverName: "opsys_m9",
        })
        ?.assertBeforeEffect(m9Target),
    ).rejects.toThrow("durable capture is unresolved");
  });

  it("binds the exact ticket target and opaque run lineage before any source call", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "durable-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await observer?.assertBeforeEffect(target);
    expect(mocks.reserve).toHaveBeenCalledOnce();
    const captured = mocks.reserve.mock.calls[0]?.[0].intent;
    expect(captured).toMatchObject({
      factKey: depositKey("session-1", "durable-call"),
      affaireId: "LEAD-1",
      outil: "m3_creer_devis",
      serverName: "opsys_m3",
      profilId: "profile-m03",
      revision: 7,
      engineId: "opsys",
    });
    expect(captured.ownerKey).toMatch(/^[0-9a-f]{64}$/u);
    expect(JSON.stringify(captured)).not.toContain("agent:m03-estimation:main");
    expect(JSON.stringify(captured)).not.toContain("run-1");
  });

  it("refuses a source dispatch when durable reservation fails", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "quota-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    mocks.reserve.mockRejectedValue(new Error("POSTFLIGHT_QUOTA_LOTS"));
    await expect(observer?.assertBeforeEffect(target)).rejects.toThrow("POSTFLIGHT_QUOTA_LOTS");
    expect(mocks.complete).not.toHaveBeenCalled();
  });

  it("revalidates admission after the reservation await without deleting uncertainty", async () => {
    let current = true;
    const { collector } = setup({
      assertCurrent: () => {
        if (!current) {
          throw new Error("revoked during reserve");
        }
      },
    });
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "await-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    mocks.reserve.mockImplementation(async (p) => {
      current = false;
      return { ...p.intent, state: "uncertain", createdAt: p.now };
    });
    await expect(observer?.assertBeforeEffect(target)).rejects.toThrow("revoked during reserve");
    expect(mocks.complete).not.toHaveBeenCalled();
  });

  it("retains an uncertain dispatch in the end-of-attempt report when no response arrives", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "lost-source-response",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await observer?.assertBeforeEffect(target);
    expect(await collector.flushPending()).toMatchObject({ failures: 1 });
    await expect(
      collector.deliverPending({
        config: undefined,
        timeoutMs: 4000,
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow(/unresolved/i);
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(mocks.deliver).not.toHaveBeenCalled();
  });

  it("blocks further source effects after a transport outcome becomes unknown", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "unknown-source",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await observer?.assertBeforeEffect(target);
    observer?.recordUnknownOutcome();
    observer?.recordUnknownOutcome();
    const next = collector.beginToolCall({
      toolCallId: "after-unknown",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await expect(next?.assertBeforeEffect(target)).rejects.toThrow(
      /durable capture is unresolved/i,
    );
    expect(mocks.reserve).toHaveBeenCalledOnce();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(await collector.flushPending()).toMatchObject({ failures: 1 });
  });

  it("rejects a cross-session ticket before durable reservation", async () => {
    const { collector } = setup();
    await collector.prepareBeforeProviderDispatch();
    const observer = collector.beginToolCall({
      toolCallId: "cross-call",
      toolName: target.toolName,
      serverName: target.serverName,
    });
    await expect(
      observer?.assertBeforeEffect({ ...target, sessionKey: "different" }),
    ).rejects.toThrow(/target/i);
    expect(mocks.reserve).not.toHaveBeenCalled();
  });
});
