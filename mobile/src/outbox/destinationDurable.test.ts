// All identities, hosts and business data in these regressions are fictitious.
import { DatabaseSync } from "node:sqlite";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let mockBase: DatabaseSync;
jest.mock("expo-sqlite", () => ({ openDatabaseAsync: async () => ({
  execAsync: async (sql: string) => { mockBase.exec(sql); },
  getAllAsync: async (sql: string, args: any[] = []) => mockBase.prepare(sql).all(...args),
  getFirstAsync: async (sql: string, args: any[] = []) => mockBase.prepare(sql).get(...args) ?? null,
  runAsync: async (sql: string, args: any[] = []) => mockBase.prepare(sql).run(...args),
}) }));

const A = "https://gateway-a.fictif.invalid", B = "https://gateway-b.fictif.invalid";
const ID = "00000000-0000-4000-8000-000000000091", NOTE = "[fictif:true] Rappel privé du chantier A";
let dossier: string, fichier: string, originalFetch: typeof fetch, horsLigne: boolean;
let appels: { url: string; body: any; authorization: string }[];

function demarrer(urlBase: string, jeton = "TOKEN-FICTIF") {
  jest.resetModules();
  const c = require("../protocole/configuration") as typeof import("../protocole/configuration");
  c.definirConfigurationAppel({ urlBase, jeton, appareilId: "APP-FICTIF" });
  c.definirPersonneConfirmee({ jeton, appareilId: "APP-FICTIF", personne: "VENDEUR-FICTIF", role: "seller" });
  return require("./service") as typeof import("./service");
}

beforeEach(() => {
  dossier = mkdtempSync(join(tmpdir(), "opsys-destination-fictif-"));
  fichier = join(dossier, "outbox.sqlite"); mockBase = new DatabaseSync(fichier);
  appels = []; horsLigne = false; originalFetch = global.fetch;
  global.fetch = jest.fn(async (url, init) => {
    appels.push({ url: String(url), body: JSON.parse(String(init?.body)), authorization: (init?.headers as any).authorization });
    if (horsLigne) throw new TypeError("Network request failed (fictif)");
    return { ok: true, status: 200, json: async () => ({ ok: true, result: {
      ok: true, resultat: { accepte: true, resultat: { lead_id: "LEAD-A-FICTIF", ligne_id: "INTERACTION-FICTIVE", horodatage: "2026-10-21T12:00:00Z" } }, rejoue: false,
    } }) } as Response;
  });
});
afterEach(() => { global.fetch = originalFetch; mockBase.close(); rmSync(dossier, { recursive: true }); });

async function creerNote() {
  const service = demarrer(A);
  const { creerMutationNote } = require("../m2/interaction") as typeof import("../m2/interaction");
  const depot = await service.obtenirDepot();
  const mutation = await depot.inserer(creerMutationNote("LEAD-A-FICTIF", NOTE, () => ID,
    { maintenant: new Date("2026-10-21T12:00:00Z"), decalageMinutesUTC: -240 }));
  return { service, depot, mutation };
}

async function redemarrer(url: string, jeton?: string) {
  mockBase.close(); mockBase = new DatabaseSync(fichier);
  return demarrer(url, jeton);
}

test("offline A → restart B, same person: no RPC transfers A's note or UUID; A can resume", async () => {
  const { service, depot, mutation } = await creerNote(); horsLigne = true;
  expect((await service.declencherVidange())?.remisesEnAttente).toEqual([ID]);
  expect(appels).toHaveLength(1); expect(appels[0]).toMatchObject({ url: A + "/tools/invoke", body: { idempotencyKey: ID, args: { resume: NOTE } } });
  const attente = await depot.obtenir(ID); expect(attente?.statut).toBe("en_attente");
  await depot.mettreAJour({ ...attente!, prochaineTentativeA: null });
  const avant = await depot.obtenir(ID); horsLigne = false; appels = [];
  const surB = await redemarrer(B, "TOKEN-B-FICTIF");
  const rapportB = await surB.declencherVidange();
  expect(appels).toEqual([]);
  expect(rapportB?.quarantaine).toEqual([ID]);
  expect(await (await surB.obtenirDepot()).obtenir(ID)).toEqual(avant);
  const surA = await redemarrer(A, "TOKEN-A-RENOUVELE-FICTIF");
  expect((await surA.declencherVidange())?.envoyees).toEqual([ID]);
  await surA.declencherVidange(); expect(appels).toHaveLength(1);
  expect(appels[0]).toMatchObject({ url: A + "/tools/invoke", authorization: "Bearer TOKEN-A-RENOUVELE-FICTIF", body: { idempotencyKey: mutation.id, args: { resume: NOTE } } });
});

test("rotation on same A survives SQLite restart and keeps the original UUID", async () => {
  const { mutation } = await creerNote();
  const service = await redemarrer(A, "TOKEN-A-ROTATION-FICTIF");
  expect((await service.declencherVidange())?.envoyees).toEqual([ID]);
  await service.declencherVidange(); expect(appels).toHaveLength(1);
  expect(appels[0]).toMatchObject({ url: A + "/tools/invoke", body: { idempotencyKey: mutation.id } });
});

test("migration without a recorded destination preserves the complete row and quarantines on A and B", async () => {
  // Independent pre-fix DDL: a person gives no evidence of which gateway owns the note.
  mockBase.exec(`CREATE TABLE outbox (id TEXT PRIMARY KEY NOT NULL, sequence INTEGER NOT NULL,
    type TEXT NOT NULL, chantier_id TEXT NOT NULL, payload TEXT NOT NULL, depends_on TEXT,
    statut TEXT NOT NULL, tentatives INTEGER NOT NULL DEFAULT 0, created_at_local TEXT NOT NULL,
    prochaine_tentative_a TEXT, proprietaire TEXT, resume_accepte TEXT)`);
  mockBase.prepare("INSERT INTO outbox VALUES (?,1,'lead_note','lead:LEAD-A-FICTIF',?,NULL,'en_attente',2,'2026-10-21T08:00:00-04:00',NULL,'VENDEUR-FICTIF',NULL)")
    .run(ID, JSON.stringify({ lead_id: "LEAD-A-FICTIF", resume: NOTE, horodatage: "2026-10-21T08:00:00-04:00" }));
  const avant = mockBase.prepare("SELECT * FROM outbox").get();
  for (const url of [A, B, A]) {
    const service = await redemarrer(url);
    expect((await service.declencherVidange())?.quarantaine).toEqual([ID]);
    expect(mockBase.prepare("SELECT * FROM outbox").get()).toMatchObject(avant!);
  }
  expect(appels).toEqual([]);
});

test("destination is checked again at the final RPC boundary when the session changes after selection", async () => {
  const { depot } = await creerNote();
  const avant = await depot.obtenir(ID);
  const { creerVidangeur } = require("./vidangeur") as typeof import("./vidangeur");
  const { DESCRIPTEURS_MUTATION } = require("./descripteurs") as typeof import("./descripteurs");
  const { invoquerOutil } = require("../protocole/client") as typeof import("../protocole/client");
  let lectures = 0;
  const rapport = await creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION,
    appelerOutil: invoquerOutil, fetchImpl: global.fetch, maintenant: () => new Date(),
    session: () => ({ urlBase: ++lectures === 1 ? A : B, jeton: "TOKEN-FICTIF", appareilId: "APP-FICTIF", personne: "VENDEUR-FICTIF" }),
  }).vidangerFileSortante();
  expect(appels).toEqual([]); expect(rapport.arret).toEqual({ genre: "session_changee" });
  expect(await depot.obtenir(ID)).toEqual(avant);
});

test.each(["memoire", "sqlite"])("%s CAS cannot retarget an intention or accept a stale destination", async moteur => {
  const { depot: sqlite, mutation } = await creerNote();
  const { DepotOutboxMemoire, capturerMutationOutbox } = require("./depot") as typeof import("./depot");
  const depot = moteur === "sqlite" ? sqlite : new DepotOutboxMemoire();
  if (moteur === "memoire") await depot.inserer(mutation);
  const avant = (await depot.obtenir(ID))!;
  expect(await depot.mettreAJourSiInchangee(capturerMutationOutbox(avant), { ...avant, destination: B })).toBe(false);
  expect(await depot.obtenir(ID)).toEqual(avant);
  if (moteur === "sqlite") {
    mockBase.prepare("UPDATE outbox SET destination=? WHERE id=?").run(B, ID);
    expect(await depot.mettreAJourSiInchangee(capturerMutationOutbox(avant), { ...avant, statut: "envoi" })).toBe(false);
    expect(await depot.obtenir(ID)).toMatchObject({ destination: B, statut: "en_attente", payload: avant.payload });
  }
});
