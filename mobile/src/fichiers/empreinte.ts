import { encoderHex } from "../appairage/base64url";

/**
 * SHA-256 d'un fichier local (R12 §4 : photos ET signature — « même principe » — référencées par
 * URI + hachage, jamais le binaire lui-même dans une mutation). Module PARTAGÉ par
 * `src/photos/mutation.ts` et `src/signature/mutation.ts` plutôt que dupliqué (AGENTS.md :
 * réutiliser).
 *
 * `expo-crypto` expose deux fonctions de hachage (`node_modules/expo-crypto/build/Crypto.d.ts`,
 * lu) : `digestStringAsync` (hache une CHAÎNE, `options.encoding` ne contrôle QUE le format de
 * SORTIE, jamais l'interprétation de l'entrée) et `digest(algorithm, data: BufferSource):
 * Promise<ArrayBuffer>` (hache des OCTETS BRUTS directement). Seule la seconde permet de hacher
 * le contenu RÉEL d'un fichier binaire sans détour par une chaîne — `digestStringAsync` sur une
 * représentation base64 du fichier hacherait le TEXTE base64, pas les octets, ce qui NE
 * correspondrait PAS au SHA-256 qu'un futur point d'envoi calculerait après décodage. La
 * fonction de hachage est INJECTÉE (`FonctionDigestSha256`, mission item 5 : testable sans
 * `expo-crypto`) ; `encoderHex` est réutilisé de `src/appairage/base64url.ts`, déjà testé.
 */
export type FonctionDigestSha256 = (octets: Uint8Array<ArrayBuffer>) => Promise<ArrayBuffer>;

/** SHA-256 hex minuscule des octets fournis. */
export async function empreinteSha256(octets: Uint8Array<ArrayBuffer>, digest: FonctionDigestSha256): Promise<string> {
  const brut = await digest(octets);
  return encoderHex(new Uint8Array(brut));
}
