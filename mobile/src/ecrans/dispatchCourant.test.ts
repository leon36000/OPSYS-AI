import type { ResultatSection } from "../admin/lecture";
import { meteoInterventionFictive, pageDispatchFictive, retardsIncidentsFictifs } from "../m4/fixturesDispatch";
import { lireMeteoIntervention } from "../m4/meteoIntervention";
import type { MeteoIntervention } from "../m4/meteoIntervention";
import { construireArgumentsPageDispatch, lirePageDispatch } from "../m4/paginationDispatch";
import { lireRetardsIncidents } from "../m4/retardsIncidents";
import type { RetardsIncidents } from "../m4/retardsIncidents";
import { presenterPage, vueMeteo, vueRetards } from "./dispatchCourant";
import type { Message, VueSection } from "./adminCommun";

const DECALAGE = -240;
const LUE_LE = "2026-10-06T16:00:00Z";
const serveur = <T>(valeur: T): ResultatSection<T> => ({ source: "serveur", valeur, misAJourLe: LUE_LE });
function contenu<T>(vue: VueSection<T>): T {
  if (vue.genre !== "contenu") throw new Error("La capture fictive native doit donner du contenu");
  return vue.contenu;
}
function meteo(): MeteoIntervention {
  const v = lireMeteoIntervention(meteoInterventionFictive, {
    intervention_id: meteoInterventionFictive.intervention_id, date: "2026-10-06",
  });
  if (!v) throw new Error("Capture météo native illisible");
  return v;
}
function retards(): RetardsIncidents {
  const v = lireRetardsIncidents(retardsIncidentsFictifs, retardsIncidentsFictifs.reference);
  if (!v) throw new Error("Capture de retards native illisible");
  return v;
}
const m = (cle: string, params?: Message["params"]): Message => params ? { cle: `admin.dispatch.${cle}`, params } : { cle: `admin.dispatch.${cle}` };

test("page native courante : huit affichées, 28 restantes, curseur réel et absence de snapshot", () => {
  const page = lirePageDispatch(pageDispatchFictive, construireArgumentsPageDispatch("planifiee", null, 8));
  if (!page) throw new Error("Capture native paginée illisible");
  const avant = JSON.stringify(page);
  const vue = presenterPage(page);
  expect(vue.lignes).toEqual([
    m("page.resume", { affichees: 8, total: 36, reste: 28 }), m("page.ordre"), m("page.courante"),
  ]);
  expect(vue.curseurSuivant).toBe(pageDispatchFictive.page.curseur_suivant);
  expect(JSON.stringify(page)).toBe(avant);
  const limite = presenterPage({ ...page, illisibles: 2, page: { ...page.page, borne_atteinte: true } });
  expect(limite.lignes).toContainEqual(m("page.borne"));
  expect(limite.lignes).toContainEqual(m("page.illisibles", { nombre: 2 }));
});

test("page réellement vide : compte nul et aucun curseur, sans inférer un résultat global", () => {
  const page = lirePageDispatch({ interventions: [], page: {
    ordre: "intervention_id croissant", curseur: null, taille_demandee: 8,
    taille: 0, total: 0, reste: 0, curseur_suivant: null, borne_atteinte: false,
  } }, construireArgumentsPageDispatch("planifiee", null, 8));
  if (!page) throw new Error("Page native vide illisible");
  expect(presenterPage(page)).toEqual({ lignes: [m("page.resume", { affichees: 0, total: 0, reste: 0 }), m("page.ordre"), m("page.courante")], curseurSuivant: null });
});

test("météo native : émission/source/heure saisie distinctes de la date de lecture", () => {
  const v = meteo(), avant = JSON.stringify(v);
  const section = vueMeteo(serveur(v), DECALAGE);
  expect(section).toMatchObject({ genre: "contenu", lue: { cle: "admin.commun.lueLe", params: { date: "2026-10-06 12:00" } }, horsLigne: null });
  const vue = contenu(section), c = vue.creneaux[0];
  expect(c.id).toBe(v.intervention_id);
  expect(vue.lignes).toContainEqual(m("meteo.statuts.ok"));
  expect(c.lignes).toContainEqual(m("meteo.creneau", { equipe: "eq-a", jour: 1, debut: "08:12", fin: "10:12" }));
  expect(c.lignes).toContainEqual(m("meteo.date", { date: "2026-10-06" }));
  expect(c.lignes).toContainEqual(m("meteo.prevision", { source: "saisie_manuelle", date: "2026-10-04 18:00" }));
  expect(c.lignes).toContainEqual(m("meteo.heureType", { type: "heure_d_emission_saisie" }));
  expect(c.lignes).toContainEqual(m("meteo.saisiPar", { personne: "nathan" }));
  expect(c.lignes).toContainEqual(m("meteo.planCourant"));
  expect(vue.lignes).toContainEqual(m("meteo.attributionsAbsentes"));
  expect(JSON.stringify(v)).toBe(avant);
});

test("ok sans prévision lorsque tous les risques sont sans objet : aucun temps ou zéro météo inventé", () => {
  const v = meteo();
  const c = { ...v.creneaux[0], prevision: null, regles: [], sans_objet: ["vent", "pluie", "gel", "verglas", "chaleur"] };
  const vue = contenu(vueMeteo(serveur({ ...v, creneaux: [c] }), DECALAGE));
  expect(vue.lignes).toContainEqual(m("meteo.statuts.ok"));
  expect(vue.creneaux[0].lignes).toContainEqual(m("meteo.previsionAbsente"));
  for (const risque of c.sans_objet) expect(vue.creneaux[0].lignes).toContainEqual(m("meteo.sansObjet", { risque }));
  expect(vue.creneaux[0].textes).toEqual([]);
});

test("date/service absents, plan périmé, manques et cause restent explicites", () => {
  const v = meteo();
  const c = { ...v.creneaux[0], date: null, service: null, plan_perime: true, prevision: null,
    statut: "inconnu" as const, regles: [], a_configurer: ["seuil du vent à déclarer"],
    cause: { code: "REJ-CHAMP-MANQUANT", detail: "Date civile non fournie (fictif)" } };
  const vue = contenu(vueMeteo(serveur({ ...v, statut: "inconnu", creneaux: [c] }), DECALAGE));
  expect(vue.creneaux[0].lignes).toEqual(expect.arrayContaining([
    m("meteo.dateAbsente"), m("meteo.serviceAbsent"), m("meteo.planPerime"),
    m("meteo.aConfigurer", { manque: "seuil du vent à déclarer" }), m("meteo.cause", { code: "REJ-CHAMP-MANQUANT" }),
  ]));
  expect(vue.creneaux[0].textes).toEqual(["Date civile non fournie (fictif)"]);
  const aucune = contenu(vueMeteo(serveur({ ...v, statut: "inconnu", plan_id: null, creneaux: [], cause: c.cause }), DECALAGE));
  expect(aucune.lignes).toContainEqual(m("meteo.planAbsent"));
  expect(aucune.textes).toContain(c.cause.detail);
});

test.each(["ok", "inconnu", "validation_requise", "bloquant"] as const)("statut météo %s vient du serveur, sans requalification", statut => {
  const v = meteo();
  const vue = contenu(vueMeteo(serveur({ ...v, statut, creneaux: [{ ...v.creneaux[0], statut }] }), DECALAGE));
  expect(vue.lignes).toContainEqual(m(`meteo.statuts.${statut}`));
});

test("citation fournisseur, attribution et détail sûrs sont montrables", () => {
  const v = meteo();
  const c = { ...v.creneaux[0], prevision: { source: "ECCC", emise_le: "2026-10-04T18:00:00-04:00", heure_type: "heure_source",
    licence: "Licence ouverte", forfait: "déclaré", collection: "ensemble météo", page_meteo: "page déclarée" },
    regles: [{ risque: "vent", statut: "validation_requise" as const, detail: "Vent au seuil déclaré (fictif)" }] };
  const vue = contenu(vueMeteo(serveur({ ...v, creneaux: [c], attributions: [{ source: "ECCC", attribution: "Données météo ECCC (fictif)" }] }), DECALAGE));
  expect(vue.lignes).toContainEqual(m("meteo.attribution", { source: "ECCC", attribution: "Données météo ECCC (fictif)" }));
  expect(vue.creneaux[0].textes).toEqual(["Vent au seuil déclaré (fictif)"]);
  expect(vue.creneaux[0].lignes).toEqual(expect.arrayContaining([
    m("meteo.licence", { licence: "Licence ouverte" }), m("meteo.forfait", { forfait: "déclaré" }),
    m("meteo.collection", { collection: "ensemble météo" }), m("meteo.pageMeteo", { page: "page déclarée" }),
  ]));
});

test("détails météo natifs km/h et mm/h restent littéraux, sans ouvrir un chemin combiné", () => {
  const v = meteo();
  const vue = contenu(vueMeteo(serveur(v), DECALAGE));
  for (const regle of v.creneaux[0].regles) expect(vue.creneaux[0].textes).toContain(regle.detail);
  const dangereux = "vent prévu 10 km/h ; lire /srv/prive/config.yaml";
  const c = { ...v.creneaux[0], regles: [{ risque: "vent", statut: "inconnu" as const, detail: dangereux }] };
  const masquee = contenu(vueMeteo(serveur({ ...v, creneaux: [c] }), DECALAGE));
  expect(masquee.creneaux[0].textes).toEqual([]);
  expect(masquee.creneaux[0].lignes).toContainEqual(m("texteMasque"));
});

test("chaque texte météo avec chemin ou commande est masqué, y compris paramètres de citation et attribution", () => {
  const v = meteo(), interdit = "opsys-metier /srv/prive/config.yaml";
  const c = { ...v.creneaux[0], equipe: interdit, service: interdit,
    cause: { code: interdit, detail: interdit }, a_configurer: [interdit],
    regles: [{ risque: "vent", statut: "inconnu" as const, detail: interdit }],
    prevision: { source: interdit, emise_le: "2026-10-04T18:00:00-04:00", heure_type: interdit, saisi_par: interdit, reference: interdit } };
  const vue = contenu(vueMeteo(serveur({ ...v, cause: c.cause, creneaux: [c], attributions: [{ source: interdit, attribution: interdit }] }), DECALAGE));
  expect(JSON.stringify(vue)).not.toContain(interdit);
  expect(vue.lignes).toContainEqual(m("texteMasque"));
  expect(vue.creneaux[0].lignes).toContainEqual(m("texteMasque"));
});

test("retards natifs : référence de l'appelant, âge du serveur et non-mesurabilité de la cédule", () => {
  const v = retards(), avant = JSON.stringify(v);
  const vue = contenu(vueRetards(serveur(v), DECALAGE));
  expect(vue.lignes).toEqual(expect.arrayContaining([
    m("retards.referenceAppelant", { date: "2026-10-06T12:00:00-04:00" }), m("retards.seuil", { heures: 24 }), m("retards.nonMesurable"),
    m("retards.reports", { total: 1, affiches: 1, reste: 0 }), m("retards.incidents", { total: 1, affiches: 1, reste: 0, bloques: 1 }),
  ]));
  expect(vue.reports[0].id).toBe(v.reports.liste[0].intervention_id);
  expect(vue.reports[0].lignes).toContainEqual(m("retards.depuis", { date: "2026-10-05 07:00" }));
  expect(vue.reports[0].lignes).toContainEqual(m("retards.origine.serveur"));
  expect(vue.reports[0].lignes).toContainEqual(m("retards.heures", { heures: 29 }));
  expect(vue.incidents[0].lignes).toContainEqual(m("retards.bloquee"));
  expect(vue.textes).toEqual([v.retard_sur_cedule.manque]);
  expect(JSON.stringify(v)).toBe(avant);
});

test.each([0, null])("âge %s ne se transforme pas en défaut ; origine appelant visible", heures => {
  const v = retards();
  const vue = contenu(vueRetards(serveur({ ...v, reports: { ...v.reports,
    liste: [{ ...v.reports.liste[0], origine_heure: "appelant", heures_ecoulees: heures }] } }), DECALAGE));
  expect(vue.reports[0].lignes).toContainEqual(m("retards.origine.appelant"));
  expect(vue.reports[0].lignes).toContainEqual(heures === null ? m("retards.heuresInconnues") : m("retards.heures", { heures: 0 }));
  if (heures === null) expect(vue.reports[0].lignes).not.toContainEqual(m("retards.heures", { heures: 0 }));
});

test("retards omis : counts conservés, suite technique masquée sans geste proposé", () => {
  const v = retards();
  const vue = contenu(vueRetards(serveur({ ...v, reports: { ...v.reports, total: 2, reste: 1, suite: "m4_lister_interventions (statut reportee)" },
    incidents: { ...v.incidents, total: 3, reste: 2, suite: "m4_lister_pending_review" },
    retard_sur_cedule: { statut: "non_mesurable", manque: "opsys-metier /srv/config.yaml" } }), DECALAGE));
  expect(vue.lignes).toContainEqual(m("retards.omis", { nombre: 1 }));
  expect(vue.lignes).toContainEqual(m("retards.omis", { nombre: 2 }));
  expect(vue.lignes.filter(x => x.cle === "admin.dispatch.retards.suiteNonLue")).toHaveLength(2);
  expect(JSON.stringify(vue)).not.toMatch(/m4_lister|opsys-metier|\/srv/);
  expect(vue.textes).toEqual([]);
});

test("relevé réellement vide : les deux listes le disent sans nier le retard sur cédule non mesurable", () => {
  const v = retards();
  const zero = { total: 0, affiches: 0, reste: 0, suite: null, liste: [] };
  const vue = contenu(vueRetards(serveur({ ...v, reports: { ...zero, par_motif: { client_absent: 0, meteo: 0, decision_admin: 0 } },
    incidents: { ...zero, par_type: { ecart_metier: 0, anomalie_pointage: 0 }, bloques: 0 } }), DECALAGE));
  expect(vue.reports).toEqual([]); expect(vue.incidents).toEqual([]);
  expect(vue.lignes.filter(x => x.cle === "admin.dispatch.retards.vide")).toHaveLength(2);
  expect(vue.lignes).toContainEqual(m("retards.nonMesurable"));
});

test("cache daté, refus et indisponibilité restent des issues distinctes, détails techniques masqués", () => {
  const cache = vueMeteo({ source: "cache", valeur: meteo(), misAJourLe: LUE_LE, raisonHorsLigne: { code: "hors_ligne", detail: "" } }, DECALAGE);
  expect(cache).toMatchObject({ genre: "contenu", horsLigne: { cle: "admin.commun.cache", params: { date: "2026-10-06 12:00", code: "hors_ligne" } } });
  const refus = vueRetards({ source: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "opsys-metier /srv/prive.json" } }, DECALAGE);
  expect(refus).toEqual({ genre: "refus", avis: { cle: "admin.commun.refusSansDetail", params: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" } }, verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "" } });
  const aucune = vueMeteo({ source: "aucune", raison: { code: "hors_ligne", detail: "" } }, DECALAGE);
  expect(aucune.genre).toBe("aucune");
});

test("codes et dates techniques de section ne sortent jamais tels quels", () => {
  const interdit = "/srv/prive/config.yaml";
  const refus = vueMeteo({ source: "refus", verdict: { code: interdit, detail: interdit } }, DECALAGE);
  expect(refus.genre).toBe("refus"); expect(JSON.stringify(refus)).not.toContain(interdit);
  const cache = vueMeteo({ source: "cache", valeur: meteo(), misAJourLe: interdit, raisonHorsLigne: { code: interdit, detail: interdit } }, DECALAGE);
  expect(cache.genre).toBe("contenu"); expect(JSON.stringify(cache)).not.toContain(interdit);
});
