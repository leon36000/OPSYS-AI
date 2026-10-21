import * as contrat from "./pertesAlertes";
import producteurReel from "./fixturesPertesAlertes.json";
import { estObjet } from "../admin/lecteurs";

// Scénarios purs en RAM issus du contrat de conception ROOT 676e04b0… : aucun DTO
// producteur/HTTP simulé présenté comme réel. Les captures producteur seront séparées.
const CONCEPTION = { fictif: true, source: "M6-pertes-alertes-backend-r1/contrat-dto-r5.json", sha256: "676e04b07287a9554e9e12189fb240f0b3b0418d32a34353f3f04da6f8e3d362" };
const ETATS = ["seuil_absent", "prevu_absent", "declaration_absente", "evaluee"] as const;
const WCT = "WCT-FICTIF";
function api() { return contrat; }
function wctFictif(wctId = WCT, rang = 7) {
  return { wct_id: wctId, intervention_id: "INTERVENTION-FICTIVE", devis_id: "DEVIS-FICTIF",
    horodatage_completion: "2026-10-08T09:30:00-04:00",
    reference_recu: { registre: "wct_recus", rang, empreinte_contenu: "c".repeat(64) },
    reference_bus: { type: "m4.travaux_termines", evenement_id: wctId } };
}
function pagination(total: number, affichees: number, decalage = 0, limite = 8) {
  const reste = Math.max(0, total - decalage - affichees);
  return { decalage, limite, affichees, total, suivant: reste ? decalage + affichees : null, reste, courante: true };
}
function listeFictive() {
  return { wcts: [wctFictif()], pagination: pagination(1, 1),
    couverture: { wcts: "recus_m6_rapproches_m4", plafond_lignes: 10000 },
    borne_caracteres: 5400, taille_caracteres: 900 };
}
function detailFictif() {
  return { wct: wctFictif(), chantier_id: "CHANTIER-FICTIF", declaration_presente: true,
    pertes_bris: [
      { type_mouvement: "PERTE", chantier_id: "CHANTIER-FICTIF", materiau_id: "MATERIAU-FICTIF-A", quantite_signee: "-1", unite: null, horodatage: null,
        reference: { registre: "principal", index: 2, hash_maillon: "1".repeat(64) } },
      { type_mouvement: "BRIS", chantier_id: "CHANTIER-FICTIF", materiau_id: "MATERIAU-FICTIF-B", quantite_signee: "-0.25", unite: null, horodatage: null,
        reference: { registre: "principal", index: 4, hash_maillon: "2".repeat(64) } },
    ],
    historique_variance: ETATS.map(statut => ({ statut, presente: true,
      publication: { reference_bus: { type: "m6.variance_chantier", evenement_id: `m6-variance-${WCT}-${statut}` },
        chantier_id: "CHANTIER-FICTIF", signal_critique: statut === "evaluee" ? true : null,
        seuil_pourcentage: statut === "seuil_absent" ? null : 0.1,
        horodatage_completion: "2026-10-08T09:30:00-04:00", horodatage_publication: null } })),
    evaluee_terminal: true, pagination: pagination(2, 2),
    couverture: { mouvements: "PERTE_BRIS_WCT_exact", variances: "quatre_statuts_publies_ordre_fixe_sans_chronologie",
      hors_corpus: ["stock_courant", "reapprovisionnement", "couts", "responsables", "preuves_photos", "unites_reelles", "dates_perte_bris"], plafond_lignes: 10000 },
    borne_caracteres: 5400, taille_caracteres: 2700 };
}
const direct = (resultat: unknown) => ({ ok: true, resultat });
type Detail = ReturnType<typeof detailFictif>;
type Liste = ReturnType<typeof listeFictive>;
const erreursDetail: Array<readonly [string, (v: Detail) => void]> = [
  ["WCT d'autre sélection", v => { v.wct.wct_id = "WCT-AUTRE"; }],
  ["bus M4 autre WCT", v => { v.wct.reference_bus.evenement_id = "WCT-AUTRE"; }],
  ["reçu mauvais registre", v => { v.wct.reference_recu.registre = "autre"; }],
  ["rang négatif", v => { v.wct.reference_recu.rang = -1; }],
  ["rang unsafe", v => { v.wct.reference_recu.rang = Number.MAX_SAFE_INTEGER + 1; }],
  ["empreinte incomplète", v => { v.wct.reference_recu.empreinte_contenu = "c".repeat(63); }],
  ["date impossible", v => { v.wct.horodatage_completion = "2026-02-30T09:30:00Z"; }],
  ["date newline", v => { v.wct.horodatage_completion += "\n"; }],
  ["chantier mouvement différent", v => { v.pertes_bris[0].chantier_id = "AUTRE"; }],
  ["mouvement RETOUR", v => { v.pertes_bris[0].type_mouvement = "RETOUR"; }],
  ["unité mouvement inventée", v => { Reflect.set(v.pertes_bris[0], "unite", "m"); }],
  ["date mouvement empruntée", v => { Reflect.set(v.pertes_bris[0], "horodatage", v.wct.horodatage_completion); }],
  ["registre mouvement autre", v => { v.pertes_bris[0].reference.registre = "autre"; }],
  ["index négatif", v => { v.pertes_bris[0].reference.index = -1; }],
  ["index fractionnel", v => { v.pertes_bris[0].reference.index = 0.5; }],
  ["hash majuscule", v => { v.pertes_bris[0].reference.hash_maillon = "A".repeat(64); }],
  ["ordre indices inversé", v => { v.pertes_bris.reverse(); }],
  ["index dupliqué", v => { v.pertes_bris[1].reference.index = v.pertes_bris[0].reference.index; }],
  ["hash dupliqué", v => { v.pertes_bris[1].reference.hash_maillon = v.pertes_bris[0].reference.hash_maillon; }],
  ["coût ajouté", v => { Reflect.set(v.pertes_bris[0], "cout_unitaire", "3.00"); }],
  ["déclaration absente avec pertes", v => { v.declaration_presente = false; }],
  ["ordre historique inversé", v => { v.historique_variance.reverse(); }],
  ["historique coupé", v => { v.historique_variance.pop(); }],
  ["publication présente flag faux", v => { v.historique_variance[0].presente = false; }],
  ["publication absente flag vrai", v => { Reflect.set(v.historique_variance[0], "publication", null); }],
  ["ID variance autre WCT", v => { v.historique_variance[0].publication.reference_bus.evenement_id = "m6-variance-WCT-AUTRE-seuil_absent"; }],
  ["ID variance autre état", v => { v.historique_variance[0].publication.reference_bus.evenement_id = `m6-variance-${WCT}-evaluee`; }],
  ["publication chantier autre", v => { v.historique_variance[0].publication.chantier_id = "AUTRE"; }],
  ["publication date autre", v => { v.historique_variance[0].publication.horodatage_completion = "2026-10-08T09:30:00Z"; }],
  ["publication datée artificiellement", v => { Reflect.set(v.historique_variance[0].publication, "horodatage_publication", v.wct.horodatage_completion); }],
  ["signal avant évaluation", v => { v.historique_variance[0].publication.signal_critique = true; }],
  ["signal absent évaluation", v => { v.historique_variance[3].publication.signal_critique = null; }],
  ["seuil absent malgré état", v => { v.historique_variance[1].publication.seuil_pourcentage = null; }],
  ["seuil présent seuil_absent", v => { v.historique_variance[0].publication.seuil_pourcentage = 0.1; }],
  ["seuil zéro", v => { v.historique_variance[1].publication.seuil_pourcentage = 0; }],
  ["seuil entier unsafe", v => { v.historique_variance[1].publication.seuil_pourcentage = Number.MAX_SAFE_INTEGER + 1; }],
  ["seuil NaN", v => { v.historique_variance[1].publication.seuil_pourcentage = NaN; }],
  ["seuil Infinity", v => { v.historique_variance[1].publication.seuil_pourcentage = Infinity; }],
  ["terminal faux", v => { v.evaluee_terminal = false; }],
  ["pagination autre départ", v => { v.pagination.decalage = 1; }],
  ["pagination autre limite", v => { v.pagination.limite = 7; }],
  ["affichées incohérentes", v => { v.pagination.affichees = 1; }],
  ["total insuffisant", v => { v.pagination.total = 1; }],
  ["reste faux", v => { v.pagination.reste = 1; }],
  ["suivant faux", v => { v.pagination.suivant = 2; }],
  ["courante faux", v => { v.pagination.courante = false; }],
  ["plafond changé", v => { v.couverture.plafond_lignes = 9999; }],
  ["hors corpus coupé", v => { v.couverture.hors_corpus.pop(); }],
  ["borne changée", v => { v.borne_caracteres = 6000; }],
  ["taille non finie", v => { v.taille_caracteres = Infinity; }],
  ["taille hors borne", v => { v.taille_caracteres = 5401; }],
];
const erreursListe: Array<readonly [string, (v: Liste) => void]> = [
  ["WCT dupliqué", v => { v.wcts.push(wctFictif()); v.pagination = pagination(2, 2); }],
  ["ordre rangs ascendant", v => { v.wcts.push(wctFictif("WCT-AUTRE", 8)); v.pagination = pagination(2, 2); }],
  ["rang reçu dupliqué", v => { v.wcts.push(wctFictif("WCT-AUTRE", 7)); v.pagination = pagination(2, 2); }],
  ["compteur unsafe", v => { v.pagination.total = Number.MAX_SAFE_INTEGER + 1; }],
  ["source couverture autre", v => { v.couverture.wcts = "tous_les_chantiers"; }],
  ["champ identité ajouté", v => { Reflect.set(v.wcts[0], "personne", "fictive"); }],
];

describe("M6 pertes/bris — contrat pur, conception fictive en RAM", () => {
  test("deux lectures sans arguments économiques ni identité", () => {
    expect(CONCEPTION.fictif).toBe(true);
    const a = api();
    expect(a.OUTIL_LISTE_WCT_PERTES).toBe("m6_lister_wct_pertes_appareil");
    expect(a.OUTIL_PERTES_ALERTES_WCT).toBe("m6_lire_pertes_alertes_wct_appareil");
    expect(a.construireArgumentsListeWct()).toEqual({ decalage: 0, limite: 8 });
    expect(a.construireArgumentsPertesWct(WCT)).toEqual({ wct_id: WCT, decalage: 0, limite: 8 });
    expect(a.construireArgumentsPertesWct(" WCT-FICTIF ", 10000, 1)).toEqual({ wct_id: " WCT-FICTIF ", decalage: 10000, limite: 1 });
  });
  test.each([-1, 0.5, 10001, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])("départ invalide %s refusé", v => {
    const a = api();
    expect(() => a.construireArgumentsListeWct(v)).toThrow();
    expect(() => a.construireArgumentsPertesWct(WCT, v)).toThrow();
  });
  test.each([0, 9, 0.5, NaN, Infinity])("limite invalide %s refusée", v => {
    const a = api();
    expect(() => a.construireArgumentsListeWct(0, v)).toThrow();
    expect(() => a.construireArgumentsPertesWct(WCT, 0, v)).toThrow();
  });
  test.each(["", " ", "WCT\n", "x".repeat(257), "\ud800"])("ID invalide sans réparation", v => {
    const a = api();
    expect(() => a.construireArgumentsPertesWct(v)).toThrow();
  });
  test("prédicat Python strip : White_Space exclu, U+FEFF source reste verbatim", () => {
    const a = api();
    for (const cp of [32, 160, 5760, 8192, 8193, 8194, 8195, 8196, 8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288]) {
      expect(() => a.construireArgumentsPertesWct(String.fromCodePoint(cp))).toThrow();
    }
    const wctId = "\ufeff";
    const args = a.construireArgumentsPertesWct(wctId);
    expect(args).toEqual({ wct_id: wctId, decalage: 0, limite: 8 });
    const v = detailFictif(); v.wct.wct_id = wctId; v.wct.reference_bus.evenement_id = wctId;
    for (const slot of v.historique_variance) slot.publication.reference_bus.evenement_id = `m6-variance-${wctId}-${slot.statut}`;
    expect(a.lirePertesAlertesWct(direct(v), args)).toEqual({ ok: true, value: v });
  });
  test("liste/detail DIRECTS natifs : pas de chiffre/date/unité refaits", () => {
    const a = api(), liste = listeFictive(), detail = detailFictif();
    expect(a.lireListeWctPertes(direct(liste), a.construireArgumentsListeWct())).toEqual({ ok: true, value: liste });
    expect(a.lirePertesAlertesWct(direct(detail), a.construireArgumentsPertesWct(WCT))).toEqual({ ok: true, value: detail });
    expect(a.lirePertesAlertesWct({ ok: true, resultat: { accepte: true, resultat: detail } }, a.construireArgumentsPertesWct(WCT))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(erreursDetail)("detail ferme : %s", (_nom, muter) => {
    const a = api(), v = detailFictif(); muter(v);
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(erreursListe)("liste ferme : %s", (_nom, muter) => {
    const a = api(), v = listeFictive(); muter(v);
    expect(a.lireListeWctPertes(direct(v), a.construireArgumentsListeWct())).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(["0", "-0", "-0.00", "1", "+1", "-1e3", "-01", "-1.0", "-1.00", "-0.250", "-Infinity", "NaN", "-1\n"])("quantité non canonique %s refusée", quantite => {
    const a = api(), v = detailFictif(); v.pertes_bris[0].quantite_signee = quantite;
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test.each(["-1", "-0.0000000000000000001", "-999999999999999999999999999.25"])("quantité exacte %s conservée sans flottant", quantite => {
    const a = api(), v = detailFictif(); v.pertes_bris[0].quantite_signee = quantite;
    const lu = a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT));
    expect(lu).toEqual({ ok: true, value: v });
  });
  test("absence des quatre publications et déclaration, distinctes de zéro pertes déclaré", () => {
    const a = api(), v = detailFictif(); v.pertes_bris = []; v.pagination = pagination(0, 0); v.declaration_presente = false;
    Reflect.set(v, "chantier_id", null); v.evaluee_terminal = false;
    for (const slot of v.historique_variance) { slot.presente = false; Reflect.set(slot, "publication", null); }
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT))).toEqual({ ok: true, value: v });
    v.declaration_presente = true; Reflect.set(v, "chantier_id", "CHANTIER-FICTIF");
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT))).toEqual({ ok: true, value: v });
  });
  test("WCT métier 256 points de code : référence canonique variance plus longue conservée", () => {
    const a = api(), v = detailFictif(), wctId = "x".repeat(256);
    v.wct.wct_id = wctId; v.wct.reference_bus.evenement_id = wctId;
    for (const slot of v.historique_variance) {
      if (slot.statut === "evaluee") slot.publication.reference_bus.evenement_id = `m6-variance-${wctId}-${slot.statut}`;
      else { slot.presente = false; Reflect.set(slot, "publication", null); }
    }
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(wctId))).toEqual({ ok: true, value: v });
  });
  test("évaluation terminale sans mouvement de déclaration reste une contradiction fermée", () => {
    const a = api(), v = detailFictif();
    v.pertes_bris = []; v.pagination = pagination(0, 0); v.declaration_presente = false;
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT))).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("pages source réduites et départ hors total restent légaux", () => {
    const a = api(), v = detailFictif(); v.pertes_bris.pop(); v.pagination = pagination(9, 1, 2, 8);
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT, 2))).toEqual({ ok: true, value: v });
    v.pertes_bris = []; v.pagination = pagination(9, 0, 10000, 8);
    expect(a.lirePertesAlertesWct(direct(v), a.construireArgumentsPertesWct(WCT, 10000))).toEqual({ ok: true, value: v });
    const vide = listeFictive(); vide.wcts = []; vide.pagination = pagination(0, 0);
    expect(a.lireListeWctPertes(direct(vide), a.construireArgumentsListeWct())).toEqual({ ok: true, value: vide });
  });
  test("refus natif prime sur flags et conserve texte ; refus incomplet jamais réparé", () => {
    const a = api(), args = a.construireArgumentsPertesWct(WCT);
    const verdict = { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "refus fictif source" };
    expect(a.lirePertesAlertesWct({ ok: true, tronque: true, resultat: { accepte: false, verdict } }, args)).toEqual({ ok: false, ...verdict });
    expect(a.lirePertesAlertesWct({ ok: false, erreur: "REJ-M6-PERTES-FICTIF", details: "fictif" }, args)).toEqual({ ok: false, code: "REJ-M6-PERTES-FICTIF", detail: "fictif" });
    for (const brut of [direct({ accepte: false }), direct({ accepte: false, verdict: { code: "" } }), { ok: false, details: "fictif" }]) {
      expect(a.lirePertesAlertesWct(brut, args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    }
    expect(a.lireListeWctPertes({ ok: true, tronque: true, apercu: "fictif" }, a.construireArgumentsListeWct())).toMatchObject({ ok: false, code: "reponse_tronquee" });
  });
  test("getters/prototypes/champs inconnus dans tout JSON sont refusés sans exécution", () => {
    const a = api(), args = a.construireArgumentsPertesWct(WCT);
    let appels = 0;
    const v = detailFictif(); Object.defineProperty(v.wct, "secret", { enumerable: true, get: () => { appels++; return "fictif"; } });
    expect(a.lirePertesAlertesWct(direct(v), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    expect(appels).toBe(0);
    const autre = detailFictif(); Object.setPrototypeOf(autre, { role: "admin" });
    expect(a.lirePertesAlertesWct(direct(autre), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    const resultat = direct(detailFictif()); Reflect.set(resultat, "agent", "fictif");
    expect(a.lirePertesAlertesWct(resultat, args)).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
  test("arguments capturés propres, fermés, non réparés même sous refus métier", () => {
    const a = api(); let appels = 0;
    const args = a.construireArgumentsPertesWct(WCT); Object.defineProperty(args, "wct_id", { enumerable: true, get: () => { appels++; return WCT; } });
    expect(a.lirePertesAlertesWct(direct(detailFictif()), args)).toMatchObject({ ok: false, code: "reponse_illisible" });
    expect(appels).toBe(0);
    const autre = a.construireArgumentsPertesWct(WCT); Reflect.set(autre, "seuil", 0.1);
    expect(a.lirePertesAlertesWct(direct({ accepte: false, verdict: { code: "REJ-FICTIF", detail: "fictif" } }), autre)).toMatchObject({ ok: false, code: "reponse_illisible" });
  });
});

// Copie exacte dto-reels-r4.json SHA20f02ac4… : executer_atomique/SQLite fictif,
// aucun Gateway/HTTP/DEVICE opaque. response est l'enveloppe DIRECTE entière ;
// le champ nommé envelope de ce reçu producteur n'est que response.resultat.
describe("M6 pertes/bris — sorties réelles du producteur Python/SQLite", () => {
  test("provenance et absence de mutation source restent distinctes du client pur", () => {
    expect(producteurReel.fictif).toBe(true);
    expect(producteurReel.scope).toContain("pas HTTP/Gateway/DEVICE opaque natif");
    expect(producteurReel.provenance.head).toBe("6f7dc1819c168ec5660dec83d4bbbe388925899b");
    expect(producteurReel.provenance.sources_owned_inchangees).toBe(true);
    expect(producteurReel.captures).toHaveLength(16);
  });
  test.each(producteurReel.captures.map(c => [c.phase, c] as const))("%s : args et enveloppe DIRECTE exacts", (phase, c) => {
    const a = api(), args = c.request.args;
    expect(c.tables_integrales_inchangees).toBe(49);
    if (c.request.toolName === a.OUTIL_LISTE_WCT_PERTES) {
      const construits = a.construireArgumentsListeWct(args.decalage, args.limite);
      expect(construits).toEqual(args);
      expect(a.lireListeWctPertes(c.response, construits)).toEqual({ ok: true, value: c.response.resultat });
      return;
    }
    expect(c.request.toolName).toBe(a.OUTIL_PERTES_ALERTES_WCT);
    if (!("wct_id" in args) || typeof args.wct_id !== "string") throw new Error("WCT source attendu.");
    if (phase === "refus-limite") {
      expect(args.limite).toBe(9);
      expect(() => a.construireArgumentsPertesWct(args.wct_id, args.decalage, args.limite)).toThrow();
      expect(Reflect.apply(a.lirePertesAlertesWct, undefined, [c.response, args])).toMatchObject({ ok: false, code: "reponse_illisible" });
      return;
    }
    const construits = a.construireArgumentsPertesWct(args.wct_id, args.decalage, args.limite);
    expect(construits).toEqual(args);
    const lu = a.lirePertesAlertesWct(c.response, construits);
    const response: unknown = c.response;
    if (!estObjet(response)) throw new Error("Réponse producteur attendue.");
    const resultat = response.resultat;
    if (estObjet(resultat) && resultat.accepte === false) {
      if (!estObjet(resultat.verdict)) throw new Error("Refus source attendu.");
      expect(lu).toEqual({ ok: false, code: resultat.verdict.code, detail: resultat.verdict.detail });
      expect(lu).not.toHaveProperty("value");
    } else if (response.ok === false) {
      const detail = typeof response.details === "string" ? response.details :
        Array.isArray(response.details) && response.details.every(v => typeof v === "string") ? response.details.join(" ; ") : null;
      if (detail === null) throw new Error("Détails de refus source illisibles.");
      expect(lu).toEqual({ ok: false, code: response.erreur, detail });
      expect(lu).not.toHaveProperty("value");
    } else {
      expect(lu).toEqual({ ok: true, value: resultat });
    }
  });
});
