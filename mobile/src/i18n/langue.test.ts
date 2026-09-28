import { LANGUE_PAR_DEFAUT, resoudreLangueDemarrage } from "./langue";

describe("resoudreLangueDemarrage", () => {
  test("aucun tag -> défaut fr-CA", () => {
    expect(resoudreLangueDemarrage([])).toBe(LANGUE_PAR_DEFAUT);
  });

  test("tag fr-CA -> fr-CA", () => {
    expect(resoudreLangueDemarrage(["fr-CA"])).toBe("fr-CA");
  });

  test("tag fr-FR (français hors Canada) -> fr-CA quand même (seul le préfixe compte)", () => {
    expect(resoudreLangueDemarrage(["fr-FR"])).toBe("fr-CA");
  });

  test("tag en-CA -> en-CA", () => {
    expect(resoudreLangueDemarrage(["en-CA"])).toBe("en-CA");
  });

  test("tag en-US -> en-CA (seule variante anglaise supportée)", () => {
    expect(resoudreLangueDemarrage(["en-US"])).toBe("en-CA");
  });

  test("prend le premier tag reconnu dans l'ordre de préférence de l'appareil", () => {
    expect(resoudreLangueDemarrage(["es-MX", "en-US", "fr-CA"])).toBe("en-CA");
  });

  test("langue non supportée (ex. espagnol seul) -> défaut fr-CA", () => {
    expect(resoudreLangueDemarrage(["es-MX"])).toBe(LANGUE_PAR_DEFAUT);
  });

  test("insensible à la casse", () => {
    expect(resoudreLangueDemarrage(["EN-ca"])).toBe("en-CA");
  });
});
