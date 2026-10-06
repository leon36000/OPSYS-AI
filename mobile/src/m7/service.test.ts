const mockObtenirSessionEnvoi = jest.fn();
const mockInvoquerOutil = jest.fn();
const mockGenererMutationId = jest.fn(() => "uuid-m7-1");

jest.mock("../protocole/configuration", () => ({
  obtenirSessionEnvoi: () => mockObtenirSessionEnvoi(),
}));
jest.mock("../protocole/client", () => ({
  invoquerOutil: (params: unknown) => mockInvoquerOutil(params),
}));
jest.mock("../outbox/id", () => ({
  genererMutationId: () => mockGenererMutationId(),
}));

import { controleMarketing } from "./service";

const session = {
  urlBase: "https://gateway.example.test",
  jeton: "bearer-token",
  appareilId: "device-123",
  personne: "nathan",
};
const preuve = { source: "brand_profiles", revision: 3, sha256: "a".repeat(64) };
let status: "PROPOSE" | "APPROVED" | "REJECTED" | "CONSENTEMENT_RETIRE";
let refusDecision = false;

function enveloppe(value: unknown) {
  return { ok: true, resultat: { accepte: true, resultat: value } };
}

function ligne() {
  return {
    contenu_id: "contenu-1",
    wct_id: "wct-1",
    plateforme: "instagram",
    revision: 1,
    approval_status: status,
    exporte: false,
    marque_source: preuve,
    fraicheur_marque: "courante",
    texte: "Texte complet du brouillon",
    origine_texte: "chantier",
    mots_clics: [],
    lien_utm: "https://example.test/utm",
    avertissements: [],
    decision: null,
    consentement: {
      recueilli_par: "nathan",
      recueilli_le: "2026-10-01T10:00:00Z",
      version_texte: "v1",
    },
  };
}

function resultatDecision(decision: "approuver" | "rejeter") {
  return {
    contenu_id: "contenu-1",
    plateforme: "instagram",
    approval_status: decision === "approuver" ? "APPROVED" : "REJECTED",
    par: "nathan",
    source: "appareil",
    horodatage: "2026-10-04T12:00:00.000Z",
    empreinte_texte: "b".repeat(64),
    prochaine_etape: "suite",
  };
}

beforeEach(() => {
  mockInvoquerOutil.mockClear();
  status = "PROPOSE";
  refusDecision = false;
  mockObtenirSessionEnvoi.mockReturnValue(session);
  mockGenererMutationId.mockReturnValue("uuid-m7-1");
  mockInvoquerOutil.mockImplementation(async ({ requete }: { requete: { tool: string; args?: Record<string, unknown> } }) => {
    if (requete.tool === "m9_lister_demandes_approbation") {
      return { ok: true, result: enveloppe({ demandes: [], proprietaire: true, total_en_attente: 0, affichees: 0, reste: 0 }) };
    }
    if (requete.tool === "m7_lister_contenus_chantier") {
      return { ok: true, result: enveloppe({ total: 1, marque_courante: preuve, contenus: [ligne()], decalage: 0, suivant: null, reste: 0 }) };
    }
    if (refusDecision) {
      return { ok: true, result: { ok: true, resultat: { accepte: false, verdict: { code: "REJ-CONTENU-PERIME", detail: "détail backend" } } } };
    }
    const decision = requete.args?.decision as "approuver" | "rejeter";
    status = decision === "approuver" ? "APPROVED" : "REJECTED";
    return { ok: true, result: enveloppe(resultatDecision(decision)) };
  });
  controleMarketing.actualiserConnectivite(true);
  controleMarketing.invalider();
  controleMarketing.actualiserConnectivite(true);
});

test("le service envoie l’identité appareil, la clé idempotente et l’horodatage sans personne/rôle/CSRF", async () => {
  await controleMarketing.charger();
  const result = await controleMarketing.decider("contenu-1", "rejeter", "Motif suffisamment clair");
  expect(result.ok).toBe(true);

  const appel = mockInvoquerOutil.mock.calls
    .map(([params]) => params as { urlBase: string; jeton: string; requete: Record<string, unknown> })
    .find(({ requete }) => requete.tool === "m7_decider_contenu");
  expect(appel).toBeDefined();
  expect(appel?.urlBase).toBe(session.urlBase);
  expect(appel?.jeton).toBe(session.jeton);
  expect(appel?.requete).toMatchObject({
    tool: "m7_decider_contenu",
    args: { contenu_id: "contenu-1", decision: "rejeter", motif: "Motif suffisamment clair" },
    idempotencyKey: "uuid-m7-1",
    deviceId: session.appareilId,
  });
  const requete = appel?.requete as { args: Record<string, unknown>; deviceTimestamp: string };
  expect(requete.deviceTimestamp).toBe(requete.args.horodatage);
  expect(requete.args).not.toHaveProperty("personne");
  expect(requete.args).not.toHaveProperty("role");
  expect(requete.args).not.toHaveProperty("csrf");
  expect(appel?.requete).not.toHaveProperty("personne");
  expect(appel?.requete).not.toHaveProperty("role");
});

test("une session appareil absente ne déclenche aucun appel", async () => {
  mockObtenirSessionEnvoi.mockReturnValue(null);
  await controleMarketing.charger();
  expect(mockInvoquerOutil).not.toHaveBeenCalled();
  expect(controleMarketing.etat().items).toEqual([]);
});

test("un refus métier transporté en HTTP réussi reste un refus après relecture", async () => {
  refusDecision = true;
  await controleMarketing.charger();
  const result = await controleMarketing.decider("contenu-1", "approuver");
  expect(result).toEqual({ ok: false, code: "refus_serveur_relue" });
  expect(controleMarketing.etat().statut).toBe("pret");
  expect(controleMarketing.etat().message).toBe("Décision refusée par le serveur; la liste a été relue.");
});
