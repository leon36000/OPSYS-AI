import type { CoffreAppairage } from "../appairage/stockage";
import type { ConfigurationAppel } from "../protocole/configuration";
import type { ResultatLectureIdentite } from "./contrat";
import { lireEtMemoriserIdentite, oublierIdentiteMemorisee, restaurerSession } from "./service";
import { chargerIdentiteMemorisee, sauvegarderIdentiteMemorisee } from "./stockage";

const APPAREIL = "a".repeat(64);
const CONFIGURATION: ConfigurationAppel = { urlBase: "https://grs.exemple.ca", jeton: "jeton-secret", appareilId: APPAREIL };
const MAINTENANT = new Date("2026-09-29T14:30:00.000Z");
const EMPLOYE = { appareilId: APPAREIL, personne: "jdupont", role: "employee" } as const;
const MEMORISEE = { ...EMPLOYE, confirmeLe: "2026-09-28T08:00:00.000Z" };
const CLE_SESSION = "opsys_appareil_session_v1";
const SESSION = { urlBase: CONFIGURATION.urlBase, jeton: CONFIGURATION.jeton, role: "operator", appareilId: APPAREIL };

function creerFauxCoffre(
  initial: Record<string, string> = {},
  pannes: { lecture?: boolean; ecriture?: boolean; effacement?: boolean } = {},
): CoffreAppairage {
  const magasin = new Map(Object.entries(initial));
  return {
    getItemAsync: async (cle) => {
      if (pannes.lecture) {
        throw new Error("Keychain indisponible");
      }
      return magasin.get(cle) ?? null;
    },
    setItemAsync: async (cle, valeur) => {
      if (pannes.ecriture) {
        throw new Error("écriture impossible");
      }
      magasin.set(cle, valeur);
    },
    deleteItemAsync: async (cle) => {
      if (pannes.effacement) {
        throw new Error("effacement impossible");
      }
      magasin.delete(cle);
    },
  };
}

function lireRendant(resultat: ResultatLectureIdentite) {
  return jest.fn(async (_configuration: ConfigurationAppel) => resultat);
}

let erreurs: jest.SpyInstance;
beforeEach(() => {
  erreurs = jest.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  erreurs.mockRestore();
});

describe("restaurerSession", () => {
  test("aucune session -> non appairé, aucune configuration", async () => {
    await expect(restaurerSession(creerFauxCoffre())).resolves.toEqual({
      configuration: null,
      etat: { genre: "non_appairee" },
    });
  });

  test("session sans identité gardée -> configuration restaurée, lecture en cours", async () => {
    const coffre = creerFauxCoffre({ [CLE_SESSION]: JSON.stringify(SESSION) });
    await expect(restaurerSession(coffre)).resolves.toEqual({
      configuration: CONFIGURATION,
      etat: { genre: "en_lecture" },
    });
  });

  test("session avec identité gardée -> à reconfirmer (utilisable hors ligne)", async () => {
    const coffre = creerFauxCoffre({ [CLE_SESSION]: JSON.stringify(SESSION) });
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);
    await expect(restaurerSession(coffre)).resolves.toEqual({
      configuration: CONFIGURATION,
      etat: { genre: "a_reconfirmer", identite: EMPLOYE, confirmeLe: MEMORISEE.confirmeLe },
    });
  });

  test("le rôle de transport stocké dans la session n'est jamais le profil", async () => {
    const coffre = creerFauxCoffre({ [CLE_SESSION]: JSON.stringify(SESSION) });
    const { etat } = await restaurerSession(coffre);
    expect(etat).not.toMatchObject({ identite: { role: "operator" } });
    expect(etat.genre).toBe("en_lecture");
  });

  test("coffre illisible -> erreur stockage_illisible (pas « non appairé »), sans lever ni fuir de secret", async () => {
    const coffre = creerFauxCoffre({ [CLE_SESSION]: JSON.stringify(SESSION) }, { lecture: true });
    await expect(restaurerSession(coffre)).resolves.toEqual({
      configuration: null,
      etat: { genre: "erreur", motif: "stockage_illisible" },
    });
    expect(erreurs).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(erreurs.mock.calls)).not.toContain("jeton-secret");
  });
});

describe("lireEtMemoriserIdentite", () => {
  test("confirmée : l'état est celui du serveur et l'identité est gardée avec l'heure de confirmation", async () => {
    const coffre = creerFauxCoffre();
    const lire = lireRendant({ genre: "confirmee", identite: EMPLOYE });

    const etat = await lireEtMemoriserIdentite({ configuration: CONFIGURATION, coffre, lire, maintenant: () => MAINTENANT });

    expect(etat).toEqual({ genre: "confirmee", identite: EMPLOYE });
    expect(lire).toHaveBeenCalledWith(CONFIGURATION);
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toEqual({
      ...EMPLOYE,
      confirmeLe: "2026-09-29T14:30:00.000Z",
    });
  });

  test("refusée : aucun profil, et l'identité gardée est effacée", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);

    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre,
      lire: lireRendant({ genre: "refusee", motif: "appareil_non_attribue" }),
      maintenant: () => MAINTENANT,
    });

    expect(etat).toEqual({ genre: "erreur", motif: "appareil_non_attribue" });
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toBeNull();
  });

  test("indisponible avec une identité gardée : elle sert, à reconfirmer, et reste au coffre", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);

    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre,
      lire: lireRendant({ genre: "indisponible", message: "réseau" }),
      maintenant: () => MAINTENANT,
    });

    expect(etat).toEqual({ genre: "a_reconfirmer", identite: EMPLOYE, confirmeLe: MEMORISEE.confirmeLe });
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toEqual(MEMORISEE);
  });

  test("indisponible sans identité gardée : erreur, aucun profil", async () => {
    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre: creerFauxCoffre(),
      lire: lireRendant({ genre: "indisponible", message: "réseau" }),
      maintenant: () => MAINTENANT,
    });
    expect(etat).toEqual({ genre: "erreur", motif: "hors_ligne_sans_memoire" });
  });

  test("une identité gardée pour un autre appareil ne sert pas hors ligne", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee({ ...MEMORISEE, appareilId: "b".repeat(64) }, coffre);
    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre,
      lire: lireRendant({ genre: "indisponible", message: "réseau" }),
    });
    expect(etat).toEqual({ genre: "erreur", motif: "hors_ligne_sans_memoire" });
  });

  test("une lecture qui lève est traitée comme indisponible, sans lever", async () => {
    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre: creerFauxCoffre(),
      lire: async () => {
        throw new Error("panne inattendue");
      },
    });
    expect(etat).toEqual({ genre: "erreur", motif: "hors_ligne_sans_memoire" });
    expect(erreurs).toHaveBeenCalled();
  });

  test("écriture impossible au coffre : l'état confirmé n'est pas perdu, l'échec est signalé, sans lever", async () => {
    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre: creerFauxCoffre({}, { ecriture: true }),
      lire: lireRendant({ genre: "confirmee", identite: EMPLOYE }),
      maintenant: () => MAINTENANT,
    });
    expect(etat).toEqual({ genre: "confirmee", identite: EMPLOYE });
    expect(erreurs).toHaveBeenCalledTimes(1);
  });

  test("coffre illisible : la lecture du serveur décide seule (rien de gardé), sans lever", async () => {
    const etat = await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre: creerFauxCoffre({}, { lecture: true, ecriture: true }),
      lire: lireRendant({ genre: "indisponible", message: "réseau" }),
    });
    expect(etat).toEqual({ genre: "erreur", motif: "hors_ligne_sans_memoire" });
  });

  test("ne journalise jamais le jeton d'appareil", async () => {
    await lireEtMemoriserIdentite({
      configuration: CONFIGURATION,
      coffre: creerFauxCoffre({}, { ecriture: true }),
      lire: lireRendant({ genre: "confirmee", identite: EMPLOYE }),
    });
    expect(JSON.stringify(erreurs.mock.calls)).not.toContain("jeton-secret");
  });
});

describe("oublierIdentiteMemorisee", () => {
  test("efface l'identité gardée (un nouvel appairage repart de zéro)", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);
    await oublierIdentiteMemorisee(coffre);
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toBeNull();
  });

  test("un effacement impossible est signalé, sans lever", async () => {
    await expect(oublierIdentiteMemorisee(creerFauxCoffre({}, { effacement: true }))).resolves.toBeUndefined();
    expect(erreurs).toHaveBeenCalledTimes(1);
  });
});
