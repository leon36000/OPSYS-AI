const mockSession = jest.fn();
const mockInvoquer = jest.fn();
const mockDepotLocal = jest.fn();
const mockDepotOutbox = jest.fn();
const mockVidanger = jest.fn();
let mockEpoch = 0, mockAdmin = true;
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const epoch = mockEpoch, session = mockAdmin ? mockSession() : null;
  return { session, courante: () => session !== null && mockAdmin && epoch === mockEpoch && mockSession() !== null };
} }));
jest.mock("../protocole/client", () => ({ invoquerOutil: (p: unknown) => mockInvoquer(p) }));
jest.mock("../stockage/service", () => ({ obtenirDepotLocal: () => mockDepotLocal() }));
jest.mock("../outbox/service", () => ({ obtenirDepot: () => mockDepotOutbox(), declencherVidange: (c: () => boolean) => mockVidanger(c) }));
jest.mock("../outbox/id", () => ({ genererMutationId: () => "uuid-service-m10" }));
import { controleMemoire } from "./service";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { FIXTURES_M10 } from "./fixtures";
import { FIXTURES_DOSSIER_M10 } from "./fixturesDossier";
import type { ParametresAppelOutil } from "../protocole/client";
const session = { urlBase: "https://gateway.fictif.local", jeton: "token-fictif", appareilId: "appareil-fictif", personne: "gestionnaire.fictif" };
const f = FIXTURES_M10.reponses, fd = FIXTURES_DOSSIER_M10.reponses.dossier_complet;
const revisionId = fd.args.revision_ligne_id;
// Vecteur indépendant encodage.py réel, identique au contrôleur ; aucun calcul crypto dans ce test.
const ack = { ...f.arbitrage_accepte.enveloppe.resultat.resultat, revision_ligne_id: revisionId,
  ligne_id: "b9b04a4382a7b29ffb92637d650781589d1db50435a84093bc8e92b24d975639" };
let outbox: DepotOutboxMemoire, cache: DepotCleValeurMemoire, arbitree = false;

beforeEach(() => {
  mockEpoch++; mockAdmin = true; mockSession.mockReturnValue(session);
  mockInvoquer.mockReset(); mockDepotLocal.mockReset(); mockDepotOutbox.mockReset(); mockVidanger.mockReset();
  outbox = new DepotOutboxMemoire(); cache = new DepotCleValeurMemoire(); arbitree = false;
  const depot = avecProprietaire(outbox, () => mockSession()?.personne ?? null);
  mockDepotLocal.mockResolvedValue(cache); mockDepotOutbox.mockResolvedValue(depot);
  const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, fetchImpl: jest.fn(),
    appelerOutil: p => mockInvoquer(p), session: () => mockSession(), maintenant: () => new Date(),
    capturerGardeSession: () => { const epoch = mockEpoch; return () => epoch === mockEpoch && mockAdmin; } });
  mockVidanger.mockImplementation((c: () => boolean) => vidangeur.vidangerFileSortante(c));
  mockInvoquer.mockImplementation(async ({ requete }: ParametresAppelOutil) => {
    if (requete.tool === "m10_lister_signaux") return { ok: true, result: f.signaux_ouverts.enveloppe };
    if (requete.tool === "m10_lister_references") return { ok: true, result: requete.args?.decalage === 8 ? f.catalogue_page_2.enveloppe : f.catalogue_page_1.enveloppe };
    if (requete.tool === "m10_statut_decision") return { ok: true, result: f.decision_inconnue.enveloppe };
    if (requete.tool === "m10_statut_revision") return { ok: true, result: { ok: true, resultat: { statut: arbitree ? "distincts_confirmes" : "en_attente" } } };
    if (requete.tool === "m10_lire_revision") {
      const r = fd.enveloppe.resultat.resultat;
      const revision = arbitree ? { ...r.revision, statut: "distincts_confirmes", statut_le: ack.horodatage,
        reference_statut: { registre: "affaires", ligne_id: ack.ligne_id, hash_tete: ack.ligne_id } } : r.revision;
      return { ok: true, result: { ok: true, resultat: { accepte: true, resultat: { revision, faits: r.faits } } } };
    }
    if (requete.tool === "m10_arbitrer_revision") {
      expect(await outbox.obtenir("uuid-service-m10")).toMatchObject({ statut: "envoi", proprietaire: session.personne });
      arbitree = true; return { ok: true, result: { ok: true, resultat: { accepte: true, resultat: ack } } };
    }
    throw new Error("outil inattendu");
  });
  controleMemoire.invalider(); controleMemoire.actualiserConnectivite(true);
});

test("câblage natif : T0 distincts, outbox persistée, guard vivante et args N3 sans acteur", async () => {
  await controleMemoire.charger(); await controleMemoire.ouvrirRevision(revisionId);
  expect((await controleMemoire.arbitrer("distincts_confirmes")).ok).toBe(true);
  const calls = mockInvoquer.mock.calls.map(([p]) => p as ParametresAppelOutil);
  const mutation = calls.find(p => p.requete.tool === "m10_arbitrer_revision");
  expect(mutation?.urlBase).toBe(session.urlBase); expect(mutation?.jeton).toBe(session.jeton);
  expect(mutation?.requete).toMatchObject({ tool: "m10_arbitrer_revision", idempotencyKey: "uuid-service-m10", deviceId: session.appareilId,
    args: { revision_ligne_id: revisionId, statut: "distincts_confirmes" } });
  expect(mutation?.requete.args).not.toHaveProperty("par"); expect(mutation?.requete.args).not.toHaveProperty("role");
  expect(mutation?.requete.deviceTimestamp).toBe(mutation?.requete.args?.horodatage);
  expect(mockVidanger).toHaveBeenCalledWith(expect.any(Function));
  expect((await outbox.obtenir("uuid-service-m10"))?.resumeAccepte).toEqual(ack);
});

test("absence de rôle admin interdit lectures, SQLite et intentions avant bootstrap", async () => {
  mockAdmin = false; await controleMemoire.charger(); await controleMemoire.ouvrirRevision(revisionId);
  expect(controleMemoire.etat().dossier).toBeNull(); expect(mockInvoquer).not.toHaveBeenCalled();
  expect(mockDepotLocal).not.toHaveBeenCalled(); expect(mockDepotOutbox).not.toHaveBeenCalled();
  expect(mockVidanger).not.toHaveBeenCalled();
});

test("dossier/statuts seuls ne démarrent pas le KV SQLite ni n’écrivent un cache", async () => {
  await controleMemoire.lireDecision("inconnue"); await controleMemoire.ouvrirRevision(revisionId);
  expect(controleMemoire.etat().statutDecision).toMatchObject({ source: "serveur", valeur: { statut: null } });
  expect(mockDepotLocal).not.toHaveBeenCalled();
  for (const [p] of mockInvoquer.mock.calls) expect(p.requete).not.toHaveProperty("idempotencyKey");
});

test("cache personnel des deux sections informatif hors ligne, pas de dossier ni arbitrage", async () => {
  await controleMemoire.charger(); mockInvoquer.mockClear(); controleMemoire.actualiserConnectivite(false);
  await controleMemoire.charger();
  expect(controleMemoire.etat().catalogue?.source).toBe("cache");
  expect(controleMemoire.etat().signaux?.source).toBe("cache");
  await controleMemoire.ouvrirRevision(revisionId);
  expect(controleMemoire.peutArbitrer()).toBe(false);
  expect(mockInvoquer).not.toHaveBeenCalled(); expect(mockVidanger).not.toHaveBeenCalled();
});

test("refus serveur courant ne fait jamais ressortir les caches préexistants", async () => {
  await controleMemoire.charger();
  mockInvoquer.mockResolvedValue({ ok: true, result: f.lecture_revoquee.enveloppe });
  await controleMemoire.charger();
  expect(controleMemoire.etat().signaux?.source).toBe("refus");
  expect(controleMemoire.etat().catalogue?.source).toBe("refus");
  expect(controleMemoire.peutArbitrer()).toBe(false);
});

test("changement de scopes à personne/token identiques masque la lecture HTTP tardive", async () => {
  let release!: (v: unknown) => void, commence!: () => void;
  const courant = new Promise<void>(r => { commence = r; });
  mockInvoquer.mockImplementation(() => { commence(); return new Promise(r => { release = r; }); });
  const lecture = controleMemoire.lireDecision("DEC-fictive"); await courant;
  mockEpoch++; release({ ok: true, result: f.decision_proposee.enveloppe }); await lecture;
  expect(controleMemoire.etat().statutDecision).toBeNull(); expect(mockVidanger).not.toHaveBeenCalled();
});

test("scope retiré pendant bootstrap KV refuse les deux lectures avant HTTP et cache", async () => {
  let release!: (d: DepotCleValeurMemoire) => void, commence!: () => void;
  const initialisee = new Promise<void>(r => { commence = r; });
  const depotEnVol = new Promise<DepotCleValeurMemoire>(r => { release = r; });
  mockDepotLocal.mockImplementation(() => { commence(); return depotEnVol; });
  const chargement = controleMemoire.charger(); await initialisee; mockEpoch++; mockAdmin = false; release(cache);
  await chargement;
  expect(mockInvoquer).not.toHaveBeenCalled(); expect(controleMemoire.etat().catalogue).toBeNull();
  expect(controleMemoire.etat().signaux).toBeNull();
});
