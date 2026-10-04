import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import type { AgentMessage } from "../runtime/index.js";
import { createFreshLlmBoundaryTokenEstimator } from "../sessions/context-token-pressure.js";

const TIMEOUT_MS = 10_000;

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
};

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
  return admissionProfile(config, agentId) !== undefined;
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
  if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined;
  const envelope = value as Record<string, unknown>;
  if (envelope.ok !== true || envelope.resultat === null || typeof envelope.resultat !== "object") {
    return undefined;
  }
  return envelope.resultat as Record<string, unknown>;
}

function throwRefusal(value: unknown): void {
  if (value === null || typeof value !== "object") return;
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
  if (!profileId)
    throw new Error(`OPSYS runtime admission is required but missing for agent ${agentId}`);
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
  if (!accordNeuf || typeof reservation?.id !== "string" || reservation.id.length < 8) {
    throw new Error("OPSYS runtime admission did not return a reservation id");
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
  if (
    reservation?.id !== capture.reservationId ||
    reservation.statut !== "liberee" ||
    reservation.agent_id !== capture.profileId ||
    reservation.execution_id !== capture.runId ||
    reservation.attempt_id !== capture.attemptId ||
    reservation.cycle_id !== capture.cycleId ||
    reservation.candidate_index !== capture.candidateIndex ||
    reservation.stream_ordinal !== capture.streamOrdinal
  ) {
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
  const mcpTool = /^(opsys_m(?:[1-9]|10))__((?:m[1-9]|m10)_[a-z0-9_]+)$/.exec(params.toolName);
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

export async function reconcileOpsysRuntimeAdmission(params: {
  config: OpenClawConfig | undefined;
  agentId: string;
  reservationId: string;
  tokensReels: number;
  signal: AbortSignal;
}): Promise<void> {
  const profileId = admissionProfile(params.config, params.agentId);
  if (!profileId)
    throw new Error(`OPSYS runtime admission is required but missing for agent ${params.agentId}`);
  if (integer(params.tokensReels) === undefined)
    throw new Error("invalid provider usage for OPSYS admission");
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
  if (reservation?.statut !== "conciliee" || reservation.tokens_reels !== params.tokensReels) {
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
  /** Rechecks live host authority after budget admission and just before provider dispatch. */
  beforeProviderDispatch?: (signal: AbortSignal) => Promise<void>;
}): StreamFn {
  let streamOrdinal = 0;
  return async (model, context, options) => {
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
    Object.defineProperty(stream, "result", {
      configurable: true,
      value: async () => {
        const message = await originalResult();
        const usage = message.usage;
        const tokensReels = usage?.totalTokens;
        if (tokensReels === undefined || !Number.isSafeInteger(tokensReels) || tokensReels <= 0) {
          throw new Error(
            "provider returned no reliable token usage; OPSYS reservation remains open",
          );
        }
        await reconcileOpsysRuntimeAdmission({
          config: capture.config,
          agentId: capture.agentId,
          reservationId: capture.reservationId,
          tokensReels,
          signal,
        });
        return message;
      },
    });
    return stream;
  };
}
