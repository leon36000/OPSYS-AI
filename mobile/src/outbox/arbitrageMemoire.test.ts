/** Fictif : vrai dépôt, descripteur, client et vidangeur ; transport seul simulé. */
import { DepotOutboxMemoire } from "./depot";
import { avecProprietaire } from "./proprietaire";
import { creerVidangeur } from "./vidangeur";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { invoquerOutil } from "../protocole/client";
import { creerMutationArbitrageMemoire, arbitragesMemoireEnFile } from "../m10/arbitrageOutbox";
import { FIXTURES_M10 } from "../m10/fixtures";
import type { MutationOutbox } from "./types";
const cap = FIXTURES_M10.reponses.arbitrage_accepte.enveloppe;
const ack = cap.resultat.resultat;
// Calculé par le vrai encodage.py, vecteur-autre-01.json ; aucun encodeur crypto dans les tests.
const autreAck = { ...ack, revision_ligne_id: "a".repeat(64),
  ligne_id: "28baa140bb8d384a1d29293cece61fd1b1fb7e4ea28a4d608fad55e56651764f" };
const { par: _par, role: _role, source_decision: _source, ...legacyAck } = ack;
const session = { urlBase: "https://fictif.local", jeton: "jeton-fictif", appareilId: "appareil-fictif", personne: ack.par };
const horloge = { maintenant: new Date("2026-09-16T15:10:00Z"), decalageMinutesUTC: -240 };
let compteur = 0;
async function intention(depot: DepotOutboxMemoire, revisionId: string = ack.revision_ligne_id, owner: string = ack.par) {
  return avecProprietaire(depot, () => owner).inserer(creerMutationArbitrageMemoire(revisionId, "distincts_confirmes", () => `uuid-fictif-${++compteur}`, horloge));
}
const couple = (v: unknown) => ({ ok: true, resultat: { accepte: true, resultat: v } });
const http = (result: unknown, status = 200) => new Response(JSON.stringify({ ok: true, result }), { status });
function vidanger(depot: DepotOutboxMemoire, fetchImpl: typeof fetch, maintenant: () => Date = () => horloge.maintenant,
  courante: () => typeof session | null = () => session) {
  return creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, maintenant, session: courante });
}
function requetes(fetchImpl: jest.Mock): Array<{ tool: string; args: Record<string, unknown>; idempotencyKey: string; deviceId: string; deviceTimestamp: string }> {
  return fetchImpl.mock.calls.map(([_url, init]) => JSON.parse(init.body));
}

test("la première intention durable est lisible avant HTTP, reçu natif et args sans acteur", async () => {
  const depot = new DepotOutboxMemoire(), m = await intention(depot);
  const fetchImpl = jest.fn(async () => {
    expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoi", proprietaire: ack.par, payload: m.payload });
    return http(cap);
  });
  const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.envoyees).toEqual([m.id]);
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoyee", resumeAccepte: ack });
  expect(requetes(fetchImpl)).toEqual([{ tool: "m10_arbitrer_revision", args: m.payload,
    idempotencyKey: m.id, deviceId: session.appareilId, deviceTimestamp: m.createdAtLocal }]);
  expect(requetes(fetchImpl)[0].args).not.toHaveProperty("par");
  expect(requetes(fetchImpl)[0].args).not.toHaveProperty("role");
});

test("réponse perdue puis restart : recul, même UUID/payload/owner et replay unique", async () => {
  const depot = new DepotOutboxMemoire(), m = await intention(depot), suivante = await intention(depot);
  const perdu = jest.fn(async () => { throw new Error("réponse perdue après effet fictif"); });
  const premier = await vidanger(depot, perdu).vidangerFileSortante();
  expect(premier.remisesEnAttente).toEqual([m.id]);
  expect(premier.bloquees).toContain(suivante.id);
  const redemarre = new DepotOutboxMemoire();
  const rows: MutationOutbox[] = JSON.parse(JSON.stringify(await depot.lister()));
  for (const row of rows) await redemarre.inserer(row);
  const reprise = jest.fn(async () => http(FIXTURES_M10.reponses.arbitrage_rejoue.enveloppe));
  await vidanger(redemarre, reprise).vidangerFileSortante();
  expect(reprise).not.toHaveBeenCalled();
  const rapport = await vidanger(redemarre, reprise, () => new Date("2026-09-16T15:10:02Z")).vidangerFileSortante();
  expect(rapport.envoyees).toEqual([m.id]);
  expect(requetes(reprise)[0]).toEqual(requetes(perdu)[0]);
  expect(reprise).toHaveBeenCalledTimes(1);
  expect(arbitragesMemoireEnFile(await redemarre.lister()).find(x => x.id === m.id)).toMatchObject({ statut: "envoyee", personne: ack.par });
});

test.each([undefined, {}, { ok: true, resultat: ack }, couple(legacyAck), couple({ ...ack, horodatage: "2026-09-16T15:11:00+00:00" }),
  { ok: true, resultat: { accepte: false, verdict: {} } }])("réponse mal formée %p conserve l’intention et la série", async result => {
  const depot = new DepotOutboxMemoire(), m = await intention(depot), suivante = await intention(depot);
  const fetchImpl = jest.fn(async () => http(result));
  const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.remisesEnAttente).toEqual([m.id]);
  expect(rapport.echecsPermanents).toEqual([]);
  expect(rapport.bloquees).toContain(suivante.id);
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "en_attente", tentatives: 1, payload: m.payload, proprietaire: ack.par });
});

test.each([null, legacyAck, { ...ack, ligne_id: "0".repeat(64) }, { ...ack, par: "autre.fictif" }])(
  "ancien envoyé avec mauvais reçu %p bloque une nouvelle intention, autre objet libre", async resumeAccepte => {
    const depot = new DepotOutboxMemoire(), ancienne = await intention(depot);
    await depot.mettreAJour({ ...ancienne, statut: "envoyee", resumeAccepte });
    const nouvelle = await intention(depot), autre = await intention(depot, autreAck.revision_ligne_id);
    const fetchImpl = jest.fn(async () => http(couple(autreAck)));
    const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
    expect(rapport.envoyees).toEqual([autre.id]);
    expect(rapport.bloquees).toContain(nouvelle.id);
    expect(requetes(fetchImpl).map(x => x.idempotencyKey)).toEqual([autre.id]);
  },
);

test("un envoyé au reçu canonique libère une passe ultérieure de la même série", async () => {
  const depot = new DepotOutboxMemoire(), ancienne = await intention(depot);
  await depot.mettreAJour({ ...ancienne, statut: "envoyee", resumeAccepte: ack });
  const nouvelle = await intention(depot), fetchImpl = jest.fn(async () => http(cap));
  expect((await vidanger(depot, fetchImpl).vidangerFileSortante()).envoyees).toEqual([nouvelle.id]);
});

test("owner changé : quarantaine réelle, seconde intention même objet bloquée, autre objet indépendant", async () => {
  const depot = new DepotOutboxMemoire(), premiere = await intention(depot, ack.revision_ligne_id, "ancien.fictif");
  const suivante = await intention(depot), autre = await intention(depot, autreAck.revision_ligne_id);
  const fetchImpl = jest.fn(async () => http(couple(autreAck)));
  const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.quarantaine).toContain(premiere.id);
  expect(rapport.bloquees).toContain(suivante.id);
  expect(rapport.envoyees).toEqual([autre.id]);
  expect(await depot.obtenir(premiere.id)).toMatchObject({ proprietaire: "ancien.fictif", statut: "en_attente", tentatives: 0 });
});

test("refus nominal string devient terminal connu et ne relance pas automatiquement", async () => {
  const depot = new DepotOutboxMemoire(), m = await intention(depot);
  const fetchImpl = jest.fn(async () => http({ ok: true, resultat: { accepte: false, verdict: "REJ-REVISION-SIGNALEMENT-INTROUVABLE" } }));
  const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.echecsPermanents).toEqual([{ id: m.id, verdict: { code: "REJ-REVISION-SIGNALEMENT-INTROUVABLE", detail: "" } }]);
  expect((await depot.obtenir(m.id))?.statut).toBe("echec_permanent");
  await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("payload mal formé reste en file sans HTTP ni champs devinés", async () => {
  const depot = new DepotOutboxMemoire(), m = await intention(depot);
  await depot.mettreAJour({ ...m, payload: { ...m.payload, role: "admin" } });
  const fetchImpl = jest.fn(async () => http(cap));
  const rapport = await vidanger(depot, fetchImpl).vidangerFileSortante();
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(rapport.remisesEnAttente).toEqual([m.id]);
  expect((await depot.obtenir(m.id))?.payload).toHaveProperty("role", "admin");
});


test("rôle retiré à tuple identique pendant stockage : garde capturée interdit tout HTTP", async () => {
  let stockage!: () => void, release!: () => void, generation = 0;
  const enAttente = new Promise<void>(resolve => { stockage = resolve; });
  class DepotSuspendu extends DepotOutboxMemoire {
    async mettreAJourSiInchangee(...args: Parameters<DepotOutboxMemoire["mettreAJourSiInchangee"]>): Promise<boolean> {
      const applique = await super.mettreAJourSiInchangee(...args);
      if (applique && args[1].statut === "envoi") { stockage(); await new Promise<void>(resolve => { release = resolve; }); }
      return applique;
    }
  }
  const depot = new DepotSuspendu(), m = await intention(depot), fetchImpl = jest.fn(async () => http(cap));
  const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, maintenant: () => horloge.maintenant, session: () => session,
    capturerGardeSession: () => { const captured = generation; return () => captured === generation; } });
  const pending = v.vidangerFileSortante();
  await enAttente; generation++; release();
  const rapport = await pending;
  expect(rapport.arret).toEqual({ genre: "session_changee" });
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "en_attente", payload: m.payload, tentatives: 0, proprietaire: ack.par });
});

test("personne retirée avant HTTP : intention originale intacte et sans tentative", async () => {
  let selection!: () => void, release!: () => void, appels = 0;
  let courante: typeof session | null = session;
  const bloque = new Promise<void>(resolve => { selection = resolve; });
  class DepotSuspendu extends DepotOutboxMemoire {
    async lister(): Promise<MutationOutbox[]> {
      if (++appels === 2) { selection(); await new Promise<void>(resolve => { release = resolve; }); }
      return super.lister();
    }
  }
  const depot = new DepotSuspendu(), m = await intention(depot), fetchImpl = jest.fn(async () => http(cap));
  const pending = vidanger(depot, fetchImpl, () => horloge.maintenant, () => courante).vidangerFileSortante();
  await bloque; courante = null; release();
  expect((await pending).arret).toEqual({ genre: "session_changee" });
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "en_attente", proprietaire: ack.par, tentatives: 0 });
});
