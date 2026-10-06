// OPSYS context engine (OPSYS-AI PLAN T3.3-suite, ADR-0010): PREFLIGHT in `assemble()`, POSTFLIGHT in
// `afterTurn()`. The call to the business engine is a fake driven by the test, and so is the timer:
// no network, no real timer, no wait. Each failure mode must leave the turn running, marked, logged.
import type { AgentMessage } from "openclaw/plugin-sdk/agent-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import {
  clearMemoryPluginState,
  registerTestMemoryPromptBuilder,
} from "../plugins/memory-state.test-fixtures.js";
import { delegateCompactionToRuntime } from "./delegate.js";
import type { OpsysContexteConfigResult } from "./opsys-contexte-config.js";
import { depositKey } from "./opsys-contexte-depot.js";
import {
  createOpsysContextEngine,
  OPSYS_CONTEXT_ENGINE_ID,
  type OpsysContexteEngineDeps,
} from "./opsys-contexte-engine.js";
import { checkOpsysContexteToolCall, OpsysContexteGuardStore } from "./opsys-contexte-garde.js";
import { parsePaquet, renderPaquet } from "./opsys-contexte-paquet.js";
import {
  AFFAIRE_M10_OPPORTUNITE,
  CONFIG_M3,
  CONFIG_M3_ET_M1_SESSION,
  emptyPaquet,
  ENVELOPE_PAQUET,
  PAQUET_M10,
  PAQUET_M10_OPPORTUNITE,
  PAQUET_M10_SIGNAL_CLOS,
} from "./opsys-contexte.test-support.js";

type Call = Parameters<NonNullable<OpsysContexteEngineDeps["callTool"]>>[0];
type Handler = (call: Call) => Promise<unknown>;

const NOW = "2026-09-28T10:15:00.000+00:00";
const DEPOSIT_OK = {
  ok: true,
  resultat: { accepte: true, resultat: { ecrits: 1, deja_deposes: 0, lignes: ["l1"] } },
};
const MARKER = "contexte d'entreprise indisponible";

function createTimers() {
  const started: Array<{ ms: number; onExpire: () => void; cancelled: boolean }> = [];
  return {
    started,
    start(ms: number, onExpire: () => void): () => void {
      const timer = { ms, onExpire, cancelled: false };
      started.push(timer);
      return () => {
        timer.cancelled = true;
      };
    },
    /** Lets every timer that is still running expire, as if its delay had elapsed. */
    expireAll(): void {
      for (const timer of started) {
        if (!timer.cancelled) {
          timer.onExpire();
        }
      }
    },
  };
}

function harness(
  options: {
    config?: OpsysContexteConfigResult;
    handler?: Handler;
    readConfig?: () => OpsysContexteConfigResult;
  } = {},
) {
  const calls: Call[] = [];
  const logs = { debug: [] as string[], info: [] as string[], warn: [] as string[] };
  const timers = createTimers();
  // Each harness records for its own guard store: no state leaks from a test to the next.
  const guardStore = new OpsysContexteGuardStore();
  const handler: Handler =
    options.handler ??
    (async (call) => {
      if (call.tool === "m10_paquet_contexte_affaire") {
        return ENVELOPE_PAQUET;
      }
      const count = Array.isArray(call.args.faits) ? call.args.faits.length : 1;
      return {
        ok: true,
        resultat: {
          accepte: true,
          resultat: {
            ecrits: count,
            deja_deposes: 0,
            lignes: Array.from({ length: count }, (_, index) => `synthetic-row-${index}`),
          },
        },
      };
    });
  const engine = createOpsysContextEngine(undefined, {
    readConfig:
      options.readConfig ?? (() => options.config ?? { kind: "enabled", config: CONFIG_M3 }),
    callTool: async (call) => {
      calls.push(call);
      return await handler(call);
    },
    startTimer: (ms, onExpire) => timers.start(ms, onExpire),
    nowMs: () => Date.parse(NOW),
    log: {
      debug: (message) => logs.debug.push(message),
      info: (message) => logs.info.push(message),
      warn: (message) => logs.warn.push(message),
    },
    guardStore,
  });
  return { engine, calls, logs, timers, guardStore };
}

function userMessage(text: string): AgentMessage {
  return { role: "user", content: text, timestamp: 1 };
}

function toolResultMessage(toolName: string, toolCallId: string, answer: unknown): AgentMessage {
  return {
    role: "toolResult",
    toolCallId,
    toolName,
    content: [{ type: "text", text: JSON.stringify(answer) }],
    isError: false,
    timestamp: 2,
  };
}

function assembleParams(
  overrides: { prompt?: string; sessionKey?: string; tokenBudget?: number } = {},
) {
  const messages = [userMessage("bonjour")];
  return {
    sessionId: "session-1",
    sessionKey: "agent:m03-estimation:main",
    messages,
    prompt: "Estime ce projet.\naffaire_id: LEAD-001",
    tokenBudget: 100_000,
    ...overrides,
  };
}

function afterTurnParams(
  messages: AgentMessage[],
  overrides: { prePromptMessageCount?: number; isHeartbeat?: boolean } = {},
) {
  return {
    sessionId: "session-1",
    sessionKey: "agent:m03-estimation:main",
    sessionFile: "unused.jsonl",
    messages,
    prePromptMessageCount: 0,
    ...overrides,
  };
}

// The runner puts the memory guidance in the prompt for the legacy engine only: no other engine's
// tests may see what an earlier test file left registered.
beforeEach(() => {
  clearMemoryPluginState();
});

afterEach(() => {
  clearMemoryPluginState();
});

const ESTIMATION_OK = toolResultMessage("opsys_m3__m3_estimer_projet", "call_1", {
  ok: true,
  resultat: { devis_id: "DEV-1" },
});

describe("OpsysContextEngine identity", () => {
  it("is a distinct engine that owns no compaction and requires the hooks it relies on", () => {
    const { engine } = harness();

    expect(engine.info.id).toBe(OPSYS_CONTEXT_ENGINE_ID);
    expect(engine.info.id).not.toBe("legacy");
    expect(engine.info.ownsCompaction).toBe(false);
    expect(engine.info.acceptedHostParams).toEqual(
      expect.arrayContaining(["sessionKey", "prompt"]),
    );
    expect(engine.info.hostRequirements?.["agent-run"]?.requiredCapabilities).toStrictEqual([
      "assemble-before-prompt",
      "after-turn",
    ]);
  });

  it("delegates compaction to the runtime, with the canonical delegate", () => {
    expect(harness().engine.compact).toBe(delegateCompactionToRuntime);
  });

  it("leaves ingestion to the session manager, like the legacy engine", async () => {
    const { engine } = harness();

    await expect(
      engine.ingest({ sessionId: "s", message: userMessage("x") }),
    ).resolves.toStrictEqual({
      ingested: false,
    });
  });
});

describe("OpsysContextEngine assemble (PREFLIGHT)", () => {
  it.each([
    { title: "no contexte.json", config: { kind: "absent" } as const },
    { title: "a contexte.json that is not active", config: { kind: "disabled" } as const },
  ])("is transparent with $title", async ({ config }) => {
    const { engine, calls, logs } = harness({ config });
    const params = assembleParams();

    const result = await engine.assemble(params);

    expect(result.messages).toBe(params.messages);
    expect(result).not.toHaveProperty("systemPromptAddition");
    expect(calls).toStrictEqual([]);
    expect(logs.warn).toStrictEqual([]);
  });

  it.each([
    { title: "an agent the file does not name", sessionKey: "agent:m01-front-office:main" },
    { title: "a run with no agent session key", sessionKey: undefined },
  ])("is transparent for $title", async ({ sessionKey }) => {
    const { engine, calls, logs } = harness();

    const result = await engine.assemble(assembleParams({ sessionKey }));

    expect(result).not.toHaveProperty("systemPromptAddition");
    expect(calls).toStrictEqual([]);
    expect(logs.warn).toStrictEqual([]);
  });

  it("asks M10 for the packet of the case and injects it, leaving the messages untouched", async () => {
    const { engine, calls, logs, timers } = harness();
    const params = assembleParams();

    const result = await engine.assemble(params);

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      server: CONFIG_M3.contextServers.get("m03-estimation"),
      tool: "m10_paquet_contexte_affaire",
      args: { affaire_id: "LEAD-001", horodatage: NOW },
      timeoutMs: 4_000,
    });
    expect(result.messages).toBe(params.messages);
    expect(result.systemPromptAddition).toContain("affaire LEAD-001");
    expect(result.systemPromptAddition).toContain("Toujours confirmer la longueur des gouttières");
    expect(result.systemPromptAddition).not.toContain(MARKER);
    expect(logs.warn).toStrictEqual([]);
    expect(timers.started.map((timer) => timer.ms)).toStrictEqual([4_000]);
    expect(timers.started.every((timer) => timer.cancelled)).toBe(true);
  });

  it("injects exactly what M10 computed: the rendering of the packet, shortened by nobody", async () => {
    const { engine } = harness();
    const parsed = parsePaquet(PAQUET_M10, "LEAD-001", "m03-estimation");
    if (!parsed.ok) {
      throw new Error(parsed.reason);
    }

    const result = await engine.assemble(assembleParams());

    expect(result.systemPromptAddition).toBe(renderPaquet(parsed.paquet).text);
  });

  it("finds the case whatever surrounds the marker line in the request", async () => {
    const { engine, calls } = harness();

    await engine.assemble(
      assembleParams({ prompt: "Peux-tu estimer ?\n  affaire_id: LEAD-001  \nMerci !" }),
    );

    expect(calls[0]?.args).toMatchObject({ affaire_id: "LEAD-001" });
  });

  it.each([
    {
      title: "no case in the request",
      prompt: "Estime ce projet.",
      handler: undefined,
      reason: "aucune affaire",
      called: false,
    },
    {
      title: "two cases in the request",
      prompt: "affaire_id: LEAD-1\naffaire_id: LEAD-2",
      handler: undefined,
      reason: "plusieurs affaires",
      called: false,
    },
    {
      title: "an engine that cannot be reached",
      prompt: undefined,
      handler: async () => {
        throw new Error("connect ECONNREFUSED");
      },
      reason: "injoignable ou trop lent (connect ECONNREFUSED)",
      called: true,
    },
    {
      title: "an engine that refuses the request",
      prompt: undefined,
      handler: async () => ({ ok: false, erreur: "refus_metier", details: "affaire_id requis" }),
      reason: "refused the request (refus_metier)",
      called: true,
    },
    {
      title: "an answer truncated by the MCP server",
      prompt: undefined,
      handler: async () => ({ ok: true, tronque: true, apercu: "{..." }),
      reason: "truncated",
      called: true,
    },
    {
      title: "a packet about another case",
      prompt: undefined,
      handler: async () => ({ ok: true, resultat: { ...PAQUET_M10, affaire_id: "LEAD-002" } }),
      reason: "another case",
      called: true,
    },
    {
      title: "a packet whose layers contradict their counters",
      prompt: undefined,
      handler: async () => ({
        ok: true,
        resultat: {
          ...PAQUET_M10,
          couches: PAQUET_M10.couches.map((couche) => ({ ...couche, nb_total: 9 })),
        },
      }),
      reason: "do not match",
      called: true,
    },
    {
      title: "an answer that is not the OPSYS envelope",
      prompt: undefined,
      handler: async () => "<html>502 Bad Gateway</html>",
      reason: "not an object",
      called: true,
    },
  ])(
    "carries the marker and goes on, with one journal line, for $title",
    async ({ prompt, handler, reason, called }) => {
      const { engine, calls, logs } = harness(handler ? { handler } : {});
      const params = assembleParams(prompt === undefined ? {} : { prompt });

      const result = await engine.assemble(params);

      expect(result.messages).toBe(params.messages);
      expect(result.systemPromptAddition).toContain(MARKER);
      expect(result.systemPromptAddition).toContain(reason);
      expect(result.systemPromptAddition).not.toContain("Règles de l'entreprise");
      expect(logs.warn).toHaveLength(1);
      expect(logs.warn[0]).toContain(MARKER);
      expect(logs.warn[0]).toContain("m03-estimation");
      expect(calls).toHaveLength(called ? 1 : 0);
    },
  );

  it("stops waiting for an engine that is too slow, and aborts the call", async () => {
    const called = createDeferred<Call>();
    const { engine, logs, timers } = harness({
      handler: async (call) => {
        called.resolve(call);
        return await new Promise<never>(() => {});
      },
    });

    const running = engine.assemble(assembleParams());
    const call = await called.promise;
    expect(call.signal.aborted).toBe(false);
    timers.expireAll();
    const result = await running;

    expect(call.signal.aborted).toBe(true);
    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain("pas de réponse en 4000 ms");
    expect(logs.warn).toHaveLength(1);
  });

  it("refuses a packet whose facts outgrow the budget M10 declared, and never shortens it", async () => {
    const big = {
      ...PAQUET_M10,
      budget_caracteres: 100,
      caracteres_utilises: 40,
      couches: PAQUET_M10.couches.map((couche) => ({ ...couche, caracteres: 10 })),
    };
    const { engine, logs } = harness({ handler: async () => ({ ok: true, resultat: big }) });

    const result = await engine.assemble(assembleParams());

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain("hors du budget de M10");
    expect(result.systemPromptAddition).toContain("sur 100 caractères), non tronqué");
    expect(result.systemPromptAddition).not.toContain("Toujours confirmer");
    expect(logs.warn).toHaveLength(1);
  });

  it("refuses a packet larger than the context budget the runner allows, and never shortens it", async () => {
    const { engine } = harness();

    const result = await engine.assemble(assembleParams({ tokenBudget: 10 }));

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain(
      "plus grand que le budget de contexte disponible, non tronqué",
    );
    expect(result.systemPromptAddition).not.toContain("Toujours confirmer");
  });

  it("injects the packet when the runner gives no token budget", async () => {
    const { engine } = harness();
    const params = { ...assembleParams(), tokenBudget: undefined };

    const result = await engine.assemble(params);

    expect(result.systemPromptAddition).toContain("Toujours confirmer");
  });

  it("says so, for any agent, when the configuration cannot be trusted", async () => {
    const { engine, calls, logs } = harness({
      config: { kind: "invalid", reason: '"agents" must map an agent' },
    });

    const result = await engine.assemble(
      assembleParams({ sessionKey: "agent:m01-front-office:main" }),
    );

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain("configuration invalide");
    expect(logs.warn).toHaveLength(1);
    expect(calls).toStrictEqual([]);
  });

  it("never throws, and costs the turn nothing, even if the engine fails in an unexpected way", async () => {
    const { engine, logs } = harness({
      readConfig: () => {
        throw new Error("boom");
      },
    });
    const params = assembleParams();

    const result = await engine.assemble(params);

    expect(result.messages).toBe(params.messages);
    expect(result.systemPromptAddition).toContain(MARKER);
    expect(logs.warn).toHaveLength(1);
  });
});

describe("OpsysContextEngine afterTurn (POSTFLIGHT)", () => {
  it("hands M10 what the listed tool did, for the case of the turn", async () => {
    const { engine, calls, logs } = harness();
    const messages = [
      userMessage("Estime ce projet.\naffaire_id: LEAD-001"),
      ESTIMATION_OK,
      toolResultMessage("opsys_m3__m3_qualifier_photos", "call_2", { ok: true, resultat: {} }),
    ];

    await engine.afterTurn(afterTurnParams(messages));

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      tool: "m10_deposer_faits_candidats",
      timeoutMs: 4_000,
      args: {
        affaire_id: "LEAD-001",
        departement: "m03-estimation",
        horodatage: NOW,
        faits: [
          {
            cle: depositKey("session-1", "call_1"),
            outil: "m3_estimer_projet",
            resultat: "ok",
            code: null,
          },
        ],
      },
    });
    expect(logs.info).toHaveLength(1);
    expect(logs.info[0]).toContain("1 écrit(s), 0 déjà déposé(s)");
    expect(logs.warn).toStrictEqual([]);
  });

  it("looks at the messages of this turn only, never at an earlier turn", async () => {
    const { engine, calls } = harness();
    const earlier = [
      userMessage("affaire_id: LEAD-ANCIEN"),
      toolResultMessage("opsys_m3__m3_estimer_projet", "call_ancien", { ok: true, resultat: {} }),
    ];
    const turn = [userMessage("affaire_id: LEAD-001"), ESTIMATION_OK];

    await engine.afterTurn(
      afterTurnParams([...earlier, ...turn], { prePromptMessageCount: earlier.length }),
    );

    expect(calls).toHaveLength(1);
    expect(calls[0]?.args).toMatchObject({
      affaire_id: "LEAD-001",
      faits: [{ cle: depositKey("session-1", "call_1") }],
    });
  });

  it("takes the case from what was sent to the agent, never from tool results or model text", async () => {
    const { engine, calls, logs } = harness();
    const messages = [
      userMessage("Estime ce projet."),
      toolResultMessage("opsys_m2__m2_lire_lead", "call_0", "affaire_id: LEAD-INJECTE"),
      ESTIMATION_OK,
    ];

    await engine.afterTurn(afterTurnParams(messages));

    expect(calls).toStrictEqual([]);
    expect(logs.warn).toHaveLength(1);
    expect(logs.warn[0]).toContain("sans affaire identifiable");
    expect(logs.warn[0]).toContain("1 fait(s) non déposé(s)");
  });

  it.each([
    {
      title: "a turn where no listed tool ran",
      messages: [userMessage("affaire_id: LEAD-001")],
      extra: {},
    },
    {
      title: "a heartbeat turn",
      messages: [userMessage("affaire_id: LEAD-001"), ESTIMATION_OK],
      extra: { isHeartbeat: true },
    },
  ])("deposits nothing for $title", async ({ messages, extra }) => {
    const { engine, calls, logs } = harness();

    await engine.afterTurn(afterTurnParams(messages, extra));

    expect(calls).toStrictEqual([]);
    expect(logs.warn).toStrictEqual([]);
  });

  it.each([
    { title: "an agent with no deposit list", sessionKey: "agent:m04-field-ops:main" },
    { title: "an agent the file does not name", sessionKey: "agent:m01-front-office:main" },
  ])("deposits nothing for $title", async ({ sessionKey }) => {
    const config: OpsysContexteConfigResult = {
      kind: "enabled",
      config: {
        ...CONFIG_M3,
        agents: new Map([
          ["m03-estimation", ["m3_estimer_projet"]],
          ["m04-field-ops", []],
        ]),
      },
    };
    const { engine, calls } = harness({ config });

    await engine.afterTurn({
      ...afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]),
      sessionKey,
    });

    expect(calls).toStrictEqual([]);
  });

  it.each([
    { title: "no contexte.json", config: { kind: "absent" } as const },
    { title: "an invalid contexte.json", config: { kind: "invalid", reason: "x" } as const },
  ])("deposits nothing with $title", async ({ config }) => {
    const { engine, calls } = harness({ config });

    await engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]));

    expect(calls).toStrictEqual([]);
  });

  it("splits a long turn into batches M10 accepts, in order", async () => {
    const { engine, calls } = harness();
    const results = Array.from({ length: 45 }, (_, index) =>
      toolResultMessage("opsys_m3__m3_estimer_projet", `call_${String(index)}`, {
        ok: true,
        resultat: {},
      }),
    );

    await engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ...results]));

    const sizes = calls.map((call) =>
      Array.isArray(call.args.faits) ? call.args.faits.length : -1,
    );
    expect(sizes).toStrictEqual([20, 20, 5]);
  });

  it.each([
    {
      title: "an engine that cannot be reached",
      handler: async () => {
        throw new Error("connect ECONNREFUSED");
      },
      line: "POSTFLIGHT indisponible",
    },
    {
      title: "a deposit M10 refuses",
      handler: async () => ({
        ok: true,
        resultat: { accepte: false, verdict: "REJ-CANDIDAT-FAIT-INVALIDE" },
      }),
      line: "refusé par M10",
    },
    {
      title: "an answer that is not the OPSYS envelope",
      handler: async () => "502 Bad Gateway",
      line: "refusé par M10",
    },
  ])("logs one warning and never throws for $title", async ({ handler, line }) => {
    const { engine, logs } = harness({ handler });

    await expect(
      engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK])),
    ).resolves.toBeUndefined();

    expect(logs.warn).toHaveLength(1);
    expect(logs.warn[0]).toContain(line);
    expect(logs.warn[0]).toContain("m03-estimation");
  });

  it.each([
    { title: "missing counters", counts: undefined },
    { title: "empty counters", counts: {} },
    { title: "missing written", counts: { deja_deposes: 1 } },
    { title: "missing already-deposited", counts: { ecrits: 1 } },
    { title: "string count", counts: { ecrits: "1", deja_deposes: 0 } },
    { title: "boolean count", counts: { ecrits: true, deja_deposes: 0 } },
    { title: "negative count", counts: { ecrits: -1, deja_deposes: 2 } },
    { title: "fractional counts", counts: { ecrits: 0.5, deja_deposes: 0.5 } },
    { title: "unsafe count", counts: { ecrits: Number.MAX_SAFE_INTEGER + 1, deja_deposes: 0 } },
    { title: "incomplete total", counts: { ecrits: 0, deja_deposes: 0 } },
    { title: "excess total", counts: { ecrits: 1, deja_deposes: 1 } },
  ])("does not report a successful deposit for $title", async ({ counts }) => {
    const { engine, calls, logs } = harness({
      handler: async () => ({ ok: true, resultat: { accepte: true, resultat: counts } }),
    });
    await engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]));
    expect(calls).toHaveLength(1);
    expect(logs.info).toStrictEqual([]);
    expect(logs.warn).toHaveLength(1);
    expect(logs.warn[0]).toContain("compteurs");
  });

  it("reports an exact already-deposited count without claiming a new write", async () => {
    const { engine, calls, logs } = harness({
      handler: async () => ({
        ok: true,
        resultat: { accepte: true, resultat: { ecrits: 0, deja_deposes: 1, lignes: [] } },
      }),
    });
    await engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]));
    expect(calls).toHaveLength(1);
    expect(logs.warn).toStrictEqual([]);
    expect(logs.info).toHaveLength(1);
    expect(logs.info[0]).toContain("0 écrit(s), 1 déjà déposé(s)");
  });

  it("accepts an exact mixed batch of new and already-deposited facts", async () => {
    const { engine, calls, logs } = harness({
      handler: async () => ({
        ok: true,
        resultat: {
          accepte: true,
          resultat: { ecrits: 1, deja_deposes: 1, lignes: ["synthetic-row"] },
        },
      }),
    });
    const second = toolResultMessage("opsys_m3__m3_estimer_projet", "second-mixed-call", {
      ok: true,
      resultat: {},
    });
    await engine.afterTurn(
      afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK, second]),
    );
    expect(calls).toHaveLength(1);
    expect(logs.warn).toStrictEqual([]);
    expect(logs.info).toHaveLength(1);
    expect(logs.info[0]).toContain("1 écrit(s), 1 déjà déposé(s)");
  });

  it("stops waiting for an engine that is too slow", async () => {
    const called = createDeferred<Call>();
    const { engine, logs, timers } = harness({
      handler: async (call) => {
        called.resolve(call);
        return await new Promise<never>(() => {});
      },
    });

    const running = engine.afterTurn(
      afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]),
    );
    await called.promise;
    timers.expireAll();
    await running;

    expect(logs.warn).toHaveLength(1);
    expect(logs.warn[0]).toContain("pas de réponse en 4000 ms");
  });

  it("never throws, even if the engine fails in an unexpected way", async () => {
    const { engine, logs } = harness({
      readConfig: () => {
        throw new Error("boom");
      },
    });

    await expect(
      engine.afterTurn(afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK])),
    ).resolves.toBeUndefined();

    expect(logs.warn).toHaveLength(1);
  });
});

describe("OpsysContextEngine memory guidance", () => {
  const GUIDANCE = "## Memory Recall\nuse memory_search first";

  it("adds the memory guidance the runner leaves out for a non-legacy engine, before the packet", async () => {
    registerTestMemoryPromptBuilder(() => ["## Memory Recall", "use memory_search first", ""]);
    const { engine } = harness();

    const result = await engine.assemble(assembleParams());

    expect(result.systemPromptAddition?.startsWith(`${GUIDANCE}\n\n## Contexte d'entreprise`)).toBe(
      true,
    );
    expect(result.systemPromptAddition).toContain("Toujours confirmer la longueur des gouttières");
  });

  it.each([
    {
      title: "no contexte.json",
      config: { kind: "absent" } as const,
      sessionKey: "agent:m03-estimation:main",
    },
    {
      title: "a contexte.json that is not active",
      config: { kind: "disabled" } as const,
      sessionKey: "agent:m03-estimation:main",
    },
    {
      title: "an agent the file does not name",
      config: { kind: "enabled", config: CONFIG_M3 } as const,
      sessionKey: "agent:m01-front-office:main",
    },
  ])(
    "keeps the native memory guidance, and only that, with $title",
    async ({ config, sessionKey }) => {
      registerTestMemoryPromptBuilder(() => ["## Memory Recall", "use memory_search first", ""]);
      const { engine, calls } = harness({ config });

      const result = await engine.assemble(assembleParams({ sessionKey }));

      expect(result.systemPromptAddition).toBe(GUIDANCE);
      expect(calls).toStrictEqual([]);
    },
  );

  it("never lets a failure of the memory path cost the turn its packet", async () => {
    registerTestMemoryPromptBuilder(() => {
      throw new Error("memory index unreadable");
    });
    const { engine, logs } = harness();

    const result = await engine.assemble(assembleParams());

    expect(result.systemPromptAddition).toContain("Toujours confirmer la longueur des gouttières");
    expect(result.systemPromptAddition).not.toContain("Memory Recall");
    expect(logs.warn).toHaveLength(1);
    expect(logs.warn[0]).toContain("memory guidance unavailable");
  });
});

const SESSION_M3 = "agent:m03-estimation:main";
const SESSION_CLIENT = "agent:m01-front-office:whatsapp:direct:+15145550101";
const ENVELOPE_CLOS = { ok: true, resultat: PAQUET_M10_SIGNAL_CLOS };

describe("OpsysContextEngine records what the guard needs (PLAN T3.3-suite-b)", () => {
  it("records that the packet is ready, and how many critical signals of the case are still open", async () => {
    const { engine, guardStore } = harness();

    await engine.assemble(assembleParams());

    expect(guardStore.get(SESSION_M3)).toStrictEqual({
      kind: "ready",
      affaireId: "LEAD-001",
      nbOuverts: 1,
      atMs: Date.parse(NOW),
    });
  });

  it("records no open signal once a person closed it", async () => {
    const { engine, guardStore } = harness({
      handler: async () => ENVELOPE_CLOS,
    });

    await engine.assemble(assembleParams());

    expect(guardStore.get(SESSION_M3)).toMatchObject({ kind: "ready", nbOuverts: 0 });
  });

  it.each([
    {
      title: "no case in the request",
      prompt: "Estime ce projet.",
      handler: undefined,
      reason: "aucune affaire",
    },
    {
      title: "an engine that cannot be reached",
      prompt: undefined,
      handler: async () => {
        throw new Error("connect ECONNREFUSED");
      },
      reason: "injoignable ou trop lent",
    },
    {
      title: "a packet about another case",
      prompt: undefined,
      handler: async () => ({ ok: true, resultat: { ...PAQUET_M10, affaire_id: "LEAD-002" } }),
      reason: "another case",
    },
    {
      title: "a packet filtered for another agent",
      prompt: undefined,
      handler: async () => ({
        ok: true,
        resultat: {
          ...PAQUET_M10,
          confidentialite: { ...PAQUET_M10.confidentialite, agent: "m01-front-office" },
        },
      }),
      reason: "not filtered for the agent that asked",
    },
    {
      title: "an answer that is not the OPSYS envelope",
      prompt: undefined,
      handler: async () => "<html>502 Bad Gateway</html>",
      reason: "not an object",
    },
  ])(
    "records that the context is unavailable, and why, for $title",
    async ({ prompt, handler, reason }) => {
      const { engine, guardStore } = harness(handler ? { handler } : {});

      await engine.assemble(assembleParams(prompt === undefined ? {} : { prompt }));

      const state = guardStore.get(SESSION_M3);
      expect(state).toMatchObject({ kind: "unavailable", atMs: Date.parse(NOW) });
      expect(state?.kind === "unavailable" ? state.reason : "").toContain(reason);
    },
  );

  it("records that the context is unavailable when the packet does not fit the budget it was refused for", async () => {
    const { engine, guardStore } = harness();

    await engine.assemble(assembleParams({ tokenBudget: 10 }));

    expect(guardStore.get(SESSION_M3)).toMatchObject({ kind: "unavailable" });
  });

  it("follows the last turn: a failing turn takes the ready state away, a good one gives it back", async () => {
    let answer: unknown = ENVELOPE_CLOS;
    const { engine, guardStore } = harness({ handler: async () => answer });

    await engine.assemble(assembleParams());
    expect(guardStore.get(SESSION_M3)).toMatchObject({ kind: "ready", nbOuverts: 0 });

    answer = "<html>502</html>";
    await engine.assemble(assembleParams());
    expect(guardStore.get(SESSION_M3)).toMatchObject({ kind: "unavailable" });

    answer = ENVELOPE_CLOS;
    await engine.assemble(assembleParams());
    expect(guardStore.get(SESSION_M3)).toMatchObject({ kind: "ready", nbOuverts: 0 });
  });

  it("records nothing for a re-assembly without the prompt, which the runner does after each tool result", async () => {
    const { engine, calls, guardStore, logs } = harness();
    await engine.assemble(assembleParams());
    const before = guardStore.get(SESSION_M3);
    calls.length = 0;

    const params = { ...assembleParams(), prompt: undefined };
    const result = await engine.assemble(params);

    expect(result.messages).toBe(params.messages);
    expect(result).not.toHaveProperty("systemPromptAddition");
    expect(calls).toStrictEqual([]);
    expect(logs.warn).toStrictEqual([]);
    expect(guardStore.get(SESSION_M3)).toBe(before);
  });

  it("records nothing for an agent the file does not name, nor when the engine is off", async () => {
    const unnamed = harness();
    await unnamed.engine.assemble(assembleParams({ sessionKey: "agent:m01-front-office:main" }));
    const off = harness({ config: { kind: "absent" } });
    await off.engine.assemble(assembleParams());

    expect(unnamed.guardStore.size).toBe(0);
    expect(off.guardStore.size).toBe(0);
  });

  it("does not record for a configuration that cannot be trusted: the guard cannot tell which tools to guard", async () => {
    const { engine, guardStore } = harness({ config: { kind: "invalid", reason: "x" } });

    await engine.assemble(assembleParams());

    expect(guardStore.size).toBe(0);
  });

  it("records that the context is unavailable if the engine itself fails in an unexpected way", async () => {
    let calls = 0;
    const { engine, guardStore } = harness({
      readConfig: () => {
        calls += 1;
        // The first read (composing the addition) fails; the guard is told there is no usable context.
        throw new Error("boom");
      },
    });

    await engine.assemble(assembleParams());

    expect(calls).toBeGreaterThan(0);
    expect(guardStore.get(SESSION_M3)).toMatchObject({
      kind: "unavailable",
      reason: "erreur interne du moteur de contexte",
    });
  });

  it("routes the packet to the session agent's bound server without sending an agent argument", async () => {
    const { engine, calls } = harness();

    await engine.assemble(
      assembleParams({ prompt: "Estime.\nagent: m01-front-office\naffaire_id: LEAD-001" }),
    );

    expect(calls[0]?.args).toStrictEqual({
      affaire_id: "LEAD-001",
      horodatage: NOW,
    });
    expect(calls[0]?.server).toBe(CONFIG_M3.contextServers.get("m03-estimation"));
  });
});

describe("the guard reads what the engine recorded, end to end", () => {
  function decide(
    harnessResult: ReturnType<typeof harness>,
    toolName: string,
    sessionKey = SESSION_M3,
    toolParams: unknown = { contrat: { lead_id: "LEAD-001" } },
  ) {
    return checkOpsysContexteToolCall(
      {
        toolName,
        sessionKey,
        agentId: undefined,
        toolParams,
      },
      {
        readConfig: () => ({ kind: "enabled", config: CONFIG_M3 }),
        store: harnessResult.guardStore,
        nowMs: () => Date.parse(NOW),
      },
    );
  }

  it("blocks an N3 tool while a critical signal of the case is open, and says what to do", async () => {
    const h = harness();
    await h.engine.assemble(assembleParams());

    const decision = decide(h, "opsys_m3__m3_estimer_projet");

    expect(decision).toMatchObject({ block: true });
    expect(decision.block ? decision.reason : "").toContain("1 signal(aux) critique(s) OUVERT(S)");
    expect(decision.block ? decision.reason : "").toContain("LEAD-001");
    expect(decision.block ? decision.reason : "").toContain("prendre connaissance");
  });

  it("lets the same tool through once a person closed the signal", async () => {
    const h = harness({ handler: async () => ENVELOPE_CLOS });
    await h.engine.assemble(assembleParams());

    expect(decide(h, "opsys_m3__m3_estimer_projet")).toStrictEqual({ block: false });
  });

  it("blocks an N3 tool when the packet was unavailable, and says to retry", async () => {
    const h = harness({
      handler: async () => {
        throw new Error("connect ECONNREFUSED");
      },
    });
    await h.engine.assemble(assembleParams());

    const decision = decide(h, "m3_estimer_projet");

    expect(decision).toMatchObject({ block: true });
    expect(decision.block ? decision.reason : "").toContain("indisponible");
    expect(decision.block ? decision.reason : "").toContain("Réessaie");
  });

  it("never blocks a tool of a lower level, whatever the state of the context", async () => {
    const h = harness();
    await h.engine.assemble(assembleParams());

    expect(decide(h, "opsys_m3__m3_lire_devis")).toStrictEqual({ block: false });
    expect(decide(h, "m10_deposer_faits_candidats")).toStrictEqual({ block: false });
  });

  it("does not block an N3 tool on a case M10 knows nothing about: that is the owner's decision (PLAN T4.18-b)", async () => {
    // Blocking would stop every case that predates M10's consumers, which have no fact and never will.
    const h = harness({
      handler: async () => ({ ok: true, resultat: emptyPaquet("LEAD-INCONNU") }),
    });
    await h.engine.assemble(assembleParams({ prompt: "Estime.\naffaire_id: LEAD-INCONNU" }));

    expect(
      decide(h, "opsys_m3__m3_estimer_projet", SESSION_M3, {
        contrat: { lead_id: "LEAD-INCONNU" },
      }),
    ).toStrictEqual({ block: false });
  });
});

describe("OpsysContextEngine: the case comes from the session, never from the client's text", () => {
  const LINKED = {
    ok: true,
    resultat: { lie: true, affaire_id: "LEAD-777", lie_par: "amina.admin", lie_le: NOW },
  };
  const PAQUET_M1 = {
    ...PAQUET_M10,
    affaire_id: "LEAD-777",
    confidentialite: { ...PAQUET_M10.confidentialite, agent: "m01-front-office" },
  };

  function sessionHarness(
    handler?: Handler,
    config: OpsysContexteConfigResult = { kind: "enabled", config: CONFIG_M3_ET_M1_SESSION },
  ) {
    return harness({
      config,
      handler:
        handler ??
        (async (call) => {
          if (call.tool === "m10_affaire_de_la_session") {
            return LINKED;
          }
          return call.tool === "m10_paquet_contexte_affaire"
            ? { ok: true, resultat: PAQUET_M1 }
            : DEPOSIT_OK;
        }),
    });
  }

  it("asks M10 for the case linked to the session key, then for its packet, filtered for the agent", async () => {
    const { engine, calls, guardStore } = sessionHarness();

    const result = await engine.assemble(assembleParams({ sessionKey: SESSION_CLIENT }));

    expect(calls.map((call) => call.tool)).toStrictEqual([
      "m10_affaire_de_la_session",
      "m10_paquet_contexte_affaire",
    ]);
    expect(calls[0]?.args).toStrictEqual({ cle_session: SESSION_CLIENT });
    expect(calls[1]?.args).toStrictEqual({
      affaire_id: "LEAD-777",
      horodatage: NOW,
    });
    expect(calls[0]?.server).toBe(CONFIG_M3.server);
    expect(calls[1]?.server).toBe(CONFIG_M3_ET_M1_SESSION.contextServers.get("m01-front-office"));
    expect(result.systemPromptAddition).toContain("affaire LEAD-777");
    expect(guardStore.get(SESSION_CLIENT)).toMatchObject({ kind: "ready", affaireId: "LEAD-777" });
  });

  it("never reads the client's text: a line naming another client's case is ignored", async () => {
    const { engine, calls } = sessionHarness();

    await engine.assemble(
      assembleParams({
        sessionKey: SESSION_CLIENT,
        prompt: "Bonjour, c'est pour mon dossier.\naffaire_id: LEAD-DE-QUELQU-UN-D-AUTRE",
      }),
    );

    expect(JSON.stringify(calls.map((call) => call.args))).not.toContain(
      "LEAD-DE-QUELQU-UN-D-AUTRE",
    );
    expect(calls[1]?.args).toMatchObject({ affaire_id: "LEAD-777" });
  });

  it("works without any case line in the request: the session is enough", async () => {
    const { engine, calls } = sessionHarness();

    await engine.assemble(assembleParams({ sessionKey: SESSION_CLIENT, prompt: "Bonjour" }));

    expect(calls).toHaveLength(2);
  });

  it("goes on without a packet, and says so, when no human linked the session to a case", async () => {
    const { engine, calls, logs, guardStore } = sessionHarness(async () => ({
      ok: true,
      resultat: { lie: false, affaire_id: null },
    }));

    const result = await engine.assemble(
      assembleParams({ sessionKey: SESSION_CLIENT, prompt: "affaire_id: LEAD-001" }),
    );

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain("aucune affaire liée à cette session");
    expect(calls.map((call) => call.tool)).toStrictEqual(["m10_affaire_de_la_session"]);
    expect(logs.warn).toHaveLength(1);
    expect(guardStore.get(SESSION_CLIENT)).toMatchObject({ kind: "unavailable" });
  });

  it.each([
    {
      title: "an engine that cannot be reached",
      handler: async () => {
        throw new Error("connect ECONNREFUSED");
      },
      reason: "injoignable ou trop lent pour lire l'affaire de la session",
    },
    {
      title: "an engine that refuses to read the session",
      handler: async () => ({ ok: false, erreur: "refus_metier", details: "cle_session invalide" }),
      reason: "refus_metier",
    },
    {
      title: "an answer that is not the OPSYS envelope",
      handler: async () => "<html>502</html>",
      reason: "autre chose qu'un objet",
    },
  ])("goes on without a packet, marked and logged, for $title", async ({ handler, reason }) => {
    const { engine, calls, logs, guardStore } = sessionHarness(handler);

    const result = await engine.assemble(assembleParams({ sessionKey: SESSION_CLIENT }));

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain(reason);
    expect(calls).toHaveLength(1);
    expect(logs.warn).toHaveLength(1);
    expect(guardStore.get(SESSION_CLIENT)).toMatchObject({ kind: "unavailable" });
  });

  it("stops waiting for the engine when it is too slow to say which case the session is about", async () => {
    const called = createDeferred<Call>();
    const { engine, timers } = sessionHarness(async (call) => {
      called.resolve(call);
      return await new Promise<never>(() => {});
    });

    const running = engine.assemble(assembleParams({ sessionKey: SESSION_CLIENT }));
    const call = await called.promise;
    timers.expireAll();
    const result = await running;

    expect(call.signal.aborted).toBe(true);
    expect(result.systemPromptAddition).toContain("pas de réponse en 4000 ms");
  });

  it("keeps the request line for an agent that only receives internal requests", async () => {
    const { engine, calls } = sessionHarness();

    await engine.assemble(assembleParams());

    expect(calls.map((call) => call.tool)).toStrictEqual(["m10_paquet_contexte_affaire"]);
    expect(calls[0]?.args).toMatchObject({ affaire_id: "LEAD-001" });
    expect(calls[0]?.args).not.toHaveProperty("agent");
    expect(calls[0]?.server).toBe(CONFIG_M3.contextServers.get("m03-estimation"));
  });

  describe("POSTFLIGHT", () => {
    const CONFIG_DEPOT: OpsysContexteConfigResult = {
      kind: "enabled",
      config: {
        ...CONFIG_M3_ET_M1_SESSION,
        agents: new Map([
          ["m03-estimation", ["m3_estimer_projet"]],
          ["m01-front-office", ["m1_qualifier_lead"]],
        ]),
      },
    };
    const QUALIFICATION = toolResultMessage("opsys_m1__m1_qualifier_lead", "call_q1", {
      ok: true,
      resultat: { accepte: true },
    });
    const turn = [
      userMessage("Je m'appelle un autre client.\naffaire_id: LEAD-INJECTE"),
      QUALIFICATION,
    ];

    it("deposits for the case linked to the session, not the one the client wrote", async () => {
      const { engine, calls } = sessionHarness(undefined, CONFIG_DEPOT);

      await engine.afterTurn({ ...afterTurnParams(turn), sessionKey: SESSION_CLIENT });

      expect(calls.map((call) => call.tool)).toStrictEqual([
        "m10_affaire_de_la_session",
        "m10_deposer_faits_candidats",
      ]);
      expect(calls[1]?.args).toMatchObject({
        affaire_id: "LEAD-777",
        departement: "m01-front-office",
        faits: [{ outil: "m1_qualifier_lead", resultat: "ok" }],
      });
      expect(JSON.stringify(calls.map((call) => call.args))).not.toContain("LEAD-INJECTE");
    });

    it("deposits nothing, and says why, when the session is not linked to a case", async () => {
      const { engine, calls, logs } = sessionHarness(
        async () => ({ ok: true, resultat: { lie: false, affaire_id: null } }),
        CONFIG_DEPOT,
      );

      await engine.afterTurn({ ...afterTurnParams(turn), sessionKey: SESSION_CLIENT });

      expect(calls.map((call) => call.tool)).toStrictEqual(["m10_affaire_de_la_session"]);
      expect(logs.warn).toHaveLength(1);
      expect(logs.warn[0]).toContain("sans affaire identifiable");
      expect(logs.warn[0]).toContain("aucune affaire liée à cette session");
    });
  });
});

describe("OpsysContextEngine: what M10 says of the case itself (PLAN T4.18-b)", () => {
  it("asks for the opportunity M2 opens, named whole on the request line, and injects its packet", async () => {
    const { engine, calls } = harness({
      handler: async () => ({ ok: true, resultat: PAQUET_M10_OPPORTUNITE }),
    });

    const result = await engine.assemble(
      assembleParams({
        prompt: `Estime le chantier suivant.\naffaire_id: ${AFFAIRE_M10_OPPORTUNITE}`,
      }),
    );

    expect(calls[0]?.args).toMatchObject({
      affaire_id: AFFAIRE_M10_OPPORTUNITE,
    });
    expect(calls[0]?.args).not.toHaveProperty("agent");
    expect(result.systemPromptAddition).toContain(`affaire ${AFFAIRE_M10_OPPORTUNITE}`);
    expect(result.systemPromptAddition).toContain("ouverte par m2.client_associe");
    expect(result.systemPromptAddition).not.toContain(MARKER);
  });

  it("says a case is unknown instead of showing empty layers, journals it, and lets the turn go on", async () => {
    const { engine, logs, guardStore } = harness({
      handler: async () => ({ ok: true, resultat: emptyPaquet("LEAD-INCONNU") }),
    });

    const result = await engine.assemble(
      assembleParams({ prompt: "Estime.\naffaire_id: LEAD-INCONNU" }),
    );

    expect(result.systemPromptAddition).toContain(
      "Affaire inconnue de la mémoire : aucun fait reçu pour l'identifiant LEAD-INCONNU.",
    );
    expect(result.systemPromptAddition).not.toContain(MARKER);
    expect(
      logs.info.some(
        (line) => line.includes("affaire inconnue de la mémoire") && line.includes("LEAD-INCONNU"),
      ),
    ).toBe(true);
    expect(logs.warn).toStrictEqual([]);
    expect(guardStore.get("agent:m03-estimation:main")).toMatchObject({
      kind: "ready",
      affaireId: "LEAD-INCONNU",
      nbOuverts: 0,
    });
  });

  it("journals nothing about a case M10 knows, even one whose opening step it never received", async () => {
    const { engine, logs } = harness();

    await engine.assemble(assembleParams());

    expect(logs.info.filter((line) => line.includes("affaire inconnue"))).toStrictEqual([]);
  });

  it("refuses a packet that calls the case unknown while it carries its events, and says so", async () => {
    const contradiction = { ...PAQUET_M10, affaire: emptyPaquet("LEAD-001").affaire };
    const { engine, logs } = harness({
      handler: async () => ({ ok: true, resultat: contradiction }),
    });

    const result = await engine.assemble(assembleParams());

    expect(result.systemPromptAddition).toContain(MARKER);
    expect(result.systemPromptAddition).toContain(
      "calls the case unknown but carries its events or signals",
    );
    expect(logs.warn.some((line) => line.includes("paquet inutilisable"))).toBe(true);
  });
});

describe("POSTFLIGHT handoff to the actual collector", () => {
  const receipt = {
    sessionId: "session-1",
    sessionKey: "agent:m03-estimation:main",
    agentId: "m03-estimation",
    factKeys: [depositKey("session-1", "call_1")],
  };

  it("never deposits a collector-owned key using the affair guessed from conversation text", async () => {
    const { engine, calls } = harness();
    await engine.afterTurn({
      ...afterTurnParams([userMessage("affaire_id: LEAD-WRONG"), ESTIMATION_OK]),
      runtimeContext: { opsysDeferredPostflight: receipt },
    });
    expect(calls).toEqual([]);
  });

  it("still deposits other calls of the same tool from this turn", async () => {
    const { engine, calls } = harness();
    const other = toolResultMessage("opsys_m3__m3_estimer_projet", "not-owned", {
      ok: true,
      resultat: {},
    });
    await engine.afterTurn({
      ...afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK, other]),
      runtimeContext: { opsysDeferredPostflight: receipt },
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.args.faits).toEqual([
      {
        cle: depositKey("session-1", "not-owned"),
        outil: "m3_estimer_projet",
        resultat: "ok",
        code: null,
      },
    ]);
  });

  it.each([
    { ...receipt, sessionId: "other-session" },
    { ...receipt, sessionKey: "agent:m03-estimation:other" },
    { ...receipt, agentId: "m05-financecore" },
    { ...receipt, factKeys: ["not-a-canonical-key"] },
    { ...receipt, factKeys: Array.from({ length: 21 }, () => receipt.factKeys[0]) },
  ])("keeps the legacy path for an invalid or unrelated host receipt %#", async (wrong) => {
    const { engine, calls } = harness();
    await engine.afterTurn({
      ...afterTurnParams([userMessage("affaire_id: LEAD-001"), ESTIMATION_OK]),
      runtimeContext: { opsysDeferredPostflight: wrong },
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.args.faits).toEqual([
      {
        cle: depositKey("session-1", "call_1"),
        outil: "m3_estimer_projet",
        resultat: "ok",
        code: null,
      },
    ]);
  });
});
