import React from "react";
import { act, create } from "react-test-renderer";
import type { ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire, Ligne } from "../admin/composants";
import { lireBriefing, lireAlertesM9, lireEtatConsolide, lireSuiteBriefing } from "../m9/briefing";
import fixture from "../m9/fixtures/reponses-moteur.json";
import strategiqueFixture from "../m9/fixturesLectureStrategique.json";
import { lireLectureStrategique } from "../m9/lectureStrategique";
let mockEpoch = 0, mockConnected = true;
let mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useEtatIdentite: () => mockIdentite }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => { const e = mockEpoch;
  return { session: mockIdentite.role === "admin" ? { personne: "admin-fictif" } : null,
    courante: () => e === mockEpoch && mockIdentite.role === "admin" }; } }), { virtual: true });

jest.mock("expo-router", () => ({
  useFocusEffect: (callback: () => void | (() => void)) => {
    const React = require("react");
    React.useEffect(callback, [callback]);
  },
}));
jest.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: unknown) => key + (params ? JSON.stringify(params) : ""),
  }),
}));
jest.mock(
  "@/admin/service",
  () => ({
    chargerBriefingM9: jest.fn(),
    chargerSuiteBriefingM9: jest.fn(),
    chargerAlertesM9: jest.fn(),
    chargerEtatConsolideM9: jest.fn(),
    chargerLectureStrategiqueM9: jest.fn(),
    actualiserConnectiviteBriefingM9: jest.fn(),
  }),
  { virtual: true },
);
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/admin/horloge", () => jest.requireActual("../admin/horloge"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/briefing", () => jest.requireActual("./briefing"), { virtual: true });
jest.mock("@/ecrans/lectureStrategique", () => jest.requireActual("./lectureStrategique"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
jest.mock("@/m9/briefing", () => jest.requireActual("../m9/briefing"), { virtual: true });

const service = require("@/admin/service") as Record<string, jest.Mock>;
const Ecran = require("../../app/(admin)/briefing").default;
const serveur = <T,>(valeur: T) => ({
  source: "serveur",
  valeur,
  misAJourLe: "2026-10-06T11:00:00Z",
});
let arbre: ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks();
  mockEpoch++; mockConnected = true; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "admin" };
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  service.chargerBriefingM9.mockResolvedValue(
    serveur(lireBriefing(fixture.reponses.briefing.resultat)!),
  );
  service.chargerAlertesM9.mockResolvedValue(
    serveur(lireAlertesM9(fixture.reponses.alertes.resultat, 0)!),
  );
  service.chargerEtatConsolideM9.mockResolvedValue(
    serveur(lireEtatConsolide(fixture.reponses.etat.resultat)!),
  );
  service.chargerLectureStrategiqueM9.mockResolvedValue({ source: "aucune", raison: { code: "fictif_absent", detail: "" } });
});
afterEach(async () => {
  if (arbre)
    await act(async () => {
      arbre.unmount();
    });
});

function bouton(cle: string) {
  return arbre.root.findAllByType(BoutonSecondaire).find((b) => b.props.texte === cle)!;
}

test("le rafraîchissement abandonne une suite qui arrive après la nouvelle lecture", async () => {
  let resoudre!: (v: unknown) => void;
  const tardive = new Promise((resolve) => {
    resoudre = resolve;
  });
  service.chargerSuiteBriefingM9.mockReturnValue(tardive);
  await act(async () => {
    arbre = create(<Ecran />);
  });
  await act(async () => {
    bouton("admin.briefing.voirPlus").props.onPress();
  });
  expect(service.chargerSuiteBriefingM9).toHaveBeenCalledTimes(1);
  await act(async () => {
    bouton("admin.commun.rafraichir").props.onPress();
  });
  expect(service.chargerBriefingM9).toHaveBeenCalledTimes(2);
  const depart = fixture.appels.suite_decisions_en_attente.args.depart;
  const page = lireSuiteBriefing(
    fixture.reponses.suite_decisions_en_attente.resultat,
    "decisions_en_attente",
    depart,
  )!;
  await act(async () => {
    resoudre(
      serveur({
        ...page,
        items: [{ ...(page.items[0] as object), resume: "page-obsolete-fictive" }],
      }),
    );
  });
  expect(JSON.stringify(arbre.toJSON())).not.toContain("page-obsolete-fictive");
});

test("une copie cache du briefing n'offre aucune suite inventée hors ligne", async () => {
  service.chargerBriefingM9.mockResolvedValue({
    ...serveur(lireBriefing(fixture.reponses.briefing.resultat)!),
    source: "cache",
    raisonHorsLigne: { code: "reseau", detail: "panne fictive" },
  });
  service.chargerAlertesM9.mockResolvedValue({
    source: "refus",
    verdict: { code: "tool_call_blocked", detail: "refus fictif" },
  });
  await act(async () => {
    arbre = create(<Ecran />);
  });
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.briefing.cacheSansSuite");
  expect(
    arbre.root
      .findAllByType(BoutonSecondaire)
      .filter((b) => b.props.texte === "admin.briefing.voirPlus"),
  ).toHaveLength(0);
  expect(service.chargerSuiteBriefingM9).not.toHaveBeenCalled();
});

test("rôle admin retiré : les données affichées et la réponse tardive disparaissent", async () => {
  await act(async () => { arbre = create(<Ecran />); });
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.briefing.sections");
  let terminer!: (v: unknown) => void;
  service.chargerBriefingM9.mockImplementationOnce(() => new Promise(r => { terminer = r; }));
  await act(async () => bouton("admin.commun.rafraichir").props.onPress());
  mockEpoch++; mockIdentite = { genre: "confirmee", personne: "admin-fictif", role: "seller" };
  await act(async () => arbre.update(<Ecran />));
  await act(async () => terminer(serveur(lireBriefing(fixture.reponses.briefing.resultat)!)));
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.commun.sansSession");
  expect(JSON.stringify(arbre.toJSON())).not.toContain("admin.briefing.sections");
  expect(service.chargerBriefingM9).toHaveBeenCalledTimes(2);
});

test("lecture stratégique demandée séparément ; erreur d'une section ferme cette seule section", async () => {
  service.chargerLectureStrategiqueM9.mockRejectedValueOnce(new Error("SQLite fictif indisponible"));
  await act(async () => { arbre = create(<Ecran />); });
  expect(service.chargerLectureStrategiqueM9).toHaveBeenCalledTimes(1);
  expect(service.actualiserConnectiviteBriefingM9).toHaveBeenCalledWith(true);
  expect(JSON.stringify(arbre.toJSON())).toContain("lecture_indisponible");
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.briefing.sections");
});

function strategiqueNative(nom: keyof typeof strategiqueFixture.capturesHttp.lectures) {
  const c = strategiqueFixture.capturesHttp.lectures[nom];
  expect(c.fictif).toBe(true);
  const v = lireLectureStrategique(c.enveloppe.resultat, c.arguments.maintenant, c.arguments.depart);
  if (!v) throw new Error("capture HTTP M9 fictive illisible");
  return v;
}
function seulementStrategique(nom: keyof typeof strategiqueFixture.capturesHttp.lectures) {
  for (const nomService of ["chargerBriefingM9", "chargerAlertesM9", "chargerEtatConsolideM9"])
    service[nomService].mockResolvedValue({ source: "aucune", raison: { code: "fictif_absent", detail: "" } });
  service.chargerLectureStrategiqueM9.mockResolvedValue(serveur(strategiqueNative(nom)));
}
test("preuve HTTP du même WCT : 40.00, seuil30.00, versions et aucune action de décision", async () => {
  seulementStrategique("ordinaire-40-30");
  await act(async () => { arbre = create(<Ecran />); });
  const messages = arbre.root.findAllByType(Ligne).map(v => v.props.m);
  const native = strategiqueNative("ordinaire-40-30").lectures[0];
  expect(messages).toContainEqual({ cle: "admin.lectureStrategique.mesure", params: { valeur: "40.00", unite: native.unite } });
  expect(messages).toContainEqual({ cle: "admin.lectureStrategique.seuil", params: { seuil: "30.00", sens: native.sens } });
  expect(messages).toContainEqual({ cle: "admin.lectureStrategique.chantier", params: { id: native.chantier } });
  expect(messages).toContainEqual({ cle: "admin.lectureStrategique.version", params: { version: native.version_definition } });
  expect(arbre.root.findAllByType(BoutonSecondaire).map(v => v.props.texte).sort())
    .toEqual(["admin.commun.rafraichir", "admin.lectureStrategique.relire"].sort());
  expect(JSON.stringify(arbre.toJSON())).toContain("admin.lectureStrategique.decisionNonPrise");
});
test("page suivante remplace les preuves, même référence conservée et première page relisible", async () => {
  seulementStrategique("page-0"); await act(async () => { arbre = create(<Ecran />); });
  const premiere = strategiqueNative("page-0"), suivante = strategiqueNative("page-1");
  service.chargerLectureStrategiqueM9.mockResolvedValueOnce(serveur(suivante));
  await act(async () => bouton("admin.lectureStrategique.suivante").props.onPress());
  expect(service.chargerLectureStrategiqueM9.mock.calls[1])
    .toEqual([service.chargerLectureStrategiqueM9.mock.calls[0][0], premiere.affichage.prochain_depart]);
  const affiches = arbre.root.findAllByType(Ligne).map(v => v.props.m).filter(m => m.cle === "admin.lectureStrategique.chantier");
  expect(affiches.map(m => m.params.id)).toEqual(suivante.lectures.map(v => v.chantier));
  service.chargerLectureStrategiqueM9.mockResolvedValueOnce(serveur(premiere));
  await act(async () => bouton("admin.lectureStrategique.relire").props.onPress());
  expect(service.chargerLectureStrategiqueM9.mock.calls[2]).toEqual([service.chargerLectureStrategiqueM9.mock.calls[0][0], 0]);
});
test("rafraîchissement abandonne l'ancienne page de preuves et hors ligne ferme la lecture", async () => {
  seulementStrategique("page-0"); await act(async () => { arbre = create(<Ecran />); });
  let finir!: (v: unknown) => void;
  service.chargerLectureStrategiqueM9.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await act(async () => bouton("admin.lectureStrategique.suivante").props.onPress());
  service.chargerLectureStrategiqueM9.mockResolvedValueOnce({ source: "refus", verdict: { code: "refus_metier", detail: "fictif" } });
  await act(async () => bouton("admin.commun.rafraichir").props.onPress());
  await act(async () => finir(serveur(strategiqueNative("page-1"))));
  expect(arbre.root.findAllByType(Ligne).filter(v => v.props.m.cle === "admin.lectureStrategique.chantier")).toHaveLength(0);
  mockConnected = false; service.chargerLectureStrategiqueM9.mockResolvedValueOnce({ source: "aucune", raison: { code: "hors_ligne", detail: "" } });
  await act(async () => arbre.update(<Ecran />));
  expect(service.actualiserConnectiviteBriefingM9).toHaveBeenLastCalledWith(false);
  expect(JSON.stringify(arbre.toJSON())).toContain("hors_ligne");
});
