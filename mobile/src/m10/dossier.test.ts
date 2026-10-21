import { FIXTURES_DOSSIER_M10 } from "./fixturesDossier";
import { lireDossierRevisionM10 } from "./dossier";

const native = FIXTURES_DOSSIER_M10.reponses.dossier_complet.enveloppe;
const copie = (): Record<string, any> => JSON.parse(JSON.stringify(native));
test("les deux décisions natives restent exactes, avec leurs raisons, options et références", () => {
  expect(FIXTURES_DOSSIER_M10.fictif).toBe(true);
  const r = lireDossierRevisionM10(native);
  expect(r.ok).toBe(true);
  if (r.ok) {
    expect(r.value.faits.map(f => f.champs)).toEqual(native.resultat.resultat.faits.map(f => f.champs));
    expect(r.value.faits[0].reference.ligne_id).toBe(r.value.revision.reference_a.ligne_id);
  }
});
test("événement et preuves JSON sont lus sans conversion ni écriture", () => {
  const env = FIXTURES_DOSSIER_M10.reponses.dossier_evenement_preuves.enveloppe;
  const before = JSON.stringify(env); const r = lireDossierRevisionM10(env);
  expect(r.ok).toBe(true); expect(JSON.stringify(env)).toBe(before);
  if (r.ok) expect(r.value.faits.map(f => f.champs)).toEqual(env.resultat.resultat.faits.map(f => f.champs));
});
test.each(["dossier_inconnu", "dossier_confidentialite", "dossier_hors_budget", "dossier_source_non_comparable", "dossier_identite_revoquee"] as const)("refus natif %s reste distinct d'un dossier vide", nom => {
  const r = lireDossierRevisionM10(FIXTURES_DOSSIER_M10.reponses[nom].enveloppe);
  expect(r.ok).toBe(false);
  if (!r.ok) expect(r.code).not.toBe("reponse_illisible");
});
test("une autre révision et des faits intervertis ne permettent pas l'action demandée", () => {
  expect(lireDossierRevisionM10(native, "a".repeat(64)).ok).toBe(false);
  const env = copie(); env.resultat.resultat.faits.reverse();
  expect(lireDossierRevisionM10(env).ok).toBe(false);
});
test("données privées/de développement ou métadonnées hors contrat ne sont pas projetées", () => {
  for (const k of ["confidentialite", "ligne_id", "precedent_ligne_id", "type_entree", "horodatage"]) {
    const env = copie(); env.resultat.resultat.faits[0].champs[k] = "fictif";
    expect(lireDossierRevisionM10(env).ok).toBe(false);
  }
  const env = copie(); env.resultat.resultat.faits[0].type_entree = "memoire_developpement";
  expect(lireDossierRevisionM10(env).ok).toBe(false);
});
test("getters, cycles, valeurs unsafe et trous ne sont jamais lus comme des faits", () => {
  const env = copie(); let appels = 0;
  Object.defineProperty(env.resultat.resultat.faits[0].champs, "raison", { enumerable: true, get: () => { appels++; throw new Error("getter fictif"); } });
  expect(lireDossierRevisionM10(env).ok).toBe(false); expect(appels).toBe(0);
  for (const v of [NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    const e = copie(); e.resultat.resultat.faits[0].champs.nombre = v; expect(lireDossierRevisionM10(e).ok).toBe(false);
  }
  const e = copie(); delete e.resultat.resultat.faits[0]; expect(lireDossierRevisionM10(e).ok).toBe(false);
  const c = copie(); c.resultat.resultat.faits[0].champs.cycle = c; expect(lireDossierRevisionM10(c).ok).toBe(false);
});
