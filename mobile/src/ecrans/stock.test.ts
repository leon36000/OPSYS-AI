import { presenterDisponibilite, presenterDigest } from "./stock";
import { disponibiliteFictive, digestFictif, digestReapprovisionnementIndetermineProduitM6Fictif } from "../m6/fixturesStock";

const digestIndetermineFictif = digestReapprovisionnementIndetermineProduitM6Fictif;

test("quantités natives sans unité inventée ni correction du négatif", () => {
  const brut = JSON.parse(JSON.stringify(disponibiliteFictive));
  brut.articles[0].disponible = "-1234.5000";
  const v = presenterDisponibilite(brut, "fr-CA");
  expect(v.articles[0].lignes).toContainEqual({ cle: "admin.stock.disponible", params: { quantite: "-1\u00a0234,5000" } });
  expect(v.articles[0].lignes.some(m => m.cle === "admin.stock.uniteInconnue")).toBe(true);
  expect(v.articles[0].lignes.some(m => m.cle === "admin.stock.negatif")).toBe(true);
  expect(v.lignes.some(m => m.cle === "admin.stock.physiqueNonFourni")).toBe(true);
});

test("troncatures métier séparées, aucun total ni curseur fabriqué", () => {
  const v = presenterDisponibilite({ ...disponibiliteFictive, tronque: true, reservations_tronquees: true }, "en-CA");
  expect(v.lignes.some(m => m.cle === "admin.stock.articlesTronques")).toBe(true);
  expect(v.lignes.some(m => m.cle === "admin.stock.reservationsTronquees")).toBe(true);
  expect(v.lignes.some(m => m.cle === "admin.stock.manquesHorsSelection")).toBe(true);
});

test("digest historique et calcul sans seuils ne promettent aucun besoin d'achat", () => {
  const v = presenterDigest(digestFictif, "fr-CA");
  expect(v.lignes.some(m => m.cle === "admin.stock.historique")).toBe(true);
  expect(v.lignes.some(m => m.cle === "admin.stock.seuilsNonFournis")).toBe(true);
  expect(v.lignes.some(m => m.cle === "admin.stock.reapprovisionnementsIndeterminesNonFournis")).toBe(true);
  expect(v.variances[0].lignes.some(m => m.cle === "admin.stock.uniteInconnue")).toBe(true);
  expect(v.reapprovisionnementsIndetermines).toEqual([]);
});

test("digest indique chaque paire indéterminée sans inventer un réapprovisionnement", () => {
  const v = presenterDigest(digestIndetermineFictif, "en-CA");
  expect(v.lignes).toContainEqual({ cle: "admin.stock.reapprovisionnementsIndetermines", params: { nombre: 1 } });
  expect(v.reapprovisionnementsIndetermines).toHaveLength(1);
  expect(v.reapprovisionnementsIndetermines[0].titre).toBe("MAT-MOBILE-FICTIF");
  expect(v.reapprovisionnementsIndetermines[0].lignes).toContainEqual({
    cle: "admin.stock.chantier", params: { valeur: "CH-MOBILE-FICTIF" },
  });
  expect(v.reapprovisionnementsIndetermines[0].lignes).toContainEqual({
    cle: "admin.stock.reapprovisionnementIndetermine",
  });
  expect(v.reapprovisionnementsIndetermines[0].detail).toEqual([]);
  expect(v.lignes.some(m => m.cle === "admin.stock.seuilsNonFournis")).toBe(true);
});

test("un constat sans écart reste présent ; il n'est pas filtré comme insignifiant", () => {
  const brut = JSON.parse(JSON.stringify(digestFictif));
  brut.variances_significatives[0].ecart = 0;
  brut.variances_significatives[0].verdict_variance = "AUCUN_ECART";
  const v = presenterDigest(brut, "en-CA");
  expect(v.variances).toHaveLength(brut.nb_variances_stock);
  expect(v.variances[0].lignes).toContainEqual({ cle: "admin.stock.ecart", params: { quantite: "0" } });
  expect(v.variances[0].lignes.some(m => m.cle === "admin.stock.verdicts.AUCUN_ECART")).toBe(true);
});
