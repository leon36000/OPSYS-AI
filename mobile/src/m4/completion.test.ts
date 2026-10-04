import {
  construireArgumentsCompleterIntervention,
  estAccuseCompletionM4,
  interpreterResultatCompleterIntervention,
} from "./completion";
import { CHOIX_CLIENT_VIDES, VERSION_TEXTE_CONSENTEMENT_CLIENT, construireChampsClient } from "./consentementClient";
import type { PreuvesCompletionM4 } from "./preuvesCompletion";

const PREUVES: PreuvesCompletionM4 = {
  checklist_complete: true,
  photos_apres: ["fichier:sha256:abc"],
  notes: "Aucun imprévu.",
  signature: "fichier:sha256:def",
};

describe("construireArgumentsCompleterIntervention", () => {
  test("args exacts sans champs client : aucun consentement n'est inventé", () => {
    const args = construireArgumentsCompleterIntervention("I1", "2026-09-28T14:00:00-04:00", PREUVES, true);
    expect(args).toEqual({
      intervention_id: "I1",
      horodatage: "2026-09-28T14:00:00-04:00",
      preuves_completion: PREUVES,
      signature_requise: true,
    });
    expect(Object.keys(args)).toEqual(["intervention_id", "horodatage", "preuves_completion", "signature_requise"]);
  });

  test("aucune case cochée : les mêmes quatre clés qu'avant (PLAN T1.5-d)", () => {
    const args = construireArgumentsCompleterIntervention(
      "I1", "2026-09-28T14:00:00-04:00", PREUVES, false, construireChampsClient(CHOIX_CLIENT_VIDES),
    );
    expect(Object.keys(args)).toEqual(["intervention_id", "horodatage", "preuves_completion", "signature_requise"]);
  });

  test("les champs client recueillis s'ajoutent tels quels, sans toucher aux quatre clés de base (PLAN T1.5-d)", () => {
    const champs = construireChampsClient({ ...CHOIX_CLIENT_VIDES, consentementDemandeAvis: true, satisfaction: "satisfait" });
    const args = construireArgumentsCompleterIntervention("I1", "2026-09-28T14:00:00-04:00", PREUVES, true, champs);
    expect(args).toEqual({
      intervention_id: "I1",
      horodatage: "2026-09-28T14:00:00-04:00",
      preuves_completion: PREUVES,
      signature_requise: true,
      consentement_demande_avis: true,
      consentement_version_texte: VERSION_TEXTE_CONSENTEMENT_CLIENT,
      client_satisfait: true,
    });
  });

  test("tout ce qui part est une clé du schéma de m4_completer_intervention (additionalProperties: false)", () => {
    const champs = construireChampsClient({ consentementDemandeAvis: true, consentementPhotos: true, satisfaction: "insatisfait" });
    const args = construireArgumentsCompleterIntervention("I1", "2026-09-28T14:00:00-04:00", PREUVES, true, champs);
    // Les clés de `outils.py::completer_intervention` (paramètres de l'outil), sans `photos` ni
    // `description_factuelle` que l'app n'envoie pas.
    const CLES_DU_SCHEMA = new Set([
      "intervention_id", "horodatage", "preuves_completion", "signature_requise", "consentement_marketing",
      "consentement_demande_avis", "consentement_version_texte", "client_satisfait", "photos", "description_factuelle",
    ]);
    expect(Object.keys(args).filter((cle) => !CLES_DU_SCHEMA.has(cle))).toEqual([]);
    expect(Object.keys(args)).not.toContain("consentement_recueilli_par"); // posé par le serveur, pas par l'app
  });
});

describe("interpreterResultatCompleterIntervention", () => {
  test("accepté -> statut affiché TEL QUEL, y compris completed_pending_review (mission item 2)", () => {
    const accuse = {
      wct_id: "W1",
      intervention_id: "I1",
      ligne_id: "L1",
      statut: "completed_pending_review",
      hash_maillon: "h1",
      duree_reelle_minutes: 120,
      ecart_signale: true,
      tete_chaine: "t1",
    };
    const resultat = interpreterResultatCompleterIntervention({ ok: true, resultat: { accepte: true, resultat: accuse } });
    expect(resultat).toEqual({ accepte: true, resultat: accuse });
    if (resultat.accepte) {
      expect(resultat.resultat?.statut).toBe("completed_pending_review"); // jamais maquillé en "terminé"
    }
  });

  test("rejet métier (ex. preuves incomplètes) -> accepte:false avec le verdict", () => {
    const resultat = interpreterResultatCompleterIntervention({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "checklist non terminée" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "checklist non terminée" } });
  });

  test("écart de référence fichier introuvable -> code affiché tel quel", () => {
    const resultat = interpreterResultatCompleterIntervention({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-PREUVE-FICHIER-INTROUVABLE", detail: "photos_apres[0] introuvable ou incomplet" } },
    });
    expect(resultat.accepte).toBe(false);
    if (!resultat.accepte) {
      expect(resultat.verdict.code).toBe("REJ-PREUVE-FICHIER-INTROUVABLE");
    }
  });

  test("erreur technique -> accepte:false", () => {
    const resultat = interpreterResultatCompleterIntervention({ ok: false, erreur: "refus_metier", details: "horodatage invalide" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "refus_metier", detail: "horodatage invalide" } });
  });

  test("réponse acceptée sans accusé complet reste incertaine et réessayable", () => {
    expect(interpreterResultatCompleterIntervention({ ok: true, resultat: { accepte: true, resultat: { wct_id: "W1" } } }))
      .toEqual({ accepte: false, verdict: { code: "accuse_invalide", detail: "Accusé de complétion incomplet ou invalide." } });
  });
});

describe("estAccuseCompletionM4", () => {
  test("accusé bien formé -> true", () => {
    expect(
      estAccuseCompletionM4({
        wct_id: "W1",
        intervention_id: "I1",
        ligne_id: "L1",
        statut: "completed_pending_review",
        hash_maillon: "h",
        duree_reelle_minutes: 60,
        ecart_signale: true,
        tete_chaine: null,
      }),
    ).toBe(true);
  });

  test.each([null, undefined, "texte", {}, { wct_id: "W1" }, { wct_id: "W1", intervention_id: "I1" }])(
    "%j -> false, jamais une lecture hasardeuse",
    (valeur) => {
      expect(estAccuseCompletionM4(valeur)).toBe(false);
    },
  );
});
