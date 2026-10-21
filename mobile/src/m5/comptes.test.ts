import { lireCreances, lireAP, lireAttentes } from "./comptes";
import { creances, ap, sansPO, attentes, JOUR, FICTIF } from "./fixturesComptes";
const copie = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
test("formes M5 fictives, décimaux conservés et âge depuis envoi", () => {
  expect(FICTIF).toBe(true);
  expect(lireCreances(creances, JOUR)).toMatchObject({ genre: "creances", total_a_recevoir: "689.85", nombre: 1 });
  expect(lireAP(ap, false, 0)).toMatchObject({ genre: "page", total_apres_taxes: "344.93", complet: true });
  expect(lireAP(sansPO, true, 0)).toMatchObject({ genre: "page", total_apres_taxes: "114.98", sans_po: true });
  expect(lireAttentes(attentes)).toMatchObject({ devis: attentes.attentes_devis, wct: attentes.attentes_wct_sans_devis_id });
});
test.each([NaN, Infinity, 2 ** 53, -1, 0.5])("compteur AP illisible %s", n => {
  expect(lireAP({ ...ap, total: n }, false, 0)).toBeNull();
});
test("curseur, jour et page contradictoires refusés, rapprochement appliqué refusé", () => {
  expect(lireAP({ ...ap, prochain_depart: 1 }, false, 0)).toBeNull();
  expect(lireAP(ap, false, 1)).toBeNull();
  expect(lireAP(sansPO, false, 0)).toBeNull();
  expect(lireCreances(creances, "2026-09-03")).toBeNull();
  const mauvais = copie(ap); mauvais.comptes[0].rapprochement.statut = "APPLIQUE";
  expect(lireAP(mauvais, false, 0)).toBeNull();
});
test("inconnu reste null ; connu n'est pas un total complet", () => {
  const brut: any = copie(ap);
  brut.totaux.complet = false; brut.totaux.a_payer_apres_taxes = null;
  brut.comptes[0].a_payer_apres_taxes = null; brut.comptes[0].attendu.apres_taxes = null;
  expect(lireAP(brut, false, 0)).toMatchObject({ complet: false, total_apres_taxes: null, connu_apres_taxes: "344.93" });
});
test("montants masqués explicitement, aucune ligne ni valeur inventée", () => {
  expect(lireCreances({ role: "admin", montants_masques: true, nombre: 3 }, JOUR)).toEqual({ genre: "masquee", role: "admin", nombre: 3 });
  expect(lireAP({ role: "admin", montants_masques: true, nombre_po: 5 }, false, 0)).toMatchObject({ genre: "masquee", nombre: 5 });
});
test("montant flottant, champ absent, liste malformée et total partiel contradictoire refusés", () => {
  expect(lireCreances({ ...creances, total_a_recevoir: 689.85 }, JOUR)).toBeNull();
  expect(lireCreances({ ...creances, total_complet: false }, JOUR)).toBeNull();
  expect(lireAttentes({ attentes_devis: [], attentes_wct_sans_devis_id: null })).toBeNull();
  const brut: any = copie(ap); delete brut.comptes[0].fournisseur_id;
  expect(lireAP(brut, false, 0)).toBeNull();
});
