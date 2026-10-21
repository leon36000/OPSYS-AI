import { creerMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";

/** Même principe que `src/photos/types.ts::PhotoCapturee` : un fichier local DÉJÀ écrit et
 * haché, jamais le binaire lui-même dans une mutation (R12 §4, « même principe » pour la
 * signature que pour les photos). */
export interface SignatureCapturee {
  readonly uri: string;
  readonly sha256: string;
  readonly tailleOctets: number;
  readonly chantierId: string;
}

/** Forme du futur payload `signature_capture` — snake_case, mêmes raisons que
 * `src/photos/mutation.ts::PayloadPhotoUpload`. */
export interface PayloadSignatureCapture {
  readonly intervention_id: string;
  readonly uri: string;
  readonly sha256: string;
  readonly taille_octets: number;
}

export function construirePayloadSignatureCapture(signature: SignatureCapturee): PayloadSignatureCapture {
  return {
    intervention_id: signature.chantierId,
    uri: signature.uri,
    sha256: signature.sha256,
    taille_octets: signature.tailleOctets,
  };
}

/**
 * Construit la mutation `signature_capture` — délibérément `brouillon`, jamais soumise : même
 * limite documentée que `src/photos/mutation.ts::construireMutationPhotoUpload` (aucune route
 * serveur pour envoyer le binaire, aucun descripteur enregistré dans
 * `src/outbox/descripteurs.ts`).
 */
export function construireMutationSignatureCapture(
  signature: SignatureCapturee,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  return creerMutation(
    {
      type: "signature_capture",
      chantierId: signature.chantierId,
      payload: { ...construirePayloadSignatureCapture(signature) },
    },
    genererId,
    horloge,
  );
}
