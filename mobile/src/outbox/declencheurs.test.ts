import { demarrerDeclencheursVidange } from "./declencheurs";
import type { FournisseurEtatApp, FournisseurReseau } from "./declencheurs";

function fauxAppState() {
  let ecouteur: ((etat: string) => void) | null = null;
  const remove = jest.fn();
  const appState: FournisseurEtatApp = {
    addEventListener: jest.fn((_type, listener) => {
      ecouteur = listener;
      return { remove };
    }),
  };
  return { appState, remove, emettre: (etat: string) => ecouteur?.(etat) };
}

function fauxNetInfo() {
  let ecouteur: ((etat: { isConnected: boolean | null }) => void) | null = null;
  const desabonner = jest.fn();
  const netInfo: FournisseurReseau = {
    addEventListener: jest.fn((listener) => {
      ecouteur = listener;
      return desabonner;
    }),
  };
  return { netInfo, desabonner, emettre: (isConnected: boolean | null) => ecouteur?.({ isConnected }) };
}

/** Laisse s'écouler la chaîne .catch()/.finally() interne de declencherEtSignaler. */
async function laisserAvancer(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("demarrerDeclencheursVidange — déclencheur premier plan", () => {
  test("AppState 'active' déclenche une vidange", async () => {
    const { appState, emettre } = fauxAppState();
    const { netInfo } = fauxNetInfo();
    const declencher = jest.fn().mockResolvedValue(undefined);

    demarrerDeclencheursVidange({ declencher, appState, netInfo });
    emettre("active");
    await laisserAvancer();

    expect(declencher).toHaveBeenCalledTimes(1);
  });

  test.each(["background", "inactive"])("AppState '%s' NE déclenche PAS de vidange", async (etat) => {
    const { appState, emettre } = fauxAppState();
    const { netInfo } = fauxNetInfo();
    const declencher = jest.fn().mockResolvedValue(undefined);

    demarrerDeclencheursVidange({ declencher, appState, netInfo });
    emettre(etat);
    await laisserAvancer();

    expect(declencher).not.toHaveBeenCalled();
  });
});

describe("demarrerDeclencheursVidange — déclencheur retour réseau", () => {
  test("NetInfo isConnected:true déclenche une vidange", async () => {
    const { appState } = fauxAppState();
    const { netInfo, emettre } = fauxNetInfo();
    const declencher = jest.fn().mockResolvedValue(undefined);

    demarrerDeclencheursVidange({ declencher, appState, netInfo });
    emettre(true);
    await laisserAvancer();

    expect(declencher).toHaveBeenCalledTimes(1);
  });

  test.each([false, null])("NetInfo isConnected:%p NE déclenche PAS de vidange", async (valeur) => {
    const { appState } = fauxAppState();
    const { netInfo, emettre } = fauxNetInfo();
    const declencher = jest.fn().mockResolvedValue(undefined);

    demarrerDeclencheursVidange({ declencher, appState, netInfo });
    emettre(valeur);
    await laisserAvancer();

    expect(declencher).not.toHaveBeenCalled();
  });
});

describe("demarrerDeclencheursVidange — nettoyage et rétroaction", () => {
  test("la fonction de nettoyage retire les DEUX abonnements", () => {
    const { appState, remove } = fauxAppState();
    const { netInfo, desabonner } = fauxNetInfo();
    const nettoyer = demarrerDeclencheursVidange({ declencher: jest.fn(), appState, netInfo });

    nettoyer();

    expect(remove).toHaveBeenCalledTimes(1);
    expect(desabonner).toHaveBeenCalledTimes(1);
  });

  test("aoDeclenchement est appelé après une vidange réussie", async () => {
    const { appState, emettre } = fauxAppState();
    const { netInfo } = fauxNetInfo();
    const aoDeclenchement = jest.fn();
    demarrerDeclencheursVidange({ declencher: jest.fn().mockResolvedValue(undefined), appState, netInfo, aoDeclenchement });

    emettre("active");
    await laisserAvancer();

    expect(aoDeclenchement).toHaveBeenCalledTimes(1);
  });

  test("une vidange qui échoue (erreur de stockage) n'empêche pas aoDeclenchement et ne remonte jamais à l'appelant", async () => {
    const espionConsole = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const { appState, emettre } = fauxAppState();
    const { netInfo } = fauxNetInfo();
    const aoDeclenchement = jest.fn();
    const declencher = jest.fn().mockRejectedValue(new Error("SQLite indisponible"));

    expect(() => {
      demarrerDeclencheursVidange({ declencher, appState, netInfo, aoDeclenchement });
      emettre("active");
    }).not.toThrow();
    await laisserAvancer();

    expect(aoDeclenchement).toHaveBeenCalledTimes(1);
    expect(espionConsole).toHaveBeenCalledTimes(1);
    espionConsole.mockRestore();
  });
});
