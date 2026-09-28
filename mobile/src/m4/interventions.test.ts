import {
  construireArgumentsDemarrerRoute,
  interpreterResultatDemarrerRoute,
  interpreterResultatListerInterventions,
  interpreterResultatStatutIntervention,
} from "./interventions";

describe("interpreterResultatListerInterventions", () => {
  test("enveloppe ok avec un tableau : renvoie les interventions telles quelles", () => {
    const brut = {
      ok: true,
      resultat: [
        { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: "D1" },
        { intervention_id: "I2", statut: "en_route", lead_id: "L2", type_travaux: "revetement", devis_id: null },
      ],
    };
    const resultat = interpreterResultatListerInterventions(brut);
    expect(resultat).toEqual({ ok: true, interventions: brut.resultat });
  });

  test("filtre les entrées mal formées plutôt que de planter (lecture défensive)", () => {
    const brut = {
      ok: true,
      resultat: [
        { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: null },
        { intervention_id: "I2" /* champs manquants */ },
        "pas un objet",
      ],
    };
    const resultat = interpreterResultatListerInterventions(brut);
    expect(resultat.ok).toBe(true);
    if (resultat.ok) {
      expect(resultat.interventions).toHaveLength(1);
      expect(resultat.interventions[0].intervention_id).toBe("I1");
    }
  });

  test("resultat qui n'est pas un tableau -> liste vide, jamais un plantage", () => {
    const resultat = interpreterResultatListerInterventions({ ok: true, resultat: null });
    expect(resultat).toEqual({ ok: true, interventions: [] });
  });

  test("échec technique (ok:false, ex. statut hors énuméré) -> verdict, jamais une liste inventée", () => {
    const resultat = interpreterResultatListerInterventions({
      ok: false,
      erreur: "refus_metier",
      details: "statut inconnu",
    });
    expect(resultat).toEqual({ ok: false, verdict: { code: "refus_metier", detail: "statut inconnu" } });
  });

  test("details sous forme de tableau (arguments_invalides) sont joints en une chaîne lisible", () => {
    const resultat = interpreterResultatListerInterventions({
      ok: false,
      erreur: "arguments_invalides",
      details: ["champ manquant : statut", "type invalide"],
    });
    expect(resultat).toEqual({
      ok: false,
      verdict: { code: "arguments_invalides", detail: "champ manquant : statut; type invalide" },
    });
  });

  test("entrée totalement inattendue (pas un objet) -> liste vide plutôt qu'un plantage", () => {
    expect(interpreterResultatListerInterventions(undefined)).toEqual({ ok: true, interventions: [] });
    expect(interpreterResultatListerInterventions("texte")).toEqual({ ok: true, interventions: [] });
  });
});

describe("interpreterResultatStatutIntervention", () => {
  test("statut connu", () => {
    const resultat = interpreterResultatStatutIntervention({
      ok: true,
      resultat: { intervention_id: "I1", statut: "sur_site" },
    });
    expect(resultat).toEqual({ ok: true, intervention_id: "I1", statut: "sur_site" });
  });

  test("statut null (intervention inconnue) N'EST PAS une erreur", () => {
    const resultat = interpreterResultatStatutIntervention({
      ok: true,
      resultat: { intervention_id: "I-inconnue", statut: null },
    });
    expect(resultat).toEqual({ ok: true, intervention_id: "I-inconnue", statut: null });
  });

  test("échec technique -> verdict", () => {
    const resultat = interpreterResultatStatutIntervention({
      ok: false,
      erreur: "arguments_invalides",
      details: ["intervention_id manquant"],
    });
    expect(resultat).toEqual({
      ok: false,
      verdict: { code: "arguments_invalides", detail: "intervention_id manquant" },
    });
  });
});

describe("interpreterResultatDemarrerRoute", () => {
  test("accepté : renvoie l'accusé de transition", () => {
    const accuse = {
      intervention_id: "I1",
      ligne_id: "L1",
      statut: "en_route",
      statut_precedent: "planifiee",
      empreinte_maillon: "abc",
      tete_chaine: "def",
      horodatage: "2026-09-28T08:00:00-04:00",
    };
    const resultat = interpreterResultatDemarrerRoute({ ok: true, resultat: { accepte: true, resultat: accuse } });
    expect(resultat).toEqual({ accepte: true, resultat: accuse });
  });

  test("rejet métier (ex. REJ-TRANSITION-ILLEGALE) : jamais un succès silencieux", () => {
    const resultat = interpreterResultatDemarrerRoute({
      ok: true,
      resultat: {
        accepte: false,
        verdict: { code: "REJ-TRANSITION-ILLEGALE", statut: "en_route", detail: "transition non autorisée" },
      },
    });
    expect(resultat).toEqual({
      accepte: false,
      verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "transition non autorisée" },
    });
  });

  test("échec technique (ok:false) -> traité comme un rejet, jamais un succès", () => {
    const resultat = interpreterResultatDemarrerRoute({
      ok: false,
      erreur: "arguments_invalides",
      details: ["technicien_id manquant"],
    });
    expect(resultat).toEqual({
      accepte: false,
      verdict: { code: "arguments_invalides", detail: "technicien_id manquant" },
    });
  });

  test("forme totalement inattendue -> succès sans accusé (même lecture défensive que m4_pointer)", () => {
    expect(interpreterResultatDemarrerRoute({ ok: true, resultat: {} })).toEqual({ accepte: true, resultat: null });
  });
});

describe("construireArgumentsDemarrerRoute", () => {
  test("args exacts, rien de plus", () => {
    expect(construireArgumentsDemarrerRoute("I1", "T1", "2026-09-28T08:00:00-04:00")).toEqual({
      intervention_id: "I1",
      technicien_id: "T1",
      horodatage: "2026-09-28T08:00:00-04:00",
    });
  });
});
