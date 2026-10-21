import { runInNewContext } from "node:vm";
import { construireArgumentsVueExecutive, lireVueExecutive } from "./vueExecutive";
import { lireCashLibreDeM8 } from "./cashLibre";
import type { CashLibreDeM8 } from "./cashLibre";
import { reponse } from "../admin/donneesDeTest";
import fixtures from "./fixturesCashLibre.json";

// Modules M8 purs et charges fictives validées par le catalogue M5, voir provenance embarquée.
function lu(brut: unknown): Extract<CashLibreDeM8, { genre: "lu" }> {
  const cash = lireCashLibreDeM8(brut);
  if (!cash || cash.genre !== "lu") throw new Error("le constat natif fictif doit rester lisible");
  return cash;
}
function clone(v: unknown): any { return JSON.parse(JSON.stringify(v)); }
function vue(cash: unknown): any { return { ...clone(reponse("vue_executive").resultat), cash_libre: cash }; }

describe("constat de M5 projeté par M8, jamais recalculé", () => {
  test("absence de constat : manque et outil à lire, aucun nombre inventé", () => {
    expect(fixtures.fictif).toBe(true);
    expect(lireCashLibreDeM8(fixtures.manque)).toEqual({ genre: "manque", source: fixtures.manque.source,
      manque: ["cash_libre"], aLire: fixtures.manque.a_lire });
  });
  test("calculé, provenance projetée et réserves : chaque montant et mention restent verbatim", () => {
    const cash = lu(fixtures.calcule);
    expect(cash).toMatchObject({ source: fixtures.calcule.source, nConstatsRecus: 1,
      constat: { sequence: 1, dateReference: "2026-09-29", statut: "CALCULE", cashLibreCad: "27861.98",
        auPlusCad: null, enDeficit: false, composantes: fixtures.calcule.constat.composantes,
        composantesOmises: null, planchersCad: null, manque: [], reserves: fixtures.calcule.constat.reserves,
        mention: fixtures.calcule.constat.mention, lecture: fixtures.calcule.constat.lecture },
      age: { jours: 1, aujourdHui: "2026-09-30", raison: null },
      nonRepris: fixtures.calcule.non_repris, aLire: fixtures.calcule.a_lire });
    expect(cash.constat).not.toHaveProperty("versionDonnees");
    expect(cash.constat).not.toHaveProperty("evenementId");
  });
  test("précision et zéro d'âge explicitement reçus ne sont ni normalisés ni recalculés", () => {
    const cash = lu(fixtures.precision);
    expect(cash.constat.cashLibreCad).toBe("27861.980");
    expect(cash.constat.composantes?.solde).toBe("37654.330");
    expect(cash.age).toEqual({ jours: 0, aujourdHui: "2026-09-29", raison: null });
  });
  test("déficit natif : valeur négative et booléen conservés, jamais ramenés à zéro", () => {
    expect(lu(fixtures.deficit).constat).toMatchObject({ cashLibreCad: "-7792.35", enDeficit: true });
  });
  test("non calculable : null, manque et repère au plus ne deviennent pas du cash disponible", () => {
    const cash = lu(fixtures.nonCalculable);
    expect(cash.constat).toMatchObject({ statut: "NON_CALCULABLE", cashLibreCad: null, enDeficit: null,
      auPlusCad: "32061.98", composantes: { paies: null }, manque: ["paies : REJ-CASH-PAIE-A-DECLARER"] });
    expect(cash.constat.lecture).toBe(fixtures.nonCalculable.constat.lecture);
    expect(cash.constat.mention).toBe(fixtures.nonCalculable.constat.mention);
    expect(lu(fixtures.soldeAbsent).constat).toMatchObject({ cashLibreCad: null, auPlusCad: null,
      composantes: { solde: null } });
  });
  test("premier jour natif : zéro déclaré distinct des composantes inconnues", () => {
    const cash = lu(fixtures.premierJour);
    expect(cash.constat.composantes).toEqual({ solde: null, taxes_a_remettre: null, paies: null, das: null,
      comptes_a_payer: "0.00", dettes: null, reserves: null });
    expect(cash.constat.cashLibreCad).toBeNull();
    expect(cash.constat.auPlusCad).toBeNull();
    expect(cash.constat.manque).toEqual(fixtures.premierJour.constat.manque);
  });
  test("plancher connu sur composante inconnue : ni montant ni total substitué", () => {
    expect(lu(fixtures.planchers).constat).toMatchObject({ cashLibreCad: null, auPlusCad: "27861.98",
      composantes: { comptes_a_payer: null }, planchersCad: { comptes_a_payer: "459.91" } });
  });
  test.each([fixtures.reduit, fixtures.calculeReduit])("décomposition omise : sept composantes comptées, omissions et mention conservées", (brut) => {
    const cash = lu(brut);
    expect(cash.constat).toMatchObject({ composantes: null, composantesOmises: 7, planchersCad: null,
      cashLibreCad: brut.constat.cash_libre_cad, auPlusCad: brut.constat.au_plus_cad, mention: brut.constat.mention });
    expect(cash.nonRepris).toBe(brut.non_repris);
    expect(cash.nonRepris).toContain("décomposition");
  });
  test.each([fixtures.sansAge, fixtures.dateFuture])("âge absent/incohérent reste null avec sa raison serveur", (brut) => {
    const cash = lu(brut);
    expect(cash.age.jours).toBeNull();
    expect(cash.age.raison).toBe(brut.age.raison);
    expect(cash.age.aujourdHui).toBe("aujourd_hui" in brut.age ? brut.age.aujourd_hui : null);
  });
  test("aucune horloge cliente n'est nécessaire pour conserver l'âge natif", () => {
    const horloge = jest.spyOn(Date, "now").mockImplementation(() => { throw new Error("horloge interdite"); });
    try { expect(lu(fixtures.calcule).age.jours).toBe(1); } finally { horloge.mockRestore(); }
  });
  test("un futur statut demeure inconnu et n'expose aucun montant", () => {
    const inconnu = clone(fixtures.calcule);
    inconnu.constat.statut = "PEUT-ETRE";
    expect(lireCashLibreDeM8(inconnu)).toEqual({ genre: "inconnu", statut: "PEUT-ETRE" });
    expect(lireCashLibreDeM8({ statut: "bientot", cash_libre_cad: "100.00" })).toEqual({ genre: "inconnu", statut: "bientot" });
  });
});

describe("les contradictions rendent le constat illisible, jamais zéro ou succès", () => {
  const cas: [string, (v: any) => void][] = [
    ["cash absent", v => delete v.constat.cash_libre_cad],
    ["cash null sur calculé", v => v.constat.cash_libre_cad = null],
    ["repère sur calculé", v => v.constat.au_plus_cad = "1.00"],
    ["déficit inconnu sur calculé", v => v.constat.en_deficit = null],
    ["booléen déficit sous forme texte", v => v.constat.en_deficit = "false"],
    ["composante inconnue sur calculé", v => v.constat.composantes.paies = null],
    ["manque sur calculé", v => v.constat.manque = ["paies : REJ-X"]],
    ["mention absente", v => delete v.constat.mention],
    ["mention vide", v => v.constat.mention = " "],
    ["lecture absente", v => delete v.constat.lecture],
    ["source absente", v => delete v.source],
    ["omissions absentes", v => delete v.non_repris],
    ["outil à lire absent", v => delete v.a_lire],
    ["compteur absent", v => delete v.n_constats_recus],
    ["compteur nul malgré constat", v => v.n_constats_recus = 0],
    ["compteur fractionnaire", v => v.n_constats_recus = 1.5],
    ["compteur booléen", v => v.n_constats_recus = true],
    ["compteur dépassant entier exact", v => v.n_constats_recus = Number.MAX_SAFE_INTEGER + 1],
    ["séquence nulle", v => v.constat.sequence = 0],
    ["séquence négative", v => v.constat.sequence = -1],
    ["séquence fractionnaire", v => v.constat.sequence = 2.5],
    ["date impossible", v => v.constat.date_reference = "2026-02-30"],
    ["composante absente", v => delete v.constat.composantes.paies],
    ["composante inattendue", v => v.constat.composantes.autre = "0.00"],
    ["décomposition sans compte d'omission", v => delete v.constat.composantes],
    ["décomposition présente et dite omise", v => v.constat.composantes_omises = 7],
    ["plancher sur montant déjà connu", v => v.constat.planchers_cad = { paies: "1.00" }],
    ["âge absent", v => delete v.age],
    ["âge négatif", v => v.age.jours = -1],
    ["âge fractionnaire", v => v.age.jours = 1.5],
    ["âge chiffré sans date appelant", v => delete v.age.aujourd_hui],
    ["âge chiffré et raison d'absence", v => v.age.raison = "illisible"],
    ["réserves doublonnées", v => v.constat.reserves.push(v.constat.reserves[0])],
  ];
  test.each(cas)("%s", (_nom, corrompre) => {
    const brut = clone(fixtures.calcule); corrompre(brut);
    expect(lireCashLibreDeM8(brut)).toBeNull();
    expect(lireVueExecutive(vue(brut))).toBeNull();
  });
  test("un ancien faux lu sans constat ne devient pas un statut inconnu", () => {
    expect(lireCashLibreDeM8({ source: "M5", statut: "lu", montant: "14106.32" })).toBeNull();
  });
  test("montant au-delà de la borne du catalogue M5", () => {
    const brut = clone(fixtures.calcule); brut.constat.cash_libre_cad = "1".repeat(25);
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test.each([
    ["réserves hors borne", (v: any) => v.constat.reserves = Array.from({ length: 17 }, (_, n) => `REJ-FICTIF-${n}`)],
    ["manques hors borne", (v: any) => v.constat.manque = Array.from({ length: 33 }, (_, n) => `paies : REJ-FICTIF-${n}`)],
    ["manque doublonné", (v: any) => v.constat.manque.push(v.constat.manque[0])],
    ["réserve sans code", (v: any) => v.constat.reserves = ["peut-être"]],
  ] as [string, (v: any) => void][])("%s : aucune liste excédentaire ou code deviné", (_nom, corrompre) => {
    const brut = clone(fixtures.nonCalculable); corrompre(brut);
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test.each(["NaN", "Infinity", "-Infinity", "1e3", "+2.00", "1,23", " 1.00", 1.23, NaN, Infinity, -Infinity])("montant illisible %s", (montant) => {
    const brut = clone(fixtures.calcule); brut.constat.cash_libre_cad = montant;
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test.each([
    ["cash sur non calculable", (v: any) => v.constat.cash_libre_cad = "1.00"],
    ["déficit sur non calculable", (v: any) => v.constat.en_deficit = false],
    ["manque vide sur non calculable", (v: any) => v.constat.manque = []],
    ["aucune composante inconnue", (v: any) => v.constat.composantes.paies = "4200.00"],
    ["repère absent malgré solde connu", (v: any) => v.constat.au_plus_cad = null],
  ] as [string, (v: any) => void][])("%s", (_nom, corrompre) => {
    const brut = clone(fixtures.nonCalculable); corrompre(brut);
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test("repère chiffré malgré solde inconnu", () => {
    const brut = clone(fixtures.soldeAbsent); brut.constat.au_plus_cad = "1.00";
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test.each([0, 6, 8, null, "7", 7.5, true])("compte de décomposition omise incohérent %s", (nombre) => {
    const brut = clone(fixtures.reduit); brut.constat.composantes_omises = nombre;
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test("un plancher ne peut survivre à la décomposition omise", () => {
    const brut = clone(fixtures.reduit); brut.constat.planchers_cad = { paies: "1.00" };
    expect(lireCashLibreDeM8(brut)).toBeNull();
  });
});

describe("données JSON propres avant toute lecture", () => {
  test("un getter profond n'est jamais exécuté", () => {
    const brut = clone(fixtures.calcule), getter = jest.fn(() => "27861.98");
    Object.defineProperty(brut.constat, "cash_libre_cad", { enumerable: true, get: getter });
    expect(lireCashLibreDeM8(brut)).toBeNull();
    expect(lireVueExecutive(vue(brut))).toBeNull();
    expect(getter).not.toHaveBeenCalled();
  });
  test("un getter sur une autre section n'est pas exécuté non plus", () => {
    const brut = vue(fixtures.calcule), getter = jest.fn(() => []);
    Object.defineProperty(brut.entonnoir, "mesures", { enumerable: true, get: getter });
    expect(lireVueExecutive(brut)).toBeNull();
    expect(getter).not.toHaveBeenCalled();
  });
  test("objet hérité/classe, symboles, cycle et liste creuse sont refusés", () => {
    const herite = Object.assign(Object.create({ n_constats_recus: 1 }), fixtures.calcule);
    expect(lireCashLibreDeM8(herite)).toBeNull();
    const symbole = clone(fixtures.calcule); symbole[Symbol("cache")] = "secret";
    const cycle = clone(fixtures.calcule); cycle.constat.cycle = cycle;
    const creux = clone(fixtures.calcule); delete creux.constat.reserves[0];
    for (const brut of [symbole, cycle, creux, new Date()]) expect(lireCashLibreDeM8(brut)).toBeNull();
  });
  test("objet JSON issu d'un autre realm et objets à prototype null sont lisibles", () => {
    const autreRealm = runInNewContext("JSON.parse(texte)", { texte: JSON.stringify(fixtures.calcule) });
    expect(lu(autreRealm).constat.cashLibreCad).toBe("27861.98");
    expect(lu(Object.assign(Object.create(null), fixtures.calcule)).constat.cashLibreCad).toBe("27861.98");
  });
  test("le modèle est détaché du JSON reçu", () => {
    const brut = clone(fixtures.calcule), cash = lu(brut);
    brut.constat.composantes.solde = "0.00";
    brut.constat.reserves.length = 0;
    expect(cash.constat.composantes?.solde).toBe("37654.33");
    expect(cash.constat.reserves).toEqual(fixtures.calcule.constat.reserves);
  });
});

describe("aujourd_hui additif et explicite, aucun jour deviné", () => {
  test("sans argument, compatibilité v1 ; jour valide transmis à l'identique", () => {
    expect(construireArgumentsVueExecutive()).toEqual({});
    for (const jour of ["2026-09-30", "2024-02-29", "2000-02-29", "0001-01-01"])
      expect(construireArgumentsVueExecutive(jour)).toEqual({ aujourd_hui: jour });
  });
  test.each(["2026-02-29", "1900-02-29", "0000-01-01", "2026-04-31", "2026-13-01", "2026-00-01", "2026-01-00", "2026-1-01", "2026-01-01T00:00:00Z", "", " 2026-01-01"])("jour illisible refusé %s", (jour) => {
    expect(() => construireArgumentsVueExecutive(jour)).toThrow("aujourd_hui doit être une date AAAA-MM-JJ valide");
  });
});
