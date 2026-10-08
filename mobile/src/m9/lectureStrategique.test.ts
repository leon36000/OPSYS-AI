import { runInNewContext } from "node:vm";
import { construireArgumentsLectureStrategique, lireLectureStrategique, OUTIL_LECTURE_STRATEGIQUE } from "./lectureStrategique";
import { interpreter } from "../admin/enveloppe";
import fixtures from "./fixturesLectureStrategique.json";

function clone(v: unknown): any { return JSON.parse(JSON.stringify(v)); }
const maintenant = fixtures.maintenant;
const mesure = fixtures.reponses.mesure.enveloppe.resultat;
const premiere = fixtures.reponses.premiere.enveloppe.resultat;
function lire(v: unknown, depart = 0) { return lireLectureStrategique(v, maintenant, depart); }

test.each(Object.entries(fixtures.reponses))("DTO pur natif M9 %s : tous les champs utiles restent ceux du serveur", (_nom, f) => {
  expect(fixtures.fictif).toBe(true);
  expect(lireLectureStrategique(f.enveloppe.resultat, f.arguments.maintenant, f.arguments.depart)).toEqual(f.enveloppe.resultat);
});
test("la nouvelle lecture est DIRECTE ; un couple ou enveloppe passée au lecteur brut est illisible", () => {
  expect(OUTIL_LECTURE_STRATEGIQUE).toBe("m9_produire_lecture_strategique");
  expect(interpreter(fixtures.reponses.mesure.enveloppe, "directe", v => lire(v)).ok).toBe(true);
  expect(lire(fixtures.reponses.mesure.enveloppe)).toBeNull();
  expect(lire({ accepte: true, resultat: mesure })).toBeNull();
});
test("la preuve, l'action proposée et la décision restent explicites, aucun calcul", () => {
  const lu = lire(mesure);
  expect(lu?.lectures[0]).toMatchObject({ metric_id: "m8_ecart_duree_pct", version_definition: "ab".repeat(32),
    chantier: "wct-fictif-1", valeur: "100.00", unite: "pourcentage", sens: "au_dessus", seuil: "50.00",
    action_proposee_par_m8: "Revoir le chantier wct-fictif-1 avec m04-field-ops.", statut_decision: "en_attente_du_proprietaire" });
  expect(lu?.decision).toEqual({ prise_par_m9: false, a_prendre_par: "nathan_owner", requise: true });
  expect(lu?.lectures[0]).not.toHaveProperty("lead_id");
  expect(lire(fixtures.reponses.sans_action.enveloppe.resultat)?.lectures[0].action_proposee_par_m8).toBeNull();
});
test("les manques et alertes de qualité non relues ne deviennent pas des mesures favorables", () => {
  expect(lire(fixtures.reponses.manques.enveloppe.resultat)?.manques).toEqual({ seuils_a_configurer: ["m8_ecart_marge_pct"], alertes_de_qualite_non_relues: 0 });
  expect(lire(fixtures.reponses.qualite.enveloppe.resultat)?.manques).toEqual({ seuils_a_configurer: [], alertes_de_qualite_non_relues: 1 });
});
test("pages courantes : première, suivante puis depart==total légal, pas total inventé depuis la page", () => {
  expect(lire(premiere)?.affichage).toMatchObject({ depart: 0, n_lectures: 20, affichees: 8, reste: 12, prochain_depart: 8 });
  expect(lire(fixtures.reponses.suite.enveloppe.resultat, 8)?.affichage.depart).toBe(8);
  const fin = lire(fixtures.reponses.fin.enveloppe.resultat, 20);
  expect(fin?.lectures).toEqual([]);
  expect(fin?.decision.requise).toBe(true); // décision globale reçue, pas déduite de la page vide
  expect(fin?.affichage).toMatchObject({ n_lectures: 20, affichees: 0, reste: 0, prochain_depart: null, message: null });
  expect(lire(premiere, 21)).toBeNull();
});
test("référence ISO d'origine : le jour local reste celui fourni, même si UTC serait la veille", () => {
  const raw = clone(fixtures.reponses.vide.enveloppe.resultat);
  expect(lireLectureStrategique(raw, "2026-09-28T00:30:00+14:00", 0)).not.toBeNull();
  expect(lireLectureStrategique(raw, "2026-09-27T23:30:00-14:00", 0)).toBeNull();
});
test("montant négatif, unité inconnue et précision native restent en texte, aucune comparaison recalculée", () => {
  const raw = clone(mesure); raw.lectures[0].valeur = "-100.00"; raw.lectures[0].seuil = "-200.00"; raw.lectures[0].unite = "unite_future";
  expect(lire(raw)?.lectures[0]).toMatchObject({ valeur: "-100.00", seuil: "-200.00", unite: "unite_future" });
});

const corruptions: [string, (v: any) => void][] = [
  ["M9 prétend décider", v => v.decision.prise_par_m9 = true],
  ["fausse décision booléenne", v => v.decision.prise_par_m9 = "false"],
  ["nécessité contredit le total", v => v.decision.requise = false],
  ["décideur absent", v => delete v.decision.a_prendre_par],
  ["jour d'un autre appel", v => v.jour = "2026-09-29"],
  ["période d'un autre jour", v => v.periode.au = "2026-09-29"],
  ["période inversée", v => v.periode.du = "2026-09-30"],
  ["date inexistante", v => v.periode.du = "2026-02-30"],
  ["autre type", v => v.type = "BRIEFING_MATIN"],
  ["extra JSON de contact", v => v.client_contact = "fictif"],
  ["extra instruction dans preuve", v => v.lectures[0].instructions = "fictif"],
  ["clé requise absente", v => delete v.lectures[0].seuil],
  ["montant numérique", v => v.lectures[0].valeur = 100],
  ["NaN texte", v => v.lectures[0].valeur = "NaN"],
  ["infini texte", v => v.lectures[0].valeur = "Infinity"],
  ["NaN nombre", v => v.lectures[0].valeur = NaN],
  ["exposant", v => v.lectures[0].seuil = "5e1"],
  ["décimale hors catalogue", v => v.lectures[0].valeur = "100.000"],
  ["version illisible", v => v.lectures[0].version_definition = "empreinte inconnue"],
  ["sens inconnu", v => v.lectures[0].sens = "autre"],
  ["statut décision inconnu", v => v.lectures[0].statut_decision = "approuve"],
  ["action absente confondue avec null", v => delete v.lectures[0].action_proposee_par_m8],
  ["source absente", v => delete v.lectures[0].source],
  ["compteur booléen", v => v.manques.alertes_de_qualite_non_relues = true],
  ["compteur qualité négatif", v => v.manques.alertes_de_qualite_non_relues = -1],
  ["compteur au-delà entier exact", v => v.affichage.n_lectures = Number.MAX_SAFE_INTEGER + 1],
  ["total fractionnaire", v => v.affichage.n_lectures = 1.5],
  ["départ inattendu", v => v.affichage.depart = 1],
  ["affichées incohérentes", v => v.affichage.affichees = 0],
  ["reste incohérent", v => v.affichage.reste = 1],
  ["curseur malgré fin", v => v.affichage.prochain_depart = 1],
  ["message de suite malgré fin", v => v.affichage.message = "suite"],
  ["borne hors socle", v => v.affichage.borne_caracteres = 6000],
  ["taille dépasse borne", v => v.affichage.taille_caracteres = 5901],
  ["taille sous-déclare même JSON compact", v => v.affichage.taille_caracteres = 2],
  ["preuves absentes", v => v.preuves_m8 = []],
  ["groupe absent", v => v.par_metrique = []],
  ["groupe doublonné", v => v.par_metrique.push(v.par_metrique[0])],
  ["preuve dupliquée", v => v.preuves_m8.push(v.preuves_m8[0])],
  ["groupe d'une autre métrique", v => v.par_metrique[0].metric_id = "autre"],
  ["alerte sans groupe", v => v.lectures[0].metric_id = "autre"],
  ["destinataire incohérent", v => v.lectures[0].a_qui = "autre"],
  ["nombre de chantiers dépasse alertes", v => v.par_metrique[0].nb_chantiers = 2],
  ["alerte comptée au-delà total", v => v.par_metrique[0].nb_alertes = 2],
];
test.each(corruptions)("contrat illisible : %s", (_nom, corrompre) => {
  const raw = clone(mesure); corrompre(raw); expect(lire(raw)).toBeNull();
});
test.each([
  ["curseur saute ligne", (v: any) => v.affichage.prochain_depart++],
  ["message de suite manquant", (v: any) => v.affichage.message = null],
  ["deux occurrences du même événement", (v: any) => v.lectures[1] = v.lectures[0]],
  ["groupe prétend moins d'alertes que la page", (v: any) => v.par_metrique[0].nb_alertes = 1],
  ["groupe prétend moins de chantiers que la page", (v: any) => v.par_metrique[0].nb_chantiers = 1],
] as [string, (v: any) => void][])("page partielle illisible : %s", (_nom, corrompre) => {
  const raw = clone(premiere); corrompre(raw); expect(lire(raw)).toBeNull();
});
test("compteurs globaux : le groupe ne peut sous-déclarer le total même si la page tient", () => {
  const raw = clone(premiere); raw.par_metrique[0].nb_alertes = 19; raw.par_metrique[0].nb_chantiers = 19;
  expect(lire(raw)).toBeNull();
});
test("aucun getter profond n'est exécuté", () => {
  const raw = clone(mesure), getter = jest.fn(() => false);
  Object.defineProperty(raw.decision, "prise_par_m9", { get: getter, enumerable: true });
  expect(lire(raw)).toBeNull(); expect(getter).not.toHaveBeenCalled();
});
test("héritage, classe, cycle, symbole et trou dans les lectures refusés", () => {
  const herite = Object.assign(Object.create({ decision: mesure.decision }), mesure);
  const cycle = clone(mesure); cycle.resume = cycle;
  const symbole = clone(mesure); symbole[Symbol("invisible")] = "x";
  const trou = clone(mesure); delete trou.lectures[0];
  for (const raw of [herite, cycle, symbole, trou, new Date()]) expect(lire(raw)).toBeNull();
});
test("JSON d'un autre realm et prototype null restent lisibles et détachés", () => {
  expect(lire(runInNewContext("JSON.parse(texte)", { texte: JSON.stringify(mesure) }))).toEqual(mesure);
  const raw = clone(mesure), lu = lire(Object.assign(Object.create(null), raw));
  expect(lu).not.toBeNull(); raw.lectures[0].valeur = "0.00"; expect(lu?.lectures[0].valeur).toBe("100.00");
});
test("arguments explicitement fournis, aucun appel d'horloge", () => {
  const spy = jest.spyOn(Date, "now").mockImplementation(() => { throw new Error("horloge interdite"); });
  try {
    expect(construireArgumentsLectureStrategique(maintenant)).toEqual({ maintenant, depart: 0 });
    expect(construireArgumentsLectureStrategique(maintenant, 8)).toEqual({ maintenant, depart: 8 });
    expect(lire(mesure)?.jour).toBe("2026-09-28");
  } finally { spy.mockRestore(); }
});
test.each(["2026-09-28", "2026-09-28T07:00:00", "2026-02-30T07:00:00Z", "2026-09-28T24:00:00Z", "2026-09-28T07:00:00+24:00", ""])("référence illisible refuse avant HTTP : %s", (r) => {
  expect(() => construireArgumentsLectureStrategique(r)).toThrow("Référence ISO avec fuseau ou départ M9 invalide.");
  expect(lireLectureStrategique(mesure, r, 0)).toBeNull();
});
test.each([-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])("départ illisible %s", (depart) => {
  expect(() => construireArgumentsLectureStrategique(maintenant, depart)).toThrow();
  expect(lireLectureStrategique(mesure, maintenant, depart)).toBeNull();
});

test.each(Object.entries(fixtures.capturesHttp.lectures))("DTO HTTP MCP réel DIRECT %s", (_nom, c) => {
  expect(c.fictif).toBe(true); expect(c.all_entire_tables_unchanged).toBe(true);
  expect(c.source_sha256).toMatch(/^[0-9a-f]{64}$/);
  const lu = interpreter(c.enveloppe, "directe", raw => lireLectureStrategique(raw, c.arguments.maintenant, c.arguments.depart));
  expect(lu.ok).toBe(true);
  if (!lu.ok) throw new Error("DTO natif réel refusé");
  expect(lu.valeur).toEqual(c.enveloppe.resultat);
});
test("preuve ordinaire HTTP même WCT : matériau40.00/seuil30.00, sans budget ni montant fabriqué", () => {
  const c = fixtures.capturesHttp.lectures["ordinaire-40-30"];
  const lu = lireLectureStrategique(c.enveloppe.resultat, c.arguments.maintenant, c.arguments.depart);
  expect(lu?.lectures[0]).toMatchObject({ metric_id: "m8_ecart_materiaux_max_pct", valeur: "40.00", seuil: "30.00",
    chantier: "e36d9748d1f4806da4e15fc08bce3939dcc10e3247d921b281fdd091f198498e",
    version_definition: "db98dea358392c834b1261bde2d416deae2df826c8060dd5eb8daa089e9f8200" });
});
test("le refus natif depart>total reste un refus et ne devient pas une page vide", () => {
  const c = fixtures.capturesHttp.refus["depart-hors-borne"];
  const lu = interpreter(c.enveloppe, "directe", raw => lireLectureStrategique(raw, c.arguments.maintenant, c.arguments.depart));
  expect(lu.ok).toBe(false);
  expect(lireLectureStrategique(c.enveloppe, c.arguments.maintenant, c.arguments.depart)).toBeNull();
});
