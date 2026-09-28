/**
 * Bridage de la capture photo (R12 §4 : « capture bridée (expo-camera), ≈1600 px de long côté,
 * JPEG ~0,8 — même principe de bridage que la commande caméra d'OpenClaw »).
 *
 * `expo-camera` (`CameraPictureOptions`, `node_modules/expo-camera/build/Camera.types.d.ts`, lu)
 * n'offre AUCUNE option de largeur/hauteur maximale ni de redimensionnement — seulement
 * `quality` (0-1) et `imageType` ('jpg'|'png'). Le SEUL levier pour approcher « ≈1600 px de long
 * côté » est de choisir, parmi les résolutions RÉELLEMENT supportées par l'appareil
 * (`CameraView.getAvailablePictureSizesAsync(): Promise<string[]>`, forme "LARGEURxHAUTEUR"), la
 * plus proche de la cible — d'où le « ≈ » de R12 §4, pas une valeur exacte.
 * `expo-image-manipulator` (qui permettrait un vrai redimensionnement post-capture) n'est PAS
 * dans la pile retenue par R12 §3 : ajouter une brique non prévue pour ce seul besoin est hors
 * périmètre de cette tranche.
 */
export const LONG_COTE_CIBLE_PX = 1600;

interface TailleParsee {
  readonly texte: string;
  readonly longCote: number;
}

function analyserTaille(brute: string): TailleParsee | null {
  const correspondance = /^(\d+)x(\d+)$/.exec(brute.trim());
  if (!correspondance) {
    return null;
  }
  const largeur = Number(correspondance[1]);
  const hauteur = Number(correspondance[2]);
  if (!(largeur > 0) || !(hauteur > 0)) {
    return null;
  }
  return { texte: brute, longCote: Math.max(largeur, hauteur) };
}

/**
 * Choisit, parmi `taillesDisponibles`, celle dont le plus long côté est le plus proche de
 * `cible`. `null` si la liste est vide ou qu'aucune entrée n'est reconnue — fail-closed :
 * l'appelant garde alors le `pictureSize` par défaut de l'appareil plutôt que d'en inventer une
 * (`photos.tsx`).
 */
export function choisirTaillePhoto(
  taillesDisponibles: readonly string[],
  cible: number = LONG_COTE_CIBLE_PX,
): string | null {
  let meilleure: TailleParsee | null = null;
  for (const brute of taillesDisponibles) {
    const parsee = analyserTaille(brute);
    if (!parsee) {
      continue;
    }
    if (!meilleure || Math.abs(parsee.longCote - cible) < Math.abs(meilleure.longCote - cible)) {
      meilleure = parsee;
    }
  }
  return meilleure ? meilleure.texte : null;
}
