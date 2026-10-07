import React from "react";
import { act, create } from "react-test-renderer";
import type { ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "../admin/composants";
import { lireBriefing, lireAlertesM9, lireEtatConsolide, lireSuiteBriefing } from "../m9/briefing";
import fixture from "../m9/fixtures/reponses-moteur.json";

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
  }),
  { virtual: true },
);
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/admin/horloge", () => jest.requireActual("../admin/horloge"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/briefing", () => jest.requireActual("./briefing"), { virtual: true });
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
