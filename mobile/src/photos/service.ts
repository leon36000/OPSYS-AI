import { Directory, File, Paths } from "expo-file-system";
import * as Crypto from "expo-crypto";

import { listerPhotosDuChantier, construireMutationPhotoUpload } from "./mutation";
import type { NaturePhoto, PhotoCapturee } from "./types";
import { empreinteSha256 } from "../fichiers/empreinte";
import type { FonctionDigestSha256 } from "../fichiers/empreinte";
import { genererMutationId } from "../outbox/id";
import { formaterHorodatageLocal } from "../outbox/mutation";
import { obtenirDepot } from "../outbox/service";
import type { MutationOutbox } from "../outbox/types";
import { capturerSessionMateriauxLecture } from "../protocole/configuration";

/**
 * Câblage RÉEL de la capture photo (`photos.tsx`) : copie le fichier TEMPORAIRE produit par
 * `CameraView.takePictureAsync` (cache système, documenté « temporary » par expo-camera — voir
 * `node_modules/expo-camera/build/CameraView.d.ts`) vers un stockage géré et durable
 * (`Paths.document`, jamais `Paths.cache` : R12 §4 exige que le fichier survive jusqu'à la purge
 * post-confirmation, que le système peut vider `Paths.cache` sans préavis sous pression de
 * stockage), hache le résultat (SHA-256, `src/fichiers/empreinte.ts`), et persiste la mutation
 * `photo_upload` (délibérément `brouillon`, voir `mutation.ts`) dans la file sortante RÉELLE
 * (`src/outbox/service.ts`, même base `expo-sqlite`).
 *
 * Les gardes et courses sont testées avec un stockage natif simulé ; caméra et appareil réels
 * restent à qualifier. Un fichier vérifié ne prouve pas la vérité de la scène photographiée.
 */
const digestSha256Expo: FonctionDigestSha256 = (octets) => Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, octets);

function repertoirePhotos(chantierId: string, nature: NaturePhoto): Directory {
  const repertoire = new Directory(Paths.document, "opsys-photos", chantierId, nature);
  if (!repertoire.exists) {
    repertoire.create({ intermediates: true, idempotent: true });
  }
  return repertoire;
}

export interface ParametresPhotoCapturee {
  /** URI temporaire renvoyé par `CameraView.takePictureAsync` (cache système). */
  readonly uriTemporaire: string;
  readonly largeur: number;
  readonly hauteur: number;
  readonly nature: NaturePhoto;
  readonly chantierId: string;
}

/** Copie + hache + persiste une photo fraîchement capturée. Renvoie la mutation `photo_upload`
 * (brouillon) telle qu'insérée dans la file sortante. */
export async function enregistrerPhotoCapturee(params: ParametresPhotoCapturee, couranteOrigine:()=>boolean=()=>true): Promise<MutationOutbox> {
  const capture = capturerSessionMateriauxLecture(), session = capture.session;
  if (!session || !couranteOrigine() || !capture.courante() || !/^[^/\\?#\p{Cc}\p{Cs}]+$/u.test(params.chantierId) ||
      params.chantierId === "." || params.chantierId === ".." || !params.uriTemporaire.startsWith("file://")) throw new Error("capture_indisponible");
  const cible = { ...params };
  const repertoire = repertoirePhotos(cible.chantierId, cible.nature);
  const destination = new File(repertoire, `${genererMutationId()}.jpg`);
  let insertionCommencee = false;
  const verifier = () => { if (!capture.courante() || !couranteOrigine()) throw new Error("session_changee"); };
  try {
    verifier();
    await new File(cible.uriTemporaire).copy(destination, { overwrite: true }); verifier();
    const octets = await destination.bytes(); verifier();
    const sha256 = await empreinteSha256(octets, digestSha256Expo); verifier();
    const photo: PhotoCapturee = { uri: destination.uri, sha256, tailleOctets: destination.size,
      largeur: cible.largeur, hauteur: cible.hauteur, nature: cible.nature, chantierId: cible.chantierId };
    const maintenant = new Date();
    const mutation = { ...construireMutationPhotoUpload(photo, genererMutationId,
      { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() }), proprietaire: session.personne };
    const depot = await obtenirDepot(); verifier();
    // Une insertion de résultat inconnu peut déjà avoir persisté la ligne : conserver son fichier.
    insertionCommencee = true;
    const inseree = await depot.inserer(mutation); verifier();
    return inseree;
  } catch (erreur) {
    if (!insertionCommencee) { try { if (destination.exists) destination.delete(); } catch { /* Ne jamais purger un autre chemin. */ } }
    throw erreur;
  }
}

/** Photos déjà capturées pour ce chantier (toutes natures), pour les vignettes de `photos.tsx`. */
export async function listerPhotosCapturees(chantierId: string): Promise<MutationOutbox[]> {
  const capture = capturerSessionMateriauxLecture(), session = capture.session;
  if (!session || !capture.courante()) return [];
  const depot = await obtenirDepot(); if (!capture.courante()) return [];
  const toutes = await depot.lister(); if (!capture.courante()) return [];
  return listerPhotosDuChantier(toutes, chantierId, session.personne);
}

// Réexporté pour que `photos.tsx` n'ait besoin d'importer que ce fichier pour le formatage
// d'horodatage d'affichage (même horloge que celle utilisée pour la mutation ci-dessus).
export { formaterHorodatageLocal };
