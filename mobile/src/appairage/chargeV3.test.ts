import { construireChargeAppairageV3, normaliserMetadonneeAppareil } from "./chargeV3";

/**
 * Vecteurs de test TIRÉS TELS QUELS de `core/src/gateway/device-auth.test.ts` et
 * `core/packages/gateway-client/src/browser-device-auth.test.ts` (lus, jamais exécutés — le
 * fichier lui-même n'est ni importé ni exécuté, seules les valeurs littérales ci-dessous en sont
 * recopiées) — mission item 5 : « charge v3 ... vérifiée contre des vecteurs de test tirés du
 * core ». Un octet de différence ici fait échouer l'appairage en vrai
 * (`core/src/gateway/server/ws-connection/connect-device-proof.ts:91-94`), donc ces tests
 * comparent des chaînes ENTIÈRES, jamais des sous-parties.
 */
describe("construireChargeAppairageV3 — vecteurs core/src/gateway/device-auth.test.ts", () => {
  test("charge v3 canonique (device-auth.test.ts:27-41)", () => {
    expect(
      construireChargeAppairageV3({
        deviceId: "dev-1",
        clientId: "openclaw-macos",
        clientMode: "ui",
        role: "operator",
        scopes: ["operator.admin", "operator.read"],
        signedAtMs: 1_700_000_000_000,
        token: "tok-123",
        nonce: "nonce-abc",
        platform: "  IOS  ",
        deviceFamily: "  iPhone  ",
      }),
    ).toBe("v3|dev-1|openclaw-macos|ui|operator|operator.admin,operator.read|1700000000000|tok-123|nonce-abc|ios|iphone");
  });

  test("emplacements vides pour les champs optionnels absents (device-auth.test.ts:42-54)", () => {
    expect(
      construireChargeAppairageV3({
        deviceId: "dev-2",
        clientId: "openclaw-ios",
        clientMode: "ui",
        role: "operator",
        scopes: ["operator.read"],
        signedAtMs: 1_700_000_000_001,
        nonce: "nonce-def",
      }),
    ).toBe("v3|dev-2|openclaw-ios|ui|operator|operator.read|1700000000001||nonce-def||");
  });

  test.each([
    ["  IOS  ", "  iPhone  ", "ios", "iphone"],
  ])("normalisation plateforme/famille %j/%j -> %j/%j", (platform, deviceFamily, plateformeAttendue, familleAttendue) => {
    const charge = construireChargeAppairageV3({
      deviceId: "d",
      clientId: "c",
      clientMode: "ui",
      role: "operator",
      scopes: [],
      signedAtMs: 0,
      nonce: "n",
      platform,
      deviceFamily,
    });
    const segments = charge.split("|");
    expect(segments[9]).toBe(plateformeAttendue);
    expect(segments[10]).toBe(familleAttendue);
  });
});

describe("normaliserMetadonneeAppareil — vecteurs core/src/gateway/device-auth.test.ts:63-70", () => {
  test.each([
    ["  İOS  ", "İos"],
    ["  MAC  ", "mac"],
    [undefined, ""],
  ])("normalise %j -> %j", (entree, attendu) => {
    expect(normaliserMetadonneeAppareil(entree)).toBe(attendu);
  });

  test("ne touche QUE les lettres ASCII A-Z (pas de casse Unicode complète)", () => {
    // "İ" (I majuscule pointé, U+0130) hors A-Z : laissé tel quel, contrairement à un
    // toLowerCase() JS complet qui le changerait — c'est exactement ce que confirme le vecteur
    // core ci-dessus (« İOS » -> « İos », pas « i̇os »).
    expect(normaliserMetadonneeAppareil("İOS")).toBe("İos");
  });

  test("chaîne vide ou blancs seulement -> chaîne vide", () => {
    expect(normaliserMetadonneeAppareil("")).toBe("");
    expect(normaliserMetadonneeAppareil("   ")).toBe("");
  });

  test("valeur non-chaîne (null) -> chaîne vide, fail-closed", () => {
    expect(normaliserMetadonneeAppareil(null)).toBe("");
  });
});

describe("construireChargeAppairageV3 — vecteurs core/packages/gateway-client/src/browser-device-auth.test.ts", () => {
  test("scénario jeton d'appareil stocké (browser-device-auth.test.ts:29-48)", () => {
    const charge = construireChargeAppairageV3({
      deviceId: "device",
      clientId: "openclaw-browser-copilot",
      clientMode: "ui",
      role: "operator",
      scopes: ["operator.admin", "operator.write"],
      signedAtMs: 456,
      token: "test-token-placeholder",
      nonce: "nonce",
      platform: "Chrome",
      deviceFamily: "Extension",
    });
    expect(charge).toBe(
      "v3|device|openclaw-browser-copilot|ui|operator|operator.admin,operator.write|456|test-token-placeholder|nonce|chrome|extension",
    );
  });

  test("scénario jeton d'amorçage préféré (browser-device-auth.test.ts:134-152)", () => {
    const charge = construireChargeAppairageV3({
      deviceId: "device",
      clientId: "openclaw-browser-copilot",
      clientMode: "ui",
      role: "operator",
      scopes: ["operator.read", "operator.write"],
      signedAtMs: 123,
      token: "test-bootstrap-token",
      nonce: "nonce",
      platform: "Chrome",
      deviceFamily: "Extension",
    });
    expect(charge).toBe(
      "v3|device|openclaw-browser-copilot|ui|operator|operator.read,operator.write|123|test-bootstrap-token|nonce|chrome|extension",
    );
  });
});
