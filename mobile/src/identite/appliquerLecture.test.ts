import type { ConfigurationAppel } from "../protocole/configuration";
import { appliquerLecture } from "./appliquerLecture";
import type { DependancesAppliquerLecture } from "./appliquerLecture";
import type { EtatIdentite } from "./etat";
import { synchroniserCaches, ecrireProprietaireDesCaches, CLE_PROPRIETAIRE_DES_CACHES } from "./caches";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { PREFIXES_DES_CACHES_PAR_PERSONNE } from "../stockage/cles";

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
    expect(synchroniserCaches).toHaveBeenCalledWith(ETAT, expect.any(Function));
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

  test("nouvel appairage pendant la purge : ne pas appliquer l'ancien état", async () => {
    let courant: ConfigurationAppel | null = CONFIGURATION;
    let terminer!: () => void;
    const purge = new Promise<void>((resolve) => { terminer = resolve; });
    const definirEtat = jest.fn();
    const pending = appliquerLecture(ETAT, CONFIGURATION, dependances({
      configurationCourante: () => courant,
      synchroniserCaches: async () => { await purge; },
      definirEtat,
    }));
    courant = { ...CONFIGURATION, jeton: "jeton-2" };
    terminer();
    expect(await pending).toBe(false);
    expect(definirEtat).not.toHaveBeenCalled();
  });

  test("purge async périmée ne réattribue pas son marqueur aux nouveaux caches", async () => {
    let courant: ConfigurationAppel | null = CONFIGURATION;
    const memoire = new DepotCleValeurMemoire();
    await ecrireProprietaireDesCaches(memoire, { personne: "ancienne", role: "employee" });
    await memoire.ecrire(`${PREFIXES_DES_CACHES_PAR_PERSONNE[0]}cache-a`, "ancienne donnée");
    let commencer!: () => void;
    let finir!: () => void;
    const purger = new Promise<void>((resolve) => { commencer = resolve; });
    const attente = new Promise<void>((resolve) => { finir = resolve; });
    const depot = {
      lire: (cle: string) => memoire.lire(cle), ecrire: (cle: string, valeur: string) => memoire.ecrire(cle, valeur),
      supprimer: (cle: string) => memoire.supprimer(cle),
      async supprimerParPrefixe(prefixe: string) { commencer(); await attente; await memoire.supprimerParPrefixe(prefixe); },
    };
    const pending = appliquerLecture(ETAT, CONFIGURATION, {
      configurationCourante: () => courant,
      synchroniserCaches: (etat, valide) => synchroniserCaches(depot, etat, valide),
      definirEtat: jest.fn(),
    });
    await purger;
    courant = { ...CONFIGURATION, jeton: "jeton-2" };
    finir();
    expect(await pending).toBe(false);
    expect(await memoire.lire(CLE_PROPRIETAIRE_DES_CACHES)).toBe(JSON.stringify({ personne: "ancienne", role: "employee" }));
    expect(await memoire.lire(`${PREFIXES_DES_CACHES_PAR_PERSONNE[0]}cache-a`)).toBeNull();
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
