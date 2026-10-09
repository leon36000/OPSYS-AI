import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { ActivityIndicator, TextInput } from "react-native";
import { BoutonSecondaire } from "../admin/composants";
import { FIXTURES_M1 } from "../m1/fixtures";
import { lireTransfertM1 } from "../m1/contrat";
import adminFr from "../i18n/locales/admin.fr-CA";
import adminEn from "../i18n/locales/admin.en-CA";
let mockEpoch = 0, mockConnected = true;
let mockSession = { presente: true, role: "admin" };
let mockParams: { transfert?: string | string[] } = {};
const mockDigest = jest.fn(), mockFiche = jest.fn(), mockConnecter = jest.fn();
const mockT = (k: string, p?: unknown) => k + (p ? JSON.stringify(p) : "");
jest.mock("expo-router", () => ({ useLocalSearchParams: () => mockParams, Link: "Link",
  useFocusEffect: (f: () => void | (() => void)) => require("react").useEffect(f, [f]) }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => mockSession }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const e = mockEpoch;
  return { session: mockSession.role === "admin" ? { personne: "admin-fictif" } : null,
    courante: () => e === mockEpoch && mockSession.role === "admin" };
} }), { virtual: true });
jest.mock("@/m1/service", () => ({ chargerDigestReception: (d: string) => mockDigest(d),
  chargerTransfertReception: (id: string) => mockFiche(id), actualiserConnectiviteTransferts: (v: boolean) => mockConnecter(v) }), { virtual: true });
jest.mock("@/m1/contrat", () => jest.requireActual("../m1/contrat"), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const Ecran = require("../../app/(admin)/reception").default;
const f = FIXTURES_M1.reponses;
const lu = lireTransfertM1(f.plainte_ouverte.enveloppe);
if (!lu.ok) throw new Error("Capture native illisible");
const natif = lu.value;
const serveur = <T,>(valeur: T) => ({ source: "serveur" as const, valeur, misAJourLe: "2026-10-07T12:00:00Z" });
let arbre: ReactTestRenderer | undefined;
beforeEach(() => {
  jest.clearAllMocks(); mockEpoch++; mockConnected = true; mockSession = { presente: true, role: "admin" };
  mockParams = { transfert: natif.transfert_id }; mockDigest.mockResolvedValue(serveur("Digest natif fictif"));
  mockFiche.mockResolvedValue(serveur(natif)); Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
});
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
const texte = () => JSON.stringify(arbre!.toJSON());
const boutonDigest = () => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === "admin.commun.rafraichir")!;
const lecturesSeulement = () => expect(arbre!.root.findAllByType(BoutonSecondaire).map(b => b.props.texte).sort())
  .toEqual(["admin.commun.rafraichir", "admin.rappelsM1.lire"]);
test("fiche serveur choisie depuis À voir : mêmes références, résumé/origine, contacts, omissions et aucune mutation", async () => {
  await act(async () => { arbre = create(<Ecran />); });
  expect(mockFiche).toHaveBeenCalledWith(natif.transfert_id); expect(mockConnecter).toHaveBeenCalledWith(true);
  for (const s of [natif.transfert_id, natif.conversation_id, natif.resume]) expect(texte()).toContain(s);
  expect(texte()).toContain("admin.reception.serveurSeul"); expect(texte()).toContain("admin.reception.note");
  expect(texte()).toContain('\\"origine\\":\\"code\\"'); expect(texte()).toContain('\\"nombre\\":0');
  for (const m of [...natif.messages_couverts, ...natif.messages_suivants]) expect(texte()).toContain(m.signal_id);
  expect(boutonDigest()).toBeDefined(); lecturesSeulement();
});
test("digest au cache daté et fiche hors ligne masquée, même si une ancienne valeur existe", async () => {
  await act(async () => { arbre = create(<Ecran />); });
  mockConnected = false;
  mockDigest.mockResolvedValue({ source: "cache", valeur: "Digest gardé fictif", misAJourLe: "2026-10-07T12:00:00Z",
    raisonHorsLigne: { code: "hors_ligne", detail: "" } });
  await act(async () => arbre!.update(<Ecran />));
  expect(texte()).toContain("admin.commun.cache"); expect(texte()).toContain("Digest gardé fictif");
  expect(texte()).toContain("admin.reception.connexion"); expect(texte()).not.toContain(natif.conversation_id);
  expect(arbre!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
});
test("date invalide ou paramètre non canonique n'ouvre aucune fiche arbitraire", async () => {
  mockParams = { transfert: "conversation-fictive" };
  await act(async () => { arbre = create(<Ecran />); });
  expect(mockFiche).not.toHaveBeenCalled(); expect(texte()).toContain("admin.reception.referenceInvalide");
  await act(async () => arbre!.root.findByType(TextInput).props.onChangeText("2026-02-30"));
  expect(texte()).toContain("admin.reception.dateInvalide");
  expect(boutonDigest().props.desactive).toBe(true);
});
test("absence de sélection renvoie aux attentes existantes sans nouvelle liste ni fiche inventée", async () => {
  mockParams = {};
  await act(async () => { arbre = create(<Ecran />); });
  expect(mockFiche).not.toHaveBeenCalled(); expect(texte()).toContain("admin.reception.selection");
  expect(texte()).toContain("/admin");
});
test("révocation à personne identique masque aussi une fiche qui arrive tard", async () => {
  let finir!: (v: unknown) => void;
  mockFiche.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await act(async () => { arbre = create(<Ecran />); });
  mockEpoch++; mockSession = { presente: true, role: "employee" };
  await act(async () => arbre!.update(<Ecran />));
  await act(async () => finir(serveur(natif)));
  expect(texte()).not.toContain(natif.conversation_id); expect(texte()).toContain("admin.commun.sansSession");
  expect(mockFiche).toHaveBeenCalledTimes(1);
});
test("STOP et brouillon non envoyé restent des faits, sans bouton d'envoi ou de clôture", async () => {
  const stop = lireTransfertM1(f.plainte_stop.enveloppe);
  if (!stop.ok) throw new Error("STOP natif illisible");
  mockParams = { transfert: stop.value.transfert_id }; mockFiche.mockResolvedValue(serveur(stop.value));
  await act(async () => { arbre = create(<Ecran />); });
  expect(texte()).toContain("admin.reception.stop"); expect(texte()).toContain("admin.reception.nonEnvoye");
  expect(boutonDigest()).toBeDefined(); lecturesSeulement();
});
test("catalogues bilingues : mêmes clés et variables", () => {
  function comparer(a: unknown, b: unknown) {
    if (typeof a === "string") { expect(typeof b).toBe("string");
      expect(a.match(/{{[^}]+}}/g)?.sort() ?? []).toEqual((b as string).match(/{{[^}]+}}/g)?.sort() ?? []); return; }
    expect(Object.keys(a as object).sort()).toEqual(Object.keys(b as object).sort());
    for (const k of Object.keys(a as object)) comparer(Reflect.get(a as object, k), Reflect.get(b as object, k));
  }
  comparer(adminFr.reception, adminEn.reception);
});
