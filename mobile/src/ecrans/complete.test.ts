import { evaluerPreparationCompletion } from "./complete";
import type { ParametresEvaluationCompletion } from "./complete";
import type { MutationOutbox, StatutMutation } from "../outbox/types";

function blocMutation(sha: string, index: number, nombreBlocs: number, statut: StatutMutation, chantierId = "I1"): MutationOutbox {
  return {
    id: `bloc-${sha}-${index}`,
    sequence: index + 1,
    type: "fichier_bloc",
    chantierId,
    payload: { empreinte_sha256: sha, index_bloc: index, nombre_blocs: nombreBlocs, bloc_base64: "QQ==" },
    dependsOn: null,
    statut,
    tentatives: 0,
    createdAtLocal: "2026-09-28T08:00:00-04:00",
    prochaineTentativeA: null,
  };
}

/** Fichier "complet" : ses `n` blocs sont tous `envoyee`. */
function mutationsFichierComplet(sha: string, n: number, chantierId = "I1"): MutationOutbox[] {
  return Array.from({ length: n }, (_, i) => blocMutation(sha, i, n, "envoyee", chantierId));
}

const BASE: ParametresEvaluationCompletion = {
  checklistComplete: true,
  photosApresSha256: ["sha-photo-1"],
  signatureSha256: null,
  signatureRequise: false,
  notes: "Aucun imprévu.",
  mutations: [],
  chantierId: "I1",
};

describe("evaluerPreparationCompletion — blocages, dans l'ordre documenté", () => {
  test("checklist non terminée -> checklist_incomplete, avant tout le reste", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, checklistComplete: false, photosApresSha256: [] });
    expect(resultat).toEqual({ pret: false, raison: "checklist_incomplete" });
  });

  test("aucune photo après -> aucune_photo_apres", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, photosApresSha256: [] });
    expect(resultat).toEqual({ pret: false, raison: "aucune_photo_apres" });
  });

  test("signature_requise pas encore choisi (null) -> signature_requise_non_choisie", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, signatureRequise: null, mutations: mutationsFichierComplet("sha-photo-1", 1) });
    expect(resultat).toEqual({ pret: false, raison: "signature_requise_non_choisie" });
  });

  test("signature requise mais aucune capturée -> signature_requise_mais_absente", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, signatureRequise: true, signatureSha256: null });
    expect(resultat).toEqual({ pret: false, raison: "signature_requise_mais_absente" });
  });

  test("fichiers pas encore envoyés (en_cours) -> fichiers_en_cours", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: [blocMutation("sha-photo-1", 0, 2, "en_attente")] });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("aucune mutation fichier_bloc du tout -> fichiers_en_cours (non_demarre), jamais pret", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: [] });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("un bloc en échec permanent -> fichiers_en_echec, PRIORITAIRE sur en_cours", () => {
    const mutations = [
      blocMutation("sha-photo-1", 0, 2, "envoyee"),
      blocMutation("sha-photo-1", 1, 2, "echec_permanent"),
    ];
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_echec" });
  });
});

describe("evaluerPreparationCompletion — prêt : dépendance d'ordre satisfaite (mission item 2)", () => {
  test("checklist + photo complète + pas de signature requise -> pret avec les références serveur", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: mutationsFichierComplet("sha-photo-1", 3) });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves).toEqual({
        checklist_complete: true,
        photos_apres: ["fichier:sha256:sha-photo-1"],
        notes: "Aucun imprévu.",
        signature: null,
      });
    }
  });

  test("plusieurs photos après, TOUTES doivent être complètes", () => {
    const mutations = [...mutationsFichierComplet("sha-1", 1), ...mutationsFichierComplet("sha-2", 1)];
    const resultat = evaluerPreparationCompletion({ ...BASE, photosApresSha256: ["sha-1", "sha-2"], mutations });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.photos_apres).toEqual(["fichier:sha256:sha-1", "fichier:sha256:sha-2"]);
    }
  });

  test("une seule des deux photos complète -> pas encore pret", () => {
    const mutations = [...mutationsFichierComplet("sha-1", 1), blocMutation("sha-2", 0, 1, "en_attente")];
    const resultat = evaluerPreparationCompletion({ ...BASE, photosApresSha256: ["sha-1", "sha-2"], mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("signature requise ET complète -> pret, référence de signature incluse", () => {
    const mutations = [...mutationsFichierComplet("sha-photo-1", 1), ...mutationsFichierComplet("sha-signature", 1)];
    const resultat = evaluerPreparationCompletion({
      ...BASE,
      signatureRequise: true,
      signatureSha256: "sha-signature",
      mutations,
    });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.signature).toBe("fichier:sha256:sha-signature");
    }
  });

  test("signature NON requise mais quand même capturée et complète -> envoyée et référencée aussi", () => {
    const mutations = [...mutationsFichierComplet("sha-photo-1", 1), ...mutationsFichierComplet("sha-signature", 1)];
    const resultat = evaluerPreparationCompletion({
      ...BASE,
      signatureRequise: false,
      signatureSha256: "sha-signature",
      mutations,
    });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.signature).toBe("fichier:sha256:sha-signature");
    }
  });

  test("signature non requise ET pas capturée -> pret avec signature null (aucun blocage)", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: mutationsFichierComplet("sha-photo-1", 1) });
    expect(resultat.pret).toBe(true);
  });

  test("ignore les mutations d'un AUTRE chantier pour la même empreinte", () => {
    const mutations = mutationsFichierComplet("sha-photo-1", 1, "AUTRE-CHANTIER");
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("notes vide est préservée telle quelle (aucun imprévu = note légitime)", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, notes: "", mutations: mutationsFichierComplet("sha-photo-1", 1) });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.notes).toBe("");
    }
  });
});
