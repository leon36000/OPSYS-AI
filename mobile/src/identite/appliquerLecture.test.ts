import type { ConfigurationAppel } from "../protocole/configuration";
import { appliquerLecture } from "./appliquerLecture";
import type { DependancesAppliquerLecture } from "./appliquerLecture";
import type { EtatIdentite } from "./etat";

const APPAREIL = "a".repeat(64);
const CONFIGURATION: ConfigurationAppel = { urlBase: "https://grs.exemple.ca", jeton: "jeton-1", appareilId: APPAREIL };
const ETAT: EtatIdentite = { genre: "confirmee", identite: { appareilId: APPAREIL, personne: "etienne", role: "employee" } };

function dependances(surcharges: Partial<DependancesAppliquerLecture> = {}, journal: string[] = []): DependancesAppliquerLecture {
  return {
    configurationCourante: () => CONFIGURATION,
    synchroniserCaches: async () => {
      journal.push("caches");
    },
    definirEtat: () => {
      journal.push("etat");
    },
    ...surcharges,
  };
}

describe("appliquerLecture — ce que l'app fait d'une lecture de l'identité qui aboutit", () => {
  test("les caches de l'ancienne identité sont effacés AVANT que le profil change", async () => {
    const journal: string[] = [];
    const appliquee = await appliquerLecture(ETAT, CONFIGURATION, dependances({}, journal));
    expect(appliquee).toBe(true);
    expect(journal).toEqual(["caches", "etat"]);
  });

  test("l'état appliqué et la configuration sont ceux de la lecture, tels quels", async () => {
    const definirEtat = jest.fn();
    const synchroniserCaches = jest.fn(async () => undefined);
    await appliquerLecture(ETAT, CONFIGURATION, dependances({ definirEtat, synchroniserCaches }));
    expect(synchroniserCaches).toHaveBeenCalledWith(ETAT);
    expect(definirEtat).toHaveBeenCalledWith(ETAT, CONFIGURATION);
  });

  test("un nouvel appairage a changé le jeton entre-temps : le résultat est JETÉ (ni profil, ni purge)", async () => {
    const journal: string[] = [];
    const appliquee = await appliquerLecture(
      ETAT,
      CONFIGURATION,
      dependances({ configurationCourante: () => ({ ...CONFIGURATION, jeton: "jeton-2" }) }, journal),
    );
    expect(appliquee).toBe(false);
    expect(journal).toEqual([]);
  });

  test("un autre appareil dans la configuration courante : jeté aussi", async () => {
    const journal: string[] = [];
    const appliquee = await appliquerLecture(
      ETAT,
      CONFIGURATION,
      dependances({ configurationCourante: () => ({ ...CONFIGURATION, appareilId: "b".repeat(64) }) }, journal),
    );
    expect(appliquee).toBe(false);
    expect(journal).toEqual([]);
  });

  test("plus aucune configuration (rien d'apparié) : jeté", async () => {
    const journal: string[] = [];
    expect(await appliquerLecture(ETAT, CONFIGURATION, dependances({ configurationCourante: () => null }, journal))).toBe(false);
    expect(journal).toEqual([]);
  });

  test("une purge qui échoue n'empêche JAMAIS le changement de profil, et l'échec est journalisé", async () => {
    const erreurs = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const journal: string[] = [];
    const appliquee = await appliquerLecture(
      ETAT,
      CONFIGURATION,
      dependances(
        {
          synchroniserCaches: async () => {
            journal.push("caches");
            throw new Error("SQLite occupé");
          },
        },
        journal,
      ),
    );
    expect(appliquee).toBe(true);
    expect(journal).toEqual(["caches", "etat"]);
    expect(erreurs).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(erreurs.mock.calls)).not.toContain("etienne");
    erreurs.mockRestore();
  });

  test("le refus du serveur (jeton révoqué) passe par la même voie : purge, puis l'écran d'identité", async () => {
    const refus: EtatIdentite = { genre: "erreur", motif: "jeton_refuse" };
    const journal: string[] = [];
    await appliquerLecture(refus, CONFIGURATION, dependances({}, journal));
    expect(journal).toEqual(["caches", "etat"]);
  });
});
