import { VERDICT_REPONSE_ILLISIBLE, VERDICT_REPONSE_TRONQUEE } from "../protocole/enveloppeOutil";
import {
  ETATS_INTERVENTION_M4,
  ETATS_TERMINAUX_M4,
  construireArgumentsDemarrerRoute,
  estInterventionM4,
  interpreterResultatDemarrerRoute,
  interpreterResultatListerInterventions,
  interpreterResultatStatutIntervention,
} from "./interventions";

describe("les statuts d'une intervention (etats.py, ETATS)", () => {
  test("neuf statuts, dans l'ordre du serveur, `a_planifier` en dernier (additif, PLAN T4.10-b)", () => {
    expect(ETATS_INTERVENTION_M4).toEqual([
      "planifiee",
      "en_route",
      "sur_site",
      "en_revue",
      "reportee",
      "completed_pending_review",
      "completed_verified",
      "annulee",
      "a_planifier",
    ]);
    expect(new Set(ETATS_INTERVENTION_M4).size).toBe(ETATS_INTERVENTION_M4.length);
  });

  test("une intervention à planifier est une intervention lisible ; elle n'est pas un état terminal", () => {
    expect(estInterventionM4({ intervention_id: "I1", statut: "a_planifier", lead_id: "L1", service: "gouttieres", devis_id: "D1" })).toBe(true);
    expect(ETATS_TERMINAUX_M4).not.toContain("a_planifier");
  });
});

describe("estInterventionM4 : nature des travaux selon la version du lead (PLAN T0.13-b)", () => {
  const base = { intervention_id: "I1", statut: "planifiee", lead_id: "L1", devis_id: null };

  test("lead v1 : `type_travaux` seul est lisible", () => {
    expect(estInterventionM4({ ...base, type_travaux: "extension" })).toBe(true);
  });

  test("lead v2 : `service` seul est lisible (l'intervention n'est pas écartée de « chantiers du jour »)", () => {
    expect(estInterventionM4({ ...base, service: "gouttieres" })).toBe(true);
  });

  test("les deux clés, ou aucune : pas une intervention lisible (jamais l'une déduite de l'autre)", () => {
    expect(estInterventionM4({ ...base, type_travaux: "extension", service: "gouttieres" })).toBe(false);
    expect(estInterventionM4({ ...base })).toBe(false);
  });

  test("une nature de travaux qui n'est pas une chaîne n'est pas lisible", () => {
    expect(estInterventionM4({ ...base, service: 3 })).toBe(false);
    expect(estInterventionM4({ ...base, type_travaux: null })).toBe(false);
  });

  test("la liste d'un employé garde les deux versions côte à côte", () => {
    const brut = {
      ok: true,
      resultat: [
        { ...base, intervention_id: "I1", type_travaux: "extension" },
        { ...base, intervention_id: "I2", service: "revetement" },
      ],
    };
    const resultat = interpreterResultatListerInterventions(brut);
    expect(resultat).toEqual({ ok: true, interventions: brut.resultat });
  });
});

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

  test("échec technique (ok:false, ex. statut hors énuméré) -> un refus, son verdict, jamais une liste inventée", () => {
    const resultat = interpreterResultatListerInterventions({
      ok: false,
      erreur: "refus_metier",
      details: "statut inconnu",
    });
    expect(resultat).toEqual({ ok: false, genre: "refus", verdict: { code: "refus_metier", detail: "statut inconnu" } });
  });

  test("details sous forme de tableau (arguments_invalides) sont joints en une chaîne lisible", () => {
    const resultat = interpreterResultatListerInterventions({
      ok: false,
      erreur: "arguments_invalides",
      details: ["champ manquant : statut", "type invalide"],
    });
    expect(resultat).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "arguments_invalides", detail: "champ manquant : statut; type invalide" },
    });
  });

  test("l'état passager de l'instance (outil pas déployé, budget) est une panne, pas un refus : un cache peut servir", () => {
    for (const code of ["outil_inconnu", "departement_appelant_inconnu", "budget_epuise"]) {
      expect(interpreterResultatListerInterventions({ ok: false, erreur: code, details: "instance" })).toEqual({
        ok: false,
        genre: "technique",
        verdict: { code, detail: "instance" },
      });
    }
  });
});

describe("interpreterResultatListerInterventions : une réponse tronquée n'est ni une liste vide ni une liste complète (PLAN T1.4-n)", () => {
  // La forme exacte de `Capacites._tronquer` : `ok` de la réponse, `tronque`, un aperçu — et PAS de `resultat`.
  const TRONQUEE = { ok: true, tronque: true, apercu: '[{"intervention_id": "b933c5c55afdb2c1e903895188cb89e6ee59439a045e27b83f9201a81c4438f6", "statut"' };

  test("la réponse coupée par le socle : un échec `tronquee`, jamais `interventions: []`", () => {
    const resultat = interpreterResultatListerInterventions(TRONQUEE);
    expect(resultat).toEqual({ ok: false, genre: "tronquee", verdict: VERDICT_REPONSE_TRONQUEE });
    expect(resultat).not.toHaveProperty("interventions");
  });

  test("l'aperçu n'est JAMAIS lu comme la liste, même s'il ressemble à une liste bien formée", () => {
    const apercuBienForme = { ok: true, tronque: true, apercu: JSON.stringify([{ intervention_id: "I1" }]), resultat: [{ intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "x", devis_id: null }] };
    expect(interpreterResultatListerInterventions(apercuBienForme)).toMatchObject({ ok: false, genre: "tronquee" });
  });

  test("`tronque` faux ou absent : la liste se lit normalement", () => {
    const liste = [{ intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "x", devis_id: null }];
    expect(interpreterResultatListerInterventions({ ok: true, tronque: false, resultat: liste })).toEqual({ ok: true, interventions: liste });
  });

  test.each([
    ["un résultat nul", { ok: true, resultat: null }],
    ["un résultat absent", { ok: true }],
    ["un résultat qui est un objet", { ok: true, resultat: { intervention_id: "I1" } }],
    ["un résultat qui est un texte", { ok: true, resultat: "aucune" }],
    ["une enveloppe sans `ok`", { resultat: [] }],
    ["une enveloppe dont `ok` n'est pas un booléen", { ok: "oui", resultat: [] }],
    ["une enveloppe qui est une liste", []],
    ["une enveloppe nulle", null],
    ["une enveloppe absente", undefined],
    ["une enveloppe qui est un texte", "texte"],
  ])("%s : forme inconnue, `illisible` — jamais « aucune intervention »", (_nom, brut) => {
    expect(interpreterResultatListerInterventions(brut)).toEqual({ ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE });
  });

  test("une liste vraiment vide est une liste vide : le serveur dit qu'il n'y a rien", () => {
    expect(interpreterResultatListerInterventions({ ok: true, resultat: [] })).toEqual({ ok: true, interventions: [] });
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

  test("échec technique -> un refus, avec son verdict", () => {
    const resultat = interpreterResultatStatutIntervention({
      ok: false,
      erreur: "arguments_invalides",
      details: ["intervention_id manquant"],
    });
    expect(resultat).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "arguments_invalides", detail: "intervention_id manquant" },
    });
  });

  test("l'identité que la base ne confirme plus est un refus ; l'état passager de l'instance est une panne", () => {
    expect(
      interpreterResultatStatutIntervention({ ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : rôle retiré" }),
    ).toMatchObject({ ok: false, genre: "refus" });
    expect(interpreterResultatStatutIntervention({ ok: false, erreur: "budget_epuise", details: "trop" })).toMatchObject({
      ok: false,
      genre: "technique",
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
