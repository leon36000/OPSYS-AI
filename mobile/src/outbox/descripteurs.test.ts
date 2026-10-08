import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";

describe("DESCRIPTEURS_MUTATION", () => {
  test("punch_in/punch_out -> m4_pointer", () => {
    expect(DESCRIPTEURS_MUTATION.get("punch_in")?.tool).toBe("m4_pointer");
    expect(DESCRIPTEURS_MUTATION.get("punch_out")?.tool).toBe("m4_pointer");
  });

  test("job_status_change -> m4_demarrer_route (PLAN T1.4-e)", () => {
    expect(DESCRIPTEURS_MUTATION.get("job_status_change")?.tool).toBe("m4_demarrer_route");
  });

  test("fichier_bloc -> m4_deposer_fichier (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.tool).toBe("m4_deposer_fichier");
  });

  test("job_completion -> m4_completer_intervention (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("job_completion")?.tool).toBe("m4_completer_intervention");
  });

  test("materials_submit -> m6_declarer_materiaux_utilises (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("materials_submit")?.tool).toBe("m6_declarer_materiaux_utilises");
  });

  test("approval_decision -> m9_decider_demande_approbation (PLAN T1.4-f étape 6)", () => {
    expect(DESCRIPTEURS_MUTATION.get("approval_decision")?.tool).toBe("m9_decider_demande_approbation");
  });

  test("lead_note -> m2_enregistrer_interaction (PLAN T4.8)", () => {
    expect(DESCRIPTEURS_MUTATION.get("lead_note")?.tool).toBe("m2_enregistrer_interaction");
  });

  test("photo_upload/signature_capture : AUCUN descripteur — le transport passe par fichier_bloc (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("photo_upload")).toBeUndefined();
    expect(DESCRIPTEURS_MUTATION.get("signature_capture")).toBeUndefined();
  });

  describe("interprète fichier_bloc (m4_deposer_fichier)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("fichier_bloc")!.interpreterResultat;

    test("bloc accepté -> accepte:true avec le résumé (reference/complet/blocsRecus)", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [0] } },
      });
      expect(resultat).toEqual({ accepte: true, resume: { reference: null, complet: false, blocsRecus: [0] } });
    });

    test("rejet (ex. empreinte discordante) -> accepte:false avec le verdict", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage différent" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage différent" } });
    });
  });

  describe("interprète lead_note (m2_enregistrer_interaction)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("lead_note")!.interpreterResultat;

    test("note enregistrée -> accepte:true, l'accusé typé en résumé", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { lead_id: "L1", ligne_id: "abc", tete_chaine: "def", horodatage: "2026-09-29T14:03:22-04:00" } },
      });
      expect(resultat).toEqual({
        accepte: true,
        resume: { leadId: "L1", ligneId: "abc", horodatage: "2026-09-29T14:03:22-04:00" },
      });
    });

    test("lead d'un autre ou clos -> accepte:false avec le verdict du serveur, tel quel", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" } });
    });

    test("accusé illisible -> accepte:false : jamais un succès silencieux", () => {
      expect(interpreter({ ok: true, resultat: { accepte: true, resultat: {} } })).toMatchObject({
        accepte: false,
        verdict: { code: "reponse_illisible" },
      });
    });
  });

  describe("interprète approval_decision (m9_decider_demande_approbation)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("approval_decision")!.interpreterResultat;

    test("décision enregistrée -> accepte:true, l'accusé typé en résumé", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { demande_id: "d1", decision: "refuser", statut: "refusee", decide_par: "proprio.fictif", role: "nathan_owner" } },
      });
      expect(resultat).toMatchObject({ accepte: true, resume: { demandeId: "d1", decision: "refuser", statut: "refusee" } });
    });

    test("N5 ou déjà décidée -> accepte:false avec le verdict du serveur, tel quel", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "n5_a_la_console", detail: "à décider à la console" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "n5_a_la_console", detail: "à décider à la console" } });
    });

    test("accusé illisible -> accepte:false : jamais un succès silencieux", () => {
      expect(interpreter({ ok: true, resultat: { accepte: true, resultat: {} } })).toMatchObject({
        accepte: false,
        verdict: { code: "reponse_illisible" },
      });
    });
  });

  describe("interprète job_completion (m4_completer_intervention)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("job_completion")!.interpreterResultat;

    test("accepté -> accepte:true, statut porté tel quel (jamais maquillé)", () => {
      const accuse = {
        wct_id: "W1",
        intervention_id: "I1",
        ligne_id: "L1",
        statut: "completed_pending_review",
        hash_maillon: "h",
        duree_reelle_minutes: 90,
        ecart_signale: true,
        tete_chaine: "t",
      };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: accuse } });
      expect(resultat).toEqual({ accepte: true, resume: accuse });
    });

    test("preuves incomplètes -> accepte:false, jamais un succès silencieux", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "photos_apres vide" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "photos_apres vide" } });
    });
  });

  describe("interprète materials_submit (m6_declarer_materiaux_utilises)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("materials_submit")!.interpreterResultat;

    test("confirmation canonique liée -> accepte:true (fixture RAM fictive)", () => {
      const lignes = [{ type_ligne: "perte", materiau_id: "MAT-FICTIF", quantite: 2, unite: "m" }];
      const formulaire = { wct_id: "WCT-FICTIF", intervention_id: "INTERVENTION-FICTIVE", chantier_id: "CHANTIER-FICTIF", lignes_materiaux: lignes };
      const mutation = { ...soumettreMutation(creerMutation({ type: "materials_submit", chantierId: formulaire.intervention_id,
        payload: { wct_id: formulaire.wct_id, formulaire } }, () => "UUID-FICTIF",
        { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 })), proprietaire: "PERSONNE-FICTIVE", sequence: 1 };
      // Trois champs exacts de contrats_sortie.py ; aucun écho WCT/personne/UUID inventé.
      const confirmation = { intervention_id: formulaire.intervention_id, chantier_id: formulaire.chantier_id, lignes_declarees: lignes };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: confirmation,
        registre: { taille: 3, hash_tete: "a".repeat(64) } } }, mutation);
      expect(resultat).toEqual({ accepte: true, resume: confirmation });
    });

    test("rejet sans detail (forme réelle du contrat M6) -> verdict avec detail vide", () => {
      const resultat = interpreter({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-DECLARATION-DEJA-SOUMISE" } } });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-DECLARATION-DEJA-SOUMISE", detail: "" } });
    });
  });

  describe("interprète job_status_change (m4_demarrer_route)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("job_status_change")!.interpreterResultat;

    test("accepté -> accepte:true avec le résumé", () => {
      const accuse = {
        intervention_id: "I1",
        ligne_id: "L1",
        statut: "en_route",
        statut_precedent: "planifiee",
        empreinte_maillon: "abc",
        tete_chaine: "def",
        horodatage: "2026-09-28T08:00:00-04:00",
      };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: accuse } });
      expect(resultat).toEqual({ accepte: true, resume: accuse });
    });

    test("rejet métier -> accepte:false avec le verdict, jamais un succès silencieux", () => {
      const resultat = interpreter({
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
  });
});
