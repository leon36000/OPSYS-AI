import { createHash } from "node:crypto";
import { normalizeDeviceAuthScopes } from "../shared/device-auth.js";
import { resolveNodePairingState } from "./device-pairing-identity.js";
import type {
  DevicePairingBindingFact,
  OperatorGrantProjection,
} from "./device-pairing-read.types.js";
import type { PairedDevice } from "./device-pairing.types.js";

/** Security-only operator projection. Never exposes the token or tracks last use. */
export function projectOperatorGrant(device: PairedDevice | null): OperatorGrantProjection | null {
  const token = device?.tokens?.operator;
  if (!device || !token || token.revokedAtMs || typeof token.token !== "string") {
    return null;
  }
  const digest = (value: string) => createHash("sha256").update(value).digest("hex");
  const normalized = (scopes: string[] | undefined) =>
    Array.isArray(scopes) ? normalizeDeviceAuthScopes(scopes) : null;
  const approved =
    normalized(device.approvedScopes ?? device.scopes)?.filter((scope) =>
      scope.startsWith("operator."),
    ) ?? null;
  const clientId = device.clientId?.trim().toLowerCase();
  const browser =
    device.clientMode?.trim().toLowerCase() === "webchat" ||
    clientId === "openclaw-control-ui" ||
    clientId === "webchat-ui";
  const tokenHash = digest(token.token);
  return {
    tokenHash,
    securityHash: digest(
      JSON.stringify({
        tokenHash,
        scopes: normalized(token.scopes),
        approved,
        issuer: token.issuer ?? null,
        browser: token.issuer ? false : browser,
      }),
    ),
  };
}

export function prepareDevicePairingBinding(
  deviceId: string,
  device: PairedDevice | null,
): DevicePairingBindingFact {
  const state = resolveNodePairingState(device);
  return {
    deviceId,
    operatorGrant: projectOperatorGrant(device),
    binding: state
      ? {
          identity: state.identity.key,
          ...(state.generation ? { generation: state.generation.key } : {}),
        }
      : null,
  };
}
