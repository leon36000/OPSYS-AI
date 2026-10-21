import React from "react";
import { act, create } from "react-test-renderer";
import type { ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "../admin/composants";
import { lireCreances, lireAP, lireAttentes } from "../m5/comptes";
import { creances, ap, sansPO, attentes, JOUR } from "../m5/fixturesComptes";
jest.mock("expo-router", () => ({
  useFocusEffect: (callback: () => void | (() => void)) => {
    const React = require("react"); React.useEffect(callback, [callback]);
  },
}));
jest.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, p?: unknown) => key + (p ? JSON.stringify(p) : ""), i18n: { language: "fr-CA" } }),
}));
jest.mock("@/admin/service", () => ({
  chargerCreancesM5: jest.fn(), chargerComptesAPM5: jest.fn(), chargerAttentesFacturationM5: jest.fn(),
}), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/comptes", () => jest.requireActual("./comptes"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const service = require("@/admin/service") as Record<string, jest.Mock>;
const Ecran = require("../../app/(admin)/comptes").default;
const serveur = <T,>(valeur: T) => ({ source: "serveur", valeur, misAJourLe: "2026-09-02T12:00:00Z" });
const premiere = () => lireAP({ ...ap, total: 2, reste: 1, prochain_depart: 1 }, false, 0)!;
let arbre: ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  service.chargerCreancesM5.mockResolvedValue(serveur(lireCreances(creances, JOUR)!));
  service.chargerAttentesFacturationM5.mockResolvedValue(serveur(lireAttentes(attentes)!));
  service.chargerComptesAPM5.mockResolvedValue(serveur(premiere()));
});
afterEach(async () => { if (arbre) await act(async () => { arbre.unmount(); }); });
const bouton = (cle: string) => arbre.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === cle)!;
test("rafraîchir abandonne une ancienne page en vol", async () => {
  let finir!: (x: unknown) => void;
  service.chargerComptesAPM5.mockImplementation((_mode, depart = 0) => depart === 1
    ? new Promise(resolve => { finir = resolve; }) : Promise.resolve(serveur(premiere())));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => { bouton("admin.comptes.suite").props.onPress(); });
  await act(async () => { bouton("admin.commun.rafraichir").props.onPress(); });
  const tardive: any = JSON.parse(JSON.stringify(ap));
  tardive.depart = 1; tardive.total = 2; tardive.comptes[0].po_id = "ancienne-page-fictive";
  await act(async () => { finir(serveur(lireAP(tardive, false, 1)!)); });
  expect(JSON.stringify(arbre.toJSON())).not.toContain("ancienne-page-fictive");
  expect(service.chargerCreancesM5).toHaveBeenCalledTimes(2);
});
test("cache AP ne propose pas une suite hors ligne", async () => {
  service.chargerComptesAPM5.mockResolvedValue({ ...serveur(premiere()), source: "cache",
    raisonHorsLigne: { code: "reseau", detail: "fictif" } });
  await act(async () => { arbre = create(<Ecran />); });
  expect(arbre.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte === "admin.comptes.suite")).toHaveLength(0);
});
test("changer de filtre remplace la page et abandonne l'ancienne suite", async () => {
  let finir!: (x: unknown) => void;
  service.chargerComptesAPM5.mockImplementation((mode, depart = 0) => mode
    ? Promise.resolve(serveur(lireAP(sansPO, true, 0)!)) : depart === 1
      ? new Promise(resolve => { finir = resolve; }) : Promise.resolve(serveur(premiere())));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => { bouton("admin.comptes.suite").props.onPress(); });
  await act(async () => { bouton("admin.comptes.voirSansPO").props.onPress(); });
  await act(async () => { finir(serveur(premiere())); });
  expect(JSON.stringify(arbre.toJSON())).toContain("C-4001");
  expect(JSON.stringify(arbre.toJSON())).not.toContain("PO-1");
  expect(service.chargerComptesAPM5).toHaveBeenLastCalledWith(true, 0);
});

test("une panne du dépôt ne masque pas les autres sections et ne laisse pas une attente infinie", async () => {
  service.chargerCreancesM5.mockRejectedValue(new Error("panne fictive dépôt"));
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("lecture_indisponible");
  expect(JSON.stringify(arbre.toJSON())).toContain("PO-1");
});

test("changer de filtre abandonne aussi la première réponse AP en vol", async () => {
  let finir!: (x: unknown) => void;
  service.chargerComptesAPM5.mockImplementation(mode => mode
    ? Promise.resolve(serveur(lireAP(sansPO, true, 0)!))
    : new Promise(resolve => { finir = resolve; }));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => { bouton("admin.comptes.voirSansPO").props.onPress(); });
  await act(async () => { finir(serveur(premiere())); });
  expect(JSON.stringify(arbre.toJSON())).toContain("C-4001");
  expect(JSON.stringify(arbre.toJSON())).not.toContain("PO-1");
  expect(service.chargerComptesAPM5).toHaveBeenLastCalledWith(true, 0);
});
