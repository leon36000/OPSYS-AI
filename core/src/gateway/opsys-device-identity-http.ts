// OPSYS device identity read (OPSYS-AI PLAN T1.4-c5, docs/architecture/MOBILE.md "Identité de
// l'appareil"): `GET /opsys/identite` tells a paired OPSYS mobile app WHICH OPSYS person and WHICH
// named role (`admin`, `employee`, `seller`) its device is attributed to.
//
// Why an authenticated HTTP read and not a field of the WebSocket `hello-ok`:
//  - the attribution is made AFTER the owner's native approval of the pairing (`opsys metier appareils
//    appairer`), so `hello-ok` cannot carry an identity the device does not have yet, and the app
//    closes its socket right after pairing and never reconnects over WebSocket;
//  - the app can ask again at every start and every return to the foreground with the device token
//    it already holds, which is also how it learns of a revoked or re-attributed device;
//  - `hello-ok` is the frozen Wire v4 frame shared by every gateway client.
//
// Trust: the identity comes from the device token VERIFIED by the same chain `/tools/invoke` uses
// (`allowDeviceToken`), and from `opsys/appareils.json` through the same code the tool door uses
// (`opsys-device-roles.ts`). Nothing the app sends (query, header, body) is read: a caller cannot ask
// for another device's identity. The shared secret carries no device identity and gets none. A device
// with no attribution (never attributed, or revoked) or with a role `roles.json` does not declare
// gets a clear refusal and no identity at all, never a default one.
import type { IncomingMessage, ServerResponse } from "node:http";
import { sendJson, sendMethodNotAllowed } from "./http-common.js";
import type { GatewayHttpRequestAuthOptions } from "./http-request-authority.js";
import {
  authorizeScopedGatewayHttpRequestOrReply,
  resolveToolsInvokeHttpOperatorScopes,
} from "./http-utils.js";
import { resolveOpsysDeviceIdentity } from "./opsys-device-roles.js";

/** The route `server-http.ts` mounts this handler on (its stage compares the same literal). */
export const OPSYS_DEVICE_IDENTITY_PATH = "/opsys/identite";

/** The closed set of refusal reasons (`error.reason`); the app fails closed on any other value. */
const REFUSAL_MESSAGES = {
  device_required: "This request carries no device identity; only a paired device has one.",
  device_unknown: "This device is not attributed to an OPSYS person (never attributed, or revoked).",
  role_unknown: "The role attributed to this device is not a role this gateway declares.",
} as const;

function sendIdentityRefusal(res: ServerResponse, reason: keyof typeof REFUSAL_MESSAGES): void {
  sendJson(res, 403, {
    ok: false,
    error: { type: "forbidden", reason, message: REFUSAL_MESSAGES[reason] },
  });
}

/** Handle `GET /opsys/identite` and return false when another HTTP route should handle the request. */
export async function handleOpsysDeviceIdentityHttpRequest(
  req: IncomingMessage,
  res: ServerResponse,
  opts: GatewayHttpRequestAuthOptions,
): Promise<boolean> {
  let url: URL;
  try {
    url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  } catch {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "bad_request", message: "Invalid request URL" }));
    return true;
  }
  if (url.pathname !== OPSYS_DEVICE_IDENTITY_PATH) {
    return false;
  }
  if (req.method !== "GET") {
    sendMethodNotAllowed(res, "GET");
    return true;
  }

  // Same authentication as `/tools/invoke`: a paired device's own token is accepted, and its scopes are
  // capped to what that device was granted. `health` is a read-scoped method: the identity read needs
  // `operator.read` and nothing more.
  const authResult = await authorizeScopedGatewayHttpRequestOrReply({
    ...opts,
    req,
    res,
    operatorMethod: "health",
    resolveOperatorScopes: resolveToolsInvokeHttpOperatorScopes,
    allowDeviceToken: true,
  });
  if (!authResult) {
    return true;
  }
  const { requestAuth } = authResult;
  try {
    // Set only from a verified device-token match, never from the request (see `checkGatewayHttpRequestAuth`).
    const deviceId = requestAuth.authMethod === "device-token" ? requestAuth.deviceId : undefined;
    // The identity is per caller and never cacheable by an intermediary.
    res.setHeader("Cache-Control", "no-store");
    if (!deviceId) {
      sendIdentityRefusal(res, "device_required");
      return true;
    }
    await requestAuth.revalidate();
    const identity = resolveOpsysDeviceIdentity(deviceId);
    if (!identity.ok) {
      sendIdentityRefusal(res, identity.reason);
      return true;
    }
    sendJson(res, 200, {
      ok: true,
      identite: { appareilId: deviceId, personne: identity.personne, role: identity.role },
    });
  } catch (error) {
    if (!res.writableEnded && !res.destroyed) {
      throw error;
    }
  }
  return true;
}
