import { evaluerPreparationCompletion } from "./complete";
import type { ParametresEvaluationCompletion } from "./complete";
import { TAILLE_BLOC_OCTETS } from "../fichiers/decoupage";
import type { MutationOutbox, StatutMutation } from "../outbox/types";

// Fixtures RAM FICTIVES : formes du contrat local, pas fichiers décodés ni observations CAS live.
const SHA_PHOTO = "a".repeat(64), SHA_PREMIERE = "b".repeat(64), SHA_SECONDE = "c".repeat(64), SHA_SIGNATURE = "d".repeat(64);
function blocMutation(sha: string, index: number, nombreBlocs: number, statut: StatutMutation, chantierId = "I1"): MutationOutbox {
  const taille = (nombreBlocs - 1) * TAILLE_BLOC_OCTETS + 1;
  const dernier = index === nombreBlocs - 1;
  return {
    id: `bloc-${sha}-${index}`,
    sequence: index + 1,
    type: "fichier_bloc",
    chantierId,
    payload: { empreinte_sha256: sha, taille_octets: taille, type_mime: "image/jpeg", index_bloc: index,
      nombre_blocs: nombreBlocs, bloc_base64: Buffer.alloc(dernier ? 1 : TAILLE_BLOC_OCTETS).toString("base64") },
    dependsOn: null,
    statut,
    tentatives: 0,
    createdAtLocal: "2026-09-28T08:00:00-04:00",
    prochaineTentativeA: null,
    proprietaire: "PROPRIETAIRE-FICTIF",
    resumeAccepte: statut === "envoyee" ? { reference: dernier ? `fichier:sha256:${sha}` : null,
      complet: dernier, blocsRecus: Array.from({ length: index + 1 }, (_, i) => i) } : null,
  };
}

/** Historique LOCAL complet : chacun des n blocs possède un reçu fermé lié à son appel.
 * Ce test pur ne qualifie pas pret live avant la vraie déclaration/complétion. */
function mutationsFichierComplet(sha: string, n: number, chantierId = "I1"): MutationOutbox[] {
  return Array.from({ length: n }, (_, i) => blocMutation(sha, i, n, "envoyee", chantierId));
}

const BASE: ParametresEvaluationCompletion = {
  checklistComplete: true,
  photosApresSha256: [SHA_PHOTO],
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
    const resultat = evaluerPreparationCompletion({ ...BASE, signatureRequise: null, mutations: mutationsFichierComplet(SHA_PHOTO, 1) });
    expect(resultat).toEqual({ pret: false, raison: "signature_requise_non_choisie" });
  });

  test("signature requise mais aucune capturée -> signature_requise_mais_absente", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, signatureRequise: true, signatureSha256: null });
    expect(resultat).toEqual({ pret: false, raison: "signature_requise_mais_absente" });
  });

  test("fichiers pas encore envoyés (en_cours) -> fichiers_en_cours", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: [blocMutation(SHA_PHOTO, 0, 2, "en_attente")] });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("aucune mutation fichier_bloc du tout -> fichiers_en_cours (non_demarre), jamais pret", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: [] });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("un bloc en échec permanent -> fichiers_en_echec, PRIORITAIRE sur en_cours", () => {
    const mutations = [
      blocMutation(SHA_PHOTO, 0, 2, "envoyee"),
      blocMutation(SHA_PHOTO, 1, 2, "echec_permanent"),
    ];
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_echec" });
  });
});

describe("evaluerPreparationCompletion — prêt : dépendance d'ordre satisfaite (mission item 2)", () => {
  test("checklist + photo complète + pas de signature requise -> pret avec les références serveur", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: mutationsFichierComplet(SHA_PHOTO, 3) });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves).toEqual({
        checklist_complete: true,
        photos_apres: [`fichier:sha256:${SHA_PHOTO}`],
        notes: "Aucun imprévu.",
        signature: null,
      });
    }
  });

  test("plusieurs photos après, TOUTES doivent être complètes", () => {
    const mutations = [...mutationsFichierComplet(SHA_PREMIERE, 1), ...mutationsFichierComplet(SHA_SECONDE, 1)];
    const resultat = evaluerPreparationCompletion({ ...BASE, photosApresSha256: [SHA_PREMIERE, SHA_SECONDE], mutations });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.photos_apres).toEqual([`fichier:sha256:${SHA_PREMIERE}`, `fichier:sha256:${SHA_SECONDE}`]);
    }
  });

  test("une seule des deux photos complète -> pas encore pret", () => {
    const mutations = [...mutationsFichierComplet(SHA_PREMIERE, 1), blocMutation(SHA_SECONDE, 0, 1, "en_attente")];
    const resultat = evaluerPreparationCompletion({ ...BASE, photosApresSha256: [SHA_PREMIERE, SHA_SECONDE], mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("signature requise ET complète -> pret, référence de signature incluse", () => {
    const mutations = [...mutationsFichierComplet(SHA_PHOTO, 1), ...mutationsFichierComplet(SHA_SIGNATURE, 1)];
    const resultat = evaluerPreparationCompletion({
      ...BASE,
      signatureRequise: true,
      signatureSha256: SHA_SIGNATURE,
      mutations,
    });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.signature).toBe(`fichier:sha256:${SHA_SIGNATURE}`);
    }
  });

  test("signature NON requise mais quand même capturée et complète -> envoyée et référencée aussi", () => {
    const mutations = [...mutationsFichierComplet(SHA_PHOTO, 1), ...mutationsFichierComplet(SHA_SIGNATURE, 1)];
    const resultat = evaluerPreparationCompletion({
      ...BASE,
      signatureRequise: false,
      signatureSha256: SHA_SIGNATURE,
      mutations,
    });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.signature).toBe(`fichier:sha256:${SHA_SIGNATURE}`);
    }
  });

  test("signature non requise ET pas capturée -> pret avec signature null (aucun blocage)", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations: mutationsFichierComplet(SHA_PHOTO, 1) });
    expect(resultat.pret).toBe(true);
  });

  test("ignore les mutations d'un AUTRE chantier pour la même empreinte", () => {
    const mutations = mutationsFichierComplet(SHA_PHOTO, 1, "AUTRE-CHANTIER");
    const resultat = evaluerPreparationCompletion({ ...BASE, mutations });
    expect(resultat).toEqual({ pret: false, raison: "fichiers_en_cours" });
  });

  test("notes vide est préservée telle quelle (aucun imprévu = note légitime)", () => {
    const resultat = evaluerPreparationCompletion({ ...BASE, notes: "", mutations: mutationsFichierComplet(SHA_PHOTO, 1) });
    expect(resultat.pret).toBe(true);
    if (resultat.pret) {
      expect(resultat.preuves.notes).toBe("");
    }
  });
});

test("legacy tous envoyee sans reçu lié ne fabrique pas une préparation complète",()=>{
 const anciennes=mutationsFichierComplet(SHA_PHOTO,1).map(m=>({...m,resumeAccepte:null}));
 expect(evaluerPreparationCompletion({...BASE,mutations:anciennes})).toEqual({pret:false,raison:"fichiers_en_cours"});
 expect(anciennes[0].statut).toBe("envoyee");expect(anciennes[0].resumeAccepte).toBeNull();
});
