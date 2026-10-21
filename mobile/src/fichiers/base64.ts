/**
 * Base64 STANDARD (RFC 4648 §4, alphabet `+/`, remplissage `=`) sur `Uint8Array`, sans
 * dépendance externe et sans supposer que `btoa`/`Buffer` existent dans le moteur JS de
 * l'appareil (Hermes ne les garantit pas) — même raison d'être que
 * `src/appairage/base64url.ts::encoderBase64Url`, alphabet DIFFÉRENT : le CONTRAT FIXE
 * `m4_deposer_fichier` (PLAN T1.4-f) exige `bloc_base64` en « base64 standard », jamais
 * base64url (`src/appairage/base64url.ts` reste réservé à la charge d'appairage v3 — pas
 * réutilisé ici pour ne pas mélanger deux alphabets sous un seul nom).
 *
 * Encodage SEULEMENT : le mobile n'a jamais besoin de décoder du base64 standard reçu du
 * serveur pour ce contrat (`m4_deposer_fichier`/`m4_etat_fichier` ne renvoient que des
 * références textuelles, jamais de binaire — R12 §4).
 */

const ALPHABET_STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function encoderBase64Standard(octets: Uint8Array): string {
  let resultat = "";
  for (let indice = 0; indice < octets.length; indice += 3) {
    const o1 = octets[indice];
    const o2 = octets[indice + 1];
    const o3 = octets[indice + 2];
    resultat += ALPHABET_STANDARD[o1 >> 2];
    resultat += ALPHABET_STANDARD[((o1 & 0x03) << 4) | (o2 === undefined ? 0 : o2 >> 4)];
    resultat += o2 === undefined ? "=" : ALPHABET_STANDARD[((o2 & 0x0f) << 2) | (o3 === undefined ? 0 : o3 >> 6)];
    resultat += o3 === undefined ? "=" : ALPHABET_STANDARD[o3 & 0x3f];
  }
  return resultat;
}
