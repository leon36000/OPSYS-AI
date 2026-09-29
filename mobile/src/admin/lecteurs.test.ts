import {
  decimalNullable,
  entierOuNull,
  entierPositifOuNull,
  estDecimal,
  listeDeTextes,
  lireListe,
  texteNullable,
} from "./lecteurs";

describe("lecteurs défensifs", () => {
  test.each(["0", "14106.32", "-500.00", "3.01", "1200.00", "0.00", "12"])("« %s » est un décimal du serveur", (texte) => {
    expect(estDecimal(texte)).toBe(true);
  });

  test.each(["", "abc", "1,5", "1e5", " 1", "1 ", ".5", "5.", "--1", "+1", "1.2.3", "NaN", "Infinity", "0x10"])(
    "« %s » n'est pas un décimal",
    (texte) => {
      expect(estDecimal(texte)).toBe(false);
    },
  );

  test("un nombre n'est jamais un décimal du serveur : les montants restent des textes", () => {
    expect(estDecimal(14106.32)).toBe(false);
    expect(estDecimal(0)).toBe(false);
    expect(estDecimal(null)).toBe(false);
    expect(estDecimal(undefined)).toBe(false);
  });

  test("decimalNullable distingue nul (le serveur dit « pas de valeur ») de mal formé", () => {
    expect(decimalNullable(null)).toBeNull();
    expect(decimalNullable("0.00")).toBe("0.00");
    expect(decimalNullable(undefined)).toBeUndefined();
    expect(decimalNullable(0)).toBeUndefined();
    expect(decimalNullable("")).toBeUndefined();
    expect(decimalNullable("abc")).toBeUndefined();
  });

  test("entiers : positif ou nul seulement, ou relatif pour les jours restants", () => {
    expect(entierPositifOuNull(0)).toBe(0);
    expect(entierPositifOuNull(7)).toBe(7);
    expect([-1, 1.5, "3", null, NaN].map(entierPositifOuNull)).toEqual([null, null, null, null, null]);
    expect(entierOuNull(-34)).toBe(-34);
    expect(entierOuNull(0)).toBe(0);
    expect([1.5, "3", null, NaN, Infinity].map(entierOuNull)).toEqual([null, null, null, null, null]);
  });

  test("texteNullable : un texte non vide, nul, ou mal formé (undefined)", () => {
    expect(texteNullable("a")).toBe("a");
    expect(texteNullable(null)).toBeNull();
    expect(texteNullable("")).toBeUndefined();
    expect(texteNullable("  ")).toBeUndefined();
    expect(texteNullable(3)).toBeUndefined();
    expect(texteNullable(undefined)).toBeUndefined();
  });

  test("listeDeTextes : tout ou rien, jamais une liste à moitié lue", () => {
    expect(listeDeTextes(["a", "b"])).toEqual(["a", "b"]);
    expect(listeDeTextes([])).toEqual([]);
    expect(listeDeTextes(["a", 2])).toBeNull();
    expect(listeDeTextes(["a", ""])).toBeNull();
    expect(listeDeTextes("a")).toBeNull();
    expect(listeDeTextes(null)).toBeNull();
  });

  test("lireListe compte les éléments illisibles au lieu de les deviner", () => {
    const lus = lireListe([1, "x", 3], (e) => (typeof e === "number" ? e * 2 : null));
    expect(lus).toEqual({ items: [2, 6], illisibles: 1 });
    expect(lireListe([], () => 1)).toEqual({ items: [], illisibles: 0 });
    expect(lireListe({}, () => 1)).toBeNull();
    expect(lireListe(null, () => 1)).toBeNull();
  });
});
