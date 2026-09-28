import { definirConfigurationAppel, obtenirConfigurationAppel } from "./configuration";

/**
 * Transition « non apparié -> apparié » (PLAN T1.4-c3, mission item 5). `configuration.ts` garde
 * un état EN MÉMOIRE (module-level) : chaque test le remet explicitement à `null` pour rester
 * indépendant des autres (pas d'isolation automatique entre fichiers de test — même module).
 */
describe("obtenirConfigurationAppel / definirConfigurationAppel", () => {
  afterEach(() => {
    definirConfigurationAppel(null);
  });

  test("état initial : null (aucun faux état apparié inventé)", () => {
    expect(obtenirConfigurationAppel()).toBeNull();
  });

  test("après definirConfigurationAppel, obtenirConfigurationAppel reflète la vraie configuration", () => {
    const configuration = { urlBase: "https://grs.exemple.ca", jeton: "jeton-abc", appareilId: "device-1" };
    definirConfigurationAppel(configuration);
    expect(obtenirConfigurationAppel()).toEqual(configuration);
  });

  test("definirConfigurationAppel(null) ramène à l'état non apparié", () => {
    definirConfigurationAppel({ urlBase: "https://x", jeton: "t", appareilId: "d" });
    expect(obtenirConfigurationAppel()).not.toBeNull();
    definirConfigurationAppel(null);
    expect(obtenirConfigurationAppel()).toBeNull();
  });

  test("un appel ultérieur écrase le précédent (dernier appairage fait foi)", () => {
    definirConfigurationAppel({ urlBase: "https://a", jeton: "1", appareilId: "d1" });
    definirConfigurationAppel({ urlBase: "https://b", jeton: "2", appareilId: "d2" });
    expect(obtenirConfigurationAppel()).toEqual({ urlBase: "https://b", jeton: "2", appareilId: "d2" });
  });
});
