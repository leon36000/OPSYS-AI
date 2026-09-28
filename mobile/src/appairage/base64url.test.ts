// `Buffer` (Node) sert ICI d'oracle indépendant pour les tests — jamais dans le code d'app
// (`src/appairage/base64url.ts` s'en passe volontairement, RN/Hermes ne le garantit pas).
/// <reference types="node" />

import { decoderBase64Url, encoderBase64Url, encoderHex } from "./base64url";

describe("encoderBase64Url / decoderBase64Url", () => {
  test.each([
    [[], ""],
    [[0], "AA"],
    [[0xff], "_w"],
    [[0xfb, 0xff, 0x01], "-_8B"],
    [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32], "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA"],
  ])("encode %j -> %s", (octets, attendu) => {
    expect(encoderBase64Url(Uint8Array.from(octets))).toBe(attendu);
  });

  test.each([
    ["", []],
    ["AA", [0]],
    ["_w", [0xff]],
    ["-_8B", [0xfb, 0xff, 0x01]],
  ])("decode %s -> %j", (texte, attendu) => {
    expect(Array.from(decoderBase64Url(texte))).toEqual(attendu);
  });

  test("aller-retour sur 256 octets consécutifs", () => {
    const octets = Uint8Array.from({ length: 256 }, (_, i) => i);
    expect(decoderBase64Url(encoderBase64Url(octets))).toEqual(octets);
  });

  test("aller-retour sur des octets aléatoires de longueurs 1..40", () => {
    for (let longueur = 1; longueur <= 40; longueur += 1) {
      const octets = Uint8Array.from({ length: longueur }, () => Math.floor(Math.random() * 256));
      expect(decoderBase64Url(encoderBase64Url(octets))).toEqual(octets);
    }
  });

  test("jamais de remplissage '=' ni de '+'/'/' dans la sortie", () => {
    const octets = Uint8Array.from({ length: 37 }, (_, i) => (i * 7) % 256);
    const encode = encoderBase64Url(octets);
    expect(encode).not.toMatch(/[+/=]/);
  });

  test("rejette un caractère hors alphabet", () => {
    expect(() => decoderBase64Url("a+b")).toThrow(/base64url invalide/);
  });

  test("rejette une longueur tronquée (un seul caractère du dernier groupe)", () => {
    expect(() => decoderBase64Url("A")).toThrow(/base64url invalide/);
  });

  test("concorde avec Buffer#toString('base64url') de Node (oracle indépendant, test uniquement)", () => {
    for (const longueur of [1, 2, 3, 4, 5, 16, 32, 64]) {
      const octets = Uint8Array.from({ length: longueur }, (_, i) => (i * 31 + 7) % 256);
      expect(encoderBase64Url(octets)).toBe(Buffer.from(octets).toString("base64url"));
      expect(Array.from(decoderBase64Url(Buffer.from(octets).toString("base64url")))).toEqual(Array.from(octets));
    }
  });
});

describe("encoderHex", () => {
  test("hex minuscule, comme Node Buffer#toString('hex')", () => {
    const octets = Uint8Array.from([0x00, 0x0f, 0xff, 0xab, 0xcd]);
    expect(encoderHex(octets)).toBe("000fffabcd");
    expect(encoderHex(octets)).toBe(Buffer.from(octets).toString("hex"));
  });

  test("tableau vide -> chaîne vide", () => {
    expect(encoderHex(Uint8Array.from([]))).toBe("");
  });
});
