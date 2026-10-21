// Node `crypto` sert ICI d'oracle indépendant pour le vecteur de test croisé — jamais dans le
// code d'app (`src/appairage/identite.ts` utilise `@noble/curves`/`@noble/hashes`, RN/Hermes ne
// garantit pas le module `node:crypto`).
/// <reference types="node" />

import crypto from "node:crypto";

import { decoderBase64Url, encoderBase64Url } from "./base64url";
import {
  chargerIdentiteDepuisCleSecrete,
  creerIdentiteDepuisGraine,
  deriverIdAppareil,
  signerAvecCleSecrete,
} from "./identite";

/**
 * `@noble/curves`/`@noble/hashes` (MIT) contre Node `crypto` — PAS contre le code de `core/`
 * (jamais exécuté ici, ADR-0008). Le vecteur ci-dessous a été produit UNE FOIS par un script
 * jetable (`node -e ...`, voir le rapport final de PLAN T1.4-c3) qui vérifiait déjà, à cet
 * instant-là, que `@noble/curves` `ed25519.sign` produit EXACTEMENT (octet pour octet) la même
 * signature que Node `crypto.sign(null, ...)` sur une clé Ed25519 PEM construite avec les
 * préfixes DER lus dans `core/src/infra/ed25519-signature.ts:4-5`
 * (`ED25519_SPKI_PREFIX`/`ED25519_PKCS8_PRIVATE_PREFIX`) — c'est-à-dire le MÊME algorithme que
 * celui que `core/src/infra/ed25519-signature.ts:170-174,199-211` utilise pour signer/vérifier
 * (`signEd25519Payload`/`verifyEd25519Signature`). Ce test-ci refait la même vérification
 * croisée EN DIRECT (avec Node `crypto`, jamais avec du code de `core/`), pour que la preuve
 * survive un changement de version de `@noble/curves` plutôt que de dépendre d'une valeur figée
 * qui se contenterait de ne jamais bouger.
 */

const SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");
const PKCS8_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

function pemPublique(publicKeyRaw: Buffer): string {
  const der = Buffer.concat([SPKI_PREFIX, publicKeyRaw]);
  return `-----BEGIN PUBLIC KEY-----\n${der.toString("base64").match(/.{1,64}/g)!.join("\n")}\n-----END PUBLIC KEY-----\n`;
}

function pemPrivee(graine: Buffer): string {
  const der = Buffer.concat([PKCS8_PREFIX, graine]);
  return `-----BEGIN PRIVATE KEY-----\n${der.toString("base64").match(/.{1,64}/g)!.join("\n")}\n-----END PRIVATE KEY-----\n`;
}

const GRAINE_TEST = Buffer.from("0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20", "hex");
const MESSAGE_TEST =
  "v3|deadbeef|openclaw-ios|ui|operator|operator.read|1700000000000|bootstrap-abc|nonce-xyz||";

describe("creerIdentiteDepuisGraine / signerAvecCleSecrete — vecteur croisé Node crypto (Ed25519)", () => {
  test("la clé publique dérivée d'une graine fixe est stable et vérifiable par Node crypto", () => {
    const identite = creerIdentiteDepuisGraine(new Uint8Array(GRAINE_TEST));
    const publicKeyRaw = Buffer.from(decoderBase64Url(identite.publicKeyBase64Url));
    expect(publicKeyRaw).toHaveLength(32);

    // Node accepte cette clé (donc : encodage SPKI/DER cohérent avec ed25519-signature.ts).
    const cleNode = crypto.createPublicKey(pemPublique(publicKeyRaw));
    expect(cleNode.asymmetricKeyType).toBe("ed25519");

    // Valeur figée en plus du calcul dynamique ci-dessus : casse si l'algorithme change.
    expect(identite.publicKeyBase64Url).toBe("ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ");
  });

  test("deviceId = sha256(clé publique brute) en hex — core/src/infra/device-identity.ts:176-187", () => {
    const identite = creerIdentiteDepuisGraine(new Uint8Array(GRAINE_TEST));
    const publicKeyRaw = Buffer.from(decoderBase64Url(identite.publicKeyBase64Url));

    expect(identite.deviceId).toBe(crypto.createHash("sha256").update(publicKeyRaw).digest("hex"));
    expect(identite.deviceId).toBe(deriverIdAppareil(new Uint8Array(publicKeyRaw)));
    // Valeur figée.
    expect(identite.deviceId).toBe("65b60673d6ed884bf01c2c222d82ada0740f29ac3355d6a925c81f17f47a27b8".slice(0, 64));
  });

  test("la signature @noble/curves est BYTE POUR BYTE identique à Node crypto.sign(null, ...)", () => {
    const identite = creerIdentiteDepuisGraine(new Uint8Array(GRAINE_TEST));
    const signatureBase64Url = signerAvecCleSecrete(identite.cleSecreteBase64Url, MESSAGE_TEST);
    const signatureOctets = Buffer.from(decoderBase64Url(signatureBase64Url));
    expect(signatureOctets).toHaveLength(64);

    const cleNode = crypto.createPrivateKey(pemPrivee(GRAINE_TEST));
    const signatureNode = crypto.sign(null, Buffer.from(MESSAGE_TEST, "utf8"), cleNode);
    expect(signatureOctets.equals(signatureNode)).toBe(true);

    // Et Node VÉRIFIE cette même signature avec la clé publique dérivée — exactement
    // `verifyEd25519Signature` (`core/src/infra/ed25519-signature.ts:199-211`, algorithme
    // identique, appelé directement ici avec Node crypto plutôt qu'en import de core/).
    const publicKeyRaw = Buffer.from(decoderBase64Url(identite.publicKeyBase64Url));
    const ok = crypto.verify(null, Buffer.from(MESSAGE_TEST, "utf8"), crypto.createPublicKey(pemPublique(publicKeyRaw)), signatureOctets);
    expect(ok).toBe(true);

    // Valeur figée.
    expect(signatureBase64Url).toBe(
      "2M5Hc_X1BmkhQwMsTo8NJmPjmYI_fPVxuiaWHMF3QODUpYQShT40FgrK6zsQFacs12_NNNaBr1CdCrMXt8waDw",
    );
  });

  test("chargerIdentiteDepuisCleSecrete restitue exactement la même identité que creerIdentiteDepuisGraine", () => {
    const depuisGraine = creerIdentiteDepuisGraine(new Uint8Array(GRAINE_TEST));
    const depuisCle = chargerIdentiteDepuisCleSecrete(depuisGraine.cleSecreteBase64Url);
    expect(depuisCle).toEqual(depuisGraine);
  });

  test("deux graines différentes donnent des identités différentes", () => {
    const a = creerIdentiteDepuisGraine(Uint8Array.from({ length: 32 }, () => 1));
    const b = creerIdentiteDepuisGraine(Uint8Array.from({ length: 32 }, () => 2));
    expect(a.deviceId).not.toBe(b.deviceId);
    expect(a.publicKeyBase64Url).not.toBe(b.publicKeyBase64Url);
    expect(a.cleSecreteBase64Url).not.toBe(b.cleSecreteBase64Url);
  });

  test("une graine de longueur incorrecte est refusée (fail-closed)", () => {
    expect(() => creerIdentiteDepuisGraine(new Uint8Array(31))).toThrow(/32 octets/);
    expect(() => creerIdentiteDepuisGraine(new Uint8Array(33))).toThrow(/32 octets/);
  });

  test("la signature ne journalise jamais la clé secrète dans un message d'erreur", () => {
    // Contrat mission item 2 : on vérifie qu'une graine invalide (chemin d'erreur le plus
    // probable) ne fait PAS fuiter la clé encodée dans le message levé.
    let capture: string | null = null;
    try {
      creerIdentiteDepuisGraine(new Uint8Array(10));
    } catch (erreur) {
      capture = erreur instanceof Error ? erreur.message : String(erreur);
    }
    expect(capture).not.toBeNull();
    expect(capture).not.toContain(encoderBase64Url(new Uint8Array(10)));
  });
});
