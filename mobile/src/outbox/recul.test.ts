import { calculerDelaiReculMs, calculerProchaineTentativeA } from "./recul";

describe("calculerDelaiReculMs", () => {
  test.each([
    [0, 1_000],
    [1, 2_000],
    [2, 4_000],
    [3, 8_000],
    [4, 16_000],
    [5, 30_000], // 32s théorique, plafonné à 30s (R12 §4)
    [6, 30_000],
    [50, 30_000],
  ] as const)("tentatives=%i -> %i ms", (tentatives, attendu) => {
    expect(calculerDelaiReculMs(tentatives)).toBe(attendu);
  });

  test("ne descend jamais sous le délai initial, même pour un compteur négatif", () => {
    expect(calculerDelaiReculMs(-3)).toBe(1_000);
  });

  test("tronque un compteur non entier plutôt que de planter", () => {
    expect(calculerDelaiReculMs(2.9)).toBe(calculerDelaiReculMs(2));
  });
});

describe("calculerProchaineTentativeA", () => {
  test("additionne le délai de recul au 'maintenant' injecté, sans appeler Date.now()", () => {
    const maintenant = new Date("2026-09-28T12:00:00.000Z");
    const prochaine = calculerProchaineTentativeA(0, maintenant);
    expect(prochaine.toISOString()).toBe("2026-09-28T12:00:01.000Z");
  });

  test("respecte le plafond de 30s au-delà de la 5e tentative", () => {
    const maintenant = new Date("2026-09-28T12:00:00.000Z");
    const prochaine = calculerProchaineTentativeA(10, maintenant);
    expect(prochaine.getTime() - maintenant.getTime()).toBe(30_000);
  });

  test("est pure : n'altère pas l'objet Date reçu", () => {
    const maintenant = new Date("2026-09-28T12:00:00.000Z");
    const avant = maintenant.getTime();
    calculerProchaineTentativeA(3, maintenant);
    expect(maintenant.getTime()).toBe(avant);
  });
});
