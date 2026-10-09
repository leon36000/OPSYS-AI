import captures from "../m6/fixturesClassementVariancesSQL.json";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
const api = () => require("./classementVariances") as typeof import("./classementVariances");
const cap = (phase: string) => captures.captures.find(c => c.phase === phase)!;
const args = cap("classement_v1").request.arguments as unknown as import("../m6/classementVariance").ArgumentsClassementVarianceM6;
function monde() {
  let epoch = 0, online = true, admin = true;
  const session: SessionEnvoi = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APP-CLASSEMENT-FICTIF", personne: "admin.contexte.fictif" };
  const base = new DepotOutboxMemoire(), depot = avecProprietaire(base, () => session.personne);
  const ouvrir = jest.fn(async () => depot), generer = jest.fn(() => "c9d2ff31-e4fd-4d80-acda-45743c28e5ee");
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true, result: cap("liste_initiale").enveloppe }), { status: 200 }));
  const d = { capturerSession: () => { const n = epoch; return { session: admin ? session : null, courante: () => admin && n === epoch }; },
    capturerReseau: () => { const n = epoch; return { enLigne: online, courante: () => online && n === epoch }; }, appelerOutil: invoquerOutil,
    fetchImpl, horloge: () => new Date("2026-10-08T17:00:00Z"), obtenirDepot: ouvrir, genererId: generer,
    decalageMinutesUTC: () => -240, declencher: jest.fn(async () => null) };
  return { d, base, depot, ouvrir, generer, fetchImpl, changer: () => { epoch++; }, offline: () => { online = false; epoch++; }, retirer: () => { admin = false; epoch++; } };
}
test("lecture SQL via SDK réel sans ouvrir le dépôt ou créer une intention", async () => {
  const h = monde(); const s = api().creerServiceClassementVariances(h.d);
  const r = await s.chargerVariances(args.selection.wct_id);
  expect(r?.source).toBe("serveur"); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
  const request = JSON.parse(String(h.fetchImpl.mock.calls[0][1]?.body));
  expect(request).not.toHaveProperty("idempotencyKey"); expect(request.args).toEqual(cap("liste_initiale").request.arguments);
});
test("deux confirmations simultanées réutilisent la seule intention persistée", async () => {
  const h = monde(), s = api().creerServiceClassementVariances(h.d);
  const [a, b] = await Promise.all([s.soumettre(args), s.soumettre(args)]);
  expect(a.genre).toBe("en_attente"); expect(b.genre).toBe("en_attente");
  expect(await h.base.lister()).toHaveLength(1); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("redémarrer le service retrouve UUID et payload sans générer de remplacement", async () => {
  const h = monde(); await api().creerServiceClassementVariances(h.d).soumettre(args);
  const lu = await api().creerServiceClassementVariances(h.d).soumettre({ ...args, cause: "breakage" });
  expect(lu.genre).toBe("en_attente"); expect(h.generer).toHaveBeenCalledTimes(1);
  expect((await h.base.lister())[0].payload).toMatchObject(args);
});
test("rôle retiré pendant l'ouverture asynchrone n'insère aucune intention", async () => {
  const h = monde(); h.ouvrir.mockImplementation(async () => { h.retirer(); return h.depot; });
  const r = await api().creerServiceClassementVariances(h.d).soumettre(args);
  expect(r.genre).toBe("indisponible"); expect(await h.base.lister()).toEqual([]); expect(h.generer).not.toHaveBeenCalled();
});
test("hors ligne empêche une nouvelle décision mais autorise la lecture locale de son intention", async () => {
  const h = monde(), s = api().creerServiceClassementVariances(h.d);
  await s.soumettre(args); h.offline();
  expect((await s.soumettre(args)).genre).toBe("indisponible");
  const r = await s.lireIntention(args.selection.wct_id); expect(r.genre).toBe("en_attente");
  expect(h.generer).toHaveBeenCalledTimes(1);
});
test("la saisie est figée avant toute attente d'ouverture du dépôt", async () => {
  const h = monde(); let liberer!: () => void;
  h.ouvrir.mockImplementationOnce(() => new Promise(resolve => { liberer = () => resolve(h.depot); }));
  const input = JSON.parse(JSON.stringify(args));
  const promise = api().creerServiceClassementVariances(h.d).soumettre(input);
  await Promise.resolve(); await Promise.resolve(); input.motif = "FICTIF : altéré pendant attente"; liberer();
  await promise; expect((await h.base.lister())[0].payload.motif).toBe(args.motif);
});
test("un getter de saisie est refusé avant toute lecture de dépôt", async () => {
  const h = monde(), getter = jest.fn(() => args.selection);
  const input = Object.defineProperty({ ...args }, "selection", { get: getter, enumerable: true });
  expect((await api().creerServiceClassementVariances(h.d).soumettre(input)).genre).toBe("indisponible");
  expect(getter).not.toHaveBeenCalled(); expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
});
