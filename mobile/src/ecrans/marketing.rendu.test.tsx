import React from "react";
import { act, create } from "react-test-renderer";
import type { EtatMarketing } from "../m7/controle";
import type { LigneContenuM7 } from "../m7/contrat";
import type { ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "../admin/composants";
import { FIXTURES_LECTURES_ADMIN_M7 } from "../m7/fixturesLecturesAdmin";
import { lireFileApprobationM7, lireDemandesAvisM7 } from "../m7/lecturesAdmin";
import adminEnCA from "../i18n/locales/admin.en-CA";

let mockGeneration = 0;
let mockConnected = true;
let mockSession = { presente: true, role: "admin" };
let mockState: EtatMarketing;
const mockT = (k: string, p?: unknown) => {
  if (k.startsWith("admin.marketing.messages.")) {
    return Reflect.get(adminEnCA.marketing.messages, k.slice("admin.marketing.messages.".length)) ?? k;
  }
  return k + (p ? JSON.stringify(p) : "");
};
jest.mock("expo-router", () => ({ useFocusEffect: (callback: () => void | (() => void)) => { const React = require("react"); React.useEffect(callback, [callback]); } }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT, i18n: { language: "fr-CA" } }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => mockSession }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionLecture: () => {
  const generation = mockGeneration;
  return { session: mockSession.role === "admin" ? { personne: "nathan.fictif", jeton: "jeton-fictif" } : null,
    courante: () => generation === mockGeneration && mockSession.role === "admin" };
} }), { virtual: true });
jest.mock("@/m7/service", () => ({ controleMarketing: {
  etat: jest.fn(() => mockState), charger: jest.fn(async () => undefined), chargerSuite: jest.fn(async () => undefined),
  decider: jest.fn(async () => undefined), peutDecider: jest.fn(() => false), invalider: jest.fn(), actualiserConnectivite: jest.fn(),
} }), { virtual: true });
jest.mock("@/m7/lecturesAdminService", () => ({ chargerFileMarketing: jest.fn(), chargerDemandesAvisMarketing: jest.fn() }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const service = require("@/m7/lecturesAdminService");
const controle = require("@/m7/service").controleMarketing;
const Ecran = require("../../app/(admin)/marketing").default;
const serveur = <T,>(valeur: T) => ({ source: "serveur", valeur, misAJourLe: "2026-10-07T12:00:00Z" });
const captures = FIXTURES_LECTURES_ADMIN_M7.captures;
const fileNative = lireFileApprobationM7(captures.file_propose.enveloppe);
const avisNative = lireDemandesAvisM7(captures.avis.enveloppe);
let arbre: ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks(); mockGeneration = 0; mockConnected = true; mockSession = { presente: true, role: "admin" };
  controle.peutDecider.mockReturnValue(false);
  controle.decider.mockResolvedValue(undefined);
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  mockState = { statut: "pret", items: [], owner: false, message: null, suivant: null, reste: 0, intentions: [], sourceDate: "2026-10-07T12:00:00Z" };
  if (!fileNative.ok || !avisNative.ok) throw new Error("Captures natives illisibles");
  service.chargerFileMarketing.mockResolvedValue(serveur(fileNative.value));
  service.chargerDemandesAvisMarketing.mockResolvedValue(serveur(avisNative.value));
});
afterEach(async () => { if (arbre) await act(async () => { arbre.unmount(); }); });
const refresh = () => arbre.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === "admin.commun.rafraichir")!;

test("les trois objets sont distincts ; historique volatile et avis n'offrent aucune décision", async () => {
  expect(FIXTURES_LECTURES_ADMIN_M7.fictif).toBe(true);
  await act(async () => { arbre = create(<Ecran />); });
  const rendu = JSON.stringify(arbre.toJSON());
  expect(rendu).toContain("admin.marketing.contenus"); expect(rendu).toContain("admin.marketing.volatil");
  expect(rendu).toContain("admin.marketing.avisNote"); expect(rendu).toContain("admin.marketing.pagesCourantes");
  expect(controle.decider).not.toHaveBeenCalled(); expect(arbre.root.findAllByType(BoutonSecondaire)).toHaveLength(1);
});

test("rafraîchir écarte l'ancienne réponse historique tardive", async () => {
  let finir!: (v: unknown) => void;
  service.chargerFileMarketing.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => { refresh().props.onPress(); });
  if (!fileNative.ok) throw new Error("Fixture invalide");
  await act(async () => { finir(serveur([{ ...fileNative.value[0], title: "Ancienne réponse fictive à écarter" }])); });
  expect(JSON.stringify(arbre.toJSON())).not.toContain("Ancienne réponse fictive à écarter");
  expect(service.chargerFileMarketing).toHaveBeenCalledTimes(2);
});

test("refus ou panne d'une section ne masque pas les autres lectures", async () => {
  service.chargerFileMarketing.mockResolvedValue({ source: "refus", verdict: { code: "REJ-FICTIF", detail: "Refus historique fictif" } });
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("Refus historique fictif"); expect(JSON.stringify(arbre.toJSON())).toContain("admin.marketing.totalAvis");
  service.chargerFileMarketing.mockRejectedValueOnce(new Error("panne fictive"));
  await act(async () => { refresh().props.onPress(); });
  expect(JSON.stringify(arbre.toJSON())).toContain("lecture_indisponible"); expect(JSON.stringify(arbre.toJSON())).toContain("admin.marketing.totalAvis");
});

test("retrait du rôle à personne et jeton égaux masque les anciennes lectures", async () => {
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.marketing.totalAvis");
  mockGeneration++; mockSession = { presente: true, role: "employee" };
  await act(async () => { arbre.update(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).not.toContain("admin.marketing.totalAvis");
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.commun.sansSession");
  expect(controle.invalider).toHaveBeenCalled();
});

test("une intention inconnue conserve sa personne et son état sans proposer un nouvel effet", async () => {
  mockState = { ...mockState, intentions: [{ id: "intention-fictive", contenuId: "contenu-fictif", decision: "approuver", statut: "en_attente", personne: "nathan.fictif" }] };
  await act(async () => { arbre = create(<Ecran />); });
  const rendu = JSON.stringify(arbre.toJSON());
  expect(rendu).toContain("admin.marketing.attente"); expect(rendu).toContain("nathan.fictif"); expect(rendu).toContain("admin.marketing.etatsFile.en_attente");
  expect(controle.decider).not.toHaveBeenCalled();
});

test("hors ligne, les lectures historiques et avis ne déclenchent aucun réseau ; reconnexion les relit", async () => {
  mockConnected = false;
  await act(async () => { arbre = create(<Ecran />); });
  expect(service.chargerFileMarketing).not.toHaveBeenCalled();
  expect(service.chargerDemandesAvisMarketing).not.toHaveBeenCalled();
  expect(JSON.stringify(arbre.toJSON())).toContain("hors_ligne");
  mockConnected = true;
  await act(async () => { arbre.update(<Ecran />); });
  expect(service.chargerFileMarketing).toHaveBeenCalledTimes(1);
  expect(service.chargerDemandesAvisMarketing).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.marketing.totalAvis");
});

test("le bouton durable conserve le motif et ignore le rafraîchissement pendant la décision", async () => {
  const contenu: LigneContenuM7 = {
    contenu_id: "contenu-fictif", wct_id: "wct-fictif", plateforme: "instagram", revision: 1,
    approval_status: "PROPOSE", exporte: false, marque_source: null, fraicheur_marque: "preuve_absente",
    texte: "Contenu fictif conservé", origine_texte: "chantier", mots_clics: [], lien_utm: null,
    avertissements: [], decision: null,
    consentement: { recueilli_par: "nathan.fictif", recueilli_le: "2026-10-07T12:00:00Z", version_texte: "fictif-v1" },
  };
  // Le contrôleur réel est qualifié séparément ; ici le port autorise ce bouton de rendu.
  mockState = { ...mockState, owner: true, items: [contenu] };
  controle.peutDecider.mockReturnValue(true);
  let finir!: () => void;
  controle.decider.mockImplementationOnce(() => {
    mockState = { ...mockState, statut: "decision_en_cours" };
    return new Promise<void>(r => { finir = r; });
  });
  await act(async () => { arbre = create(<Ecran />); });
  const input = arbre.root.findByProps({ accessibilityLabel: "admin.marketing.motif contenu-fictif" });
  await act(async () => { input.props.onChangeText("Motif fictif saisi"); });
  const rejet = arbre.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === "admin.marketing.rejeter")!;
  await act(async () => { rejet.props.onPress(); });
  expect(controle.decider).toHaveBeenCalledWith("contenu-fictif", "rejeter", "Motif fictif saisi");
  const lectures = controle.charger.mock.calls.length;
  await act(async () => { refresh().props.onPress(); });
  expect(controle.charger).toHaveBeenCalledTimes(lectures);
  expect(service.chargerFileMarketing).toHaveBeenCalledTimes(1);
  await act(async () => { mockState = { ...mockState, statut: "decision_incertaine", owner: false }; finir(); });
  expect(controle.decider).toHaveBeenCalledTimes(1);
});

test("un message local utilise la langue de l'écran ; un texte serveur inconnu reste intact", async () => {
  mockState = { ...mockState, statut: "decision_incertaine", message: "Réponse de décision incertaine; l’état a été relu. La même intention reste en file.", codeMessage: "decisionIncertaine" };
  await act(async () => { arbre = create(<Ecran />); });
  let rendu = JSON.stringify(arbre.toJSON());
  expect(rendu).toContain(adminEnCA.marketing.messages.decisionIncertaine);
  expect(rendu).not.toContain("Réponse de décision incertaine");
  mockState = { ...mockState, message: "Explication serveur fictive originale", codeMessage: null };
  await act(async () => { arbre.update(<Ecran />); });
  rendu = JSON.stringify(arbre.toJSON());
  expect(rendu).toContain("Explication serveur fictive originale");
});
