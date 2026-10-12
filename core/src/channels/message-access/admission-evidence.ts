import type { DecisionReceiptV1 } from "../../../packages/gateway-protocol/src/index.js";
import type { GatewayContextResolver } from "../../gateway/server-methods/types.js";
import { createChannelAdmissionDecisionReceipt } from "./admission-decision-receipt.js";
import {
  finalizedContextScopeKey,
  INVALID_SCOPE_VALUE,
  ownDataValue,
  publicResultScopeKey,
  scopedParticipantRef,
  snapshotContextBinding,
  normalizeScopeId,
  contextHandoffMatches,
} from "./admission-evidence-scope-key.js";
import type {
  AdmissionAuditOptions,
  AdmissionContributionRead,
  AdmissionDecisionInput,
  ChannelAdmissionContribution,
  ChannelAdmissionEvidence,
  ChannelAdmissionEvidencePayload,
  ChannelIngressResolutionBinding,
  ConsumedChannelAdmissionEvidence,
  ContextAdmissionValue,
  IngressResolutionInput,
  ParticipantContributionInput,
  PrepareHostAdmissionInput,
  RequiredSmsTask,
} from "./admission-evidence.types.js";
import {
  readChannelIngressHostOwner,
  type ChannelIngressHostOwner,
  type ChannelParticipantInput,
} from "./ingress-host-owner.js";
import type { ResolvedChannelMessageIngress } from "./runtime-types.js";

export type { ChannelAdmissionEvidence } from "./admission-evidence.types.js";

const CHANNEL_ADMISSION_EVIDENCE_MAX_CONTRIBUTIONS = 16;
const CHANNEL_ADMISSION_EVIDENCE_MAX_AGE_MS = 30 * 24 * 60 * 60_000;
const CONTEXT_ADMISSION = Symbol("openclaw.channelContextAdmission");

export class ChannelAdmissionAudit {
  #enabled: boolean;
  #closed = false;
  #revision = {};
  #sink: ((receipt: DecisionReceiptV1) => boolean) | undefined;
  constructor(params: AdmissionAuditOptions) {
    this.#enabled = params.enabled;
    this.#sink = params.decisionSink;
  }
  get enabled(): boolean {
    return this.#enabled;
  }
  configure(enabled: boolean): void {
    if (this.#closed || enabled === this.#enabled) {
      return;
    }
    this.#enabled = enabled;
    this.#revision = {};
  }
  captureCurrent(): () => boolean {
    const revision = this.#revision;
    return () => this.#enabled && this.#revision === revision;
  }
  recordDecision(receipt: DecisionReceiptV1): boolean {
    return this.#enabled ? (this.#sink?.(receipt) ?? false) : false;
  }
  close(): void {
    this.#closed = true;
    this.#enabled = false;
    this.#revision = {};
    this.#sink = undefined;
  }
}

export function createChannelAdmissionAudit(params: AdmissionAuditOptions): ChannelAdmissionAudit {
  return new ChannelAdmissionAudit(params);
}

class AdmissionEvidence implements ChannelAdmissionEvidence {
  readonly kind = "channel-admission-evidence";
  #payload: ChannelAdmissionEvidencePayload;
  #audit: ChannelAdmissionAudit | undefined;
  #isCurrent: (() => boolean) | undefined;
  #consumed = false;
  constructor(payload: ChannelAdmissionEvidencePayload, audit: ChannelAdmissionAudit | undefined) {
    this.#payload = payload;
    this.#audit = audit;
    this.#isCurrent = audit?.captureCurrent();
    Object.setPrototypeOf(this, null);
    Object.freeze(this);
  }
  static read(value: ChannelAdmissionEvidence | undefined) {
    return value !== undefined &&
      value !== null &&
      typeof value === "object" &&
      #payload in value &&
      (value.#isCurrent?.() ?? true)
      ? { payload: value.#payload, audit: value.#audit, consumed: value.#consumed }
      : undefined;
  }
  static consume(value: ChannelAdmissionEvidence): void {
    if (value !== null && typeof value === "object" && #payload in value) {
      value.#consumed = true;
    }
  }
}

function hostOwnerMatchesGateway(
  owner: ChannelIngressHostOwner | undefined,
  gatewayContext: ReturnType<GatewayContextResolver>,
): boolean {
  if (owner === undefined) {
    return true;
  }
  if (readChannelIngressHostOwner(owner) !== "live") {
    return false;
  }
  const context = owner.resolveGatewayContext?.();
  return readChannelIngressHostOwner(owner) === "live" && context === gatewayContext;
}

class PreparedChannelAdmissionEvidence {
  #consumed = false;
  #evidence: ChannelAdmissionEvidence | undefined;
  #resolver: GatewayContextResolver | undefined;
  #owner: ChannelIngressHostOwner | undefined;
  #gatewayContext: ReturnType<GatewayContextResolver>;
  constructor(
    evidence: ChannelAdmissionEvidence | undefined,
    resolver?: GatewayContextResolver,
    owner?: ChannelIngressHostOwner,
    gatewayContext?: ReturnType<GatewayContextResolver>,
  ) {
    this.#evidence = evidence;
    this.#resolver = resolver;
    this.#owner = owner;
    this.#gatewayContext = gatewayContext;
    Object.setPrototypeOf(this, null);
    Object.freeze(this);
  }
  static take(value: PreparedChannelAdmissionEvidence | undefined) {
    if (!value || typeof value !== "object" || !(#consumed in value) || value.#consumed) {
      return undefined;
    }
    value.#consumed = true;
    const current = hostOwnerMatchesGateway(value.#owner, value.#gatewayContext);
    return {
      evidence: current
        ? value.#evidence
        : unknownChannelAdmissionEvidence(AdmissionEvidence.read(value.#evidence)?.audit),
      resolver: current ? value.#resolver : undefined,
      owner: value.#owner,
      gatewayContext: value.#gatewayContext,
    };
  }
}

// Denial classification is independent of configurable audit/resolver carriers on the public object.
const requiredSmsTaskContexts = new WeakMap<object, RequiredSmsTask>();

class ContextAdmission {
  #context: object;
  #value: Readonly<ContextAdmissionValue>;
  constructor(context: object, value: ContextAdmissionValue) {
    this.#context = context;
    this.#value = Object.freeze(value);
    Object.setPrototypeOf(this, null);
    Object.freeze(this);
  }
  static read(value: unknown, context: object): Readonly<ContextAdmissionValue> | undefined {
    return value !== null &&
      typeof value === "object" &&
      #context in value &&
      value.#context === context
      ? value.#value
      : undefined;
  }
}
function readContextAdmission(context: object): Readonly<ContextAdmissionValue> | undefined {
  return ContextAdmission.read(ownDataValue(context, CONTEXT_ADMISSION), context);
}
function writeContextAdmission(context: object, value: ContextAdmissionValue): void {
  const prior = requiredSmsTaskContexts.get(context);
  // Exact-context rebinds may refresh evidence, never clear or retarget a Task requirement.
  if (prior && prior.scope !== value.scope) {
    requiredSmsTaskContexts.set(context, Object.freeze({ ...prior, poisoned: true }));
  }
  Object.defineProperty(context, CONTEXT_ADMISSION, {
    value: new ContextAdmission(context, value),
    configurable: true,
  });
}

class HostIngressResolution {
  #binding: ChannelIngressResolutionBinding;
  #participant: ChannelParticipantInput | undefined;
  constructor(binding: ChannelIngressResolutionBinding, participant?: ChannelParticipantInput) {
    this.#binding = binding;
    this.#participant = participant;
    Object.setPrototypeOf(this, null);
  }
  static read(value: object): ChannelIngressResolutionBinding | undefined {
    return value !== null && typeof value === "object" && #binding in value
      ? value.#binding
      : undefined;
  }
  static takeParticipant(value: object): ChannelParticipantInput | undefined {
    if (value === null || typeof value !== "object" || !(#binding in value)) {
      return undefined;
    }
    const participant = value.#binding.handoff.accepted ? value.#participant : undefined;
    value.#participant = undefined;
    return participant;
  }
}
export function takeChannelParticipantInput(
  result: ResolvedChannelMessageIngress,
): ChannelParticipantInput | undefined {
  return HostIngressResolution.takeParticipant(result);
}

function mintChannelAdmissionEvidence(
  audit: ChannelAdmissionAudit | undefined,
  payload:
    | Omit<Extract<ChannelAdmissionEvidencePayload, { kind: "leaf" }>, "createdAt">
    | Omit<Extract<ChannelAdmissionEvidencePayload, { kind: "aggregate" }>, "createdAt">,
): ChannelAdmissionEvidence | undefined {
  if (!audit?.enabled) {
    return undefined;
  }
  return new AdmissionEvidence(Object.freeze({ ...payload, createdAt: Date.now() }), audit);
}
function unsupportedChannelAdmissionEvidence(
  audit: ChannelAdmissionAudit | undefined,
): ChannelAdmissionEvidence | undefined {
  const payload = {
    kind: "leaf" as const,
    contribution: Object.freeze({ participant: { state: "unsupported" as const } }),
  };
  // A capability-absence marker carries no participant facts and needs no ambient collector.
  return audit
    ? mintChannelAdmissionEvidence(audit, payload)
    : new AdmissionEvidence(Object.freeze({ ...payload, createdAt: Date.now() }), undefined);
}

function participantContribution(
  params: ParticipantContributionInput,
): ChannelAdmissionContribution {
  const rawPrincipalRef = scopedParticipantRef(params);
  return Object.freeze(
    rawPrincipalRef
      ? { participant: Object.freeze({ state: "present" as const, rawPrincipalRef }) }
      : { participant: Object.freeze({ state: "unknown" as const }) },
  );
}

export function recordChannelIngressResolution(
  params: IngressResolutionInput,
): ResolvedChannelMessageIngress {
  const owner = params.owner;
  if (readChannelIngressHostOwner(owner) !== "live" || !owner) {
    return params.result;
  }
  if (readChannelIngressHostOwner(owner, params.channelId) !== "live") {
    return params.result;
  }
  const activeOwner = owner;
  const gatewayContext = activeOwner.resolveGatewayContext?.();
  if (!hostOwnerMatchesGateway(activeOwner, gatewayContext)) {
    return params.result;
  }
  const binding = Object.freeze({
    channelId: params.channelId,
    accountId: params.accountId,
    rawPrincipalRef: params.rawPrincipalRef,
    participantOutcomeAffecting: params.participantOutcomeAffecting,
    identifierAuthentication: params.identifierAuthentication,
    owner: activeOwner,
    gatewayContext,
    scope: Object.freeze({ conversation: Object.freeze({ ...params.scope.conversation }) }),
    contextBinding: snapshotContextBinding(params.scope.contextBinding),
    publicScopeKey: publicResultScopeKey(params.result),
    handoff: { consumed: false },
  });
  if (!hostOwnerMatchesGateway(activeOwner, gatewayContext)) {
    return params.result;
  }
  const result = Object.assign(
    new HostIngressResolution(binding, params.participantInput),
    params.result,
  );
  return hostOwnerMatchesGateway(activeOwner, gatewayContext) ? result : params.result;
}

function unknownChannelAdmissionEvidence(
  audit: ChannelAdmissionAudit | undefined,
): ChannelAdmissionEvidence | undefined {
  return mintChannelAdmissionEvidence(audit, {
    kind: "leaf",
    contribution: Object.freeze({ participant: { state: "unknown" as const } }),
  });
}

/** Consume and validate the exact resolver-to-context handoff before context construction. */
export function prepareHostChannelContextAdmissionEvidence(
  params: PrepareHostAdmissionInput,
): PreparedChannelAdmissionEvidence | undefined {
  const owner = params.owner;
  if (readChannelIngressHostOwner(owner) === "closed") {
    return undefined;
  }
  const gatewayContext = owner?.resolveGatewayContext?.();
  const audit = gatewayContext?.channelAdmissionAudit;
  if (!hostOwnerMatchesGateway(owner, gatewayContext)) {
    return undefined;
  }
  readChannelIngressHostOwner(owner, params.channelId);
  const ingress = params.ingress;
  if (!hostOwnerMatchesGateway(owner, gatewayContext)) {
    return undefined;
  }
  if (ingress === "unsupported") {
    return new PreparedChannelAdmissionEvidence(
      unsupportedChannelAdmissionEvidence(audit),
      undefined,
      owner,
      gatewayContext,
    );
  }
  const results =
    ingress === undefined
      ? []
      : Array.isArray(ingress)
        ? ingress
        : [ingress as ResolvedChannelMessageIngress];
  const seen = new Set<object>();
  const validBindings: ChannelIngressResolutionBinding[] = [];
  let valid = results.length > 0 && results.length <= CHANNEL_ADMISSION_EVIDENCE_MAX_CONTRIBUTIONS;
  for (const [index, result] of results.entries()) {
    const binding = HostIngressResolution.read(result);
    const firstUse = binding !== undefined && !binding.handoff.consumed && !seen.has(result);
    if (binding && !binding.handoff.consumed) {
      // Consume before validation and before the ordinary context builder runs.
      binding.handoff.consumed = true;
    }
    seen.add(result);
    const ownerMatches =
      owner !== undefined &&
      binding?.owner === owner &&
      binding.gatewayContext === gatewayContext &&
      hostOwnerMatchesGateway(owner, gatewayContext);
    const resultIngress = ownDataValue(result, "ingress");
    const resultMatches =
      binding?.publicScopeKey !== undefined &&
      publicResultScopeKey(result) === binding.publicScopeKey &&
      resultIngress !== null &&
      typeof resultIngress === "object" &&
      ownDataValue(resultIngress, "admission") === "dispatch";
    const contextMatches =
      binding !== undefined &&
      contextHandoffMatches({
        ...params,
        binding,
        // A batch exposes the final sender; earlier sources retain their own exact identities.
        rawPrincipalRef:
          index === results.length - 1 ? params.rawPrincipalRef : binding.rawPrincipalRef,
      });
    if (
      !firstUse ||
      !ownerMatches ||
      !resultMatches ||
      !contextMatches ||
      !binding ||
      !hostOwnerMatchesGateway(owner, gatewayContext)
    ) {
      valid = false;
    } else {
      validBindings.push(binding);
    }
  }
  const contextMessageId = normalizeScopeId(ownDataValue(params.contextParams, "messageId"));
  const finalMessageId = validBindings.at(-1)?.contextBinding?.messageId;
  if (
    contextMessageId === INVALID_SCOPE_VALUE ||
    (finalMessageId !== undefined && contextMessageId !== finalMessageId)
  ) {
    valid = false;
  }
  if (!hostOwnerMatchesGateway(owner, gatewayContext)) {
    return undefined;
  }
  if (valid) {
    for (const binding of validBindings) {
      binding.handoff.accepted = true;
    }
  }
  const sources = valid
    ? validBindings.map((binding) => {
        const contribution = participantContribution(binding);
        return mintChannelAdmissionEvidence(audit, {
          kind: "leaf",
          contribution: Object.freeze({
            ...contribution,
            decision: Object.freeze({
              participantAware: contribution.participant.state === "present",
              outcomeAffecting: binding.participantOutcomeAffecting,
              identifierAuthentication: binding.identifierAuthentication,
            }),
          }),
        });
      })
    : [];
  const evidence = valid
    ? combineChannelAdmissionEvidence(sources)
    : unknownChannelAdmissionEvidence(audit);
  if (!hostOwnerMatchesGateway(owner, gatewayContext)) {
    return undefined;
  }
  return new PreparedChannelAdmissionEvidence(
    evidence,
    valid ? owner?.resolveGatewayContext : undefined,
    owner,
    gatewayContext,
  );
}

/** Attach one prepared private carrier to the exact finalized context scope. */
export function bindHostChannelContextAdmissionEvidence(params: {
  context: object;
  preparation: PreparedChannelAdmissionEvidence | undefined;
}): void {
  const prepared = PreparedChannelAdmissionEvidence.take(params.preparation);
  const scope = finalizedContextScopeKey(params.context);
  const audit = AdmissionEvidence.read(prepared?.evidence)?.audit;
  const current = hostOwnerMatchesGateway(prepared?.owner, prepared?.gatewayContext);
  writeContextAdmission(params.context, {
    scope,
    evidence:
      current && scope !== undefined ? prepared?.evidence : unknownChannelAdmissionEvidence(audit),
    resolver: current && scope !== undefined ? prepared?.resolver : undefined,
  });
}
export function readChannelContextAdmissionEvidence(
  context: object,
): ChannelAdmissionEvidence | undefined {
  return readContextAdmission(context)?.evidence;
}
export function readChannelContextGatewayContextResolver(
  context: object,
): GatewayContextResolver | undefined {
  return readContextAdmission(context)?.resolver;
}

/** Core-only denial requirement. The task owner is opaque and checked by its private factory. */
export function bindRequiredSmsTaskContext(context: object, owner: object): void {
  const original = readContextAdmission(context);
  const scope = finalizedContextScopeKey(context);
  const prior = requiredSmsTaskContexts.get(context);
  requiredSmsTaskContexts.set(
    context,
    Object.freeze({
      owner: prior ? prior.owner : owner,
      scope: prior ? prior.scope : original ? original.scope : scope,
      poisoned:
        prior?.poisoned === true ||
        (prior !== undefined && (prior.owner !== owner || prior.scope !== scope)) ||
        scope === undefined ||
        (original !== undefined && original.scope !== scope),
    }),
  );
  writeContextAdmission(context, {
    ...original,
    scope: original ? original.scope : scope,
    evidence: original?.evidence,
  });
}
/** Not authority: checks only current identity/scope of an already stamped requirement. */
export function isRequiredSmsTaskContextCurrent(context: object, owner: object): boolean {
  const value = requiredSmsTaskContexts.get(context);
  return (
    value?.owner === owner &&
    value.poisoned === false &&
    value.scope !== undefined &&
    value.scope === finalizedContextScopeKey(context)
  );
}

/** Preserve private evidence only when its owner explicitly replaces an unchanged context. */
export function copyChannelParticipantAdmissionEvidence(source: object, target: object): void {
  const original = readContextAdmission(source);
  if (!original) {
    return;
  }
  const targetScope = finalizedContextScopeKey(target);
  const sameScope = original.scope !== undefined && targetScope === original.scope;
  const safeEvidence =
    sameScope && activePayload(original.evidence, Date.now()) !== undefined
      ? original.evidence
      : unknownChannelAdmissionEvidence(AdmissionEvidence.read(original.evidence)?.audit);
  const current = readContextAdmission(target);
  const resolverConflict =
    current?.resolverConflict === true ||
    Boolean(current?.resolver && original.resolver && current.resolver !== original.resolver);
  writeContextAdmission(target, {
    scope: targetScope,
    evidence: safeEvidence,
    resolver: sameScope && !resolverConflict ? original.resolver : undefined,
    resolverConflict,
  });
}

function activePayload(
  evidence: ChannelAdmissionEvidence | undefined,
  now: number,
): ChannelAdmissionEvidencePayload | undefined {
  const stored = AdmissionEvidence.read(evidence);
  if (!stored || stored.consumed) {
    return undefined;
  }
  const { payload, audit } = stored;
  return (!audit || audit.enabled) &&
    now - payload.createdAt <= CHANNEL_ADMISSION_EVIDENCE_MAX_AGE_MS
    ? payload
    : undefined;
}

/** Preserve one source exactly; collected sources get one new bounded opaque aggregate. */
export function combineChannelAdmissionEvidence(
  evidence: readonly (ChannelAdmissionEvidence | undefined)[],
): ChannelAdmissionEvidence | undefined {
  if (evidence.length === 1) {
    return evidence[0];
  }
  const audit = evidence
    .map((entry) => AdmissionEvidence.read(entry)?.audit)
    .find((entry) => entry !== undefined);
  if (!audit?.enabled) {
    return undefined;
  }
  if (
    evidence.length > CHANNEL_ADMISSION_EVIDENCE_MAX_CONTRIBUTIONS ||
    evidence.some((entry) => AdmissionEvidence.read(entry)?.audit !== audit)
  ) {
    return unknownChannelAdmissionEvidence(audit);
  }
  return mintChannelAdmissionEvidence(audit, {
    kind: "aggregate",
    sources: Object.freeze([...evidence]),
  });
}

function inspectContributions(params: AdmissionContributionRead): ChannelAdmissionContribution[] {
  const payload = activePayload(params.evidence, params.now);
  if (!payload || !params.evidence || params.seen.has(params.evidence)) {
    return [{ participant: { state: "unknown" } }];
  }
  params.seen.add(params.evidence);
  return payload.kind === "leaf"
    ? [payload.contribution]
    : payload.sources.flatMap((source) => inspectContributions({ ...params, evidence: source }));
}

/** Compare opaque participants without exposing or consuming their raw references. */
export function compareChannelAdmissionParticipants(
  evidence: readonly (ChannelAdmissionEvidence | undefined)[],
): "same" | "mixed-or-unknown" {
  const contributions = evidence.flatMap((candidate) =>
    inspectContributions({ evidence: candidate, now: Date.now(), seen: new Set() }),
  );
  if (
    contributions.length === 0 ||
    contributions.length > CHANNEL_ADMISSION_EVIDENCE_MAX_CONTRIBUTIONS
  ) {
    return "mixed-or-unknown";
  }
  const participants = contributions.map((item) => item.participant);
  const first = participants[0];
  return first?.state === "present" &&
    participants.every(
      (item) => item.state === "present" && item.rawPrincipalRef === first.rawPrincipalRef,
    )
    ? "same"
    : "mixed-or-unknown";
}

function consumeContributions(params: AdmissionContributionRead): ChannelAdmissionContribution[] {
  const payload = activePayload(params.evidence, params.now);
  if (!payload || !params.evidence || params.seen.has(params.evidence)) {
    return [{ participant: { state: "unknown" } }];
  }
  params.seen.add(params.evidence);
  AdmissionEvidence.consume(params.evidence);
  if (payload.kind === "leaf") {
    return [payload.contribution];
  }
  const contributions = payload.sources.flatMap((source) =>
    consumeContributions({ ...params, evidence: source }),
  );
  return contributions.length <= CHANNEL_ADMISSION_EVIDENCE_MAX_CONTRIBUTIONS
    ? contributions
    : [{ participant: { state: "unknown" } }];
}

function freezeConsumed(
  value: Omit<ConsumedChannelAdmissionEvidence, "invoker"> & {
    invoker: ConsumedChannelAdmissionEvidence["invoker"];
  },
): ConsumedChannelAdmissionEvidence {
  return Object.freeze({
    ...value,
    invoker: Object.freeze(value.invoker),
  });
}

/** Consume one aggregate at run admission. Missing, forged, stale, or reused carriers are unknown. */
export function consumeChannelAdmissionEvidence(
  evidence: ChannelAdmissionEvidence | undefined,
): ConsumedChannelAdmissionEvidence {
  const contributions = consumeContributions({ evidence, now: Date.now(), seen: new Set() });
  const participants = contributions.map((item) => item.participant);
  const allUnsupported =
    participants.length > 0 && participants.every((item) => item.state === "unsupported");
  if (allUnsupported) {
    return freezeConsumed({
      ingressState: "unsupported",
      invoker: { state: "unknown" },
      decisionCoverage: "unsupported",
      identifierAuthentication: "unknown",
    });
  }

  const present = participants.filter(
    (item): item is Extract<(typeof participants)[number], { state: "present" }> =>
      item.state === "present",
  );
  const sameParticipant =
    present.length === participants.length &&
    present.every((item) => item.rawPrincipalRef === present[0]?.rawPrincipalRef);
  if (!sameParticipant || !present[0]) {
    return freezeConsumed({
      ingressState: "unknown",
      invoker: { state: "unknown" },
      decisionCoverage: "unknown",
      identifierAuthentication: "unknown",
    });
  }

  const everyDecisionEnforced = contributions.every(
    (item) => item.decision?.participantAware && item.decision.outcomeAffecting,
  );
  const identifierAuthentication = contributions.some(
    (item) => item.decision?.identifierAuthentication === "affected",
  )
    ? "affected"
    : contributions.some((item) => item.decision?.identifierAuthentication === "evaluated")
      ? "evaluated"
      : contributions.every((item) => item.decision?.identifierAuthentication === "not-evaluated")
        ? "not-evaluated"
        : "unknown";
  return freezeConsumed({
    ingressState: "present",
    invoker: {
      state: "present",
      kind: "person",
      rawPrincipalRef: present[0].rawPrincipalRef,
    },
    assuranceRef: "channel-admission",
    decisionCoverage: everyDecisionEnforced ? "enforced" : "attribution-only",
    identifierAuthentication,
  });
}

/** Queue the channel decision after its exact identity tuple on the shared audit FIFO. */
export function recordChannelAdmissionDecision(
  evidence: ChannelAdmissionEvidence | undefined,
  params: AdmissionDecisionInput,
): boolean {
  const stored = AdmissionEvidence.read(evidence);
  return stored?.audit
    ? stored.audit.recordDecision(createChannelAdmissionDecisionReceipt(params))
    : false;
}
