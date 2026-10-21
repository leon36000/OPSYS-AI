import captures from "../m1/fixturesRappelsSQL.json";
import capturesCap from "../m1/fixturesRappelsCapSQL.json";
import { creerMutationPriseRappelM1, verifierDestinationPriseRappelM1 } from "../m1/rappelsAppareil";
import { DepotOutboxMemoire } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { ArgumentsPriseRappelM1 } from "../m1/rappelsAppareil";
import type { MutationOutbox } from "./types";
let mockDepotService: DepotOutboxMemoire;
jest.mock("expo-sqlite", () => ({ openDatabaseAsync: async () => ({}) }));
jest.mock("./depot.sqlite", () => ({ initialiserSchemaOutbox: async () => undefined, creerDepotOutboxSqlite: () => mockDepotService }));
// Producteur SQLite réel ; transport SDK fourni par fetch fictif, aucun Gateway déduit.
const prise = captures.captures.find(c => c.phase === "prise_v1")!, replay = captures.captures.find(c => c.phase === "cache_sql_v1_apres_cloture_restart")!;
const meta = prise.request.meta!, args = prise.request.arguments as ArgumentsPriseRappelM1;
const session = { personne: "admin-rappel-fictif", appareilId: meta.appareil, urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF" };
const horloge = { maintenant: new Date(meta.horodatage_appareil), decalageMinutesUTC: 0 };
const m = (id = meta.cle) => ({ ...creerMutationPriseRappelM1(args, () => id, horloge, session), destination: session.urlBase, proprietaire: session.personne });
function monde(fetchImpl: typeof fetch) {
  const depot = new DepotOutboxMemoire(); let now = horloge.maintenant;
  const creer = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
    session: () => session, maintenant: () => now, verifierAvantEnvoi: async mutation => verifierDestinationPriseRappelM1(mutation, session) });
  return { depot, creer, avancer: () => { now = new Date(now.getTime() + 60000); } };
}
test("descripteur dédié ferme les arguments et garde toute issue HTTP incertaine", () => {
  const d = DESCRIPTEURS_MUTATION.get("prise_en_charge_rappel");
  expect(d).toMatchObject({ tool: "m1_prendre_en_charge_rappel_appareil", groupeSerie: "rappel", serialiserParChantier: true,
    conserverRefusHttpIncertains: true, verifierAvantEnvoi: true });
  expect(d?.construireArguments?.(m())).toEqual(args);
});
test("confirmation perdue puis refus préclaim conserve UUID/corps et bloque la suivante jusqu'au cache propre", async () => {
  const fetchImpl = jest.fn().mockRejectedValueOnce(new Error("FICTIF : réponse perdue après effet possible"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: { ok: false, erreur: "REJ-M1-RAPPEL-IDENTITE-INVALIDE", details: "FICTIF" } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: replay.response }), { status: 200 }));
  const h = monde(fetchImpl), first = await h.depot.inserer(m());
  const next = await h.depot.inserer(m("f6106514-51d2-4c1a-964f-f7a080a290f1"));
  expect((await h.creer().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]); h.avancer();
  expect((await h.creer().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]);
  expect(fetchImpl).toHaveBeenCalledTimes(2); expect((await h.depot.obtenir(next.id))?.statut).toBe("en_attente");
  expect((await h.depot.obtenir(first.id))?.payload).toEqual(first.payload); h.avancer();
  const r = await h.creer().vidangerFileSortante(); expect(r.envoyees).toContain(first.id);
  const requests = fetchImpl.mock.calls.slice(0, 3).map(c => JSON.parse(c[1].body));
  expect(requests[0]).toEqual(requests[1]); expect(requests[1]).toEqual(requests[2]);
  expect(requests[0]).toMatchObject({ args, idempotencyKey: meta.cle, deviceId: meta.appareil, deviceTimestamp: first.createdAtLocal });
  expect(Object.keys(requests[0].args).sort()).toEqual(["snapshot_attendu", "transfert_id"]);
});
test.each([403, 404, 400])("HTTP %i inconnu ne libère pas la série", async status => {
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: false, error: { type: "tool_call_blocked", message: "FICTIF" } }), { status }));
  const h = monde(fetchImpl), first = await h.depot.inserer(m()), next = await h.depot.inserer(m("3d42b597-468b-4c5e-a4b1-0c4dd1092c51"));
  const r = await h.creer().vidangerFileSortante(); expect(r.echecsPermanents).toEqual([]);
  expect((await h.depot.obtenir(first.id))?.statut).toBe("en_attente"); expect((await h.depot.obtenir(next.id))?.statut).toBe("en_attente"); expect(fetchImpl).toHaveBeenCalledTimes(1);
});
test("refus métier interne frais certain est visible, sans le confondre avec un refus de garde", async () => {
  const refusal = captures.captures.find(c => c.phase === "prise_snapshot_perime")!.response;
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: refusal }), { status: 200 }));
  const h = monde(fetchImpl), first = await h.depot.inserer(m());
  expect((await h.creer().vidangerFileSortante()).echecsPermanents).toMatchObject([{ id: first.id, verdict: { code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME" } }]);
});
test("un reçu terminal mal lié bloque la suivante avant tout RPC", async () => {
  const fetchImpl = jest.fn(), h = monde(fetchImpl), first = await h.depot.inserer({ ...m(), statut: "envoyee", resumeAccepte: { FICTIF: true } });
  const next = await h.depot.inserer(m("47d2b63b-68a4-46c1-858a-e3d6fab139d2"));
  const r = await h.creer().vidangerFileSortante(); expect(r.bloquees).toContain(next.id); expect(fetchImpl).not.toHaveBeenCalled();
  expect((await h.depot.obtenir(first.id))?.resumeAccepte).toEqual({ FICTIF: true });
});
test("destination originale modifiée ou personne étrangère ne provoque aucun envoi", async () => {
  const fetchImpl = jest.fn(), h = monde(fetchImpl);
  const other = { ...m(), proprietaire: "autre-fictif" } as MutationOutbox;
  await h.depot.inserer(other); const r = await h.creer().vidangerFileSortante(); expect(r.quarantaine).toContain(other.id); expect(fetchImpl).not.toHaveBeenCalled();
});
test("singleton production : garde admin et destination M1 indépendante de la branche matériaux", async () => {
  const cfg = require("../protocole/configuration") as typeof import("../protocole/configuration");
  const service = require("./service") as typeof import("./service"); mockDepotService = new DepotOutboxMemoire();
  const confirmer = (role: string, appareil = session.appareilId) => {
    cfg.definirConfigurationAppel({ urlBase: session.urlBase, jeton: session.jeton, appareilId: appareil });
    cfg.definirPersonneConfirmee({ jeton: session.jeton, appareilId: appareil, personne: session.personne, role });
  };
  confirmer("seller"); const depot = await service.obtenirDepot(), first = await depot.inserer(m());
  const precedent = global.fetch, fetchMock = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: prise.response }), { status: 200 })); global.fetch = fetchMock;
  const sansRecul = async () => { const row = await depot.obtenir(first.id); if (!row) throw new Error("intention perdue"); await depot.mettreAJour({ ...row, prochaineTentativeA: null }); };
  try {
    await service.declencherVidange(); expect(fetchMock).not.toHaveBeenCalled(); await sansRecul();
    confirmer("admin", "DEVICE-AUTRE-FICTIF"); await service.declencherVidange(); expect(fetchMock).not.toHaveBeenCalled(); await sansRecul();
    confirmer("admin"); expect((await service.declencherVidange())?.envoyees).toEqual([first.id]); expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((await depot.obtenir(first.id))?.payload).toEqual(first.payload);
  } finally { global.fetch = precedent; cfg.definirConfigurationAppel(null); cfg.definirPersonneConfirmee(null); }
});
test("perte fictive puis rôle/quota Cap réels : la suivante reste bloquée jusqu'à l'ACK propre après restart", async () => {
  const phase = (n: string) => capturesCap.phases.find(c => c.name === n)!;
  const primaire = phase("prise-acceptee"), fetchImpl = jest.fn().mockRejectedValueOnce(new Error("FICTIF perte de réponse après succès Cap capturé"));
  for (const name of ["role-retire-cache-inconnu", "quota-cache800-inconnu", "restart-succes-cache-exact"])
    fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: phase(name).response }), { status: 200 }));
  const h = monde(fetchImpl), first = await h.depot.inserer({ ...creerMutationPriseRappelM1(primaire.arguments as ArgumentsPriseRappelM1,
    () => primaire.mutation_uuid!, horloge, session), destination: session.urlBase, proprietaire: session.personne });
  const next = await h.depot.inserer({ ...first, id: "2b151e59-c5eb-4af3-957d-a72c4ab65404", sequence: null });
  for (let i = 0; i < 3; i++) {
    expect((await h.creer().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]);
    expect((await h.depot.obtenir(next.id))?.statut).toBe("en_attente"); expect(fetchImpl).toHaveBeenCalledTimes(i + 1); h.avancer();
  }
  const r = await h.creer().vidangerFileSortante(); expect(r.envoyees).toContain(first.id);
  const requests = fetchImpl.mock.calls.slice(0, 4).map(c => JSON.parse(c[1].body)); expect(requests.every(r => JSON.stringify(r) === JSON.stringify(requests[0]))).toBe(true);
  expect((await h.depot.obtenir(first.id))?.resumeAccepte).toEqual((primaire.response as unknown as { resultat: { resultat: unknown } }).resultat.resultat);
  // Une tentative suivante peut commencer après confirmation ; aucun second effet serveur n'est déduit du faux transport.
});
test("refus certain perdu : même UUID puis cache Cap exact devient refus définitif sans succès fabriqué", async () => {
  const primaire = capturesCap.phases.find(c => c.name === "refus-frais-certain")!, cache = capturesCap.phases.find(c => c.name === "restart-refus-cache-exact")!;
  const fetchImpl = jest.fn().mockRejectedValueOnce(new Error("FICTIF : refus certain perdu"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: cache.response }), { status: 200 }));
  const h = monde(fetchImpl), first = await h.depot.inserer({ ...creerMutationPriseRappelM1(primaire.arguments as ArgumentsPriseRappelM1,
    () => primaire.mutation_uuid!, horloge, session), destination: session.urlBase, proprietaire: session.personne });
  expect((await h.creer().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]); h.avancer();
  const r = await h.creer().vidangerFileSortante(); expect(r.envoyees).toEqual([]);
  expect(r.echecsPermanents).toMatchObject([{ id: first.id, verdict: { code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME" } }]);
  expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual(JSON.parse(fetchImpl.mock.calls[1][1].body));
});
