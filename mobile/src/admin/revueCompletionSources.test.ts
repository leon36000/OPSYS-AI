import cap from "../m4/fixturesRevueCompletionCapSQL.json";
import { DepotOutboxMemoire } from "../outbox/depot";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
const api = () => require("./revueCompletionSources") as typeof import("./revueCompletionSources");
const courant = cap.lectures[0].reponse.resultat.resultat;
const historique = cap.lectures[1].reponse.resultat.resultat;
function monde() {
  let epoch = 0, online = true, admin = true;
  const session = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APP-FICTIF", personne: "ADMIN-FICTIF" } satisfies SessionEnvoi;
  const depot = new DepotOutboxMemoire(), ouvrir = jest.fn(async () => depot), generer = jest.fn(() => "UUID-FICTIF");
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: cap.lectures[0].reponse }), { status: 200 }));
  const d = { capturerSession: () => { const n = epoch; return { session: admin ? { ...session } : null, courante: () => admin && n === epoch }; },
    capturerReseau: () => { const n = epoch; return { enLigne: online, courante: () => online && n === epoch }; },
    appelerOutil: invoquerOutil, fetchImpl, horloge: () => new Date("2026-10-09T12:00:00Z"), decalageMinutesUTC: () => 0,
    obtenirDepot: ouvrir, genererId: generer, declencher: jest.fn(async () => null) };
  return { d, depot, ouvrir, generer, fetchImpl, session, changer: () => epoch++, offline: () => { online = false; epoch++; }, retirer: () => { admin = false; epoch++; } };
}
test("lecture courante Cap via SDK, ni cache ni dépôt ; args T0 sans Meta", async () => {
  const h = monde(), r = await api().creerServiceRevueCompletionSources(h.d).charger(courant.intervention_id);
  expect(r).toMatchObject({ source: "serveur", valeur: courant }); expect(h.ouvrir).not.toHaveBeenCalled();
  const args = JSON.parse(String((h.fetchImpl.mock.calls as unknown as [unknown, RequestInit][])[0][1].body));
  expect(args.args).toEqual(cap.lectures[0].arguments); expect(args).not.toHaveProperty("idempotencyKey");
});
test("deux confirmations et nouvelle instance retrouvent une intention, jamais UUID remplacé", async () => {
  const h = monde(), s = api().creerServiceRevueCompletionSources(h.d);
  const [a, b] = await Promise.all([s.proposer(courant, "correction", "FICTIF : A"), s.proposer(courant, "correction", "FICTIF : A")]);
  expect(a.genre).toBe("en_attente"); expect(b.genre).toBe("en_attente");
  await api().creerServiceRevueCompletionSources(h.d).proposer(courant, "verifiee", "FICTIF : autre saisie");
  expect(await h.depot.lister()).toHaveLength(1); expect(h.generer).toHaveBeenCalledTimes(1);
  expect((await h.depot.lister())[0].payload).toMatchObject({ arguments_proposition: { motif: "FICTIF : A" } });
});
test.each(["role", "epoch", "focus", "offline"])("%s pendant ouverture ferme sans création", async cause => {
  const h = monde(); let focus = true;
  h.ouvrir.mockImplementation(async () => { if (cause === "role") h.retirer(); else if (cause === "offline") h.offline(); else if (cause === "focus") focus = false; else h.changer(); return h.depot; });
  expect((await api().creerServiceRevueCompletionSources(h.d).proposer(courant, "correction", "FICTIF", () => focus)).genre).toBe("indisponible");
  expect(await h.depot.lister()).toEqual([]); expect(h.generer).not.toHaveBeenCalled();
});
test("corps et destination capturés avant await ; aucun getter invoqué", async () => {
  const h = monde(); let fin!: () => void;
  h.ouvrir.mockImplementationOnce(() => new Promise(resolve => { fin = () => resolve(h.depot); }));
  const input = JSON.parse(JSON.stringify(courant));
  const p = api().creerServiceRevueCompletionSources(h.d).proposer(input, "correction", "FICTIF : original");
  await Promise.resolve(); await Promise.resolve(); input.sources.chantier_id = "AUTRE"; fin(); await p;
  expect((await h.depot.lister())[0].payload).toMatchObject({ arguments_proposition: { sources: courant.sources },
    destination_origine: { personne: "ADMIN-FICTIF", appareil_id: "APP-FICTIF", url_base: h.session.urlBase } });
  const getter = jest.fn(() => courant.sources), v = Object.defineProperty({ ...courant }, "sources", { enumerable: true, get: getter });
  expect((await api().creerServiceRevueCompletionSources(h.d).proposer(v, "correction", "FICTIF")).genre).toBe("indisponible");
  expect(getter).not.toHaveBeenCalled();
});
test("quarantaine d'une autre personne bloque D et ne réattribue jamais P", async () => {
  const h = monde(), s = api().creerServiceRevueCompletionSources(h.d);
  await s.proposer(courant, "correction", "FICTIF"); h.session.personne = "OWNER-FICTIF"; h.changer();
  expect((await s.decider({ ...historique, demande: { ...historique.demande, statut: "en_attente", decide_par: null, decide_role: null, decide_le: null, motif_decision: null }, issue: null, preuve_completion: null }, "approuver", undefined, true)).genre).toBe("quarantaine");
  expect((await h.depot.lister())[0].proprietaire).toBe("ADMIN-FICTIF"); expect(h.generer).toHaveBeenCalledTimes(1);
});
test("owner serveur nécessaire avant D ; admin seul ne crée pas de décision", async () => {
  const h = monde(), s = api().creerServiceRevueCompletionSources(h.d);
  expect((await s.decider(historique, "approuver", undefined, false)).genre).toBe("indisponible");
  expect(h.ouvrir).not.toHaveBeenCalled(); expect(h.generer).not.toHaveBeenCalled();
});
test("A vers B vers A pendant HTTP n'adopte pas une ancienne lecture", async () => {
  const h = monde(); let fin!: () => void;
  h.fetchImpl.mockImplementationOnce(() => new Promise(resolve => { fin = () => resolve(new Response(JSON.stringify({ ok: true, result: cap.lectures[0].reponse }), { status: 200 })); }));
  const p = api().creerServiceRevueCompletionSources(h.d).charger(courant.intervention_id);
  h.session.personne = "B-FICTIF"; h.changer(); h.session.personne = "ADMIN-FICTIF"; h.changer(); fin();
  expect(await p).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
test("owner n'est lu que dans une liste serveur actuelle, jamais depuis la session admin", async () => {
  const h = monde();
  h.fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: true,
    resultat: { demandes: [], total_en_attente: 0, affichees: 0, reste: 0, proprietaire: true } } } }), { status: 200 }));
  expect(await api().creerServiceRevueCompletionSources(h.d).chargerProprietaire()).toBe(true);
  h.offline(); expect(await api().creerServiceRevueCompletionSources(h.d).chargerProprietaire()).toBeNull();
  expect(h.fetchImpl).toHaveBeenCalledTimes(1); expect(h.generer).not.toHaveBeenCalled();
});
test("une ouverture qui échoue et une source trop grande ne génèrent aucun UUID", async () => {
  const h = monde(), s = api().creerServiceRevueCompletionSources(h.d);
  h.ouvrir.mockRejectedValueOnce(new Error("FICTIF : stockage indisponible"));
  expect((await s.proposer(courant, "correction", "FICTIF")).genre).toBe("indisponible");
  expect(h.generer).not.toHaveBeenCalled();
  expect((await s.proposer({ ...courant, surplus: "X".repeat(6000) }, "correction", "FICTIF")).genre).toBe("indisponible");
  expect(h.generer).not.toHaveBeenCalled();
});
test("échec local après insertion puis reprise retrouve le même UUID, sans réattribution", async () => {
  const h = monde(), s = api().creerServiceRevueCompletionSources(h.d), ins = h.depot.inserer.bind(h.depot);
  const spy = jest.spyOn(h.depot, "inserer").mockImplementationOnce(async m => { await ins(m); throw new Error("FICTIF : confirmation locale perdue"); });
  expect((await s.proposer(courant, "correction", "FICTIF : même corps")).genre).toBe("indisponible");
  const original = (await h.depot.lister())[0];
  expect((await api().creerServiceRevueCompletionSources(h.d).proposer(courant, "correction", "FICTIF : autre saisie")).genre).toBe("en_attente");
  expect((await h.depot.lister())[0]).toEqual(original); expect(h.generer).toHaveBeenCalledTimes(1); spy.mockRestore();
});
