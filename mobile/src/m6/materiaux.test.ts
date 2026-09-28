import {
  construireArgumentsDeclarerMateriauxUtilises,
  construireFormulaireMateriauxUtilises,
  construireLigneDeclaree,
  interpreterResultatDeclarerMateriauxUtilises,
} from "./materiaux";

const WCT = { wct_id: "W1", intervention_id: "I1", lead_id: "L1", statut: "completed_pending_review" };

describe("construireLigneDeclaree", () => {
  test("type 'prevu' avec quantite_estimee -> clé incluse", () => {
    const ligne = construireLigneDeclaree({
      typeLigne: "prevu",
      materiauId: "gouttiere-alu-5po",
      quantite: 12,
      unite: "pi",
      quantiteEstimee: 10,
    });
    expect(ligne).toEqual({
      type_ligne: "prevu",
      materiau_id: "gouttiere-alu-5po",
      quantite: 12,
      unite: "pi",
      quantite_estimee: 10,
    });
  });

  test("type 'prevu' sans quantite_estimee fournie -> clé omise, jamais undefined explicite", () => {
    const ligne = construireLigneDeclaree({ typeLigne: "prevu", materiauId: "m1", quantite: 1, unite: "un" });
    expect(ligne).toEqual({ type_ligne: "prevu", materiau_id: "m1", quantite: 1, unite: "un" });
    expect("quantite_estimee" in ligne).toBe(false);
  });

  test("type 'achat_terrain' -> photo_fournie/recu_fourni toujours présents (false par défaut, jamais omis)", () => {
    const ligne = construireLigneDeclaree({ typeLigne: "achat_terrain", materiauId: "vis", quantite: 1, unite: "boite", recuFourni: true });
    expect(ligne).toEqual({ type_ligne: "achat_terrain", materiau_id: "vis", quantite: 1, unite: "boite", photo_fournie: false, recu_fourni: true });
  });

  test("type 'non_prevu'/'retour'/'perte'/'bris' -> aucune clé optionnelle, même si fournie par erreur", () => {
    const ligne = construireLigneDeclaree({
      typeLigne: "retour",
      materiauId: "m1",
      quantite: 2,
      unite: "un",
      quantiteEstimee: 99,
      photoFournie: true,
    });
    expect(ligne).toEqual({ type_ligne: "retour", materiau_id: "m1", quantite: 2, unite: "un" });
  });
});

describe("construireFormulaireMateriauxUtilises / construireArgumentsDeclarerMateriauxUtilises", () => {
  test("assemble wct_id/intervention_id/chantier_id/lignes, jamais de coût ni de prix", () => {
    const lignes = [construireLigneDeclaree({ typeLigne: "non_prevu", materiauId: "clou", quantite: 3, unite: "boite" })];
    const formulaire = construireFormulaireMateriauxUtilises("W1", "I1", "I1", lignes);
    expect(formulaire).toEqual({ wct_id: "W1", intervention_id: "I1", chantier_id: "I1", lignes_materiaux: lignes });
    expect(JSON.stringify(formulaire)).not.toMatch(/cout|prix|price/i);

    const args = construireArgumentsDeclarerMateriauxUtilises(WCT, formulaire);
    expect(args).toEqual({ wct: WCT, formulaire });
  });

  test("le wct voyage VERBATIM, jamais reconstruit champ par champ", () => {
    const wctEtendu = { ...WCT, un_champ_futur_inconnu: "valeur" };
    const args = construireArgumentsDeclarerMateriauxUtilises(wctEtendu, construireFormulaireMateriauxUtilises("W1", "I1", "I1", []));
    expect(args.wct).toBe(wctEtendu);
    expect(args.wct.un_champ_futur_inconnu).toBe("valeur");
  });
});

describe("interpreterResultatDeclarerMateriauxUtilises", () => {
  test("accepté -> accepte:true avec le résultat", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({
      ok: true,
      resultat: { accepte: true, resultat: { statut: "ok" }, registre: { taille: 4, hash_tete: "h" } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { statut: "ok" } });
  });

  test("rejet SANS detail (forme réelle confirmée en lisant outils.py, ligne 649) -> detail vide, jamais un plantage", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE", detail: "" } });
  });

  test("REJ-DECLARATION-DEJA-SOUMISE affiché tel quel", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-DECLARATION-DEJA-SOUMISE" } },
    });
    expect(resultat.accepte).toBe(false);
    if (!resultat.accepte) {
      expect(resultat.verdict.code).toBe("REJ-DECLARATION-DEJA-SOUMISE");
    }
  });

  test("erreur technique -> accepte:false", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({ ok: false, erreur: "invalid_request", details: "formulaire invalide" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "invalid_request", detail: "formulaire invalide" } });
  });
});
