import { Platform } from "react-native";

import { resoudreInfoClientAppairage } from "./clientInfo";

/**
 * `core/packages/gateway-protocol/src/client-info.ts:10-29` : `GATEWAY_CLIENT_IDS` est un
 * catalogue fermé, sans identifiant OPSYS. Ce test fige la limite documentée dans
 * `docs/architecture/MOBILE.md` (§ Appairage) : on emprunte `openclaw-ios`/`openclaw-android`
 * selon `Platform.OS`, jamais une valeur inventée qui échouerait la validation de schéma côté
 * fork (`ConnectParamsSchema`, `client.id` requis, valeurs fermées).
 */
describe("resoudreInfoClientAppairage", () => {
  const osOriginal = Platform.OS;
  afterEach(() => {
    Object.defineProperty(Platform, "OS", { value: osOriginal, configurable: true });
  });

  test("iOS -> openclaw-ios", () => {
    Object.defineProperty(Platform, "OS", { value: "ios", configurable: true });
    expect(resoudreInfoClientAppairage("1.2.3")).toEqual({
      id: "openclaw-ios",
      version: "1.2.3",
      platform: "ios",
      mode: "ui",
    });
  });

  test("Android -> openclaw-android", () => {
    Object.defineProperty(Platform, "OS", { value: "android", configurable: true });
    expect(resoudreInfoClientAppairage("1.2.3")).toEqual({
      id: "openclaw-android",
      version: "1.2.3",
      platform: "android",
      mode: "ui",
    });
  });

  test("plateforme non prise en charge (ex. web) -> erreur fail-closed, jamais un id inventé", () => {
    Object.defineProperty(Platform, "OS", { value: "web", configurable: true });
    expect(() => resoudreInfoClientAppairage("1.2.3")).toThrow(/non prise en charge/);
  });
});
