import { bindCommandOwnerAuthority } from "../../auto-reply/command-owner-authority.js";
import type { MsgContext } from "../../auto-reply/templating.js";
import { prepareSessionParticipantInput } from "../../sessions/session-participant-input.js";
import { takeChannelParticipantInput } from "./admission-evidence.js";
import { readChannelIngressHostOwner, type ChannelIngressHostOwner } from "./ingress-host-owner.js";
import type {
  ChannelIngressContextBinding,
  ResolvedChannelMessageIngress,
} from "./runtime-types.js";

export function bindChannelParticipantInput(params: {
  context: MsgContext;
  channelId: string;
  ingress:
    | ResolvedChannelMessageIngress
    | readonly ResolvedChannelMessageIngress[]
    | "unsupported"
    | undefined;
  binding: ChannelIngressContextBinding;
  owner: ChannelIngressHostOwner;
}): void {
  const owner = params.owner;
  if (readChannelIngressHostOwner(owner) !== "live") {
    return;
  }
  readChannelIngressHostOwner(owner, params.channelId);
  if (!params.ingress || params.ingress === "unsupported") {
    return;
  }
  const resolutions = Array.isArray(params.ingress) ? params.ingress : [params.ingress];
  const batch = resolutions.map(takeChannelParticipantInput);
  // Batched ingress uses the final transport message id; every source keeps its own accepted time.
  if (
    batch.at(-1)?.binding.messageId !== params.binding.messageId ||
    readChannelIngressHostOwner(owner) !== "live" ||
    batch.some(
      (input) =>
        !input ||
        input.owner !== owner ||
        input.gatewayContext !== owner.resolveGatewayContext?.() ||
        input.identity.pluginId !== params.channelId ||
        input.binding.agentId !== params.binding.agentId ||
        input.binding.sessionKey !== params.binding.sessionKey ||
        input.binding.nativeChannelId !== params.binding.nativeChannelId ||
        input.binding.inboundEventKind !== params.binding.inboundEventKind,
    )
  ) {
    return;
  }
  let context: MsgContext | undefined;
  for (const input of batch) {
    if (input) {
      const identity = input.identity;
      const promptedAt = input.promptedAt;
      if (readChannelIngressHostOwner(owner) !== "live") {
        return;
      }
      context ??= params.context;
      if (readChannelIngressHostOwner(owner) !== "live") {
        return;
      }
      const gatewayContext = owner.resolveGatewayContext?.();
      if (
        readChannelIngressHostOwner(owner) !== "live" ||
        input.gatewayContext !== gatewayContext
      ) {
        return;
      }
      prepareSessionParticipantInput(context, identity, promptedAt);
    }
  }
  const principal = batch.at(-1)?.verifiedPrincipal;
  const principalKey = principal && JSON.stringify(principal);
  if (readChannelIngressHostOwner(owner) !== "live") {
    return;
  }
  const gateway = owner.resolveGatewayContext?.();
  if (
    !principal ||
    !gateway ||
    batch.some((input) => JSON.stringify(input?.verifiedPrincipal) !== principalKey)
  ) {
    return;
  }
  const authority = batch.at(-1)?.commandOwnerAuthority;
  if (!authority?.source || readChannelIngressHostOwner(owner) !== "live") {
    return;
  }
  const isCurrent = () => {
    if (readChannelIngressHostOwner(owner) !== "live") {
      return false;
    }
    const currentGateway = owner.resolveGatewayContext?.();
    if (readChannelIngressHostOwner(owner) !== "live" || currentGateway !== gateway) {
      return false;
    }
    const config = gateway.getRuntimeConfig();
    if (readChannelIngressHostOwner(owner) !== "live") {
      return false;
    }
    const current = authority.isCurrent(config);
    if (readChannelIngressHostOwner(owner) !== "live") {
      return false;
    }
    const finalGateway = owner.resolveGatewayContext?.();
    return readChannelIngressHostOwner(owner) === "live" && current && finalGateway === gateway;
  };
  if (!isCurrent() || context === undefined) {
    return;
  }
  bindCommandOwnerAuthority(context, {
    isCurrent,
  });
}
