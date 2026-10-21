import fixture from "../m8/fixturesCashLibre.json";
import { lireCashLibreDeM8 } from "../m8/cashLibre";
import type { CashLibreDeM8 } from "../m8/vueExecutive";
import type { Message } from "./adminCommun";
import { presenterCashConstatM8 } from "./cashConstatM8";

/** Charges fictives produites par le module pur M8, à partir des constats M5 validés par son catalogue.
 * Les cas capturesHttp viennent aussi du vrai HTTP MCP natif ; provenance SHA séparée dans la fixture.
 * Jest les relit ici : aucun serveur ni téléphone réel n'est exécuté par ces tests de présentation. */
const DECALAGE = -240;
const m = (cle: string, params?: Message["params"]): Message =>
  params === undefined ? { cle: `admin.cashConstatM8.${cle}` } : { cle: `admin.cashConstatM8.${cle}`, params };
function cash(nom: keyof typeof fixture): CashLibreDeM8 {
  const lu = lireCashLibreDeM8(fixture[nom]);
  if (!lu) throw new Error(`La capture fictive native ${nom} doit être lisible`);
  return lu;
}
function lu(nom: keyof typeof fixture = "calcule"): Extract<CashLibreDeM8, { genre: "lu" }> {
  const valeur = cash(nom);
  if (valeur.genre !== "lu") throw new Error("Un constat lu est attendu");
  return valeur;
}

test("le constat calculé garde sa source, son rang, sa date civile et le jour original de son âge", () => {
  const c = lu(), avant = JSON.stringify(c);
  const vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(fixture.fictif).toBe(true);
  expect(vue.genre).toBe("lu");
  expect(vue.lignes).toEqual([
    m("source", { source: "M5 (m5.cash_libre_constate)" }), m("nConstats", { nombre: 1 }),
    m("constat", { sequence: 1, date: "2026-09-29" }), m("age", { jours: 1, jour: "2026-09-30" }),
    m("CALCULE"), m("montant", { montant: "27 861,98 $" }), m("renvoiTresorerie"),
  ]);
  expect(vue.composantes.map((v) => v.id)).toEqual([
    "solde", "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves",
  ]);
  expect(vue.composantes[0]).toEqual({ id: "solde", libelle: { cle: "admin.chiffres.composantes.solde" },
    valeur: { cle: "admin.chiffres.composante.montant", params: { montant: "37 654,33 $" } }, plancher: null });
  expect(vue.reserves).toEqual([m("reserve", { code: "REJ-AP-UNITE-PRIX-NON-CONFIRMEE" })]);
  expect(vue.manques).toEqual([]);
  expect(vue.lecture).toBe(c.constat.lecture);
  expect(vue.mention).toBe(c.constat.mention);
  expect(vue.nonRepris).toBe(c.nonRepris);
  expect(vue.textes).toEqual([c.constat.lecture, c.constat.mention, c.nonRepris]);
  expect(JSON.stringify(c)).toBe(avant);
});

test("les chiffres du serveur conservent toute leur précision dans les deux langues, sans arrondi", () => {
  const c = lu("precision");
  const fr = presenterCashConstatM8(c, "fr-CA", DECALAGE), en = presenterCashConstatM8(c, "en-CA", 0);
  expect(fr.lignes).toContainEqual(m("montant", { montant: "27 861,980 $" }));
  expect(en.lignes).toContainEqual(m("montant", { montant: "$27,861.980" }));
  expect(fr.composantes[0].valeur.params?.montant).toBe("37 654,330 $");
  expect(en.composantes[0].valeur.params?.montant).toBe("$37,654.330");
  expect(fr.lignes).toContainEqual(m("age", { jours: 0, jour: "2026-09-29" }));
});

test("un constat non calculable n'a aucun cash : au plus reste un repère distinct de la composante absente", () => {
  const c = lu("nonCalculable"), vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.lignes).toContainEqual(m("NON_CALCULABLE"));
  expect(vue.lignes).toContainEqual(m("auPlus", { montant: "32 061,98 $" }));
  expect(vue.lignes.some((v) => v.cle === m("montant").cle)).toBe(false);
  expect(vue.lignes).not.toContainEqual(m("deficit"));
  expect(vue.composantes.find((v) => v.id === "paies")?.valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
  expect(vue.manques).toEqual([m("manqueLigne", { manque: "paies : REJ-CASH-PAIE-A-DECLARER" })]);
  expect(vue.lecture).toContain("PAS de l'argent disponible");
  expect(JSON.stringify(vue.composantes.find((v) => v.id === "paies"))).not.toContain("0,00");
});

test("un plancher publié accompagne une composante inconnue, sans se substituer à son montant", () => {
  const vue = presenterCashConstatM8(cash("planchers"), "fr-CA", DECALAGE);
  expect(vue.composantes.find((v) => v.id === "comptes_a_payer")).toEqual({
    id: "comptes_a_payer", libelle: { cle: "admin.chiffres.composantes.comptes_a_payer" },
    valeur: { cle: "admin.chiffres.composante.nonCalculable" },
    plancher: { cle: "admin.chiffres.composante.plancher", params: { montant: "459,91 $" } },
  });
});

test("le solde absent ne devient ni un zéro ni un repère au plus", () => {
  const vue = presenterCashConstatM8(cash("soldeAbsent"), "fr-CA", DECALAGE);
  expect(vue.composantes[0].valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
  expect(vue.lignes.some((v) => v.cle === m("auPlus").cle || v.cle === m("montant").cle)).toBe(false);
  expect(vue.manques).toContainEqual(m("manqueLigne", { manque: "solde : REJ-CASH-SOLDE-ABSENT" }));
});

test("au premier jour fictif, le zéro déclaré des comptes à payer reste distinct des composantes null", () => {
  const vue = presenterCashConstatM8(cash("premierJour"), "fr-CA", DECALAGE);
  expect(vue.composantes.find((v) => v.id === "comptes_a_payer")?.valeur).toEqual({
    cle: "admin.chiffres.composante.montant", params: { montant: "0,00 $" },
  });
  expect(vue.composantes.find((v) => v.id === "solde")?.valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
  expect(vue.lignes).toContainEqual(m("NON_CALCULABLE"));
  expect(vue.lignes).toContainEqual(m("age", { jours: 0, jour: "2026-09-29" }));
  expect(vue.lignes.some((v) => v.cle === m("montant").cle || v.cle === m("auPlus").cle)).toBe(false);
});

test.each(["reduit", "calculeReduit"] as const)("%s : la décomposition omise est comptée, jamais reconstruite", (nom) => {
  const c = lu(nom), vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.lignes).toContainEqual(m("composantesOmises", { nombre: 7 }));
  expect(vue.composantes).toEqual([]);
  expect(vue.nonRepris).toBe("décomposition, source et fraîcheur de chaque composante, hypothèses");
  expect(vue.mention).toBe(c.constat.mention);
  expect(vue.reserves).toHaveLength(1);
  expect(vue.lecture).toBe(c.constat.lecture);
});

test("le déficit est uniquement le drapeau déclaré par M5, jamais inféré du signe d'un montant", () => {
  const c = lu("deficit"), vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.lignes).toContainEqual(m("deficit"));
  expect(vue.lignes).toContainEqual(m("montant", { montant: "-7 792,35 $" }));
  const sansDrapeau = presenterCashConstatM8({ ...c, constat: { ...c.constat, enDeficit: false } }, "fr-CA", DECALAGE);
  expect(sansDrapeau.lignes).not.toContainEqual(m("deficit"));
});

test.each(["sansAge", "dateFuture"] as const)("%s : âge nul garde sa raison native sans devenir zéro", (nom) => {
  const c = lu(nom), vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.lignes).toContainEqual(m("ageInconnu", { raison: c.age.raison! }));
  expect(vue.lignes.some((v) => v.cle === m("age").cle)).toBe(false);
  if (nom === "dateFuture") expect(vue.lignes).toContainEqual(m("jourAge", { jour: "2026-09-28" }));
  else expect(vue.lignes.some((v) => v.cle === m("jourAge").cle)).toBe(false);
});

test("manque : source et manque explicites, renvoi neutre vers Trésorerie sans outil ou action constater", () => {
  const vue = presenterCashConstatM8(cash("manque"), "fr-CA", DECALAGE);
  expect(vue.genre).toBe("manque");
  expect(vue.lignes).toEqual([m("source", { source: "M5 (m5.cash_libre_constate)" }), m("manque"), m("renvoiTresorerie")]);
  expect(vue.manques).toEqual([m("manqueLigne", { manque: "cash_libre" })]);
  expect(vue.composantes).toEqual([]);
  expect(vue.mention).toBeNull();
  expect(JSON.stringify(vue)).not.toContain("m5_constater_cash_libre");
  expect(JSON.stringify(vue)).not.toContain("m5_etat_tresorerie");
});

test("statut futur de section ou constat : inconnu explicite, aucun chiffre financier conservé", () => {
  for (const brut of [{ ...fixture.calcule, statut: "ESTIME" },
    { ...fixture.calcule, constat: { ...fixture.calcule.constat, statut: "ESTIME" } }]) {
    const c = lireCashLibreDeM8(brut);
    if (!c) throw new Error("Le statut futur est dit inconnu par le lecteur");
    const vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
    expect(vue.genre).toBe("inconnu");
    expect(vue.lignes).toEqual([m("inconnu", { statut: "ESTIME" }), m("renvoiTresorerie")]);
    expect(vue.composantes).toEqual([]);
    expect(vue.textes).toEqual([]);
    expect(JSON.stringify(vue)).not.toContain("27861");
  }
});

test("tous les textes de chemins/commandes sont masqués sans affecter le DTO source", () => {
  const c = lu("nonCalculable"), avant = JSON.stringify(c);
  const vue = presenterCashConstatM8({ ...c, source: "/srv/opsys/finance.json", nonRepris: "opsys-metier finances lire",
    aLire: "opsys-metier constater --depuis /srv/secret", age: { ...c.age, jours: null, raison: "$HOME" },
    constat: { ...c.constat, lecture: "Cash libre : 32061.98 $ ; /srv/secret", manque: ["paies : REJ-CASH-PAIE-A-DECLARER", "/srv/paies"],
      reserves: ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE", "opsys-metier payer"] } }, "fr-CA", DECALAGE);
  expect(vue.lignes).toContainEqual(m("sourceMasquee"));
  expect(vue.lignes).toContainEqual(m("ageRaisonMasquee"));
  expect(vue.lignes).toContainEqual(m("lectureMasquee"));
  expect(vue.lignes).toContainEqual(m("nonReprisMasque"));
  expect(vue.lecture).toBeNull();
  expect(vue.nonRepris).toBeNull();
  expect(vue.manques).toEqual([m("manqueLigne", { manque: "paies : REJ-CASH-PAIE-A-DECLARER" }), m("manqueMasque")]);
  expect(vue.reserves).toEqual([m("reserve", { code: "REJ-AP-UNITE-PRIX-NON-CONFIRMEE" }), m("reserveMasquee")]);
  const texte = JSON.stringify(vue);
  expect(texte).not.toMatch(/\/srv|opsys-metier|\$HOME/);
  expect(JSON.stringify(c)).toBe(avant);
});

test.each(["Cash libre : 27861.98 $ ; $(id)", "Cash libre : 27861.98 $HOME", "Cash libre : 27861.98 $ ; `id`",
  "Cash libre : 27861.98 $ ; C:\\paies\\secret", "Cash libre : 27861.98 $ ; entreprise.yaml"])(
  "le marqueur monétaire sûr n'autorise pas une commande ou un chemin voisin : %s", (lecture) => {
    const c = lu(), vue = presenterCashConstatM8({ ...c, constat: { ...c.constat, lecture } }, "fr-CA", DECALAGE);
    expect(vue.lecture).toBeNull();
    expect(vue.lignes).toContainEqual(m("lectureMasquee"));
  },
);

test("la mention canonique avec Nathan/CPA/fiscaliste reste intacte ; une mention unsafe cache les chiffres", () => {
  const c = lu(), vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.mention).toBe("Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.");
  const unsafe = presenterCashConstatM8({ ...c, constat: { ...c.constat, mention: "/srv/mention.md" } }, "fr-CA", DECALAGE);
  expect(unsafe.mention).toBeNull();
  expect(unsafe.lignes).toContainEqual(m("mentionMasquee"));
  expect(unsafe.composantes).toEqual([]);
  expect(unsafe.lecture).toBeNull();
  expect(unsafe.lignes.some((v) => v.cle === m("montant").cle || v.cle === m("auPlus").cle)).toBe(false);
  expect(JSON.stringify(unsafe)).not.toContain("27861");
});

test("un statut inconnu qui cite une commande est masqué sans zéro ni chiffres", () => {
  const vue = presenterCashConstatM8({ genre: "inconnu", statut: "opsys-metier lire /srv/secret" }, "fr-CA", DECALAGE);
  expect(vue.lignes).toEqual([m("statutMasque"), m("renvoiTresorerie")]);
  expect(JSON.stringify(vue)).not.toMatch(/opsys-metier|\/srv|montant|27861/);
});

test.each([
  ["aucun-constat", "manque"], ["premier-jour", "lu"], ["calcule", "lu"], ["non-calculable", "lu"],
  ["plancher", "lu"], ["age-inconnu", "lu"], ["reference-future", "lu"], ["composantes-omises", "lu"],
] as const)("capture HTTP MCP fictive %s : texte/mention/date natifs conservés sans nouveau calcul", (nom, genre) => {
  const capture = fixture.capturesHttp.lectures[nom], brut = capture.enveloppe.resultat.cash_libre;
  const c = lireCashLibreDeM8(brut);
  if (!c) throw new Error(`La capture HTTP fictive ${nom} doit être lisible`);
  const vue = presenterCashConstatM8(c, "fr-CA", DECALAGE);
  expect(vue.genre).toBe(genre);
  expect(vue.lignes).toContainEqual(m("source", { source: brut.source }));
  if (c.genre === "lu") {
    expect(vue.mention).toBe(c.constat.mention);
    expect(vue.lecture).toBe(c.constat.lecture);
    expect(vue.nonRepris).toBe(c.nonRepris);
    expect(vue.lignes).toContainEqual(m("constat", { sequence: c.constat.sequence, date: c.constat.dateReference }));
    if (c.age.jours === null) {
      expect(vue.lignes).toContainEqual(m("ageInconnu", { raison: c.age.raison! }));
      expect(vue.lignes.some((v) => v.cle === m("age").cle)).toBe(false);
    }
    if (nom === "composantes-omises") {
      expect(vue.composantes).toEqual([]);
      expect(vue.lignes).toContainEqual(m("composantesOmises", { nombre: 7 }));
    }
    if (c.constat.statut === "NON_CALCULABLE") {
      expect(vue.lignes).toContainEqual(m("NON_CALCULABLE"));
      expect(vue.lignes.some((v) => v.cle === m("montant").cle)).toBe(false);
      expect(vue.manques.length).toBeGreaterThan(0);
    }
  }
  expect(JSON.stringify(vue)).not.toContain("m5_constater_cash_libre");
});
