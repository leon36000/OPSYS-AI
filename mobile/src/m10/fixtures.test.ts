import { createHash } from "node:crypto";
import { FIXTURES_M10 } from "./fixtures";
import { lireReferencesM10, lireSignauxM10, lireStatutDecisionM10, lireStatutRevisionM10 } from "./contrat";

test("captures fictives natives conservées exactement avec provenance et SHA", () => {
  expect(FIXTURES_M10.fictif).toBe(true);
  const reponses = new Map<string, unknown>(Object.entries(FIXTURES_M10.reponses).map(([nom, r]) => [nom, r.enveloppe]));
  for (const source of FIXTURES_M10.provenance) {
    expect(source.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(source.preuve).toContain("réel");
    for (const [nom, sha] of Object.entries(source.enveloppes_sha256)) {
      const serialise = JSON.stringify(reponses.get(nom));
      expect(typeof serialise).toBe("string");
      if (typeof serialise === "string") expect(createHash("sha256").update(serialise).digest("hex")).toBe(sha);
    }
  }
});

test("les fixtures de lecture font foi sur les identifiants natifs sans conversion signal/révision", () => {
  const f = FIXTURES_M10.reponses;
  expect(lireSignauxM10(f.signaux_ouverts.enveloppe).ok).toBe(true);
  expect(lireSignauxM10(f.signaux_volume.enveloppe).ok).toBe(true);
  expect(lireStatutDecisionM10(f.decision_proposee.enveloppe)).toEqual({ ok: true, value: { statut: "proposee" } });
  expect(lireStatutRevisionM10(f.revision_arbitree.enveloppe)).toEqual({ ok: true, value: { statut: "distincts_confirmes" } });
  const r = lireReferencesM10(f.catalogue_page_2.enveloppe);
  expect(r.ok).toBe(true);
  if (r.ok) {
    expect(r.value.revisions[0].revision_ligne_id).not.toBe(f.signaux_ouverts.enveloppe.resultat.signaux[0].signal_id);
    expect(r.value.revisions[0].reference.hash_tete).toBe(r.value.revisions[0].revision_ligne_id);
  }
});
