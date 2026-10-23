import { createHash } from "node:crypto";
import { types } from "node:util";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import { recordModelFallbackStop } from "../model-fallback-stop.js";
import type { AgentMessage } from "../runtime/index.js";
import { createFreshLlmBoundaryTokenEstimator } from "../sessions/context-token-pressure.js";

const TIMEOUT_MS = 10_000;

/** Minimal admission evidence safe for an attempt-local collector; excludes captured config/id. */
export type OpsysRuntimeAdmissionReceipt = Readonly<{
  agentId: string;
  profileId: string;
  profileRevision: number;
  departement: string;
  runId: string;
  attemptId: string;
  cycleId: string;
}>;

/** Historical host binding to one reconciled original result; not current authority or semantic truth. */
export type OpsysRuntimeCompletionReceipt = Readonly<
  OpsysRuntimeAdmissionReceipt & {
    candidateIndex: number;
    streamOrdinal: number;
    resultSHA256: string;
    tokensReels: number;
  }
>;

const completionReceipts = new WeakMap<object, OpsysRuntimeCompletionReceipt>();
const completionBindingFields = [
  "agentId",
  "profileId",
  "profileRevision",
  "departement",
  "runId",
  "attemptId",
  "cycleId",
] as const satisfies readonly (keyof OpsysRuntimeAdmissionReceipt)[];

function completionResultSHA256(message: object): string | undefined {
  try {
    const bytes = JSON.stringify(message);
    return typeof bytes === "string"
      ? createHash("sha256").update(bytes, "utf8").digest("hex")
      : undefined;
  } catch {
    // Serialization can invoke getters/toJSON or encounter a cycle/BigInt; proof stays absent.
    return undefined;
  }
}

/** Only the exact original object, expected host tuple and current serialized bytes can retrieve proof. */
export function getOpsysRuntimeCompletionReceipt(
  message: unknown,
  expected: OpsysRuntimeAdmissionReceipt,
): OpsysRuntimeCompletionReceipt | undefined {
  try {
    if (message === null || typeof message !== "object" || Array.isArray(message)) {
      return undefined;
    }
    if (expected === null || typeof expected !== "object" || Array.isArray(expected)) {
      return undefined;
    }
    const receipt = completionReceipts.get(message);
    if (!receipt) {
      return undefined;
    }
    for (const field of completionBindingFields) {
      if (!Object.hasOwn(expected, field) || expected[field] !== receipt[field]) {
        return undefined;
      }
    }
    return completionResultSHA256(message) === receipt.resultSHA256 ? receipt : undefined;
  } catch {
    // Malformed host expectations or throwing accessors never create an observer failure.
    return undefined;
  }
}

const completionCustodyBrand = Symbol("opsys.runtime.completion-custody");

/** Private Core handle; only this module's WeakMap grants custody provenance. */
export type OpsysRuntimeCompletionCustody = Readonly<{ [completionCustodyBrand]: true }>;

type CompletionCustodyBinding = Readonly<
  Pick<
    OpsysRuntimeCompletionReceipt,
    "agentId" | "profileId" | "profileRevision" | "departement" | "runId" | "candidateIndex"
  >
>;
type CompletionCustodyRecord = Readonly<{
  message: unknown;
  receipt: OpsysRuntimeCompletionReceipt;
}>;
type CompletionCustodyState = {
  readonly binding: CompletionCustodyBinding;
  readonly streamOrdinals: readonly number[];
  records: Map<number, CompletionCustodyRecord> | undefined;
  closed: boolean;
};
const completionCustodies = new WeakMap<object, CompletionCustodyState>();

function completionCustodyState(handle: unknown): CompletionCustodyState | undefined {
  return handle !== null && typeof handle === "object"
    ? completionCustodies.get(handle)
    : undefined;
}

function closeCompletionCustodyState(state: CompletionCustodyState): void {
  state.closed = true;
  state.records?.clear();
  state.records = undefined;
}

/** Fix the complete required set before dispatch; later work cannot fill an already consumed set. */
export function createOpsysRuntimeCompletionCustody(
  input: CompletionCustodyBinding & { readonly streamOrdinals: readonly number[] },
): OpsysRuntimeCompletionCustody {
  const {
    agentId,
    profileId,
    profileRevision: revision,
    departement,
    runId,
    candidateIndex,
    streamOrdinals,
  } = input;
  if (
    typeof agentId !== "string" ||
    agentId.trim().length === 0 ||
    typeof profileId !== "string" ||
    profileId.trim().length === 0 ||
    typeof runId !== "string" ||
    runId.trim().length === 0 ||
    !canonicalDepartment(departement) ||
    !Number.isSafeInteger(revision) ||
    revision < 1 ||
    !Number.isSafeInteger(candidateIndex) ||
    candidateIndex < 0 ||
    !Array.isArray(streamOrdinals)
  ) {
    throw new Error("OPSYS runtime completion custody binding is invalid");
  }
  const ordinalCount = streamOrdinals.length;
  if (!Number.isSafeInteger(ordinalCount) || ordinalCount < 1 || ordinalCount > 16) {
    throw new Error("OPSYS runtime completion custody ordinals are invalid");
  }
  const ordinals: number[] = [];
  const seen = new Set<number>();
  for (let index = 0; index < ordinalCount; index++) {
    const ordinal: unknown = streamOrdinals[index];
    if (
      typeof ordinal !== "number" ||
      !Number.isSafeInteger(ordinal) ||
      ordinal < 0 ||
      seen.has(ordinal)
    ) {
      throw new Error("OPSYS runtime completion custody ordinals are invalid");
    }
    seen.add(ordinal);
    ordinals.push(ordinal);
  }
  ordinals.sort((a, b) => a - b);
  const handle: OpsysRuntimeCompletionCustody = Object.freeze({ [completionCustodyBrand]: true });
  completionCustodies.set(handle, {
    binding: Object.freeze({
      agentId,
      profileId,
      profileRevision: revision,
      departement,
      runId,
      candidateIndex,
    }),
    streamOrdinals: Object.freeze(ordinals),
    records: new Map(),
    closed: false,
  });
  return handle;
}

/** Reject serialization callouts before validating any member of a mutable batch. */
function completionCustodyDataIsInert(messages: readonly unknown[]): boolean {
  const pending: unknown[] = [...messages];
  const visited = new WeakSet<object>();
  while (pending.length > 0) {
    const value = pending.pop();
    if (typeof value === "function" || typeof value === "bigint") {
      return false;
    }
    if (value === null || typeof value !== "object") {
      continue;
    }
    // Even prototype/descriptor inspection would invoke traps on a Proxy.
    if (types.isProxy(value) || ArrayBuffer.isView(value) || types.isAnyArrayBuffer(value)) {
      return false;
    }
    if (visited.has(value)) {
      continue;
    }
    visited.add(value);
    const array = Array.isArray(value);
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== null && prototype !== (array ? Array.prototype : Object.prototype)) {
      return false;
    }
    for (
      let inherited = prototype;
      inherited !== null;
      inherited = Object.getPrototypeOf(inherited)
    ) {
      if (inherited !== Object.prototype && inherited !== Array.prototype) {
        return false;
      }
      const hook = Object.getOwnPropertyDescriptor(inherited, "toJSON");
      if (hook && (!Object.hasOwn(hook, "value") || typeof hook.value === "function")) {
        return false;
      }
    }
    let length = 0;
    if (array) {
      const size: unknown = Object.getOwnPropertyDescriptor(value, "length")?.value;
      if (typeof size !== "number" || !Number.isSafeInteger(size) || size < 0) {
        return false;
      }
      length = size;
    }
    let indices = 0;
    for (const key of Reflect.ownKeys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !Object.hasOwn(descriptor, "value")) {
        return false;
      }
      pending.push(descriptor.value);
      if (array && typeof key === "string") {
        const index = Number(key);
        if (Number.isInteger(index) && index >= 0 && index < length && String(index) === key) {
          indices++;
        }
      }
    }
    // JSON reads inherited indices for holes; counting own indices avoids probing a huge sparse array.
    if (array && indices !== length) {
      return false;
    }
  }
  return true;
}

/** Terminal even when incomplete or invalid; detach retained originals before any fallible lookup. */
export function consumeOpsysRuntimeCompletionCustody(
  handle: unknown,
): readonly CompletionCustodyRecord[] | undefined {
  const state = completionCustodyState(handle);
  if (!state || state.closed) {
    return undefined;
  }
  state.closed = true;
  const records = state.records;
  state.records = undefined;
  try {
    if (!records || records.size !== state.streamOrdinals.length) {
      return undefined;
    }
    const batch: CompletionCustodyRecord[] = [];
    for (const ordinal of state.streamOrdinals) {
      const record = records.get(ordinal);
      if (!record) {
        return undefined;
      }
      batch.push(record);
    }
    if (!completionCustodyDataIsInert(batch.map((record) => record.message))) {
      return undefined;
    }
    // All graphs are inert before the first digest. With standard intrinsics, no user code
    // can mutate an earlier member during this synchronous check; originals remain mutable after return.
    for (const record of batch) {
      if (getOpsysRuntimeCompletionReceipt(record.message, record.receipt) !== record.receipt) {
        return undefined;
      }
    }
    return Object.freeze(batch);
  } catch {
    return undefined;
  } finally {
    records?.clear();
  }
}

/** Unknown handles are inert; closing never calls user code or restores closed custody. */
export function closeOpsysRuntimeCompletionCustody(handle: unknown): void {
  try {
    const state = completionCustodyState(handle);
    if (state) {
      closeCompletionCustodyState(state);
    }
  } catch {
    // Cleanup cannot turn an otherwise successful provider result into an error.
  }
}

/** Read only the existing seal and lexical admission capture: no JSON, callback, await or dispatch. */
function captureOpsysRuntimeCompletionCustody(
  handle: unknown,
  message: unknown,
  capture: RuntimeReservationCapture,
): void {
  let state: CompletionCustodyState | undefined;
  try {
    state = completionCustodyState(handle);
    if (!state || state.closed) {
      return;
    }
    const receipt =
      message !== null && typeof message === "object" ? completionReceipts.get(message) : undefined;
    let receiptMatchesCapture = receipt !== undefined;
    if (receipt) {
      for (const field of completionBindingFields) {
        if (receipt[field] !== capture[field]) {
          receiptMatchesCapture = false;
          break;
        }
      }
    }
    const binding = state.binding;
    if (
      !receipt ||
      binding.agentId !== capture.agentId ||
      binding.profileId !== capture.profileId ||
      binding.profileRevision !== capture.profileRevision ||
      binding.departement !== capture.departement ||
      binding.runId !== capture.runId ||
      binding.candidateIndex !== capture.candidateIndex ||
      !receiptMatchesCapture ||
      receipt.candidateIndex !== capture.candidateIndex ||
      receipt.streamOrdinal !== capture.streamOrdinal ||
      !state.streamOrdinals.includes(capture.streamOrdinal) ||
      !state.records ||
      state.records.has(capture.streamOrdinal)
    ) {
      closeCompletionCustodyState(state);
      return;
    }
    state.records.set(capture.streamOrdinal, Object.freeze({ message, receipt }));
  } catch {
    if (state) {
      closeCompletionCustodyState(state);
    }
  }
}

type RuntimeProfileBinding = { profileId?: unknown; profileRevision?: unknown };
type RuntimeReservationCapture = {
  readonly config: OpenClawConfig | undefined;
  readonly agentId: string;
  readonly reservationId: string;
  readonly profileId: string;
  readonly profileRevision: number;
  readonly runId: string;
  readonly attemptId: string;
  readonly cycleId: string;
  readonly candidateIndex: number;
  readonly streamOrdinal: number;
  readonly tokensPlafond: number;
  readonly departement: string;
};

/** Best-effort proof only after exact reconciliation; never reject a known reconciled result. */
function sealOpsysRuntimeCompletion(
  message: unknown,
  capture: RuntimeReservationCapture,
  tokensReels: number,
): void {
  try {
    if (message === null || typeof message !== "object" || Array.isArray(message)) {
      return;
    }
    // A later cycle sharing this object cannot overwrite or claim the first association.
    if (completionReceipts.has(message)) {
      return;
    }
    const resultSHA256 = completionResultSHA256(message);
    if (resultSHA256 === undefined) {
      return;
    }
    completionReceipts.set(
      message,
      Object.freeze({
        agentId: capture.agentId,
        profileId: capture.profileId,
        profileRevision: capture.profileRevision,
        departement: capture.departement,
        runId: capture.runId,
        attemptId: capture.attemptId,
        cycleId: capture.cycleId,
        candidateIndex: capture.candidateIndex,
        streamOrdinal: capture.streamOrdinal,
        resultSHA256,
        tokensReels,
      }),
    );
  } catch {
    // Missing proof must not change provider/reconciliation success or trigger another dispatch.
  }
}

function admissionBinding(
  config: OpenClawConfig | undefined,
  agentId: string,
): RuntimeProfileBinding | undefined {
  const entry = config?.agents?.entries?.[agentId] as
    | { opsysRuntimeAdmission?: RuntimeProfileBinding }
    | undefined;
  return entry?.opsysRuntimeAdmission;
}

function admissionProfile(config: OpenClawConfig | undefined, agentId: string): string | undefined {
  const profileId = admissionBinding(config, agentId)?.profileId;
  return typeof profileId === "string" ? profileId : undefined;
}

function profileRevision(config: OpenClawConfig | undefined, agentId: string): number {
  const revision = admissionBinding(config, agentId)?.profileRevision;
  if (typeof revision !== "number" || !Number.isSafeInteger(revision) || revision < 1) {
    throw new Error(`OPSYS runtime profile revision is required for agent ${agentId}`);
  }
  return revision;
}

export function requiresOpsysRuntimeAdmission(
  config: OpenClawConfig | undefined,
  agentId: string,
): boolean {
  // Earlier generated department entries had isolation but no durable admission binding.
  // Keep those installed entries fail-closed during explicit profile provisioning; do not
  // turn a missing migration choice into a free provider path. Generic Core agents retain
  // their existing contract.
  const departmentEntry = config?.agents?.entries?.[agentId];
  return (
    admissionProfile(config, agentId) !== undefined ||
    (canonicalDepartment(agentId) && departmentEntry?.opsysIsolation?.exec === "sandbox-required")
  );
}

/** Generic compaction owns a separate provider path, so profiled runs refuse it until gated. */
export function opsysRuntimeCompactionRefusal(
  config: OpenClawConfig | undefined,
  agentId: string,
): string | undefined {
  return requiresOpsysRuntimeAdmission(config, agentId)
    ? "OPSYS-profiled agents cannot use generic compaction until its provider call has runtime admission."
    : undefined;
}

function integer(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

function resultObject(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const envelope = value as Record<string, unknown>;
  if (envelope.ok !== true || envelope.resultat === null || typeof envelope.resultat !== "object") {
    return undefined;
  }
  return envelope.resultat as Record<string, unknown>;
}

function canonicalDepartment(value: unknown): value is string {
  return typeof value === "string" && /^m(?:0[1-9]|10)-[a-z][a-z0-9-]+$/.test(value);
}

function reservationMatchesCapture(
  reservation: Record<string, unknown> | undefined,
  capture: Omit<RuntimeReservationCapture, "config">,
  status: "reservee" | "conciliee" | "liberee",
  tokensReels: number | null,
): boolean {
  return Boolean(
    reservation &&
    typeof reservation.id === "string" &&
    /^[0-9a-f]{32}$/.test(reservation.id) &&
    reservation.id === capture.reservationId &&
    reservation.agent_id === capture.profileId &&
    canonicalDepartment(reservation.departement) &&
    reservation.departement === capture.departement &&
    reservation.cle_idempotence === capture.cycleId &&
    reservation.tokens_plafond === capture.tokensPlafond &&
    reservation.tokens_reels === tokensReels &&
    reservation.execution_id === capture.runId &&
    reservation.tours === 1 &&
    reservation.reessais === capture.candidateIndex &&
    reservation.statut === status &&
    reservation.attempt_id === capture.attemptId &&
    reservation.cycle_id === capture.cycleId &&
    reservation.candidate_index === capture.candidateIndex &&
    reservation.stream_ordinal === capture.streamOrdinal &&
    reservation.is_fallback_retry === capture.candidateIndex > 0 &&
    (reservation.revision_profil === undefined ||
      reservation.revision_profil === capture.profileRevision),
  );
}

function throwRefusal(value: unknown): void {
  if (value === null || typeof value !== "object") {
    return;
  }
  const envelope = value as Record<string, unknown>;
  if (envelope.ok === false) {
    const reason =
      typeof envelope.details === "string"
        ? envelope.details
        : typeof envelope.erreur === "string"
          ? envelope.erreur
          : "request refused";
    throw new Error(`OPSYS runtime admission refused: ${reason}`);
  }
}

/** The profile id is read from the validated agent entry, never from model/tool arguments. */
async function reserveCapturedOpsysRuntimeAdmission(params: {
  config: OpenClawConfig | undefined;
  agentId: string;
  runId: string;
  candidateIndex: number;
  streamOrdinal: number;
  isFallbackRetry: boolean;
  tokensPlafond: number;
  signal: AbortSignal;
}): Promise<RuntimeReservationCapture> {
  const agentId = params.agentId;
  let config: OpenClawConfig | undefined;
  try {
    // Validated host config is plain data. Retain no alias to its mutable MCP URL/header maps.
    config = structuredClone(params.config);
  } catch {
    throw new Error("OPSYS runtime admission configuration could not be captured");
  }
  const profileId = admissionProfile(config, agentId);
  if (!profileId) {
    throw new Error(`OPSYS runtime admission is required but missing for agent ${agentId}`);
  }
  const revision = profileRevision(config, agentId);
  const runId = params.runId;
  const candidateIndex = params.candidateIndex;
  const streamOrdinal = params.streamOrdinal;
  const attemptId = `${runId}:${candidateIndex}`;
  const cycleId = `${attemptId}:${streamOrdinal}`;
  const value = await callOpsysMcpTool({
    config,
    server: `opsys_runtime_${profileId}`,
    tool: "opsys_runtime_admettre",
    args: {
      execution_id: runId,
      cle_idempotence: cycleId,
      tokens_plafond: params.tokensPlafond,
      revision_profil: revision,
      tours: 1,
      attempt_id: attemptId,
      cycle_id: cycleId,
      candidate_index: candidateIndex,
      stream_ordinal: streamOrdinal,
      is_fallback_retry: params.isFallbackRetry,
    },
    timeoutMs: TIMEOUT_MS,
    signal: params.signal,
  });
  throwRefusal(value);
  const reservation = resultObject(value);
  const accordNeuf =
    value !== null && typeof value === "object"
      ? (value as Record<string, unknown>).accord_neuf === true
      : false;
  if (
    !accordNeuf ||
    typeof reservation?.id !== "string" ||
    !/^[0-9a-f]{32}$/.test(reservation.id)
  ) {
    throw new Error("OPSYS runtime admission did not return a reservation id");
  }
  if (!canonicalDepartment(reservation.departement)) {
    throw new Error("OPSYS runtime admission receipt does not match the captured request");
  }
  const captureWithoutConfig = {
    agentId,
    reservationId: reservation.id,
    profileId,
    profileRevision: revision,
    runId,
    attemptId,
    cycleId,
    candidateIndex,
    streamOrdinal,
    tokensPlafond: params.tokensPlafond,
    departement: reservation.departement,
  };
  if (!reservationMatchesCapture(reservation, captureWithoutConfig, "reservee", null)) {
    throw new Error("OPSYS runtime admission receipt does not match the captured request");
  }
  return Object.freeze({
    config,
    agentId,
    reservationId: reservation.id,
    profileId,
    profileRevision: revision,
    runId,
    attemptId,
    cycleId,
    candidateIndex,
    streamOrdinal,
    tokensPlafond: params.tokensPlafond,
    departement: reservation.departement,
  });
}

/** Preserve the existing caller contract; only this module's stream gate retains the capture. */
export async function reserveOpsysRuntimeAdmission(
  params: Parameters<typeof reserveCapturedOpsysRuntimeAdmission>[0],
): Promise<string> {
  return (await reserveCapturedOpsysRuntimeAdmission(params)).reservationId;
}

/** Private host cleanup, callable only from the pre-invocation catch below. */
async function releaseBeforeProviderDispatch(capture: RuntimeReservationCapture): Promise<void> {
  const value = await callOpsysMcpTool({
    config: capture.config,
    server: `opsys_runtime_${capture.profileId}`,
    tool: "opsys_runtime_liberer_avant_dispatch",
    args: {
      reservation_id: capture.reservationId,
      execution_id: capture.runId,
      attempt_id: capture.attemptId,
      cycle_id: capture.cycleId,
      candidate_index: capture.candidateIndex,
      stream_ordinal: capture.streamOrdinal,
      revision_profil: capture.profileRevision,
    },
    timeoutMs: TIMEOUT_MS,
    // The dispatch authority can already be aborted: cleanup has its own bounded lifetime.
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  throwRefusal(value);
  const reservation = resultObject(value);
  if (!reservationMatchesCapture(reservation, capture, "liberee", null)) {
    throw new Error("OPSYS runtime admission could not confirm pre-dispatch release");
  }
}

/** Revalidate a configured profile's MCP tool immediately before Core dispatches it. */
export async function verifyOpsysRuntimeToolCall(params: {
  config: OpenClawConfig | undefined;
  agentId: string | undefined;
  toolName: string;
  signal?: AbortSignal;
}): Promise<void> {
  if (!params.agentId) {
    return;
  }
  const profileId = admissionProfile(params.config, params.agentId);
  if (!profileId) {
    return;
  }
  const mcpTool =
    /^(opsys_m(?:[1-9]|10))__((?:m[1-9]|m10)_[a-z0-9_]+|opsys_(?:lire_artefact|etat_budget|demandes_approbation|memoire_rechercher|memoire_ajouter|memoire_oublier))$/.exec(
      params.toolName,
    );
  if (!mcpTool) {
    return;
  }
  const revision = profileRevision(params.config, params.agentId);
  const value = await callOpsysMcpTool({
    config: params.config,
    server: `opsys_runtime_${profileId}`,
    tool: "opsys_runtime_verifier_outil",
    args: { outil: params.toolName, revision_profil: revision },
    timeoutMs: TIMEOUT_MS,
    signal: params.signal ?? new AbortController().signal,
  });
  throwRefusal(value);
  const result = resultObject(value);
  if (result?.autorise !== true || result.revision_profil !== revision) {
    throw new Error("OPSYS configured tool permission could not be verified");
  }
}

async function reconcileCapturedOpsysRuntimeAdmission(params: {
  capture: RuntimeReservationCapture;
  tokensReels: number;
}): Promise<void> {
  if (integer(params.tokensReels) === undefined) {
    throw new Error("invalid provider usage for OPSYS admission");
  }
  const value = await callOpsysMcpTool({
    config: params.capture.config,
    server: `opsys_runtime_${params.capture.profileId}`,
    tool: "opsys_runtime_concilier",
    args: { reservation_id: params.capture.reservationId, tokens_reels: params.tokensReels },
    timeoutMs: TIMEOUT_MS,
    // Known provider usage must be accounted for even after delivery is cancelled.
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  throwRefusal(value);
  const reservation = resultObject(value);
  if (!reservationMatchesCapture(reservation, params.capture, "conciliee", params.tokensReels)) {
    throw new Error("OPSYS runtime admission could not verify the reconciled provider usage");
  }
}

/** Retain the existing exported API for non-stream internal callers. */
export async function reconcileOpsysRuntimeAdmission(params: {
  config: OpenClawConfig | undefined;
  agentId: string;
  reservationId: string;
  tokensReels: number;
  signal: AbortSignal;
}): Promise<void> {
  const profileId = admissionProfile(params.config, params.agentId);
  if (!profileId) {
    throw new Error(`OPSYS runtime admission is required but missing for agent ${params.agentId}`);
  }
  if (integer(params.tokensReels) === undefined) {
    throw new Error("invalid provider usage for OPSYS admission");
  }
  const value = await callOpsysMcpTool({
    config: params.config,
    server: `opsys_runtime_${profileId}`,
    tool: "opsys_runtime_concilier",
    args: { reservation_id: params.reservationId, tokens_reels: params.tokensReels },
    timeoutMs: TIMEOUT_MS,
    signal: params.signal,
  });
  throwRefusal(value);
  const reservation = resultObject(value);
  if (
    reservation?.id !== params.reservationId ||
    reservation.agent_id !== profileId ||
    !canonicalDepartment(reservation.departement) ||
    reservation.statut !== "conciliee" ||
    reservation.tokens_reels !== params.tokensReels
  ) {
    throw new Error("OPSYS runtime admission could not verify the reconciled provider usage");
  }
}

export function opsysAdmissionEnvelope(
  model: { contextWindow?: number; maxTokens?: number },
  context: Parameters<StreamFn>[1],
  outputLimit?: number,
): number {
  const contextWindow = integer(model.contextWindow);
  const maxOutput = integer(outputLimit ?? model.maxTokens ?? model.contextWindow);
  if (!contextWindow || !maxOutput || !Array.isArray(context.messages)) {
    throw new Error(
      "OPSYS runtime admission requires a context, contextWindow and output token bound",
    );
  }
  const estimateInput = createFreshLlmBoundaryTokenEstimator({
    systemPrompt: context.systemPrompt,
    tools: context.tools,
  })({ messages: context.messages as AgentMessage[], prompt: "" });
  const envelope = estimateInput + maxOutput;
  if (!Number.isSafeInteger(envelope) || envelope < 1 || estimateInput > contextWindow) {
    throw new Error("OPSYS runtime admission token envelope is invalid");
  }
  return envelope;
}

/** Gate exactly one provider stream, leaving uncertain provider outcomes reserved. */
export function createOpsysRuntimeAdmissionStreamFn(params: {
  config: OpenClawConfig | undefined;
  agentId: string;
  runId: string;
  getCandidateIndex: () => number;
  signal?: AbortSignal;
  streamFn: StreamFn;
  /** Private attempt-local custody; never supplied by provider/model JSON. */
  completionCustody?: OpsysRuntimeCompletionCustody;
  /** Rechecks live host authority after budget admission and just before provider dispatch. */
  beforeProviderDispatch?: (signal: AbortSignal) => Promise<void>;
  /** Receives the admitted receipt only after its request match and live-authority recheck. */
  onAdmitted?: (receipt: OpsysRuntimeAdmissionReceipt) => void;
}): StreamFn {
  let streamOrdinal = 0;
  return async (model, context, options) => {
    const completionCustody = params.completionCustody;
    const signal = options?.signal ?? params.signal ?? new AbortController().signal;
    const ordinal = streamOrdinal++;
    const candidateIndex = params.getCandidateIndex();
    if (!Number.isSafeInteger(candidateIndex) || candidateIndex < 0) {
      throw new Error("OPSYS runtime admission is missing the host candidate ordinal");
    }
    const capture = await reserveCapturedOpsysRuntimeAdmission({
      config: params.config,
      agentId: params.agentId,
      runId: params.runId,
      candidateIndex,
      streamOrdinal: ordinal,
      // The backend defines fallback retries by contiguous admitted candidate
      // ordinal; model routing provenance may still say fallback when earlier
      // candidates never reached admission.
      isFallbackRetry: candidateIndex > 0,
      tokensPlafond: opsysAdmissionEnvelope(model, context, options?.maxTokens),
      signal,
    });
    try {
      await params.beforeProviderDispatch?.(signal);
      signal.throwIfAborted();
      params.onAdmitted?.(
        Object.freeze({
          agentId: capture.agentId,
          profileId: capture.profileId,
          profileRevision: capture.profileRevision,
          departement: capture.departement,
          runId: capture.runId,
          attemptId: capture.attemptId,
          cycleId: capture.cycleId,
        }),
      );
    } catch (error) {
      try {
        await releaseBeforeProviderDispatch(capture);
      } catch {
        // Unconfirmed cleanup remains operator-recoverable; preserve the original gate refusal.
      }
      throw error;
    }
    // Even a synchronous throw from streamFn is an invoked provider with an uncertain outcome.
    const stream = await params.streamFn(model, context, options);
    const originalResult = stream.result.bind(stream);
    let resultPromise: ReturnType<typeof originalResult> | undefined;
    Object.defineProperty(stream, "result", {
      configurable: true,
      value: () => {
        // Assign the promise before invoking provider code, including synchronous throws/reentrancy.
        resultPromise ??= Promise.resolve().then(async () => {
          const message = await originalResult();
          const usage = message.usage;
          const tokensReels = usage?.totalTokens;
          if (tokensReels === undefined || !Number.isSafeInteger(tokensReels) || tokensReels <= 0) {
            throw new Error(
              "provider returned no reliable token usage; OPSYS reservation remains open",
            );
          }
          try {
            await reconcileCapturedOpsysRuntimeAdmission({
              capture,
              tokensReels,
            });
          } catch (cause) {
            // The provider already returned reliable usage; replay cannot repair local accounting.
            // Keep the original transport error reusable outside this terminal attempt.
            const error = new Error(
              "OPSYS runtime reconciliation failed after known provider usage; fallback is unsafe",
              { cause },
            );
            recordModelFallbackStop(error);
            throw error;
          }
          sealOpsysRuntimeCompletion(message, capture, tokensReels);
          captureOpsysRuntimeCompletionCustody(completionCustody, message, capture);
          return message;
        });
        return resultPromise;
      },
    });
    return stream;
  };
}
