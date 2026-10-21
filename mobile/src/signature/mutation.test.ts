import { construireMutationSignatureCapture, construirePayloadSignatureCapture } from "./mutation";
import type { SignatureCapturee } from "./mutation";
import { selectionnerProchainesEnvoyables } from "../outbox/planification";

const HORLOGE = { maintenant: new Date("2026-09-28T18:32:00.000Z"), decalageMinutesUTC: -240 };
const SIGNATURE: SignatureCapturee = {
  uri: "file:///opsys-signatures/I1/abc.png",
  sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  tailleOctets: 4321,
  chantierId: "I1",
};

describe("construirePayloadSignatureCapture", () => {
  test("mappe chaque champ, jamais de binaire", () => {
    expect(construirePayloadSignatureCapture(SIGNATURE)).toEqual({
      intervention_id: "I1",
      uri: SIGNATURE.uri,
      sha256: SIGNATURE.sha256,
      taille_octets: 4321,
    });
  });
});

describe("construireMutationSignatureCapture", () => {
  test("type signature_capture, chantierId = intervention, statut brouillon", () => {
    const mutation = construireMutationSignatureCapture(SIGNATURE, () => "sig-1", HORLOGE);
    expect(mutation.type).toBe("signature_capture");
    expect(mutation.chantierId).toBe("I1");
    expect(mutation.statut).toBe("brouillon");
    expect(mutation.payload).toEqual(construirePayloadSignatureCapture(SIGNATURE));
  });

  test("jamais soumise : reste hors de la sélection d'envoi", () => {
    const mutation = construireMutationSignatureCapture(SIGNATURE, () => "sig-1", HORLOGE);
    const inseree = { ...mutation, sequence: 1 };
    expect(selectionnerProchainesEnvoyables([inseree], new Date("2026-09-28T19:00:00.000Z"))).toEqual([]);
  });
});
