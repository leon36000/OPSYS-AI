import { creerLigneVide, convertirLigne, validerLigne } from "./materials";
import captures from "../m6/fixturesContexteMateriaux.json";
import { lireContexteMateriaux } from "../m6/contexteMateriaux";
test.each(["9007199254740993", "1.00000000000000000001", "0.100000000000000005", "0", "-1"])('quantité réelle %s ne devient pas une autre valeur envoyable', texte => {
  const l = { ...creerLigneVide("FICTIF"), typeLigne: "perte" as const, materiauId: "SKU-FICTIF", unite: "pi", quantiteTexte: texte };
  expect(validerLigne(l)).toBe("quantite_invalide"); expect(convertirLigne(l)).toBeNull();
});
test('une ligne prévue ne fabrique pas la quantité estimée requise par le serveur', () => {
  const l = { ...creerLigneVide("FICTIF"), materiauId: "SKU-FICTIF", unite: "pi", quantiteTexte: "2,5" };
  expect(validerLigne(l)).toBe("quantite_estimee_invalide"); expect(convertirLigne(l)).toBeNull();
});
test.each(["2,5", ".5", "12.", "00012.2500", "0.0000001"])('saisie décimale exacte %s conservée jusqu’à conversion explicite', texte => {
  const l = { ...creerLigneVide("FICTIF"), typeLigne: "non_prevu" as const, materiauId: "SKU-FICTIF", unite: "pi", quantiteTexte: texte };
  expect(validerLigne(l)).toBeNull(); expect(convertirLigne(l)?.quantite).toBe(Number(texte.replace(",", ".")));
  expect(l.quantiteTexte).toBe(texte);
});
test('un identifiant et une unité source restent verbatim à la déclaration', () => {
  const l = { ...creerLigneVide("FICTIF"), typeLigne: "non_prevu" as const, materiauId: " SKU-FICTIF ", unite: " pi ", quantiteTexte: "2,5" };
  expect(convertirLigne(l)).toMatchObject({ materiau_id: " SKU-FICTIF ", unite: " pi " });
});
test('la vraie capture SQL U+FEFF est déclarable sans changer son identifiant ni son unité', () => {
  const c = captures.captures.find(x => x.phase === "ids-unites-feff-verbatim"); if (!c) throw new Error("Capture réelle absente.");
  const r = lireContexteMateriaux(c.response, c.request.args); if (!r.ok) throw new Error(r.code);
  const source = r.value.lignes[0];
  const l = { ...creerLigneVide("FICTIF"), materiauId: source.materiau_id, unite: source.unite, quantiteTexte: "1", quantiteEstimeeTexte: source.quantite_estimee };
  expect(validerLigne(l)).toBeNull(); expect(convertirLigne(l)).toMatchObject({ materiau_id: source.materiau_id, unite: source.unite });
});
