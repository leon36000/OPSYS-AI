import { creerIdentiteDepuisGraine } from "./identite";
import { chargerOuCreerIdentite, chargerSession, effacerSession, sauvegarderSession, type CoffreAppairage } from "./stockage";

/** Faux `expo-secure-store` en mémoire — même principe d'injection que
 * `FournisseurEtatApp`/`FournisseurReseau` de `src/outbox/declencheurs.ts`. */
function creerFauxCoffre(initial: Record<string, string> = {}): CoffreAppairage {
  const magasin = new Map(Object.entries(initial));
  return {
    getItemAsync: async (cle) => magasin.get(cle) ?? null,
    setItemAsync: async (cle, valeur) => {
      magasin.set(cle, valeur);
    },
    deleteItemAsync: async (cle) => {
      magasin.delete(cle);
    },
  };
}

const GRAINE_FIXE = Uint8Array.from({ length: 32 }, (_, i) => i + 1);

describe("chargerOuCreerIdentite", () => {
  test("premier lancement : génère une identité et la persiste (clé secrète jamais vide)", async () => {
    const coffre = creerFauxCoffre();
    const genererGraine = jest.fn(() => GRAINE_FIXE);

    const identite = await chargerOuCreerIdentite(coffre, genererGraine);

    expect(genererGraine).toHaveBeenCalledTimes(1);
    expect(identite).toEqual(creerIdentiteDepuisGraine(GRAINE_FIXE));
    await expect(coffre.getItemAsync("opsys_appareil_cle_secrete_v1")).resolves.toBe(identite.cleSecreteBase64Url);
  });

  test("lancements suivants : relit la MÊME identité, sans régénérer de graine", async () => {
    const coffre = creerFauxCoffre();
    const genererGraine = jest.fn(() => GRAINE_FIXE);
    const premiere = await chargerOuCreerIdentite(coffre, genererGraine);

    const genererGraineAppelSuivant = jest.fn(() => {
      throw new Error("ne doit jamais être appelé : une identité existe déjà");
    });
    const deuxieme = await chargerOuCreerIdentite(coffre, genererGraineAppelSuivant);

    expect(deuxieme).toEqual(premiere);
    expect(genererGraineAppelSuivant).not.toHaveBeenCalled();
  });

  test("deux coffres vides indépendants génèrent des identités différentes", async () => {
    let compteur = 0;
    const genererGraine = () => Uint8Array.from({ length: 32 }, () => (compteur += 1) % 256);

    const a = await chargerOuCreerIdentite(creerFauxCoffre(), genererGraine);
    const b = await chargerOuCreerIdentite(creerFauxCoffre(), genererGraine);

    expect(a.deviceId).not.toBe(b.deviceId);
  });
});

describe("sauvegarderSession / chargerSession / effacerSession", () => {
  const SESSION = { urlBase: "https://grs.exemple.ca", jeton: "jeton-secret", role: "operator", appareilId: "abc123" };

  test("aller-retour simple", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderSession(SESSION, coffre);
    await expect(chargerSession(coffre)).resolves.toEqual(SESSION);
  });

  test("aucune session stockée -> null (jamais une session devinée)", async () => {
    await expect(chargerSession(creerFauxCoffre())).resolves.toBeNull();
  });

  test("valeur stockée corrompue (JSON invalide) -> null, fail-closed", async () => {
    const coffre = creerFauxCoffre({ opsys_appareil_session_v1: "{ pas du json" });
    await expect(chargerSession(coffre)).resolves.toBeNull();
  });

  test("valeur stockée d'une forme inconnue (champ manquant) -> null, fail-closed", async () => {
    const coffre = creerFauxCoffre({ opsys_appareil_session_v1: JSON.stringify({ jeton: "x" }) });
    await expect(chargerSession(coffre)).resolves.toBeNull();
  });

  test("effacerSession retire la session persistée", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderSession(SESSION, coffre);
    await effacerSession(coffre);
    await expect(chargerSession(coffre)).resolves.toBeNull();
  });

  test("la clé de session est distincte de la clé d'identité (pas de collision)", async () => {
    const coffre = creerFauxCoffre();
    await chargerOuCreerIdentite(coffre, () => GRAINE_FIXE);
    await sauvegarderSession(SESSION, coffre);
    await expect(chargerSession(coffre)).resolves.toEqual(SESSION);
    const identiteEncore = await chargerOuCreerIdentite(coffre, () => {
      throw new Error("ne doit pas être appelé");
    });
    expect(identiteEncore.deviceId).toBe(creerIdentiteDepuisGraine(GRAINE_FIXE).deviceId);
  });
});
