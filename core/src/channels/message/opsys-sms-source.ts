/** Private native Source owner. No SDK callback, ContextAdmission receiver or model consumer. */
import { types } from "node:util";
import {
  validateSmsCommand,
  type ValidatedSmsCommand,
} from "../../agents/opsys-runtime-sms-contract.js";
import type { SmsHostReceipt } from "../../gateway/opsys-sms-receipt-gate.js";
import {
  assertOwnNativeClaimCurrent,
  assertOwnNativeCompletionAccount,
  bindOwnNativeCompletionGuard,
  consumeOwnNativeCompletionReceipt,
  prepareOwnNativeCompletion,
  readNativeSmsQueueScope,
  readNativeSmsQueueOwnerAssertion,
  revokeOwnNativeCompletion,
  type NativeSmsClaimRef,
  type NativeSmsCompletionPermit,
  type NativeSmsCompletionReceipt,
} from "./ingress-queue.js";

export type SmsSourceHandle = Readonly<object>;
export type NativeSmsClaimLifecycle = Readonly<object>;
export type SmsSourceScope = Readonly<{
  agentId: string;
  sessionKey: string;
  accountId: string;
  sender: string;
  messageSid: string;
}>;
export type GateReceivedBinding = Readonly<{
  status: "received";
  command: ValidatedSmsCommand;
  receipt: SmsHostReceipt;
  receivedAt: number;
  destinationSha256: string;
}>;
type SourceCell = {
  phase: "REGISTERED" | "ARMED" | "ADOPTED" | "CLOSED";
  source: SmsSourceHandle;
  scope?: SmsSourceScope;
  binding?: GateReceivedBinding;
  host?: () => void;
  claimCurrent?: () => void;
  assertion: () => void;
  signal?: AbortSignal;
  abort?: () => void;
  preAdoptionSignal: AbortSignal;
  preAdoptionAbort?: () => void;
  armAttempted: boolean;
};
type ClaimOwner = {
  queueScope: object;
  assertQueueOwnerCurrent: () => void;
  key: string;
  lifecycleOwner: object;
  lifecycle: NativeSmsClaimLifecycle;
  claim: NativeSmsClaimRef;
  permit: NativeSmsCompletionPermit;
  cell: SourceCell;
};
const ERROR = "REJ-M1-SMS-SOURCE-NON-COURANTE";
const nativeThen = Promise.prototype.then;
const nativeSignalAborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted")?.get;
const nativeAddListener = EventTarget.prototype.addEventListener;
const nativeRemoveListener = EventTarget.prototype.removeEventListener;
const owners = new WeakMap<object, ClaimOwner>();
const sources = new WeakMap<object, ClaimOwner>();
const liveClaims = new WeakMap<object, Map<string, ClaimOwner>>();

function requireSource(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(ERROR);
  }
}
function plain(value: unknown, fields: readonly string[]): Record<string, unknown> {
  requireSource(value !== null && typeof value === "object" && !types.isProxy(value));
  const prototype = Object.getPrototypeOf(value);
  requireSource(prototype === Object.prototype || prototype === null);
  const keys = Reflect.ownKeys(value);
  requireSource(
    keys.length === fields.length && keys.every((k) => typeof k === "string" && fields.includes(k)),
  );
  const data: Record<string, unknown> = Object.create(null);
  for (const field of fields) {
    const descriptor = Object.getOwnPropertyDescriptor(value, field);
    requireSource(descriptor && "value" in descriptor && descriptor.enumerable);
    data[field] = descriptor.value;
  }
  return data;
}
function claimCopy(value: NativeSmsClaimRef): NativeSmsClaimRef {
  const data = plain(value, ["id", "token", "ownerId"]);
  requireSource(
    typeof data.id === "string" &&
      data.id.length > 0 &&
      typeof data.token === "string" &&
      data.token.length > 0 &&
      typeof data.ownerId === "string" &&
      data.ownerId.length > 0,
  );
  return Object.freeze({ id: data.id, token: data.token, ownerId: data.ownerId });
}
function tuple(claim: NativeSmsClaimRef): string {
  return JSON.stringify([claim.id, claim.token, claim.ownerId]);
}
function invokeGuard(guard: () => void): void {
  const result: unknown = guard();
  if (types.isPromise(result)) {
    void nativeThen.call(result, undefined, () => undefined);
  }
  requireSource(result === undefined);
}
function sourceIsOpen(cell: SourceCell): boolean {
  return cell.phase !== "CLOSED";
}
function preAdoptionCurrent(cell: SourceCell): void {
  requireSource(sourceIsOpen(cell));
  if (cell.phase !== "ADOPTED") {
    requireSource(nativeSignalAborted?.call(cell.preAdoptionSignal) === false);
  }
}
function detachPreAdoptionSignal(cell: SourceCell): void {
  if (cell.preAdoptionAbort) {
    nativeRemoveListener.call(cell.preAdoptionSignal, "abort", cell.preAdoptionAbort);
    cell.preAdoptionAbort = undefined;
  }
}
function hostCurrent(owner: ClaimOwner): void {
  try {
    preAdoptionCurrent(owner.cell);
    requireSource(sourceIsOpen(owner.cell) && owner.cell.host && owner.cell.signal);
    owner.assertQueueOwnerCurrent();
    preAdoptionCurrent(owner.cell);
    owner.cell.signal.throwIfAborted();
    invokeGuard(owner.cell.host);
    preAdoptionCurrent(owner.cell);
    owner.cell.signal.throwIfAborted();
    owner.assertQueueOwnerCurrent();
    preAdoptionCurrent(owner.cell);
  } catch {
    disposeSmsSource(owner.cell.source);
    throw new Error(ERROR);
  }
}
function currentArmed(owner: ClaimOwner): void {
  hostCurrent(owner);
  requireSource(owner.cell.phase === "ARMED" && owner.cell.claimCurrent);
  try {
    assertOwnNativeClaimCurrent(owner.permit);
    preAdoptionCurrent(owner.cell);
    invokeGuard(owner.cell.claimCurrent);
    requireSource(owner.cell.phase === "ARMED");
    owner.cell.signal?.throwIfAborted();
    assertOwnNativeClaimCurrent(owner.permit);
    preAdoptionCurrent(owner.cell);
  } catch {
    disposeSmsSource(owner.cell.source);
    throw new Error(ERROR);
  }
}

function isReceiptDecision(value: unknown): value is SmsHostReceipt["decision"] {
  return (
    value === "DEMANDER_PRECISIONS" ||
    value === "TRANSMETTRE_M2" ||
    value === "CONVERSATION_DEJA_QUALIFIEE" ||
    value === "RETRAIT_CONSENTEMENT" ||
    value === "ESCALADE_PLAINTE" ||
    value === "ESCALADE_URGENCE" ||
    value === "TRANSFERT_EN_COURS"
  );
}

/** Called by the native drain before dispatch; no arm or permission is produced here. */
export function registerNativeSmsClaimLifecycle(
  queue: unknown,
  claim: NativeSmsClaimRef,
  lifecycleOwner: object,
  preAdoptionSignal: AbortSignal,
): NativeSmsClaimLifecycle | undefined {
  let registered: ClaimOwner | undefined;
  let prepared: NativeSmsCompletionPermit | null | undefined;
  try {
    requireSource(!types.isProxy(preAdoptionSignal) && preAdoptionSignal instanceof AbortSignal);
    requireSource(nativeSignalAborted?.call(preAdoptionSignal) === false);
    const queueScope = readNativeSmsQueueScope(queue);
    const assertQueueOwnerCurrent = readNativeSmsQueueOwnerAssertion(queue);
    if (!queueScope || !assertQueueOwnerCurrent) {
      return undefined;
    }
    const copied = claimCopy(claim);
    let live = liveClaims.get(queueScope);
    if (!live) {
      liveClaims.set(queueScope, (live = new Map()));
    }
    const key = tuple(copied);
    if (live.has(key)) {
      return undefined;
    }
    const source = Object.freeze({}),
      lifecycle = Object.freeze({});
    const cell: SourceCell = {
      phase: "REGISTERED",
      source,
      preAdoptionSignal,
      armAttempted: false,
      assertion: () => {
        const owner = sources.get(source);
        requireSource(owner?.cell.phase === "ADOPTED");
        hostCurrent(owner);
      },
    };
    const permit = prepareOwnNativeCompletion(queue, copied, cell, lifecycleOwner);
    prepared = permit;
    if (!permit) {
      return undefined;
    }
    assertOwnNativeClaimCurrent(permit);
    const owner: ClaimOwner = {
      queueScope,
      assertQueueOwnerCurrent,
      key,
      lifecycleOwner,
      lifecycle,
      claim: copied,
      permit,
      cell,
    };
    live.set(key, owner);
    owners.set(lifecycle, owner);
    sources.set(source, owner);
    registered = owner;
    preAdoptionCurrent(cell);
    cell.preAdoptionAbort = () => disposeSmsSource(source);
    nativeAddListener.call(preAdoptionSignal, "abort", cell.preAdoptionAbort, { once: true });
    preAdoptionCurrent(cell);
    return lifecycle;
  } catch {
    if (registered) {
      disposeSmsSource(registered.cell.source);
      liveClaims.get(registered.queueScope)?.delete(registered.key);
      owners.delete(registered.lifecycle);
    } else if (prepared) {
      revokeOwnNativeCompletion(prepared);
    }
    return undefined;
  }
}

function validatedBinding(
  value: GateReceivedBinding,
  scopeValue: SmsSourceScope,
  id: string,
): { binding: GateReceivedBinding; scope: SmsSourceScope } {
  const b = plain(value, ["status", "command", "receipt", "receivedAt", "destinationSha256"]);
  requireSource(
    b.status === "received" &&
      typeof b.receivedAt === "number" &&
      Number.isSafeInteger(b.receivedAt) &&
      b.receivedAt >= 0,
  );
  requireSource(
    typeof b.destinationSha256 === "string" &&
      /^[0-9a-f]{64}$/u.exec(b.destinationSha256)?.[0] === b.destinationSha256,
  );
  const raw = plain(b.command, [
    "commande",
    "permission",
    "operation",
    "intention_id",
    "commande_sha256",
    "arguments_sha256",
  ]);
  const command = validateSmsCommand(
    { version: 1, commande: raw.commande, permission: raw.permission },
    raw.operation,
  );
  requireSource(
    command.intention_id === raw.intention_id &&
      command.commande_sha256 === raw.commande_sha256 &&
      command.arguments_sha256 === raw.arguments_sha256,
  );
  const c = command.commande;
  requireSource(c.message_sid === id && c.recu_le === new Date(b.receivedAt).toISOString());
  const s = plain(scopeValue, ["agentId", "sessionKey", "accountId", "sender", "messageSid"]);
  requireSource(
    s.agentId === c.agent_id &&
      s.sessionKey === c.session_key &&
      s.accountId === c.compte_id &&
      s.sender === c.expediteur &&
      s.messageSid === c.message_sid,
  );
  const r = plain(b.receipt, [
    "source",
    "compte_id",
    "account_sid",
    "message_sid",
    "agent_id",
    "session_key",
    "signal_id",
    "signal_ligne_id",
    "decision",
    "lead_ligne_id",
    "transfert_id",
  ]);
  requireSource(
    r.source === "sms:twilio" &&
      r.compte_id === c.compte_id &&
      r.account_sid === c.account_sid &&
      r.message_sid === c.message_sid &&
      r.agent_id === c.agent_id &&
      r.session_key === c.session_key &&
      r.signal_id === "sms:" + c.message_sid,
  );
  requireSource(
    typeof r.signal_ligne_id === "string" &&
      /^[0-9a-f]{64}$/u.exec(r.signal_ligne_id)?.[0] === r.signal_ligne_id,
  );
  requireSource(isReceiptDecision(r.decision));
  requireSource(
    r.lead_ligne_id === null ||
      (typeof r.lead_ligne_id === "string" &&
        /^[0-9a-f]{64}$/u.exec(r.lead_ligne_id)?.[0] === r.lead_ligne_id),
  );
  requireSource(
    r.transfert_id === null ||
      (typeof r.transfert_id === "string" &&
        /^tr-[0-9a-f]{20}$/u.exec(r.transfert_id)?.[0] === r.transfert_id),
  );
  if (r.decision === "TRANSMETTRE_M2" || r.decision === "CONVERSATION_DEJA_QUALIFIEE") {
    requireSource(
      r.lead_ligne_id !== null && r.lead_ligne_id !== r.signal_ligne_id && r.transfert_id === null,
    );
  } else if (
    r.decision === "ESCALADE_PLAINTE" ||
    r.decision === "ESCALADE_URGENCE" ||
    r.decision === "TRANSFERT_EN_COURS"
  ) {
    requireSource(r.lead_ligne_id === null && r.transfert_id !== null);
  } else {
    requireSource(r.lead_ligne_id === null && r.transfert_id === null);
  }
  const receipt: SmsHostReceipt = Object.freeze({
    source: "sms:twilio",
    compte_id: c.compte_id,
    account_sid: c.account_sid,
    message_sid: c.message_sid,
    agent_id: c.agent_id,
    session_key: c.session_key,
    signal_id: "sms:" + c.message_sid,
    signal_ligne_id: r.signal_ligne_id,
    decision: r.decision,
    lead_ligne_id: r.lead_ligne_id,
    transfert_id: r.transfert_id,
  });
  const scope = Object.freeze({
    agentId: c.agent_id,
    sessionKey: c.session_key,
    accountId: c.compte_id,
    sender: c.expediteur,
    messageSid: c.message_sid,
  });
  return {
    scope,
    binding: Object.freeze({
      status: "received",
      command,
      receipt,
      receivedAt: b.receivedAt,
      destinationSha256: b.destinationSha256,
    }),
  };
}

/** Root Gate composition only: destination is supplied from its original verified capsule. */
export function armNativeSmsSource(
  input: Readonly<{
    queue: unknown;
    claim: NativeSmsClaimRef;
    received: GateReceivedBinding;
    scope: SmsSourceScope;
    assertHostAndRouteCurrent: () => void;
    assertClaimCurrent: () => void;
    signal: AbortSignal;
  }>,
): SmsSourceHandle {
  let armed: ClaimOwner | undefined;
  try {
    const data = plain(input, [
      "queue",
      "claim",
      "received",
      "scope",
      "assertHostAndRouteCurrent",
      "assertClaimCurrent",
      "signal",
    ]);
    const queueScope = readNativeSmsQueueScope(data.queue);
    const claim = claimCopy(input.claim);
    const owner = queueScope && liveClaims.get(queueScope)?.get(tuple(claim));
    requireSource(owner);
    armed = owner;
    owner.cell.armAttempted = true;
    requireSource(owner.cell.phase === "REGISTERED");
    preAdoptionCurrent(owner.cell);
    requireSource(
      typeof data.assertHostAndRouteCurrent === "function" &&
        !types.isProxy(data.assertHostAndRouteCurrent),
    );
    requireSource(
      typeof data.assertClaimCurrent === "function" && !types.isProxy(data.assertClaimCurrent),
    );
    requireSource(!types.isProxy(data.signal) && data.signal instanceof AbortSignal);
    const copied = validatedBinding(input.received, input.scope, claim.id);
    assertOwnNativeCompletionAccount(owner.permit, copied.scope.accountId);
    const cell = owner.cell;
    cell.host = input.assertHostAndRouteCurrent;
    cell.claimCurrent = input.assertClaimCurrent;
    cell.signal = input.signal;
    cell.scope = copied.scope;
    cell.binding = copied.binding;
    cell.phase = "ARMED";
    bindOwnNativeCompletionGuard(owner.permit, cell, owner.lifecycleOwner, () =>
      currentArmed(owner),
    );
    currentArmed(owner);
    cell.abort = () => disposeSmsSource(cell.source);
    cell.signal.addEventListener("abort", cell.abort, { once: true });
    hostCurrent(owner);
    return cell.source;
  } catch {
    if (armed) {
      disposeSmsSource(armed.cell.source);
    }
    throw new Error(ERROR);
  }
}

export function readNativeSmsCompletionPermit(
  lifecycle: NativeSmsClaimLifecycle,
): NativeSmsCompletionPermit | undefined {
  const owner = owners.get(lifecycle);
  if (!owner) {
    return undefined;
  }
  // Never downgrade an attempted selected arm to the legacy completion lane.
  if (
    !owner.cell.armAttempted &&
    (owner.cell.phase === "REGISTERED" || owner.cell.phase === "CLOSED")
  ) {
    return undefined;
  }
  requireSource(owner.cell.phase === "ARMED");
  currentArmed(owner);
  return owner.permit;
}
export function confirmOwnNativeCompletion(
  lifecycle: NativeSmsClaimLifecycle,
  receipt: NativeSmsCompletionReceipt,
  lifecycleOwner: object,
): void {
  const owner = owners.get(lifecycle);
  requireSource(owner && owner.lifecycleOwner === lifecycleOwner && owner.cell.phase === "ARMED");
  try {
    hostCurrent(owner);
    consumeOwnNativeCompletionReceipt(owner.permit, receipt, owner.cell, lifecycleOwner);
    // The native commit removed the claim: only Host/pre-adoption guards apply here.
    hostCurrent(owner);
    owner.cell.phase = "ADOPTED";
    detachPreAdoptionSignal(owner.cell);
  } catch {
    disposeSmsSource(owner.cell.source);
    throw new Error(ERROR);
  }
}
export function readSmsSourceScope(source: unknown): SmsSourceScope {
  requireSource(source !== null && typeof source === "object");
  const owner = sources.get(source);
  requireSource(owner?.cell.scope);
  if (owner.cell.phase === "ARMED") {
    currentArmed(owner);
  } else {
    requireSource(owner.cell.phase === "ADOPTED");
    hostCurrent(owner);
  }
  return owner.cell.scope;
}
export function readSmsSourceAssertion(source: unknown): () => void {
  requireSource(source !== null && typeof source === "object");
  const owner = sources.get(source);
  requireSource(owner && (owner.cell.phase === "ARMED" || owner.cell.phase === "ADOPTED"));
  hostCurrent(owner);
  return owner.cell.assertion;
}
export function retireNativeSmsClaimLifecycle(lifecycle: NativeSmsClaimLifecycle): void {
  const owner = owners.get(lifecycle);
  if (!owner) {
    return;
  }
  liveClaims.get(owner.queueScope)?.delete(owner.key);
  owners.delete(lifecycle);
  if (owner.cell.phase !== "ADOPTED") {
    disposeSmsSource(owner.cell.source);
  }
}
export function disposeSmsSource(source: SmsSourceHandle): void {
  const owner = sources.get(source);
  if (!owner || owner.cell.phase === "CLOSED") {
    return;
  }
  owner.cell.phase = "CLOSED";
  revokeOwnNativeCompletion(owner.permit);
  detachPreAdoptionSignal(owner.cell);
  if (owner.cell.abort && owner.cell.signal) {
    owner.cell.signal.removeEventListener("abort", owner.cell.abort);
  }
  // Retain this terminal lifecycle until native retirement: a refused late arm
  // must still exclude legacy completion and cannot reopen the same owner.
}
