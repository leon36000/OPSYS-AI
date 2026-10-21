// `Buffer` (Node) construit ici les fixtures de code d'appairage — outillage de test seulement.
/// <reference types="node" />

import { ErreurCodeAppairageExpire, decoderCodeAppairage, urlHttpDepuisUrlGateway } from "./codeAppairage";

/**
 * Format confirmé en lisant `core/src/pairing/setup-code.ts:414-494`
 * (`encodePairingSetupCode`/`decodePairingSetupCode`, jamais exécuté ni importé — ADR-0008) :
 * `oc-pair://` + base64url(JSON `{url, urls?, bootstrapToken, expiresAtMs?, tlsFingerprint?}`).
 * Les fixtures ci-dessous encodent avec Node `Buffer` (indépendant de `src/appairage
 * /base64url.ts`, déjà testé ailleurs) pour ne pas boucler sur le code testé.
 */
function encoderCode(charge: unknown): string {
  return Buffer.from(JSON.stringify(charge), "utf8").toString("base64url");
}

const CHARGE_MINIMALE = { url: "wss://grs.exemple.ca:8787", bootstrapToken: "amorce-abc123" };

describe("decoderCodeAppairage — formes valides", () => {
  test("avec le préfixe oc-pair://", () => {
    const resultat = decoderCodeAppairage(`oc-pair://${encoderCode(CHARGE_MINIMALE)}`);
    expect(resultat).toEqual(CHARGE_MINIMALE);
  });

  test("sans préfixe (code copié/collé sans l'URL)", () => {
    const resultat = decoderCodeAppairage(encoderCode(CHARGE_MINIMALE));
    expect(resultat).toEqual(CHARGE_MINIMALE);
  });

  test("préfixe insensible à la casse", () => {
    const resultat = decoderCodeAppairage(`OC-PAIR://${encoderCode(CHARGE_MINIMALE)}`);
    expect(resultat).toEqual(CHARGE_MINIMALE);
  });

  test("espaces de bord ignorés (copier/coller)", () => {
    const resultat = decoderCodeAppairage(`  oc-pair://${encoderCode(CHARGE_MINIMALE)}  `);
    expect(resultat).toEqual(CHARGE_MINIMALE);
  });

  test("ws:// (non chiffré, ex. développement local) accepté au même titre que wss://", () => {
    const charge = { url: "ws://localhost:8787", bootstrapToken: "x" };
    expect(decoderCodeAppairage(encoderCode(charge))).toEqual(charge);
  });

  test("champs optionnels (urls, expiresAtMs futur, tlsFingerprint) propagés", () => {
    const dansLeFutur = Date.now() + 5 * 60_000;
    const charge = {
      url: "wss://grs.exemple.ca",
      urls: ["wss://grs.exemple.ca", "wss://repli.exemple.ca"],
      bootstrapToken: "abc",
      expiresAtMs: dansLeFutur,
      tlsFingerprint: "aa:bb:cc",
    };
    expect(decoderCodeAppairage(encoderCode(charge))).toEqual(charge);
  });
});

describe("decoderCodeAppairage — refus fail-closed", () => {
  test("chaîne vide", () => {
    expect(() => decoderCodeAppairage("")).toThrow();
  });

  test("caractères hors alphabet base64url", () => {
    expect(() => decoderCodeAppairage("oc-pair://not base64url!!")).toThrow();
  });

  test("base64url valide mais pas du JSON", () => {
    expect(() => decoderCodeAppairage(Buffer.from("pas du json", "utf8").toString("base64url"))).toThrow();
  });

  test("JSON valide mais pas un objet (tableau)", () => {
    expect(() => decoderCodeAppairage(encoderCode(["url", "token"]))).toThrow();
  });

  test("url absente", () => {
    expect(() => decoderCodeAppairage(encoderCode({ bootstrapToken: "x" }))).toThrow();
  });

  test("url non-WebSocket (http au lieu de ws)", () => {
    expect(() => decoderCodeAppairage(encoderCode({ url: "https://grs.exemple.ca", bootstrapToken: "x" }))).toThrow();
  });

  test("url avec identifiants intégrés (username:password@) refusée", () => {
    expect(() =>
      decoderCodeAppairage(encoderCode({ url: "wss://user:pass@grs.exemple.ca", bootstrapToken: "x" })),
    ).toThrow();
  });

  test("bootstrapToken absent", () => {
    expect(() => decoderCodeAppairage(encoderCode({ url: "wss://grs.exemple.ca" }))).toThrow();
  });

  test("bootstrapToken vide", () => {
    expect(() => decoderCodeAppairage(encoderCode({ url: "wss://grs.exemple.ca", bootstrapToken: "" }))).toThrow();
  });

  test("urls[] trop longue (> 8)", () => {
    const charge = {
      url: "wss://grs.exemple.ca",
      urls: Array.from({ length: 9 }, (_, i) => `wss://h${i}.exemple.ca`),
      bootstrapToken: "x",
    };
    expect(() => decoderCodeAppairage(encoderCode(charge))).toThrow();
  });

  test("urls[] avec une entrée invalide", () => {
    const charge = { url: "wss://grs.exemple.ca", urls: ["wss://ok.ca", "pas-une-url"], bootstrapToken: "x" };
    expect(() => decoderCodeAppairage(encoderCode(charge))).toThrow();
  });

  test("expiresAtMs non entier", () => {
    expect(() =>
      decoderCodeAppairage(encoderCode({ ...CHARGE_MINIMALE, expiresAtMs: "demain" })),
    ).toThrow();
  });
});

describe("decoderCodeAppairage — expiration (R12 §1.3 : usage unique, 10 min)", () => {
  test("code expiré -> ErreurCodeAppairageExpire, pas une erreur générique", () => {
    const charge = { ...CHARGE_MINIMALE, expiresAtMs: 1_000 };
    expect(() => decoderCodeAppairage(encoderCode(charge), () => new Date(2_000))).toThrow(ErreurCodeAppairageExpire);
  });

  test("code dont l'expiration tombe EXACTEMENT à 'maintenant' est déjà expiré (<=, pas <)", () => {
    const charge = { ...CHARGE_MINIMALE, expiresAtMs: 5_000 };
    expect(() => decoderCodeAppairage(encoderCode(charge), () => new Date(5_000))).toThrow(ErreurCodeAppairageExpire);
  });

  test("code pas encore expiré -> accepté", () => {
    const charge = { ...CHARGE_MINIMALE, expiresAtMs: 5_001 };
    expect(decoderCodeAppairage(encoderCode(charge), () => new Date(5_000))).toEqual(charge);
  });

  test("expiresAtMs absent -> jamais considéré comme expiré", () => {
    expect(decoderCodeAppairage(encoderCode(CHARGE_MINIMALE), () => new Date(8.64e15))).toEqual(CHARGE_MINIMALE);
  });
});

describe("urlHttpDepuisUrlGateway", () => {
  test("wss:// -> https://", () => {
    expect(urlHttpDepuisUrlGateway("wss://grs.exemple.ca:8787/gw")).toBe("https://grs.exemple.ca:8787/gw");
  });

  test("ws:// -> http://", () => {
    expect(urlHttpDepuisUrlGateway("ws://localhost:8787")).toBe("http://localhost:8787");
  });

  test("schéma inattendu -> erreur (fail-closed, jamais une URL devinée)", () => {
    expect(() => urlHttpDepuisUrlGateway("https://grs.exemple.ca")).toThrow();
  });
});
