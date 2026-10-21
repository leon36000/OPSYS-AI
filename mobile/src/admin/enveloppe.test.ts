import { ERREURS_PASSAGERES, interpreter, ouvrirEnveloppe } from "./enveloppe";
import { enveloppeCouple, enveloppeDirecte, enveloppeEnErreur, enveloppeRefusee, reponse } from "./donneesDeTest";

describe("l'enveloppe d'un outil de forme `couple` (depuis_couple)", () => {
  test("une lecture acceptée rend la valeur sous `resultat.resultat`", () => {
    const ouverte = ouvrirEnveloppe(reponse("prevision"), "couple");
    expect(ouverte.ok && (ouverte.valeur as { type: string }).type).toBe("PREVISION_TRESORERIE");
  });

  test("un refus de l'outil est un refus, avec son verdict tel quel (ce qui manque)", () => {
    expect(ouvrirEnveloppe(reponse("prevision_horizon_a_declarer"), "couple")).toEqual({
      ok: false,
      genre: "refus",
      verdict: {
        code: "REJ-PREVISION-HORIZON-A-CONFIGURER",
        detail: expect.stringContaining("aucun horizon n'est supposé"),
      },
    });
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "ok"],
    ["une liste", []],
    ["sans `ok`", { resultat: { accepte: true, resultat: {} } }],
    ["`ok: true` sans résultat", { ok: true }],
    ["`accepte` absent", { ok: true, resultat: { resultat: {} } }],
    ["`accepte: true` sans donnée", { ok: true, resultat: { accepte: true } }],
    ["`accepte: true` avec une donnée nulle", { ok: true, resultat: { accepte: true, resultat: null } }],
    ["`accepte` qui n'est pas un booléen", { ok: true, resultat: { accepte: "oui", resultat: {} } }],
  ])("%s : illisible, jamais une lecture", (_nom, brut) => {
    expect(ouvrirEnveloppe(brut, "couple")).toMatchObject({ ok: false, genre: "illisible", verdict: { code: "reponse_illisible" } });
  });
});

describe("l'enveloppe d'un outil de forme directe", () => {
  test("la valeur est celle de `resultat`, qu'elle soit un objet ou une liste", () => {
    const vue = ouvrirEnveloppe(reponse("vue_executive"), "directe");
    expect(vue.ok && (vue.valeur as { vue: string }).vue).toBe("executive");
    const liste = ouvrirEnveloppe(reponse("interventions_planifiee"), "directe");
    expect(liste.ok && Array.isArray(liste.valeur) && liste.valeur.length).toBe(2);
    const videe = ouvrirEnveloppe(reponse("interventions_planifiee_vide"), "directe");
    expect(videe).toEqual({ ok: true, valeur: [] });
  });

  test("M5 refuse par `accepte: false` même en forme directe : un refus, avec son verdict", () => {
    expect(ouvrirEnveloppe(reponse("refus_identite_tresorerie"), "directe")).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" },
    });
  });

  test.each([
    ["sans résultat", { ok: true }],
    ["résultat nul", { ok: true, resultat: null }],
    ["`ok` qui n'est pas vrai", { resultat: {} }],
    ["un texte", "réponse"],
  ])("%s : illisible", (_nom, brut) => {
    expect(ouvrirEnveloppe(brut, "directe")).toMatchObject({ ok: false, genre: "illisible" });
  });
});

describe("les échecs de l'enveloppe du socle : refus ou panne passagère", () => {
  test("`refus_metier` (personne désactivée) est un refus : aucun cache ne le remplace", () => {
    expect(ouvrirEnveloppe(reponse("refus_identite_vue_executive"), "directe")).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "refus_metier", detail: expect.stringContaining("REJ-IDENTITE-APPAREIL-INVALIDE") },
    });
  });

  test("`arguments_invalides` : un refus, et la liste des détails est mise bout à bout", () => {
    const ouverte = ouvrirEnveloppe(reponse("interventions_statut_inconnu"), "directe");
    expect(ouverte).toMatchObject({ ok: false, genre: "refus", verdict: { code: "arguments_invalides" } });
    expect(!ouverte.ok && ouverte.verdict.detail).toContain("valeur hors liste");
    expect(!ouverte.ok && ouverte.verdict.detail).not.toContain("[object");
    const deux = ouvrirEnveloppe(enveloppeEnErreur("arguments_invalides", ["a", "b"]), "couple");
    expect(!deux.ok && deux.verdict.detail).toBe("a ; b");
  });

  test.each(["hors_portee_role", "mutation_conflit", "meta_invalide", "code_que_personne_ne_connait"])(
    "%s : un refus (le serveur a répondu non)",
    (code) => {
      expect(ouvrirEnveloppe(enveloppeEnErreur(code, "d"), "directe")).toMatchObject({ ok: false, genre: "refus", verdict: { code } });
    },
  );

  test("une enveloppe `ok: false` sans code lisible est un refus `erreur_inconnue`, jamais une panne", () => {
    expect(ouvrirEnveloppe({ ok: false }, "couple")).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "erreur_inconnue", detail: "" },
    });
    expect(ouvrirEnveloppe({ ok: false, erreur: "" }, "couple")).toMatchObject({ verdict: { code: "erreur_inconnue" } });
  });

  test("l'état de l'instance (outil pas déployé, budget) est une panne passagère : un cache peut servir", () => {
    expect([...ERREURS_PASSAGERES].sort()).toEqual(["budget_epuise", "departement_appelant_inconnu", "outil_inconnu"]);
    for (const code of ERREURS_PASSAGERES) {
      expect(ouvrirEnveloppe(enveloppeEnErreur(code, "instance"), "directe")).toMatchObject({ ok: false, genre: "technique", verdict: { code } });
    }
  });

  test("une sortie tronquée n'est pas la donnée : panne, et l'aperçu n'est jamais lu comme elle", () => {
    const tronquee = { ok: true, tronque: true, apercu: '{"vue": "exec' };
    expect(ouvrirEnveloppe(tronquee, "directe")).toMatchObject({ ok: false, genre: "technique", verdict: { code: "reponse_tronquee" } });
    expect(ouvrirEnveloppe(tronquee, "couple")).toMatchObject({ ok: false, genre: "technique", verdict: { code: "reponse_tronquee" } });
  });
});

describe("interpreter : ouvrir l'enveloppe, puis lire la valeur", () => {
  test("un lecteur qui ne comprend pas la valeur rend une réponse illisible", () => {
    expect(interpreter(enveloppeDirecte({ x: 1 }), "directe", () => null)).toMatchObject({ ok: false, genre: "illisible" });
  });

  test("un lecteur qui comprend rend sa valeur", () => {
    expect(interpreter(enveloppeCouple({ x: 1 }), "couple", (v) => (v as { x: number }).x)).toEqual({ ok: true, valeur: 1 });
  });

  test("le lecteur n'est jamais appelé sur un refus", () => {
    const lecteur = jest.fn(() => 1);
    expect(interpreter(enveloppeRefusee("REJ-X", "d"), "couple", lecteur)).toMatchObject({ ok: false, genre: "refus" });
    expect(lecteur).not.toHaveBeenCalled();
  });

  test("une valeur `0` ou une chaîne vide, lues par le lecteur, sont des valeurs (pas « rien »)", () => {
    expect(interpreter(enveloppeDirecte({ v: 1 }), "directe", () => 0)).toEqual({ ok: true, valeur: 0 });
  });
});
