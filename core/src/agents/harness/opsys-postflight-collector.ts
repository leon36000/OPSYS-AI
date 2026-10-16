import { createHash } from "node:crypto";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { OpsysCibleTicketReceipt } from "../../context-engine/opsys-contexte-cible-ticket.js";
import { isOpsysCibleTicketTool } from "../../context-engine/opsys-contexte-cibles.js";
import {
  collectDepositFactForToolResult,
  depositKey,
} from "../../context-engine/opsys-contexte-depot.js";
import type { UserTurnTranscriptRecorder } from "../../sessions/user-turn-transcript.types.js";
import type {
  OpenClawAgentDatabase,
  OpenClawAgentDatabaseOptions,
} from "../../state/openclaw-agent-db-contract.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import type { OpsysRuntimeAdmissionReceipt } from "../embedded-agent-runner/opsys-runtime-admission.js";
import {
  deliverOpsysPostflightLots,
  type OpsysPostflightDeliveryResult,
} from "./opsys-postflight-delivery.js";
import {
  completeOpsysPostflightIntent,
  observeOpsysM9ApprovalPending,
  reserveOpsysPostflightIntent,
  type OpsysPostflightIntentInput,
  type OpsysPostflightFact,
  type OpsysPostflightLotInput,
} from "./opsys-postflight-outbox.js";

export type OpsysDeferredPostflightReceipt = Readonly<{
  sessionId: string;
  sessionKey: string;
  agentId: string;
  factKeys: readonly string[];
}>;

export type OpsysPostflightCallObserver = Readonly<{
  checkCurrent: () => void;
  assertBeforeEffect: (target: OpsysCibleTicketReceipt) => Promise<void>;
  recordUnknownOutcome: () => void;
  observe: (
    target: OpsysCibleTicketReceipt,
    result: CallToolResult,
    state: { authorityCurrent: boolean },
  ) => Promise<void>;
}>;

const MAX_FACTS_PER_ATTEMPT = 20;
const MAX_ENQUEUE_ATTEMPTS = 2;

type CapturedFact = Readonly<{ lot: OpsysPostflightLotInput; intent: OpsysPostflightIntentInput }>;

function sameLot(left: OpsysPostflightLotInput, right: OpsysPostflightLotInput): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function observedM9PendingRequest(toolName: string, result: CallToolResult): string | undefined {
  if (
    toolName !== "m9_ouvrir_suivi_decision" ||
    result.isError === true ||
    result.content.length !== 1
  ) {
    return undefined;
  }
  const block = result.content[0];
  if (block?.type !== "text") {
    return undefined;
  }
  let response: unknown;
  try {
    response = JSON.parse(block.text);
  } catch {
    return undefined;
  }
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    return undefined;
  }
  if (
    !("ok" in response) ||
    response.ok !== true ||
    !("statut" in response) ||
    response.statut !== "en_attente_approbation" ||
    !("demande_id" in response) ||
    typeof response.demande_id !== "string" ||
    !/^[0-9a-f]{12}$/u.test(response.demande_id)
  ) {
    return undefined;
  }
  return response.demande_id;
}

/** Attempt-owned collector. Its DB identity comes only from the persisted user-turn receipt. */
export class OpsysPostflightCollector {
  readonly #runId: string;
  readonly #sessionId: string;
  readonly #sessionKey: string;
  readonly #agentId: string;
  readonly #recorder: Pick<
    UserTurnTranscriptRecorder,
    "waitForRuntimePersistence" | "getAdmissionReceipt"
  >;
  readonly #assertCurrent: () => void;
  readonly #depositTools: ReadonlySet<string>;
  readonly #usedCallIds = new Set<string>();
  readonly #knownFacts = new Map<string, OpsysPostflightLotInput>();
  readonly #pending = new Map<string, CapturedFact>();
  readonly #openIntents = new Set<string>();
  #runtimeAdmission: OpsysRuntimeAdmissionReceipt | undefined;
  #database: OpenClawAgentDatabase | undefined;
  #databaseOptions: OpenClawAgentDatabaseOptions | undefined;
  #reservedFacts = 0;
  #revokedAfterEffect = 0;
  #captureFailures = 0;

  constructor(params: {
    runId: string;
    sessionId: string;
    sessionKey: string;
    agentId: string;
    recorder: Pick<UserTurnTranscriptRecorder, "waitForRuntimePersistence" | "getAdmissionReceipt">;
    depositTools: readonly string[];
    assertCurrent: () => void;
  }) {
    this.#runId = params.runId;
    this.#sessionId = params.sessionId;
    this.#sessionKey = params.sessionKey;
    this.#agentId = params.agentId;
    this.#recorder = params.recorder;
    this.#depositTools = new Set(params.depositTools);
    this.#assertCurrent = params.assertCurrent;
  }

  recordRuntimeAdmission(receipt: OpsysRuntimeAdmissionReceipt): void {
    this.#runtimeAdmission = undefined;
    if (
      receipt.runId !== this.#runId ||
      receipt.agentId !== this.#agentId ||
      typeof receipt.profileId !== "string" ||
      receipt.profileId.length === 0 ||
      !Number.isSafeInteger(receipt.profileRevision) ||
      receipt.profileRevision < 1 ||
      typeof receipt.departement !== "string" ||
      !/^m(?:0[1-9]|10)-[a-z][a-z0-9-]*$/u.test(receipt.departement) ||
      typeof receipt.attemptId !== "string" ||
      receipt.attemptId.length === 0 ||
      typeof receipt.cycleId !== "string" ||
      receipt.cycleId.length === 0
    ) {
      throw new Error("OPSYS postflight runtime admission receipt is invalid or stale");
    }
    this.#runtimeAdmission = Object.freeze({ ...receipt });
  }

  /** Wait for the recorder's real append; never installs or replaces its admission handler. */
  async prepareBeforeProviderDispatch(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    this.#assertCurrent();
    await this.#recorder.waitForRuntimePersistence();
    signal?.throwIfAborted();
    this.#assertCurrent();
    const receipt = this.#recorder.getAdmissionReceipt();
    if (
      !receipt ||
      receipt.agentId !== this.#agentId ||
      receipt.sessionId !== this.#sessionId ||
      receipt.sessionKey !== this.#sessionKey ||
      typeof receipt.storePath !== "string" ||
      receipt.storePath.length === 0
    ) {
      throw new Error("OPSYS postflight requires a matching persisted transcript admission");
    }
    const options = { agentId: receipt.agentId, path: receipt.storePath };
    const database = openOpenClawAgentDatabase(options);
    if (database.agentId !== receipt.agentId) {
      throw new Error("OPSYS postflight transcript database owner mismatch");
    }
    this.#databaseOptions = options;
    this.#database = database;
  }

  beginToolCall(params: {
    toolCallId: string;
    toolName: string;
    serverName: string;
  }): OpsysPostflightCallObserver | undefined {
    if (!this.#depositTools.has(params.toolName) || !isOpsysCibleTicketTool(params.toolName)) {
      return undefined;
    }
    if (!params.toolCallId || this.#usedCallIds.has(params.toolCallId)) {
      throw new Error("OPSYS postflight duplicate or empty tool call id refused before effect");
    }
    const admission = this.#runtimeAdmission;
    if (!admission || !this.#database || !this.#databaseOptions) {
      throw new Error("OPSYS postflight authority is incomplete before tool dispatch");
    }
    const database = this.#database;
    const databaseOptions = this.#databaseOptions;
    let reserved = false;
    let completed = false;
    let durableIntent: OpsysPostflightIntentInput | undefined;
    const assertBeforeEffect = async (target: OpsysCibleTicketReceipt) => {
      if (reserved) {
        throw new Error("OPSYS postflight source effect reservation cannot be reused");
      }
      this.#assertCurrent();
      if (this.#runtimeAdmission !== admission) {
        throw new Error("OPSYS postflight runtime admission changed before the effect");
      }
      if (this.#pending.size > 0 || this.#captureFailures > 0) {
        throw new Error("OPSYS postflight durable capture is unresolved; new effect refused");
      }
      if (this.#usedCallIds.has(params.toolCallId)) {
        throw new Error("OPSYS postflight duplicate tool call id refused before effect");
      }
      if (this.#reservedFacts >= MAX_FACTS_PER_ATTEMPT) {
        throw new Error("OPSYS postflight per-attempt fact capacity reached before effect");
      }
      if (
        !target ||
        target.agentId !== admission.agentId ||
        target.sessionKey !== this.#sessionKey ||
        target.toolName !== params.toolName ||
        target.serverName !== params.serverName ||
        !target.affaireId
      ) {
        throw new Error("OPSYS postflight requires the exact private target before reservation");
      }
      this.#usedCallIds.add(params.toolCallId);
      this.#reservedFacts += 1;
      reserved = true;
      const intent: OpsysPostflightIntentInput = Object.freeze({
        factKey: depositKey(this.#sessionId, params.toolCallId),
        affaireId: target.affaireId,
        departementSource: admission.departement,
        profilId: admission.profileId,
        revision: admission.profileRevision,
        engineId: "opsys",
        outil: params.toolName,
        serverName: params.serverName,
        // A scoped opaque correlation key, not encryption or proof of a business effect.
        ownerKey: createHash("sha256")
          .update(
            JSON.stringify([
              "opsys-source-intent-v1",
              this.#agentId,
              this.#sessionId,
              this.#runId,
              admission.attemptId,
              admission.cycleId,
              params.toolCallId,
            ]),
            "utf8",
          )
          .digest("hex"),
      });
      try {
        await reserveOpsysPostflightIntent({
          database: this.#database!,
          options: this.#databaseOptions!,
          intent,
          now: Date.now(),
          assertCurrent: () => {
            this.#assertCurrent();
            if (this.#runtimeAdmission !== admission) {
              throw new Error("OPSYS postflight admission changed during durable reservation");
            }
          },
        });
        durableIntent = intent;
        this.#openIntents.add(intent.factKey);
        this.#assertCurrent();
        if (this.#runtimeAdmission !== admission) {
          throw new Error("OPSYS postflight admission changed after durable reservation");
        }
      } catch (error) {
        this.#captureFailures += 1;
        throw error;
      }
    };
    return Object.freeze({
      checkCurrent: this.#assertCurrent,
      assertBeforeEffect,
      recordUnknownOutcome: () => {
        if (completed || !durableIntent) {
          return;
        }
        completed = true;
        // Keep the pre-dispatch uncertain row; do not manufacture a refusal or replay.
        this.#captureFailures += 1;
      },
      observe: async (
        target: OpsysCibleTicketReceipt,
        result: CallToolResult,
        state: { authorityCurrent: boolean },
      ) => {
        if (completed || !reserved || !durableIntent) {
          return;
        }
        completed = true;
        if (!state.authorityCurrent) {
          this.#revokedAfterEffect += 1;
        }
        if (
          target.agentId !== admission.agentId ||
          target.sessionKey !== this.#sessionKey ||
          target.toolName !== params.toolName ||
          target.serverName !== params.serverName ||
          target.affaireId !== durableIntent.affaireId
        ) {
          this.#captureFailures += 1;
          return;
        }
        let fact: OpsysPostflightFact | undefined;
        try {
          fact = collectDepositFactForToolResult({
            sessionId: this.#sessionId,
            toolCallId: params.toolCallId,
            toolName: params.toolName,
            content: result.content,
            isError: result.isError === true,
            depositTools: [...this.#depositTools],
          });
        } catch {
          this.#captureFailures += 1;
          return;
        }
        if (!fact) {
          const requestId = observedM9PendingRequest(params.toolName, result);
          if (requestId !== undefined) {
            try {
              await observeOpsysM9ApprovalPending({
                database,
                options: databaseOptions,
                expected: durableIntent,
                requestId,
                now: Date.now(),
              });
            } catch {
              // A crash or failed observation write conservatively leaves the fence armed.
            }
          }
          // The durable uncertain intent remains available for explicit reconciliation.
          this.#captureFailures += 1;
          return;
        }
        // Authority revocation after this effect is reported operationally; it does not
        // change the already-observed business result or authorize downstream dispatch.
        const lot: OpsysPostflightLotInput = {
          affaireId: target.affaireId,
          departementSource: admission.departement,
          profilId: admission.profileId,
          revision: admission.profileRevision,
          engineId: "opsys",
          facts: [fact],
        };
        const key = fact.cle;
        const previous = this.#knownFacts.get(key);
        if (previous && !sameLot(previous, lot)) {
          this.#captureFailures += 1;
          return;
        }
        this.#knownFacts.set(key, lot);
        this.#pending.set(key, { lot, intent: durableIntent });
        await this.#enqueue(key);
      },
    });
  }

  /** Host-only evidence of reserved calls, never an authorization or a guessed affair. */
  getDeferredDepositReceipt(): OpsysDeferredPostflightReceipt | undefined {
    if (!this.#database || !this.#databaseOptions || !this.#runtimeAdmission) {
      return undefined;
    }
    return Object.freeze({
      sessionId: this.#sessionId,
      sessionKey: this.#sessionKey,
      agentId: this.#agentId,
      factKeys: Object.freeze(
        Array.from(this.#usedCallIds, (callId) => depositKey(this.#sessionId, callId)),
      ),
    });
  }

  /** One bounded delivery pass while the attempt still owns live authority. */
  async deliverPending(params: {
    config: OpenClawConfig | undefined;
    timeoutMs: number;
    signal: AbortSignal;
  }): Promise<OpsysPostflightDeliveryResult> {
    const database = this.#database;
    const options = this.#databaseOptions;
    const admission = this.#runtimeAdmission;
    if (!database || !options || !admission) {
      throw new Error("OPSYS postflight delivery authority is incomplete");
    }
    const assertCurrent = () => {
      params.signal.throwIfAborted();
      this.#assertCurrent();
      if (this.#runtimeAdmission !== admission) {
        throw new Error("OPSYS postflight admission changed before delivery");
      }
    };
    assertCurrent();
    const captured = await this.flushPending();
    assertCurrent();
    if (captured.remaining > 0 || captured.failures > 0) {
      throw new Error("OPSYS postflight capture is unresolved before delivery");
    }
    return await deliverOpsysPostflightLots({
      database,
      options,
      config: params.config,
      timeoutMs: params.timeoutMs,
      profile: {
        id: admission.profileId,
        revision: admission.profileRevision,
        departement: admission.departement,
      },
      assertCurrent,
      signal: params.signal,
      nowMs: Date.now,
    });
  }

  async flushPending(): Promise<
    Readonly<{ remaining: number; revokedAfterEffect: number; failures: number }>
  > {
    // Snapshot the bounded pending set; facts arriving during an awaited write belong to the next flush.
    for (const key of Array.from(this.#pending.keys())) {
      await this.#enqueue(key);
    }
    return Object.freeze({
      remaining: this.#pending.size,
      revokedAfterEffect: this.#revokedAfterEffect,
      failures: Math.max(this.#captureFailures + this.#pending.size, this.#openIntents.size),
    });
  }

  async #enqueue(key: string): Promise<void> {
    const captured = this.#pending.get(key);
    const database = this.#database;
    const options = this.#databaseOptions;
    if (!captured || !database || !options) {
      return;
    }
    for (let attempt = 0; attempt < MAX_ENQUEUE_ATTEMPTS; attempt += 1) {
      try {
        await completeOpsysPostflightIntent({
          database,
          options,
          expected: captured.intent,
          fact: captured.lot.facts[0]!,
          now: Date.now(),
        });
        this.#pending.delete(key);
        this.#openIntents.delete(key);
        return;
      } catch {
        // Keep the exact envelope for one local cleanup retry; never replay the remote effect.
      }
    }
  }
}
