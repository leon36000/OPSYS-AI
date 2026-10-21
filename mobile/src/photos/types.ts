/** DEFINITION-PRODUIT.md §9.2/§9.3 : « photos avant/pendant/après ». */
export type NaturePhoto = "avant" | "pendant" | "apres";

export const NATURES_PHOTO: readonly NaturePhoto[] = ["avant", "pendant", "apres"];

/**
 * Une photo CAPTURÉE ET DÉJÀ COPIÉE dans le stockage géré par l'app (jamais le chemin
 * temporaire de `expo-camera`, voir `src/photos/service.ts`) — R12 §4 : « le fichier va sur le
 * stockage local … et la ligne de file référence son URI + un hachage SHA-256 + sa cible
 * (job_id, nature) ».
 */
export interface PhotoCapturee {
  readonly uri: string;
  readonly sha256: string;
  readonly tailleOctets: number;
  readonly largeur: number;
  readonly hauteur: number;
  readonly nature: NaturePhoto;
  readonly chantierId: string;
}
