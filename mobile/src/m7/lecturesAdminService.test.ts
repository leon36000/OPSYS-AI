import { creerChargeurLecturesMarketing } from "./lecturesAdminService";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

const FICTIF = true;
const session = { urlBase: "https://gateway.example.test", jeton: "jeton-fictif", appareilId: "appareil-fictif", personne: "admin.fictif" };
const date = "2026-10-07T19:00:00Z";
const vide = { ok: true, resultat: { total: 0, demandes: [], reste: 0 } };
function banc(appeler: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>) {
  let courante = true;
  const mock = jest.fn(appeler);
  const chargeur = creerChargeurLecturesMarketing({ capturerSession: () => ({ session, courante: () => courante }), appeler: mock, fetchImpl: jest.fn(), maintenant: () => date });
  return { chargeur, mock, retirer: () => { courante = false; } };
}

test("deux lectures exactes indépendantes, aucune clé de mutation ni autorité client", async () => {
  expect(FICTIF).toBe(true);
  const h = banc(async p => ({ ok: true, result: p.requete.tool === "m7_lister_demandes_avis" ? vide : { ok: true, resultat: [] } }));
  expect(await h.chargeur.chargerFile()).toEqual({ source: "serveur", valeur: [], misAJourLe: date });
  expect(await h.chargeur.chargerDemandesAvis()).toEqual({ source: "serveur", valeur: { total: 0, demandes: [], reste: 0 }, misAJourLe: date });
  expect(h.mock.mock.calls.map(([p]) => p.requete)).toEqual([{ tool: "m7_lister_file_approbation", args: {} }, { tool: "m7_lister_demandes_avis", args: { limite: 8 } }]);
  expect(h.mock.mock.calls.every(([p]) => p.jeton === session.jeton)).toBe(true);
});

test("retrait avant réseau et pendant réponse, même personne et jeton, écarte les données", async () => {
  const avant = banc(async () => ({ ok: true, result: vide })); avant.retirer();
  expect(await avant.chargeur.chargerDemandesAvis()).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(avant.mock).not.toHaveBeenCalled();
  let resoudre!: (r: ResultatAppelOutil) => void;
  const apres = banc(() => new Promise(r => { resoudre = r; }));
  const pending = apres.chargeur.chargerDemandesAvis(); apres.retirer(); resoudre({ ok: true, result: vide });
  expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});

test("refus natif, réponse tronquée et transport ne deviennent ni vide ni cache", async () => {
  const refus = banc(async () => ({ ok: true, result: { ok: true, resultat: { accepte: false, verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "fictif" } } } }));
  expect(await refus.chargeur.chargerDemandesAvis()).toMatchObject({ source: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" } });
  const tronquee = banc(async () => ({ ok: true, result: { ok: true, tronque: true, apercu: "fictif" } }));
  expect(await tronquee.chargeur.chargerFile()).toMatchObject({ source: "aucune", raison: { code: "reponse_tronquee" } });
  const panne = banc(async () => { throw new Error("fictif"); });
  expect(await panne.chargeur.chargerDemandesAvis()).toMatchObject({ source: "aucune", raison: { code: "lecture_indisponible" } });
});

test("sans session il n'y a ni lecture inventée ni réseau", async () => {
  const appeler = jest.fn();
  const h = creerChargeurLecturesMarketing({ capturerSession: () => ({ session: null, courante: () => false }), appeler, fetchImpl: jest.fn(), maintenant: () => date });
  expect(await h.chargerFile()).toBeNull(); expect(await h.chargerDemandesAvis()).toBeNull(); expect(appeler).not.toHaveBeenCalled();
});
