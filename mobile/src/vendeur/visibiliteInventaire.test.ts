import type { ResultatInventaireDevis } from "./chargeurDevis";
import { inventaireVisiblePourPersonne, peutAppliquerReponseInventaire } from "./visibiliteInventaire";

const INVENTAIRE_A: ResultatInventaireDevis = {
  personne: "vendeur.a",
  entrees: [],
  curseurSuivant: null,
  etat: { genre: "serveur", consulteLe: "2026-10-05T12:00:00.000Z" },
};

describe("visibilité d'inventaire après un changement d'identité", () => {
  test("une carte déjà chargée sous l'ancien vendeur est invisible sous le nouveau vendeur", () => {
    expect(inventaireVisiblePourPersonne(INVENTAIRE_A, "vendeur.a")).toBe(true);
    expect(inventaireVisiblePourPersonne(INVENTAIRE_A, "vendeur.b")).toBe(false);
    expect(inventaireVisiblePourPersonne(INVENTAIRE_A, null)).toBe(false);
  });

  test("une réponse différée après bascule de personne et de séquence est rejetée", async () => {
    let personneCourante: string | null = "vendeur.a";
    let sequenceCourante = 7;
    let terminer!: (valeur: ResultatInventaireDevis) => void;
    const reponse = new Promise<ResultatInventaireDevis>((resolve) => {
      terminer = resolve;
    });
    const resultatProtege = reponse.then((valeur) =>
      peutAppliquerReponseInventaire(
        valeur.personne,
        personneCourante,
        7,
        sequenceCourante,
      )
        ? valeur
        : null,
    );

    personneCourante = "vendeur.b";
    sequenceCourante += 1;
    terminer(INVENTAIRE_A);

    expect(await resultatProtege).toBeNull();
    expect(peutAppliquerReponseInventaire("vendeur.a", "vendeur.a", 7, 8)).toBe(false);
  });
});
