import type { DecisionReceiptV1 } from "../../../packages/gateway-protocol/src/index.js";
import type { GatewayContextResolver } from "../../gateway/server-methods/types.js";
import type { ChannelAdmissionDecisionReceiptInput } from "./admission-decision-receipt.js";
import type { ChannelIngressResolutionScope } from "./admission-evidence-scope-key.js";
import type { ChannelIngressHostOwner, ChannelParticipantInput } from "./ingress-host-owner.js";
import type {
  ChannelIngressContextBinding,
  ResolvedChannelMessageIngress,
} from "./runtime-types.js";

export type ChannelAdmissionEvidence = Readonly<{
  kind: "channel-admission-evidence";
}>;

export type ChannelAdmissionContribution = Readonly<{
  participant:
    | { state: "present"; rawPrincipalRef: string }
    | { state: "unknown" }
    | { state: "unsupported" };
  decision?: Readonly<{
    participantAware: boolean;
    outcomeAffecting: boolean;
    identifierAuthentication: "affected" | "evaluated" | "not-evaluated";
  }>;
}>;

export type ChannelAdmissionEvidencePayload =
  | Readonly<{
      kind: "leaf";
      createdAt: number;
      contribution: ChannelAdmissionContribution;
    }>
  | Readonly<{
      kind: "aggregate";
      createdAt: number;
      sources: readonly (ChannelAdmissionEvidence | undefined)[];
    }>;

export type ConsumedChannelAdmissionEvidence = Readonly<{
  ingressState: "present" | "unknown" | "unsupported";
  invoker: { state: "present"; kind: "person"; rawPrincipalRef: string } | { state: "unknown" };
  assuranceRef?: string;
  decisionCoverage?: "enforced" | "attribution-only" | "unknown" | "unsupported";
  identifierAuthentication?: "affected" | "evaluated" | "not-evaluated" | "unknown";
}>;

export type ChannelIngressResolutionBinding = Readonly<{
  channelId: string;
  accountId?: string;
  rawPrincipalRef: string | number | null | undefined;
  participantOutcomeAffecting: boolean;
  identifierAuthentication: "affected" | "evaluated" | "not-evaluated";
  owner?: ChannelIngressHostOwner;
  gatewayContext?: ReturnType<GatewayContextResolver>;
  scope?: ChannelIngressResolutionScope;
  contextBinding?: Readonly<ChannelIngressContextBinding>;
  publicScopeKey?: string;
  handoff: { consumed: boolean; accepted?: boolean };
}>;

export type ContextAdmissionValue = {
  scope: string | undefined;
  evidence: ChannelAdmissionEvidence | undefined;
  resolver?: GatewayContextResolver;
  resolverConflict?: boolean;
};
export type RequiredSmsTask = Readonly<{
  owner: object;
  scope: string | undefined;
  poisoned: boolean;
}>;

export type AdmissionAuditOptions = {
  enabled: boolean;
  decisionSink?: (receipt: DecisionReceiptV1) => boolean;
};

export type ParticipantContributionInput = {
  channelId: string;
  accountId?: string;
  rawPrincipalRef: string | number | null | undefined;
};

export type IngressResolutionInput = {
  result: ResolvedChannelMessageIngress;
  owner?: ChannelIngressHostOwner;
  participantInput?: ChannelParticipantInput;
  channelId: string;
  accountId?: string;
  rawPrincipalRef: string | number | null | undefined;
  participantOutcomeAffecting: boolean;
  identifierAuthentication: "affected" | "evaluated" | "not-evaluated";
  scope: ChannelIngressResolutionScope;
};

export type PrepareHostAdmissionInput = {
  owner?: ChannelIngressHostOwner;
  channelId: string;
  accountId?: string;
  ingress?:
    | ResolvedChannelMessageIngress
    | readonly ResolvedChannelMessageIngress[]
    | "unsupported";
  rawPrincipalRef: string | number | null | undefined;
  contextParams: object;
};

export type AdmissionContributionRead = {
  evidence: ChannelAdmissionEvidence | undefined;
  now: number;
  seen: Set<object>;
};

export type AdmissionDecisionInput = {
  contextId: ChannelAdmissionDecisionReceiptInput["contextId"];
  executionId: ChannelAdmissionDecisionReceiptInput["executionId"];
  runId: ChannelAdmissionDecisionReceiptInput["runId"];
  occurredAt: ChannelAdmissionDecisionReceiptInput["occurredAt"];
  coverageState: ChannelAdmissionDecisionReceiptInput["coverageState"];
  identifierAuthentication: ChannelAdmissionDecisionReceiptInput["identifierAuthentication"];
};
