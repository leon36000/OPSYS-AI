import {
  CLES_PREUVES_COMPLETION,
  construirePreuvesCompletion,
  extraireReferencePhotosApres,
  extraireReferenceSignatureLocale,
  extraireReferencesPhotosLocales,
} from "./preuvesCompletion";
import type { MutationOutbox, TypeMutation } from "../outbox/types";

function mutation(partiel: Partial<MutationOutbox> & { readonly type: TypeMutation; readonly chantierId: string }): MutationOutbox {
  return {
    id: "id-defaut",
    sequence: 1,
    payload: {},
    dependsOn: null,
    statut: "brouillon",
    tentatives: 0,
    createdAtLocal: "2026-09-28T08:00:00-04:00",
    prochaineTentativeA: null,
    proprietaire: null,
    ...partiel,
  };
}

describe("CLES_PREUVES_COMPLETION", () => {
  test("copie exacte du contrat serveur (preuves.py)", () => {
    expect(CLES_PREUVES_COMPLETION).toEqual(["checklist_complete", "photos_apres", "notes", "signature"]);
  });
});

describe("construirePreuvesCompletion", () => {
  test("assemble les quatre clés exactes, rien de plus", () => {
    const preuves = construirePreuvesCompletion({
      checklistComplete: true,
      referencesPhotosApres: ["m1", "m2"],
      notes: "Aucun imprévu.",
      signature: "m-signature",
    });
    expect(Object.keys(preuves).sort()).toEqual([...CLES_PREUVES_COMPLETION].sort());
    expect(preuves).toEqual({
      checklist_complete: true,
      photos_apres: ["m1", "m2"],
      notes: "Aucun imprévu.",
      signature: "m-signature",
    });
  });

  test("signature null (non requise ou pas encore capturée) est préservée telle quelle", () => {
    const preuves = construirePreuvesCompletion({
      checklistComplete: false,
      referencesPhotosApres: [],
      notes: "",
      signature: null,
    });
    expect(preuves.signature).toBeNull();
    expect(preuves.checklist_complete).toBe(false);
    expect(preuves.photos_apres).toEqual([]);
  });

  test("ne mute jamais le tableau fourni par l'appelant", () => {
    const references = ["m1"];
    const preuves = construirePreuvesCompletion({
      checklistComplete: true,
      referencesPhotosApres: references,
      notes: "",
      signature: null,
    });
    expect(preuves.photos_apres).not.toBe(references);
    expect(preuves.photos_apres).toEqual(references);
  });
});

describe("extraireReferencesPhotosLocales", () => {
  test("ne retient que les photo_upload brouillon du bon chantier et de la bonne nature", () => {
    const mutations: MutationOutbox[] = [
      mutation({ id: "p1", type: "photo_upload", chantierId: "I1", payload: { nature: "apres" } }),
      mutation({ id: "p2", type: "photo_upload", chantierId: "I1", payload: { nature: "avant" } }),
      mutation({ id: "p3", type: "photo_upload", chantierId: "I2", payload: { nature: "apres" } }),
      mutation({
        id: "p4",
        type: "photo_upload",
        chantierId: "I1",
        payload: { nature: "apres" },
        statut: "envoyee",
      }),
      mutation({ id: "punch", type: "punch_in", chantierId: "I1", payload: {} }),
    ];
    expect(extraireReferencesPhotosLocales(mutations, "I1", "apres")).toEqual(["p1"]);
  });

  test("aucune photo -> tableau vide, jamais inventé", () => {
    expect(extraireReferencesPhotosLocales([], "I1", "apres")).toEqual([]);
  });
});

describe("extraireReferencePhotosApres", () => {
  test("alias documenté de extraireReferencesPhotosLocales(..., 'apres')", () => {
    const mutations: MutationOutbox[] = [
      mutation({ id: "p1", type: "photo_upload", chantierId: "I1", payload: { nature: "apres" } }),
    ];
    expect(extraireReferencePhotosApres(mutations, "I1")).toEqual(["p1"]);
  });
});

describe("extraireReferenceSignatureLocale", () => {
  test("null si aucune signature capturée", () => {
    expect(extraireReferenceSignatureLocale([], "I1")).toBeNull();
  });

  test("renvoie la dernière capture brouillon du chantier", () => {
    const mutations: MutationOutbox[] = [
      mutation({ id: "s1", type: "signature_capture", chantierId: "I1", sequence: 1 }),
      mutation({ id: "s2", type: "signature_capture", chantierId: "I1", sequence: 2 }),
      mutation({ id: "s-autre-chantier", type: "signature_capture", chantierId: "I2", sequence: 3 }),
      mutation({ id: "s-envoyee", type: "signature_capture", chantierId: "I1", statut: "envoyee", sequence: 4 }),
    ];
    expect(extraireReferenceSignatureLocale(mutations, "I1")).toBe("s2");
  });
});
