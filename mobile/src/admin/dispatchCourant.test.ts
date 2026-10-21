import { creerChargeurDispatch, interpreterDispatch, type DependancesDispatch } from "./dispatchCourant";
import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { enveloppeCouple, enveloppeDirecte, enveloppeRefusee, HORLOGE_DE_TEST, reponse } from "./donneesDeTest";
import type { ParametresAppelOutil } from "../protocole/client";
import { pageDispatchFictive, pageSuivanteFictive, meteoInterventionFictive, retardsIncidentsFictifs, varianteFictive } from "../m4/fixturesDispatch";

function harnais() {
  definirConfigurationAppel({ urlBase: "https://fictif.exemple.ca", jeton: "jeton-fictif", appareilId: "device-fictif" });
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "admin-fictif", role: "admin" });
  const depot = new DepotCleValeurMemoire();
  const appelerOutil = jest.fn(async (_params: ParametresAppelOutil) => ({ ok: true as const, result: enveloppeDirecte(pageDispatchFictive) }));
  const obtenirDepot = jest.fn(async () => depot);
  let connectee = true;
  const d: DependancesDispatch = { capturerSession: capturerSessionAdminLecture, obtenirDepot, appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch, horloge: () => ({ ...HORLOGE_DE_TEST,
      maintenant: new Date("2026-10-06T16:00:00Z") }), enLigne: () => connectee };
  return { d, appelerOutil, obtenirDepot, depot, chargeur: creerChargeurDispatch(d), horsLigne: () => { connectee = false; } };
}
afterEach(() => { definirPersonneConfirmee(null); definirConfigurationAppel(null); });

test("un rôle vendeur est arrêté avant dépôt et HTTP", async () => {
  const h = harnais();
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "admin-fictif", role: "seller" });
  expect(await h.chargeur.chargerPage("planifiee")).toBeNull();
  expect(await h.chargeur.chargerRetards()).toBeNull();
  expect(h.obtenirDepot).not.toHaveBeenCalled(); expect(h.appelerOutil).not.toHaveBeenCalled();
});
test("la session remplacée pendant l'ouverture du dépôt interdit HTTP", async () => {
  const h = harnais();
  h.obtenirDepot.mockImplementation(async () => { definirPersonneConfirmee(null); return h.depot; });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(h.appelerOutil).not.toHaveBeenCalled();
});
test("huit éléments, curseur serveur exact, deuxième page remplace la première", async () => {
  const h = harnais(), curseur = pageDispatchFictive.page.curseur_suivant;
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "serveur", valeur: { page: { taille: 8 } } });
  h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeDirecte(pageSuivanteFictive) });
  const suite = await h.chargeur.chargerPage("planifiee", curseur);
  expect(suite).toMatchObject({ source: "serveur", valeur: { page: { curseur, taille: 8 } } });
  if (suite?.source === "serveur") expect(suite.valeur.interventions).toHaveLength(8);
  expect(h.appelerOutil.mock.calls[1]?.[0]).toMatchObject({ requete: { tool: "m4_lister_interventions", args: { statut: "planifiee", curseur, taille_page: 8 } } });
});
test("deux pages en vol, B avant A : admin valide, seule B reste courante et en cache", async () => {
  const h = harnais(), curseur = pageDispatchFictive.page.curseur_suivant;
  const autorite = capturerSessionAdminLecture();
  let signalerEntreeA!: () => void;
  let repondreA!: (r: Awaited<ReturnType<typeof h.appelerOutil>>) => void;
  const entreeA = new Promise<void>(resolve => { signalerEntreeA = resolve; });
  h.appelerOutil.mockImplementationOnce(() => new Promise(resolve => {
    repondreA = resolve;
    signalerEntreeA();
  })).mockResolvedValueOnce({ ok: true, result: enveloppeDirecte(pageSuivanteFictive) });

  const a = h.chargeur.chargerPage("planifiee");
  await entreeA; // A a réellement atteint le transport avant que B remplace ce slot.
  const b = await h.chargeur.chargerPage("planifiee", curseur);
  expect(b).toMatchObject({ source: "serveur", valeur: { page: { curseur, taille: 8 } } });
  expect(h.appelerOutil.mock.calls.map(c => c[0].requete)).toEqual([
    { tool: "m4_lister_interventions", args: { statut: "planifiee", curseur: null, taille_page: 8 } },
    { tool: "m4_lister_interventions", args: { statut: "planifiee", curseur, taille_page: 8 } },
  ]);
  if (b?.source !== "serveur") throw new Error("La page B légitime doit rester accessible");

  repondreA({ ok: true, result: enveloppeDirecte(pageDispatchFictive) });
  expect(await a).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(autorite.session?.personne).toBe("admin-fictif");
  expect(autorite.courante()).toBe(true);
  expect(h.depot.cles()).toHaveLength(1);

  h.horsLigne();
  expect(await h.chargeur.chargerPage("planifiee", curseur)).toMatchObject({ source: "cache", valeur: b.valeur });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune" });
  expect(await h.chargeur.chargerPage("planifiee", curseur)).toMatchObject({ source: "cache", valeur: b.valeur });
  expect(h.appelerOutil).toHaveBeenCalledTimes(2);
  expect(h.depot.cles()).toHaveLength(1);
});
test("cache relisible, personnel, lié au curseur exact ; hors ligne aucun HTTP", async () => {
  const h = harnais(); await h.chargeur.chargerPage("planifiee"); h.horsLigne();
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "cache" });
  expect(await h.chargeur.chargerPage("planifiee", pageDispatchFictive.page.curseur_suivant)).toMatchObject({ source: "aucune" });
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "autre-fictif", role: "admin" });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune" });
  expect(h.appelerOutil).toHaveBeenCalledTimes(1);
});
test("un refus actuel ne relit jamais une page gardée", async () => {
  const h = harnais(); await h.chargeur.chargerPage("planifiee");
  h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeRefusee("REJ-ACCES-INTERDIT") });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "refus", verdict: { code: "REJ-ACCES-INTERDIT" } });
  h.horsLigne(); expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune" });
  expect(await creerChargeurDispatch(h.d).chargerPage("planifiee")).toMatchObject({ source: "aucune" });
});
test("refus connu même si le dépôt ne s'ouvre pas : aucune copie à sa réouverture", async () => {
  const h = harnais(); await h.chargeur.chargerPage("planifiee");
  h.obtenirDepot.mockRejectedValueOnce(new Error("SQLite fictif fermé"));
  h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeRefusee("REJ-ACCES-INTERDIT") });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "refus" });
  h.horsLigne(); expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune" });
  expect(await creerChargeurDispatch(h.d).chargerPage("planifiee")).toMatchObject({ source: "aucune" });
});
test("arguments impossibles : aucun dépôt ni HTTP, aucune nouvelle clé", async () => {
  const h = harnais();
  for (const r of [h.chargeur.chargerPage("autre"), h.chargeur.chargerPage("planifiee", "faux"),
    h.chargeur.chargerMeteo("0".repeat(64), "2026-02-30"), h.chargeur.chargerPreparation("faux")])
    expect(await r).toMatchObject({ source: "aucune", raison: { code: "arguments_invalides" } });
  expect(h.obtenirDepot).not.toHaveBeenCalled(); expect(h.appelerOutil).not.toHaveBeenCalled();
});
test("réponse tardive après retrait du rôle : masquée et aucun cache", async () => {
  const h = harnais();
  h.appelerOutil.mockImplementation(async () => { definirPersonneConfirmee(null); return { ok: true, result: enveloppeDirecte(pageDispatchFictive) }; });
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "admin-fictif", role: "admin" }); h.horsLigne();
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "aucune" });
});
test("météo : date civile explicite, aucune prévision envoyée, cache date séparé", async () => {
  const h = harnais(), id = meteoInterventionFictive.intervention_id;
  h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeCouple(meteoInterventionFictive) });
  expect(await h.chargeur.chargerMeteo(id, "2026-10-06")).toMatchObject({ source: "serveur" });
  expect(h.appelerOutil.mock.calls[0]?.[0]).toMatchObject({ requete: { tool: "m4_lire_meteo_intervention", args: { intervention_id: id, date: "2026-10-06" } } });
  h.horsLigne(); expect(await h.chargeur.chargerMeteo(id, "2026-10-06")).toMatchObject({ source: "cache" });
  expect(await h.chargeur.chargerMeteo(id)).toMatchObject({ source: "aucune" });
});
test("les retards sont serveur seulement ; référence avec fuseau, dépôt jamais ouvert", async () => {
  const h = harnais(); h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeCouple(retardsIncidentsFictifs) });
  expect(await h.chargeur.chargerRetards()).toMatchObject({ source: "serveur" });
  expect(h.appelerOutil.mock.calls[0]?.[0]).toMatchObject({ requete: { args: { horodatage_reference: "2026-10-06T12:00:00-04:00" } } });
  h.horsLigne(); expect(await h.chargeur.chargerRetards()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(h.obtenirDepot).not.toHaveBeenCalled(); expect(h.appelerOutil).toHaveBeenCalledTimes(1);
});
test("une panne SQLite ne transforme pas une lecture serveur en absence", async () => {
  const h = harnais(); h.obtenirDepot.mockRejectedValue(new Error("SQLite fictif"));
  expect(await h.chargeur.chargerPage("planifiee")).toMatchObject({ source: "serveur" });
});
test("préparation d'une autre intervention : refus de présentation et de cache", async () => {
  const h = harnais(); h.appelerOutil.mockResolvedValue({ ok: true, result: reponse("preparation_lead_v2") });
  expect(await h.chargeur.chargerPreparation("0".repeat(64))).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
  expect(h.depot.cles()).toHaveLength(0);
});
test("digest d'un autre jour ou d'une autre référence : jamais présenté comme la demande actuelle", async () => {
  const h = harnais(); h.appelerOutil.mockResolvedValue({ ok: true, result: reponse("digest") });
  expect(await h.chargeur.chargerDigest()).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
  expect(h.depot.cles()).toHaveLength(0);
});
test("cache borné : une page par statut et un digest, même après plusieurs références", async () => {
  const h = harnais(); await h.chargeur.chargerPage("planifiee");
  h.appelerOutil.mockResolvedValue({ ok: true, result: enveloppeDirecte(pageSuivanteFictive) });
  await h.chargeur.chargerPage("planifiee", pageDispatchFictive.page.curseur_suivant);
  expect(h.depot.cles()).toHaveLength(1);
  let maintenant = new Date("2026-10-06T16:00:00Z");
  const chargeur = creerChargeurDispatch({ ...h.d, horloge: () => ({ maintenant, decalageMinutesUTC: -240 }) });
  h.appelerOutil.mockImplementation(async p => {
    const brut = reponse("digest");
    brut.resultat.resultat.date_cible = p.requete.args!.date_cible;
    brut.resultat.resultat.horodatage_reference = p.requete.args!.horodatage_reference;
    return { ok: true, result: brut };
  });
  expect(await chargeur.chargerDigest()).toMatchObject({ source: "serveur" });
  maintenant = new Date("2026-10-06T16:01:00Z");
  expect(await chargeur.chargerDigest()).toMatchObject({ source: "serveur" });
  expect(h.depot.cles()).toHaveLength(2);
  h.horsLigne(); maintenant = new Date("2026-10-06T16:02:00Z");
  expect(await chargeur.chargerDigest()).toMatchObject({ source: "cache", valeur: { horodatageReference: "2026-10-06T12:01:00-04:00" } });
});
test("l'enveloppe est copiée sans exécuter un getter ; refus malformé sans cache", () => {
  const getter = jest.fn(() => true), brut = { resultat: varianteFictive(pageDispatchFictive) };
  Object.defineProperty(brut, "ok", { get: getter, enumerable: true });
  expect(interpreterDispatch(brut, "directe", () => null)).toMatchObject({ ok: false, genre: "illisible" });
  expect(getter).not.toHaveBeenCalled();
  const refus = { ok: true, resultat: { accepte: false } }; Object.defineProperty(refus, "secret", { get: getter });
  expect(interpreterDispatch(refus, "directe", () => null)).toMatchObject({ ok: false, genre: "refus" });
  expect(getter).not.toHaveBeenCalled();
  const transitoire = { ...refus, erreur: "budget_epuise" }; Object.defineProperty(transitoire, "secret", { get: getter });
  expect(interpreterDispatch(transitoire, "directe", () => null)).toMatchObject({ ok: false, genre: "refus" });
});
