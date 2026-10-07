import { presenterCreances, presenterAP, presenterAttentes } from "./comptes";
import { lireCreances, lireAP, lireAttentes } from "../m5/comptes";
import { creances, ap, attentes, JOUR } from "../m5/fixturesComptes";
test("âge depuis envoi, source financière textuelle et montants sans calcul", () => {
  const lu = lireCreances(creances, JOUR)!;
  const v = presenterCreances(lu, "fr-CA", -240);
  expect(v.lignes.some(m => m.cle === "admin.comptes.ageDepuisEnvoi")).toBe(true);
  expect(v.groupes[0].lignes.some(m => m.params?.valeur === "689,85\u00a0$")).toBe(true);
});
test("montants inconnus jamais blancs/zero, rapprochement reste proposé", () => {
  const brut: any = JSON.parse(JSON.stringify(ap));
  brut.totaux.a_payer_apres_taxes = null; brut.totaux.complet = false;
  brut.comptes[0].a_payer_apres_taxes = null; brut.comptes[0].attendu.apres_taxes = null;
  const v = presenterAP(lireAP(brut, false, 0)!, "fr-CA", -240);
  expect(v.lignes[1].cle).toBe("admin.comptes.payerPartiel");
  expect(v.groupes[0].lignes.some(m => m.cle === "admin.comptes.payerInconnu")).toBe(true);
  expect(v.groupes[0].lignes.some(m => m.cle === "admin.comptes.attenduInconnu")).toBe(true);
});
test("masquage n'est pas une liste vide ; attentes ne sont pas une approbation", () => {
  expect(presenterAP({ genre: "masquee", nombre: 5, role: "admin" }, "en-CA", 0).vide).toBe(false);
  expect(presenterAttentes(lireAttentes(attentes)!).lignes[0].cle).toBe("admin.comptes.attentesLecture");
});

test("les versions fiscales sont des données et ne deviennent pas des clés de traduction", () => {
  const v = presenterAP(lireAP(ap, false, 0)!, "fr-CA", -240);
  const versions = v.lignes.filter(m => m.cle === "admin.comptes.versionFiscale");
  expect(versions.map(m => m.params)).toEqual(Object.entries(ap.taxes_versions).map(([taxe, version]) => ({ taxe, version })));
});
