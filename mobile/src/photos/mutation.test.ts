import { construireMutationPhotoUpload, construirePayloadPhotoUpload, listerPhotosDuChantier } from "./mutation";
import type { PhotoCapturee } from "./types";
import { selectionnerProchainesEnvoyables } from "../outbox/planification";
import type { MutationOutbox } from "../outbox/types";

const HORLOGE = { maintenant: new Date("2026-09-28T18:32:00.000Z"), decalageMinutesUTC: -240 };
const PHOTO: PhotoCapturee = {
  uri: "file:///opsys-photos/I1/apres/abc.jpg",
  sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  tailleOctets: 123_456,
  largeur: 1600,
  hauteur: 1200,
  nature: "apres",
  chantierId: "I1",
};

describe("construirePayloadPhotoUpload", () => {
  test("mappe chaque champ vers le nom snake_case attendu, sans binaire", () => {
    expect(construirePayloadPhotoUpload(PHOTO)).toEqual({
      intervention_id: "I1",
      nature: "apres",
      uri: PHOTO.uri,
      sha256: PHOTO.sha256,
      taille_octets: 123_456,
      largeur: 1600,
      hauteur: 1200,
    });
  });
});

describe("construireMutationPhotoUpload", () => {
  test("type photo_upload, chantierId = intervention, statut brouillon", () => {
    const mutation = construireMutationPhotoUpload(PHOTO, () => "mut-1", HORLOGE);
    expect(mutation.type).toBe("photo_upload");
    expect(mutation.chantierId).toBe("I1");
    expect(mutation.statut).toBe("brouillon");
    expect(mutation.id).toBe("mut-1");
    expect(mutation.payload).toEqual(construirePayloadPhotoUpload(PHOTO));
  });

  test("jamais soumise : une mutation photo_upload en brouillon n'est jamais sélectionnée pour l'envoi", () => {
    const mutation = construireMutationPhotoUpload(PHOTO, () => "mut-1", HORLOGE);
    // sequence null tant qu'elle n'est pas insérée dans un dépôt — mais même une fois "insérée"
    // (sequence posée), un statut brouillon reste hors de la sélection d'envoi.
    const inseree = { ...mutation, sequence: 1 };
    expect(selectionnerProchainesEnvoyables([inseree], new Date("2026-09-28T19:00:00.000Z"))).toEqual([]);
  });
});

describe("listerPhotosDuChantier", () => {
  test("ne retient que les photo_upload brouillon du chantier, toutes natures confondues", () => {
    const mutations: MutationOutbox[] = [
      { ...construireMutationPhotoUpload({ ...PHOTO, nature: "avant" }, () => "p1", HORLOGE), proprietaire: "A" },
      { ...construireMutationPhotoUpload({ ...PHOTO, nature: "apres" }, () => "p2", HORLOGE), proprietaire: "A" },
      construireMutationPhotoUpload({ ...PHOTO, chantierId: "I2" }, () => "p3", HORLOGE),
      { ...construireMutationPhotoUpload(PHOTO, () => "p4", HORLOGE), statut: "envoyee" },
    ];
    expect(listerPhotosDuChantier(mutations, "I1", "A").map((m) => m.id)).toEqual(["p1", "p2"]);
  });
});
