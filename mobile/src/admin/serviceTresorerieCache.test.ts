import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { lireCacheSection } from "./cache";
import { enveloppeEnErreur, enveloppeRefusee, FICTIF, reponse } from "./donneesDeTest";
import cashFictif from "../m8/fixturesCashLibre.json";
import { obtenirDepotLocal } from "../stockage/service";
import { actualiserConnectiviteChiffres, chargerTresorerie, chargerVueExecutive } from "./service";

// Seule la frontière SQLite native est remplacée : service, SDK, lecteurs et gardes sont réels.
// Les sorties moteur et le constat M8 sont fictifs et déjà conservés dans leurs fixtures sourcées.
jest.mock("../stockage/service", () => ({ obtenirDepotLocal: jest.fn() }));
const obtenirDepotFictif = jest.mocked(obtenirDepotLocal);
const PERSONNE = "admin-cache-fictif", URL = "https://core-fictif.invalid", JETON = "jeton-fictif";
const fetchOriginal = globalThis.fetch;
let depot: DepotCleValeurMemoire;
let fetchFictif: jest.Mock<Promise<Response>, [RequestInfo | URL, RequestInit?]>;

function reponseHTTP(result: unknown): Response {
  return new Response(JSON.stringify({ ok: true, result }), { status: 200 });
}
function refusHTTP(status = 403): Response {
  return new Response(JSON.stringify({ ok: false, error: { type: "forbidden", message: "Refus actuel fictif" } }), { status });
}
function attente<T>() {
  let resoudre!: (valeur: T) => void;
  const promise = new Promise<T>(resolve => { resoudre = resolve; });
  return { promise, resoudre };
}
function admin(role = "admin") {
  definirPersonneConfirmee({ jeton: JETON, appareilId: "device-fictif", personne: PERSONNE, role });
}
beforeEach(() => {
  jest.useFakeTimers({ now: new Date("2026-09-30T12:00:00.000Z") });
  jest.clearAllMocks();
  expect(FICTIF).toBe(true); expect(cashFictif.fictif).toBe(true);
  depot = new DepotCleValeurMemoire(); obtenirDepotFictif.mockResolvedValue(depot);
  definirConfigurationAppel({ urlBase: URL, jeton: JETON, appareilId: "device-fictif" }); admin();
  actualiserConnectiviteChiffres(true);
  fetchFictif = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async () => reponseHTTP(reponse("tresorerie")));
  globalThis.fetch = fetchFictif;
});
afterEach(() => {
  globalThis.fetch = fetchOriginal;
  actualiserConnectiviteChiffres(false);
  definirPersonneConfirmee(null); definirConfigurationAppel(null);
  jest.restoreAllMocks(); jest.useRealTimers();
});

test.each([403, 401])("trésorerie : le refus HTTP %s invalide le cache avant le passage hors ligne", async status => {
  const capture = capturerSessionAdminLecture();
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur", valeur: { solde: { genre: "connu", montant: "20000.00" }, cashLibre: { montant: "14106.32" } } });
  fetchFictif.mockResolvedValueOnce(refusHTTP(status));
  expect(await chargerTresorerie()).toEqual({ source: "refus", verdict: { code: "forbidden", detail: "Refus actuel fictif" } });
  // Le refus de section doit suffire avant que le cycle indépendant d'identité apprenne un retrait.
  expect(capture.courante()).toBe(true);
  actualiserConnectiviteChiffres(false);
  expect(await chargerTresorerie()).toEqual({ source: "aucune", raison: { code: "hors_ligne", detail: "" } });
  expect(await lireCacheSection(depot, PERSONNE, "tresorerie")).toBeNull();
  expect(fetchFictif).toHaveBeenCalledTimes(2);
  expect(fetchFictif.mock.calls[0][0]).toBe(`${URL}/tools/invoke`);
  expect(JSON.parse(String(fetchFictif.mock.calls[0][1]?.body))).toEqual({ tool: "m5_etat_tresorerie", args: {} });
});

test.each([
  ["verdict métier", enveloppeRefusee("REJ-ACCES-INTERDIT", "Refus métier fictif"), "REJ-ACCES-INTERDIT"],
  ["refus nominal d'identité", enveloppeEnErreur("refus_metier", "REJ-IDENTITE-APPAREIL-INVALIDE : fictif"), "refus_metier"],
])("trésorerie : %s ferme également la copie, sans requalifier le refus en panne", async (_nom, enveloppe, code) => {
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur" });
  fetchFictif.mockResolvedValueOnce(reponseHTTP(enveloppe));
  expect(await chargerTresorerie()).toMatchObject({ source: "refus", verdict: { code } });
  actualiserConnectiviteChiffres(false);
  expect(await chargerTresorerie()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(fetchFictif).toHaveBeenCalledTimes(2);
});

test("une panne réseau garde la trésorerie personnelle marquée comme cache", async () => {
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur" });
  fetchFictif.mockRejectedValueOnce(new Error("Panne réseau fictive"));
  expect(await chargerTresorerie()).toMatchObject({ source: "cache", valeur: { cashLibre: { montant: "14106.32" } }, raisonHorsLigne: { code: "erreur_reseau", detail: "Panne réseau fictive" } });
  actualiserConnectiviteChiffres(false);
  expect(await chargerTresorerie()).toMatchObject({ source: "cache", valeur: { solde: { montant: "20000.00" } }, raisonHorsLigne: { code: "hors_ligne" } });
});

test("Executive : le constat cash M8 reste fermé après 403 sans invalider une trésorerie non refusée", async () => {
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur" });
  const vue = reponse("vue_executive"); vue.resultat.cash_libre = cashFictif.calcule;
  fetchFictif.mockResolvedValueOnce(reponseHTTP(vue));
  expect(await chargerVueExecutive()).toMatchObject({ source: "serveur", valeur: { cashLibre: { genre: "lu", constat: { cashLibreCad: "27861.98" } } } });
  fetchFictif.mockResolvedValueOnce(refusHTTP());
  expect(await chargerVueExecutive()).toMatchObject({ source: "refus", verdict: { code: "forbidden" } });
  actualiserConnectiviteChiffres(false);
  expect(await chargerVueExecutive()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(await chargerTresorerie()).toMatchObject({ source: "cache", valeur: { cashLibre: { montant: "14106.32" } } });
});

test("le succès déjà en vol avant un refus trésorerie ne repeuple pas le slot refusé", async () => {
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur" });
  const ancienneReponse = attente<Response>(), demarre = attente<void>();
  fetchFictif.mockImplementationOnce(async () => { demarre.resoudre(); return ancienneReponse.promise; });
  const ancienne = chargerTresorerie(); await demarre.promise;
  fetchFictif.mockResolvedValueOnce(refusHTTP());
  expect(await chargerTresorerie()).toMatchObject({ source: "refus", verdict: { code: "forbidden" } });
  ancienneReponse.resoudre(reponseHTTP(reponse("tresorerie")));
  expect(await ancienne).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  actualiserConnectiviteChiffres(false);
  expect(await chargerTresorerie()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
});

test("l'écriture du tombstone échouée ferme le cache dans le process sans effacement silencieux", async () => {
  expect(await chargerTresorerie()).toMatchObject({ source: "serveur" });
  const ecrire = depot.ecrire.bind(depot);
  jest.spyOn(depot, "ecrire").mockImplementation(async (cle, valeur) => {
    if (JSON.parse(valeur).resultat === null) throw new Error("SQLite fictif indisponible pendant purge");
    await ecrire(cle, valeur);
  });
  fetchFictif.mockResolvedValueOnce(refusHTTP());
  expect(await chargerTresorerie()).toMatchObject({ source: "refus", verdict: { code: "forbidden" } });
  expect(await lireCacheSection(depot, PERSONNE, "tresorerie")).not.toBeNull(); // Octets conservés, sans permission de les rendre.
  actualiserConnectiviteChiffres(false);
  expect(await chargerTresorerie()).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});

test("un rôle retiré pendant HTTP ferme la réponse sans rendre ni garder ses chiffres", async () => {
  fetchFictif.mockImplementationOnce(async () => { admin("seller"); return reponseHTTP(reponse("tresorerie")); });
  expect(await chargerTresorerie()).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(await lireCacheSection(depot, PERSONNE, "tresorerie")).toBeNull();
  expect(await chargerTresorerie()).toBeNull();
  expect(fetchFictif).toHaveBeenCalledTimes(1);
});
