import {
  construireArgumentsDeciderDemande,
  interpreterResultatDeciderDemande,
  interpreterResultatListerDemandes,
  NIVEAUX_DECIDABLES_DEPUIS_L_APP,
} from "./contrat";

// Données FICTIVES : aucune personne ni demande réelle.
function demandeBrute(surcharge: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "d1a2b3c4d5e6",
    departement: "m09-strategic-intelligence",
    departement_nom: "Strategic Intelligence",
    outil: "m9_etat_consolide",
    description_outil: "Ingère un snapshot.",
    niveau: "N3",
    depuis: "2026-09-28T14:00:00+00:00",
    motif_demande: null,
    arguments: { snapshot: { module_source: "m04-field-ops" } },
    decidable: true,
    lecture_seule: null,
    ...surcharge,
  };
}

function reponseListe(surcharge: Record<string, unknown> = {}, demandes: unknown[] = [demandeBrute()]): unknown {
  return {
    ok: true,
    resultat: {
      accepte: true,
      resultat: { demandes, total_en_attente: demandes.length, affichees: demandes.length, reste: 0, proprietaire: true, ...surcharge },
    },
    rejoue: false,
  };
}

describe("interpreterResultatListerDemandes", () => {
  test("liste valide -> demandes typées, totaux et propriétaire lus tels quels", () => {
    const resultat = interpreterResultatListerDemandes(reponseListe());
    expect(resultat).toEqual({
      ok: true,
      liste: {
        demandes: [
          {
            id: "d1a2b3c4d5e6",
            departement: "m09-strategic-intelligence",
            departementNom: "Strategic Intelligence",
            outil: "m9_etat_consolide",
            descriptionOutil: "Ingère un snapshot.",
            niveau: "N3",
            depuis: "2026-09-28T14:00:00+00:00",
            motifDemande: null,
            arguments: { snapshot: { module_source: "m04-field-ops" } },
            decidable: true,
            lectureSeule: null,
          },
        ],
        totalEnAttente: 1,
        affichees: 1,
        reste: 0,
        proprietaire: true,
        illisibles: 0,
        attentes: null,
      },
    });
  });

  test("file vide : une liste vide, pas une erreur ; le total et le reste sont conservés", () => {
    const resultat = interpreterResultatListerDemandes(reponseListe({ total_en_attente: 0, reste: 0 }, []));
    expect(resultat).toMatchObject({ ok: true, liste: { demandes: [], totalEnAttente: 0, reste: 0, illisibles: 0 } });
  });

  describe("attentes des départements (PLAN T1.5)", () => {
    // Sortie RÉELLE du moteur, relevée par le test E2E `tests/e2e/test_travaux_termines_appareil.py` (scénario B,
    // écart de matériaux de 40 %) : les trois attentes que voit l'admin, telles que le serveur les a écrites.
    const ATTENTES_REELLES = [
      {
        type: "completion_en_revue",
        id: "99da0a062b9d9eea1f58bf4fe885a3b01079d82f2d25c1cf5e2d10a357ef2680",
        departement: "m04-field-ops",
        departement_nom: "Field Ops",
        resume:
          "Complétion en revue (99da0a062b9d9eea1f58bf4fe885a3b01079d82f2d25c1cf5e2d10a357ef2680) — écart matériaux CRITIQUE signalé par M6 (seuil 0.3)",
        niveau: "N4",
        depuis: "2026-09-16T11:00:00-04:00",
        action_proposee: "m4_resoudre_revue_completion : verifiee (confirme) ou correction (nomme le problème)",
      },
      {
        type: "facture_brouillon",
        id: "fac-DEVIS-SPIKE-fictif",
        departement: "m05-financecore",
        departement_nom: "FinanceCore",
        resume: "Facture fac-DEVIS-SPIKE-fictif prête à envoyer (689.85 $)",
        niveau: "N4",
        depuis: "2026-09-16T15:00:00+00:00",
        action_proposee: "envoyer",
      },
      {
        type: "chantier_a_reviser",
        id: "variance-a1b6b33cc2eabd5e1d2f753b3911831dfedd879b5fcbe79623cdd555cf22ae6c",
        departement: "m05-financecore",
        departement_nom: "FinanceCore",
        resume:
          "Écart matériaux critique sur le chantier CH-SPIKE-fictif (wct a1b6b33cc2eabd5e1d2f753b3911831dfedd879b5fcbe79623cdd555cf22ae6c) — facture fac-DEVIS-SPIKE-fictif prête à envoyer quand même",
        niveau: "N4",
        depuis: "2026-09-16T15:00:00+00:00",
        action_proposee: "réviser",
      },
    ];

    function avecAttentes(surcharge: Record<string, unknown> = {}): unknown {
      return reponseListe(
        {
          attentes: ATTENTES_REELLES,
          total_attentes: 3,
          attentes_affichees: 3,
          attentes_reste: 0,
          attentes_illisibles: [],
          ...surcharge,
        },
        [],
      );
    }

    test("la sortie réelle du moteur est lue : les trois attentes, mot pour mot", () => {
      const resultat = interpreterResultatListerDemandes(avecAttentes());
      expect(resultat.ok).toBe(true);
      if (!resultat.ok) {
        return;
      }
      const attentes = resultat.liste.attentes;
      expect(attentes).not.toBeNull();
      expect(attentes?.total).toBe(3);
      expect(attentes?.reste).toBe(0);
      expect(attentes?.illisibles).toBe(0);
      expect(attentes?.departementsIllisibles).toEqual([]);
      expect(attentes?.items.map((a) => a.type)).toEqual(["completion_en_revue", "facture_brouillon", "chantier_a_reviser"]);
      expect(attentes?.items[0]).toEqual({
        type: "completion_en_revue",
        id: "99da0a062b9d9eea1f58bf4fe885a3b01079d82f2d25c1cf5e2d10a357ef2680",
        departement: "m04-field-ops",
        departementNom: "Field Ops",
        resume: ATTENTES_REELLES[0]?.resume,
        niveau: "N4",
        depuis: "2026-09-16T11:00:00-04:00",
        actionProposee: "m4_resoudre_revue_completion : verifiee (confirme) ou correction (nomme le problème)",
      });
      expect(attentes?.items[0]?.resume).toContain("écart matériaux CRITIQUE signalé par M6");
    });

    test("le moteur ne donne pas d'attentes : null, ni « aucune » ni une liste vide inventée", () => {
      const resultat = interpreterResultatListerDemandes(reponseListe());
      expect(resultat).toMatchObject({ ok: true, liste: { attentes: null } });
    });

    test("une liste d'attentes vide, dite par le serveur, est vide et connue", () => {
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ attentes: [], total_attentes: 0, attentes_affichees: 0 }),
      );
      expect(resultat).toMatchObject({
        ok: true,
        liste: { attentes: { items: [], total: 0, reste: 0, illisibles: 0, departementsIllisibles: [] } },
      });
    });

    test("la page lue dit son rang et le rang de la suivante (T1.5-e)", () => {
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ total_attentes: 9, attentes_reste: 4, attentes_decalage: 2, attentes_suivant: 5 }),
      );
      expect(resultat).toMatchObject({
        ok: true,
        liste: { attentes: { total: 9, reste: 4, decalage: 2, suivant: 5 } },
      });
    });

    test("rien ne suit : suivant est nul, et un moteur qui ne pagine pas n'en dit rien (rang 0, pas de suite)", () => {
      const derniere = interpreterResultatListerDemandes(avecAttentes({ attentes_decalage: 6, attentes_suivant: null }));
      expect(derniere).toMatchObject({ ok: true, liste: { attentes: { decalage: 6, suivant: null } } });

      const ancien = interpreterResultatListerDemandes(avecAttentes());
      expect(ancien).toMatchObject({ ok: true, liste: { attentes: { decalage: 0, suivant: null } } });
    });

    test("une page vide au-delà de la fin est une page vide, pas une erreur : rien n'est inventé", () => {
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ attentes: [], total_attentes: 3, attentes_affichees: 0, attentes_reste: 0, attentes_decalage: 40, attentes_suivant: null }),
      );
      expect(resultat).toMatchObject({
        ok: true,
        liste: { attentes: { items: [], total: 3, reste: 0, decalage: 40, suivant: null } },
      });
    });

    test("le reste et les départements illisibles sont conservés", () => {
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ total_attentes: 5, attentes_reste: 2, attentes_illisibles: ["m05-financecore"] }),
      );
      expect(resultat).toMatchObject({
        ok: true,
        liste: { attentes: { total: 5, reste: 2, departementsIllisibles: ["m05-financecore"] } },
      });
    });

    test("une attente mal formée est comptée dans illisibles, jamais devinée ni supprimée en silence", () => {
      const mauvaises = [
        { ...ATTENTES_REELLES[0], id: "" },
        { ...ATTENTES_REELLES[0], resume: null },
        { ...ATTENTES_REELLES[0], departement: 4 },
        { ...ATTENTES_REELLES[0], niveau: 4 },
        "pas un objet",
        null,
      ];
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ attentes: [ATTENTES_REELLES[1], ...mauvaises], total_attentes: 7 }),
      );
      expect(resultat).toMatchObject({ ok: true, liste: { attentes: { total: 7, illisibles: mauvaises.length } } });
      if (resultat.ok) {
        expect(resultat.liste.attentes?.items).toHaveLength(1);
      }
    });

    test("un niveau absent reste null, jamais deviné", () => {
      const sansNiveau = { ...ATTENTES_REELLES[1], niveau: null, action_proposee: null };
      const resultat = interpreterResultatListerDemandes(
        avecAttentes({ attentes: [sansNiveau], total_attentes: 1 }),
      );
      expect(resultat).toMatchObject({ ok: true, liste: { attentes: { items: [{ niveau: null, actionProposee: null }] } } });
    });

    test.each([
      ["attentes n'est pas une liste", { attentes: "rien" }],
      ["total_attentes manquant", { total_attentes: undefined }],
      ["total_attentes négatif", { total_attentes: -1 }],
      ["attentes_reste fractionnaire", { attentes_reste: 1.5 }],
      ["attentes_illisibles n'est pas une liste", { attentes_illisibles: "m05" }],
      ["attentes_illisibles contient autre chose que du texte", { attentes_illisibles: [3] }],
      ["attentes_suivant est un texte", { attentes_suivant: "3" }],
      ["attentes_suivant est négatif", { attentes_suivant: -1 }],
      ["attentes_suivant est fractionnaire", { attentes_suivant: 2.5 }],
      ["attentes_suivant est un booléen", { attentes_suivant: true }],
      ["attentes_decalage est un texte", { attentes_decalage: "0" }],
      ["attentes_decalage est négatif", { attentes_decalage: -3 }],
      ["attentes_decalage est nul (null)", { attentes_decalage: null }],
    ])("réponse illisible, jamais « aucune attente » : %s", (_nom, surcharge) => {
      const resultat = interpreterResultatListerDemandes(avecAttentes(surcharge));
      expect(resultat).toEqual({ ok: false, verdict: expect.objectContaining({ code: "reponse_illisible" }) });
    });
  });

  test("N5 : lecture seule et verdict du serveur conservés mot pour mot", () => {
    const n5 = demandeBrute({
      niveau: "N5",
      decidable: false,
      lecture_seule: { code: "n5_a_la_console", detail: "Niveau N5 : à décider à la console." },
    });
    const resultat = interpreterResultatListerDemandes(reponseListe({}, [n5]));
    expect(resultat).toMatchObject({
      ok: true,
      liste: { demandes: [{ niveau: "N5", decidable: false, lectureSeule: { code: "n5_a_la_console", detail: "Niveau N5 : à décider à la console." } }] },
    });
  });

  test("ancienne demande sans niveau : niveau null conservé, jamais deviné", () => {
    const resultat = interpreterResultatListerDemandes(reponseListe({}, [demandeBrute({ niveau: null, decidable: false })]));
    expect(resultat).toMatchObject({ ok: true, liste: { demandes: [{ niveau: null }] } });
  });

  test("arguments null (pas le propriétaire, ou trop gros) restent null", () => {
    const resultat = interpreterResultatListerDemandes(reponseListe({ proprietaire: false }, [demandeBrute({ arguments: null, decidable: false })]));
    expect(resultat).toMatchObject({ ok: true, liste: { proprietaire: false, demandes: [{ arguments: null }] } });
  });

  test("un élément mal formé est compté dans illisibles, jamais deviné ni supprimé en silence", () => {
    const mauvais = [
      { ...demandeBrute(), id: "" },
      { ...demandeBrute(), decidable: "oui" },
      { ...demandeBrute(), arguments: "texte" },
      { ...demandeBrute(), lecture_seule: "non" },
      { ...demandeBrute(), niveau: 4 },
      "pas un objet",
      null,
    ];
    const resultat = interpreterResultatListerDemandes(reponseListe({ total_en_attente: 8, affichees: 8 }, [demandeBrute(), ...mauvais]));
    expect(resultat).toMatchObject({ ok: true, liste: { totalEnAttente: 8, illisibles: mauvais.length } });
    if (resultat.ok) {
      expect(resultat.liste.demandes).toHaveLength(1);
    }
  });

  test.each([
    ["totaux absents", reponseListe({ total_en_attente: undefined })],
    ["total négatif", reponseListe({ total_en_attente: -1 })],
    ["reste fractionnaire", reponseListe({ reste: 1.5 })],
    ["proprietaire absent", reponseListe({ proprietaire: undefined })],
    ["demandes n'est pas une liste", reponseListe({ demandes: "x" })],
    ["enveloppe vide", {}],
    ["null", null],
    ["texte", "ok"],
    ["accepte true sans résultat", { ok: true, resultat: { accepte: true } }],
  ])("réponse illisible (%s) -> verdict reponse_illisible, jamais une liste vide", (_nom, brut) => {
    const resultat = interpreterResultatListerDemandes(brut);
    expect(resultat).toMatchObject({ ok: false, verdict: { code: "reponse_illisible" } });
  });

  test("verdict du serveur (pas d'identité) -> repris tel quel", () => {
    const resultat = interpreterResultatListerDemandes({
      ok: true,
      resultat: { accepte: false, verdict: { code: "identite_absente", detail: "Aucune identité d'appareil authentifiée." } },
    });
    expect(resultat).toEqual({ ok: false, verdict: { code: "identite_absente", detail: "Aucune identité d'appareil authentifiée." } });
  });

  test("refus technique (ok:false) -> code de l'erreur, détails d'une liste mis bout à bout", () => {
    const resultat = interpreterResultatListerDemandes({ ok: false, erreur: "arguments_invalides", details: ["paramètre inconnu : x", "limite : type attendu integer"] });
    expect(resultat).toEqual({ ok: false, verdict: { code: "arguments_invalides", detail: "paramètre inconnu : x ; limite : type attendu integer" } });
  });
});

function accuseBrut(surcharge: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    demande_id: "d1a2b3c4d5e6",
    decision: "approuver",
    statut: "executee",
    outil: "m9_etat_consolide",
    departement: "m09-strategic-intelligence",
    niveau: "N3",
    decide_par: "proprio.fictif",
    role: "nathan_owner",
    decide_le: "2026-09-28T14:05:00+00:00",
    issue: { ok: true, accepte: true },
    ...surcharge,
  };
}

const accepte = (accuse: unknown) => ({ ok: true, resultat: { accepte: true, resultat: accuse }, rejoue: false });

describe("interpreterResultatDeciderDemande", () => {
  test("approbation exécutée -> accusé typé", () => {
    expect(interpreterResultatDeciderDemande(accepte(accuseBrut()))).toEqual({
      accepte: true,
      resultat: {
        demandeId: "d1a2b3c4d5e6",
        decision: "approuver",
        statut: "executee",
        outil: "m9_etat_consolide",
        departement: "m09-strategic-intelligence",
        niveau: "N3",
        decidePar: "proprio.fictif",
        role: "nathan_owner",
        decideLe: "2026-09-28T14:05:00+00:00",
        issue: { ok: true, accepte: true, verdict: null, erreur: null, details: null },
      },
    });
  });

  test("refus enregistré : statut refusee, pas d'issue", () => {
    const resultat = interpreterResultatDeciderDemande(accepte(accuseBrut({ decision: "refuser", statut: "refusee", issue: undefined })));
    expect(resultat).toMatchObject({ accepte: true, resultat: { decision: "refuser", statut: "refusee", issue: null } });
  });

  test("approuvée mais l'exécution a échoué : le statut echec et l'erreur sont conservés", () => {
    const resultat = interpreterResultatDeciderDemande(
      accepte(accuseBrut({ statut: "echec", issue: { ok: false, erreur: "refus_metier", details: "valeur négative refusée" } })),
    );
    expect(resultat).toMatchObject({
      accepte: true,
      resultat: { statut: "echec", issue: { ok: false, erreur: "refus_metier", details: "valeur négative refusée" } },
    });
  });

  test("approuvée mais l'outil a refusé sur le fond : le verdict métier est conservé", () => {
    const resultat = interpreterResultatDeciderDemande(
      accepte(accuseBrut({ issue: { ok: true, accepte: false, verdict: { code: "REJ-X", detail: "snapshot refusé" } } })),
    );
    expect(resultat).toMatchObject({
      accepte: true,
      resultat: { issue: { ok: true, accepte: false, verdict: { code: "REJ-X", detail: "snapshot refusé" } } },
    });
  });

  test.each([
    ["deja_decidee", "La demande d1 est déjà traitée (executee) : rien n'a été refait."],
    ["n5_a_la_console", "Niveau N5 : à décider à la console."],
    ["reserve_au_proprietaire", "Réservé au propriétaire."],
    ["identite_absente", "Aucune identité."],
    ["appareil_inconnu", "Appareil inconnu."],
    ["politique_du_departement", "Politique."],
  ])("rejet du serveur %s -> verdict repris tel quel, jamais un succès", (code, detail) => {
    const resultat = interpreterResultatDeciderDemande({
      ok: true,
      resultat: { accepte: false, verdict: { code, detail, statut: "executee", decide_par: "quelqu-un" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code, detail } });
  });

  test("mutation_conflit (même clé, autres arguments) -> refus technique repris tel quel", () => {
    const resultat = interpreterResultatDeciderDemande({ ok: false, erreur: "mutation_conflit", details: "clé déjà utilisée" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "mutation_conflit", detail: "clé déjà utilisée" } });
  });

  test.each([
    ["statut inconnu", accepte(accuseBrut({ statut: "en_cours" }))],
    ["statut absent", accepte(accuseBrut({ statut: undefined }))],
    ["décision inconnue", accepte(accuseBrut({ decision: "annuler" }))],
    ["demande_id vide", accepte(accuseBrut({ demande_id: "" }))],
    ["accusé absent", { ok: true, resultat: { accepte: true } }],
    ["accepte absent", { ok: true, resultat: {} }],
    ["enveloppe vide", {}],
    ["null", null],
    ["texte", "ok"],
  ])("réponse illisible (%s) -> JAMAIS un succès : rejet qui dit de revérifier la liste", (_nom, brut) => {
    const resultat = interpreterResultatDeciderDemande(brut);
    expect(resultat.accepte).toBe(false);
    if (!resultat.accepte) {
      expect(resultat.verdict.code).toBe("reponse_illisible");
      expect(resultat.verdict.detail).toContain("liste");
    }
  });
});

describe("construireArgumentsDeciderDemande", () => {
  test("sans note : demande_id et decision seulement", () => {
    expect(construireArgumentsDeciderDemande("d1", "approuver", "")).toEqual({ demande_id: "d1", decision: "approuver" });
    expect(construireArgumentsDeciderDemande("d1", "refuser", "   ")).toEqual({ demande_id: "d1", decision: "refuser" });
  });

  test("avec une note épurée : motif ajouté", () => {
    expect(construireArgumentsDeciderDemande("d1", "refuser", "  Pas maintenant.  ")).toEqual({
      demande_id: "d1",
      decision: "refuser",
      motif: "Pas maintenant.",
    });
  });

  test("jamais de personne, de rôle ni d'appareil dans les arguments (le serveur les tient du jeton)", () => {
    const args = construireArgumentsDeciderDemande("d1", "approuver", "ok");
    expect(Object.keys(args).sort()).toEqual(["decision", "demande_id", "motif"]);
  });
});

describe("NIVEAUX_DECIDABLES_DEPUIS_L_APP", () => {
  test("N3 et N4 seulement : N5 ne se décide jamais depuis l'app", () => {
    expect([...NIVEAUX_DECIDABLES_DEPUIS_L_APP]).toEqual(["N3", "N4"]);
  });
});
