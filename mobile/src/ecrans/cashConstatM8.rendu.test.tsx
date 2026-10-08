import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire, Ligne } from "../admin/composants";
import { lireVueExecutive } from "../m8/vueExecutive";
import fixture from "../m8/fixturesCashLibre.json";
import { reponse } from "../admin/donneesDeTest";
import fr from "../i18n/locales/admin.fr-CA";
import en from "../i18n/locales/admin.en-CA";
let mockEpoch = 0, mockConnected = true;
let mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
const mockVue = jest.fn(), mockConnecter = jest.fn(), mockTres = jest.fn(), mockPrev = jest.fn(), mockEch = jest.fn(), mockSuite = jest.fn();
jest.mock("expo-router", () => ({ useFocusEffect: (f: () => void | (() => void)) => require("react").useEffect(f, [f]) }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ i18n: { language: "fr-CA" }, t: (k: string, p?: unknown) => k + (p ? JSON.stringify(p) : "") }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useEtatIdentite: () => mockIdentite }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => { const e = mockEpoch;
  return { session: mockIdentite.role === "admin" ? { personne: "admin-fictif" } : null, courante: () => e === mockEpoch && mockIdentite.role === "admin" }; } }), { virtual: true });
jest.mock("@/admin/service", () => ({ chargerVueExecutive: () => mockVue(), actualiserConnectiviteChiffres: (v: boolean) => mockConnecter(v),
  chargerTresorerie: () => mockTres(), chargerPrevision: () => mockPrev(), chargerEcheances: () => mockEch(), chargerSuitePrevision: (v: unknown) => mockSuite(v) }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/admin/vuesChiffres", () => jest.requireActual("../admin/vuesChiffres"), { virtual: true });
jest.mock("@/ecrans/chiffres", () => jest.requireActual("./chiffres"), { virtual: true });
jest.mock("@/ecrans/vueExecutive", () => jest.requireActual("./vueExecutive"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const Ecran = require("../../app/(admin)/chiffres").default;
const aucun = { source: "aucune", raison: { code: "fictif_absent", detail: "" } };
function vueCash(cash: unknown) { const brut = reponse("vue_executive_vide").resultat; brut.cash_libre = JSON.parse(JSON.stringify(cash));
  const vue = lireVueExecutive(brut); if (vue === null) throw new Error("fixture cash fictive illisible"); return vue; }
const serveur = (cash: unknown) => ({ source: "serveur", valeur: vueCash(cash), misAJourLe: "2026-09-30T16:00:00Z" });
let arbre: ReactTestRenderer | undefined;
beforeEach(() => { jest.clearAllMocks(); mockEpoch++; mockConnected = true; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
  mockVue.mockResolvedValue(serveur(fixture.calcule)); mockTres.mockResolvedValue(aucun); mockPrev.mockResolvedValue(aucun); mockEch.mockResolvedValue(aucun);
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true); });
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
const texte = () => JSON.stringify(arbre!.toJSON());
const messages = () => arbre!.root.findAllByType(Ligne).map(l => l.props.m);
async function monter() { await act(async () => { arbre = create(<Ecran />); }); }
test("constat calculé : provenance, âge, montant, composantes et mention, un seul geste de lecture", async () => {
  await monter(); expect(mockConnecter).toHaveBeenCalledWith(true);
  expect(messages()).toContainEqual({ cle: "admin.cashConstatM8.age", params: { jours: 1, jour: "2026-09-30" } });
  expect(messages().some(m => m.cle === "admin.cashConstatM8.montant")).toBe(true);
  expect(texte()).toContain(fixture.calcule.constat.mention); expect(texte()).toContain("admin.chiffres.composantes.solde");
  expect(arbre!.root.findAllByType(BoutonSecondaire)).toHaveLength(1); expect(mockSuite).not.toHaveBeenCalled();
});
test("NON_CALCULABLE : repère déclaré, manques et planchers, jamais un cash libre disponible", async () => {
  mockVue.mockResolvedValue(serveur(fixture.planchers)); await monter();
  expect(messages().some(m => m.cle === "admin.cashConstatM8.auPlus")).toBe(true);
  expect(messages().some(m => m.cle === "admin.cashConstatM8.montant")).toBe(false);
  expect(texte()).toContain("admin.cashConstatM8.NON_CALCULABLE"); expect(texte()).toContain("admin.chiffres.composante.plancher");
});
test("omissions natives comptées et âge futur inconnu visibles", async () => {
  mockVue.mockResolvedValue(serveur(fixture.reduit)); await monter();
  expect(messages()).toContainEqual({ cle: "admin.cashConstatM8.composantesOmises", params: { nombre: 7 } });
  mockVue.mockResolvedValue(serveur(fixture.dateFuture));
  await act(async () => arbre!.root.findAllByType(BoutonSecondaire)[0].props.onPress());
  expect(messages().some(m => m.cle === "admin.cashConstatM8.ageInconnu")).toBe(true);
});
test("copie datée garde son âge d'origine et ne prétend pas une mesure courante", async () => {
  mockConnected = false; mockVue.mockResolvedValue({ ...serveur(fixture.calcule), source: "cache", raisonHorsLigne: { code: "hors_ligne", detail: "" } });
  await monter(); expect(texte()).toContain("admin.commun.cache");
  expect(messages()).toContainEqual({ cle: "admin.cashConstatM8.age", params: { jours: 1, jour: "2026-09-30" } });
  expect(mockConnecter).toHaveBeenCalledWith(false);
});
test("retrait du rôle : données affichées et réponse tardive masquées, pas de nouvelles lectures", async () => {
  let finir!: (v: unknown) => void; mockVue.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); mockEpoch++; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "seller" };
  await act(async () => arbre!.update(<Ecran />)); await act(async () => finir(serveur(fixture.calcule)));
  expect(texte()).toContain("admin.commun.sansSession"); expect(texte()).not.toContain(fixture.calcule.constat.mention);
  expect(mockVue).toHaveBeenCalledTimes(1);
});
test("rafraîchissement supplante une réponse ancienne et exception ferme la section", async () => {
  let finir!: (v: unknown) => void; mockVue.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); mockVue.mockRejectedValueOnce(new Error("panne SQLite fictive"));
  await act(async () => arbre!.root.findAllByType(BoutonSecondaire)[0].props.onPress());
  await act(async () => finir(serveur(fixture.calcule)));
  expect(texte()).not.toContain(fixture.calcule.constat.mention); expect(texte()).toContain("lecture_indisponible");
});
test("locales financières : mêmes clés et variables", () => {
  const verifier = (a: unknown, b: unknown) => { if (typeof a === "string") {
    expect(typeof b).toBe("string"); expect(a.match(/{{[^}]+}}/g)?.sort() ?? []).toEqual((b as string).match(/{{[^}]+}}/g)?.sort() ?? []); return; }
    expect(Object.keys(a as object).sort()).toEqual(Object.keys(b as object).sort());
    for (const k of Object.keys(a as object)) verifier(Reflect.get(a as object, k), Reflect.get(b as object, k)); };
  verifier(fr.cashConstatM8, en.cashConstatM8);
});
