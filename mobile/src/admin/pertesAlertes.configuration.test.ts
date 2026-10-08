import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { creerChargeurPertesAlertesM6 } from "./pertesAlertes";
import type { ParametresAppelOutil } from "../protocole/client";

// Configuration et gardes réelles ; transport différé FICTIF. Ni HTTP natif ni téléphone.
const config = { urlBase: "http://127.0.0.1:0", jeton: "jeton-A-fictif", appareilId: "appareil-A-fictif" };
const personne = { jeton: config.jeton, appareilId: config.appareilId, personne: "admin-A-fictif", role: "admin" };
const appel = jest.fn();
let epochReseau = 0, enLigne = true;
const lectures = () => creerChargeurPertesAlertesM6({
  capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const epoch = epochReseau; return { enLigne, courante: () => enLigne && epoch === epochReseau }; },
  appelerOutil: appel, fetchImpl: jest.fn() as unknown as typeof fetch, horloge: () => new Date("2026-10-08T12:00:00Z"),
});
beforeEach(() => {
  jest.clearAllMocks(); enLigne = true; epochReseau++;
  definirConfigurationAppel(config); definirPersonneConfirmee(personne);
});
afterEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });

test.each(["role", "jeton", "URL", "appareil", "personne", "deconnexion"])("configuration réelle %s change : réponse en vol fermée", async champ => {
  let finir!: (v: unknown) => void;
  appel.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = lectures().chargerPertes("WCT-A-FICTIF");
  switch (champ) {
    case "role": definirPersonneConfirmee({ ...personne, role: "employee" }); break;
    case "jeton": definirConfigurationAppel({ ...config, jeton: "jeton-B-fictif" });
      definirPersonneConfirmee({ ...personne, jeton: "jeton-B-fictif" }); break;
    case "URL": definirConfigurationAppel({ ...config, urlBase: "http://127.0.0.1:1" }); break;
    case "appareil": definirConfigurationAppel({ ...config, appareilId: "appareil-B-fictif" });
      definirPersonneConfirmee({ ...personne, appareilId: "appareil-B-fictif" }); break;
    case "personne": definirPersonneConfirmee({ ...personne, personne: "admin-B-fictif" }); break;
    case "deconnexion": definirConfigurationAppel(null); definirPersonneConfirmee(null); break;
  }
  finir({ ok: true, result: { fictif: true } });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect((appel.mock.calls[0][0] as ParametresAppelOutil).requete).toEqual({ tool: "m6_lire_pertes_alertes_wct_appareil",
    args: { wct_id: "WCT-A-FICTIF", decalage: 0, limite: 8 } });
});
test("personne A→B→A avec rôle égal : la capture originale reste fermée", async () => {
  let finir!: (v: unknown) => void; appel.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = lectures().chargerWcts();
  definirPersonneConfirmee({ ...personne, personne: "admin-B-fictif" }); definirPersonneConfirmee(personne);
  finir({ ok: true, result: { fictif: true } });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
test("un rôle actuel employee, seller ou non confirmé n'émet jamais", async () => {
  for (const role of ["employee", "seller", undefined]) {
    definirPersonneConfirmee({ ...personne, role }); expect(await lectures().chargerWcts()).toBeNull();
  }
  expect(appel).not.toHaveBeenCalled();
});
test("une confirmation identique conserve la garde et le refus serveur réel", async () => {
  let finir!: (v: unknown) => void; appel.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = lectures().chargerWcts(); definirConfigurationAppel({ ...config }); definirPersonneConfirmee({ ...personne });
  finir({ ok: true, result: { ok: true, resultat: { accepte: false, verdict: { code: "REJ-FICTIF", detail: "Source fictive inconnue" } } } });
  expect(await lecture).toEqual({ source: "refus", verdict: { code: "REJ-FICTIF", detail: "Source fictive inconnue" } });
});
