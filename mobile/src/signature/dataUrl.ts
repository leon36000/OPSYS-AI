/**
 * `react-native-signature-canvas` rend sa capture via `onOK(signature: string)` — une DataURL
 * (`node_modules/react-native-signature-canvas/index.d.ts`, `DataURL = string`, `imageType:
 * "image/png" | "image/jpeg" | "image/svg+xml"`), forme standard `data:<mimeType>;base64,<...>`.
 * Fonction PURE de décodage, testable sans WebView (voir `signature.tsx` : la brique elle-même
 * n'est pas testable sous Jest, seule sa sortie l'est — mission, item « si … pose un problème de
 * test, isole la logique en fonctions pures »).
 */
export interface DataUrlDecodee {
  readonly mimeType: string;
  readonly base64: string;
}

const MOTIF_DATA_URL = /^data:([^;,]+);base64,(.+)$/s;

/** `null` si la chaîne n'est pas une DataURL base64 reconnaissable, ou si la partie base64 est
 * vide (signature non tracée — `react-native-signature-canvas` appelle alors `onEmpty`, pas
 * `onOK`, mais on reste défensif) — fail-closed, jamais un fichier vide écrit en silence. */
export function decoderDataUrl(dataUrl: string): DataUrlDecodee | null {
  const correspondance = MOTIF_DATA_URL.exec(dataUrl.trim());
  if (!correspondance) {
    return null;
  }
  const [, mimeType, base64] = correspondance;
  if (base64.trim() === "") {
    return null;
  }
  return { mimeType, base64 };
}

const EXTENSIONS_CONNUES: Readonly<Record<string, string>> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/svg+xml": "svg",
};

/** `"bin"` pour un type MIME non reconnu (`react-native-signature-canvas` n'en propose que
 * trois, mais on ne suppose jamais qu'un tiers respectera la liste fermée) — jamais un plantage
 * sur un nom de fichier. */
export function extensionDepuisMimeType(mimeType: string): string {
  return EXTENSIONS_CONNUES[mimeType] ?? "bin";
}
