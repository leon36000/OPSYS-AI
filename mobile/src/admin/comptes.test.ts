import { creerChargeurComptes } from "./comptes";
import { config, enveloppeCouple, enveloppeDirecte, echecHttp, transportHorsLigne } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { synchroniserCaches } from "../identite/caches";
import { creances, ap, sansPO, attentes } from "../m5/fixturesComptes";
const horloge = { maintenant: new Date("2026-09-02T12:00:00Z"), decalageMinutesUTC: -240 };
const transport = () => jest.fn(async (p) => ({ ok: true as const, result: p.requete.tool === "m5_lire_comptes_a_recevoir"
  ? enveloppeCouple(creances) : p.requete.tool === "m5_lister_comptes_a_payer"
    ? enveloppeCouple(p.requete.args.sans_po ? sansPO : ap) : enveloppeDirecte(attentes) }));
test("noms et arguments exacts, pas d'identité/coût transmis", async () => {
  const appeler = transport(), lecteur = creerChargeurComptes(config(appeler, { horloge }));
  await lecteur.chargerCreances(); await lecteur.chargerAP(); await lecteur.chargerAP(true); await lecteur.chargerAttentes();
  expect(appeler.mock.calls.map(([p]) => p.requete)).toEqual([
    { tool: "m5_lire_comptes_a_recevoir", args: { aujourd_hui: "2026-09-02" } },
    { tool: "m5_lister_comptes_a_payer", args: { depart: 0 } },
    { tool: "m5_lister_comptes_a_payer", args: { sans_po: true, depart: 0 } },
    { tool: "m5_lister_attentes_facturation", args: {} },
  ]);
});
test("cache normalisé relisible, isolé et refus sans cache", async () => {
  const depot = new DepotCleValeurMemoire();
  const premier = creerChargeurComptes(config(transport(), { depot, horloge }));
  await premier.chargerCreances(); await premier.chargerAP(); await premier.chargerAP(true); await premier.chargerAttentes();
  const offline = creerChargeurComptes(config(transportHorsLigne(), { depot, horloge }));
  expect((await offline.chargerCreances()).source).toBe("cache");
  expect((await offline.chargerAP()).source).toBe("cache");
  expect((await offline.chargerAP(true)).source).toBe("cache");
  expect((await offline.chargerAttentes()).source).toBe("cache");
  const autre = creerChargeurComptes(config(transportHorsLigne(), { depot, horloge, personne: "autre-fictive" }));
  expect((await autre.chargerAP()).source).toBe("aucune");
  const refuse = creerChargeurComptes(config(jest.fn(async () => echecHttp(403, "tool_call_blocked")), { depot, horloge }));
  expect((await refuse.chargerCreances()).source).toBe("refus");
});
test("suite sans lecture/écriture cache, compteurs invalides sans appel", async () => {
  const depot = new DepotCleValeurMemoire(), appeler = transport();
  const lire = jest.spyOn(depot, "lire"), ecrire = jest.spyOn(depot, "ecrire");
  const lecteur = creerChargeurComptes(config(appeler, { depot, horloge }));
  expect((await lecteur.chargerAP(false, 1)).source).toBe("aucune");
  expect(lire).not.toHaveBeenCalled(); expect(ecrire).not.toHaveBeenCalled();
  const n = appeler.mock.calls.length;
  await lecteur.chargerAP(false, 2 ** 53); expect(appeler).toHaveBeenCalledTimes(n);
});
test("lecteur retenu après purge ne déclenche aucune lecture", async () => {
  const depot = new DepotCleValeurMemoire(), appeler = transport();
  const lecteur = creerChargeurComptes(config(appeler, { depot, horloge }));
  await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
  expect((await lecteur.chargerCreances()).source).toBe("aucune");
  expect((await lecteur.chargerAP()).source).toBe("aucune");
  expect((await lecteur.chargerAttentes()).source).toBe("aucune");
  expect(appeler).not.toHaveBeenCalled();
});
test.each(["creances", "ap", "attentes"] as const)("réponse tardive %s abandonnée après purge", async nom => {
  const depot = new DepotCleValeurMemoire(); let finir!: (x: any) => void;
  const appeler = jest.fn(() => new Promise<any>(r => { finir = r; }));
  const lecteur = creerChargeurComptes(config(appeler, { depot, horloge }));
  const promise = nom === "creances" ? lecteur.chargerCreances() : nom === "ap" ? lecteur.chargerAP() : lecteur.chargerAttentes();
  await Promise.resolve(); await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
  finir({ ok: true, result: nom === "creances" ? enveloppeCouple(creances) : nom === "ap" ? enveloppeCouple(ap) : enveloppeDirecte(attentes) });
  expect((await promise).source).toBe("aucune");
  expect(depot.cles().filter(cle => cle.startsWith("admin:"))).toEqual([]);
});
