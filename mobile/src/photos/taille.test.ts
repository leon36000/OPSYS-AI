import { LONG_COTE_CIBLE_PX, choisirTaillePhoto } from "./taille";

describe("choisirTaillePhoto", () => {
  test("choisit la taille dont le plus long côté est le plus proche de la cible", () => {
    expect(choisirTaillePhoto(["640x480", "1920x1080", "4032x3024"])).toBe("1920x1080");
  });

  test("une taille exactement à la cible est choisie", () => {
    expect(choisirTaillePhoto(["1600x1200", "3200x2400"])).toBe("1600x1200");
  });

  test("la hauteur peut être le plus long côté (portrait)", () => {
    expect(choisirTaillePhoto(["480x640", "1080x1920"])).toBe("1080x1920");
  });

  test("liste vide -> null (fail-closed, garde le défaut de l'appareil)", () => {
    expect(choisirTaillePhoto([])).toBeNull();
  });

  test("aucune entrée reconnue -> null", () => {
    expect(choisirTaillePhoto(["invalide", "aussi-invalide"])).toBeNull();
  });

  test("ignore les entrées mal formées, choisit parmi les valides", () => {
    expect(choisirTaillePhoto(["pas-une-taille", "1920x1080"])).toBe("1920x1080");
  });

  test("cible personnalisée", () => {
    expect(choisirTaillePhoto(["640x480", "1920x1080"], 640)).toBe("640x480");
  });

  test("cible par défaut documentée = 1600", () => {
    expect(LONG_COTE_CIBLE_PX).toBe(1600);
  });
});
