import * as Contrat from "./reapprovisionnement";

// Fixtures de conception uniquement en RAM, fictives ; aucune capture SQL/HTTP inventée.
const CONCEPTION = { fictif: true, source: "M6-reapprovisionnement-backend-r1/contrat-dto-r1.json", sha256: "24f8f7927de85556277b2fb6e737b53aa54d8d586d7fc5cc39ecdf8057a9a66a" };
function api(): typeof Contrat { return Contrat; }
const REGISTRES = ["besoins_commande", "principal", "reservations", "emplacements"] as const;
const ETATS = ["stock_bas", "stock_suffisant", "seuil_absent", "configuration_invalide"] as const;
function articleFictif(statut: (typeof ETATS)[number] = "stock_bas", rang = 3) {
  const config = statut === "stock_bas" || statut === "stock_suffisant";
  return { materiau_id: "MAT-FICTIF", statut,
    chiffres: { stock_theorique: "10", hors_main: "2", en_main: "8", reserve: statut === "stock_suffisant" ? "3" : "4", disponible: statut === "stock_suffisant" ? "5" : "4" },
    seuil_reapprovisionnement: config ? "5" : null, quantite_cible: config ? "10" : null,
    quantite_a_commander: statut === "stock_bas" ? "6" : null, stock_negatif: false,
    code_configuration: statut === "configuration_invalide" ? "REJ-REAPPRO-ARTICLE-INVALIDE" : null,
    unite: null, unite_dernier_constat: "m", dernier_constat: {
      reference: { registre: "besoins_commande", rang, empreinte_snapshot: "c".repeat(64) },
      type_entree: "besoin_commande", evenement_declencheur: "WCT-FICTIF",
      horodatage: "2026-10-08T09:30:00-04:00", chantier_id: "CHANTIER-FICTIF",
      reference_bus: { type: "m4.travaux_termines", evenement_id: "WCT-FICTIF" },
    } };
}
function dtoFictif(statut: (typeof ETATS)[number] = "stock_bas") {
  return { articles: [articleFictif(statut)], pagination: { decalage: 0, limite: 8, affichees: 1, total: 1, suivant: null, reste: 0, courante: true },
    source_configuration: { fichier: "departments/m06-material-control/department.yaml", chemin: "configuration.reapprovisionnement.articles", sha256: "a".repeat(64) },
    sources_registres: REGISTRES.map((registre, i) => ({ registre, lignes: i === 0 ? 4 : i === 1 ? 2 : 0, empreinte_snapshot: "b".repeat(64) })),
    source_publications: {
      evenements: { type: "m4.travaux_termines", lignes: 1, empreinte_snapshot: "d".repeat(64) },
      recus_m6: { registre: "wct_recus", lignes: 0, empreinte_snapshot: "e".repeat(64) },
    },
    couverture: { articles: "articles_deja_constates", stock: "theorique_disponible", unites: "homogeneite_non_confirmee", horodatage: "dernier_constat_sans_date_calcul", plafond_lignes: 10000 },
    borne_caracteres: 5400, taille_caracteres: 1800 };
}
const direct = (resultat: unknown) => ({ ok: true, resultat });
type Article = ReturnType<typeof articleFictif>;
type DTO = ReturnType<typeof dtoFictif>;
const erreursArticle: Array<readonly [string, (a: Article) => void]> = [
  ["ID blanc", a => { a.materiau_id = " "; }],
  ["ID contrôle", a => { a.materiau_id += "\n"; }],
  ["ID257", a => { a.materiau_id = "x".repeat(257); }],
  ["état inconnu", a => { Reflect.set(a, "statut", "alerte"); }],
  ["chiffre absent", a => { Reflect.deleteProperty(a.chiffres, "reserve"); }],
  ["chiffre supplémentaire", a => { Reflect.set(a.chiffres, "stock_physique", "3"); }],
  ["horsmain négatif", a => { a.chiffres.hors_main = "-1"; }],
  ["réservé négatif", a => { a.chiffres.reserve = "-1"; }],
  ["négatif faux", a => { a.chiffres.en_main = "-1"; }],
  ["négatif vrai sans stock négatif", a => { a.stock_negatif = true; }],
  ["configuré seuilnull", a => { a.seuil_reapprovisionnement = null; }],
  ["seuil zéro", a => { a.seuil_reapprovisionnement = "0"; }],
  ["seuil négatif", a => { a.seuil_reapprovisionnement = "-1"; }],
  ["cible seuil inférieur", a => { a.quantite_cible = "4.9999999999999999999999999999"; }],
  ["bas égal seuil", a => { a.chiffres.disponible = "5"; }],
  ["bas supérieur seuil", a => { a.chiffres.disponible = "5.000000000000000000000000001"; }],
  ["bas sans commande", a => { a.quantite_a_commander = null; }],
  ["commande zéro", a => { a.quantite_a_commander = "0"; }],
  ["commande négative", a => { a.quantite_a_commander = "-1"; }],
  ["code malgré configuré", a => { a.code_configuration = "REJ-REAPPRO-ARTICLE-INVALIDE"; }],
  ["unité courante inventée", a => { Reflect.set(a, "unite", "m"); }],
  ["unitéhistorique blanche", a => { a.unite_dernier_constat = " "; }],
  ["unitéhistorique257", a => { a.unite_dernier_constat = "x".repeat(257); }],
  ["constat registre autre", a => { a.dernier_constat.reference.registre = "principal"; }],
  ["rang négatif", a => { a.dernier_constat.reference.rang = -1; }],
  ["rang unsafe", a => { a.dernier_constat.reference.rang = Number.MAX_SAFE_INTEGER + 1; }],
  ["rang égal compte", a => { a.dernier_constat.reference.rang = 4; }],
  ["snapshot hash63", a => { a.dernier_constat.reference.empreinte_snapshot = "c".repeat(63); }],
  ["snapshot headinventée", a => { Reflect.set(a.dernier_constat.reference, "hash_tete", "c".repeat(64)); }],
  ["type entrée inconnu", a => { a.dernier_constat.type_entree = "stock_bas"; }],
  ["événement lien différent", a => { a.dernier_constat.reference_bus.evenement_id = "WCT-AUTRE"; }],
  ["bus type autre", a => { a.dernier_constat.reference_bus.type = "m6.variance_chantier"; }],
  ["date sans fuseau", a => { a.dernier_constat.horodatage = "2026-10-08T09:30:00"; }],
  ["date impossible", a => { a.dernier_constat.horodatage = "2026-02-30T09:30:00Z"; }],
  ["date contrôle", a => { a.dernier_constat.horodatage += "\n"; }],
  ["chantier blanc", a => { a.dernier_constat.chantier_id = " "; }],
  ["auteur ajouté", a => { Reflect.set(a.dernier_constat, "auteur", "fictif"); }],
];
const erreursDTO: Array<readonly [string, (v: DTO) => void]> = [
  ["page départ autre", v => { v.pagination.decalage = 1; }],
  ["page limite autre", v => { v.pagination.limite = 7; }],
  ["page affichées autre", v => { v.pagination.affichees = 0; }],
  ["page total insuffisant", v => { v.pagination.total = 0; }],
  ["page total hors constats", v => { v.pagination.total = 5; v.pagination.reste = 4; Reflect.set(v.pagination, "suivant", 1); }],
  ["page totalunsafe", v => { v.pagination.total = Number.MAX_SAFE_INTEGER + 1; }],
  ["page reste autre", v => { v.pagination.reste = 1; }],
  ["page suivant autre", v => { Reflect.set(v.pagination, "suivant", 1); }],
  ["page courante faux", v => { v.pagination.courante = false; }],
  ["source fichier autre", v => { v.source_configuration.fichier = "/serveur/fictif.yaml"; }],
  ["source bloc autre", v => { v.source_configuration.chemin = "configuration.prix"; }],
  ["config hash majuscules", v => { v.source_configuration.sha256 = "A".repeat(64); }],
  ["rawconfig ajouté", v => { Reflect.set(v.source_configuration, "configuration", { fictif: true }); }],
  ["sources ordre inversé", v => { v.sources_registres.reverse(); }],
  ["source supplémentaire", v => { v.sources_registres.push({ ...v.sources_registres[0] }); }],
  ["source supprimée", v => { v.sources_registres.pop(); }],
  ["source count négatif", v => { v.sources_registres[0].lignes = -1; }],
  ["source countunsafe", v => { v.sources_registres[0].lignes = Number.MAX_SAFE_INTEGER + 1; }],
  ["source total6 dépasse10000", v => { v.source_publications.recus_m6.lignes = 9994; }],
  ["publication type faux", v => { v.source_publications.evenements.type = "m5.facture"; }],
  ["reçu registre faux", v => { v.source_publications.recus_m6.registre = "affaires"; }],
  ["publication snapshot faux", v => { v.source_publications.evenements.empreinte_snapshot = "z".repeat(64); }],
  ["couverture totalité inventée", v => { v.couverture.articles = "tous_articles"; }],
  ["couverture physique inventée", v => { v.couverture.stock = "physique"; }],
  ["couvertureunité confirmée", v => { v.couverture.unites = "confirmee"; }],
  ["date calcul inventée", v => { v.couverture.horodatage = "calcul_courant"; }],
  ["plafond autre", v => { v.couverture.plafond_lignes = 9999; }],
  ["taille0", v => { v.taille_caracteres = 0; }],
  ["taille horsborne", v => { v.taille_caracteres = 5401; }],
  ["taille NaN", v => { v.taille_caracteres = NaN; }],
  ["borne changée", v => { v.borne_caracteres = 6000; }],
];

describe("M6 réapprovisionnement — scénarios purement fictifs en RAM", () => {
  test("API lecture seulement : requête fermée requise", () => {
    expect(CONCEPTION.fictif).toBe(true);
    const a = api(); expect(a.OUTIL_REAPPROVISIONNEMENT).toBe("m6_lire_reapprovisionnement_appareil");
    expect(a.construireArgumentsReapprovisionnement()).toEqual({ decalage: 0, limite: 8 });
    expect(a.construireArgumentsReapprovisionnement(10000, 1)).toEqual({ decalage: 10000, limite: 1 });
  });
  test.each([-1, 0.5, 10001, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])("offset %s invalide", v => {
    const a = api(); expect(() => a.construireArgumentsReapprovisionnement(v)).toThrow();
  });
  test.each([0, 9, 0.5, NaN, Infinity])("limite %s invalide", v => {
    const a = api(); expect(() => a.construireArgumentsReapprovisionnement(0, v)).toThrow();
  });
  test.each(ETATS)("état natif %s sans emprunter unité/date", statut => {
    const a = api(), v = dtoFictif(statut);
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
  });
  test.each(erreursArticle)("article fermé : %s", (_nom, muter) => {
    const a = api(), v = dtoFictif(); muter(v.articles[0]);
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(erreursDTO)("DTO fermé : %s", (_nom, muter) => {
    const a = api(), v = dtoFictif(); muter(v);
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(["-0", "-0.00", "00", "01", "1.0", "1.00", "0.10", "+1", "1e3", "Infinity", "NaN", "1\n", " 1"])("décimal non canonique %s refusé", chiffre => {
    const a = api(), v = dtoFictif(); v.articles[0].chiffres.stock_theorique = chiffre;
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("nontexte booléen/NaN/Infinity/grand JSNumber refusé", () => {
    const a = api();
    for (const valeur of [true, 3, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, null]) {
      const v = dtoFictif(); Reflect.set(v.articles[0].chiffres, "stock_theorique", valeur);
      expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    }
  });
  test("égalité au seuil suffisante, différences minuscules/grands entiers restent textes exacts", () => {
    const a = api(), v = dtoFictif("stock_suffisant"), article = v.articles[0];
    article.chiffres.disponible = "9007199254740993000000000000000000.00000000000000000001";
    article.seuil_reapprovisionnement = article.chiffres.disponible;
    article.quantite_cible = "9007199254740993000000000000000001";
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
    article.statut = "stock_bas"; article.quantite_a_commander = "0.99999999999999999999";
    article.chiffres.disponible = "9007199254740993000000000000000000.000000000000000000009";
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
  });
  test.each(ETATS)("en main négatif explicite même %s ; aucune commande", statut => {
    const a = api(), v = dtoFictif(statut), article = v.articles[0];
    article.chiffres.stock_theorique = "-3"; article.chiffres.hors_main = "0"; article.chiffres.en_main = "-3";
    article.chiffres.reserve = "1"; article.chiffres.disponible = "-4"; article.stock_negatif = true; article.quantite_a_commander = null;
    if (statut === "stock_suffisant") {
      expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    } else {
      expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
    }
  });
  test("réservation dépassant enmain : disponible négatif conservé, quantité source positive", () => {
    const a = api(), v = dtoFictif(); v.articles[0].chiffres.reserve = "12"; v.articles[0].chiffres.disponible = "-4"; v.articles[0].quantite_a_commander = "14";
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
  });
  test("absence/invalide ferme params et codes, état suffisant ne propose jamais commande", () => {
    const a = api();
    for (const statut of ["seuil_absent", "configuration_invalide"] as const) {
      for (const champ of ["seuil_reapprovisionnement", "quantite_cible", "quantite_a_commander"] as const) {
        const v = dtoFictif(statut); v.articles[0][champ] = "5";
        expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
      }
    }
    const suffisant = dtoFictif("stock_suffisant"); suffisant.articles[0].quantite_a_commander = "1";
    expect(a.lireReapprovisionnement(direct(suffisant), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    const absent = dtoFictif("seuil_absent"); absent.articles[0].code_configuration = "REJ-REAPPRO-ARTICLE-INVALIDE";
    expect(a.lireReapprovisionnement(direct(absent), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    const invalide = dtoFictif("configuration_invalide"); invalide.articles[0].code_configuration = "REJ-REAPPRO-INVENTE";
    expect(a.lireReapprovisionnement(direct(invalide), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    invalide.articles[0].code_configuration = null;
    expect(a.lireReapprovisionnement(direct(invalide), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("dernier rang source DESC, jamais date : ordre inverse/duplicata fermés", () => {
    const a = api(), v = dtoFictif(); const deux = articleFictif("stock_bas", 2); deux.materiau_id = "MAT-FICTIF-B";
    deux.dernier_constat.horodatage = "2026-10-09T09:30:00-04:00";
    v.articles.push(deux); v.pagination.affichees = 2; v.pagination.total = 2;
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
    v.articles.reverse();
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
    v.articles.reverse(); deux.materiau_id = v.articles[0].materiau_id;
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("page réduite, vide et au-delà total ; historiquetype ne force pas état courant", () => {
    const a = api(), v = dtoFictif("stock_suffisant"); v.articles[0].dernier_constat.type_entree = "seuil_a_configurer";
    v.articles[0].unite_dernier_constat = "\ufeff"; v.articles[0].materiau_id = "\ufeff";
    v.pagination.total = 4; v.pagination.reste = 3; Reflect.set(v.pagination, "suivant", 1);
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
    v.articles = []; v.pagination.decalage = 10000; v.pagination.affichees = 0; v.pagination.reste = 0; Reflect.set(v.pagination, "suivant", null);
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement(10000))).toEqual({ ok: true, value: v });
    v.pagination.decalage = 0; v.pagination.total = 0;
    expect(a.lireReapprovisionnement(direct(v), a.construireArgumentsReapprovisionnement())).toEqual({ ok: true, value: v });
  });
  test("snapshot JSON entier : getter/prototype/symbol/cycle, aucun getter exécuté", () => {
    const a = api(), args = a.construireArgumentsReapprovisionnement(); let appels = 0;
    const v = dtoFictif(); Object.defineProperty(v.articles[0], "secret", { enumerable: true, get: () => { appels++; return "fictif"; } });
    expect(a.lireReapprovisionnement(direct(v), args)).toMatchObject({ ok: false, code: "reponse_illisible" }); expect(appels).toBe(0);
    const proto = dtoFictif(); Object.setPrototypeOf(proto.source_configuration, { role: "admin" });
    expect(a.lireReapprovisionnement(direct(proto), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    const symbole = dtoFictif(); Reflect.set(symbole, Symbol("fictif"), true);
    expect(a.lireReapprovisionnement(direct(symbole), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    const cycle = dtoFictif(); Reflect.set(cycle, "cycle", cycle);
    expect(a.lireReapprovisionnement(direct(cycle), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("refus nommés prioritaires, malformedpasréparé et troncaturefermée", () => {
    const a = api(), args = a.construireArgumentsReapprovisionnement(), verdict = { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "refus fictif" };
    expect(a.lireReapprovisionnement({ ok: true, tronque: true, resultat: { accepte: false, verdict } }, args)).toEqual({ ok: false, ...verdict });
    expect(a.lireReapprovisionnement({ ok: false, erreur: "REJ-M6-REAPPRO-SOURCE-FICTIVE", details: "fictif" }, args)).toEqual({ ok: false, code: "REJ-M6-REAPPRO-SOURCE-FICTIVE", detail: "fictif" });
    for (const brut of [direct({ accepte: false }), direct({ accepte: false, verdict: { code: "" } }), { ok: false }]) {
      expect(a.lireReapprovisionnement(brut, args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    }
    expect(a.lireReapprovisionnement({ ok: true, tronque: true, apercu: "fictif" }, args)).toMatchObject({ ok: false, code: "reponse_tronquee" });
  });
  test("args fermés, capturés sans getters avant réponse même refus", () => {
    const a = api(), args = a.construireArgumentsReapprovisionnement(); Reflect.set(args, "seuil", "1");
    expect(a.lireReapprovisionnement(direct(dtoFictif()), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    let appels = 0; const getters = a.construireArgumentsReapprovisionnement();
    Object.defineProperty(getters, "limite", { enumerable: true, get: () => { appels++; return 8; } });
    expect(a.lireReapprovisionnement(direct({ accepte: false }), getters)).toMatchObject({ ok: false, code: "reponse_illisible" }); expect(appels).toBe(0);
  });
});


import fixturesProducteur from "./fixturesReapprovisionnement.json";
describe("M6 — captures SQL réelles fictives, aucune HTTP/Gateway", () => {
  test("provenance distincte des scénarios RAM", () => {
    expect(fixturesProducteur.fictif).toBe(true);
    expect(fixturesProducteur.sources_owned_inchangees).toBe(true);
    expect(fixturesProducteur.contrat_sha256).toBe(CONCEPTION.sha256);
    expect(fixturesProducteur.captures).toHaveLength(13);
  });
  test.each(fixturesProducteur.captures)("capture producteur $phase, enveloppe entière inchangée", capture => {
    const a = api();
    const args = a.construireArgumentsReapprovisionnement(capture.request.args.decalage, capture.request.args.limite);
    expect(args).toEqual(capture.request.args);
    expect(capture.request.toolName).toBe(a.OUTIL_REAPPROVISIONNEMENT);
    expect(capture.tables_integrales_inchangees).toBe(49);
    const lecture = a.lireReapprovisionnement(capture.response, args);
    if (capture.response.resultat.accepte === false) {
      const verdict = capture.response.resultat.verdict;
      if (!verdict) throw new Error("Capture de refus sans verdict.");
      expect(lecture).toEqual({ ok: false, code: verdict.code, detail: verdict.detail });
    } else {
      expect(lecture).toEqual({ ok: true, value: capture.response.resultat });
    }
  });
});
