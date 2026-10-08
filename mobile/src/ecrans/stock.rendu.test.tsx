import React from "react";
import { act, create } from "react-test-renderer";
import type { ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "../admin/composants";
import { disponibiliteFictive, digestFictif } from "../m6/fixturesStock";
jest.mock("expo-router", () => ({
  useFocusEffect: (callback: () => void | (() => void)) => {
    const React = require("react"); React.useEffect(callback, [callback]);
  },
}));
jest.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, p?: unknown) => key + (p ? JSON.stringify(p) : ""), i18n: { language: "fr-CA" } }),
}));
jest.mock("@/admin/service", () => ({ chargerDisponibiliteM6: jest.fn(), chargerDigestM6: jest.fn() }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/stock", () => jest.requireActual("./stock"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
// La nouvelle lecture WCT est qualifiée séparément ; ce voisin conserve son périmètre global.
jest.mock("@/admin/PertesAlertesM6", () => ({ PertesAlertesM6: () => null }), { virtual: true });
jest.mock("@/admin/ReapprovisionnementM6", () => ({ ReapprovisionnementM6: () => null }), { virtual: true });
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: true }) }));
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => ({ session: { personne: "admin-fictif" }, courante: () => true }) }), { virtual: true });
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => "admin-fictif" }), { virtual: true });
const service = require("@/admin/service") as Record<string, jest.Mock>;
const Ecran = require("../../app/(admin)/stock").default;
const serveur = <T,>(valeur: T) => ({ source: "serveur", valeur, misAJourLe: "2026-10-07T12:00:00Z" });
let arbre: ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  service.chargerDisponibiliteM6.mockResolvedValue(serveur(disponibiliteFictive));
  service.chargerDigestM6.mockResolvedValue(serveur(digestFictif));
});
afterEach(async () => { if (arbre) await act(async () => { arbre.unmount(); }); });
const rafraichir = () => arbre.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === "admin.commun.rafraichir")!;

test("limites et unités explicites, sans pagination inventée", async () => {
  service.chargerDisponibiliteM6.mockResolvedValue(serveur({ ...disponibiliteFictive, tronque: true, reservations_tronquees: true }));
  await act(async () => { arbre = create(<Ecran />); });
  const rendu = JSON.stringify(arbre.toJSON());
  expect(rendu).toContain("admin.stock.articlesTronques");
  expect(rendu).toContain("admin.stock.reservationsTronquees");
  expect(rendu).toContain("admin.stock.uniteInconnue");
  expect(rendu).toContain("admin.stock.seuilsNonFournis");
  expect(arbre.root.findAllByType(BoutonSecondaire)).toHaveLength(1);
});

test("rafraîchir écarte la lecture précédente encore en vol", async () => {
  let finir!: (x: unknown) => void;
  service.chargerDisponibiliteM6.mockImplementationOnce(() => new Promise(resolve => { finir = resolve; }));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => { rafraichir().props.onPress(); });
  const ancienne = JSON.parse(JSON.stringify(disponibiliteFictive));
  ancienne.articles[0].materiau_id = "ancienne-lecture-fictive";
  await act(async () => { finir(serveur(ancienne)); });
  expect(JSON.stringify(arbre.toJSON())).not.toContain("ancienne-lecture-fictive");
  expect(service.chargerDisponibiliteM6).toHaveBeenCalledTimes(2);
});

test("une section refusée ou en panne ne masque pas l'autre", async () => {
  service.chargerDisponibiliteM6.mockResolvedValue({ source: "refus", verdict: { code: "REJ-fictif", detail: "Refus fictif" } });
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("Refus fictif");
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.stock.historique");
  service.chargerDisponibiliteM6.mockRejectedValue(new Error("panne fictive dépôt"));
  await act(async () => { rafraichir().props.onPress(); });
  expect(JSON.stringify(arbre.toJSON())).toContain("lecture_indisponible");
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.stock.historique");
});

test("lecture cache datée et absence de session visibles", async () => {
  service.chargerDisponibiliteM6.mockResolvedValue({ ...serveur(disponibiliteFictive), source: "cache", raisonHorsLigne: { code: "reseau", detail: "fictif" } });
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.commun.cache");
  service.chargerDisponibiliteM6.mockResolvedValue(null);
  await act(async () => { rafraichir().props.onPress(); });
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.commun.sansSession");
  expect(JSON.stringify(arbre.toJSON())).not.toContain("admin.stock.historique");
});
