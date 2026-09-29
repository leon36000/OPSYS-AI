import { appel, reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import {
  construireArgumentsDigest,
  construireArgumentsListerInterventions,
  construireArgumentsPreparation,
  lireDigest,
  lireInterventions,
  lirePreparation,
  OUTIL_LISTER_INTERVENTIONS,
  OUTIL_PRODUIRE_DIGEST,
  OUTIL_VERIFIER_PREPARATION,
  STATUTS_DE_VOLET,
  STATUTS_DU_DISPATCH,
  STATUTS_PREPARABLES,
  TYPES_DE_DEMANDE_DE_REVUE,
  VERDICTS_DE_PREPARATION,
  VOLETS_DE_PREPARATION,
} from "./dispatch";
import type { DigestDuJour, InterventionsLues, Preparation } from "./dispatch";
import { ETATS_INTERVENTION_M4 } from "./interventions";

function valeurDirecte(nom: string): any {
  return reponse(nom).resultat;
}
function valeurCouple(nom: string): any {
  return reponse(nom).resultat.resultat;
}

function groupe(statut: string): InterventionsLues {
  const lu = lireInterventions(valeurDirecte(`interventions_${statut}`), statut);
  if (lu === null) {
    throw new Error(`le groupe « ${statut} » devrait être lisible`);
  }
  return lu;
}

describe("les noms, les catalogues et les arguments", () => {
  test("le nom nu des trois outils", () => {
    expect([OUTIL_LISTER_INTERVENTIONS, OUTIL_VERIFIER_PREPARATION, OUTIL_PRODUIRE_DIGEST]).toEqual([
      "m4_lister_interventions",
      "m4_verifier_preparation",
      "m4_produire_digest",
    ]);
  });

  test("le dispatch demande sept statuts, un appel chacun : ce qui se passe, ce qui est planifié, le reporté et la file de revue", () => {
    expect(STATUTS_DU_DISPATCH).toEqual([
      "en_route",
      "sur_site",
      "en_revue",
      "planifiee",
      "a_planifier",
      "reportee",
      "completed_pending_review",
    ]);
    // L'historique n'est jamais demandé : ni terminé vérifié, ni annulé.
    expect(STATUTS_DU_DISPATCH).not.toContain("completed_verified");
    expect(STATUTS_DU_DISPATCH).not.toContain("annulee");
    expect(new Set(STATUTS_DU_DISPATCH).size).toBe(STATUTS_DU_DISPATCH.length);
  });

  test("la préparation n'a de sens qu'avant le départ, et ses volets sont ceux de M4, dans son ordre", () => {
    expect(STATUTS_PREPARABLES).toEqual(["a_planifier", "planifiee", "reportee"]);
    expect(VOLETS_DE_PREPARATION).toEqual(["soumission", "adresse", "equipe", "materiel", "meteo"]);
    expect(STATUTS_DE_VOLET).toEqual(["ok", "manque", "non_verifiable"]);
    expect(VERDICTS_DE_PREPARATION).toEqual(["pret", "bloque", "non_verifiable"]);
    expect(TYPES_DE_DEMANDE_DE_REVUE).toEqual(["ecart_metier", "anomalie_pointage"]);
  });

  test("chaque statut préparable est un statut du dispatch : le bouton « Préparation » n'apparaît que sur un groupe demandé", () => {
    for (const statut of STATUTS_PREPARABLES) {
      expect(STATUTS_DU_DISPATCH).toContain(statut);
    }
  });

  test("les arguments : un statut ; un numéro d'intervention ; un jour et un instant de référence. Jamais une personne.", () => {
    expect(construireArgumentsListerInterventions("planifiee")).toEqual({ statut: "planifiee" });
    expect(construireArgumentsPreparation("abc")).toEqual({ intervention_id: "abc" });
    expect(construireArgumentsDigest("2026-09-21", "2026-09-21T18:00:00-04:00")).toEqual({
      date_cible: "2026-09-21",
      horodatage_reference: "2026-09-21T18:00:00-04:00",
    });
    for (const args of [construireArgumentsListerInterventions("a_planifier"), construireArgumentsPreparation("x"), construireArgumentsDigest("2026-09-21", "t")]) {
      for (const interdit of ["technicien_id", "personne", "role", "appareil"]) {
        expect(Object.keys(args)).not.toContain(interdit);
      }
    }
  });

  test("les statuts du dispatch sont des statuts connus de l'app pour l'employé, sauf `a_planifier`, que seul le dispatch connaît", () => {
    const inconnus = STATUTS_DU_DISPATCH.filter((s) => !(ETATS_INTERVENTION_M4 as readonly string[]).includes(s));
    expect(inconnus).toEqual(["a_planifier"]);
  });
});

describe("m4_lister_interventions par statut, tel que le moteur le rend", () => {
  test("les planifiées : un lead v1 (type de travaux) et un lead v2 (service), l'assignation dite par le serveur, aucune fenêtre", () => {
    const lu = groupe("planifiee");

    expect(lu.statut).toBe("planifiee");
    expect(lu.illisibles).toBe(0);
    expect(lu.interventions.map((i) => [i.leadId, i.travaux, i.devisId, i.technicienAssigne, i.fenetrePlanifiee])).toEqual([
      ["LEAD-ADM-C-fictif", { genre: "type_travaux", valeur: "renovation_totale" }, "DEVIS-ADM-C-fictif", "etienne", null],
      ["LEAD-ADM-B-fictif", { genre: "service", valeur: "gouttieres" }, "DEVIS-ADM-B-fictif", "etienne", null],
    ]);
    expect(lu.interventions.every((i) => i.statut === "planifiee" && i.interventionId.length === 64)).toBe(true);
  });

  test("à planifier : l'intervention née du devis accepté, PERSONNE d'assigné (dit par le serveur, pas deviné)", () => {
    const [d] = groupe("a_planifier").interventions;
    expect(d).toMatchObject({ leadId: "LEAD-ADM-D-fictif", travaux: { genre: "service", valeur: "gouttieres" }, technicienAssigne: null });
  });

  test("la file de revue : la complétion à vérifier", () => {
    const [a] = groupe("completed_pending_review").interventions;
    expect(a).toMatchObject({ leadId: "LEAD-ADM-A-fictif", devisId: "DEVIS-ADM-A-fictif", technicienAssigne: "etienne" });
  });

  test("un groupe vide est une liste vide (le serveur dit « aucune »), pas une erreur", () => {
    for (const statut of ["en_route", "sur_site", "en_revue", "reportee"]) {
      expect(groupe(statut)).toEqual({ statut, interventions: [], illisibles: 0 });
    }
    expect(lireInterventions(valeurDirecte("interventions_planifiee_vide"), "planifiee")).toEqual({ statut: "planifiee", interventions: [], illisibles: 0 });
  });

  test("la réponse enregistrée porte bien un appel par statut, avec le seul argument `statut`", () => {
    for (const statut of STATUTS_DU_DISPATCH) {
      expect(appel(`interventions_${statut}`)).toEqual({ outil: OUTIL_LISTER_INTERVENTIONS, args: { statut } });
    }
  });

  test("un statut hors catalogue est un refus du serveur (arguments invalides), jamais une liste vide", () => {
    expect(interpreter(reponse("interventions_statut_inconnu"), "directe", (v) => lireInterventions(v, "inconnu"))).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "arguments_invalides" },
    });
  });

  test("une personne désactivée reçoit un refus, pas une liste", () => {
    expect(interpreter(reponse("refus_identite_interventions"), "directe", (v) => lireInterventions(v, "planifiee"))).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "refus_metier" },
    });
  });
});

describe("ce que la liste des interventions refuse de lire (fail-closed)", () => {
  function lue(modification: (liste: any[]) => void, statut = "planifiee"): InterventionsLues | null {
    const liste = valeurDirecte(`interventions_${statut}`);
    modification(liste);
    return lireInterventions(liste, statut);
  }

  test.each([
    ["ni liste ni rien", null],
    ["un objet", {}],
    ["un texte", "aucune"],
    ["une réponse tronquée lue comme un objet", { tronque: true, apercu: "[" }],
  ])("%s : illisible (jamais « aucune intervention »)", (_nom, valeur) => {
    expect(lireInterventions(valeur, "planifiee")).toBeNull();
  });

  test("une intervention d'un AUTRE statut dans le groupe est comptée illisible : le groupe ne ment pas sur son statut", () => {
    const lu = lue((l) => (l[0].statut = "en_route"));
    expect(lu).toMatchObject({ illisibles: 1 });
    expect(lu?.interventions).toHaveLength(1);
  });

  test.each([
    ["ni service ni type de travaux", (i: any) => delete i.type_travaux],
    ["les deux natures de travaux", (i: any) => (i.service = "gouttieres")],
    ["identifiant absent", (i: any) => delete i.intervention_id],
    ["lead absent", (i: any) => delete i.lead_id],
    ["devis absent (la clé manque)", (i: any) => delete i.devis_id],
    ["assignation absente (la clé manque : on ne dit pas « personne »)", (i: any) => delete i.technicien_assigne],
    ["assignation qui n'est pas un texte", (i: any) => (i.technicien_assigne = 42)],
    ["fenêtre qui n'est ni nulle ni un texte", (i: any) => (i.fenetre_planifiee = { debut: "07:00" })],
    ["statut absent", (i: any) => delete i.statut],
  ])("une intervention avec %s est comptée illisible, l'autre reste lue", (_nom, modification) => {
    const lu = lue((l) => modification(l[0]));
    expect(lu?.illisibles).toBe(1);
    expect(lu?.interventions).toHaveLength(1);
  });

  test("une fenêtre planifiée écrite par le serveur s'affiche telle quelle (jamais une date recalculée)", () => {
    const lu = lue((l) => (l[0].fenetre_planifiee = "2026-10-05T07:00:00-04:00"));
    expect(lu?.interventions[0].fenetrePlanifiee).toBe("2026-10-05T07:00:00-04:00");
  });
});

describe("m4_verifier_preparation, telle que le moteur la rend", () => {
  function preparation(nom: string): Preparation {
    const lue = lirePreparation(valeurCouple(nom));
    if (lue === null) {
      throw new Error(`« ${nom} » devrait être lisible`);
    }
    return lue;
  }

  test("un chantier planifié sans adresse confirmée, sans équipe ni règle météo déclarées : bloqué, volet par volet, avec ce qu'il faut fournir", () => {
    const lue = preparation("preparation_lead_v2");

    expect(lue).toMatchObject({ statutIntervention: "planifiee", verdict: "bloque", pret: false });
    expect(lue.volets.map((v) => [v.nom, v.statut])).toEqual([
      ["soumission", "ok"],
      ["adresse", "manque"],
      ["equipe", "manque"],
      ["materiel", "ok"],
      ["meteo", "manque"],
    ]);
    expect(lue.volets.map((v) => v.nom)).toEqual([...VOLETS_DE_PREPARATION]);
    expect(lue.volets[0]).toMatchObject({ manque: null, detail: "devis accepté DEVIS-ADM-B-fictif" });
    expect(lue.volets[1]).toMatchObject({ manque: "coordonnées manquantes : à confirmer. Aucune localisation confirmée.", detail: "REJ-COORDONNEES-A-CONFIRMER" });
    expect(lue.volets[2].manque).toContain("aucun profil des équipes déclaré");
    expect(lue.volets[3]).toMatchObject({ manque: null, detail: "matériel prêt et réservé (M6, révision 1)" });
    expect(lue.aFournir.map((a) => a.volet)).toEqual(["adresse", "equipe", "meteo"]);
  });

  test("les trois interventions préparables (lead v2, lead v1, née d'un devis) sont bloquées par les mêmes volets, dits par M4", () => {
    for (const nom of ["preparation_lead_v2", "preparation_lead_v1", "preparation_a_planifier"]) {
      const lue = preparation(nom);
      expect(lue.verdict).toBe("bloque");
      expect(lue.pret).toBe(false);
    }
    expect(preparation("preparation_a_planifier").statutIntervention).toBe("a_planifier");
  });

  test("une intervention qui n'est plus à préparer, ou inconnue : un refus de M4, ses mots tels quels", () => {
    expect(interpreter(reponse("preparation_terminee"), "couple", lirePreparation)).toEqual({
      ok: false,
      genre: "refus",
      verdict: {
        code: "REJ-TRANSITION-ILLEGALE",
        detail: "préparation sans objet : l'intervention est completed_pending_review (attendu a_planifier, planifiee, reportee)",
      },
    });
    expect(interpreter(reponse("preparation_inconnue"), "couple", lirePreparation)).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "intervention inexistante" },
    });
  });

  test("un chantier prêt (tous les volets `ok`) : « prêt » seulement quand chaque volet le confirme", () => {
    const brut = valeurCouple("preparation_lead_v2");
    for (const volet of Object.values<any>(brut.volets)) {
      volet.statut = "ok";
      volet.manque = null;
    }
    Object.assign(brut, { statut: "pret", pret: true, a_fournir: [] });
    expect(lirePreparation(brut)).toMatchObject({ verdict: "pret", pret: true, aFournir: [] });
  });

  test("un volet non vérifiable : le verdict est `non_verifiable`, jamais « prêt »", () => {
    const brut = valeurCouple("preparation_lead_v2");
    for (const [nom, volet] of Object.entries<any>(brut.volets)) {
      volet.statut = nom === "meteo" ? "non_verifiable" : "ok";
      volet.manque = nom === "meteo" ? "lead v1 : la météo n'a pas de règle par type de travaux" : null;
    }
    Object.assign(brut, {
      statut: "non_verifiable",
      pret: false,
      a_fournir: [{ volet: "meteo", statut: "non_verifiable", manque: "lead v1 : la météo n'a pas de règle par type de travaux" }],
    });
    const lue = lirePreparation(brut);
    expect(lue).toMatchObject({ verdict: "non_verifiable", pret: false });
    expect(lue?.volets.find((v) => v.nom === "meteo")?.statut).toBe("non_verifiable");
  });
});

describe("ce que la préparation refuse de lire : jamais un « prêt » supposé", () => {
  function modifiee(nom: string, modification: (brut: any) => void): Preparation | null {
    const brut = valeurCouple(nom);
    modification(brut);
    return lirePreparation(brut);
  }

  test.each([
    ["« prêt » alors qu'un volet manque", (b: any) => Object.assign(b, { pret: true, statut: "pret" })],
    // Seuls les volets démentent ce « prêt » : `a_fournir` est vide, `pret` et le verdict s'accordent.
    ["« prêt » sans rien à fournir, mais un volet manque encore", (b: any) => Object.assign(b, { pret: true, statut: "pret", a_fournir: [] })],
    ["`pret` vrai sous un verdict qui n'est pas « pret »", (b: any) => (b.pret = true)],
    ["verdict « pret » avec `pret` faux", (b: any) => (b.statut = "pret")],
    ["verdict inconnu", (b: any) => (b.statut = "presque")],
    ["`pret` n'est pas un booléen", (b: any) => (b.pret = "non")],
    ["un volet au statut inconnu", (b: any) => (b.volets.adresse.statut = "peut-etre")],
    ["un volet sans statut", (b: any) => delete b.volets.adresse.statut],
    ["un volet dont le manque n'est pas un texte", (b: any) => (b.volets.adresse.manque = 3)],
    ["aucun volet", (b: any) => (b.volets = {})],
    ["les volets ne sont pas un objet", (b: any) => (b.volets = [])],
    ["l'intervention manque", (b: any) => delete b.intervention_id],
    ["le statut de l'intervention manque", (b: any) => delete b.statut_intervention],
    ["`a_fournir` n'est pas une liste", (b: any) => (b.a_fournir = "adresse")],
    ["`a_fournir` contient un élément illisible", (b: any) => (b.a_fournir[0] = { volet: "adresse" })],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifiee("preparation_lead_v2", modification)).toBeNull();
  });

  test("un verdict « pret » qui dit encore quoi fournir est une contradiction", () => {
    const brut = valeurCouple("preparation_lead_v2");
    for (const volet of Object.values<any>(brut.volets)) {
      volet.statut = "ok";
      volet.manque = null;
    }
    Object.assign(brut, { statut: "pret", pret: true });
    expect(lirePreparation(brut)).toBeNull(); // `a_fournir` liste encore trois volets
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "prêt"],
    ["une liste", []],
  ])("%s : illisible", (_nom, valeur) => {
    expect(lirePreparation(valeur)).toBeNull();
  });
});

describe("m4_produire_digest, tel que le moteur le rend", () => {
  function digest(nom: string): DigestDuJour {
    const lu = lireDigest(valeurCouple(nom));
    if (lu === null) {
      throw new Error(`« ${nom} » devrait être lisible`);
    }
    return lu;
  }

  test("le digest du jour du chantier terminé : ce qui s'est terminé (durée réelle et écart signalé du serveur), la file de revue", () => {
    const lu = digest("digest");

    expect(lu).toMatchObject({
      dateCible: "2026-09-21",
      horodatageReference: "2026-09-21T18:00:00-04:00",
      enRevue: [],
      countPendingReview: 0,
      bloquees: [],
      illisibles: 0,
    });
    expect(lu.terminees).toEqual([
      {
        interventionId: expect.stringMatching(/^[0-9a-f]{64}$/),
        wctId: expect.stringMatching(/^[0-9a-f]{64}$/),
        dureeReelleMinutes: 180,
        ecartSignale: false,
      },
    ]);
    expect(lu.pendingParType).toEqual([
      { type: "ecart_metier", nombre: 0 },
      { type: "anomalie_pointage", nombre: 0 },
    ]);
    expect(lu.pendingParType.map((p) => p.type)).toEqual([...TYPES_DE_DEMANDE_DE_REVUE]);
  });

  test("un jour sans rien : des listes vides, dites vides", () => {
    expect(digest("digest_vide")).toMatchObject({ terminees: [], enRevue: [], countPendingReview: 0, bloquees: [], illisibles: 0 });
  });

  test("les demandes bloquées en revue : les heures sont celles de M4", () => {
    const brut = valeurCouple("digest");
    brut.interventions_bloquees_en_revue = [{ intervention_id: "i1", demande_id: "d1", heures_ecoulees: 31 }];
    brut.count_pending_review = 1;
    brut.pending_par_type.ecart_metier = 1;
    brut.interventions_en_revue = ["i1"];
    expect(lireDigest(brut)).toMatchObject({
      bloquees: [{ interventionId: "i1", demandeId: "d1", heuresEcoulees: 31 }],
      countPendingReview: 1,
      enRevue: ["i1"],
      pendingParType: [
        { type: "ecart_metier", nombre: 1 },
        { type: "anomalie_pointage", nombre: 0 },
      ],
    });
  });

  test("un appel : le jour et l'instant de l'appareil, rien d'autre", () => {
    expect(appel("digest")).toEqual({
      outil: OUTIL_PRODUIRE_DIGEST,
      args: { date_cible: "2026-09-21", horodatage_reference: "2026-09-21T18:00:00-04:00" },
    });
  });

  function modifie(modification: (brut: any) => void): DigestDuJour | null {
    const brut = valeurCouple("digest");
    modification(brut);
    return lireDigest(brut);
  }

  test.each([
    ["la date cible manque", (b: any) => delete b.date_cible],
    ["l'instant de référence manque", (b: any) => delete b.horodatage_reference],
    ["les terminées ne sont pas une liste", (b: any) => (b.interventions_terminees = {})],
    ["les interventions en revue ne sont pas des textes", (b: any) => (b.interventions_en_revue = [1])],
    ["le compte de la file de revue manque", (b: any) => delete b.count_pending_review],
    ["le compte de la file de revue est négatif", (b: any) => (b.count_pending_review = -1)],
    ["le compte par type n'est pas un objet", (b: any) => (b.pending_par_type = [])],
    ["un compte par type n'est pas un entier", (b: any) => (b.pending_par_type.ecart_metier = "0")],
    ["les bloquées ne sont pas une liste", (b: any) => (b.interventions_bloquees_en_revue = null)],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifie(modification)).toBeNull();
  });

  test("une intervention terminée illisible est comptée, jamais devinée", () => {
    const lu = modifie((b) => {
      b.interventions_terminees[0].duree_reelle_minutes = "180";
    });
    expect(lu?.terminees).toEqual([]);
    expect(lu?.illisibles).toBe(1);
    expect(modifie((b) => delete b.interventions_terminees[0].ecart_signale)?.illisibles).toBe(1);
    expect(modifie((b) => (b.interventions_terminees[0].duree_reelle_minutes = -5))?.illisibles).toBe(1);
  });

  test("une demande bloquée illisible est comptée", () => {
    const lu = modifie((b) => (b.interventions_bloquees_en_revue = [{ intervention_id: "i1", demande_id: "d1" }]));
    expect(lu?.bloquees).toEqual([]);
    expect(lu?.illisibles).toBe(1);
  });

  test("un type de demande que cette version ne connaît pas est gardé tel quel, avec son compte", () => {
    const lu = modifie((b) => (b.pending_par_type.retard_inconnu = 2));
    expect(lu?.pendingParType.at(-1)).toEqual({ type: "retard_inconnu", nombre: 2 });
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "digest"],
    ["une liste", []],
  ])("%s : illisible", (_nom, valeur) => {
    expect(lireDigest(valeur)).toBeNull();
  });
});
