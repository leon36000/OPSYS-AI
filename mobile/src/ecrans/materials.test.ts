import {
  ajouterLigne,
  convertirLigne,
  creerLigneVide,
  evaluerPreparationFormulaire,
  modifierLigne,
  retirerLigne,
  validerLigne,
} from "./materials";
import type { LigneEnSaisie } from "./materials";

function ligne(partiel: Partial<LigneEnSaisie> = {}): LigneEnSaisie {
  return { ...creerLigneVide("l1"), ...partiel };
}

describe("creerLigneVide", () => {
  test("aucune quantité ni prix pré-remplis (mission item 3)", () => {
    const l = creerLigneVide("l1");
    expect(l).toEqual({
      id: "l1",
      typeLigne: "prevu",
      materiauId: "",
      quantiteTexte: "",
      unite: "",
      quantiteEstimeeTexte: "",
      photoFournie: false,
      recuFourni: false,
    });
    expect(JSON.stringify(l)).not.toMatch(/cout|prix|price/i);
  });
});

describe("ajouterLigne / retirerLigne / modifierLigne", () => {
  test("ajoute à la fin, retire par id, modifie un sous-ensemble de champs", () => {
    const l1 = creerLigneVide("l1");
    const l2 = creerLigneVide("l2");
    let lignes = ajouterLigne([], l1);
    lignes = ajouterLigne(lignes, l2);
    expect(lignes.map((l) => l.id)).toEqual(["l1", "l2"]);

    lignes = modifierLigne(lignes, "l1", { materiauId: "gouttiere", unite: "pi" });
    expect(lignes[0]).toMatchObject({ materiauId: "gouttiere", unite: "pi" });
    expect(lignes[1]).toEqual(l2); // l'autre ligne reste inchangée

    lignes = retirerLigne(lignes, "l1");
    expect(lignes.map((l) => l.id)).toEqual(["l2"]);
  });
});

describe("validerLigne / convertirLigne", () => {
  test("ligne vide -> materiau_id_manquant en premier", () => {
    expect(validerLigne(ligne())).toBe("materiau_id_manquant");
  });

  test("materiau saisi mais unité vide -> unite_manquante", () => {
    expect(validerLigne(ligne({ materiauId: "clou" }))).toBe("unite_manquante");
  });

  test("quantité vide ou non numérique -> quantite_invalide", () => {
    expect(validerLigne(ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "" }))).toBe("quantite_invalide");
    expect(validerLigne(ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "abc" }))).toBe("quantite_invalide");
  });

  test("virgule décimale (fr-CA) acceptée pour la quantité", () => {
    expect(validerLigne(ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "3,5" }))).toBeNull();
  });

  test("type 'prevu', quantite_estimee non numérique renseignée -> quantite_estimee_invalide", () => {
    const l = ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "3", quantiteEstimeeTexte: "abc" });
    expect(validerLigne(l)).toBe("quantite_estimee_invalide");
  });

  test("type 'prevu', quantite_estimee vide -> valide (optionnelle)", () => {
    const l = ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "3", quantiteEstimeeTexte: "" });
    expect(validerLigne(l)).toBeNull();
  });

  test("type 'achat_terrain' sans photo ni reçu -> achat_terrain_preuve_manquante", () => {
    const l = ligne({ typeLigne: "achat_terrain", materiauId: "vis", unite: "boite", quantiteTexte: "1" });
    expect(validerLigne(l)).toBe("achat_terrain_preuve_manquante");
  });

  test("type 'achat_terrain' avec au moins une preuve -> valide", () => {
    const l = ligne({ typeLigne: "achat_terrain", materiauId: "vis", unite: "boite", quantiteTexte: "1", recuFourni: true });
    expect(validerLigne(l)).toBeNull();
  });

  test("convertirLigne : ligne invalide -> null, jamais une conversion partielle", () => {
    expect(convertirLigne(ligne())).toBeNull();
  });

  test("convertirLigne : ligne valide -> LigneDeclareeChantierM6 exacte", () => {
    const l = ligne({ materiauId: " clou ", unite: " boite ", quantiteTexte: "3,5" });
    expect(convertirLigne(l)).toEqual({ type_ligne: "prevu", materiau_id: "clou", quantite: 3.5, unite: "boite" });
  });

  test("convertirLigne : quantite_estimee incluse seulement si renseignée et type prevu", () => {
    const l = ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "3", quantiteEstimeeTexte: "2" });
    expect(convertirLigne(l)).toEqual({ type_ligne: "prevu", materiau_id: "clou", quantite: 3, unite: "boite", quantite_estimee: 2 });
  });
});

describe("evaluerPreparationFormulaire", () => {
  test("aucune ligne -> aucune_ligne", () => {
    expect(evaluerPreparationFormulaire("W1", "I1", "I1", [])).toEqual({ pret: false, raison: "aucune_ligne" });
  });

  test("au moins une ligne invalide -> lignes_invalides, aucun formulaire construit", () => {
    const lignes = [ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "1" }), ligne({ id: "l2" })];
    expect(evaluerPreparationFormulaire("W1", "I1", "I1", lignes)).toEqual({ pret: false, raison: "lignes_invalides" });
  });

  test("toutes les lignes valides -> pret avec le formulaire exact, wct_id/intervention_id/chantier_id corrects", () => {
    const lignes = [ligne({ materiauId: "clou", unite: "boite", quantiteTexte: "1" })];
    const resultat = evaluerPreparationFormulaire("W1", "I1", "I1", lignes);
    expect(resultat).toEqual({
      pret: true,
      formulaire: {
        wct_id: "W1",
        intervention_id: "I1",
        chantier_id: "I1",
        lignes_materiaux: [{ type_ligne: "prevu", materiau_id: "clou", quantite: 1, unite: "boite" }],
      },
    });
  });
});
