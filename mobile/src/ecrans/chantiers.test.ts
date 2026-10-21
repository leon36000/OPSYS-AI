import type { GroupeInterventions } from "../admin/chantiers";
import { reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import { lireDigest, lireInterventions, lirePreparation, STATUTS_DU_DISPATCH, STATUTS_PREPARABLES } from "../m4/dispatch";
import type { DigestDuJour, Preparation } from "../m4/dispatch";
import { presenterDigest, presenterGroupes, presenterPreparation, vueDigest, vuePreparation } from "./chantiers";
import { digestDe, duCache, duServeur, interventionsDe, preparationDe } from "./donneesDeVue";
import { texteSansChemin } from "./texteSur";

const DECALAGE = -240;

function groupesDeLaFixture(): GroupeInterventions[] {
  return STATUTS_DU_DISPATCH.map((statut) => ({
    statut,
    resultat: duServeur(interventionsDe(`interventions_${statut}`, statut)),
  }));
}

function digestDeBrut(brut: unknown): DigestDuJour {
  const lu = interpreter(brut, "couple", lireDigest);
  if (!lu.ok) {
    throw new Error(`digest illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

function preparationDeBrut(brut: unknown): Preparation {
  const lu = interpreter(brut, "couple", lirePreparation);
  if (!lu.ok) {
    throw new Error(`préparation illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

describe("les interventions du dispatch, un groupe par statut", () => {
  test("les sept groupes, dans l'ordre du dispatch, chacun avec son libellé de statut", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    expect(groupes.map((g) => g.statut)).toEqual([...STATUTS_DU_DISPATCH]);
    expect(groupes.map((g) => g.titre.cle)).toEqual(STATUTS_DU_DISPATCH.map((s) => `admin.chantiers.statuts.${s}`));
  });

  test("un groupe lu qui a des interventions : chaque ligne dit la nature des travaux, le lead, le devis, le technicien", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    const planifiee = groupes.find((g) => g.statut === "planifiee");
    if (planifiee?.section.genre !== "contenu") {
      throw new Error("le groupe planifiée devrait être lu");
    }
    expect(planifiee.section.contenu.resume).toEqual({ cle: "admin.chantiers.groupe.nombre", params: { nombre: 2 } });
    expect(planifiee.section.contenu.illisibles).toBeNull();
    const [v1, v2] = planifiee.section.contenu.interventions;
    // Lead v1 : un type de travaux ; lead v2 : un service. Jamais l'un déduit de l'autre.
    expect(v1.travaux).toEqual({ cle: "admin.chantiers.travauxType", params: { valeur: "renovation_totale" } });
    expect(v2.travaux).toEqual({ cle: "admin.chantiers.travauxService", params: { valeur: "gouttieres" } });
    expect(v1.lead).toEqual({ cle: "admin.chantiers.lead", params: { id: "LEAD-ADM-C-fictif" } });
    expect(v2.devis).toEqual({ cle: "admin.chantiers.devis", params: { id: "DEVIS-ADM-B-fictif" } });
    expect(v1.technicien).toEqual({ cle: "admin.chantiers.technicien", params: { nom: "etienne" } });
    // L'identifiant envoyé au serveur reste entier ; l'affichage l'abrège.
    expect(v1.interventionId).toMatch(/^[0-9a-f]{64}$/);
    expect(v1.reference).toBe(`${v1.interventionId.slice(0, 8)}…`);
  });

  test("le registre ne porte aucune fenêtre : aucune n'est montrée, jamais inventée ; une fenêtre du serveur est dite", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    for (const groupe of groupes) {
      if (groupe.section.genre === "contenu") {
        for (const intervention of groupe.section.contenu.interventions) {
          expect(intervention.fenetre).toBeNull();
        }
      }
    }
    const brut = reponse("interventions_planifiee");
    brut.resultat[0].fenetre_planifiee = "08:00-12:00";
    const lues = interpreter(brut, "directe", (valeur) => lireInterventions(valeur, "planifiee"));
    if (!lues.ok) {
      throw new Error("la liste devrait être lisible");
    }
    const [groupe] = presenterGroupes([{ statut: "planifiee", resultat: duServeur(lues.valeur) }], DECALAGE);
    if (groupe.section.genre !== "contenu") {
      throw new Error("le groupe devrait être lu");
    }
    expect(groupe.section.contenu.interventions[0].fenetre).toEqual({ cle: "admin.chantiers.fenetre", params: { fenetre: "08:00-12:00" } });
  });

  test("aucun technicien assigné est dit, jamais un nom deviné", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    const aPlanifier = groupes.find((g) => g.statut === "a_planifier");
    if (aPlanifier?.section.genre !== "contenu") {
      throw new Error("le groupe à planifier devrait être lu");
    }
    expect(aPlanifier.section.contenu.interventions[0].technicien).toEqual({ cle: "admin.chantiers.technicienAucun" });
  });

  test("UN GROUPE LU ET VIDE le dit ; il ne reste pas muet", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    const enRoute = groupes.find((g) => g.statut === "en_route");
    expect(enRoute?.section).toMatchObject({
      genre: "contenu",
      contenu: { interventions: [], resume: { cle: "admin.chantiers.groupe.aucune" }, illisibles: null },
    });
  });

  test("UN GROUPE QUI N'A PAS PU ÊTRE LU ne ressemble jamais à un groupe vide", () => {
    const raison = { code: "reponse_tronquee", detail: "la réponse dépasse la limite du serveur" };
    const groupes = presenterGroupes(
      [
        { statut: "planifiee", resultat: { source: "aucune", raison } },
        { statut: "sur_site", resultat: { source: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } } },
      ],
      DECALAGE,
    );
    expect(groupes[0].section).toEqual({ genre: "aucune", avis: { cle: "admin.commun.aucune", params: raison }, raison });
    expect(groupes[1].section).toMatchObject({ genre: "refus", avis: { cle: "admin.commun.refus", params: { code: "tool_call_blocked" } } });
    for (const groupe of groupes) {
      expect(groupe.section).not.toHaveProperty("contenu");
    }
  });

  test("le cache d'un groupe est marqué avec sa date et sa raison", () => {
    const lues = interventionsDe("interventions_planifiee", "planifiee");
    const [groupe] = presenterGroupes([{ statut: "planifiee", resultat: duCache(lues, "reponse_tronquee") }], DECALAGE);
    expect(groupe.section).toMatchObject({
      genre: "contenu",
      horsLigne: { cle: "admin.commun.cache", params: { date: "2026-09-28 09:30", code: "reponse_tronquee" } },
    });
  });

  test("« Vérifier la préparation » n'est offert que pour les statuts d'avant le départ", () => {
    const groupes = presenterGroupes(groupesDeLaFixture(), DECALAGE);
    for (const groupe of groupes) {
      if (groupe.section.genre !== "contenu") {
        continue;
      }
      for (const intervention of groupe.section.contenu.interventions) {
        expect(intervention.preparable).toBe(STATUTS_PREPARABLES.includes(groupe.statut));
      }
    }
    const pending = groupes.find((g) => g.statut === "completed_pending_review");
    expect(pending?.section.genre === "contenu" && pending.section.contenu.interventions[0].preparable).toBe(false);
    const planifiee = groupes.find((g) => g.statut === "planifiee");
    expect(planifiee?.section.genre === "contenu" && planifiee.section.contenu.interventions.every((i) => i.preparable)).toBe(true);
  });

  test("des interventions illisibles sont comptées et dites, jamais devinées", () => {
    const brut = reponse("interventions_planifiee");
    brut.resultat.push({ intervention_id: 12 });
    const lues = interpreter(brut, "directe", (valeur) => lireInterventions(valeur, "planifiee"));
    if (!lues.ok) {
      throw new Error("la liste devrait être lisible");
    }
    const [groupe] = presenterGroupes([{ statut: "planifiee", resultat: duServeur(lues.valeur) }], DECALAGE);
    expect(groupe.section).toMatchObject({
      genre: "contenu",
      contenu: { resume: { params: { nombre: 2 } }, illisibles: { cle: "admin.chantiers.groupe.illisibles", params: { nombre: 1 } } },
    });
  });

  test("un statut que cette version ne connaît pas est dit inconnu", () => {
    const [groupe] = presenterGroupes(
      [{ statut: "annulee", resultat: duServeur({ statut: "annulee", interventions: [], illisibles: 0 }) }],
      DECALAGE,
    );
    expect(groupe.titre).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "annulee" } });
  });
});

describe("le digest du jour", () => {
  test("le jour couvert, l'instant de référence à l'heure locale, ce qui s'est terminé et la file de revue", () => {
    const vue = presenterDigest(digestDe("digest"), DECALAGE);
    expect(vue.titre).toEqual({ cle: "admin.chantiers.digest.titre", params: { date: "2026-09-21", reference: "2026-09-21 18:00" } });
    expect(vue.terminees).toEqual([
      {
        titre: {
          cle: "admin.chantiers.digest.terminee",
          params: { intervention: expect.stringMatching(/^[0-9a-f]{8}…$/), chantier: expect.stringMatching(/^[0-9a-f]{8}…$/) },
        },
        // La durée est celle que M4 compte, en minutes : l'app n'en fait pas des heures.
        duree: { cle: "admin.chantiers.digest.duree", params: { minutes: 180 } },
        ecart: { cle: "admin.chantiers.digest.aucunEcart" },
      },
    ]);
    expect(vue.enRevue).toEqual([]);
    expect(vue.enAttenteDeRevue).toEqual({ cle: "admin.chantiers.digest.enAttenteDeRevue", params: { nombre: 0 } });
    expect(vue.parType).toEqual([
      { cle: "admin.chantiers.typesDeRevue.ecart_metier", params: { nombre: 0 } },
      { cle: "admin.chantiers.typesDeRevue.anomalie_pointage", params: { nombre: 0 } },
    ]);
    expect(vue.bloquees).toEqual([]);
    expect(vue.illisibles).toBeNull();
    expect(vue.rienASignaler).toBe(false);
  });

  test("une intervention terminée : SON numéro et celui de SON chantier, abrégés, jamais l'un pour l'autre", () => {
    const brut = reponse("digest").resultat.resultat.interventions_terminees[0];
    expect(brut.intervention_id).not.toBe(brut.wct_id);
    const [terminee] = presenterDigest(digestDe("digest"), DECALAGE).terminees;
    expect(terminee.titre).toEqual({
      cle: "admin.chantiers.digest.terminee",
      params: { intervention: `${brut.intervention_id.slice(0, 8)}…`, chantier: `${brut.wct_id.slice(0, 8)}…` },
    });
  });

  test("le digest d'un jour où rien ne s'est passé le dit ; ce n'est pas déduit d'une lecture partielle", () => {
    const vide = presenterDigest(digestDe("digest_vide"), DECALAGE);
    expect(vide.rienASignaler).toBe(true);
    expect(vide.terminees).toEqual([]);
    const brut = reponse("digest_vide");
    brut.resultat.resultat.interventions_terminees.push({ intervention_id: 4 });
    const partiel = presenterDigest(digestDeBrut(brut), DECALAGE);
    expect(partiel.rienASignaler).toBe(false);
    expect(partiel.illisibles).toEqual({ cle: "admin.chantiers.digest.illisibles", params: { nombre: 1 } });
  });

  test("un écart signalé à la complétion, des interventions en revue et une demande bloquée depuis des heures", () => {
    const brut = reponse("digest");
    const digest = brut.resultat.resultat;
    digest.interventions_terminees[0].ecart_signale = true;
    digest.interventions_en_revue = ["b1903e5166860713cd4116bf5905c4520e9bb99f17274c8f0026ff6b4e6330f7"];
    digest.count_pending_review = 2;
    digest.pending_par_type = { ecart_metier: 1, anomalie_pointage: 1 };
    digest.interventions_bloquees_en_revue = [
      { intervention_id: "b1903e5166860713cd4116bf5905c4520e9bb99f17274c8f0026ff6b4e6330f7", demande_id: "0d2570487ea4", heures_ecoulees: 30 },
    ];
    const vue = presenterDigest(digestDeBrut(brut), DECALAGE);
    expect(vue.terminees[0].ecart).toEqual({ cle: "admin.chantiers.digest.ecartSignale" });
    expect(vue.enRevue).toEqual([{ cle: "admin.chantiers.digest.enRevueLigne", params: { intervention: "b1903e51…" } }]);
    expect(vue.enAttenteDeRevue.params).toEqual({ nombre: 2 });
    expect(vue.parType.map((m) => m.params)).toEqual([{ nombre: 1 }, { nombre: 1 }]);
    // Les heures sont celles que M4 compte depuis l'instant de référence de l'appareil, telles quelles.
    expect(vue.bloquees).toEqual([
      {
        titre: { cle: "admin.chantiers.digest.bloquee", params: { intervention: "b1903e51…", demande: "0d2570487ea4" } },
        attente: { cle: "admin.chantiers.digest.attente", params: { heures: 30 } },
      },
    ]);
    expect(vue.rienASignaler).toBe(false);
  });

  test("un type de demande de revue que l'app ne connaît pas est dit inconnu", () => {
    const brut = reponse("digest");
    brut.resultat.resultat.pending_par_type.demande_nouvelle = 1;
    const vue = presenterDigest(digestDeBrut(brut), DECALAGE);
    expect(vue.parType[2]).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "demande_nouvelle" } });
  });

  test("le digest selon ce que le chargeur a pu lire", () => {
    const lu = digestDe("digest");
    expect(vueDigest(duServeur(lu), DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: null });
    expect(vueDigest(duCache(lu), DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: { cle: "admin.commun.cache" } });
    expect(vueDigest({ source: "refus", verdict: { code: "REJ-X", detail: "y" } }, DECALAGE).genre).toBe("refus");
    expect(vueDigest({ source: "aucune", raison: { code: "erreur_reseau", detail: "y" } }, DECALAGE).genre).toBe("aucune");
  });
});

describe("la préparation d'une intervention", () => {
  test("bloquée : le verdict de M4, chaque volet avec ce qu'il faut fournir, dans l'ordre de M4", () => {
    const vue = presenterPreparation(preparationDe("preparation_lead_v2"));
    expect(vue.titre).toEqual({ cle: "admin.chantiers.preparation.titre", params: { reference: expect.stringMatching(/^[0-9a-f]{8}…$/) } });
    expect(vue.interventionId).toMatch(/^[0-9a-f]{64}$/);
    expect(vue.statutIntervention).toEqual({ cle: "admin.chantiers.statuts.planifiee" });
    expect(vue.verdict).toEqual({ cle: "admin.chantiers.verdicts.bloque" });
    expect(vue.pret).toBe(false);
    expect(vue.volets.map((v) => v.nom.cle)).toEqual([
      "admin.chantiers.volets.soumission",
      "admin.chantiers.volets.adresse",
      "admin.chantiers.volets.equipe",
      "admin.chantiers.volets.materiel",
      "admin.chantiers.volets.meteo",
    ]);
    expect(vue.volets.map((v) => v.ok)).toEqual([true, false, false, true, false]);
    // Le manque se dit par une phrase de l'app, choisie par le code de M4 ; le code suit, pour le support.
    expect(vue.volets[1]).toEqual({
      nom: { cle: "admin.chantiers.volets.adresse" },
      statut: { cle: "admin.chantiers.statutsDeVolet.manque" },
      ok: false,
      manque: { cle: "admin.chantiers.manques.adresse.aConfirmer" },
      code: { cle: "admin.chantiers.manques.code", params: { code: "REJ-COORDONNEES-A-CONFIRMER" } },
      detail: null,
    });
    // Un volet prêt garde ce que M4 dit de lui (un fait) et n'a ni manque ni code.
    expect(vue.volets[0]).toMatchObject({ ok: true, manque: null, code: null, detail: "devis accepté DEVIS-ADM-B-fictif" });
    expect(vue.volets[3]).toMatchObject({ ok: true, manque: null, code: null, detail: "matériel prêt et réservé (M6, révision 1)" });
    expect(vue.aFournir).toEqual([
      { volet: { cle: "admin.chantiers.volets.adresse" }, manque: { cle: "admin.chantiers.manques.adresse.aConfirmer" } },
      { volet: { cle: "admin.chantiers.volets.equipe" }, manque: { cle: "admin.chantiers.manques.equipe.nonDeclarees" } },
      { volet: { cle: "admin.chantiers.volets.meteo" }, manque: { cle: "admin.chantiers.manques.meteo.nonDeclarees" } },
    ]);
  });

  test("LA MÉTÉO : le volet ne dit que les règles déclarées ; il est nommé comme tel, pas comme une prévision", () => {
    const vue = presenterPreparation(preparationDe("preparation_lead_v2"));
    const meteo = vue.volets[4];
    expect(meteo.nom.cle).toBe("admin.chantiers.volets.meteo");
    expect(meteo.manque).toEqual({ cle: "admin.chantiers.manques.meteo.nonDeclarees" });
    expect(meteo.code).toEqual({ cle: "admin.chantiers.manques.code", params: { code: "REJ-METEO-NON-CONFIGUREE" } });
    expect(meteo.detail).toBeNull();
  });

  test("JAMAIS le texte de M4 : ni le chemin du serveur, ni la commande `opsys-metier`, dans aucune ligne de la vue", () => {
    for (const nom of ["preparation_lead_v2", "preparation_lead_v1", "preparation_a_planifier"]) {
      // Le texte brut de M4 cite bien ce que l'écran ne doit pas dire : sans cela, le test ne prouverait rien.
      const brut = JSON.stringify(reponse(nom).resultat.resultat);
      expect(brut).toContain("/srv/opsys/entreprise.yaml");
      expect(brut).toContain("opsys-metier equipes declarer");
      const vue = JSON.stringify(presenterPreparation(preparationDe(nom)));
      expect(vue).not.toMatch(/\/srv|entreprise\.yaml|opsys-metier|TAXONOMIE|\.md\b|YAML|--depuis|--par/i);
      expect(texteSansChemin(vue)).toBe(vue);
    }
  });

  test("un manque que l'app ne connaît pas (serveur plus récent) : « à configurer côté serveur » avec son code, jamais son texte", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.volets.equipe = {
      statut: "manque",
      manque: "déclare X : écris /srv/opsys/nouveau.yaml puis `opsys-metier nouveau declarer --par <ton nom>`",
      detail: "REJ-NOUVEAU-MANQUE",
    };
    brut.resultat.resultat.a_fournir[1].manque = brut.resultat.resultat.volets.equipe.manque;
    const vue = presenterPreparation(preparationDeBrut(brut));
    expect(vue.volets[2].manque).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "REJ-NOUVEAU-MANQUE" } });
    expect(vue.volets[2].code).toEqual({ cle: "admin.chantiers.manques.code", params: { code: "REJ-NOUVEAU-MANQUE" } });
    expect(vue.aFournir[1].manque).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "REJ-NOUVEAU-MANQUE" } });
    expect(JSON.stringify(vue)).not.toMatch(/nouveau\.yaml|opsys-metier|\/srv/);
  });

  test("un manque SANS code (« aucune équipe admissible ») se dit pareil dans le volet et dans « à fournir »", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.volets.equipe = {
      statut: "manque",
      manque: "aucune équipe admissible pour le service 'gouttieres' : ajuster (`opsys-metier equipes declarer`)",
      detail: null,
    };
    brut.resultat.resultat.a_fournir[1].manque = brut.resultat.resultat.volets.equipe.manque;
    const vue = presenterPreparation(preparationDeBrut(brut));
    const phrase = { cle: "admin.chantiers.manques.equipe.aucuneAdmissible" };
    expect(vue.volets[2]).toMatchObject({ manque: phrase, code: null });
    expect(vue.aFournir[1]).toEqual({ volet: { cle: "admin.chantiers.volets.equipe" }, manque: phrase });
  });

  test("un volet à fournir que la liste des volets ne porte pas : M4 se contredit, « à configurer côté serveur » sans deviner", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.a_fournir[1] = { volet: "assurance", statut: "manque", manque: "écris /srv/opsys/assurance.yaml" };
    const vue = presenterPreparation(preparationDeBrut(brut));
    expect(vue.aFournir[1]).toEqual({
      volet: { cle: "admin.commun.inconnu", params: { valeur: "assurance" } },
      manque: { cle: "admin.chantiers.manques.inconnu", params: { code: "assurance.manque" } },
    });
    expect(JSON.stringify(vue)).not.toMatch(/assurance\.yaml|\/srv/);
  });

  test("un volet à fournir SANS volet du même nom, même connu : M4 se contredit, jamais la phrase d'un manque sans code", () => {
    const brut = reponse("preparation_lead_v2");
    delete brut.resultat.resultat.volets.equipe;
    const vue = presenterPreparation(preparationDeBrut(brut));
    const ligne = vue.aFournir.find((a) => a.volet.cle === "admin.chantiers.volets.equipe");
    // « equipe:manque: » existe dans la table (aucune équipe admissible), mais ce volet-là n'est pas celui-ci : inconnu.
    expect(ligne?.manque).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "equipe.manque" } });
  });

  test("un manque dont le détail n'est pas un code (une phrase, un chemin) ne montre que son volet et son statut", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.volets.meteo.detail = "voir /srv/opsys/entreprise.yaml, clé 'meteo'";
    const vue = presenterPreparation(preparationDeBrut(brut));
    expect(vue.volets[4].manque).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "meteo.manque" } });
    expect(vue.volets[4].code).toBeNull();
    expect(vue.volets[4].detail).toBeNull();
    expect(JSON.stringify(vue)).not.toMatch(/\/srv|entreprise\.yaml/);
  });

  test("un volet PRÊT dont le détail cite un chemin n'affiche pas ce détail ; un détail sans chemin reste dit", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.volets.soumission.detail = "devis accepté, lu dans /srv/opsys/devis.sqlite";
    const vue = presenterPreparation(preparationDeBrut(brut));
    expect(vue.volets[0]).toMatchObject({ ok: true, manque: null, code: null, detail: null });
    expect(vue.volets[3].detail).toBe("matériel prêt et réservé (M6, révision 1)");
  });

  test("une intervention à planifier : le statut de l'intervention est celui de M4", () => {
    const vue = presenterPreparation(preparationDe("preparation_a_planifier"));
    expect(vue.statutIntervention).toEqual({ cle: "admin.chantiers.statuts.a_planifier" });
    expect(vue.verdict).toEqual({ cle: "admin.chantiers.verdicts.bloque" });
    expect(vue.aFournir).toHaveLength(3);
  });

  test("« prête » n'existe que si M4 le dit et que chaque volet est prêt", () => {
    const brut = reponse("preparation_lead_v2");
    const resultat = brut.resultat.resultat;
    resultat.statut = "pret";
    resultat.pret = true;
    resultat.a_fournir = [];
    for (const volet of Object.values<{ statut: string; manque: string | null; detail: string }>(resultat.volets)) {
      volet.statut = "ok";
      volet.manque = null;
    }
    const vue = presenterPreparation(preparationDeBrut(brut));
    expect(vue.pret).toBe(true);
    expect(vue.verdict).toEqual({ cle: "admin.chantiers.verdicts.pret" });
    expect(vue.volets.every((v) => v.ok)).toBe(true);
    expect(vue.aFournir).toEqual([]);
  });

  test("un volet ou un verdict inconnus sont dits inconnus ; ils ne sont jamais lus comme « prêt »", () => {
    const brut = reponse("preparation_lead_v2");
    brut.resultat.resultat.volets.assurance = { statut: "ok", manque: null, detail: "assurance à jour" };
    const vue = presenterPreparation(preparationDeBrut(brut));
    const assurance = vue.volets[vue.volets.length - 1];
    expect(assurance.nom).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "assurance" } });
    expect(assurance.ok).toBe(true);
    expect(vue.pret).toBe(false);
  });

  test("la préparation selon ce que le chargeur a pu lire : refus de M4 dit, jamais une copie à sa place", () => {
    const lue = preparationDe("preparation_lead_v2");
    expect(vuePreparation(duServeur(lue), DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: null });
    expect(vuePreparation(duCache(lue), DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: { cle: "admin.commun.cache" } });
    const refus = vuePreparation(
      {
        source: "refus",
        verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "préparation sans objet : l'intervention est completed_pending_review" },
      },
      DECALAGE,
    );
    expect(refus).toMatchObject({ genre: "refus", avis: { cle: "admin.commun.refus", params: { code: "REJ-TRANSITION-ILLEGALE" } } });
    expect(refus).not.toHaveProperty("contenu");
  });
});
