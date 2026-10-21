import captures from "../m1/fixturesRappelsSQL.json";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import type { ArgumentsPriseRappelM1 } from "../m1/rappelsAppareil";
const api = () => require("./rappelsM1") as typeof import("./rappelsM1");
const premiere = captures.captures.find(c => c.phase === "page_premiere")!, prise = captures.captures.find(c => c.phase === "prise_v1")!;
const args = prise.request.arguments as ArgumentsPriseRappelM1, meta = prise.request.meta!;
function monde() {
  let epoch = 0, online = true, admin = true;
  const session: SessionEnvoi = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: meta.appareil, personne: "admin-rappel-fictif" };
  const base = new DepotOutboxMemoire(), depot = avecProprietaire(base, () => session.personne), ouvrir = jest.fn(async () => depot);
  const generer = jest.fn(() => meta.cle), declencher = jest.fn(async () => null);
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true, result: premiere.response }), { status: 200 }));
  const d = { capturerSession: () => { const n = epoch; return { session: admin ? session : null, courante: () => admin && n === epoch }; },
    capturerReseau: () => { const n = epoch; return { enLigne: online, courante: () => online && n === epoch }; }, appelerOutil: invoquerOutil,
    fetchImpl, horloge: () => new Date(meta.horodatage_appareil), decalageMinutesUTC: () => 0, obtenirDepot: ouvrir, genererId: generer, declencher };
  return { d, session, base, depot, ouvrir, generer, declencher, fetchImpl, changer: () => { epoch++; },
    offline: () => { online = false; epoch++; }, retirer: () => { admin = false; epoch++; } };
}
test("lecture SDK réelle des octets SQL sans cache/dépôt/clé et arguments stricts", async () => {
  const h = monde(), s = api().creerChargeurRappelsM1(h.d);
  expect((await s.charger(null, 2))?.source).toBe("serveur"); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
  const req = JSON.parse(String(h.fetchImpl.mock.calls[0][1]?.body)); expect(req).toEqual({ tool: "m1_lister_rappels_appareil", args: premiere.request.arguments });
  expect((await s.charger(null, 9))?.source).toBe("aucune"); expect(h.fetchImpl).toHaveBeenCalledTimes(1);
});
test("offline/admin retiré : ni lecture cache ni RPC ni nouvelle intention", async () => {
  const h = monde(), s = api().creerChargeurRappelsM1(h.d); h.offline();
  expect((await s.charger())?.source).toBe("aucune"); expect((await s.soumettre(args)).genre).toBe("indisponible");
  h.retirer(); expect(await s.charger()).toBeNull(); expect(h.fetchImpl).not.toHaveBeenCalled(); expect(h.ouvrir).not.toHaveBeenCalled();
});
test("transition réseau/session après réponse masque toute page", async () => {
  const h = monde(); h.fetchImpl.mockImplementation(async () => { h.changer(); return new Response(JSON.stringify({ ok: true, result: premiere.response })); });
  expect((await api().creerChargeurRappelsM1(h.d).charger(null, 2))?.source).toBe("aucune");
});
test("deux prises simultanées produisent une seule intention durable", async () => {
  const h = monde(), s = api().creerChargeurRappelsM1(h.d); const r = await Promise.all([s.soumettre(args), s.soumettre(args)]);
  expect(r.map(v => v.genre)).toEqual(["en_attente", "en_attente"]); expect(await h.base.lister()).toHaveLength(1); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("restart/reprise conserve UUID/body/date/personne et ne prend pas le nouveau snapshot", async () => {
  const h = monde(); await api().creerChargeurRappelsM1(h.d).soumettre(args); const before = (await h.base.lister())[0];
  const s = api().creerChargeurRappelsM1(h.d); expect((await s.soumettre({ ...args, snapshot_attendu: "f".repeat(64) })).genre).toBe("en_attente");
  expect(await h.base.obtenir(before.id)).toEqual(before); expect(h.generer).toHaveBeenCalledTimes(1);
  h.offline(); expect((await s.lireIntention(args.transfert_id)).genre).toBe("en_attente");
});
test("une intention d'autre personne est une quarantaine bloquante", async () => {
  const h = monde(); await api().creerChargeurRappelsM1(h.d).soumettre(args); Object.assign(h.session, { personne: "autre-fictif" }); h.changer();
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args)).genre).toBe("quarantaine"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test.each(["appareilId", "urlBase"])("destination %s changée : intention originale retenue et pas de nouveau UUID", async champ => {
  const h = monde(); await api().creerChargeurRappelsM1(h.d).soumettre(args);
  Object.assign(h.session, { [champ]: champ === "urlBase" ? "https://autre.invalid" : "DEVICE-AUTRE-FICTIF" }); h.changer();
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args)).genre).toBe("quarantaine"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("rôle retiré pendant ouverture : zéro insertion", async () => {
  const h = monde(); h.ouvrir.mockImplementation(async () => { h.retirer(); return h.depot; });
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args)).genre).toBe("indisponible"); expect(await h.base.lister()).toEqual([]);
});
test("body/session copiés avant await et getters refusés sans exécution", async () => {
  const h = monde(); let liberer!: () => void; h.ouvrir.mockImplementationOnce(() => new Promise(resolve => { liberer = () => resolve(h.depot); }));
  const input = { ...args }, p = api().creerChargeurRappelsM1(h.d).soumettre(input); await Promise.resolve(); await Promise.resolve();
  input.snapshot_attendu = "0".repeat(64); liberer(); await p;
  expect((await h.base.lister())[0].payload.snapshot_attendu).toBe(args.snapshot_attendu);
  const getter = jest.fn(() => args.transfert_id), bad = Object.defineProperty({ ...args }, "transfert_id", { get: getter, enumerable: true });
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(bad)).genre).toBe("indisponible"); expect(getter).not.toHaveBeenCalled();
});
test("insertion tardive capture propriétaire original ; changement ne le réattribue pas", async () => {
  const h = monde(), insert = h.depot.inserer;
  h.depot.inserer = async m => { Object.assign(h.session, { personne: "autre-fictif" }); h.changer(); return insert(m); };
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args)).genre).toBe("indisponible");
  expect((await h.base.lister())[0].proprietaire).toBe("admin-rappel-fictif"); expect(h.declencher).not.toHaveBeenCalled();
});
test("panne après persistance : la reprise retrouve la ligne au lieu de recréer un effet", async () => {
  const h = monde(), insert = h.depot.inserer;
  h.depot.inserer = async m => { await insert(m); throw new Error("FICTIF après insertion"); };
  const s = api().creerChargeurRappelsM1(h.d); expect((await s.soumettre(args)).genre).toBe("indisponible");
  expect((await s.soumettre(args)).genre).toBe("en_attente"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("un callback externe invalidé pendant lister n'insère et ne déclenche rien", async () => {
  const h = monde(); let actif = true; h.depot.lister = async () => { actif = false; return []; };
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args, () => actif)).genre).toBe("indisponible");
  expect(h.generer).not.toHaveBeenCalled(); expect(h.declencher).not.toHaveBeenCalled();
});
test("métadonnées locales à getter refusées avant stockage, sans les exécuter", async () => {
  const h = monde(), getter = jest.fn(() => "autre-fictif");
  Object.defineProperty(h.session, "personne", { get: getter, enumerable: true });
  expect((await api().creerChargeurRappelsM1(h.d).soumettre(args)).genre).toBe("indisponible");
  expect(getter).not.toHaveBeenCalled(); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
});
