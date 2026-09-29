import {
  VERDICT_REPONSE_ILLISIBLE,
  VERDICT_REPONSE_TRONQUEE,
  entierOuNull,
  lireEnveloppeMetier,
  lireVerdict,
  texteOuNull,
} from "./enveloppeOutil";

describe("lireEnveloppeMetier", () => {
  test("réponse acceptée : rend R, la donnée de Y.resultat", () => {
    const lecture = lireEnveloppeMetier({ ok: true, resultat: { accepte: true, resultat: { a: 1 } }, rejoue: false });
    expect(lecture).toEqual({ ok: true, valeur: { a: 1 } });
  });

  test("refus métier : genre refus, verdict du serveur tel quel (code et détail)", () => {
    const lecture = lireEnveloppeMetier({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-LEAD-NON-ASSIGNE", statut: "", detail: "lead inconnu" } },
    });
    expect(lecture).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" },
    });
  });

  test("refus métier sans verdict lisible : code de repli, jamais un succès", () => {
    const lecture = lireEnveloppeMetier({ ok: true, resultat: { accepte: false } });
    expect(lecture).toEqual({ ok: false, genre: "refus", verdict: { code: "refus_inconnu", detail: "" } });
  });

  test("refus technique (ok:false) : genre technique, détails en liste mis bout à bout", () => {
    const lecture = lireEnveloppeMetier({ ok: false, erreur: "arguments_invalides", details: ["a manque", "b inconnu"] });
    expect(lecture).toEqual({
      ok: false,
      genre: "technique",
      verdict: { code: "arguments_invalides", detail: "a manque ; b inconnu" },
    });
  });

  test("refus technique sans code : erreur_inconnue", () => {
    expect(lireEnveloppeMetier({ ok: false })).toEqual({
      ok: false,
      genre: "technique",
      verdict: { code: "erreur_inconnue", detail: "" },
    });
  });

  test("sortie tronquée par le socle : jamais lue comme la donnée, verdict reponse_tronquee", () => {
    const lecture = lireEnveloppeMetier({ ok: true, tronque: true, apercu: '{"accepte": true, "resultat": {"a"' });
    expect(lecture).toEqual({ ok: false, genre: "technique", verdict: VERDICT_REPONSE_TRONQUEE });
  });

  test.each([
    ["null", null],
    ["un tableau", []],
    ["un texte", "ok"],
    ["ok sans resultat", { ok: true }],
    ["resultat sans accepte", { ok: true, resultat: { resultat: { a: 1 } } }],
    ["accepte sans donnée", { ok: true, resultat: { accepte: true } }],
    ["donnée nulle", { ok: true, resultat: { accepte: true, resultat: null } }],
    ["accepte texte", { ok: true, resultat: { accepte: "true", resultat: { a: 1 } } }],
  ])("forme inattendue (%s) : illisible, jamais un succès", (_nom, brut) => {
    expect(lireEnveloppeMetier(brut)).toEqual({ ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE });
  });
});

describe("lecteurs défensifs", () => {
  test("lireVerdict garde le code et le détail, et un repli pour le code seulement", () => {
    expect(lireVerdict({ code: "X", detail: "d", statut: "s" }, "repli")).toEqual({ code: "X", detail: "d" });
    expect(lireVerdict({ code: "", detail: 3 }, "repli")).toEqual({ code: "repli", detail: "" });
    expect(lireVerdict(undefined, "repli")).toEqual({ code: "repli", detail: "" });
  });

  test("texteOuNull refuse le vide et le non-texte", () => {
    expect(texteOuNull("a")).toBe("a");
    expect(texteOuNull("  ")).toBeNull();
    expect(texteOuNull(4)).toBeNull();
  });

  test("entierOuNull n'accepte qu'un entier supérieur ou égal à 0", () => {
    expect(entierOuNull(0)).toBe(0);
    expect(entierOuNull(7)).toBe(7);
    expect(entierOuNull(-1)).toBeNull();
    expect(entierOuNull(1.5)).toBeNull();
    expect(entierOuNull("3")).toBeNull();
    expect(entierOuNull(Number.NaN)).toBeNull();
  });
});
