import {
  construireArgumentsDeclarerMateriauxUtilises,
  construireFormulaireMateriauxUtilises,
  construireLigneDeclaree,
  interpreterResultatDeclarerMateriauxUtilises,
  validerRecuDeclarerMateriauxUtilises,
} from "./materiaux";

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

    const args = construireArgumentsDeclarerMateriauxUtilises(formulaire);
    expect(args).toEqual({ wct_id: "W1", formulaire });
  });

  test("n'envoie que wct_id et formulaire : jamais un WCT, jamais un registre", () => {
    const formulaire = construireFormulaireMateriauxUtilises("W1", "I1", "I1", []);
    const args = construireArgumentsDeclarerMateriauxUtilises(formulaire);
    expect(Object.keys(args).sort()).toEqual(["formulaire", "wct_id"]);
  });

  test("le wct_id est TOUJOURS celui du formulaire : une seule source, jamais deux valeurs divergentes", () => {
    const formulaire = construireFormulaireMateriauxUtilises("W-accuse", "I1", "I1", []);
    expect(construireArgumentsDeclarerMateriauxUtilises(formulaire).wct_id).toBe(formulaire.wct_id);
  });
});

// Fixtures RAM fictives ; forme confirmée par contrats_sortie.py, sans faux écho WCT/personne/UUID.
import { creerMutation, soumettreMutation } from "../outbox/mutation";
const LIGNE_FICTIVE = construireLigneDeclaree({ typeLigne: "perte", materiauId: "MAT-FICTIF", quantite: 2, unite: "m" });
function mutationFictive() {
  const formulaire = construireFormulaireMateriauxUtilises("WCT-FICTIF", "INTERVENTION-FICTIVE", "CHANTIER-FICTIF", [LIGNE_FICTIVE]);
  return { ...soumettreMutation(creerMutation({ type: "materials_submit", chantierId: formulaire.intervention_id,
    payload: { ...construireArgumentsDeclarerMateriauxUtilises(formulaire) } }, () => "UUID-FICTIF",
    { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 })), proprietaire: "PERSONNE-FICTIVE" };
}
function confirmationFictive() {
  // Output byte-shape du constructeur Python pur, Q/M6-ACK-INTENTION-r1/confirmation-pure-source-r1.json.
  return { intervention_id: "INTERVENTION-FICTIVE", chantier_id: "CHANTIER-FICTIF", lignes_declarees: [LIGNE_FICTIVE] };
}
function ackFictif() { return { ok: true, resultat: { accepte: true, resultat: confirmationFictive(), registre: { taille: 4, hash_tete: "a".repeat(64) } } }; }
describe("interpreterResultatDeclarerMateriauxUtilises", () => {
  test("accepté -> accepte:true avec le résultat", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises(ackFictif(), mutationFictive());
    expect(resultat).toEqual({ accepte: true, resultat: confirmationFictive() });
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

  test("REJ-WCT-INCONNU (wct_id que M4 n'a jamais publié) affiché tel quel", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-WCT-INCONNU" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-WCT-INCONNU", detail: "" } });
  });

  test("erreur technique -> accepte:false", () => {
    const resultat = interpreterResultatDeclarerMateriauxUtilises({ ok: false, erreur: "invalid_request", details: "formulaire invalide" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "invalid_request", detail: "formulaire invalide" } });
  });
});


describe("ACK M6 — JSON strict et contexte persistant", () => {
  test("ancienne pseudo-confirmation et contexte absent sont inconnus, jamais succès null", () => {
    for (const r of [{ ok: true, resultat: { accepte: true, resultat: { statut: "ok" }, registre: { taille: 4, hash_tete: "h" } } }, ackFictif(), {}, null]) {
      expect(interpreterResultatDeclarerMateriauxUtilises(r)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    }
  });
  test("rejeu booléen réel et tuple source conservé sans ajouter wct_id ou personne", () => {
    const r = { ...ackFictif(), rejoue: true }, attendu = confirmationFictive();
    expect(interpreterResultatDeclarerMateriauxUtilises(r, mutationFictive())).toEqual({ accepte: true, resultat: attendu });
    expect(Object.keys(attendu).sort()).toEqual(["chantier_id", "intervention_id", "lignes_declarees"]);
  });
  test("WCT extérieur du payload doit être celui du formulaire, propriétaire/type/objet concordants", () => {
    const muters = [
      (m: ReturnType<typeof mutationFictive>) => { m.proprietaire = ""; },
      (m: ReturnType<typeof mutationFictive>) => { Reflect.set(m, "type", "punch_in"); },
      (m: ReturnType<typeof mutationFictive>) => { m.chantierId = "AUTRE-INTERVENTION"; },
      (m: ReturnType<typeof mutationFictive>) => { Reflect.set(m.payload, "wct_id", "WCT-AUTRE"); },
      (m: ReturnType<typeof mutationFictive>) => { Reflect.set(m.payload, "registre", { fictif: true }); },
    ];
    for (const muter of muters) { const m = mutationFictive(); muter(m);
      expect(interpreterResultatDeclarerMateriauxUtilises(ackFictif(), m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } }); }
  });
  test("getters/prototypes/symboles/cycles ne déclenchent pas de lecture ou succès", () => {
    let appels = 0; const r = ackFictif(); Object.defineProperty(r.resultat, "resultat", { get: () => { appels++; return confirmationFictive(); } });
    const m = mutationFictive(); Object.defineProperty(m.payload, "formulaire", { get: () => { appels++; return {}; } });
    const proto = Object.create({ ok: true }); Reflect.set(proto, "resultat", ackFictif().resultat);
    const symbol = ackFictif(); Reflect.set(symbol, Symbol("fictif"), true);
    const cycle = ackFictif(); Reflect.set(cycle, "cycle", cycle);
    for (const x of [r, proto, symbol, cycle]) expect(interpreterResultatDeclarerMateriauxUtilises(x, mutationFictive())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    expect(interpreterResultatDeclarerMateriauxUtilises(ackFictif(), m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } }); expect(appels).toBe(0);
  });
  test("résumé envoyé valide lié, null/artifact/partiel/ligne étrangère restent non terminaux", () => {
    const m = { ...mutationFictive(), statut: "envoyee" as const, resumeAccepte: confirmationFictive() };
    expect(validerRecuDeclarerMateriauxUtilises(m)).toBe(true);
    for (const resumeAccepte of [null, "artefact://fictif", { intervention_id: "INTERVENTION-FICTIVE" }, { ...confirmationFictive(), chantier_id: "AUTRE" }]) {
      expect(validerRecuDeclarerMateriauxUtilises({ ...m, resumeAccepte })).toBe(false);
    }
  });
});
