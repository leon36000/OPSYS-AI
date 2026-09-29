import { Platform } from "react-native";

import { resoudreInfoClientAppairage } from "./clientInfo";

/**
 * PLAN T1.4-c5 : l'app se présente au core sous son propre identifiant, `opsys-mobile`
 * (`GATEWAY_CLIENT_IDS.OPSYS_MOBILE`, `core/packages/gateway-protocol/src/client-info.ts`), et non plus
 * sous les identifiants `openclaw-ios` / `openclaw-android` qu'elle empruntait. La plateforme voyage
 * dans `platform`. Le core épingle de son côté que cet identifiant est valide au schéma de connexion et
 * n'est PAS de la classe « app native OpenClaw » (`core/src/gateway/opsys-mobile-trust.test.ts`).
 */
describe("resoudreInfoClientAppairage", () => {
  const osOriginal = Platform.OS;
  afterEach(() => {
    Object.defineProperty(Platform, "OS", { value: osOriginal, configurable: true });
  });

  test("iOS -> opsys-mobile, plateforme ios", () => {
    Object.defineProperty(Platform, "OS", { value: "ios", configurable: true });
    expect(resoudreInfoClientAppairage("1.2.3")).toEqual({
      id: "opsys-mobile",
      version: "1.2.3",
      platform: "ios",
      mode: "ui",
    });
  });

  test("Android -> opsys-mobile, plateforme android", () => {
    Object.defineProperty(Platform, "OS", { value: "android", configurable: true });
    expect(resoudreInfoClientAppairage("1.2.3")).toEqual({
      id: "opsys-mobile",
      version: "1.2.3",
      platform: "android",
      mode: "ui",
    });
  });

  test("jamais un identifiant emprunté à une app OpenClaw", () => {
    for (const os of ["ios", "android"]) {
      Object.defineProperty(Platform, "OS", { value: os, configurable: true });
      expect(resoudreInfoClientAppairage("1.0.0").id).not.toMatch(/^openclaw-/);
    }
  });

  test("plateforme non prise en charge (ex. web) -> erreur fail-closed, jamais un id inventé", () => {
    Object.defineProperty(Platform, "OS", { value: "web", configurable: true });
    expect(() => resoudreInfoClientAppairage("1.2.3")).toThrow(/non prise en charge/);
  });
});
