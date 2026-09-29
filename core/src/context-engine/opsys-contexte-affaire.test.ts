// The form of a case, shared with M10 (OPSYS-AI PLAN T4.18-b). A case is a lead (`LEAD-001`) or the opportunity M2
// opens when a client comes back (`LEAD-001~opp~WCT-009`): bounded (64 + 5 + 128 characters) and closed (letters,
// digits and `._:-`). `opsys-contexte.affaires.json` lists the cases both sides must agree on: M10 replays it in
// `departments/m10-memoire/tests/test_affaire.py`, through every entry that takes a case; this file replays the
// same list through the core's own reading (`isOpsysAffaireId`, the `affaire_id:` line of a request, and the case
// M10 links to a session). Every identifier in the list is fictional (`fictif: true`).
import { describe, expect, it } from "vitest";
import cases from "./opsys-contexte.affaires.json" with { type: "json" };
import {
  extractAffaireId,
  isOpsysAffaireId,
  parseAffaireEnvelope,
} from "./opsys-contexte-paquet.js";

function linkedTo(affaireId: string): unknown {
  return { ok: true, resultat: { lie: true, affaire_id: affaireId } };
}

describe("the list of cases shared with M10", () => {
  it("is fictional, covers both forms and their bounds, and its limits add up", () => {
    expect(cases.fictif).toBe(true);
    expect(new Set(cases.acceptees.map((entry) => entry.genre))).toStrictEqual(
      new Set(["lead", "opportunite"]),
    );
    const lengths = cases.acceptees.map((entry) => entry.id.length);
    expect(lengths).toContain(1);
    expect(lengths).toContain(cases.limites.lead);
    expect(lengths).toContain(cases.limites.affaire);
    expect(cases.limites.affaire).toBe(
      cases.limites.lead + cases.limites.separateur + cases.limites.wct,
    );
    expect(cases.refusees.length).toBeGreaterThanOrEqual(50);
    const ids = [...cases.acceptees, ...cases.refusees].map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("puts the bounds where the identifiers stop: one character more is refused", () => {
    const lead = "a".repeat(cases.limites.lead);
    const wct = "b".repeat(cases.limites.wct);

    expect(isOpsysAffaireId(lead)).toBe(true);
    expect(isOpsysAffaireId(`${lead}~opp~${wct}`)).toBe(true);
    expect(`${lead}~opp~${wct}`).toHaveLength(cases.limites.affaire);
    expect(isOpsysAffaireId(`${lead}a`)).toBe(false);
    expect(isOpsysAffaireId(`${lead}~opp~${wct}b`)).toBe(false);
  });
});

describe("a case M10 admits is a case for the core", () => {
  it.each(cases.acceptees)("admits $note", ({ id }) => {
    expect(isOpsysAffaireId(id)).toBe(true);
    expect(extractAffaireId(`Estime ce projet.\naffaire_id: ${id}\nMerci.`)).toStrictEqual({
      kind: "found",
      affaireId: id,
    });
    expect(parseAffaireEnvelope(linkedTo(id))).toStrictEqual({ kind: "found", affaireId: id });
  });
});

describe("a case M10 refuses is never a case for the core", () => {
  it.each(cases.refusees)("refuses $note", ({ id }) => {
    expect(isOpsysAffaireId(id)).toBe(false);
    expect(parseAffaireEnvelope(linkedTo(id))).toMatchObject({ kind: "unresolved" });
    // Written on the line of a request, a refused identifier is never taken as itself: at most a well-formed
    // part of it, cut at a line break or at trailing spaces, is found.
    const lookup = extractAffaireId(`affaire_id: ${id}`);
    expect(lookup.kind === "found" ? lookup.affaireId : undefined).not.toBe(id);
  });
});

describe("the affaire_id line of a request", () => {
  it("finds the opportunity M2 opens, whole", () => {
    expect(extractAffaireId("affaire_id: LEAD-001~opp~WCT-009")).toStrictEqual({
      kind: "found",
      affaireId: "LEAD-001~opp~WCT-009",
    });
  });

  it("never cuts an opportunity at its separator: the lead alone is another case", () => {
    expect(
      extractAffaireId("affaire_id: LEAD-001~opp~WCT-009\naffaire_id: LEAD-001"),
    ).toStrictEqual({ kind: "ambiguous" });
  });

  it.each([
    { title: "a lead past its bound", text: `affaire_id: ${"a".repeat(65)}` },
    { title: "a wct_id past its bound", text: `affaire_id: LEAD-1~opp~${"b".repeat(129)}` },
    { title: "a separator without a wct_id", text: "affaire_id: LEAD-1~opp~" },
    { title: "a wct_id that does not start with a letter or digit", text: "affaire_id: LEAD-1~opp~-x" },
    { title: "a chain of opportunities (the form admits one level)", text: "affaire_id: L~opp~a~opp~b" },
  ])("takes no prefix of $title: no case", ({ text }) => {
    expect(extractAffaireId(text)).toStrictEqual({ kind: "none" });
  });
});
