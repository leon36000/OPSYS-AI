import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { ActivityIndicator, Text } from "react-native";
import { BoutonSecondaire } from "../admin/composants";
import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import type { ReapprovisionnementM6, ArticleReapprovisionnementM6 } from "../m6/reapprovisionnement";
import { presenterReapprovisionnementM6 } from "./reapprovisionnementM6";
import frCA from "../i18n/locales/fr-CA";
import enCA from "../i18n/locales/en-CA";
import { disponibiliteFictive, digestFictif } from "../m6/fixturesStock";

let mockConnected = true, mockBlur: (() => void) | undefined;
const mockLire = jest.fn(), mockReseau = jest.fn();
jest.mock("expo-router", () => ({ useFocusEffect: (callback: () => void | (() => void)) => {
  const React = require("react"); React.useEffect(() => { const fermeture = callback();
    if (fermeture) mockBlur = fermeture; return fermeture; }, [callback]);
} }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (cle: string, args?: unknown) => cle + (args ? JSON.stringify(args) : ""), i18n: { language: "fr-CA" } }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => "session-fictive" }));
jest.mock("../admin/reapprovisionnement", () => ({ chargerReapprovisionnementM6: (...args: unknown[]) => mockLire(...args),
  actualiserConnectiviteReapprovisionnementM6: (v: boolean) => mockReseau(v) }));
jest.mock("@/admin/ReapprovisionnementM6", () => jest.requireActual("../admin/ReapprovisionnementM6"), { virtual: true });
jest.mock("@/admin/PertesAlertesM6", () => ({ PertesAlertesM6: () => null }), { virtual: true });
jest.mock("@/admin/service", () => ({ chargerDisponibiliteM6: jest.fn(), chargerDigestM6: jest.fn() }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/stock", () => jest.requireActual("./stock"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
jest.mock("@/protocole/configuration", () => jest.requireActual("../protocole/configuration"), { virtual: true });
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => "session-fictive" }), { virtual: true });
const EcranStock = require("../../app/(admin)/stock").default;
const ComposantReapprovisionnement = require("../admin/ReapprovisionnementM6").ReapprovisionnementM6;
const serviceGlobal = require("@/admin/service") as Record<string, jest.Mock>;
const config = { urlBase: "http://127.0.0.1:0", jeton: "jeton-stock-fictif", appareilId: "appareil-stock-fictif" };
const identite = { ...config, personne: "admin-stock-fictif", role: "admin" };

// Fixtures FICTIVES de rendu et composition, sans parsing, HTTP ni stock physique qualifié.
function article(id = "ARTICLE-FICTIF", rang = 0): ArticleReapprovisionnementM6 {
  return { materiau_id: id, statut: "stock_bas", chiffres: { stock_theorique: "12", hors_main: "2", en_main: "10", reserve: "3", disponible: "7" },
    seuil_reapprovisionnement: "8", quantite_cible: "15", quantite_a_commander: "8", stock_negatif: false, code_configuration: null,
    unite: null, unite_dernier_constat: "pi", dernier_constat: { reference: { registre: "besoins_commande", rang, empreinte_snapshot: "a".repeat(64) },
      type_entree: "besoin_commande", evenement_declencheur: "WCT-FICTIF", horodatage: "2026-10-08T05:00:00-04:00", chantier_id: "CHANTIER-FICTIF",
      reference_bus: { type: "m4.travaux_termines", evenement_id: "WCT-FICTIF" } } };
}
function page(articles = [article()], total = articles.length, decalage = 0): ReapprovisionnementM6 {
  const affichees = articles.length, reste = Math.max(0, total - decalage - affichees);
  return { articles, pagination: { decalage, limite: 8, affichees, total, reste, suivant: reste ? decalage + affichees : null, courante: true },
    source_configuration: { fichier: "departments/m06-material-control/department.yaml", chemin: "configuration.reapprovisionnement.articles", sha256: "b".repeat(64) },
    sources_registres: (["besoins_commande", "principal", "reservations", "emplacements"] as const).map(registre => ({ registre, lignes: 3, empreinte_snapshot: "c".repeat(64) })),
    source_publications: { evenements: { type: "m4.travaux_termines", lignes: 1, empreinte_snapshot: "d".repeat(64) },
      recus_m6: { registre: "wct_recus", lignes: 0, empreinte_snapshot: "e".repeat(64) } },
    couverture: { articles: "articles_deja_constates", stock: "theorique_disponible", unites: "homogeneite_non_confirmee", horodatage: "dernier_constat_sans_date_calcul", plafond_lignes: 10000 },
    borne_caracteres: 5400, taille_caracteres: 2200 };
}
const serveur = (valeur: ReapprovisionnementM6) => ({ source: "serveur", valeur, misAJourLe: "2026-10-08T12:00:00Z" });
let arbre: ReactTestRenderer | undefined;
const texte = () => JSON.stringify(arbre!.toJSON());
const bouton = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === `admin.reapprovisionnement.${cle}`)!;
const presser = async (cle = "lire") => { await act(async () => { bouton(cle).props.onPress(); }); };
const monter = async () => { await act(async () => { arbre = create(<EcranStock />); }); };
beforeEach(() => {
  jest.clearAllMocks(); mockConnected = true; mockBlur = undefined;
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  definirConfigurationAppel(config); definirPersonneConfirmee(identite);
  serviceGlobal.chargerDisponibiliteM6.mockResolvedValue({ source: "serveur", valeur: disponibiliteFictive, misAJourLe: "2026-10-08T12:00:00Z" });
  serviceGlobal.chargerDigestM6.mockResolvedValue({ source: "serveur", valeur: digestFictif, misAJourLe: "2026-10-08T12:00:00Z" });
  mockLire.mockResolvedValue(serveur(page()));
});
afterEach(async () => {
  if (arbre) await act(async () => arbre!.unmount()); arbre = undefined;
  definirConfigurationAppel(null); definirPersonneConfirmee(null);
});

test("Stock compose le vrai composant, lecture explicite et quantité source sans unité empruntée", async () => {
  await monter(); expect(mockLire).not.toHaveBeenCalled(); expect(bouton("lire").props.desactive).toBe(false);
  await presser(); expect(mockLire).toHaveBeenCalledWith(0); expect(texte()).toContain("ARTICLE-FICTIF");
  expect(arbre!.root.findAllByType(Text).map(n => n.props.children)).toContain('admin.reapprovisionnement.proposition{"valeur":"8"}');
  expect(texte()).toContain("admin.reapprovisionnement.uniteConstatDistincte"); expect(texte()).toContain("admin.reapprovisionnement.aucunAchat");
  expect(serviceGlobal.chargerDigestM6).toHaveBeenCalledTimes(1);
});
test("page suivante remplace la première sans recomposer les articles", async () => {
  mockLire.mockResolvedValueOnce(serveur(page([article()], 2))); await monter(); await presser();
  mockLire.mockResolvedValueOnce(serveur(page([article("ARTICLE-SUIVANT-FICTIF", 1)], 2, 1)));
  await presser("suite"); expect(mockLire).toHaveBeenLastCalledWith(1);
  expect(texte()).toContain("ARTICLE-SUIVANT-FICTIF"); expect(texte()).not.toContain("ARTICLE-FICTIF");
});
test("retrait du rôle masque résultat et ferme un ancien callback", async () => {
  await monter(); await presser(); const ancien = bouton("lire").props.onPress;
  definirPersonneConfirmee({ ...identite, role: "employee" }); await act(async () => arbre!.update(<EcranStock />));
  expect(texte()).not.toContain("ARTICLE-FICTIF"); expect(bouton("lire").props.desactive).toBe(true);
  await act(async () => ancien()); expect(mockLire).toHaveBeenCalledTimes(1);
});
test("nouvelle personne ferme le callback même si son rôle est admin", async () => {
  await monter(); const ancien = bouton("lire").props.onPress;
  definirPersonneConfirmee({ ...identite, personne: "autre-admin-fictif" }); await act(async () => arbre!.update(<EcranStock />));
  await act(async () => ancien()); expect(mockLire).not.toHaveBeenCalled();
});
test("réseau A→B→A ferme le résultat encore en vol", async () => {
  let finir!: (v: unknown) => void; mockLire.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); await presser(); expect(arbre!.root.findAllByType(ActivityIndicator).length).toBeGreaterThan(0);
  mockConnected = false; await act(async () => arbre!.update(<EcranStock />)); expect(texte()).toContain("admin.reapprovisionnement.horsLigne");
  mockConnected = true; await act(async () => arbre!.update(<EcranStock />));
  await act(async () => finir(serveur(page()))); expect(texte()).not.toContain("ARTICLE-FICTIF");
  expect(mockReseau).toHaveBeenCalledWith(false);
});
test("refus puis panne ne reconstitue pas un ancien article", async () => {
  await monter(); await presser();
  mockLire.mockResolvedValueOnce({ source: "refus", verdict: { code: "REJ-FICTIF", detail: "Refus fictif" } });
  await presser(); expect(texte()).toContain("Refus fictif"); expect(texte()).not.toContain("ARTICLE-FICTIF");
  mockLire.mockRejectedValueOnce(new Error("Panne fictive")); await presser();
  expect(texte()).not.toContain("ARTICLE-FICTIF"); expect(texte()).not.toContain("admin.reapprovisionnement.aucunArticleConstate");
});
test("une copie cache inattendue ne devient pas une source courante", async () => {
  mockLire.mockResolvedValueOnce({ source: "cache", valeur: page(), misAJourLe: "2026-10-08T12:00:00Z" });
  await monter(); await presser(); expect(texte()).not.toContain("ARTICLE-FICTIF");
});
test("callback de page fermé après retour au début", async () => {
  mockLire.mockResolvedValueOnce(serveur(page([article()], 2))); await monter(); await presser();
  const ancien = bouton("suite").props.onPress; await presser(); await act(async () => ancien());
  expect(mockLire).toHaveBeenCalledTimes(2);
});
test("perte de focus ferme la réponse en vol et son callback", async () => {
  let finir!: (v: unknown) => void; mockLire.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await act(async () => { arbre = create(<ComposantReapprovisionnement connected />); });
  await presser(); const ancien = bouton("lire").props.onPress;
  expect(mockBlur).toBeDefined(); await act(async () => mockBlur!());
  await act(async () => finir(serveur(page()))); await act(async () => ancien());
  expect(texte()).not.toContain("ARTICLE-FICTIF"); expect(mockLire).toHaveBeenCalledTimes(1);
});
test("nouvelle lecture remplace un ancien stock bas par le verdict courant suffisant", async () => {
  await monter(); await presser();
  const suffisant = { ...article(), statut: "stock_suffisant" as const, quantite_a_commander: null,
    chiffres: { stock_theorique: "22", hors_main: "2", en_main: "20", reserve: "3", disponible: "17" } };
  mockLire.mockResolvedValueOnce(serveur(page([suffisant]))); await presser();
  expect(texte()).toContain("admin.reapprovisionnement.statuts.stock_suffisant");
  expect(texte()).not.toContain("admin.reapprovisionnement.statuts.stock_bas");
  expect(arbre!.root.findAllByType(Text).map(n => n.props.children)).not.toContain('admin.reapprovisionnement.proposition{"valeur":"8"}');
});
test("corpus vide et page au-delà du corpus restent distincts", () => {
  expect(JSON.stringify(presenterReapprovisionnementM6(page([], 0)))).toContain("admin.reapprovisionnement.aucunArticleConstate");
  const auDela = JSON.stringify(presenterReapprovisionnementM6(page([], 3, 4)));
  expect(auDela).toContain("admin.reapprovisionnement.aucunArticlePage"); expect(auDela).not.toContain("admin.reapprovisionnement.aucunArticleConstate");
});
test("seuil absent, configuration invalide et stock négatif ne deviennent pas zéro commande", () => {
  const absent = { ...article(), statut: "seuil_absent" as const, seuil_reapprovisionnement: null, quantite_cible: null, quantite_a_commander: null };
  const invalide = { ...absent, statut: "configuration_invalide" as const, code_configuration: "REJ-REAPPRO-ARTICLE-INVALIDE" as const };
  const negatif = { ...article(), stock_negatif: true, quantite_a_commander: null, chiffres: { ...article().chiffres, en_main: "-2", disponible: "-5" } };
  expect(JSON.stringify(presenterReapprovisionnementM6(page([absent])))).toContain("admin.reapprovisionnement.statuts.seuil_absent");
  expect(JSON.stringify(presenterReapprovisionnementM6(page([invalide])))).toContain("REJ-REAPPRO-ARTICLE-INVALIDE");
  expect(JSON.stringify(presenterReapprovisionnementM6(page([negatif])))).toContain("admin.reapprovisionnement.propositionStockNegatif");
});
test("date et unité du constat ne deviennent pas celles du calcul ou du stock", () => {
  const rendu = JSON.stringify(presenterReapprovisionnementM6(page()));
  expect(rendu).toContain("2026-10-08T05:00:00-04:00"); expect(rendu).toContain("admin.reapprovisionnement.dateDistincte");
  expect(rendu).toContain("admin.reapprovisionnement.uniteConstatDistincte");
  expect(rendu).toContain("admin.reapprovisionnement.empreintesSnapshots");
});
test("catalogues bilingues : mêmes clés, variables et quatre états sans texte absent", () => {
  const flatten = (v: object, prefixe = ""): Record<string, string> => Object.fromEntries(Object.entries(v).flatMap(([k, item]) =>
    typeof item === "string" ? [[prefixe + k, item]] : Object.entries(flatten(item, prefixe + k + "."))));
  const fr = flatten(frCA.admin.reapprovisionnement), en = flatten(enCA.admin.reapprovisionnement);
  expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
  for (const cle of Object.keys(fr)) {
    expect(fr[cle].length).toBeGreaterThan(0); expect(en[cle].length).toBeGreaterThan(0);
    expect((fr[cle].match(/\{\{[^}]+\}\}/g) ?? []).sort()).toEqual((en[cle].match(/\{\{[^}]+\}\}/g) ?? []).sort());
  }
  expect(Object.keys(frCA.admin.reapprovisionnement.statuts).sort()).toEqual(["configuration_invalide", "seuil_absent", "stock_bas", "stock_suffisant"]);
});
