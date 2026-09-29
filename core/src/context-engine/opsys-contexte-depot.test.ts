// OPSYS context engine POSTFLIGHT facts (OPSYS-AI PLAN T3.3-suite): what the core hands M10 after a
// turn is read from the department tools' own structured answers, never from the model's text.
import { describe, expect, it } from "vitest";
import { collectDepositFacts, collectUserText, depositKey } from "./opsys-contexte-depot.js";

const TOOLS = ["m3_estimer_projet"];

function toolResult(
  toolName: string,
  toolCallId: string,
  answer: unknown,
  overrides: Record<string, unknown> = {},
) {
  return {
    role: "toolResult",
    toolCallId,
    toolName,
    content: [{ type: "text", text: typeof answer === "string" ? answer : JSON.stringify(answer) }],
    isError: false,
    timestamp: 1,
    ...overrides,
  };
}

function collect(messages: readonly unknown[], depositTools: readonly string[] = TOOLS) {
  return collectDepositFacts({ sessionId: "session-1", messages, depositTools });
}

describe("collectDepositFacts", () => {
  it("turns a successful tool answer into an ok fact keyed by the call", () => {
    const facts = collect([
      toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: true, resultat: { devis_id: "DEV-1" } }),
    ]);

    expect(facts).toStrictEqual([
      { cle: depositKey("session-1", "call_1"), outil: "m3_estimer_projet", resultat: "ok", code: null },
    ]);
  });

  it("matches the tool with or without the server prefix, and only exactly", () => {
    const facts = collect([
      toolResult("m3_estimer_projet", "a", { ok: true, resultat: {} }),
      toolResult("opsys_m3__m3_estimer_projet", "b", { ok: true, resultat: {} }),
      toolResult("opsys_m3__m3_estimer_projet_bis", "c", { ok: true, resultat: {} }),
      toolResult("opsys_m3__autre_m3_estimer_projet", "d", { ok: true, resultat: {} }),
    ]);

    expect(facts.map((fact) => fact.cle)).toStrictEqual([
      depositKey("session-1", "a"),
      depositKey("session-1", "b"),
    ]);
  });

  it("deposits nothing for a tool that is not in the agent's list", () => {
    expect(
      collect([toolResult("opsys_m3__m3_qualifier_photos", "call_1", { ok: true, resultat: {} })]),
    ).toStrictEqual([]);
    expect(collect([toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: true })], [])).toStrictEqual([]);
  });

  it("reads a refusal and keeps the tool's own code", () => {
    const facts = collect([
      toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: false, erreur: "refus_metier", details: "x" }),
    ]);

    expect(facts).toMatchObject([{ resultat: "refus", code: "refus_metier" }]);
  });

  it("reads a domain refusal (accepte false) and its verdict", () => {
    const facts = collect([
      toolResult("opsys_m3__m3_estimer_projet", "call_1", {
        ok: true,
        resultat: { accepte: false, verdict: "REJ-PHOTOS-INSUFFISANTES" },
      }),
    ]);

    expect(facts).toMatchObject([{ resultat: "refus", code: "REJ-PHOTOS-INSUFFISANTES" }]);
  });

  it("drops a code that is not in the closed form M10 accepts, instead of sending it", () => {
    const facts = collect([
      toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: false, erreur: "deux mots" }),
    ]);

    expect(facts).toMatchObject([{ resultat: "refus", code: null }]);
  });

  it("counts a truncated but successful answer as done", () => {
    const facts = collect([
      toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: true, tronque: true, apercu: "{..." }),
    ]);

    expect(facts).toMatchObject([{ resultat: "ok", code: null }]);
  });

  it.each([
    { title: "an action waiting for an approval (it did not happen)", answer: { ok: true, statut: "en_attente_approbation" } },
    { title: "text that is not JSON", answer: "Erreur : délai dépassé" },
    { title: "JSON that is not an OPSYS answer", answer: "[1, 2]" },
    { title: "an answer with no ok flag", answer: { resultat: {} } },
  ])("produces no fact for $title", ({ answer }) => {
    expect(collect([toolResult("opsys_m3__m3_estimer_projet", "call_1", answer)])).toStrictEqual([]);
  });

  it("produces no fact for a result with no text or a transport error that says nothing about the tool", () => {
    const noText = { ...toolResult("opsys_m3__m3_estimer_projet", "call_1", {}), content: [] };
    const transportError = toolResult("opsys_m3__m3_estimer_projet", "call_2", "MCP error -32001: Request timed out", {
      isError: true,
    });

    expect(collect([noText, transportError])).toStrictEqual([]);
  });

  it("ignores everything the model wrote", () => {
    const facts = collect([
      { role: "user", content: "affaire_id: LEAD-001", timestamp: 1 },
      {
        role: "assistant",
        content: [
          { type: "text", text: "J'ai estimé le projet avec m3_estimer_projet : 12 345 $." },
          { type: "toolCall", id: "call_1", name: "opsys_m3__m3_estimer_projet", arguments: {} },
        ],
        timestamp: 2,
      },
    ]);

    expect(facts).toStrictEqual([]);
  });

  it("gives one fact per tool call even if a result is seen twice", () => {
    const message = toolResult("opsys_m3__m3_estimer_projet", "call_1", { ok: true, resultat: {} });

    expect(collect([message, message])).toHaveLength(1);
  });

  it("ignores things that are not messages", () => {
    expect(collect([null, "texte", 7, [], { role: "toolResult" }])).toStrictEqual([]);
  });
});

describe("depositKey", () => {
  it("is stable, different per call and per session, and safe whatever the provider puts in a call id", () => {
    const key = depositKey("session-1", "call_1|fc_abc/def+ghi==");

    expect(key).toBe(depositKey("session-1", "call_1|fc_abc/def+ghi=="));
    expect(key).not.toBe(depositKey("session-1", "call_2"));
    expect(key).not.toBe(depositKey("session-2", "call_1|fc_abc/def+ghi=="));
    expect(key).toMatch(/^tc-[0-9a-f]{40}$/u);
  });

  it("does not confuse two ways of splitting the same characters", () => {
    expect(depositKey("ab", "c")).not.toBe(depositKey("a", "bc"));
  });
});

describe("collectUserText", () => {
  it("joins the text of user messages only", () => {
    const text = collectUserText([
      { role: "user", content: "Estime ce projet.", timestamp: 1 },
      { role: "assistant", content: [{ type: "text", text: "affaire_id: LEAD-666" }], timestamp: 2 },
      toolResult("opsys_m2__m2_lire_lead", "call_1", "affaire_id: LEAD-777"),
      { role: "user", content: [{ type: "text", text: "affaire_id: LEAD-001" }], timestamp: 3 },
    ]);

    expect(text).toBe("Estime ce projet.\naffaire_id: LEAD-001");
  });

  it("leaves out the runtime context carriers", () => {
    const text = collectUserText([
      { role: "user", content: "affaire_id: LEAD-INJECTE", runtimeContextCarrier: true, timestamp: 1 },
      { role: "user", content: "affaire_id: LEAD-001", timestamp: 2 },
    ]);

    expect(text).toBe("affaire_id: LEAD-001");
  });
});
