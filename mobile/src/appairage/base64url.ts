/**
 * Base64url (RFC 4648 §5, sans remplissage `=`) sur `Uint8Array`, sans dépendance externe et
 * sans supposer que `btoa`/`atob`/`Buffer` existent dans le moteur JS de l'appareil (Hermes ne
 * les garantit pas). Nécessaire ici parce que le fork encode la clé publique et la signature
 * d'appareil en base64url (`core/src/infra/ed25519-signature.ts`, `base64UrlEncode` = `Buffer
 * .toString("base64url")` côté Node — même alphabet, juste sans le `Buffer` de Node) — voir
 * PLAN T1.4-c3.
 */

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const VALEUR_PAR_CARACTERE: Readonly<Record<string, number>> = Object.fromEntries(
  [...ALPHABET].map((caractere, index) => [caractere, index]),
);

export function encoderBase64Url(octets: Uint8Array): string {
  let resultat = "";
  for (let indice = 0; indice < octets.length; indice += 3) {
    const o1 = octets[indice];
    const o2 = octets[indice + 1];
    const o3 = octets[indice + 2];
    resultat += ALPHABET[o1 >> 2];
    resultat += ALPHABET[((o1 & 0x03) << 4) | (o2 === undefined ? 0 : o2 >> 4)];
    if (o2 !== undefined) {
      resultat += ALPHABET[((o2 & 0x0f) << 2) | (o3 === undefined ? 0 : o3 >> 6)];
    }
    if (o3 !== undefined) {
      resultat += ALPHABET[o3 & 0x3f];
    }
  }
  return resultat;
}

/** Décodage strict : rejette tout caractère hors alphabet (jamais de remplissage `=` attendu). */
export function decoderBase64Url(texte: string): Uint8Array {
  const caracteres = [...texte];
  for (const caractere of caracteres) {
    if (!(caractere in VALEUR_PAR_CARACTERE)) {
      throw new Error(`base64url invalide : caractère inattendu ${JSON.stringify(caractere)}`);
    }
  }
  const octets: number[] = [];
  for (let indice = 0; indice < caracteres.length; indice += 4) {
    const v1 = VALEUR_PAR_CARACTERE[caracteres[indice]];
    const v2 = caracteres[indice + 1] === undefined ? undefined : VALEUR_PAR_CARACTERE[caracteres[indice + 1]];
    const v3 = caracteres[indice + 2] === undefined ? undefined : VALEUR_PAR_CARACTERE[caracteres[indice + 2]];
    const v4 = caracteres[indice + 3] === undefined ? undefined : VALEUR_PAR_CARACTERE[caracteres[indice + 3]];
    if (v2 === undefined) {
      throw new Error("base64url invalide : longueur trop courte");
    }
    octets.push(((v1 << 2) | (v2 >> 4)) & 0xff);
    if (v3 !== undefined) {
      octets.push(((v2 << 4) | (v3 >> 2)) & 0xff);
    }
    if (v4 !== undefined) {
      octets.push(((v3! << 6) | v4) & 0xff);
    }
  }
  return Uint8Array.from(octets);
}

const CARACTERES_HEX = "0123456789abcdef";

/** Hex minuscule — même casse que Node `Buffer#toString("hex")` (core `deriveDeviceIdFromPublicKey`). */
export function encoderHex(octets: Uint8Array): string {
  let resultat = "";
  for (const octet of octets) {
    resultat += CARACTERES_HEX[octet >> 4];
    resultat += CARACTERES_HEX[octet & 0x0f];
  }
  return resultat;
}
