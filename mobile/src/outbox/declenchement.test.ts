import { creerDeclencheurVidange } from "./declenchement";
import type { RapportVidange, Vidangeur } from "./vidangeur";

const RAPPORT_VIDE: RapportVidange = {
  envoyees: [],
  resultatsAcceptes: [],
  remisesEnAttente: [],
  echecsPermanents: [],
  bloquees: [],
  quarantaine: [],
  arret: null,
  ignoreeVerrouActif: false,
};

function vidangeurQuiRend(rapport: RapportVidange): { vidangeur: Vidangeur; passes: jest.Mock } {
  const passes = jest.fn().mockResolvedValue(rapport);
  return { vidangeur: { vidangerFileSortante: passes }, passes };
}

describe("creerDeclencheurVidange", () => {
  test("sans session : null, le vidangeur n'est même pas construit, aucun refus signalé", async () => {
    const obtenirVidangeur = jest.fn();
    const signalerRefus = jest.fn();
    const declencher = creerDeclencheurVidange({ sessionDisponible: () => false, obtenirVidangeur, signalerRefus });

    await expect(declencher()).resolves.toBeNull();
    expect(obtenirVidangeur).not.toHaveBeenCalled();
    expect(signalerRefus).not.toHaveBeenCalled();
  });

  test("avec session : une passe, le rapport est rendu tel quel, aucun signal si tout va bien", async () => {
    const { vidangeur, passes } = vidangeurQuiRend({ ...RAPPORT_VIDE, envoyees: ["m1"] });
    const signalerRefus = jest.fn();
    const declencher = creerDeclencheurVidange({
      sessionDisponible: () => true,
      obtenirVidangeur: async () => vidangeur,
      signalerRefus,
    });

    const rapport = await declencher();

    expect(passes).toHaveBeenCalledTimes(1);
    expect(rapport?.envoyees).toEqual(["m1"]);
    expect(signalerRefus).not.toHaveBeenCalled();
  });

  test("le serveur refuse l'appareil : le refus est signalé UNE fois, la passe n'est pas relancée", async () => {
    const { vidangeur, passes } = vidangeurQuiRend({
      ...RAPPORT_VIDE,
      arret: { genre: "appareil_refuse", mutationId: "m1", status: 401, message: "Unauthorized" },
    });
    const signalerRefus = jest.fn();
    const declencher = creerDeclencheurVidange({
      sessionDisponible: () => true,
      obtenirVidangeur: async () => vidangeur,
      signalerRefus,
    });

    const rapport = await declencher();

    expect(signalerRefus).toHaveBeenCalledTimes(1);
    expect(passes).toHaveBeenCalledTimes(1); // pas de boucle : le signal ne relance rien
    expect(rapport?.arret?.genre).toBe("appareil_refuse");
  });

  test.each([{ genre: "sans_session" }, { genre: "session_changee" }] as const)(
    "un arrêt %s n'est pas un refus d'appareil : rien n'est signalé",
    async (arret) => {
      const { vidangeur } = vidangeurQuiRend({ ...RAPPORT_VIDE, arret });
      const signalerRefus = jest.fn();
      const declencher = creerDeclencheurVidange({
        sessionDisponible: () => true,
        obtenirVidangeur: async () => vidangeur,
        signalerRefus,
      });

      await declencher();

      expect(signalerRefus).not.toHaveBeenCalled();
    },
  );

  test("une panne de stockage n'est pas avalée : elle remonte à l'appelant", async () => {
    const declencher = creerDeclencheurVidange({
      sessionDisponible: () => true,
      obtenirVidangeur: async () => {
        throw new Error("SQLite illisible");
      },
      signalerRefus: jest.fn(),
    });

    await expect(declencher()).rejects.toThrow("SQLite illisible");
  });
});
