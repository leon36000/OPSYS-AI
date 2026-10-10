/**
 * Durable channel ingress queue.
 *
 * Stores, claims, completes, and tombstones inbound channel events in OpenClaw state.
 */
import { randomUUID } from "node:crypto";
import { realpathSync } from "node:fs";
import type { DatabaseSync } from "node:sqlite";
import { types } from "node:util";
import { sql, type Selectable } from "kysely";
import {
  executeSqliteQuerySync,
  executeSqliteQueryTakeFirstSync,
  getNodeSqliteKysely,
} from "../../infra/kysely-sync.js";
import { stageSqliteTransactionState } from "../../infra/sqlite-post-commit.js";
import { assertExistingDatabaseIdentity } from "../../infra/sqlite-worker-identity.js";
import {
  borrowOpenClawStateDatabaseForAsyncRead,
  captureOpenClawStateDatabaseReadAdmission,
  openClawStateDatabaseCache,
  requireOpenClawStateDatabaseIdentity,
} from "../../state/openclaw-state-db-cache.js";
import type {
  ChannelIngressEvents,
  DB as OpenClawStateKyselyDatabase,
} from "../../state/openclaw-state-db.generated.js";
import {
  openExistingOpenClawStateDatabaseReadOnly,
  openOpenClawStateDatabase,
  runOpenClawStateWriteTransaction,
} from "../../state/openclaw-state-db.js";
import { resolveOpenClawStateSqlitePath } from "../../state/openclaw-state-db.paths.js";
import { IngressAdoptionLostError } from "./ingress-drain-state.js";

/** Private Core handles; none are SDK queue properties or plugin-supplied callbacks. */
export type NativeSmsClaimRef = Readonly<{ id: string; token: string; ownerId: string }>;
export type NativeSmsCompletionPermit = Readonly<object>;
export type NativeSmsCompletionReceipt = Readonly<object>;
type NativeQueueScope = {
  handle: object;
  queueName: string;
  accountId: string;
  database: ReturnType<typeof openChannelIngressDatabase>;
  assertCurrent: () => void;
};
type NativeQueueOwner = {
  writable: boolean;
  assertViewsCurrent: () => void;
  scope: () => NativeQueueScope;
  complete: (entry: NativeCompletionEntry) => NativeSmsCompletionReceipt;
};
type NativeCompletionEntry = {
  permit: object;
  owner: NativeQueueOwner;
  scope: NativeQueueScope;
  claim: NativeSmsClaimRef;
  sourceOwner: object;
  lifecycleOwner: object;
  assertSourceCurrent?: () => void;
};
type NativeCommitEntry = NativeCompletionEntry & {
  permit: object;
  committed: boolean;
  consumed: boolean;
};
const nativeQueueOwners = new WeakMap<object, NativeQueueOwner>();
const nativeQueueScopes = new WeakMap<DatabaseSync, Map<string, NativeQueueScope>>();
const nativeCompletionPermits = new WeakMap<object, NativeCompletionEntry>();
const nativeCommitReceipts = new WeakMap<object, NativeCommitEntry>();

function requireNativeCompletion(condition: unknown): asserts condition {
  if (!condition) {
    throw new IngressAdoptionLostError("reclaimed");
  }
}
function nativeClaim(value: NativeSmsClaimRef): NativeSmsClaimRef {
  requireNativeCompletion(value !== null && typeof value === "object" && !types.isProxy(value));
  const result: Record<string, string> = Object.create(null);
  requireNativeCompletion(Reflect.ownKeys(value).length === 3);
  for (const field of ["id", "token", "ownerId"] as const) {
    const descriptor = Object.getOwnPropertyDescriptor(value, field);
    requireNativeCompletion(
      descriptor &&
        "value" in descriptor &&
        descriptor.enumerable &&
        typeof descriptor.value === "string" &&
        descriptor.value.length > 0,
    );
    result[field] = descriptor.value;
  }
  return Object.freeze({ id: result.id!, token: result.token!, ownerId: result.ownerId! });
}

/** Exact native factory identity only. Unknown queues do not execute any property/trap. */
export function readNativeSmsQueueScope(queue: unknown): object | undefined {
  if (queue === null || typeof queue !== "object") {
    return undefined;
  }
  const owner = nativeQueueOwners.get(queue);
  try {
    return owner?.scope().handle;
  } catch {
    return undefined;
  }
}

/** Private Core data snapshot. No SDK queue property or dispatch authority. */
export type NativeSmsClaimOrigin = Readonly<{
  queueScope: object;
  accountId: string;
  id: string;
  token: string;
  ownerId: string;
  claimedAt: number;
  receivedAt: number;
  payloadJson: string;
}>;

/** Existing canonical connection only, outside a transaction, exact native queue/view. */
export function readOwnNativeSmsClaimOrigin(
  queue: unknown,
  claim: NativeSmsClaimRef,
): NativeSmsClaimOrigin | null {
  if (queue === null || typeof queue !== "object") {
    return null;
  }
  const owner = nativeQueueOwners.get(queue);
  if (!owner) {
    return null;
  }
  try {
    const ref = nativeClaim(claim);
    owner.assertViewsCurrent();
    const scope = owner.scope();
    scope.assertCurrent();
    const row = executeSqliteQueryTakeFirstSync(
      scope.database.db,
      getChannelIngressKysely(scope.database.db)
        .selectFrom("channel_ingress_events")
        .select(["payload_json", "received_at", "claimed_at"])
        .where("queue_name", "=", scope.queueName)
        .where("channel_id", "=", "sms")
        .where("account_id", "=", scope.accountId)
        .where("event_id", "=", ref.id)
        .where("status", "=", "claimed")
        .where("claim_token", "=", ref.token)
        .where("claim_owner", "=", ref.ownerId)
        // Same maximum as the existing sealed capture. Bound bytes before returning the cell.
        .where(sql<number>`length(CAST(payload_json AS BLOB))`, "<=", 262144),
    );
    owner.assertViewsCurrent();
    scope.assertCurrent();
    if (
      !row ||
      typeof row.payload_json !== "string" ||
      Buffer.byteLength(row.payload_json, "utf8") > 262144 ||
      typeof row.received_at !== "number" ||
      !Number.isSafeInteger(row.received_at) ||
      row.received_at < 0 ||
      typeof row.claimed_at !== "number" ||
      !Number.isSafeInteger(row.claimed_at) ||
      row.claimed_at < 0
    ) {
      return null;
    }
    return Object.freeze({
      queueScope: scope.handle,
      accountId: scope.accountId,
      ...ref,
      claimedAt: row.claimed_at,
      receivedAt: row.received_at,
      payloadJson: row.payload_json,
    });
  } catch {
    return null;
  }
}

/** Called only where Core publishes an actual PluginInstance value view. */
export function registerNativeSmsQueueView(
  original: object,
  view: object,
  assertViewCurrent: () => void,
): void {
  const owner = nativeQueueOwners.get(original);
  if (!owner || original === view || nativeQueueOwners.has(view)) {
    return;
  }
  let closed = false;
  const assertViewsCurrent = () => {
    try {
      requireNativeCompletion(!closed);
      owner.assertViewsCurrent();
      assertViewCurrent();
      owner.assertViewsCurrent();
    } catch {
      closed = true;
      throw new IngressAdoptionLostError("reclaimed");
    }
  };
  nativeQueueOwners.set(view, {
    writable: owner.writable,
    assertViewsCurrent,
    scope: () => {
      assertViewsCurrent();
      return owner.scope();
    },
    complete: owner.complete,
  });
}

/** Captures view lifetime alone; adopted Sources never re-read the completed claim. */
export function readNativeSmsQueueOwnerAssertion(queue: unknown): (() => void) | undefined {
  return queue !== null && typeof queue === "object"
    ? nativeQueueOwners.get(queue)?.assertViewsCurrent
    : undefined;
}

export function prepareOwnNativeCompletion(
  queue: unknown,
  claim: NativeSmsClaimRef,
  sourceOwner: object,
  lifecycleOwner: object,
): NativeSmsCompletionPermit | null {
  if (queue === null || typeof queue !== "object") {
    return null;
  }
  const owner = nativeQueueOwners.get(queue);
  if (!owner?.writable) {
    return null;
  }
  try {
    requireNativeCompletion(
      sourceOwner !== null && typeof sourceOwner === "object" && !types.isProxy(sourceOwner),
    );
    requireNativeCompletion(
      lifecycleOwner !== null &&
        typeof lifecycleOwner === "object" &&
        !types.isProxy(lifecycleOwner),
    );
    const scope = owner.scope();
    const copied = nativeClaim(claim);
    const handle = Object.freeze({});
    nativeCompletionPermits.set(handle, {
      permit: handle,
      owner,
      scope,
      claim: copied,
      sourceOwner,
      lifecycleOwner,
    });
    return handle;
  } catch {
    return null;
  }
}

/** Captured Core Source owner only; this is not a structural SDK queue callback. */
export function bindOwnNativeCompletionGuard(
  permit: NativeSmsCompletionPermit,
  sourceOwner: object,
  lifecycleOwner: object,
  guard: () => void,
): void {
  const entry = nativeCompletionPermits.get(permit);
  requireNativeCompletion(
    entry && entry.sourceOwner === sourceOwner && entry.lifecycleOwner === lifecycleOwner,
  );
  requireNativeCompletion(
    !entry.assertSourceCurrent && typeof guard === "function" && !types.isProxy(guard),
  );
  entry.assertSourceCurrent = guard;
}

export function assertOwnNativeCompletionAccount(
  permit: NativeSmsCompletionPermit,
  accountId: string,
): void {
  const entry = nativeCompletionPermits.get(permit);
  requireNativeCompletion(entry && entry.scope.accountId === accountId);
  entry.scope.assertCurrent();
}

function assertNativeWriteCurrent(entry: NativeCompletionEntry): void {
  requireNativeCompletion(nativeCompletionPermits.get(entry.permit) === entry);
  entry.owner.assertViewsCurrent();
  entry.scope.assertCurrent();
  try {
    entry.assertSourceCurrent?.();
  } catch {
    throw new IngressAdoptionLostError("reclaimed");
  }
  requireNativeCompletion(nativeCompletionPermits.get(entry.permit) === entry);
  assertOwnNativeClaimCurrent(entry.permit);
}

/** Actual current native claim, in addition to the captured Host's freshness checks. */
export function assertOwnNativeClaimCurrent(permit: NativeSmsCompletionPermit): void {
  const entry = nativeCompletionPermits.get(permit);
  requireNativeCompletion(entry);
  requireNativeCompletion(entry.owner.scope() === entry.scope);
  entry.scope.assertCurrent();
  const row = executeSqliteQueryTakeFirstSync(
    entry.scope.database.db,
    getChannelIngressKysely(entry.scope.database.db)
      .selectFrom("channel_ingress_events")
      .select(["claim_token", "claim_owner"])
      .where("event_id", "=", entry.claim.id)
      .where("queue_name", "=", entry.scope.queueName)
      .where("channel_id", "=", "sms")
      .where("account_id", "=", entry.scope.accountId)
      .where("status", "=", "claimed")
      .where("claim_token", "=", entry.claim.token)
      .where("claim_owner", "=", entry.claim.ownerId),
  );
  requireNativeCompletion(
    row?.claim_token === entry.claim.token && row.claim_owner === entry.claim.ownerId,
  );
}

export async function completeOwnNativeClaim(
  permit: NativeSmsCompletionPermit,
): Promise<NativeSmsCompletionReceipt> {
  const entry = nativeCompletionPermits.get(permit);
  requireNativeCompletion(entry);
  assertNativeWriteCurrent(entry);
  requireNativeCompletion(entry.owner.scope() === entry.scope);
  const receipt = entry.owner.complete(entry);
  const commit = nativeCommitReceipts.get(receipt);
  requireNativeCompletion(commit?.committed && !commit.consumed);
  return receipt;
}

export function consumeOwnNativeCompletionReceipt(
  permit: NativeSmsCompletionPermit,
  receipt: NativeSmsCompletionReceipt,
  sourceOwner: object,
  lifecycleOwner: object,
): void {
  const entry = nativeCompletionPermits.get(permit);
  const commit = nativeCommitReceipts.get(receipt);
  requireNativeCompletion(
    entry && commit?.committed && !commit.consumed && commit.permit === permit,
  );
  requireNativeCompletion(
    entry.sourceOwner === sourceOwner && entry.lifecycleOwner === lifecycleOwner,
  );
  requireNativeCompletion(
    commit.sourceOwner === sourceOwner &&
      commit.lifecycleOwner === lifecycleOwner &&
      commit.scope === entry.scope,
  );
  entry.scope.assertCurrent();
  commit.consumed = true;
  nativeCompletionPermits.delete(permit);
}

/** Source/claim retirement revokes a captured write before any subsequent retry. */
export function revokeOwnNativeCompletion(permit: NativeSmsCompletionPermit): void {
  nativeCompletionPermits.delete(permit);
}

/** Pending or retryable inbound channel event stored in the durable ingress queue. */
export type ChannelIngressQueueRecord<TPayload, TMetadata = unknown> = {
  id: string;
  channelId: string;
  accountId: string;
  queueName: string;
  payload: TPayload;
  metadata?: TMetadata;
  receivedAt: number;
  updatedAt: number;
  laneKey?: string;
  attempts: number;
  lastAttemptAt?: number;
  lastError?: string;
};

/** Pending ingress event currently claimed by a worker. */
export type ChannelIngressQueueClaim<TPayload, TMetadata = unknown> = ChannelIngressQueueRecord<
  TPayload,
  TMetadata
> & {
  claim: {
    token: string;
    ownerId: string;
    claimedAt: number;
  };
};

/** Minimal claim reference used to guard completion/release/failure with a claim token. */
export type ChannelIngressQueueClaimRef = {
  id: string;
  claim: {
    token: string;
  };
};

/** Current durable identity only; neither payload nor dispatch authority. */
export type ChannelIngressQueueClaimIdentity = Readonly<{
  id: string;
  token: string;
  ownerId: string;
  claimedAt: number;
}>;

export type ChannelIngressQueueClaimIdentityReader = {
  read(ref: ChannelIngressQueueClaimRef): ChannelIngressQueueClaimIdentity | null;
  dispose(): void;
};

/** Claim identity available when a stale row's payload cannot be decoded. */
export type ChannelIngressQueueCorruptClaim = {
  id: string;
  channelId: string;
  accountId: string;
  queueName: string;
  laneKey?: string;
  reason: "corrupt_payload";
  claim: {
    token: string;
    ownerId: string;
    claimedAt: number;
  };
};

/** Completed ingress event tombstone retained for duplicate detection. */
type ChannelIngressQueueCompletedRecord<TCompletedMetadata = unknown> = {
  id: string;
  channelId: string;
  accountId: string;
  queueName: string;
  completedAt: number;
  metadata?: TCompletedMetadata;
};

/** Failed ingress event tombstone retained for duplicate detection. */
type ChannelIngressQueueFailedRecord = {
  id: string;
  channelId: string;
  accountId: string;
  queueName: string;
  failedAt: number;
  reason: string;
  message?: string;
};

/** Rich failed ingress event retained for diagnostics and operator recovery. */
type ChannelIngressQueueDeadLetterRecord<
  TPayload = unknown,
  TMetadata = unknown,
> = ChannelIngressQueueFailedRecord & {
  payload?: TPayload;
  metadata?: TMetadata;
  receivedAt: number;
  updatedAt: number;
  laneKey?: string;
  attempts: number;
  lastAttemptAt?: number;
};

/** Outcome of asking a channel/account queue to re-enqueue one failed event. */
type ChannelIngressQueueResubmitResult<
  TPayload,
  TMetadata = unknown,
  TCompletedMetadata = unknown,
> =
  | {
      kind: "resubmitted";
      record: ChannelIngressQueueRecord<TPayload, TMetadata>;
      previous: ChannelIngressQueueDeadLetterRecord<TPayload, TMetadata>;
    }
  | { kind: "not-found" }
  | {
      kind: "completed";
      record: ChannelIngressQueueCompletedRecord<TCompletedMetadata>;
    }
  | { kind: "active"; status: "pending" | "claimed" }
  | {
      kind: "unrecoverable";
      record: ChannelIngressQueueDeadLetterRecord<TPayload, TMetadata>;
    };

/** Retention options for pending, completed, and failed ingress queue rows. */
export type ChannelIngressQueuePruneOptions = {
  pendingTtlMs?: number;
  completedTtlMs?: number;
  failedTtlMs?: number;
  pendingMaxEntries?: number;
  completedMaxEntries?: number;
  failedMaxEntries?: number;
  protectIds?: Iterable<string>;
  now?: number;
};

/** Result of enqueueing a possibly duplicate ingress event id. */
type ChannelIngressQueueEnqueueResult<TPayload, TMetadata, TCompletedMetadata> =
  | {
      kind: "accepted";
      duplicate: false;
      record: ChannelIngressQueueRecord<TPayload, TMetadata>;
    }
  | {
      kind: "pending";
      duplicate: true;
      record: ChannelIngressQueueRecord<TPayload, TMetadata>;
    }
  | {
      kind: "claimed";
      duplicate: true;
      record: ChannelIngressQueueClaim<TPayload, TMetadata>;
    }
  | {
      kind: "completed";
      duplicate: true;
      record: ChannelIngressQueueCompletedRecord<TCompletedMetadata>;
    }
  | {
      kind: "failed";
      duplicate: true;
      record: ChannelIngressQueueFailedRecord;
    };

/** Durable FIFO-ish ingress queue with claims, duplicate detection, and retention pruning. */
export type ChannelIngressQueue<TPayload, TMetadata = unknown, TCompletedMetadata = unknown> = {
  enqueue(
    id: string,
    payload: TPayload,
    options?: {
      metadata?: TMetadata;
      receivedAt?: number;
      laneKey?: string;
    },
  ): Promise<ChannelIngressQueueEnqueueResult<TPayload, TMetadata, TCompletedMetadata>>;
  listPending(options?: {
    limit?: number | "all";
    orderBy?: "received" | "id";
  }): Promise<Array<ChannelIngressQueueRecord<TPayload, TMetadata>>>;
  listClaims(): Promise<Array<ChannelIngressQueueClaim<TPayload, TMetadata>>>;
  /** Existing native owner only; read synchronously after the caller's final await. */
  prepareClaimIdentityReader?(): Promise<ChannelIngressQueueClaimIdentityReader>;
  /** Additive SDK seam; optional so existing external queue test doubles remain compatible. */
  listFailed?(options?: {
    limit?: number | "all";
  }): Promise<Array<ChannelIngressQueueDeadLetterRecord<TPayload, TMetadata>>>;
  claimNext(options?: {
    ownerId?: string;
    blockedLaneKeys?: Iterable<string>;
    staleMs?: number;
    orderBy?: "received" | "id";
    scanLimit?: number;
    candidateIds?: Iterable<string>;
    deriveLaneKey?: (record: ChannelIngressQueueRecord<TPayload, TMetadata>) => string | undefined;
    /** Authorize a changed durable lane before the atomic pending-to-claimed transition. */
    reconcileStoredLaneKey?: (
      record: ChannelIngressQueueRecord<TPayload, TMetadata>,
      storedLaneKey: string,
      derivedLaneKey: string,
    ) => boolean;
  }): Promise<ChannelIngressQueueClaim<TPayload, TMetadata> | null>;
  claim(
    id: string,
    options?: { ownerId?: string },
  ): Promise<ChannelIngressQueueClaim<TPayload, TMetadata> | null>;
  refreshClaim?(
    claim: ChannelIngressQueueClaimRef,
    options?: { refreshedAt?: number },
  ): Promise<boolean>;
  complete(
    idOrClaim: string | ChannelIngressQueueClaimRef,
    options?: { metadata?: TCompletedMetadata; completedAt?: number },
  ): Promise<boolean>;
  release(
    idOrClaim: string | ChannelIngressQueueClaimRef,
    options?: { lastError?: string; releasedAt?: number; recordAttempt?: boolean },
  ): Promise<boolean>;
  fail(
    idOrClaim: string | ChannelIngressQueueClaimRef,
    options: { reason: string; message?: string; failedAt?: number },
  ): Promise<boolean>;
  /** Additive SDK seam; actual runtime queues support operator resubmission. */
  resubmit?(
    id: string,
    options?: { resubmittedAt?: number },
  ): Promise<ChannelIngressQueueResubmitResult<TPayload, TMetadata, TCompletedMetadata>>;
  delete(
    idOrClaim:
      | string
      | ChannelIngressQueueRecord<TPayload, TMetadata>
      | ChannelIngressQueueClaimRef,
  ): Promise<boolean>;
  recoverStaleClaims(options?: {
    staleMs?: number;
    now?: number;
    shouldRecover?: (
      claim: ChannelIngressQueueClaim<TPayload, TMetadata>,
    ) => boolean | Promise<boolean>;
    shouldRecoverCorrupt?: (claim: ChannelIngressQueueCorruptClaim) => boolean | Promise<boolean>;
  }): Promise<number>;
  prune(options?: ChannelIngressQueuePruneOptions): Promise<number>;
};

/** Construction options for a channel/account-scoped ingress queue. */
export type CreateChannelIngressQueueOptions = {
  channelId: string;
  accountId?: string;
  stateDir?: string;
  now?: () => number;
  /**
   * `read-only` reads through the existing-database read-only opener, which never
   * creates, migrates, chmods or configures the shared state file. Callers that must
   * not touch durable state before they own it - Doctor detection runs before the
   * exclusive maintenance lock - use it so listing cannot take a write path.
   */
  access?: "read-write" | "read-only";
};

type ChannelIngressDatabase = Pick<OpenClawStateKyselyDatabase, "channel_ingress_events">;
type ChannelIngressRow = Selectable<ChannelIngressEvents>;

// Failed rows need to distinguish a retained JSON null payload from the "null"
// scrub marker written by older versions. Invalid JSON cannot collide with enqueue output.
const FAILED_NULL_PAYLOAD_SENTINEL = "OPENCLAW_CHANNEL_INGRESS_FAILED_NULL_V1";

function normalizePart(value: string | undefined, fallback: string): string {
  const normalized = value?.trim();
  return normalized ? normalized : fallback;
}

// Keep inherited lookups for HOME/etc. without enumerating large Kubernetes service envs.
function createStateDirEnv(
  stateDir: string,
  baseEnv: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const env = Object.create(baseEnv) as NodeJS.ProcessEnv;
  env.OPENCLAW_STATE_DIR = stateDir;
  return env;
}

export function openChannelIngressDatabase(stateDir?: string) {
  return openOpenClawStateDatabase({
    env: stateDir ? createStateDirEnv(stateDir) : process.env,
  });
}

type ChannelIngressReadHandle = {
  db: DatabaseSync;
  release: () => void;
};

/**
 * Resolve a database handle for listing. Read-only callers get the non-creating opener
 * and own closing it; read-write callers keep the shared cached handle they already had.
 */
async function openChannelIngressDatabaseForListing(
  stateDir: string | undefined,
  access: "read-write" | "read-only",
): Promise<ChannelIngressReadHandle | undefined> {
  if (access !== "read-only") {
    return { db: openChannelIngressDatabase(stateDir).db, release: () => {} };
  }
  const env = stateDir ? createStateDirEnv(stateDir) : process.env;
  const database = await openExistingOpenClawStateDatabaseReadOnly({ env });
  if (!database) {
    return undefined;
  }
  return {
    db: database.db,
    release: () => {
      database.walMaintenance.close();
    },
  };
}

export function getChannelIngressKysely(db: DatabaseSync) {
  return getNodeSqliteKysely<ChannelIngressDatabase>(db);
}

function affectedRows(result: { numAffectedRows?: bigint }): number {
  return Number(result.numAffectedRows ?? 0n);
}

type ParseJsonResult = { ok: true; value: unknown } | { ok: false };

function parseJson(value: string): ParseJsonResult {
  try {
    return { ok: true, value: JSON.parse(value) };
  } catch {
    return { ok: false };
  }
}

function parseFailedPayload(value: string): ParseJsonResult {
  return value === FAILED_NULL_PAYLOAD_SENTINEL ? { ok: true, value: null } : parseJson(value);
}

function baseRecord<TPayload, TMetadata>(
  row: ChannelIngressRow,
): ChannelIngressQueueRecord<TPayload, TMetadata> | null {
  const payloadResult = parseJson(row.payload_json);
  if (!payloadResult.ok) {
    return null;
  }
  const metaResult = row.metadata_json === null ? null : parseJson(row.metadata_json);
  return {
    id: row.event_id,
    channelId: row.channel_id,
    accountId: row.account_id,
    queueName: row.queue_name,
    payload: payloadResult.value as TPayload,
    ...(metaResult === null || !metaResult.ok ? {} : { metadata: metaResult.value as TMetadata }),
    receivedAt: row.received_at,
    updatedAt: row.updated_at,
    ...(row.lane_key === null ? {} : { laneKey: row.lane_key }),
    attempts: row.attempts,
    ...(row.last_attempt_at === null ? {} : { lastAttemptAt: row.last_attempt_at }),
    ...(row.last_error === null ? {} : { lastError: row.last_error }),
  };
}

type ChannelIngressClaimColumns = { token: string; ownerId: string; claimedAt: number };

// A claimant writes token/owner/claimed_at in one UPDATE, and complete/release/
// refresh all match on claim_token. A claimed row missing any of the three has
// no reachable owner and could never be released; reject it instead of minting
// sentinel claim identity that release/liveness checks silently fail against.
function decodeClaimColumns(row: ChannelIngressRow): ChannelIngressClaimColumns | null {
  if (!row.claim_token || !row.claim_owner || row.claimed_at === null) {
    return null;
  }
  return { token: row.claim_token, ownerId: row.claim_owner, claimedAt: row.claimed_at };
}

function claimedRecord<TPayload, TMetadata>(
  row: ChannelIngressRow,
): ChannelIngressQueueClaim<TPayload, TMetadata> | null {
  const claim = decodeClaimColumns(row);
  const base = claim === null ? null : baseRecord<TPayload, TMetadata>(row);
  if (claim === null || base === null) {
    return null;
  }
  return { ...base, claim };
}

function corruptClaimRecord(
  row: ChannelIngressRow,
  claim: ChannelIngressClaimColumns,
): ChannelIngressQueueCorruptClaim {
  return {
    id: row.event_id,
    channelId: row.channel_id,
    accountId: row.account_id,
    queueName: row.queue_name,
    ...(row.lane_key === null ? {} : { laneKey: row.lane_key }),
    reason: "corrupt_payload",
    claim,
  };
}

function completedRecord<TCompletedMetadata>(
  row: ChannelIngressRow,
): ChannelIngressQueueCompletedRecord<TCompletedMetadata> {
  const metaResult =
    row.completed_metadata_json === null ? null : parseJson(row.completed_metadata_json);
  return {
    id: row.event_id,
    channelId: row.channel_id,
    accountId: row.account_id,
    queueName: row.queue_name,
    completedAt: row.completed_at ?? row.updated_at,
    ...(metaResult === null || !metaResult.ok
      ? {}
      : { metadata: metaResult.value as TCompletedMetadata }),
  };
}

function failedRecord<TPayload, TMetadata>(
  row: ChannelIngressRow,
): ChannelIngressQueueDeadLetterRecord<TPayload, TMetadata> {
  const payloadResult = parseFailedPayload(row.payload_json);
  const metadataResult = row.metadata_json === null ? null : parseJson(row.metadata_json);
  return {
    id: row.event_id,
    channelId: row.channel_id,
    accountId: row.account_id,
    queueName: row.queue_name,
    ...(payloadResult.ok && row.payload_json !== "null"
      ? { payload: payloadResult.value as TPayload }
      : {}),
    ...(metadataResult?.ok ? { metadata: metadataResult.value as TMetadata } : {}),
    receivedAt: row.received_at,
    updatedAt: row.updated_at,
    ...(row.lane_key === null ? {} : { laneKey: row.lane_key }),
    attempts: row.attempts,
    ...(row.last_attempt_at === null ? {} : { lastAttemptAt: row.last_attempt_at }),
    failedAt: row.failed_at ?? row.updated_at,
    reason: row.failed_reason ?? "failed",
    ...(row.last_error === null ? {} : { message: row.last_error }),
  };
}

function selectRow(db: DatabaseSync, queueName: string, id: string) {
  const kysely = getChannelIngressKysely(db);
  return executeSqliteQueryTakeFirstSync(
    db,
    kysely
      .selectFrom("channel_ingress_events")
      .selectAll()
      .where("queue_name", "=", queueName)
      .where("event_id", "=", id),
  );
}

function tombstoneCorruptRow(params: {
  db: DatabaseSync;
  row: ChannelIngressRow;
  expectedStatus: "pending" | "claimed";
  failedAt: number;
  staleCutoff?: number;
  reason: "corrupt_payload" | "corrupt_claim";
}): boolean {
  const kysely = getChannelIngressKysely(params.db);
  const baseUpdate = kysely
    .updateTable("channel_ingress_events")
    .set((eb) => ({
      status: "failed",
      failed_at: params.failedAt,
      failed_reason: params.reason,
      last_error: null,
      // A corrupt payload is unreadable — scrub it. A corrupt claim can wrap a
      // valid payload; keep it resubmittable (JSON null maps to the fail() sentinel).
      ...(params.reason === "corrupt_payload"
        ? { payload_json: "null", metadata_json: null }
        : {
            payload_json: eb
              .case()
              .when("payload_json", "=", "null")
              .then(FAILED_NULL_PAYLOAD_SENTINEL)
              .else(eb.ref("payload_json"))
              .end(),
          }),
      claim_token: null,
      claim_owner: null,
      claimed_at: null,
      updated_at: params.failedAt,
    }))
    .where("queue_name", "=", params.row.queue_name)
    .where("event_id", "=", params.row.event_id)
    .where("status", "=", params.expectedStatus);
  if (params.expectedStatus === "pending") {
    return affectedRows(executeSqliteQuerySync(params.db, baseUpdate)) > 0;
  }
  // The exact-token guard fences concurrent re-claims: claiming always writes a
  // fresh random token, so a matching (or still-NULL) token proves the row is
  // unchanged since it was read. Malformed-claim tombstones rely on this guard
  // alone and pass no staleCutoff — their claimed_at can be NULL or corrupt.
  const claimGuardedUpdate =
    params.row.claim_token === null
      ? baseUpdate.where("claim_token", "is", null)
      : baseUpdate.where("claim_token", "=", params.row.claim_token);
  const staleGuardedUpdate =
    params.staleCutoff === undefined
      ? claimGuardedUpdate
      : claimGuardedUpdate.where("claimed_at", "<=", params.staleCutoff);
  return affectedRows(executeSqliteQuerySync(params.db, staleGuardedUpdate)) > 0;
}

function idFrom(idOrRecord: string | { id: string }): string {
  const id = normalizePart(typeof idOrRecord === "string" ? idOrRecord : idOrRecord.id, "");
  if (!id) {
    throw new Error("Channel ingress event id cannot be empty");
  }
  return id;
}

function claimTokenFrom(
  idOrClaim: string | { id: string; claim?: { token: string } },
): string | null {
  return typeof idOrClaim === "string" ? null : (idOrClaim.claim?.token ?? null);
}

function ownClaimField(value: unknown, key: string): unknown {
  if (value === null || typeof value !== "object" || types.isProxy(value)) {
    return undefined;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return undefined;
  }
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor && "value" in descriptor ? descriptor.value : undefined;
}

function rowToEnqueueResult<TPayload, TMetadata, TCompletedMetadata>(
  row: ChannelIngressRow,
): ChannelIngressQueueEnqueueResult<TPayload, TMetadata, TCompletedMetadata> | null {
  if (row.status === "completed") {
    return { kind: "completed", duplicate: true, record: completedRecord(row) };
  }
  if (row.status === "failed") {
    return {
      kind: "failed",
      duplicate: true,
      record: failedRecord<TPayload, TMetadata>(row),
    };
  }
  if (row.status === "claimed") {
    const rec = claimedRecord<TPayload, TMetadata>(row);
    return rec ? { kind: "claimed", duplicate: true, record: rec } : null;
  }
  const rec = baseRecord<TPayload, TMetadata>(row);
  return rec ? { kind: "pending", duplicate: true, record: rec } : null;
}

function normalizeLimit(limit: number | "all" | undefined): number {
  return limit === "all" ? Number.MAX_SAFE_INTEGER : Math.max(1, Math.floor(limit ?? 100));
}

function normalizeScanLimit(limit: number | undefined): number {
  return Math.max(1, Math.floor(limit ?? 100));
}

// Materialize pending rows in bounded chunks because SQLite's json_valid()
// rejects some payloads accepted by the queue's JSON.stringify/JSON.parse contract.
const LIST_PENDING_BATCH_SIZE = 100;
// Keep repair work bounded under one SQLite write lock; later calls continue
// from the durable failed tombstones left by this call.
const MAX_CORRUPT_RECONCILIATIONS_PER_CLAIM = 100;

function normalizeMaxEntries(value: number | undefined): number | null {
  return value === undefined ? null : Math.max(0, Math.floor(value));
}

function normalizedProtectedIds(ids: Iterable<string> | undefined): string[] {
  return [...(ids ?? [])].map((id) => id.trim()).filter(Boolean);
}

function normalizedCandidateIds(ids: Iterable<string> | undefined): string[] | undefined {
  return ids === undefined ? undefined : [...ids].map((id) => id.trim()).filter(Boolean);
}

function queueNameForParts(channelId: string, accountId: string): string {
  // JSON tuple encoding keeps channel/account scopes unambiguous even when ids contain separators.
  return JSON.stringify([channelId, accountId]);
}

/** Lists account ids that hold any ingress rows for a channel, so doctor
 *  migrations can sweep durable state whose account is gone from config. */
export function listChannelIngressQueueAccountIds(params: {
  channelId: string;
  stateDir?: string;
}): string[] {
  const channelId = normalizePart(params.channelId, "unknown");
  const database = openChannelIngressDatabase(params.stateDir);
  const rows = executeSqliteQuerySync(
    database.db,
    getChannelIngressKysely(database.db)
      .selectFrom("channel_ingress_events")
      .select("account_id")
      .distinct()
      .where("channel_id", "=", channelId)
      .orderBy("account_id", "asc"),
  ).rows;
  return rows.map((row) => row.account_id);
}

/**
 * Account discovery for callers that must not touch durable state yet. Uses the
 * non-creating read-only opener, so an absent store yields no accounts instead of
 * being created and migrated by the lookup itself.
 */
export async function listChannelIngressQueueAccountIdsReadOnly(params: {
  channelId: string;
  stateDir?: string;
}): Promise<string[]> {
  const channelId = normalizePart(params.channelId, "unknown");
  const handle = await openChannelIngressDatabaseForListing(params.stateDir, "read-only");
  if (!handle) {
    return [];
  }
  try {
    return executeSqliteQuerySync(
      handle.db,
      getChannelIngressKysely(handle.db)
        .selectFrom("channel_ingress_events")
        .select("account_id")
        .distinct()
        .where("channel_id", "=", channelId)
        .orderBy("account_id", "asc"),
    ).rows.map((row) => row.account_id);
  } finally {
    handle.release();
  }
}

/** Creates a durable channel/account-scoped ingress queue backed by the OpenClaw state database. */
export function createChannelIngressQueue<
  TPayload,
  TMetadata = unknown,
  TCompletedMetadata = unknown,
>(
  options: CreateChannelIngressQueueOptions,
): ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata> {
  const channelId = normalizePart(options.channelId, "unknown");
  const accountId = normalizePart(options.accountId, "default");
  const queueName = queueNameForParts(channelId, accountId);
  const now = options.now ?? Date.now;
  const access = options.access ?? "read-write";

  const prepareClaimIdentityReader = async (): Promise<ChannelIngressQueueClaimIdentityReader> => {
    const pathname = resolveOpenClawStateSqlitePath(
      options.stateDir ? createStateDirEnv(options.stateDir) : process.env,
    );
    const borrow = borrowOpenClawStateDatabaseForAsyncRead(pathname);
    let closed = borrow === undefined;
    let released = false;
    const dispose = () => {
      closed = true;
      if (!released) {
        released = true;
        borrow?.release();
      }
    };
    if (!borrow) {
      return { read: () => null, dispose };
    }
    try {
      const { database } = borrow;
      const admission = captureOpenClawStateDatabaseReadAdmission(pathname);
      const identity = requireOpenClawStateDatabaseIdentity(database);
      const assertCurrent = () => {
        borrow.assertCurrent();
        admission.assertCurrent();
        if (
          openClawStateDatabaseCache.getOpenClawStateDatabaseIfOpenAtPath(pathname) !== database
        ) {
          throw new Error("Claim identity reader lost its canonical native owner");
        }
        assertExistingDatabaseIdentity(pathname, identity.key);
        if (realpathSync.native(pathname) !== identity.canonicalPath || database.db.isTransaction) {
          throw new Error("Claim identity reader lost its committed native owner");
        }
      };
      assertCurrent();
      return {
        read(ref) {
          if (closed) {
            return null;
          }
          try {
            const id = ownClaimField(ref, "id");
            const token = ownClaimField(ownClaimField(ref, "claim"), "token");
            if (typeof id !== "string" || !id || typeof token !== "string" || !token) {
              return null;
            }
            assertCurrent();
            const row = executeSqliteQueryTakeFirstSync(
              database.db,
              getChannelIngressKysely(database.db)
                .selectFrom("channel_ingress_events")
                .select(["event_id", "claim_token", "claim_owner", "claimed_at"])
                .where("queue_name", "=", queueName)
                .where("event_id", "=", id)
                .where("status", "=", "claimed")
                .where("claim_token", "=", token),
            );
            assertCurrent();
            if (!row) {
              return null;
            }
            if (
              row.event_id !== id ||
              row.claim_token !== token ||
              typeof row.claim_owner !== "string" ||
              !row.claim_owner ||
              typeof row.claimed_at !== "number" ||
              !Number.isSafeInteger(row.claimed_at) ||
              row.claimed_at < 0
            ) {
              closed = true;
              return null;
            }
            return Object.freeze({
              id: row.event_id,
              token: row.claim_token,
              ownerId: row.claim_owner,
              claimedAt: row.claimed_at,
            });
          } catch {
            closed = true;
            return null;
          }
        },
        dispose,
      };
    } catch (error) {
      dispose();
      throw error;
    }
  };

  const enqueue: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["enqueue"] = async (
    id,
    payload,
    enqueueOptions,
  ) => {
    const eventId = normalizePart(id, "");
    if (!eventId) {
      throw new Error("Channel ingress event id cannot be empty");
    }
    const receivedAt = enqueueOptions?.receivedAt ?? now();
    const updatedAt = now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const insert = executeSqliteQuerySync(
          tx.db,
          kysely
            .insertInto("channel_ingress_events")
            .values({
              queue_name: queueName,
              event_id: eventId,
              channel_id: channelId,
              account_id: accountId,
              status: "pending",
              lane_key: enqueueOptions?.laneKey ?? null,
              payload_json: JSON.stringify(payload),
              metadata_json:
                enqueueOptions?.metadata === undefined
                  ? null
                  : JSON.stringify(enqueueOptions.metadata),
              received_at: receivedAt,
              updated_at: updatedAt,
              attempts: 0,
            })
            .onConflict((conflict) => conflict.columns(["queue_name", "event_id"]).doNothing()),
        );
        const row = selectRow(tx.db, queueName, eventId);
        if (!row) {
          throw new Error(`Failed to read channel ingress event ${queueName}/${eventId}`);
        }
        if (affectedRows(insert) > 0) {
          const fresh = baseRecord<TPayload, TMetadata>(row);
          if (fresh === null) {
            throw new Error(
              `Corrupt payload_json in channel ingress event ${queueName}/${eventId}`,
            );
          }
          return {
            kind: "accepted",
            duplicate: false,
            record: fresh,
          };
        }
        const dup = rowToEnqueueResult<TPayload, TMetadata, TCompletedMetadata>(row);
        if (dup === null) {
          // A live claimant may already be producing external side effects.
          // Duplicate enqueue cannot prove ownership is stale, so leave claimed
          // corruption for the ownership-aware recovery path.
          if (row.status === "claimed") {
            throw new Error(`Corrupt claimed channel ingress event ${queueName}/${eventId}`);
          }
          if (
            !tombstoneCorruptRow({
              db: tx.db,
              row,
              expectedStatus: "pending",
              failedAt: updatedAt,
              reason: "corrupt_payload",
            })
          ) {
            throw new Error(`Failed to tombstone corrupt ingress event ${queueName}/${eventId}`);
          }
          const failedRow = selectRow(tx.db, queueName, eventId);
          if (!failedRow) {
            throw new Error(`Failed to read corrupt ingress tombstone ${queueName}/${eventId}`);
          }
          return {
            kind: "failed",
            duplicate: true,
            record: failedRecord<TPayload, TMetadata>(failedRow),
          };
        }
        return dup;
      },
      { path: database.path },
    );
  };

  const listPending: ChannelIngressQueue<
    TPayload,
    TMetadata,
    TCompletedMetadata
  >["listPending"] = async (listOptions) => {
    const handle = await openChannelIngressDatabaseForListing(options.stateDir, access);
    if (!handle) {
      return [];
    }
    const { db } = handle;
    try {
      const kysely = getChannelIngressKysely(db);
      const limit = normalizeLimit(listOptions?.limit);
      const records: Array<ChannelIngressQueueRecord<TPayload, TMetadata>> = [];
      let lastRow: ChannelIngressRow | undefined;
      while (records.length < limit) {
        let pageQuery = kysely
          .selectFrom("channel_ingress_events")
          .selectAll()
          .where("queue_name", "=", queueName)
          .where("status", "=", "pending");
        if (lastRow) {
          const cursor = lastRow;
          pageQuery =
            listOptions?.orderBy === "id"
              ? pageQuery.where("event_id", ">", cursor.event_id)
              : pageQuery.where((eb) =>
                  eb.or([
                    eb("received_at", ">", cursor.received_at),
                    eb.and([
                      eb("received_at", "=", cursor.received_at),
                      eb("event_id", ">", cursor.event_id),
                    ]),
                  ]),
                );
        }
        const orderedQuery =
          listOptions?.orderBy === "id"
            ? pageQuery.orderBy("event_id", "asc")
            : pageQuery.orderBy("received_at", "asc").orderBy("event_id", "asc");
        const rows = executeSqliteQuerySync(db, orderedQuery.limit(LIST_PENDING_BATCH_SIZE)).rows;
        for (const row of rows) {
          const record = baseRecord<TPayload, TMetadata>(row);
          if (record) {
            records.push(record);
            if (records.length === limit) {
              break;
            }
          }
        }
        if (rows.length < LIST_PENDING_BATCH_SIZE) {
          break;
        }
        lastRow = rows.at(-1);
      }
      return records;
    } finally {
      handle.release();
    }
  };

  const listClaims: ChannelIngressQueue<
    TPayload,
    TMetadata,
    TCompletedMetadata
  >["listClaims"] = async () => {
    const handle = await openChannelIngressDatabaseForListing(options.stateDir, access);
    if (!handle) {
      return [];
    }
    const { db } = handle;
    try {
      const kysely = getChannelIngressKysely(db);
      const rows = executeSqliteQuerySync(
        db,
        kysely
          .selectFrom("channel_ingress_events")
          .selectAll()
          .where("queue_name", "=", queueName)
          .where("status", "=", "claimed")
          .orderBy("claimed_at", "asc")
          .orderBy("received_at", "asc")
          .orderBy("event_id", "asc"),
      ).rows;
      return rows
        .map((row) => claimedRecord<TPayload, TMetadata>(row))
        .filter((rec): rec is ChannelIngressQueueClaim<TPayload, TMetadata> => rec !== null);
    } finally {
      handle.release();
    }
  };

  const listFailed: NonNullable<
    ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["listFailed"]
  > = async (listOptions) => {
    const handle = await openChannelIngressDatabaseForListing(options.stateDir, access);
    if (!handle) {
      return [];
    }
    const { db } = handle;
    try {
      const rows = executeSqliteQuerySync(
        db,
        getChannelIngressKysely(db)
          .selectFrom("channel_ingress_events")
          .selectAll()
          .where("queue_name", "=", queueName)
          .where("status", "=", "failed")
          .orderBy("failed_at", "asc")
          .orderBy("event_id", "asc")
          .limit(normalizeLimit(listOptions?.limit)),
      ).rows;
      return rows.map((row) => failedRecord<TPayload, TMetadata>(row));
    } finally {
      handle.release();
    }
  };

  const claimNext: ChannelIngressQueue<
    TPayload,
    TMetadata,
    TCompletedMetadata
  >["claimNext"] = async (claimOptions) => {
    if (claimOptions?.staleMs !== undefined) {
      await recoverStaleClaims({ staleMs: claimOptions.staleMs });
    }
    const blocked = new Set(
      [...(claimOptions?.blockedLaneKeys ?? [])].map((key) => key.trim()).filter(Boolean),
    );
    const candidateIds = normalizedCandidateIds(claimOptions?.candidateIds);
    if (candidateIds?.length === 0) {
      return null;
    }
    const resolveClaimLaneKey = (
      record: ChannelIngressQueueRecord<TPayload, TMetadata>,
    ): string | undefined => {
      const storedLaneKey = record.laneKey;
      if (storedLaneKey === undefined) {
        return claimOptions?.deriveLaneKey?.(record);
      }
      if (!claimOptions?.deriveLaneKey || !claimOptions.reconcileStoredLaneKey) {
        return storedLaneKey;
      }
      const derivedLaneKey = claimOptions.deriveLaneKey(record);
      if (!derivedLaneKey || derivedLaneKey === storedLaneKey) {
        return storedLaneKey;
      }
      // Durable identity changes need their channel owner's explicit approval;
      // unrelated derivations can intentionally be ephemeral claim lanes.
      return claimOptions.reconcileStoredLaneKey(record, storedLaneKey, derivedLaneKey)
        ? derivedLaneKey
        : storedLaneKey;
    };
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        let effectiveBlocked = blocked;
        if (candidateIds && candidateIds.length > 0) {
          // Candidate snapshots can race a sibling drainer. If an earlier
          // candidate is now claimed, its lane must block later same-lane rows.
          const claimedCandidateRows = executeSqliteQuerySync(
            tx.db,
            kysely
              .selectFrom("channel_ingress_events")
              .selectAll()
              .where("queue_name", "=", queueName)
              .where("status", "=", "claimed")
              .where("event_id", "in", candidateIds),
          ).rows;
          const claimedCandidateLaneKeys = claimedCandidateRows
            .map((row) => {
              if (row.lane_key && !claimOptions?.reconcileStoredLaneKey) {
                return row.lane_key;
              }
              const rec = baseRecord<TPayload, TMetadata>(row);
              return rec ? resolveClaimLaneKey(rec) : (row.lane_key ?? undefined);
            })
            .filter((laneKey): laneKey is string => Boolean(laneKey));
          if (claimedCandidateLaneKeys.length > 0) {
            effectiveBlocked = new Set([...blocked, ...claimedCandidateLaneKeys]);
          }
        }
        const baseSelect = kysely
          .selectFrom("channel_ingress_events")
          .selectAll()
          .where("queue_name", "=", queueName)
          .where("status", "=", "pending");
        let select = baseSelect;
        if (candidateIds) {
          select = select.where("event_id", "in", candidateIds);
        }
        if (effectiveBlocked.size > 0 && !claimOptions?.deriveLaneKey) {
          select = select.where((eb) =>
            eb.or([eb("lane_key", "is", null), eb("lane_key", "not in", [...effectiveBlocked])]),
          );
        }
        let orderedSelect =
          claimOptions?.orderBy === "id"
            ? select.orderBy("event_id", "asc")
            : select.orderBy("received_at", "asc").orderBy("event_id", "asc");
        orderedSelect = orderedSelect.limit(normalizeScanLimit(claimOptions?.scanLimit));
        const transitionAt = now();
        let corruptReconciliations = 0;
        let selected:
          | { row: ChannelIngressRow; record: ChannelIngressQueueRecord<TPayload, TMetadata> }
          | undefined;
        while (!selected) {
          const rows = executeSqliteQuerySync(tx.db, orderedSelect).rows;
          let tombstonedCorruptRow = false;
          for (const row of rows) {
            const rec = baseRecord<TPayload, TMetadata>(row);
            if (rec === null) {
              if (corruptReconciliations >= MAX_CORRUPT_RECONCILIATIONS_PER_CLAIM) {
                continue;
              }
              const didTombstone = tombstoneCorruptRow({
                db: tx.db,
                row,
                expectedStatus: "pending",
                failedAt: transitionAt,
                reason: "corrupt_payload",
              });
              tombstonedCorruptRow = didTombstone || tombstonedCorruptRow;
              if (didTombstone) {
                corruptReconciliations += 1;
              }
              continue;
            }
            const laneKey = resolveClaimLaneKey(rec);
            if (!laneKey || !effectiveBlocked.has(laneKey)) {
              selected = { row, record: rec };
              break;
            }
          }
          if (
            selected ||
            !tombstonedCorruptRow ||
            corruptReconciliations >= MAX_CORRUPT_RECONCILIATIONS_PER_CLAIM
          ) {
            break;
          }
        }
        if (!selected) {
          return null;
        }
        const derivedLaneKey = resolveClaimLaneKey(selected.record);
        const token = randomUUID();
        const ownerId = normalizePart(claimOptions?.ownerId, `${process.pid}`);
        const result = executeSqliteQuerySync(
          tx.db,
          kysely
            .updateTable("channel_ingress_events")
            .set({
              status: "claimed",
              claim_token: token,
              claim_owner: ownerId,
              claimed_at: transitionAt,
              ...(derivedLaneKey ? { lane_key: derivedLaneKey } : {}),
              updated_at: transitionAt,
            })
            .where("queue_name", "=", queueName)
            .where("event_id", "=", selected.row.event_id)
            .where("status", "=", "pending"),
        );
        if (affectedRows(result) === 0) {
          return null;
        }
        const row = selectRow(tx.db, queueName, selected.row.event_id);
        return row ? claimedRecord<TPayload, TMetadata>(row) : null;
      },
      { path: database.path },
    );
  };

  const claim: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["claim"] = async (
    id,
    claimOptions,
  ) => {
    const eventId = normalizePart(id, "");
    if (!eventId) {
      throw new Error("Channel ingress event id cannot be empty");
    }
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const transitionAt = now();
        const pendingRow = selectRow(tx.db, queueName, eventId);
        if (!pendingRow || pendingRow.status !== "pending") {
          return null;
        }
        if (baseRecord<TPayload, TMetadata>(pendingRow) === null) {
          tombstoneCorruptRow({
            db: tx.db,
            row: pendingRow,
            expectedStatus: "pending",
            failedAt: transitionAt,
            reason: "corrupt_payload",
          });
          return null;
        }
        const token = randomUUID();
        const ownerId = normalizePart(claimOptions?.ownerId, `${process.pid}`);
        const result = executeSqliteQuerySync(
          tx.db,
          kysely
            .updateTable("channel_ingress_events")
            .set({
              status: "claimed",
              claim_token: token,
              claim_owner: ownerId,
              claimed_at: transitionAt,
              updated_at: transitionAt,
            })
            .where("queue_name", "=", queueName)
            .where("event_id", "=", eventId)
            .where("status", "=", "pending"),
        );
        if (affectedRows(result) === 0) {
          return null;
        }
        const row = selectRow(tx.db, queueName, eventId);
        return row ? claimedRecord<TPayload, TMetadata>(row) : null;
      },
      { path: database.path },
    );
  };

  const refreshClaim: NonNullable<
    ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["refreshClaim"]
  > = async (claimRef, refreshOptions) => {
    const eventId = idFrom(claimRef);
    const refreshedAt = refreshOptions?.refreshedAt ?? now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const result = executeSqliteQuerySync(
          tx.db,
          kysely
            .updateTable("channel_ingress_events")
            .set({
              claimed_at: refreshedAt,
              updated_at: refreshedAt,
            })
            .where("queue_name", "=", queueName)
            .where("event_id", "=", eventId)
            .where("status", "=", "claimed")
            .where("claim_token", "=", claimRef.claim.token),
        );
        return affectedRows(result) > 0;
      },
      { path: database.path },
    );
  };

  const releaseClaimIfStillStale = async (
    claimRef: ChannelIngressQueueClaimRef,
    releaseOptions: { cutoff: number; releasedAt: number },
  ): Promise<boolean> => {
    const eventId = idFrom(claimRef);
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const result = executeSqliteQuerySync(
          tx.db,
          kysely
            .updateTable("channel_ingress_events")
            .set((eb) => ({
              status: "pending",
              claim_token: null,
              claim_owner: null,
              claimed_at: null,
              attempts: eb("attempts", "+", 1),
              last_attempt_at: releaseOptions.releasedAt,
              updated_at: releaseOptions.releasedAt,
            }))
            .where("queue_name", "=", queueName)
            .where("event_id", "=", eventId)
            .where("status", "=", "claimed")
            .where("claim_token", "=", claimRef.claim.token)
            .where("claimed_at", "<=", releaseOptions.cutoff),
        );
        return affectedRows(result) > 0;
      },
      { path: database.path },
    );
  };

  const recoverStaleClaims: ChannelIngressQueue<
    TPayload,
    TMetadata,
    TCompletedMetadata
  >["recoverStaleClaims"] = async (recoverOptions) => {
    const current = recoverOptions?.now ?? now();
    const staleMs = Math.max(0, Math.floor(recoverOptions?.staleMs ?? 0));
    const cutoff = current - staleMs;
    const database = openChannelIngressDatabase(options.stateDir);
    const claimedRows = executeSqliteQuerySync(
      database.db,
      getChannelIngressKysely(database.db)
        .selectFrom("channel_ingress_events")
        .selectAll()
        .where("queue_name", "=", queueName)
        .where("status", "=", "claimed")
        // A claimed row missing any claim column has no live owner (see
        // decodeClaimColumns); scan it regardless of claimed_at, since a NULL
        // or corrupt future timestamp would dodge every cutoff comparison.
        .where((eb) =>
          eb.or([
            eb("claimed_at", "<=", cutoff),
            eb("claimed_at", "is", null),
            eb("claim_token", "is", null),
            eb("claim_owner", "is", null),
            eb("claim_token", "=", ""),
            eb("claim_owner", "=", ""),
          ]),
        ),
    ).rows;
    let recovered = 0;
    for (const row of claimedRows) {
      const claimColumns = decodeClaimColumns(row);
      const claimRec = claimColumns === null ? null : claimedRecord<TPayload, TMetadata>(row);
      if (claimRec === null) {
        if (claimColumns !== null) {
          const shouldRecoverCorrupt = recoverOptions?.shouldRecoverCorrupt;
          if (shouldRecoverCorrupt) {
            if (!(await shouldRecoverCorrupt(corruptClaimRecord(row, claimColumns)))) {
              continue;
            }
          } else if (recoverOptions?.shouldRecover) {
            // Existing payload-aware policies cannot safely decide on corrupt
            // data. Preserve ownership unless the caller opts into the raw claim
            // identity contract above.
            continue;
          }
        }
        // claimColumns === null: no reachable owner can exist, so no policy
        // consult — tombstone unconditionally to keep the queue recoverable.
        const tombstoned = runOpenClawStateWriteTransaction(
          (tx) =>
            tombstoneCorruptRow({
              db: tx.db,
              row,
              expectedStatus: "claimed",
              failedAt: current,
              // Malformed claims skip the stale guard: their claimed_at may be
              // NULL or a corrupt future value; the exact-token guard fences.
              ...(claimColumns === null ? {} : { staleCutoff: cutoff }),
              reason: claimColumns === null ? "corrupt_claim" : "corrupt_payload",
            }),
          { path: database.path },
        );
        if (tombstoned) {
          recovered += 1;
        }
        continue;
      }
      if (recoverOptions?.shouldRecover && !(await recoverOptions.shouldRecover(claimRec))) {
        continue;
      }
      if (await releaseClaimIfStillStale(claimRec, { cutoff, releasedAt: current })) {
        recovered += 1;
      }
    }
    return recovered;
  };

  const complete: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["complete"] = async (
    idOrClaim,
    completeOptions,
  ) => {
    const eventId = idFrom(idOrClaim);
    const token = claimTokenFrom(idOrClaim);
    const completedAt = completeOptions?.completedAt ?? now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const baseUpdate = kysely
          .updateTable("channel_ingress_events")
          .set({
            status: "completed",
            completed_at: completedAt,
            completed_metadata_json:
              completeOptions?.metadata === undefined
                ? null
                : JSON.stringify(completeOptions.metadata),
            payload_json: "null",
            metadata_json: null,
            claim_token: null,
            claim_owner: null,
            claimed_at: null,
            last_attempt_at: null,
            last_error: null,
            updated_at: completedAt,
          })
          .where("queue_name", "=", queueName)
          .where("event_id", "=", eventId);
        const update =
          token === null
            ? baseUpdate.where("status", "=", "pending")
            : baseUpdate.where("status", "=", "claimed").where("claim_token", "=", token);
        const result = executeSqliteQuerySync(tx.db, update);
        if (affectedRows(result) > 0) {
          return true;
        }
        if (token !== null) {
          return false;
        }
        const insert = executeSqliteQuerySync(
          tx.db,
          kysely
            .insertInto("channel_ingress_events")
            .values({
              queue_name: queueName,
              event_id: eventId,
              channel_id: channelId,
              account_id: accountId,
              status: "completed",
              lane_key: null,
              payload_json: "null",
              metadata_json: null,
              received_at: completedAt,
              updated_at: completedAt,
              attempts: 0,
              completed_at: completedAt,
              completed_metadata_json:
                completeOptions?.metadata === undefined
                  ? null
                  : JSON.stringify(completeOptions.metadata),
            })
            .onConflict((conflict) => conflict.columns(["queue_name", "event_id"]).doNothing()),
        );
        return affectedRows(insert) > 0;
      },
      { path: database.path },
    );
  };

  const release: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["release"] = async (
    idOrClaim,
    releaseOptions,
  ) => {
    const eventId = idFrom(idOrClaim);
    const token = claimTokenFrom(idOrClaim);
    const releasedAt = releaseOptions?.releasedAt ?? now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const baseUpdate = kysely
          .updateTable("channel_ingress_events")
          .set((eb) => ({
            status: "pending",
            claim_token: null,
            claim_owner: null,
            claimed_at: null,
            // A claim can lose its owner before processing starts. Returning it
            // must not consume retry budget or erase the previous real failure.
            ...(releaseOptions?.recordAttempt === false
              ? {}
              : {
                  attempts: eb("attempts", "+", 1),
                  last_attempt_at: releasedAt,
                }),
            ...(releaseOptions?.lastError === undefined
              ? {}
              : { last_error: releaseOptions.lastError }),
            updated_at: releasedAt,
          }))
          .where("queue_name", "=", queueName)
          .where("event_id", "=", eventId);
        const update =
          token === null
            ? baseUpdate.where("status", "=", "pending")
            : baseUpdate.where("status", "=", "claimed").where("claim_token", "=", token);
        return affectedRows(executeSqliteQuerySync(tx.db, update)) > 0;
      },
      { path: database.path },
    );
  };

  const fail: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["fail"] = async (
    idOrClaim,
    failOptions,
  ) => {
    const eventId = idFrom(idOrClaim);
    const token = claimTokenFrom(idOrClaim);
    const failedAt = failOptions.failedAt ?? now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const baseUpdate = kysely
          .updateTable("channel_ingress_events")
          .set((eb) => ({
            status: "failed",
            failed_at: failedAt,
            failed_reason: failOptions.reason,
            last_error: failOptions.message ?? null,
            payload_json: eb
              .case()
              .when("payload_json", "=", "null")
              .then(FAILED_NULL_PAYLOAD_SENTINEL)
              .else(eb.ref("payload_json"))
              .end(),
            claim_token: null,
            claim_owner: null,
            claimed_at: null,
            updated_at: failedAt,
          }))
          .where("queue_name", "=", queueName)
          .where("event_id", "=", eventId);
        const update =
          token === null
            ? baseUpdate.where("status", "=", "pending")
            : baseUpdate.where("status", "=", "claimed").where("claim_token", "=", token);
        return affectedRows(executeSqliteQuerySync(tx.db, update)) > 0;
      },
      { path: database.path },
    );
  };

  const resubmit: NonNullable<
    ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["resubmit"]
  > = async (id, resubmitOptions) => {
    const eventId = idFrom(id);
    const resubmittedAt = resubmitOptions?.resubmittedAt ?? now();
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const row = selectRow(tx.db, queueName, eventId);
        if (!row) {
          return { kind: "not-found" };
        }
        if (row.status === "completed") {
          return { kind: "completed", record: completedRecord<TCompletedMetadata>(row) };
        }
        if (row.status !== "failed") {
          return {
            kind: "active",
            status: row.status === "claimed" ? "claimed" : "pending",
          };
        }
        const previous = failedRecord<TPayload, TMetadata>(row);
        // Pre-retention tombstones and corrupt-payload failures stored JSON null.
        // Refuse them rather than enqueueing an event with invented payload data.
        if (row.payload_json === "null" || !parseFailedPayload(row.payload_json).ok) {
          return { kind: "unrecoverable", record: previous };
        }
        const result = executeSqliteQuerySync(
          tx.db,
          getChannelIngressKysely(tx.db)
            .updateTable("channel_ingress_events")
            .set({
              status: "pending",
              payload_json:
                row.payload_json === FAILED_NULL_PAYLOAD_SENTINEL ? "null" : row.payload_json,
              received_at: resubmittedAt,
              updated_at: resubmittedAt,
              attempts: 0,
              last_attempt_at: null,
              last_error: null,
              failed_at: null,
              failed_reason: null,
              claim_token: null,
              claim_owner: null,
              claimed_at: null,
              completed_at: null,
              completed_metadata_json: null,
            })
            .where("queue_name", "=", queueName)
            .where("event_id", "=", eventId)
            .where("status", "=", "failed"),
        );
        if (affectedRows(result) === 0) {
          return { kind: "active", status: "pending" };
        }
        const updated = selectRow(tx.db, queueName, eventId);
        const record = updated ? baseRecord<TPayload, TMetadata>(updated) : null;
        if (!record) {
          throw new Error(
            `Failed to read resubmitted channel ingress event ${queueName}/${eventId}`,
          );
        }
        return { kind: "resubmitted", record, previous };
      },
      { path: database.path },
    );
  };

  const deleteEntry: ChannelIngressQueue<
    TPayload,
    TMetadata,
    TCompletedMetadata
  >["delete"] = async (idOrRecord) => {
    const eventId = idFrom(idOrRecord);
    const token = claimTokenFrom(idOrRecord);
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        const baseDelete = kysely
          .deleteFrom("channel_ingress_events")
          .where("queue_name", "=", queueName)
          .where("event_id", "=", eventId);
        const deleteQuery =
          token === null
            ? baseDelete.where("status", "=", "pending")
            : baseDelete.where("status", "=", "claimed").where("claim_token", "=", token);
        return affectedRows(executeSqliteQuerySync(tx.db, deleteQuery)) > 0;
      },
      { path: database.path },
    );
  };

  const prune: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>["prune"] = async (
    pruneOptions,
  ) => {
    const current = pruneOptions?.now ?? now();
    const pendingCutoff =
      pruneOptions?.pendingTtlMs === undefined ? null : current - pruneOptions.pendingTtlMs;
    const completedCutoff =
      pruneOptions?.completedTtlMs === undefined ? null : current - pruneOptions.completedTtlMs;
    const failedCutoff =
      pruneOptions?.failedTtlMs === undefined ? null : current - pruneOptions.failedTtlMs;
    const pendingMaxEntries = normalizeMaxEntries(pruneOptions?.pendingMaxEntries);
    const completedMaxEntries = normalizeMaxEntries(pruneOptions?.completedMaxEntries);
    const failedMaxEntries = normalizeMaxEntries(pruneOptions?.failedMaxEntries);
    const protectIds = normalizedProtectedIds(pruneOptions?.protectIds);
    if (
      pendingCutoff === null &&
      completedCutoff === null &&
      failedCutoff === null &&
      pendingMaxEntries === null &&
      completedMaxEntries === null &&
      failedMaxEntries === null
    ) {
      return 0;
    }
    const database = openChannelIngressDatabase(options.stateDir);
    return runOpenClawStateWriteTransaction(
      (tx) => {
        const kysely = getChannelIngressKysely(tx.db);
        let deleted = 0;
        if (pendingCutoff !== null) {
          let deleteQuery = kysely
            .deleteFrom("channel_ingress_events")
            .where("queue_name", "=", queueName)
            .where("status", "=", "pending")
            .where("updated_at", "<", pendingCutoff);
          if (protectIds.length > 0) {
            deleteQuery = deleteQuery.where("event_id", "not in", protectIds);
          }
          deleted += affectedRows(executeSqliteQuerySync(tx.db, deleteQuery));
        }
        if (completedCutoff !== null) {
          let deleteQuery = kysely
            .deleteFrom("channel_ingress_events")
            .where("queue_name", "=", queueName)
            .where("status", "=", "completed")
            .where("completed_at", "<", completedCutoff);
          if (protectIds.length > 0) {
            deleteQuery = deleteQuery.where("event_id", "not in", protectIds);
          }
          deleted += affectedRows(executeSqliteQuerySync(tx.db, deleteQuery));
        }
        if (failedCutoff !== null) {
          let deleteQuery = kysely
            .deleteFrom("channel_ingress_events")
            .where("queue_name", "=", queueName)
            .where("status", "=", "failed")
            .where("failed_at", "<", failedCutoff);
          if (protectIds.length > 0) {
            deleteQuery = deleteQuery.where("event_id", "not in", protectIds);
          }
          deleted += affectedRows(executeSqliteQuerySync(tx.db, deleteQuery));
        }
        const pruneMaxEntries = (status: string, maxEntries: number | null) => {
          if (maxEntries === null) {
            return;
          }
          const batchSize = 500;
          const protectedSet = new Set(protectIds);
          // Page before filtering protected IDs; they still occupy their retention slots.
          while (true) {
            const rowsToDelete = executeSqliteQuerySync(
              tx.db,
              kysely
                .selectFrom("channel_ingress_events")
                .select("event_id")
                .where("queue_name", "=", queueName)
                .where("status", "=", status)
                .orderBy("updated_at", "desc")
                .orderBy("event_id", "desc")
                .limit(batchSize)
                .offset(maxEntries),
            ).rows;
            const ids = rowsToDelete
              .map((row) => row.event_id)
              .filter((id) => !protectedSet.has(id));
            if (ids.length === 0) {
              return;
            }
            deleted += affectedRows(
              executeSqliteQuerySync(
                tx.db,
                kysely
                  .deleteFrom("channel_ingress_events")
                  .where("queue_name", "=", queueName)
                  .where("status", "=", status)
                  .where("event_id", "in", ids),
              ),
            );
          }
        };
        pruneMaxEntries("pending", pendingMaxEntries);
        pruneMaxEntries("completed", completedMaxEntries);
        pruneMaxEntries("failed", failedMaxEntries);
        return deleted;
      },
      { path: database.path },
    );
  };

  const queue: ChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata> = {
    enqueue,
    listPending,
    listClaims,
    prepareClaimIdentityReader,
    listFailed,
    claimNext,
    claim,
    refreshClaim,
    complete,
    release,
    fail,
    resubmit,
    delete: deleteEntry,
    recoverStaleClaims,
    prune,
  };
  if (channelId === "sms") {
    const pathname = resolveOpenClawStateSqlitePath(
      options.stateDir ? createStateDirEnv(options.stateDir) : process.env,
    );
    const scope = (): NativeQueueScope => {
      const database = openClawStateDatabaseCache.getOpenClawStateDatabaseIfOpenAtPath(pathname);
      requireNativeCompletion(database && database.db.isOpen && !database.db.isTransaction);
      let scopes = nativeQueueScopes.get(database.db);
      if (!scopes) {
        nativeQueueScopes.set(database.db, (scopes = new Map()));
      }
      let current = scopes.get(queueName);
      if (!current) {
        const identity = requireOpenClawStateDatabaseIdentity(database);
        const admission = captureOpenClawStateDatabaseReadAdmission(pathname);
        current = {
          handle: Object.freeze({}),
          queueName,
          accountId,
          database,
          assertCurrent: () => {
            admission.assertCurrent();
            requireNativeCompletion(
              database.db.isOpen &&
                !database.db.isTransaction &&
                openClawStateDatabaseCache.getOpenClawStateDatabaseIfOpenAtPath(pathname) ===
                  database,
            );
            assertExistingDatabaseIdentity(pathname, identity.key);
            requireNativeCompletion(realpathSync.native(pathname) === identity.canonicalPath);
          },
        };
        scopes.set(queueName, current);
      }
      current.assertCurrent();
      return current;
    };
    nativeQueueOwners.set(queue, {
      writable: access === "read-write",
      assertViewsCurrent: () => {},
      scope,
      complete: (entry) => {
        const receipt = Object.freeze({});
        const record: NativeCommitEntry = { ...entry, committed: false, consumed: false };
        nativeCommitReceipts.set(receipt, record);
        const database = entry.scope.database;
        const completedAt = now();
        // now() is a captured clock callback and can revoke the Source reentrantly.
        assertNativeWriteCurrent(entry);
        runOpenClawStateWriteTransaction(
          (tx) => {
            requireNativeCompletion(tx.db === database.db && tx.path === database.path);
            const result = executeSqliteQuerySync(
              tx.db,
              getChannelIngressKysely(tx.db)
                .updateTable("channel_ingress_events")
                .set({
                  status: "completed",
                  completed_at: completedAt,
                  updated_at: completedAt,
                  completed_metadata_json: null,
                  payload_json: "null",
                  metadata_json: null,
                  claim_token: null,
                  claim_owner: null,
                  claimed_at: null,
                  last_attempt_at: null,
                  last_error: null,
                })
                .where("queue_name", "=", queueName)
                .where("channel_id", "=", channelId)
                .where("account_id", "=", accountId)
                .where("event_id", "=", entry.claim.id)
                .where("status", "=", "claimed")
                .where("claim_token", "=", entry.claim.token)
                .where("claim_owner", "=", entry.claim.ownerId),
            );
            requireNativeCompletion(affectedRows(result) === 1);
            requireNativeCompletion(
              stageSqliteTransactionState(tx.db, {
                stage: () => {},
                commit: () => {
                  record.committed = true;
                },
                rollback: () => {
                  record.committed = false;
                },
              }),
            );
          },
          { path: database.path },
        );
        requireNativeCompletion(record.committed);
        return receipt;
      },
    });
  }
  return queue;
}
/* oxlint-disable max-lines -- TODO: split this grandfathered oversized file. */
