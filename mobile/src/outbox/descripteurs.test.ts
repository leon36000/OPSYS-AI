import { DESCRIPTEURS_MUTATION } from "./descripteurs";

describe("DESCRIPTEURS_MUTATION", () => {
  test("punch_in/punch_out -> m4_pointer", () => {
    expect(DESCRIPTEURS_MUTATION.get("punch_in")?.tool).toBe("m4_pointer");
    expect(DESCRIPTEURS_MUTATION.get("punch_out")?.tool).toBe("m4_pointer");
  });

  test("job_status_change -> m4_demarrer_route (PLAN T1.4-e)", () => {
    expect(DESCRIPTEURS_MUTATION.get("job_status_change")?.tool).toBe("m4_demarrer_route");
  });

  test("photo_upload/signature_capture : AUCUN descripteur (pas de route serveur d'envoi du binaire)", () => {
    expect(DESCRIPTEURS_MUTATION.get("photo_upload")).toBeUndefined();
    expect(DESCRIPTEURS_MUTATION.get("signature_capture")).toBeUndefined();
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
