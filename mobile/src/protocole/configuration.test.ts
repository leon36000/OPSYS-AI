import {
  definirConfigurationAppel,
  definirPersonneConfirmee,
  obtenirConfigurationAppel,
  obtenirSessionEnvoi,
} from "./configuration";

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

describe("obtenirSessionEnvoi (PLAN T1.4-l) : la file sortante suit le jeton courant", () => {
  const CONFIG_1 = { urlBase: "https://grs.exemple.ca", jeton: "jeton-1", appareilId: "device-1" };
  const CONFIG_2 = { urlBase: "https://grs.exemple.ca", jeton: "jeton-2", appareilId: "device-1" };

  afterEach(() => {
    definirConfigurationAppel(null);
    definirPersonneConfirmee(null);
  });

  test("rien sans configuration, rien sans personne confirmée", () => {
    expect(obtenirSessionEnvoi()).toBeNull();
    definirConfigurationAppel(CONFIG_1);
    expect(obtenirSessionEnvoi()).toBeNull();
    definirConfigurationAppel(null);
    definirPersonneConfirmee({ jeton: "jeton-1", appareilId: "device-1", personne: "jdupont" });
    expect(obtenirSessionEnvoi()).toBeNull();
  });

  test("configuration et personne du MÊME jeton : la session porte le jeton et la personne", () => {
    definirConfigurationAppel(CONFIG_1);
    definirPersonneConfirmee({ jeton: "jeton-1", appareilId: "device-1", personne: "jdupont" });
    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_1, personne: "jdupont" });
  });

  test("nouvel appairage : la personne confirmée pour l'ancien jeton ne vaut rien pour le nouveau", () => {
    definirConfigurationAppel(CONFIG_1);
    definirPersonneConfirmee({ jeton: "jeton-1", appareilId: "device-1", personne: "jdupont" });
    definirConfigurationAppel(CONFIG_2);
    expect(obtenirSessionEnvoi()).toBeNull();

    definirPersonneConfirmee({ jeton: "jeton-2", appareilId: "device-1", personne: "jdupont" });
    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_2, personne: "jdupont" });
  });

  test("une personne confirmée pour un autre appareil ne sert pas", () => {
    definirConfigurationAppel(CONFIG_1);
    definirPersonneConfirmee({ jeton: "jeton-1", appareilId: "device-9", personne: "jdupont" });
    expect(obtenirSessionEnvoi()).toBeNull();
  });
});
