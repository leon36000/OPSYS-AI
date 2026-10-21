import {
  bindHostChannelContextAdmissionEvidence,
  prepareHostChannelContextAdmissionEvidence,
  readChannelContextAdmissionEvidence,
  recordChannelIngressResolution,
  type ChannelAdmissionAudit,
  type ChannelAdmissionEvidence,
} from "../../src/channels/message-access/admission-evidence.js";
import type { ResolvedChannelMessageIngress } from "../../src/channels/message-access/runtime-types.js";
import type { GatewayRequestContext } from "../../src/gateway/server-methods/types.js";
import { createNativeChannelIngressOwner } from "./native-channel-ingress-owner.js";

export function createTestChannelIngressOwner(params: {
  audit: ChannelAdmissionAudit;
  channelId: string;
}) {
  const gateway = {
    channelAdmissionAudit: params.audit,
    getRuntimeConfig: () => ({}),
  } as GatewayRequestContext;
  return createNativeChannelIngressOwner({
    channelId: params.channelId,
    resolveGatewayContext: () => gateway,
  }).owner;
}

/** Build test evidence through the same host-owned binding path used by channel resolvers. */
export function createChannelParticipantAdmissionEvidence(params: {
  audit: ChannelAdmissionAudit;
  channelId: string;
  accountId?: string;
  participantId: string | number;
  identifierAuthentication?: "affected" | "evaluated" | "not-evaluated";
}): ChannelAdmissionEvidence | undefined {
  return bindTestChannelParticipantAdmissionEvidence({ ...params, context: {} });
}

/** Bind test evidence through an exact resolver result at the host-owned boundary. */
export function bindTestChannelParticipantAdmissionEvidence(params: {
  audit: ChannelAdmissionAudit;
  context: object;
  channelId: string;
  accountId?: string;
  participantId: string | number;
  identifierAuthentication?: "affected" | "evaluated" | "not-evaluated";
}): ChannelAdmissionEvidence | undefined {
  // Synthetic policy result retained for audit-carrier unit tests; H is born natively, not G/R.
  const result = {
    state: {
      conversationKind: "direct",
      event: { kind: "message", authMode: "inbound", mayPair: true },
      routeFacts: [],
    },
    ingress: { admission: "dispatch" },
  } as unknown as ResolvedChannelMessageIngress;
  const owner = createTestChannelIngressOwner(params);
  const ingress = recordChannelIngressResolution({
    result,
    owner,
    channelId: params.channelId,
    accountId: params.accountId,
    rawPrincipalRef: params.participantId,
    participantOutcomeAffecting: false,
    identifierAuthentication: params.identifierAuthentication ?? "not-evaluated",
    scope: {
      conversation: { kind: "direct", id: "test-conversation" },
      contextBinding: {
        agentId: "main",
        sessionKey: "agent:main:test:dm:test-conversation",
        inboundEventKind: "user_request",
      },
    },
  });
  const contextParams = {
    channel: params.channelId,
    accountId: params.accountId,
    sender: { id: params.participantId },
    conversation: { kind: "direct", id: "test-conversation" },
    route: {
      agentId: "main",
      routeSessionKey: "agent:main:test:dm:test-conversation",
    },
    reply: {},
    message: {},
  };
  const preparation = prepareHostChannelContextAdmissionEvidence({
    owner,
    channelId: params.channelId,
    accountId: params.accountId,
    ingress,
    rawPrincipalRef: params.participantId,
    contextParams,
  });
  bindHostChannelContextAdmissionEvidence({ context: params.context, preparation });
  return readChannelContextAdmissionEvidence(params.context);
}
