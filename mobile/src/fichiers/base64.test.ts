// `Buffer` (Node) sert ICI d'oracle indépendant — jamais dans le code d'app (RN/Hermes ne le
// garantit pas), même discipline que `src/appairage/base64url.test.ts`.
/// <reference types="node" />

import { encoderBase64Standard } from "./base64";

describe("encoderBase64Standard", () => {
  test.each([
    [[], ""],
    [[0], "AA=="],
    [[0xff], "/w=="],
    [[0xfb, 0xff, 0x01], "+/8B"],
    [[1, 2, 3, 4, 5], "AQIDBAU="],
  ])("encode %j -> %s", (octets, attendu) => {
    expect(encoderBase64Standard(Uint8Array.from(octets))).toBe(attendu);
  });

  test("contre l'oracle Node Buffer sur 0..300 octets consécutifs", () => {
    const octets = Uint8Array.from({ length: 300 }, (_, i) => i % 256);
    expect(encoderBase64Standard(octets)).toBe(Buffer.from(octets).toString("base64"));
  });

  test("contre l'oracle Node Buffer sur des longueurs 1..40, contenu aléatoire", () => {
    for (let longueur = 1; longueur <= 40; longueur += 1) {
      const octets = Uint8Array.from({ length: longueur }, () => Math.floor(Math.random() * 256));
      expect(encoderBase64Standard(octets)).toBe(Buffer.from(octets).toString("base64"));
    }
  });

  test("alphabet standard : jamais '-'/'_'  (base64url), remplissage '=' présent quand attendu", () => {
    const sortie = encoderBase64Standard(Uint8Array.from([0xfb, 0xff]));
    expect(sortie).not.toMatch(/[-_]/);
    expect(sortie.endsWith("=")).toBe(true);
  });
});
