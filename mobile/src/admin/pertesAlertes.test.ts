import type { ParametresAppelOutil } from "../protocole/client";

// Ce transport et ces lecteurs sont FICTIFS : ils isolent les gardes du service,
// sans qualifier le DTO métier, SQLite, un téléphone ou un appel natif.
jest.mock("../m6/pertesAlertes", () => ({
  OUTIL_LISTE_WCT_PERTES: "m6_lister_wct_pertes_appareil",
  OUTIL_PERTES_ALERTES_WCT: "m6_lire_pertes_alertes_wct_appareil",
  construireArgumentsListeWct: (decalage = 0, limite = 8) => ({ decalage, limite }),
  construireArgumentsPertesWct: (wct_id: string, decalage = 0, limite = 8) => {
    if (!wct_id) throw new Error("identifiant fictif vide");
    return { wct_id, decalage, limite };
  },
  lireListeWctPertes: (v: unknown, args: unknown) => mockLire(v, args),
  lirePertesAlertesWct: (v: unknown, args: unknown) => mockLire(v, args),
}));
const mockLire = jest.fn();
const { creerChargeurPertesAlertesM6 } = require("./pertesAlertes");

const preuveFictive = { fictif: true, lecture: "WCT-A-FICTIF" };
let epochSession = 0, epochReseau = 0, admin = true, connecte = true;
const appel = jest.fn();
const fetchFictif = jest.fn() as unknown as typeof fetch;
const captureSession = jest.fn(() => {
  const epoch = epochSession;
  return { session: admin ? { urlBase: "http://127.0.0.1:0", jeton: "jeton-fictif", appareilId: "appareil-fictif", personne: "admin-fictif" } : null,
    courante: () => admin && epoch === epochSession };
});
const captureReseau = () => {
  const epoch = epochReseau;
  return { enLigne: connecte, courante: () => connecte && epoch === epochReseau };
};
const creer = () => creerChargeurPertesAlertesM6({ capturerSession: captureSession, capturerReseau: captureReseau,
  appelerOutil: appel, fetchImpl: fetchFictif, horloge: () => new Date("2026-10-08T12:00:00Z") });
beforeEach(() => {
  epochSession++; epochReseau++; admin = true; connecte = true; jest.clearAllMocks();
  appel.mockResolvedValue({ ok: true, result: { fictif: true } });
  mockLire.mockReturnValue({ ok: true, value: preuveFictive });
});

test("deux outils de lecture exacts sans agent, identité métier ou clé de mutation", async () => {
  const lectures = creer();
  expect(await lectures.chargerWcts(3)).toEqual({ source: "serveur", valeur: preuveFictive, misAJourLe: "2026-10-08T12:00:00.000Z" });
  await lectures.chargerPertes("WCT-A-FICTIF", 7);
  const requetes = appel.mock.calls.map(([p]: [ParametresAppelOutil]) => p.requete);
  expect(requetes).toEqual([
    { tool: "m6_lister_wct_pertes_appareil", args: { decalage: 3, limite: 8 } },
    { tool: "m6_lire_pertes_alertes_wct_appareil", args: { wct_id: "WCT-A-FICTIF", decalage: 7, limite: 8 } },
  ]);
  expect(mockLire.mock.calls.map(([, args]) => args)).toEqual(requetes.map(p => p.args));
});
test("aucune session admin : aucun HTTP ni lecteur", async () => {
  admin = false;
  expect(await creer().chargerWcts()).toBeNull();
  expect(await creer().chargerPertes("WCT-A-FICTIF")).toBeNull();
  expect(appel).not.toHaveBeenCalled(); expect(mockLire).not.toHaveBeenCalled();
});
test("hors ligne : pas de cache, dépôt ou HTTP", async () => {
  connecte = false;
  expect(await creer().chargerWcts()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(appel).not.toHaveBeenCalled(); expect(mockLire).not.toHaveBeenCalled();
});
test("capture de session invalidée pendant HTTP : réponse tardive fermée avant lecteur", async () => {
  let finir!: (v: unknown) => void; appel.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = creer().chargerPertes("WCT-A-FICTIF"); epochSession++;
  finir({ ok: true, result: { fictif: true } });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(mockLire).not.toHaveBeenCalled();
});
test("réseau A→B→A ferme la réponse même après reconnexion", async () => {
  let finir!: (v: unknown) => void; appel.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = creer().chargerWcts(); connecte = false; epochReseau++; connecte = true; epochReseau++;
  finir({ ok: true, result: { fictif: true } });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(mockLire).not.toHaveBeenCalled();
});
test("révocation pendant le lecteur : aucune projection déposée", async () => {
  mockLire.mockImplementationOnce(() => { epochSession++; return { ok: true, value: preuveFictive }; });
  expect(await creer().chargerWcts()).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
test("un refus métier reste un refus explicite", async () => {
  mockLire.mockReturnValueOnce({ ok: false, code: "REJ-WCT-FICTIF", detail: "Source fictive absente" });
  expect(await creer().chargerPertes("WCT-A-FICTIF")).toEqual({ source: "refus", verdict: { code: "REJ-WCT-FICTIF", detail: "Source fictive absente" } });
});
test.each(["reponse_illisible", "reponse_tronquee", "outil_inconnu"])("%s : aucune donnée reconstituée", async code => {
  mockLire.mockReturnValueOnce({ ok: false, code, detail: "fictif" });
  expect(await creer().chargerWcts()).toMatchObject({ source: "aucune", raison: { code } });
});
test("un code inconnu n'est pas promu en panne passagère", async () => {
  mockLire.mockReturnValueOnce({ ok: false, code: "outil_indisponible", detail: "fictif" });
  expect(await creer().chargerWcts()).toEqual({ source: "refus", verdict: { code: "outil_indisponible", detail: "fictif" } });
});
test.each([401, 403])("HTTP %i : refus connu, aucune projection", async status => {
  appel.mockResolvedValueOnce({ ok: false, echec: { origine: "http", reessayable: false, status, message: "fictif" } });
  expect(await creer().chargerWcts()).toMatchObject({ source: "refus", verdict: { code: `http_${status}` } });
  expect(mockLire).not.toHaveBeenCalled();
});
test("échec réseau et exception : aucune ancienne lecture conservée", async () => {
  const lectures = creer(); await lectures.chargerWcts();
  appel.mockResolvedValueOnce({ ok: false, echec: { origine: "reseau", reessayable: true, message: "fictif" } });
  expect(await lectures.chargerWcts()).toMatchObject({ source: "aucune", raison: { code: "erreur_reseau" } });
  appel.mockRejectedValueOnce(new Error("fictif"));
  expect(await lectures.chargerWcts()).toMatchObject({ source: "aucune", raison: { code: "lecture_indisponible" } });
});
test("entrée invalide : pas de HTTP ni de réparation", async () => {
  expect(await creer().chargerPertes("")).toMatchObject({ source: "aucune", raison: { code: "lecture_indisponible" } });
  expect(appel).not.toHaveBeenCalled();
});
