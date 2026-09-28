import { ed25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { utf8ToBytes } from "@noble/hashes/utils.js";

import { decoderBase64Url, encoderBase64Url, encoderHex } from "./base64url";

/**
 * Identité d'appareil Ed25519 (R12 §1.3, §3 ; PLAN T1.4-c3 item 2).
 *
 * Algorithme EXACT confirmé en lisant le fork (jamais exécuté — ADR-0008) :
 * - courbe/signature : Ed25519 pur (EdDSA RFC 8032, sans pré-hachage — Node `crypto.sign(null,
 *   ...)`/`crypto.verify(null, ...)` sur une clé Ed25519), `core/src/infra/ed25519-signature.ts:170-174,199-211`.
 * - identifiant d'appareil : hex minuscule de `sha256(clé publique brute 32 octets)`,
 *   `core/src/infra/device-identity.ts:176-187` (`deriveDeviceIdFromPublicKey`), VÉRIFIÉ par le
 *   serveur à chaque connexion (`core/src/gateway/server/ws-connection/connect-device-proof.ts:64-68` :
 *   `derivedId !== device.id` -> rejet `device-id-mismatch`) — cette dérivation n'est donc pas
 *   un détail, elle est obligatoire pour que l'appairage réussisse.
 * - encodage sur le fil : base64url SANS remplissage, aussi bien pour la clé publique que pour
 *   la signature (`ed25519-signature.ts`, `base64UrlEncode` = `Buffer#toString("base64url")`
 *   côté Node — `src/appairage/base64url.ts` en est l'équivalent sans `Buffer`).
 *
 * Brique de calcul : `@noble/curves` (Ed25519) + `@noble/hashes` (SHA-256), MIT, implémentations
 * JS auditées — inscrites dans `docs/research/INGREDIENTS.md`. La SOURCE d'aléa (graine 32
 * octets) est fournie par l'appelant (`expo-crypto.getRandomBytes`, DÉJÀ une dépendance du
 * projet) plutôt que laissée à la détection interne de `@noble/curves` : ce module ne génère
 * jamais lui-même de hasard, il ne fait QUE la transformation déterministe graine -> paire de
 * clés -> signature (`ed25519.keygen(graine)`/`ed25519.sign`), ce qui le rend testable avec une
 * graine fixe (voir `identite.test.ts`, vecteur croisé avec Node `crypto`).
 *
 * `cleSecreteBase64Url` (la graine, 32 octets) ne doit JAMAIS être journalisée (mission item 2) —
 * aucune fonction de ce module ne l'écrit dans une erreur ni un `console.*`.
 */
export interface IdentiteAppareil {
  readonly deviceId: string;
  readonly publicKeyBase64Url: string;
  readonly cleSecreteBase64Url: string;
}

/** Port de `deriveDeviceIdFromPublicKey` (`device-identity.ts:176-187`) : hex minuscule de
 * `sha256(clé publique brute)`. Doit matcher OCTET PAR OCTET ce que le serveur recalcule. */
export function deriverIdAppareil(publicKey: Uint8Array): string {
  return encoderHex(sha256(publicKey));
}

/** Reconstruit une identité complète à partir d'une graine Ed25519 de 32 octets (chargée depuis
 * `expo-secure-store`, ou fraîchement générée). Pure et déterministe : aucun accès stockage ni
 * réseau ici (mission item 5, testabilité). */
export function creerIdentiteDepuisGraine(graine: Uint8Array): IdentiteAppareil {
  if (graine.length !== 32) {
    throw new Error("graine Ed25519 invalide : 32 octets attendus");
  }
  const paire = ed25519.keygen(graine);
  return {
    deviceId: deriverIdAppareil(paire.publicKey),
    publicKeyBase64Url: encoderBase64Url(paire.publicKey),
    cleSecreteBase64Url: encoderBase64Url(paire.secretKey),
  };
}

/** Équivalent, à partir de la forme stockée (base64url) plutôt que des octets bruts. */
export function chargerIdentiteDepuisCleSecrete(cleSecreteBase64Url: string): IdentiteAppareil {
  return creerIdentiteDepuisGraine(decoderBase64Url(cleSecreteBase64Url));
}

/**
 * Signe une charge d'appairage (v3 ou toute autre chaîne) avec la clé secrète fournie et rend la
 * signature encodée en base64url — forme exacte attendue par `ConnectParams.device.signature`
 * (`core/packages/gateway-protocol/src/schema/frames.ts`, `device: closedObject({..., signature:
 * NonEmptyString, ...})`).
 */
export function signerAvecCleSecrete(cleSecreteBase64Url: string, charge: string): string {
  const cleSecrete = decoderBase64Url(cleSecreteBase64Url);
  const message = utf8ToBytes(charge);
  const signature = ed25519.sign(message, cleSecrete);
  return encoderBase64Url(signature);
}
