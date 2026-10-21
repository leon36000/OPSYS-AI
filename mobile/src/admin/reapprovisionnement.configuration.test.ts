import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { creerChargeurReapprovisionnementM6 } from "./reapprovisionnement";
import capturesSql from "../m6/fixturesReapprovisionnement.json";

// Configuration, client et lecteur réels ; transport HTTP uniquement fictif et différé.
// Ces tests ne qualifient aucun téléphone ni appel réseau Native.
const config = { urlBase: "http://127.0.0.1:0", jeton: "jeton-A-fictif", appareilId: "appareil-A-fictif" };
const personne = { jeton: config.jeton, appareilId: config.appareilId, personne: "admin-A-fictif", role: "admin" };
const corpsRefus = { ok: true, result: { ok: true, resultat: { accepte: false,
  verdict: { code: "REJ-M6-REAPPRO-REGISTRE-INVALIDE", detail: "Source fictive illisible" } } } };
let epoch = 0, enLigne = true;
const fetchFictif = jest.fn();
function response(status = 200, body: unknown = corpsRefus): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}
const creer = () => creerChargeurReapprovisionnementM6({
  capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const n = epoch; return { enLigne, courante: () => enLigne && n === epoch }; },
  appelerOutil: invoquerOutil, fetchImpl: fetchFictif as typeof fetch,
  horloge: () => new Date("2026-10-08T12:00:00Z"),
});
beforeEach(() => {
  jest.clearAllMocks(); epoch++; enLigne = true; fetchFictif.mockResolvedValue(response());
  definirConfigurationAppel(config); definirPersonneConfirmee(personne);
});
afterEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });

test("outil et arguments exacts sans seuil, auteur, agent ou clé de mutation", async () => {
  const resultat = await creer().chargerReapprovisionnement(7);
  expect(resultat).toEqual({ source: "refus", verdict: corpsRefus.result.resultat.verdict });
  const [url, init] = fetchFictif.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:0/tools/invoke");
  expect(JSON.parse(init.body)).toEqual({ tool: "m6_lire_reapprovisionnement_appareil", args: { decalage: 7, limite: 8 } });
  expect(fetchFictif).toHaveBeenCalledTimes(1);
});
test.each(["employee", "seller", undefined])("rôle %s : aucune émission", async role => {
  definirPersonneConfirmee({ ...personne, role });
  expect(await creer().chargerReapprovisionnement()).toBeNull();
  expect(fetchFictif).not.toHaveBeenCalled();
});
test("hors ligne : aucune copie locale ni émission", async () => {
  enLigne = false;
  expect(await creer().chargerReapprovisionnement()).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(fetchFictif).not.toHaveBeenCalled();
});
test.each(["role", "jeton", "URL", "appareil", "personne", "deconnexion", "retour_personne", "retour_reseau"])("%s change pendant HTTP : réponse ancienne fermée", async changement => {
  let finir!: (v: Response) => void;
  fetchFictif.mockImplementationOnce(() => new Promise<Response>(r => { finir = r; }));
  const attente = creer().chargerReapprovisionnement();
  switch (changement) {
    case "role": definirPersonneConfirmee({ ...personne, role: "employee" }); break;
    case "jeton": definirConfigurationAppel({ ...config, jeton: "jeton-B-fictif" }); definirPersonneConfirmee({ ...personne, jeton: "jeton-B-fictif" }); break;
    case "URL": definirConfigurationAppel({ ...config, urlBase: "http://127.0.0.1:1" }); break;
    case "appareil": definirConfigurationAppel({ ...config, appareilId: "appareil-B-fictif" }); definirPersonneConfirmee({ ...personne, appareilId: "appareil-B-fictif" }); break;
    case "personne": definirPersonneConfirmee({ ...personne, personne: "admin-B-fictif" }); break;
    case "deconnexion": definirConfigurationAppel(null); definirPersonneConfirmee(null); break;
    case "retour_personne": definirPersonneConfirmee({ ...personne, personne: "admin-B-fictif" }); definirPersonneConfirmee(personne); break;
    case "retour_reseau": enLigne = false; epoch++; enLigne = true; epoch++; break;
  }
  finir(response());
  expect(await attente).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(fetchFictif).toHaveBeenCalledTimes(1);
});
test("confirmation identique : refus courant conservé", async () => {
  let finir!: (v: Response) => void;
  fetchFictif.mockImplementationOnce(() => new Promise<Response>(r => { finir = r; }));
  const attente = creer().chargerReapprovisionnement();
  definirConfigurationAppel({ ...config }); definirPersonneConfirmee({ ...personne });
  finir(response());
  expect(await attente).toEqual({ source: "refus", verdict: corpsRefus.result.resultat.verdict });
});
test.each([401, 403])("HTTP %i : refus connu sans projection", async status => {
  fetchFictif.mockResolvedValueOnce(response(status, { error: { type: "unauthorized", message: "Fictif" } }));
  expect(await creer().chargerReapprovisionnement()).toMatchObject({ source: "refus", verdict: { code: `http_${status}` } });
});
test("refus puis erreur réseau : aucune réponse métier ni cache ressuscité", async () => {
  const lectures = creer();
  expect(await lectures.chargerReapprovisionnement()).toMatchObject({ source: "refus" });
  fetchFictif.mockRejectedValueOnce(new Error("Panne fictive"));
  expect(await lectures.chargerReapprovisionnement()).toMatchObject({ source: "aucune", raison: { code: "erreur_reseau" } });
});
test.each([-1, 10001, 0.5, NaN, Infinity])("offset %s : pas d'émission ou réparation", async offset => {
  expect(await creer().chargerReapprovisionnement(offset)).toMatchObject({ source: "aucune", raison: { code: "lecture_indisponible" } });
  expect(fetchFictif).not.toHaveBeenCalled();
});
const phasesService = ["corpus-vide", "stock-bas-vrai-writer", "stock-suffisant-courant", "seuil-absent", "configuration-invalide"];
const capturesService = capturesSql.captures.filter(c => phasesService.includes(c.phase));
test("cinq captures de succès sélectionnées présentes ; autres cas couverts par le lecteur pur", () => {
  expect(capturesService.map(c => c.phase).sort()).toEqual([...phasesService].sort());
});
test.each(capturesService.map(c => [c.phase, c] as const))("%s : DTO SQL source consommé par le vrai client et le service", async (_phase, c) => {
  // Capture Python/SQL réelle, mais enveloppe HTTP et fetch de ce test sont fictifs.
  // Aucun nouveau HTTP ni Gateway, téléphone ou préparation du stock n'est revendiqué.
  expect(capturesSql.fictif).toBe(true);
  expect(c.request.toolName).toBe("m6_lire_reapprovisionnement_appareil");
  expect(c.request.args.limite).toBe(8);
  const avant = JSON.stringify(c.response);
  fetchFictif.mockResolvedValueOnce(response(200, { ok: true, result: c.response }));
  expect(await creer().chargerReapprovisionnement(c.request.args.decalage)).toEqual({
    source: "serveur", valeur: c.response.resultat, misAJourLe: "2026-10-08T12:00:00.000Z",
  });
  expect(JSON.stringify(c.response)).toBe(avant);
  expect(JSON.parse(fetchFictif.mock.calls[0][1].body)).toEqual({ tool: c.request.toolName, args: c.request.args });
});
