import * as Contrat from "./contexteMateriaux";
// Vecteurs de conception fictifs en RAM ; pas des captures backend/HTTP.
const FICTIF = true;
function api(): typeof Contrat { return Contrat; }
function args(a: typeof Contrat) { return a.construireArgumentsContexteMateriaux("INTERVENTION-FICTIVE", "WCT-FICTIF", 0, 8); }
function dtoFictif() {
  return { wct: { wct_id: "WCT-FICTIF", intervention_id: "INTERVENTION-FICTIVE", devis_id: "DEVIS-FICTIF", horodatage_completion: "2026-10-08T13:00:00-04:00", hash_maillon: "a".repeat(64), reference_bus: { type: "m4.travaux_termines", evenement_id: "WCT-FICTIF" } },
    chantier: { chantier_id: "INTERVENTION-FICTIVE", origine: "intervention_employee" },
    prevu: { statut: "provisoire_estimation_m3", source: { registre: "besoins_prevus", rang: 0, empreinte_snapshot: "b".repeat(64), estimation_id: "c".repeat(64), rang_m3: 2, bareme_version: "BAREME-FICTIF", horodatage: null as string | null, reference_m3: { type: "m3.besoins_materiaux", evenement_id: "EVENEMENT-M3-FICTIF" } } },
    lignes: [{ position_source: 0, materiau_id: "MAT-FICTIF", unite: "pi", quantite_estimee: "0001.2500", origine_quantite: "texte_m3_verifie" }],
    pagination: { decalage: 0, limite: 8, affichees: 1, total: 1, suivant: null as number | null, reste: 0, courante: true },
    manques: ["horodatage_prevu_absent"], couverture: { objet: "contexte_et_prevu_du_wct", quantite_reelle: "non_renseignee", pages: "courantes", plafond_lignes: 10000 }, borne_caracteres: 5400, taille_caracteres: 1900 };
}
const direct = (resultat: unknown) => ({ ok: true, resultat });
type DTO = ReturnType<typeof dtoFictif>;
const erreurs: Array<readonly [string, (v: DTO) => void]> = [
  ["WCT autre", v => { v.wct.wct_id = "WCT-AUTRE"; }], ["intervention autre", v => { v.wct.intervention_id = "AUTRE"; }],
  ["bus autre", v => { v.wct.reference_bus.evenement_id = "AUTRE"; }], ["typebus autre", v => { v.wct.reference_bus.type = "m3.devis_accepte"; }],
  ["hash invalide", v => { v.wct.hash_maillon = "A".repeat(64); }], ["date impossible", v => { v.wct.horodatage_completion = "2026-02-30T00:00:00Z"; }],
  ["date sans fuseau", v => { v.wct.horodatage_completion = "2026-10-08T00:00:00"; }], ["personne divulguée", v => { Reflect.set(v.wct, "technicien_id", "FICTIF"); }],
  ["fallback employé autre", v => { v.chantier.chantier_id = "CHANTIER-AUTRE"; }], ["origine inconnue", v => { v.chantier.origine = "route"; }],
  ["statut inconnu", v => { v.prevu.statut = "vide"; }], ["source absent malgré provisoire", v => { Reflect.set(v.prevu, "source", null); }],
  ["registre source autre", v => { v.prevu.source.registre = "principal"; }], ["rang source négatif", v => { v.prevu.source.rang = -1; }],
  ["rang source unsafe", v => { v.prevu.source.rang = Number.MAX_SAFE_INTEGER + 1; }], ["empreinte source fausse", v => { v.prevu.source.empreinte_snapshot = "h"; }],
  ["estimation source nulle", v => { Reflect.set(v.prevu.source, "estimation_id", null); }], ["rang M3 nonentier", v => { v.prevu.source.rang_m3 = 1.5; }],
  ["bareme vide", v => { v.prevu.source.bareme_version = ""; }], ["ref M3 mauvais type", v => { v.prevu.source.reference_m3.type = "m3.devis_accepte"; }],
  ["date prévue empruntée complétion", v => { v.prevu.source.horodatage = v.wct.horodatage_completion; v.manques = []; }],
  ["position autre", v => { v.lignes[0].position_source = 1; }], ["position unsafe", v => { v.lignes[0].position_source = Number.MAX_SAFE_INTEGER + 1; }],
  ["unité absente", v => { v.lignes[0].unite = ""; }], ["unité contrôle", v => { v.lignes[0].unite += "\n"; }],
  ["matière257", v => { v.lignes[0].materiau_id = "x".repeat(257); }], ["réel inventé", v => { Reflect.set(v.lignes[0], "quantite_reelle", "1.25"); }],
  ["prix inventé", v => { Reflect.set(v.lignes[0], "prix", "10"); }], ["origine quantité inconnue", v => { v.lignes[0].origine_quantite = "calculee"; }],
  ["page départ autre", v => { v.pagination.decalage = 1; }], ["page limite autre", v => { v.pagination.limite = 7; }], ["affichées autre", v => { v.pagination.affichees = 0; }],
  ["total insuf", v => { v.pagination.total = 0; }], ["total10001", v => { v.pagination.total = 10001; v.pagination.reste = 10000; v.pagination.suivant = 1; }],
  ["suite fausse", v => { v.pagination.suivant = 1; }], ["reste faux", v => { v.pagination.reste = 1; }], ["noncourante", v => { v.pagination.courante = false; }],
  ["manque inconnu", v => { v.manques.push("prix_absent"); }], ["manque doublon", v => { v.manques.push(v.manques[0]); }],
  ["manque omis", v => { v.manques = []; }], ["faux prévu absent", v => { v.manques.push("prevu_absent"); }],
  ["couverture autre", v => { v.couverture.objet = "stock_global"; }], ["réel prétendu", v => { v.couverture.quantite_reelle = "zero"; }],
  ["plafond autre", v => { v.couverture.plafond_lignes = 9000; }], ["borne autre", v => { v.borne_caracteres = 6000; }],
  ["taille nulle", v => { v.taille_caracteres = 0; }], ["taille horsborne", v => { v.taille_caracteres = 5401; }],
];
describe("M6 contexte — vecteurs RAM fictifs", () => {
  test("API requête quatre champs required sans defaults", () => {
    expect(FICTIF).toBe(true); const a = api(); expect(a.OUTIL_CONTEXTE_MATERIAUX).toBe("m6_lire_contexte_materiaux_appareil");
    expect(args(a)).toEqual({ intervention_id: "INTERVENTION-FICTIVE", wct_id: "WCT-FICTIF", decalage: 0, limite: 8 });
    expect(() => Reflect.apply(a.construireArgumentsContexteMateriaux, null, ["I", "W"])).toThrow();
  });
  test.each(["", " ", "\n", "x".repeat(257), "\ud800"])("ID fermé %j", v => { const a = api(); expect(() => a.construireArgumentsContexteMateriaux(v, "W", 0, 8)).toThrow(); });
  test.each([-1, 0.5, 10001, NaN, Infinity])("offset %s fermé", v => { const a = api(); expect(() => a.construireArgumentsContexteMateriaux("I", "W", v, 8)).toThrow(); });
  test.each([0, 9, 0.5, NaN, Infinity])("limite %s fermée", v => { const a = api(); expect(() => a.construireArgumentsContexteMateriaux("I", "W", 0, v)).toThrow(); });
  test("DIRECT natif, zéros M3 conservés, quantité réelle absente", () => { const a = api(), v = dtoFictif(); expect(a.lireContexteMateriaux(direct(v), args(a))).toEqual({ ok: true, value: v }); });
  test.each(erreurs)("données fermées : %s", (_nom, muter) => { const a = api(), v = dtoFictif(); muter(v); expect(a.lireContexteMateriaux(direct(v), args(a))).toMatchObject({ ok: false, code: "reponse_illisible" }); });
  test.each(["0", "0.000", "-1", "+1", "1e3", "1.", ".1", "NaN", "Infinity", "١", "1\n", " 1"])("texte quantité non natif %s", texte => { const a = api(), v = dtoFictif(); v.lignes[0].quantite_estimee = texte; expect(a.lireContexteMateriaux(direct(v), args(a))).toMatchObject({ ok: false, code: "reponse_illisible" }); });
  test.each([["1",1],["0001.2500",1.25],["0.0000001000",1e-7],["9007199254740991",Number.MAX_SAFE_INTEGER]])("conversion exacte de %s", (texte, n) => { const a = api(); expect(a.estimationEnNombreExact(String(texte))).toBe(n); });
  test.each(["9007199254740992", "9007199254740993", "100000000000000000000", "0.100000000000000000001", "1".repeat(400), "1e3", "-1", "0", "NaN"])("estimation %s non importable", texte => { const a = api(); expect(a.estimationEnNombreExact(texte)).toBeNull(); });
  test("getters, prototypes, symbols et cycles fermés sans getter lu", () => {
    const a = api(); let lus = 0; const v = dtoFictif(); Object.defineProperty(v, "wct", { get: () => { lus++; return {}; } });
    const proto = Object.create({ wct: dtoFictif().wct }); Object.assign(proto, dtoFictif());
    const s = dtoFictif(); Reflect.set(s, Symbol("fictif"), true); const c = dtoFictif(); Reflect.set(c, "cycle", c);
    for (const r of [v, proto, s, c]) expect(a.lireContexteMateriaux(direct(r), args(a))).toMatchObject({ ok: false, code: "reponse_illisible" }); expect(lus).toBe(0);
  });
  test("refus nominal jamais transformé en succès/couple/troncature fallback", () => {
    const a = api(), refus = { ok: true, resultat: { accepte: false, verdict: { code: "REJ-M6-CONTEXTE-WCT-INCONNU", detail: "WCT fictif inconnu" } }, tronque: true };
    expect(a.lireContexteMateriaux(refus, args(a))).toMatchObject({ ok: false, code: "REJ-M6-CONTEXTE-WCT-INCONNU" });
    expect(a.lireContexteMateriaux({ ok: true, resultat: { accepte: true, resultat: dtoFictif() } }, args(a))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
});


describe("M6 contexte — absence, source et page courante fictives", () => {
  test("prévu absent admin et prévu présent vide restent distincts", () => {
    const v = dtoFictif();
    const absent = { ...v, chantier: { chantier_id: null, origine: "absent_admin" }, prevu: { statut: "absent", source: null }, lignes: [],
      pagination: { ...v.pagination, affichees: 0, total: 0 }, manques: ["prevu_absent", "chantier_source_absent"] };
    const vide = { ...v, lignes: [], pagination: { ...v.pagination, affichees: 0, total: 0 } };
    expect(Contrat.lireContexteMateriaux(direct(absent), args(Contrat))).toEqual({ ok: true, value: absent });
    expect(Contrat.lireContexteMateriaux(direct(vide), args(Contrat))).toEqual({ ok: true, value: vide });
  });
  test("définitif garde sa date propre et écarte les métadonnées provisoires", () => {
    const v = dtoFictif(), source = { ...v.prevu.source, estimation_id: null, rang_m3: null, bareme_version: null,
      reference_m3: { type: "m3.devis_accepte", evenement_id: "DEVIS-ACCEPTE-FICTIF" }, horodatage: "2026-10-01T11:30:00Z" };
    const d = { ...v, chantier: { chantier_id: "CHANTIER-FICTIF", origine: "prevu_m6" }, prevu: { statut: "definitif", source }, manques: [] };
    expect(Contrat.lireContexteMateriaux(direct(d), args(Contrat))).toEqual({ ok: true, value: d });
    expect(Contrat.lireContexteMateriaux(direct({ ...d, prevu: { statut: "definitif", source: { ...source, estimation_id: v.prevu.source.estimation_id } } }), args(Contrat))).toMatchObject({ ok: false });
  });
  test("legacy sans référence M3 ne prétend pas au texte M3 vérifié", () => {
    const v = dtoFictif(), legacy = { ...v, prevu: { ...v.prevu, source: { ...v.prevu.source, reference_m3: null } },
      lignes: [{ ...v.lignes[0], origine_quantite: "nombre_m6_persiste" }], manques: ["horodatage_prevu_absent", "provenance_m3_absente"] };
    expect(Contrat.lireContexteMateriaux(direct(legacy), args(Contrat))).toEqual({ ok: true, value: legacy });
    expect(Contrat.lireContexteMateriaux(direct({ ...legacy, lignes: v.lignes }), args(Contrat))).toMatchObject({ ok: false });
  });
  test("page suivante conserve les positions natives", () => {
    const a = Contrat.construireArgumentsContexteMateriaux("INTERVENTION-FICTIVE", "WCT-FICTIF", 2, 1), v = dtoFictif();
    const p = { ...v, lignes: [{ ...v.lignes[0], position_source: 2 }], pagination: { ...v.pagination, decalage: 2, limite: 1, total: 5, reste: 2, suivant: 3 } };
    expect(Contrat.lireContexteMateriaux(direct(p), a)).toEqual({ ok: true, value: p });
    expect(Contrat.lireContexteMateriaux(direct(p), args(Contrat))).toMatchObject({ ok: false });
  });
  test("offset au-delà du total conserve une page vide et la source présente", () => {
    const a = Contrat.construireArgumentsContexteMateriaux("INTERVENTION-FICTIVE", "WCT-FICTIF", 10000, 8), v = dtoFictif();
    const p = { ...v, lignes: [], pagination: { ...v.pagination, decalage: 10000, affichees: 0 } };
    expect(Contrat.lireContexteMateriaux(direct(p), a)).toEqual({ ok: true, value: p });
  });
  test("positions inversées ou matière dupliquée refusées sans réparer", () => {
    const v = dtoFictif(), d = { ...v, lignes: [v.lignes[0], { ...v.lignes[0], position_source: 1 }], pagination: { ...v.pagination, affichees: 2, total: 2 } };
    expect(Contrat.lireContexteMateriaux(direct(d), args(Contrat))).toMatchObject({ ok: false });
    d.lignes[1].materiau_id = "MAT-AUTRE-FICTIF"; d.lignes.reverse();
    expect(Contrat.lireContexteMateriaux(direct(d), args(Contrat))).toMatchObject({ ok: false });
  });
  test("FEFF et 256 points de code restent verbatim", () => {
    const v = dtoFictif(), wct = "\ufeff", intervention = "😀".repeat(256);
    const a = Contrat.construireArgumentsContexteMateriaux(intervention, wct, 0, 8);
    const lie = { ...v, wct: { ...v.wct, wct_id: wct, intervention_id: intervention, reference_bus: { ...v.wct.reference_bus, evenement_id: wct } },
      chantier: { chantier_id: intervention, origine: "intervention_employee" } };
    expect(Contrat.lireContexteMateriaux(direct(lie), a)).toEqual({ ok: true, value: lie });
    expect(() => Contrat.construireArgumentsContexteMateriaux("\u0085\u2003", wct, 0, 8)).toThrow();
  });
  test("grande quantité texte affichable reste non importable", () => {
    const v = dtoFictif(); v.lignes[0].quantite_estimee = "9".repeat(100);
    expect(Contrat.lireContexteMateriaux(direct(v), args(Contrat))).toEqual({ ok: true, value: v });
    expect(Contrat.estimationEnNombreExact(v.lignes[0].quantite_estimee)).toBeNull();
    expect(Object.hasOwn(v.lignes[0], "quantite_reelle")).toBe(false);
  });
  test("arguments getter ou supplémentaires fermés avant lecture", () => {
    let lus = 0; const a = args(Contrat); Object.defineProperty(a, "limite", { get: () => { lus++; return 8; } });
    expect(Contrat.lireContexteMateriaux(direct(dtoFictif()), a)).toMatchObject({ ok: false }); expect(lus).toBe(0);
    const s = args(Contrat); Reflect.set(s, "role", "admin"); expect(Contrat.lireContexteMateriaux(direct(dtoFictif()), s)).toMatchObject({ ok: false });
  });
  test.each([NaN, Infinity, 1.5])("métadonnée numérique %s refusée", n => {
    const v = dtoFictif(); v.prevu.source.rang = n; expect(Contrat.lireContexteMateriaux(direct(v), args(Contrat))).toMatchObject({ ok: false });
  });
  test("refus malformé ne récupère pas une réponse partielle", () => {
    expect(Contrat.lireContexteMateriaux({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-M6-CONTEXTE-WCT-INCONNU" }, ...dtoFictif() } }, args(Contrat))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
});

import capturesProducteur from "./fixturesContexteMateriaux.json";
describe("M6 contexte — captures finales producteur SQL réel fictif", () => {
  test("source précise et privée nettoyée, aucune réponse HTTP inventée", () => {
    expect(capturesProducteur.fictif).toBe(true); expect(capturesProducteur.private_DB_removed).toBe(true); expect(capturesProducteur.captures).toHaveLength(18);
    expect(capturesProducteur.contract_sha256).toBe("954ecd730ec22bcadedf4e37ec032dbe00bec47cec09eb46b0918021482b4d4f");
  });
  test.each(capturesProducteur.captures)("$phase entièrement consommée sans réparation", capture => {
    const a = api(), r = capture.request.args;
    expect(capture.request.toolName).toBe(a.OUTIL_CONTEXTE_MATERIAUX); expect(capture.all_entire_tables_unchanged).toBe(49);
    expect(capture.envelope).toEqual(capture.response.resultat);
    if (capture.phase === "refus-arguments-limite") {
      // Le producteur applique la borne ; le mobile refuse AVANT HTTP. Aucun 9→8.
      expect(r.limite).toBe(9);
      expect(() => a.construireArgumentsContexteMateriaux(r.intervention_id, r.wct_id, r.decalage, r.limite)).toThrow();
      expect(capture.response.resultat).toMatchObject({ accepte: false, verdict: { code: "REJ-M6-CONTEXTE-ARGUMENTS-INVALIDES" } });
      expect(a.lireContexteMateriaux(capture.response, r)).toMatchObject({ ok: false, code: "reponse_illisible" });
      return;
    }
    const argumentsExacts = a.construireArgumentsContexteMateriaux(r.intervention_id, r.wct_id, r.decalage, r.limite);
    expect(argumentsExacts).toEqual(r);
    const natif = capture.response.resultat;
    if ("accepte" in natif && natif.accepte === false && natif.verdict) {
      expect(a.lireContexteMateriaux(capture.response, argumentsExacts)).toEqual({ ok: false, code: natif.verdict.code, detail: natif.verdict.detail });
    } else {
      expect(a.lireContexteMateriaux(capture.response, argumentsExacts)).toEqual({ ok: true, value: natif });
    }
  });
});
