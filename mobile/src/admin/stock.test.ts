import { creerChargeurStock } from "./stock";
import { config, fauxTransport, echecHttp, transportHorsLigne, enveloppeCouple, enveloppeDirecte } from "./donneesDeTest";
import { reponseStock, disponibiliteFictive, digestFictif, CAPTURES_STOCK } from "../m6/fixturesStock";
import { OUTIL_DIGEST, OUTIL_DISPONIBILITE } from "../m6/stock";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { synchroniserCaches, ecrireProprietaireDesCaches } from "../identite/caches";
import type { ResultatAppelOutil } from "../protocole/client";

const horloge = { maintenant: new Date("2026-10-07T12:00:00Z"), decalageMinutesUTC: -240 };
const succes = () => fauxTransport({
  [OUTIL_DISPONIBILITE]: () => reponseStock("disponibilite_fictif"),
  [OUTIL_DIGEST]: () => reponseStock("digest_sans_seuil_fictif"),
});
const noms = ["chargerDisponibilite", "chargerDigest"] as const;

test("deux lectures indépendantes, noms nus et arguments toujours vides", async () => {
  const appeler = succes();
  const chargeur = creerChargeurStock(config(appeler, { horloge }));
  expect((await chargeur.chargerDisponibilite()).source).toBe("serveur");
  expect((await chargeur.chargerDigest()).source).toBe("serveur");
  expect(appeler.mock.calls.map(([p]) => p.requete)).toEqual([
    { tool: "m6_lire_disponibilite", args: {} }, { tool: "m6_produire_digest", args: {} },
  ]);
});

test("cache minimal normalisé, relisible et personnel", async () => {
  const depot = new DepotCleValeurMemoire();
  const brut = { ...disponibiliteFictive, secret_interne_fictif: "ne pas garder",
    articles: disponibiliteFictive.articles.map(a => ({ ...a, source_interne_fictive: "ne pas garder" })) };
  const appeler = fauxTransport({
    [OUTIL_DISPONIBILITE]: () => enveloppeCouple(brut),
    [OUTIL_DIGEST]: () => enveloppeDirecte({ ...digestFictif, secret_interne_fictif: "ne pas garder" }),
  });
  const chargeur = creerChargeurStock(config(appeler, { depot, horloge }));
  await chargeur.chargerDisponibilite(); await chargeur.chargerDigest();
  const cles = depot.cles().filter(c => c.startsWith("admin:"));
  expect(cles).toHaveLength(2);
  for (const cle of cles) expect(await depot.lire(cle)).not.toContain("interne_fictif");
  const offline = creerChargeurStock(config(transportHorsLigne(), { depot, horloge }));
  expect(await offline.chargerDisponibilite()).toMatchObject({ source: "cache", valeur: disponibiliteFictive,
    misAJourLe: horloge.maintenant.toISOString() });
  expect(await offline.chargerDigest()).toMatchObject({ source: "cache", valeur: digestFictif });
  const autre = creerChargeurStock(config(transportHorsLigne(), { depot, horloge, personne: "autre.fictive" }));
  expect((await autre.chargerDisponibilite()).source).toBe("aucune");
  expect((await autre.chargerDigest()).source).toBe("aucune");
});

test.each(noms)("refus métier %s ne remplace jamais le refus par un cache", async nom => {
  const depot = new DepotCleValeurMemoire();
  const chargeur = creerChargeurStock(config(succes(), { depot, horloge }));
  await chargeur[nom]();
  const appels = fauxTransport({
    [OUTIL_DISPONIBILITE]: () => reponseStock("refus_admin_desactive_m6_lire_disponibilite_fictif"),
    [OUTIL_DIGEST]: () => reponseStock("refus_admin_desactive_m6_produire_digest_fictif"),
  });
  expect(await creerChargeurStock(config(appels, { depot, horloge }))[nom]()).toMatchObject({
    source: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" },
  });
});

test.each([401, 403])("refus HTTP %s sans cache et sections indépendantes", async statut => {
  const depot = new DepotCleValeurMemoire();
  const chargeur = creerChargeurStock(config(succes(), { depot, horloge }));
  await chargeur.chargerDisponibilite(); await chargeur.chargerDigest();
  const appelle = jest.fn(async () => echecHttp(statut, "tool_call_blocked"));
  const refuse = creerChargeurStock(config(appelle, { depot, horloge }));
  expect((await refuse.chargerDisponibilite()).source).toBe("refus");
  expect((await refuse.chargerDigest()).source).toBe("refus");
});

test("troncature métier visible, transport tronqué fermé et cache daté distinct", async () => {
  const depot = new DepotCleValeurMemoire();
  const partiel = fauxTransport({ [OUTIL_DISPONIBILITE]: () => reponseStock("articles_16_fictif") });
  const chargeur = creerChargeurStock(config(partiel, { depot, horloge }));
  const lu = await chargeur.chargerDisponibilite();
  expect(lu).toMatchObject({ source: "serveur", valeur: { tronque: true } });
  expect((await chargeur.chargerDigest()).source).toBe("refus");
  const coupe = fauxTransport({ [OUTIL_DISPONIBILITE]: () => ({ ok: true, tronque: true, apercu: "fictif" }) });
  expect(await creerChargeurStock(config(coupe, { depot, horloge })).chargerDisponibilite()).toMatchObject({
    source: "cache", valeur: { tronque: true }, raisonHorsLigne: { code: "reponse_tronquee" },
  });
  expect((await creerChargeurStock(config(coupe, { horloge })).chargerDisponibilite()).source).toBe("aucune");
});

test("digest avec suggestions malgré args {} ne se garde pas et reste illisible", async () => {
  const depot = new DepotCleValeurMemoire();
  const appeler = fauxTransport({ [OUTIL_DIGEST]: () => reponseStock("digest_seuil_fourni_fictif") });
  expect(await creerChargeurStock(config(appeler, { depot, horloge })).chargerDigest()).toMatchObject({
    source: "aucune", raison: { code: "reponse_illisible" },
  });
  expect(depot.cles()).toEqual([]);
});

test("cache corrompu relu sous les mêmes règles strictes", async () => {
  const depot = new DepotCleValeurMemoire();
  await creerChargeurStock(config(succes(), { depot, horloge })).chargerDigest();
  const [cle] = depot.cles();
  await depot.ecrire(cle, JSON.stringify({ misAJourLe: horloge.maintenant.toISOString(),
    resultat: enveloppeDirecte(CAPTURES_STOCK.digest_seuil_fourni_fictif.corps.result.resultat) }));
  expect((await creerChargeurStock(config(transportHorsLigne(), { depot, horloge })).chargerDigest()).source).toBe("aucune");
});

test.each(noms)("chargeur %s retenu avant révocation/purge ne relit ni serveur ni cache", async nom => {
  const depot = new DepotCleValeurMemoire();
  const appeler = succes();
  const chargeur = creerChargeurStock(config(appeler, { depot, horloge }));
  await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
  expect(await chargeur[nom]()).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(appeler).not.toHaveBeenCalled();
});

test("changement de rôle purge les deux caches et invalide le chargeur retenu", async () => {
  const depot = new DepotCleValeurMemoire();
  await ecrireProprietaireDesCaches(depot, { personne: "nathan", role: "admin" });
  const chargeur = creerChargeurStock(config(succes(), { depot, horloge }));
  await chargeur.chargerDisponibilite(); await chargeur.chargerDigest();
  await synchroniserCaches(depot, { genre: "confirmee", identite: {
    appareilId: "a".repeat(64), personne: "nathan", role: "seller",
  } });
  expect(depot.cles().filter(c => c.startsWith("admin:"))).toEqual([]);
  expect((await chargeur.chargerDisponibilite()).source).toBe("aucune");
  expect((await chargeur.chargerDigest()).source).toBe("aucune");
});

test.each(noms)("réponse %s en vol après purge abandonnée sans repeupler le cache", async nom => {
  const depot = new DepotCleValeurMemoire();
  let finir!: (resultat: ResultatAppelOutil) => void;
  const appeler = jest.fn(() => new Promise<ResultatAppelOutil>(resolve => { finir = resolve; }));
  const chargeur = creerChargeurStock(config(appeler, { depot, horloge }));
  const lecture = chargeur[nom]();
  await Promise.resolve();
  await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
  finir({ ok: true, result: reponseStock(nom === "chargerDisponibilite" ? "disponibilite_fictif" : "digest_sans_seuil_fictif") });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(depot.cles().filter(c => c.startsWith("admin:"))).toEqual([]);
});
