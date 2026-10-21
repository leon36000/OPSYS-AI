// Node `crypto` sert ICI d'oracle indépendant pour vérifier l'encodage hex du SHA-256 — jamais
// dans le code d'app (RN/Hermes ne garantit pas `node:crypto`), même discipline que
// `src/appairage/identite.test.ts`.
/// <reference types="node" />

import crypto from "node:crypto";

import { empreinteSha256 } from "./empreinte";
import type { FonctionDigestSha256 } from "./empreinte";

/** Adaptateur de test qui hache réellement (Node `crypto`), pour vérifier la fonction complète
 * — pas seulement un simulacre qui renverrait une valeur toute faite. */
const digestNode: FonctionDigestSha256 = async (octets) => {
  const hachage = crypto.createHash("sha256").update(octets).digest();
  return hachage.buffer.slice(hachage.byteOffset, hachage.byteOffset + hachage.byteLength);
};

describe("empreinteSha256", () => {
  test("vecteur connu : sha256('') = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", async () => {
    const empreinte = await empreinteSha256(new Uint8Array(0), digestNode);
    expect(empreinte).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });

  test("vecteur connu : sha256('abc') = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", async () => {
    const octets = new TextEncoder().encode("abc");
    const empreinte = await empreinteSha256(octets, digestNode);
    expect(empreinte).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  test("deux contenus différents -> deux empreintes différentes", async () => {
    const a = await empreinteSha256(new TextEncoder().encode("photo-1"), digestNode);
    const b = await empreinteSha256(new TextEncoder().encode("photo-2"), digestNode);
    expect(a).not.toBe(b);
  });

  test("même contenu -> même empreinte (déterministe)", async () => {
    const octets = new TextEncoder().encode("même photo");
    const a = await empreinteSha256(octets, digestNode);
    const b = await empreinteSha256(octets, digestNode);
    expect(a).toBe(b);
  });

  test("hex minuscule, longueur 64 (256 bits)", async () => {
    const empreinte = await empreinteSha256(new TextEncoder().encode("x"), digestNode);
    expect(empreinte).toMatch(/^[0-9a-f]{64}$/);
  });
});
