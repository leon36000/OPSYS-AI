import {
  ERREURS_PASSAGERES,
  VERDICT_REPONSE_ILLISIBLE,
  VERDICT_REPONSE_TRONQUEE,
  entierOuNull,
  estRefusDeRequete,
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

  test("refus technique (ok:false) : genre refus, détails en liste mis bout à bout", () => {
    const lecture = lireEnveloppeMetier({ ok: false, erreur: "arguments_invalides", details: ["a manque", "b inconnu"] });
    expect(lecture).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "arguments_invalides", detail: "a manque ; b inconnu" },
    });
  });

  test("refus technique sans code : refus erreur_inconnue, jamais une panne qui laisserait relire un cache", () => {
    expect(lireEnveloppeMetier({ ok: false })).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "erreur_inconnue", detail: "" },
    });
    expect(lireEnveloppeMetier({ ok: false, erreur: "" })).toMatchObject({ genre: "refus", verdict: { code: "erreur_inconnue" } });
  });

  // PLAN T1.4-n : « personne désactivée, rôle retiré » arrive en `ok: false` (`refus_metier`) ; avant, cela se lisait
  // « technique » et le cache du vendeur était relu.
  test.each([
    ["refus_metier", "REJ-IDENTITE-APPAREIL-INVALIDE : personne 'sophie' inconnue, inactive, ou ne porte plus le rôle 'seller'"],
    ["hors_portee_role", "cet outil n'est pas dans la portée du rôle"],
    ["meta_invalide", "_meta illisible"],
    ["arguments_invalides", "paramètre inconnu : owner"],
    ["mutation_conflit", "clé déjà utilisée"],
    ["panne_execution", "RuntimeError"],
  ])("`ok: false` %s : un refus de la requête, son verdict tel quel (aucun cache ne le remplace)", (code, details) => {
    expect(lireEnveloppeMetier({ ok: false, erreur: code, details })).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code, detail: details },
    });
  });

  test("l'état passager de l'instance (outil pas déployé, budget) n'est pas un refus : un cache peut servir", () => {
    expect([...ERREURS_PASSAGERES].sort()).toEqual(["budget_epuise", "departement_appelant_inconnu", "outil_inconnu"]);
    for (const code of ERREURS_PASSAGERES) {
      expect(lireEnveloppeMetier({ ok: false, erreur: code, details: "instance" })).toEqual({
        ok: false,
        genre: "technique",
        verdict: { code, detail: "instance" },
      });
    }
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

describe("estRefusDeRequete : le refus de la requête, distinct d'un verdict métier", () => {
  test("`ok: false` qui n'est pas une panne passagère : la requête est refusée", () => {
    expect(estRefusDeRequete({ ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : ..." })).toBe(true);
    expect(estRefusDeRequete({ ok: false, erreur: "hors_portee_role" })).toBe(true);
    expect(estRefusDeRequete({ ok: false })).toBe(true);
  });

  test("une panne passagère de l'instance n'est pas un refus de la requête", () => {
    for (const code of ERREURS_PASSAGERES) {
      expect(estRefusDeRequete({ ok: false, erreur: code })).toBe(false);
    }
  });

  test("un verdict métier (`accepte: false`) n'est pas un refus de la requête : il fait partie de ce qu'on lit", () => {
    expect(estRefusDeRequete({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-CONVERSATION-CLOSE", detail: "" } } })).toBe(false);
  });

  test.each([
    ["une réponse acceptée", { ok: true, resultat: { accepte: true, resultat: { a: 1 } } }],
    ["une sortie tronquée", { ok: true, tronque: true, apercu: "{" }],
    ["null", null],
    ["un tableau", []],
    ["un texte", "ok"],
  ])("%s : ce n'est pas un refus de la requête", (_nom, brut) => {
    expect(estRefusDeRequete(brut)).toBe(false);
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
