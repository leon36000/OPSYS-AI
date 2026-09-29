// The OPSYS mobile app's gateway client id and the trust the core gives it (OPSYS-AI PLAN T1.4-c5,
// docs/architecture/MOBILE.md "Identifiant de client").
//
// Two facts are pinned here.
//  1. The connect frame the app really sends (`mobile/src/appairage/client.ts`) is valid with the
//     `opsys-mobile` client id: the app can leave the `openclaw-ios`/`openclaw-android` ids it borrowed.
//  2. `opsys-mobile` is NOT a "native app UI" client. That class (`isNativeAppUiClient`) unlocks silent
//     lanes for OpenClaw's own first-party apps (a silent metadata refresh from a direct-local socket,
//     and the trusted-proxy auto-approval). The OPSYS app needs none of them: a phone pairs through the
//     owner's explicit approval, and its OPSYS identity comes from an explicit attribution. Wiring the
//     id into that class would widen trust for no benefit. If someone does it, this test fails and asks
//     for a decision.
//
// Named without "client" or "server" on purpose: the gateway-core project excludes such file names.
import { describe, expect, it } from "vitest";
import {
  GATEWAY_CLIENT_IDS,
  GATEWAY_CLIENT_MODES,
  normalizeGatewayClientId,
} from "../../packages/gateway-protocol/src/client-info.js";
import { validateConnectParams } from "../../packages/gateway-protocol/src/index.js";
import type { ConnectParams } from "../../packages/gateway-protocol/src/schema.js";
import {
  isNativeAppUiClient,
  shouldAllowSilentLocalPairing,
} from "./server/ws-connection/handshake-auth-helpers.js";

function uiClient(id: string): ConnectParams["client"] {
  return { id, mode: GATEWAY_CLIENT_MODES.UI } as ConnectParams["client"];
}

/** The `connect` params `mobile/src/appairage/client.ts` builds, with fictional key material. */
function appConnectParams(clientId: string) {
  return {
    minProtocol: 4,
    maxProtocol: 4,
    client: { id: clientId, version: "0.1.0", platform: "ios", mode: GATEWAY_CLIENT_MODES.UI },
    role: "operator",
    scopes: ["operator.read", "operator.write"],
    device: {
      id: "0".repeat(64),
      publicKey: "cle-publique-fictive",
      signature: "signature-fictive",
      signedAt: 1_700_000_000_000,
      nonce: "nonce-fictif",
    },
    auth: { bootstrapToken: "jeton-d-amorcage-fictif" },
  };
}

describe("opsys-mobile gateway client id", () => {
  it("is a registered client id, spelled the way the app sends it", () => {
    expect(GATEWAY_CLIENT_IDS.OPSYS_MOBILE).toBe("opsys-mobile");
    expect(normalizeGatewayClientId("opsys-mobile")).toBe(GATEWAY_CLIENT_IDS.OPSYS_MOBILE);
  });

  it("makes the app's connect frame valid, as the borrowed native ids did", () => {
    for (const clientId of [
      GATEWAY_CLIENT_IDS.OPSYS_MOBILE,
      GATEWAY_CLIENT_IDS.IOS_APP,
      GATEWAY_CLIENT_IDS.ANDROID_APP,
    ]) {
      expect(validateConnectParams(appConnectParams(clientId)), clientId).toBe(true);
    }
    expect(validateConnectParams(appConnectParams("opsys-mobil"))).toBe(false);
  });

  it("is not a native app UI client: no silent pairing lane opens for it, local or remote", () => {
    const isNativeAppUi = isNativeAppUiClient(uiClient(GATEWAY_CLIENT_IDS.OPSYS_MOBILE));
    expect(isNativeAppUi).toBe(false);

    // The borrowed ids it replaces are in that class: this is the trust the app deliberately gives up.
    expect(isNativeAppUiClient(uiClient(GATEWAY_CLIENT_IDS.IOS_APP))).toBe(true);
    expect(isNativeAppUiClient(uiClient(GATEWAY_CLIENT_IDS.ANDROID_APP))).toBe(true);

    for (const locality of ["direct_local", "remote"] as const) {
      expect(
        shouldAllowSilentLocalPairing({
          locality,
          hasBrowserOriginHeader: false,
          isControlUi: false,
          isWebchat: false,
          isNativeAppUi,
          reason: "metadata-upgrade",
        }),
        `metadata-upgrade ${locality}`,
      ).toBe(false);
    }
    expect(
      shouldAllowSilentLocalPairing({
        locality: "remote",
        hasBrowserOriginHeader: false,
        isControlUi: false,
        isWebchat: false,
        isNativeAppUi,
        reason: "not-paired",
      }),
    ).toBe(false);
  });
});
