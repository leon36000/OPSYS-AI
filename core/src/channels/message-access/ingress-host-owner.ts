import type { PreparedCommandOwnerAuthority } from "../../auto-reply/command-auth.js";
import type { SessionParticipantIdentity } from "../../config/sessions/session-participant-identity.js";
import type { GatewayContextResolver } from "../../gateway/server-methods/types.js";
import { readNativeChannelIngressHostOwner } from "../../plugins/registry-runtime.js";
import type { UserChannelIdentity } from "../../state/user-profiles.types.js";
import type { ChannelIngressContextBinding } from "./runtime-types.js";

export type ChannelIngressHostOwner = Readonly<{
  channelId: string;
  isLive: () => boolean;
  resolveGatewayContext?: GatewayContextResolver;
}>;

/** Classify exact native custody before consulting any structural owner field. */
export function readChannelIngressHostOwner(
  owner: ChannelIngressHostOwner | undefined,
  channelId?: string,
): "absent" | "live" | "closed" {
  if (owner === undefined) {
    return "absent";
  }
  const state = readNativeChannelIngressHostOwner(owner);
  if (channelId !== undefined && owner.channelId !== channelId) {
    throw new Error("Channel ingress host owner does not match the requested channel.");
  }
  return state;
}

export type ChannelParticipantInput = {
  identity: Extract<SessionParticipantIdentity, { type: "remote" | "observation" }>;
  binding: ChannelIngressContextBinding;
  promptedAt: number;
  owner: ChannelIngressHostOwner;
  gatewayContext: ReturnType<GatewayContextResolver>;
  verifiedPrincipal?: UserChannelIdentity;
  commandOwnerAuthority?: PreparedCommandOwnerAuthority;
};
