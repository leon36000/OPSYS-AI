import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { Bouton, BoutonSecondaire, Ligne } from "../admin/composants";
import { lirePageDispatch } from "../m4/paginationDispatch";
import { lireMeteoIntervention } from "../m4/meteoIntervention";
import { lireRetardsIncidents } from "../m4/retardsIncidents";
import { pageDispatchFictive, pageSuivanteFictive, meteoInterventionFictive, retardsIncidentsFictifs, varianteFictive } from "../m4/fixturesDispatch";
import { lirePreparation } from "../m4/dispatch";
import { reponse } from "../admin/donneesDeTest";
import fr from "../i18n/locales/admin.fr-CA";
import en from "../i18n/locales/admin.en-CA";
let mockEpoch = 0, mockConnected = true;
let mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
const mockPage = jest.fn(), mockDigest = jest.fn(), mockPreparation = jest.fn(), mockMeteo = jest.fn(), mockRetards = jest.fn(), mockConnecter = jest.fn();
jest.mock("expo-router", () => ({ useFocusEffect: (f: () => void | (() => void)) => require("react").useEffect(f, [f]) }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, p?: unknown) => k + (p ? JSON.stringify(p) : "") }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useEtatIdentite: () => mockIdentite }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => { const e = mockEpoch;
  return { session: mockIdentite.role === "admin" ? { personne: "admin-fictif" } : null,
    courante: () => e === mockEpoch && mockIdentite.role === "admin" }; } }), { virtual: true });
jest.mock("@/admin/dispatchService", () => ({ chargerPageDispatch: (...a: unknown[]) => mockPage(...a),
  chargerDigestDispatch: () => mockDigest(), chargerPreparationDispatch: (id: string) => mockPreparation(id),
  chargerMeteoDispatch: (...a: unknown[]) => mockMeteo(...a), chargerRetardsDispatch: () => mockRetards(),
  actualiserConnectiviteDispatch: (v: boolean) => mockConnecter(v) }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/chantiers", () => jest.requireActual("./chantiers"), { virtual: true });
jest.mock("@/ecrans/dispatchCourant", () => jest.requireActual("./dispatchCourant"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
jest.mock("@/m4/dispatch", () => jest.requireActual("../m4/dispatch"), { virtual: true });
const Ecran = require("../../app/(admin)/chantiers").default;
const serveur = <T,>(valeur: T) => ({ source: "serveur", valeur, misAJourLe: "2026-10-08T05:00:00Z" });
const aucune = { source: "aucune", raison: { code: "fictif_absent", detail: "" } };
const page = lirePageDispatch(pageDispatchFictive, { statut: "planifiee", curseur: null, taille_page: 8 })!;
const suite = lirePageDispatch(pageSuivanteFictive, { statut: "planifiee", curseur: page.page.curseur_suivant, taille_page: 8 })!;
let arbre: ReactTestRenderer | undefined;
beforeEach(() => {
  jest.clearAllMocks(); mockEpoch++; mockConnected = true; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
  mockPage.mockImplementation(async (s: string, c?: string) => s === "planifiee" ? serveur(c ? suite : page) : aucune);
  mockDigest.mockResolvedValue(aucune); mockPreparation.mockResolvedValue(aucune); mockMeteo.mockResolvedValue(aucune);
  mockRetards.mockResolvedValue(serveur(lireRetardsIncidents(retardsIncidentsFictifs, retardsIncidentsFictifs.reference)!));
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
});
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
const texte = () => JSON.stringify(arbre!.toJSON());
const bouton = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === cle)!;
async function monter() { await act(async () => { arbre = create(<Ecran />); }); }

test("page suivante remplace les huit lignes et garde total/reste/source, jamais un snapshot", async () => {
  await monter(); expect(mockPage).toHaveBeenCalledTimes(7); expect(mockConnecter).toHaveBeenCalledWith(true);
  expect(texte()).toContain(page.interventions[0].leadId); expect(texte()).toContain("admin.dispatch.page.courante");
  await act(async () => bouton("admin.dispatch.suivante").props.onPress());
  expect(mockPage).toHaveBeenLastCalledWith("planifiee", page.page.curseur_suivant);
  expect(texte()).not.toContain(page.interventions[0].leadId); expect(texte()).toContain(suite.interventions[0].leadId);
  expect(arbre!.root.findAllByType(Ligne).map(l => l.props.m)).toContainEqual({ cle: "admin.dispatch.page.resume", params: { affichees: 8, total: 36, reste: 20 } });
});
test("copie datée : page suivante désactivée et aucun âge ancien de retards présenté hors ligne", async () => {
  mockPage.mockImplementation(async (s: string) => s === "planifiee" ? { ...serveur(page), source: "cache", raisonHorsLigne: { code: "hors_ligne", detail: "" } } : aucune);
  mockConnected = false; mockRetards.mockResolvedValue({ source: "aucune", raison: { code: "hors_ligne", detail: "" } });
  await monter(); expect(bouton("admin.dispatch.suivante").props.desactive).toBe(true);
  expect(texte()).toContain("admin.commun.cache"); expect(texte()).not.toContain("admin.dispatch.retards.heures");
});
test("date météo vide transmise null, date impossible bloque le bouton", async () => {
  await monter(); await act(async () => bouton("admin.dispatch.lireMeteo").props.onPress());
  expect(mockMeteo).toHaveBeenCalledWith(page.interventions[0].interventionId, null);
  await act(async () => arbre!.root.findByType(TextInput).props.onChangeText("2026-02-30"));
  expect(bouton("admin.dispatch.lireMeteo").props.desactive).toBe(true); expect(texte()).toContain("admin.dispatch.dateInvalide");
});
test("météo tardive A→B→A n'est pas présentée pour la nouvelle demande", async () => {
  let finir!: (v: unknown) => void; mockMeteo.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); await act(async () => arbre!.root.findByType(TextInput).props.onChangeText("2026-10-06"));
  await act(async () => bouton("admin.dispatch.lireMeteo").props.onPress());
  await act(async () => arbre!.root.findByType(TextInput).props.onChangeText("2026-10-07"));
  await act(async () => arbre!.root.findByType(TextInput).props.onChangeText("2026-10-06"));
  const m = varianteFictive(meteoInterventionFictive); m.intervention_id = page.interventions[0].interventionId;
  m.creneaux[0].intervention_id = m.intervention_id; m.creneaux[0].prevision.reference = "meteo-obsolete-fictive";
  const lu = lireMeteoIntervention(m, { intervention_id: m.intervention_id, date: "2026-10-06" })!;
  await act(async () => finir(serveur(lu))); expect(texte()).not.toContain("meteo-obsolete-fictive");
});
test("une préparation tardive abandonnée lors d'un changement de page ne réapparaît pas", async () => {
  let finir!: (v: unknown) => void; mockPreparation.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); const preparer = arbre!.root.findAllByType(Bouton).find(b => b.props.texte === "admin.chantiers.preparer")!;
  await act(async () => preparer.props.onPress()); await act(async () => bouton("admin.dispatch.suivante").props.onPress());
  const raw = reponse("preparation_lead_v2").resultat.resultat; raw.intervention_id = page.interventions[0].interventionId;
  raw.volets.adresse.detail = "preparation-obsolete-fictive";
  await act(async () => finir(serveur(lirePreparation(raw)!)));
  await act(async () => bouton("admin.dispatch.recommencer").props.onPress());
  expect(texte()).not.toContain("preparation-obsolete-fictive");
});
test("retrait du rôle : données déjà affichées et réponse tardive masquées", async () => {
  let finir!: (v: unknown) => void; mockPage.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); mockEpoch++; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "employee" };
  await act(async () => arbre!.update(<Ecran />)); await act(async () => finir(serveur(page)));
  expect(texte()).toContain("admin.commun.sansSession"); expect(texte()).not.toContain(page.interventions[0].leadId);
  expect(mockPage).toHaveBeenCalledTimes(7);
});
test("locales du raccord : mêmes clés et variables en français et anglais", () => {
  function comparer(a: unknown, b: unknown) {
    if (typeof a === "string") { expect(typeof b).toBe("string"); expect(a.match(/{{[^}]+}}/g)?.sort() ?? []).toEqual((b as string).match(/{{[^}]+}}/g)?.sort() ?? []); return; }
    expect(Object.keys(a as object).sort()).toEqual(Object.keys(b as object).sort());
    for (const k of Object.keys(a as object)) comparer(Reflect.get(a as object, k), Reflect.get(b as object, k));
  }
  comparer(fr.dispatch, en.dispatch);
});
