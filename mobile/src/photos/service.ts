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
import { obtenirSessionEnvoi } from "../protocole/configuration";

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
 * Non testé unitairement : `expo-camera`/`expo-file-system` natifs, même limite que
 * `src/outbox/service.ts`/`src/appairage/stockage.ts`. Chaque étape pure (hachage, choix de
 * taille, construction de mutation) est testée ailleurs.
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
export async function enregistrerPhotoCapturee(params: ParametresPhotoCapturee): Promise<MutationOutbox> {
  const repertoire = repertoirePhotos(params.chantierId, params.nature);
  const destination = new File(repertoire, `${genererMutationId()}.jpg`);
  const source = new File(params.uriTemporaire);
  await source.copy(destination, { overwrite: true });

  const octets = await destination.bytes();
  const sha256 = await empreinteSha256(octets, digestSha256Expo);

  const photo: PhotoCapturee = {
    uri: destination.uri,
    sha256,
    tailleOctets: destination.size,
    largeur: params.largeur,
    hauteur: params.hauteur,
    nature: params.nature,
    chantierId: params.chantierId,
  };

  const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
  const mutation = construireMutationPhotoUpload(photo, genererMutationId, horloge);
  const depot = await obtenirDepot();
  return depot.inserer(mutation);
}

/** Photos déjà capturées pour ce chantier (toutes natures), pour les vignettes de `photos.tsx`. */
export async function listerPhotosCapturees(chantierId: string): Promise<MutationOutbox[]> {
  const depot = await obtenirDepot();
  const toutes = await depot.lister();
  const session = obtenirSessionEnvoi();
  return session ? listerPhotosDuChantier(toutes, chantierId, session.personne) : [];
}

// Réexporté pour que `photos.tsx` n'ait besoin d'importer que ce fichier pour le formatage
// d'horodatage d'affichage (même horloge que celle utilisée pour la mutation ci-dessus).
export { formaterHorodatageLocal };
