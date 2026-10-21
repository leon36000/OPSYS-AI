/** SDK replay of byte-exact SQL façade read; mutations use fictive RAM only. */
import captures from "../m5/fixturesObligationsPrepareesSQL.json";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import type { ArgumentsDeclarationObligation } from "../m5/obligationsPreparees";
const api = () => require("./obligationsPrepareesM5");
const premiere = captures.captures.find(c => c.name === "lecture-absente")!;
const args: ArgumentsDeclarationObligation = { categorie: "paies", operation: "declarer", declaration: { montant: null, source: null, au: null, echeance: null, calendrier: null }, revision_attendue: null, motif: "FICTIF" };
const meta = { appareil: "DEVICE-FICTIF", cle: "4e1b7c25-918d-4b70-bcc5-885a2c6a7ab9", horodatage_appareil: "2026-10-09T12:00:00.000Z" };
function monde() {
  let epoch = 0, online = true, admin = true;
  const session: SessionEnvoi = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: meta.appareil, personne: "admin-rappel-fictif" };
  const base = new DepotOutboxMemoire(), depot = avecProprietaire(base, () => session.personne), ouvrir = jest.fn(async () => depot);
  const generer = jest.fn(() => meta.cle), declencher = jest.fn(async () => null);
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true, result: premiere.enveloppe }), { status: 200 }));
  const d = { capturerSession: () => { const n = epoch; return { session: admin ? session : null, courante: () => admin && n === epoch }; },
    capturerReseau: () => { const n = epoch; return { enLigne: online, courante: () => online && n === epoch }; }, appelerOutil: invoquerOutil,
    fetchImpl, horloge: () => new Date(meta.horodatage_appareil), decalageMinutesUTC: () => 0, obtenirDepot: ouvrir, genererId: generer, declencher };
  return { d, session, base, depot, ouvrir, generer, declencher, fetchImpl, changer: () => { epoch++; },
    offline: () => { online = false; epoch++; }, retirer: () => { admin = false; epoch++; } };
}
test("lecture SDK réelle des octets SQL sans cache/dépôt/clé et arguments stricts", async () => {
  const h = monde(), s = api().creerChargeurObligationsM5(h.d);
  expect((await s.charger("2026-10-09", 0, 1))?.source).toBe("serveur"); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
  const req = JSON.parse(String(h.fetchImpl.mock.calls[0][1]?.body)); expect(req).toEqual({ tool: "m5_lire_obligations_preparees_appareil", args: premiere.request!.arguments });
  expect((await s.charger("2026-10-09", 0, 9))?.source).toBe("aucune"); expect(h.fetchImpl).toHaveBeenCalledTimes(1);
});
test("offline/admin retiré : ni lecture cache ni RPC ni nouvelle intention", async () => {
  const h = monde(), s = api().creerChargeurObligationsM5(h.d); h.offline();
  expect((await s.charger("2026-10-09"))?.source).toBe("aucune"); expect((await s.soumettre(args)).genre).toBe("indisponible");
  h.retirer(); expect(await s.charger("2026-10-09")).toBeNull(); expect(h.fetchImpl).not.toHaveBeenCalled(); expect(h.ouvrir).not.toHaveBeenCalled();
});
test("transition réseau/session après réponse masque toute page", async () => {
  const h = monde(); h.fetchImpl.mockImplementation(async () => { h.changer(); return new Response(JSON.stringify({ ok: true, result: premiere.enveloppe })); });
  expect((await api().creerChargeurObligationsM5(h.d).charger("2026-10-09", 0, 1))?.source).toBe("aucune");
});
test("deux prises simultanées produisent une seule intention durable", async () => {
  const h = monde(), s = api().creerChargeurObligationsM5(h.d); const r = await Promise.all([s.soumettre(args), s.soumettre(args)]);
  expect(r.map(v => v.genre)).toEqual(["en_attente", "en_attente"]); expect(await h.base.lister()).toHaveLength(1); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("restart/reprise conserve UUID/body/date/personne et ne prend pas le nouveau snapshot", async () => {
  const h = monde(); await api().creerChargeurObligationsM5(h.d).soumettre(args); const before = (await h.base.lister())[0];
  const s = api().creerChargeurObligationsM5(h.d); expect((await s.soumettre({ ...args, motif: "new FICTIF body not adopted" })).genre).toBe("en_attente");
  expect(await h.base.obtenir(before.id)).toEqual(before); expect(h.generer).toHaveBeenCalledTimes(1);
  h.offline(); expect((await s.lireIntention(args.categorie)).genre).toBe("en_attente");
});
test("une intention d'autre personne est une quarantaine bloquante", async () => {
  const h = monde(); await api().creerChargeurObligationsM5(h.d).soumettre(args); Object.assign(h.session, { personne: "autre-fictif" }); h.changer();
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("quarantaine"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test.each(["appareilId", "urlBase"])("destination %s changée : intention originale retenue et pas de nouveau UUID", async champ => {
  const h = monde(); await api().creerChargeurObligationsM5(h.d).soumettre(args);
  Object.assign(h.session, { [champ]: champ === "urlBase" ? "https://autre.invalid" : "DEVICE-AUTRE-FICTIF" }); h.changer();
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("quarantaine"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("rôle retiré pendant ouverture : zéro insertion", async () => {
  const h = monde(); h.ouvrir.mockImplementation(async () => { h.retirer(); return h.depot; });
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("indisponible"); expect(await h.base.lister()).toEqual([]);
});
test("body/session copiés avant await et getters refusés sans exécution", async () => {
  const h = monde(); let liberer!: () => void; h.ouvrir.mockImplementationOnce(() => new Promise(resolve => { liberer = () => resolve(h.depot); }));
  const input = { ...args }, p = api().creerChargeurObligationsM5(h.d).soumettre(input); await Promise.resolve(); await Promise.resolve();
  input.motif = "changed after await"; liberer(); await p;
  expect((await h.base.lister())[0].payload.motif).toBe(args.motif);
  const getter = jest.fn(() => args.categorie), bad = Object.defineProperty({ ...args }, "categorie", { get: getter, enumerable: true });
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(bad)).genre).toBe("indisponible"); expect(getter).not.toHaveBeenCalled();
});
test("insertion tardive capture propriétaire original ; changement ne le réattribue pas", async () => {
  const h = monde(), insert = h.depot.inserer;
  h.depot.inserer = async m => { Object.assign(h.session, { personne: "autre-fictif" }); h.changer(); return insert(m); };
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("indisponible");
  expect((await h.base.lister())[0].proprietaire).toBe("admin-rappel-fictif"); expect(h.declencher).not.toHaveBeenCalled();
});
test("panne après persistance : la reprise retrouve la ligne au lieu de recréer un effet", async () => {
  const h = monde(), insert = h.depot.inserer;
  h.depot.inserer = async m => { await insert(m); throw new Error("FICTIF après insertion"); };
  const s = api().creerChargeurObligationsM5(h.d); expect((await s.soumettre(args)).genre).toBe("indisponible");
  expect((await s.soumettre(args)).genre).toBe("en_attente"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("un callback externe invalidé pendant lister n'insère et ne déclenche rien", async () => {
  const h = monde(); let actif = true; h.depot.lister = async () => { actif = false; return []; };
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args, () => actif)).genre).toBe("indisponible");
  expect(h.generer).not.toHaveBeenCalled(); expect(h.declencher).not.toHaveBeenCalled();
});
test("métadonnées locales à getter refusées avant stockage, sans les exécuter", async () => {
  const h = monde(), getter = jest.fn(() => "autre-fictif");
  Object.defineProperty(h.session, "personne", { get: getter, enumerable: true });
  expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("indisponible");
  expect(getter).not.toHaveBeenCalled(); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
});

test("A to B to A session generations cannot revive a late current page",async()=> {
 const h=monde();let finish!:(r:Response)=>void;h.fetchImpl.mockImplementationOnce(()=>new Promise(r=>{finish=r;}));
 const pending=api().creerChargeurObligationsM5(h.d).charger("2026-10-09",0,1);
 Object.assign(h.session,{personne:"autre-fictif"});h.changer();Object.assign(h.session,{personne:"admin-rappel-fictif"});h.changer();
 finish(new Response(JSON.stringify({ok:true,result:premiere.enveloppe})));expect((await pending)?.source).toBe("aucune");expect(h.ouvrir).not.toHaveBeenCalled();
});
test("token replacement during depot opening does not dispatch the captured session",async()=> {
 const h=monde();h.ouvrir.mockImplementation(async()=>{Object.assign(h.session,{jeton:"AUTRE-JETON-FICTIF"});h.changer();return h.depot;});
 expect((await api().creerChargeurObligationsM5(h.d).soumettre(args)).genre).toBe("indisponible");expect(h.declencher).not.toHaveBeenCalled();expect(await h.base.lister()).toEqual([]);
});

test("default service read sends one without rewriting an explicit limit",async()=> {
 const h=monde(),s=api().creerChargeurObligationsM5(h.d);expect((await s.charger("2026-10-09"))?.source).toBe("serveur");
 expect(JSON.parse(String(h.fetchImpl.mock.calls[0][1]?.body)).args).toEqual({aujourd_hui:"2026-10-09",decalage:0,limite:1});
 await s.charger("2026-10-09",0,8);expect(JSON.parse(String(h.fetchImpl.mock.calls[1][1]?.body)).args.limite).toBe(8);
});
