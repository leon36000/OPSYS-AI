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
      },
    });
  });

  test("file vide : une liste vide, pas une erreur ; le total et le reste sont conservés", () => {
    const resultat = interpreterResultatListerDemandes(reponseListe({ total_en_attente: 0, reste: 0 }, []));
    expect(resultat).toMatchObject({ ok: true, liste: { demandes: [], totalEnAttente: 0, reste: 0, illisibles: 0 } });
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
