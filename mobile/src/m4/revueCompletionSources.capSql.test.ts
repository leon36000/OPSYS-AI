import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import captures from "./fixturesRevueCompletionCapSQL.json";
import {
  lireDossierRevueCompletion, lireCreationPropositionRevueCompletion,
  lireDecisionRevueCompletion, figerPayloadDecisionRevueCompletion,
} from "./revueCompletionSources";

// Réponses Cap/SQLite réelles, monde fictif et identité injectée par le harnais ROOT.
// Aucun transport HTTP/Gateway n'est revendiqué par ce consommateur.
test("la copie SQL r3 reste byte-exact ; origine Cap sans transport déclarée", () => {
  const bytes = readFileSync(join(__dirname, "fixturesRevueCompletionCapSQL.json"));
  expect(createHash("sha256").update(bytes).digest("hex"))
    .toBe("c3f9e948ec4c15e7f6eb7dd8f94a3f310133caeb191242bfd0580a800fe38a74");
  expect(captures.fictif).toBe(true);
  expect(captures.origine).toContain("aucun HTTP/Gateway");
});

test.each(captures.lectures)("T0 $arguments.demande_id lit l'enveloppe couple réelle entière", (c) => {
  expect(lireDossierRevueCompletion(c.reponse, c.arguments))
    .toEqual({ ok: true, value: c.reponse.resultat.resultat });
  expect(c.tables_apres).toEqual(c.tables_avant);
});

test("P réelle certifie uniquement la création et son couple propre", () => {
  const c = captures.creation;
  const r = lireCreationPropositionRevueCompletion(c.reponse, c.arguments, {
    personne: c.reponse.preuve_proposition.proposant.personne,
    appareil_id: c.meta.appareil_id, intention_uuid: c.meta.intention_uuid,
  });
  expect(r).toEqual({ ok: true, value: c.reponse });
});

test("D réelle lie sa preuve à la proposition historique validée et à la mutation locale", () => {
  const c = captures.decision;
  const lu = lireDossierRevueCompletion(captures.lectures[1].reponse, captures.lectures[1].arguments);
  expect(lu.ok).toBe(true);
  if (!lu.ok || lu.value.lecture !== "historique") throw new Error("fixture historique attendue");
  const h = lu.value;
  const payload = figerPayloadDecisionRevueCompletion({
    arguments_decision: c.arguments, outil_proposition: h.proposition.outil,
    capture_proposition: { demande_id: h.demande.id, empreinte_arguments: h.proposition.empreinte_arguments,
      sources: h.demande.arguments.sources },
    destination_origine: { personne: c.auteur_sql, appareil_id: c.meta.appareil_id,
      url_base: "https://fixture-sql.fictif.invalid" },
  });
  expect(payload).not.toBeNull();
  expect(lireDecisionRevueCompletion(c.reponse, payload, { personne: c.auteur_sql, ...c.meta }))
    .toEqual({ ok: true, value: c.reponse.resultat.resultat });
});
