import cap from "./fixturesRevueCompletionCapSQL.json";
import { DepotOutboxMemoire } from "../outbox/depot";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { creerVidangeur } from "../outbox/vidangeur";
import { invoquerOutil } from "../protocole/client";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
const api = () => require("./revueCompletionOutbox") as typeof import("./revueCompletionOutbox");
const horloge = { maintenant: new Date("2026-10-09T12:00:00Z"), decalageMinutesUTC: 0 };
const destinationP = { personne: cap.creation.reponse.preuve_proposition.proposant.personne,
  appareilId: cap.creation.meta.appareil_id, urlBase: "https://fictif.invalid" };
const destinationD = { personne: cap.decision.auteur_sql, appareilId: cap.decision.meta.appareil_id, urlBase: "https://fictif.invalid" };
function p() { return { ...api().creerMutationPropositionRevueCompletion(cap.creation.arguments, () => cap.creation.meta.intention_uuid, horloge, destinationP), destination: destinationP.urlBase, proprietaire: destinationP.personne }; }
function d() { return { ...api().creerMutationDecisionRevueCompletion(cap.decision.arguments,
  cap.lectures[1].reponse, cap.lectures[1].arguments, () => cap.decision.meta.intention_uuid, horloge, destinationD), destination: destinationD.urlBase, proprietaire: destinationD.personne }; }
test("P et D RPC gardent leurs vrais args ; destination/UUID restent locaux", () => {
  const m = p(), n = d();
  expect(api().argumentsRpcRevueCompletion(m)).toEqual(cap.creation.arguments);
  expect(api().argumentsRpcRevueCompletion(n)).toEqual(cap.decision.arguments);
  expect(m.chantierId).toBe("approbations"); expect(n.chantierId).toBe("approbations");
  expect(api().interpreterRevueCompletion(cap.creation.reponse, m).accepte).toBe(true);
  expect(api().interpreterRevueCompletion(cap.decision.reponse, n).accepte).toBe(true);
  expect(JSON.stringify(n.payload)).not.toContain("jeton");
});
test("reçu durable D propre et P création seulement ; projection récupérée sans refaire P", () => {
  for (const [m, r] of [[p(), cap.creation.reponse], [d(), cap.decision.reponse]] as const) {
    const i = api().interpreterRevueCompletion(r, m); if (!i.accepte) throw new Error("réponse SQL attendue");
    const saved = { ...m, statut: "envoyee" as const, resumeAccepte: i.resume };
    expect(api().validerRecuRevueCompletion(saved)).toBe(true);
    expect(api().validerRecuRevueCompletion({ ...saved, id: "AUTRE-UUID-FICTIF" })).toBe(false);
    expect(api().validerRecuRevueCompletion({ ...saved, proprietaire: "AUTRE-FICTIF" })).toBe(false);
  }
});
test.each(["personne", "appareilId", "urlBase"] as const)("destination originale %s jamais réattribuée", k => {
  expect(api().verifierDestinationRevueCompletion(d(), destinationD)).toBe(true);
  expect(api().verifierDestinationRevueCompletion(d(), { ...destinationD, [k]: "AUTRE-FICTIF" })).toBe(false);
});
test("getter/cycle/prototype refusés avant génération UUID ; arguments D hors capture refusés", () => {
  const gen = jest.fn(() => "UUID-FICTIF"), getter = jest.fn(() => cap.creation.arguments.sources);
  const v = Object.defineProperty({ ...cap.creation.arguments }, "sources", { enumerable: true, get: getter });
  expect(() => api().creerMutationPropositionRevueCompletion(v, gen, horloge, destinationP)).toThrow();
  expect(gen).not.toHaveBeenCalled(); expect(getter).not.toHaveBeenCalled();
  expect(() => api().creerMutationDecisionRevueCompletion({ ...cap.decision.arguments, demande_id: "AUTRE" },
    cap.lectures[1].reponse, cap.lectures[1].arguments, gen, horloge, destinationD)).toThrow();
});
const mauvaisD = [ {}, { ok: false, erreur: "mutation_conflit" }, { ok: true, resultat: { accepte: false,
  verdict: { code: "deja_decidee", detail: "FICTIF" } }, rejoue: false },
  ...["refusee", "echec"].map(statut => ({ ...cap.decision.reponse, resultat: { accepte: true, resultat: {
    ...cap.decision.reponse.resultat.resultat, statut, preuve_completion: null } } })),
];
test.each(mauvaisD)("D sans preuve propre demeure inconnue, même quand son statut est définitif", r => {
  expect(api().interpreterRevueCompletion(r, d())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("SDK/dépôt/vidangeur : D inconnue bloque la generic suivante et reprise exacte après restart", async () => {
  const depot = new DepotOutboxMemoire(), m = await depot.inserer(d());
  const next = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "approval_decision", chantierId: "approbations",
    payload: { demande_id: "APP-SUITE-FICTIVE", decision: "approuver" } }, () => "UUID-SUITE-FICTIF", horloge)), destination: destinationD.urlBase, proprietaire: destinationD.personne });
  let date = horloge.maintenant, response: unknown = {};
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: response }), { status: 200 }));
  const config = { depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
    session: () => ({ ...destinationD, jeton: "JETON-FICTIF" }), maintenant: () => date,
    verifierAvantEnvoi: async () => true };
  const r = await creerVidangeur(config).vidangerFileSortante();
  expect(r.echecsPermanents).toEqual([]); expect(fetchImpl).toHaveBeenCalledTimes(1);
  expect(await depot.obtenir(next.id)).toMatchObject({ statut: "en_attente" });
  const pending = await depot.obtenir(m.id); if (!pending?.prochaineTentativeA) throw new Error("recul attendu");
  expect(pending).toMatchObject({ id: m.id, payload: m.payload, createdAtLocal: m.createdAtLocal });
  date = new Date(new Date(pending.prochaineTentativeA).getTime() + 1); response = cap.decision.reponse;
  await creerVidangeur(config).vidangerFileSortante();
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoyee", id: m.id, payload: m.payload });
  for (const [, init] of fetchImpl.mock.calls as unknown as [RequestInfo, RequestInit][]) {
    const req = JSON.parse(String(init.body)); if (req.idempotencyKey === m.id) {
      expect(req.args).toEqual(cap.decision.arguments); expect(req.deviceTimestamp).toBe(m.createdAtLocal);
    }
  }
});

test.each([400, 401, 403, 404, 500])("HTTP %s après dispatch ne libère pas une décision suivante", async status => {
  const depot = new DepotOutboxMemoire(), m = await depot.inserer(d());
  await depot.inserer({ ...d(), id: "UUID-D-SUITE-FICTIF" });
  const f = jest.fn(async () => new Response("{}", { status }));
  const r = await creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: f,
    session: () => ({ ...destinationD, jeton: "JETON-FICTIF" }), maintenant: () => horloge.maintenant,
    verifierAvantEnvoi: async () => true }).vidangerFileSortante();
  expect(r.echecsPermanents).toEqual([]); expect(f).toHaveBeenCalledTimes(1);
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente" });
});
test("générique inconnue devant D bloque aussi la même série ; anciens ACK génériques inchangés", async () => {
  const depot = new DepotOutboxMemoire();
  await depot.inserer({ ...soumettreMutation(creerMutation({ type: "approval_decision", chantierId: "approbations",
    payload: { demande_id: "APP-AVANT-FICTIVE", decision: "approuver" } }, () => "UUID-AVANT-FICTIF", horloge)), destination: destinationD.urlBase, proprietaire: destinationD.personne });
  const m = await depot.inserer(d()), f = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 }));
  await creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: f,
    session: () => ({ ...destinationD, jeton: "JETON-FICTIF" }), maintenant: () => horloge.maintenant,
    verifierAvantEnvoi: async () => true }).vidangerFileSortante();
  expect(f).toHaveBeenCalledTimes(1); expect(await depot.obtenir(m.id)).toMatchObject({ statut: "en_attente", tentatives: 0 });
});
test("P confirmation perdue puis son ACK création libère la série sans certifier une complétion", async () => {
  const depot = new DepotOutboxMemoire(), m = await depot.inserer(p());
  let now = horloge.maintenant, response: unknown = {};
  const f = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: response }), { status: 200 }));
  const config = { depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: f,
    session: () => ({ ...destinationP, jeton: "JETON-FICTIF" }), maintenant: () => now, verifierAvantEnvoi: async () => true };
  await creerVidangeur(config).vidangerFileSortante(); const pending = await depot.obtenir(m.id);
  if (!pending?.prochaineTentativeA) throw new Error("recul attendu");
  response = cap.creation.reponse; now = new Date(new Date(pending.prochaineTentativeA).getTime() + 1);
  const r = await creerVidangeur(config).vidangerFileSortante(); expect(r.envoyees).toEqual([m.id]);
  const saved = await depot.obtenir(m.id); expect(saved?.resumeAccepte).toEqual(cap.creation.reponse);
  expect(saved?.resumeAccepte).not.toHaveProperty("preuve_completion");
  expect(api().validerRecuRevueCompletion(saved!)).toBe(true);
  expect(f).toHaveBeenCalledTimes(2);
});
test("D réutilisée par autre UUID, corps ou microseconde ne certifie aucune nouvelle intention", () => {
  const m = d();
  for (const autre of [{ ...m, id: "AUTRE-UUID-FICTIF" }, { ...m, createdAtLocal: "2026-10-09T12:00:00.000001+00:00" },
    { ...m, payload: { ...m.payload, arguments_decision: { ...cap.decision.arguments, motif: "FICTIF : autre" } } }]) {
    expect(api().interpreterRevueCompletion(cap.decision.reponse, autre)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  }
});
test.each(["P", "D"])("reçu %s persisté mais altéré bloque la suivante sans RPC", async type => {
  const depot = new DepotOutboxMemoire(), m = type === "P" ? p() : d();
  const i = api().interpreterRevueCompletion(type === "P" ? cap.creation.reponse : cap.decision.reponse, m);
  if (!i.accepte) throw new Error("ACK SQL attendu");
  await depot.inserer({ ...m, statut: "envoyee", resumeAccepte: i.resume, id: "UUID-ALTERE-FICTIF" });
  await depot.inserer({ ...soumettreMutation(creerMutation({ type: "approval_decision", chantierId: "approbations",
    payload: { demande_id: "SUITE-FICTIVE", decision: "approuver" } }, () => "UUID-SUITE-FICTIF", horloge)), destination: m.destination, proprietaire: m.proprietaire });
  const f = jest.fn(async () => new Response("{}", { status: 200 }));
  const r = await creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: f,
    session: () => ({ ...(type === "P" ? destinationP : destinationD), jeton: "JETON-FICTIF" }),
    maintenant: () => horloge.maintenant, verifierAvantEnvoi: async () => true }).vidangerFileSortante();
  expect(f).not.toHaveBeenCalled(); expect(r.envoyees).toEqual([]);
});
