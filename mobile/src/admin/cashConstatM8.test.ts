import fixture from "../m8/fixturesCashLibre.json";
import { creerChargeurChiffres } from "./chiffres";
import { config, reponse, enveloppeRefusee } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { epurerVueExecutive } from "./cacheVueExecutive";
import { lireVueExecutive } from "../m8/vueExecutive";

function reponseCash(cash = fixture.calcule): Record<string, unknown> {
  const v = reponse("vue_executive_vide"); v.resultat.cash_libre = JSON.parse(JSON.stringify(cash)); return v;
}
function harnais() {
  const depot = new DepotCleValeurMemoire(), transport = jest.fn(async () => ({ ok: true, result: reponseCash() }));
  let maintenant = new Date("2026-09-30T16:00:00Z"), connectee = true;
  const configuration = { ...config(transport, { depot }), enLigne: () => connectee,
    horloge: () => ({ maintenant, decalageMinutesUTC: -240 }) };
  return { depot, transport, chargeur: creerChargeurChiffres(configuration),
    horsLigne: () => { connectee = false; }, lendemain: () => { maintenant = new Date("2026-10-01T16:00:00Z"); } };
}
test("constat natif transmis avec jour explicite ; monnaie et âge inchangés", async () => {
  expect(fixture.fictif).toBe(true); const h = harnais();
  const r = await h.chargeur.chargerVueExecutive();
  expect(r).toMatchObject({ source: "serveur", valeur: { cashLibre: { genre: "lu", age: { jours: 1, aujourdHui: "2026-09-30" },
    constat: { cashLibreCad: fixture.calcule.constat.cash_libre_cad } } } });
});
test("jour de réponse différent : aucun constat actuel ni cache produit", async () => {
  const h = harnais(); h.lendemain();
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
  expect(h.depot.cles()).toHaveLength(0);
});
test("copie fixe personnelle : âge original affichable le lendemain, aucun réseau ni recalcul", async () => {
  const h = harnais(); await h.chargeur.chargerVueExecutive(); h.horsLigne(); h.lendemain();
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "cache", valeur: { cashLibre: { age: { jours: 1, aujourdHui: "2026-09-30" } } } });
  expect(h.transport).toHaveBeenCalledTimes(1); expect(h.depot.cles()).toHaveLength(1);
});
test("refus actuel : copie invalidée, aucune reprise hors ligne sous même personne", async () => {
  const h = harnais(); await h.chargeur.chargerVueExecutive();
  h.transport.mockResolvedValue({ ok: true, result: enveloppeRefusee("REJ-ACCES-INTERDIT") });
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "refus" }); h.horsLigne();
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "aucune" });
});
test("getter malformé + refus métier : pas de cache ni getter exécuté", async () => {
  const h = harnais(); await h.chargeur.chargerVueExecutive(); const getter = jest.fn(() => "secret-fictif");
  const refuse = { ok: true, erreur: "budget_epuise", resultat: { accepte: false } };
  Object.defineProperty(refuse, "extra", { get: getter }); h.transport.mockResolvedValue({ ok: true, result: refuse });
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "refus" });
  expect(getter).not.toHaveBeenCalled(); h.horsLigne(); expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "aucune" });
});
test("refus acquis prioritaire sur tronque : verdict conservé et aucune copie reprise", async () => {
  const h = harnais(); await h.chargeur.chargerVueExecutive();
  h.transport.mockResolvedValue({ ok: true, result: { ok: true, tronque: true,
    resultat: { accepte: false, verdict: { code: "REJ-ACCES-FICTIF", detail: "Rôle retiré (fictif)" } } } });
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "refus", verdict: { code: "REJ-ACCES-FICTIF" } });
  h.horsLigne(); expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "aucune" });
});
test("cache minimal : aucun champ financier ou contact non projeté conservé", async () => {
  const h = harnais(), brut = reponse("vue_executive_vide");
  brut.resultat.cash_libre = JSON.parse(JSON.stringify(fixture.calcule));
  brut.resultat.contact_non_projete = "contact-confidentiel-fictif";
  brut.resultat.cash_libre.constat.extra_prive = "extra-confidentiel-fictif";
  brut.resultat.entonnoir.mesures[0].contact_non_projete = "mesure-confidentielle-fictive";
  h.transport.mockResolvedValue({ ok: true, result: brut });
  expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "serveur" });
  const garde = await h.depot.lire(h.depot.cles()[0]);
  for (const texte of ["contact-confidentiel-fictif", "extra-confidentiel-fictif", "mesure-confidentielle-fictive"])
    expect(garde).not.toContain(texte);
  h.horsLigne(); expect(await h.chargeur.chargerVueExecutive()).toMatchObject({ source: "cache" });
});

test.each(Object.entries(fixture.capturesHttp.lectures))("cache : capture HTTP %s restituée sans perte de projection", (_nom, capture) => {
  expect(capture.fictif).toBe(true);
  const propre = epurerVueExecutive(capture.enveloppe) as { resultat: unknown };
  expect(propre).not.toBeNull();
  expect(lireVueExecutive(propre.resultat)).toEqual(lireVueExecutive(capture.enveloppe.resultat));
});

test("cache : branches inutilisées et six listes illisibles ne gardent aucune donnée ignorée", () => {
  const brut = reponse("vue_executive_vide"), v = brut.resultat;
  v.cash_libre = JSON.parse(JSON.stringify(fixture.calcule));
  v.entonnoir.mesures[0] = { ...v.entonnoir.mesures[0], statut: "calculee", valeur: "0", manque: ["fictif-inutile-mesure"] };
  v.marge_reelle.chantiers.push({ wct_id: "WCT-fictif", devis_id: null, horodatage_completion: null,
    statut: "calculee", marge_reelle_cad: "0.00", raison: "fictif-inutile-raison", prix_definitif: "fictif-inutile-prix" });
  v.stock_a_commander = { source: "M6-fictif", statut: "manque", manque: ["configuration"],
    articles: ["fictif-inutile-stock"], n_articles: 7, reste: 7, seuils_a_configurer: true };
  for (const liste of [v.entonnoir.mesures, v.entonnoir.sources, v.entonnoir.seuils.evalues,
    v.marge_reelle.chantiers, v.manques]) liste.push({ nom: "fictif-inutile-illisible" });
  const lue = lireVueExecutive(v), propre = epurerVueExecutive(brut) as { resultat: unknown };
  expect(lue).not.toBeNull(); expect(propre).not.toBeNull();
  expect(lireVueExecutive(propre.resultat)).toEqual(lue);
  expect(JSON.stringify(propre)).not.toContain("fictif-inutile");
  v.stock_a_commander = { source: "M6-fictif", statut: "lu", n_articles: 1, reste: 0, seuils_a_configurer: false,
    articles: [{ id: "ARTICLE-fictif", resume: false, depuis: null, action_proposee: "fictif-inutile-article" }] };
  const stock = epurerVueExecutive(brut) as { resultat: unknown };
  expect(stock).not.toBeNull(); expect(lireVueExecutive(stock.resultat)).toEqual(lireVueExecutive(v));
  expect(JSON.stringify(stock)).not.toContain("fictif-inutile");
});
