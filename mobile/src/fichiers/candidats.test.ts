import { candidatSignature, candidatsPhotosApres, deduireTypeMimeDepuisUri } from "./candidats";
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
    ...partiel,
  };
}

describe("deduireTypeMimeDepuisUri", () => {
  test.each([
    ["file:///opsys-photos/I1/apres/a.jpg", "image/jpeg"],
    ["file:///opsys-photos/I1/apres/A.JPG", "image/jpeg"],
    ["file:///opsys-photos/I1/apres/a.jpeg", "image/jpeg"],
    ["file:///opsys-signatures/I1/s.png", "image/png"],
    ["file:///opsys-signatures/I1/S.PNG", "image/png"],
  ])("%s -> %s", (uri, attendu) => {
    expect(deduireTypeMimeDepuisUri(uri)).toBe(attendu);
  });

  test.each(["file:///x.svg", "file:///x.bin", "file:///x", "file:///x.heic"])(
    "%s -> null (type non permis par le contrat)",
    (uri) => {
      expect(deduireTypeMimeDepuisUri(uri)).toBeNull();
    },
  );
});

describe("candidatsPhotosApres", () => {
  test("ne retient que les photo_upload brouillon 'apres' du bon chantier, payload complet", () => {
    const mutations: MutationOutbox[] = [
      mutation({
        id: "p1",
        type: "photo_upload",
        chantierId: "I1",
        payload: { nature: "apres", uri: "file:///a.jpg", sha256: "sha-a", taille_octets: 1000 },
      }),
      mutation({ id: "p2", type: "photo_upload", chantierId: "I1", payload: { nature: "avant", uri: "file:///b.jpg", sha256: "sha-b", taille_octets: 500 } }),
      mutation({ id: "p3", type: "photo_upload", chantierId: "I2", payload: { nature: "apres", uri: "file:///c.jpg", sha256: "sha-c", taille_octets: 500 } }),
      mutation({
        id: "p4",
        type: "photo_upload",
        chantierId: "I1",
        statut: "envoyee",
        payload: { nature: "apres", uri: "file:///d.jpg", sha256: "sha-d", taille_octets: 500 },
      }),
    ];
    const candidats = candidatsPhotosApres(mutations, "I1");
    expect(candidats).toEqual([
      { mutationId: "p1", chantierId: "I1", uri: "file:///a.jpg", sha256: "sha-a", tailleOctets: 1000, typeMime: "image/jpeg" },
    ]);
  });

  test("payload corrompu (uri manquant) -> exclu, jamais un candidat inventé", () => {
    const mutations: MutationOutbox[] = [
      mutation({ id: "p1", type: "photo_upload", chantierId: "I1", payload: { nature: "apres", sha256: "sha-a", taille_octets: 1000 } }),
    ];
    expect(candidatsPhotosApres(mutations, "I1")).toEqual([]);
  });

  test("aucune photo -> tableau vide", () => {
    expect(candidatsPhotosApres([], "I1")).toEqual([]);
  });
});

describe("candidatSignature", () => {
  test("null si aucune signature capturée", () => {
    expect(candidatSignature([], "I1")).toBeNull();
  });

  test("renvoie la DERNIÈRE capture brouillon du chantier", () => {
    const mutations: MutationOutbox[] = [
      mutation({ id: "s1", type: "signature_capture", chantierId: "I1", sequence: 1, payload: { uri: "file:///s1.png", sha256: "sha-1", taille_octets: 10 } }),
      mutation({ id: "s2", type: "signature_capture", chantierId: "I1", sequence: 2, payload: { uri: "file:///s2.png", sha256: "sha-2", taille_octets: 20 } }),
      mutation({ id: "s-autre", type: "signature_capture", chantierId: "I2", sequence: 3, payload: { uri: "file:///s3.png", sha256: "sha-3", taille_octets: 30 } }),
    ];
    expect(candidatSignature(mutations, "I1")).toEqual({
      mutationId: "s2",
      chantierId: "I1",
      uri: "file:///s2.png",
      sha256: "sha-2",
      tailleOctets: 20,
      typeMime: "image/png",
    });
  });
});
