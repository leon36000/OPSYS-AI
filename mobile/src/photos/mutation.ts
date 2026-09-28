import { creerMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { NaturePhoto, PhotoCapturee } from "./types";

/** Photos déjà capturées (mutations `photo_upload` `brouillon`) pour un chantier, TOUTES natures
 * confondues — pour l'affichage des vignettes dans `photos.tsx` (`extraireReferencesPhotosLocales`,
 * `src/m4/preuvesCompletion.ts`, se limite lui à une nature et ne renvoie que des `id`, pas de
 * quoi afficher une vignette). */
export function listerPhotosDuChantier(mutations: readonly MutationOutbox[], chantierId: string): MutationOutbox[] {
  return mutations.filter((m) => m.type === "photo_upload" && m.chantierId === chantierId && m.statut === "brouillon");
}

/**
 * Forme du futur payload `photo_upload` (R12 §4 : « la ligne de file référence son URI + un
 * hachage SHA-256 + sa cible (job_id, nature) »). Snake_case parce que destinée, une fois la
 * route serveur d'envoi du binaire écrite (hors périmètre de cette tranche — voir MOBILE.md), à
 * devenir des arguments d'outil réel. Jamais de binaire ici.
 */
export interface PayloadPhotoUpload {
  readonly intervention_id: string;
  readonly nature: NaturePhoto;
  readonly uri: string;
  readonly sha256: string;
  readonly taille_octets: number;
  readonly largeur: number;
  readonly hauteur: number;
}

export function construirePayloadPhotoUpload(photo: PhotoCapturee): PayloadPhotoUpload {
  return {
    intervention_id: photo.chantierId,
    nature: photo.nature,
    uri: photo.uri,
    sha256: photo.sha256,
    taille_octets: photo.tailleOctets,
    largeur: photo.largeur,
    hauteur: photo.hauteur,
  };
}

/**
 * Construit la mutation `photo_upload` — et la laisse délibérément `brouillon`
 * (`creerMutation` ne produit que ce statut, R12 §4 : « permettre un brouillon local modifiable …
 * avant soumission explicite »). AUCUNE route serveur n'existe encore pour envoyer le binaire de
 * la photo (mission T1.4-e item 2, documenté dans MOBILE.md) : cette fonction n'appelle donc
 * JAMAIS `soumettreMutation` (brouillon -> en_attente). `selectionnerProchainesEnvoyables`
 * (`src/outbox/planification.ts`) n'inclut que `en_attente`/`envoi` — une mutation `photo_upload`
 * reste ainsi PERSISTÉE (survit à un redémarrage, relisible par
 * `src/m4/preuvesCompletion.ts::extraireReferencesPhotosLocales`) sans jamais être proposée au
 * vidangeur. Aucun descripteur `photo_upload` n'est d'ailleurs enregistré dans
 * `src/outbox/descripteurs.ts` (voir son en-tête) : si une future régression soumettait quand
 * même ce type par erreur, le vidangeur échouerait fort (`Error`) plutôt que d'échouer en
 * silence — préférable à un envoi qui prétendrait avoir marché.
 */
export function construireMutationPhotoUpload(
  photo: PhotoCapturee,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  return creerMutation(
    { type: "photo_upload", chantierId: photo.chantierId, payload: { ...construirePayloadPhotoUpload(photo) } },
    genererId,
    horloge,
  );
}
