// `crypto` (Node) sert ICI d'oracle indépendant pour hacher réellement — jamais dans le code
// d'app (RN/Hermes ne le garantit pas), même discipline que `src/fichiers/empreinte.test.ts`.
/// <reference types="node" />

import crypto from "node:crypto";

import { verifierEmpreinteFichier } from "./verification";
import type { FonctionDigestSha256 } from "./empreinte";

const digestNode: FonctionDigestSha256 = async (octets) => {
  const hachage = crypto.createHash("sha256").update(octets).digest();
  return hachage.buffer.slice(hachage.byteOffset, hachage.byteOffset + hachage.byteLength);
};

describe("verifierEmpreinteFichier", () => {
  test("octets inchangés depuis la capture -> ok", async () => {
    const octets = new TextEncoder().encode("contenu-photo") as Uint8Array<ArrayBuffer>;
    const sha256Capture = crypto.createHash("sha256").update(octets).digest("hex");
    const resultat = await verifierEmpreinteFichier(octets, sha256Capture, digestNode);
    expect(resultat).toEqual({ ok: true });
  });

  test("octets modifiés depuis la capture -> discordance explicite, jamais un envoi silencieux", async () => {
    const octetsRelus = new TextEncoder().encode("contenu-modifie") as Uint8Array<ArrayBuffer>;
    const sha256CaptureFictif = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    const resultat = await verifierEmpreinteFichier(octetsRelus, sha256CaptureFictif, digestNode);
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.sha256Capture).toBe(sha256CaptureFictif);
      expect(resultat.sha256Relu).not.toBe(sha256CaptureFictif);
    }
  });

  test("fichier vide relu alors qu'une empreinte non vide était attendue -> discordance", async () => {
    const resultat = await verifierEmpreinteFichier(
      new Uint8Array(0) as Uint8Array<ArrayBuffer>,
      "abc123",
      digestNode,
    );
    expect(resultat.ok).toBe(false);
  });
});
