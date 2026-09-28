import { obtenirContextePointageProvisoire } from "./contextePointageProvisoire";

describe("obtenirContextePointageProvisoire", () => {
  test("porte l'appareilId FOURNI par l'appelant, jamais un id généré ici", () => {
    const contexte = obtenirContextePointageProvisoire("appareil-reel-abc123");
    expect(contexte.appareilId).toBe("appareil-reel-abc123");
  });

  test("deux appels avec le même appareilId donnent le même contexte (pur, déterministe)", () => {
    expect(obtenirContextePointageProvisoire("X")).toEqual(obtenirContextePointageProvisoire("X"));
  });

  test("deux appareilId différents ne changent QUE ce champ", () => {
    const a = obtenirContextePointageProvisoire("A");
    const b = obtenirContextePointageProvisoire("B");
    expect(a.appareilId).toBe("A");
    expect(b.appareilId).toBe("B");
    expect({ ...a, appareilId: "" }).toEqual({ ...b, appareilId: "" });
  });

  test("champs provisoires documentés : fenêtre large, ville/sel/référentiel cohérents entre eux", () => {
    const contexte = obtenirContextePointageProvisoire("A");
    expect(contexte.sel).toBe("provisoire-t1.4-d");
    expect(Object.keys(contexte.referentielVilles)).toHaveLength(1);
    expect(new Date(contexte.fenetreTravail.debut).getTime()).toBeLessThan(new Date(contexte.fenetreTravail.fin).getTime());
  });
});
