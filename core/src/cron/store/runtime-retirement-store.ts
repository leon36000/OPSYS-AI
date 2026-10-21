/** Host-only retirement receipts, independent of the deleted job's cascading sidecar. */
import { createHash } from "node:crypto";
import type { DatabaseSync } from "node:sqlite";
import { isDeepStrictEqual } from "node:util";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import {
  executeSqliteQuerySync,
  executeSqliteQueryTakeFirstSync,
  getNodeSqliteKysely,
} from "../../infra/kysely-sync.js";
import { extractSqliteTableSchema } from "../../infra/sqlite-schema-sql.js";
import { registerSecretValueForRedaction } from "../../logging/secret-redaction-registry.js";
import { tableExists } from "../../state/openclaw-state-db-schema-helpers.js";
import { OPENCLAW_STATE_SCHEMA_SQL } from "../../state/openclaw-state-schema.js";
import { resolveCronJobConfigRevision } from "../config-revision.js";
import { normalizeCronRuntimeAuthority, type CronRuntimeAuthority } from "../runtime-authority.js";
import type { CronStoredJob } from "../types.js";
import {
  OPSYS_CRON_AUTHORITY_NAMESPACE,
  OPSYS_CRON_AUTHORITY_RUNTIME_ID,
  openOpsysCronAuthority,
  sealOpsysCronAuthority,
  type OpsysCronAuthorityBinding,
} from "./opsys-runtime-authority-crypto.js";
import { loadCronRows, loadedCronStoreFromRows } from "./row-codec.js";
import { loadCronRuntimeAuthorities } from "./runtime-authority-store.js";
import { getCronStoreKysely } from "./schema.js";

const TABLE = "cron_job_runtime_retirements";
const PURPOSE = "opsys-cron-retirement";
const HEX = /^[a-f0-9]{64}$/u;
const REVISION = /^sha256:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/u;
const PROFILE = /^[a-z][a-z0-9-]{1,63}$/u;
const JOB = /^[A-Za-z0-9._:-]{1,128}$/u;
const MAX_PENDING = 16;

export type CronRetirementCapture = Readonly<{
  receiptId: string;
  sourceHash: string;
  profileId: string;
  intentionId: string;
  epoch: number;
  capabilityFingerprint: string;
  declarationHash: string;
  nativeRevision: string;
}>;

type RetirementRow = {
  store_key: string;
  receipt_id: string;
  job_id: string;
  profile_id: string;
  intention_id: string;
  epoch: number;
  source_hash: string;
  input_fingerprint: string;
  ciphertext: string;
  removed_at_ms: number;
  acknowledged_at_ms: number | null;
};
type RetirementDatabase = { cron_job_runtime_retirements: RetirementRow };

export type PendingCronRetirements = Readonly<{
  total: number;
  items: readonly Readonly<{ receiptId: string; profileId: string }>[];
}>;

export type CronRetirementProof = Readonly<{
  version: 1;
  purpose: typeof PURPOSE;
  capture: CronRetirementCapture;
  jobId: string;
  removedAtMs: number;
  authority: CronRuntimeAuthority;
}>;

function refuse(): never {
  throw new Error("Cron retirement proof refused.");
}
function transaction(db: DatabaseSync): void {
  if (!db.isTransaction) {
    refuse();
  }
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function integer(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** Capture every scalar now; asynchronous preconditions never reread caller objects. */
export function snapshotCronRetirementCapture(input: CronRetirementCapture): CronRetirementCapture {
  try {
    const snapshot = {
      receiptId: input.receiptId,
      sourceHash: input.sourceHash,
      profileId: input.profileId,
      intentionId: input.intentionId,
      epoch: input.epoch,
      capabilityFingerprint: input.capabilityFingerprint,
      declarationHash: input.declarationHash,
      nativeRevision: input.nativeRevision,
    };
    if (
      ![
        snapshot.receiptId,
        snapshot.sourceHash,
        snapshot.intentionId,
        snapshot.capabilityFingerprint,
        snapshot.declarationHash,
      ].every((v) => typeof v === "string" && HEX.test(v)) ||
      !integer(snapshot.epoch) ||
      snapshot.epoch > 2 ** 31 - 1 ||
      typeof snapshot.profileId !== "string" ||
      !PROFILE.test(snapshot.profileId) ||
      typeof snapshot.nativeRevision !== "string" ||
      !REVISION.test(snapshot.nativeRevision)
    ) {
      refuse();
    }
    return Object.freeze(snapshot);
  } catch {
    return refuse();
  }
}

function fingerprint(capture: CronRetirementCapture, jobId: string): string {
  return `retirement-v1:${createHash("sha256").update(stableStringify({ capture, jobId })).digest("hex")}`;
}
function binding(
  storeKey: string,
  jobId: string,
  inputFingerprint: string,
): OpsysCronAuthorityBinding {
  return {
    storeKey,
    jobId,
    inputFingerprint,
    runtimeId: OPSYS_CRON_AUTHORITY_RUNTIME_ID,
    namespace: OPSYS_CRON_AUTHORITY_NAMESPACE,
  };
}

function authorityMatches(
  authority: CronRuntimeAuthority,
  capture: CronRetirementCapture,
): boolean {
  const payload = authority.payload;
  if (
    authority.version !== 1 ||
    authority.runtimeId !== OPSYS_CRON_AUTHORITY_RUNTIME_ID ||
    authority.namespace !== OPSYS_CRON_AUTHORITY_NAMESPACE ||
    payload.version !== 1 ||
    payload.profil_id !== capture.profileId ||
    payload.intention_id !== capture.intentionId ||
    payload.epoch !== capture.epoch ||
    typeof payload.capabilite !== "string" ||
    !HEX.test(payload.capabilite) ||
    !isRecord(payload.declaration)
  ) {
    return false;
  }
  registerSecretValueForRedaction(payload.capabilite);
  return (
    createHash("sha256").update(Buffer.from(payload.capabilite, "hex")).digest("hex") ===
      capture.capabilityFingerprint &&
    createHash("sha256").update(stableStringify(payload.declaration), "utf8").digest("hex") ===
      capture.declarationHash
  );
}

function ensure(db: DatabaseSync): void {
  transaction(db);
  // sqlite-allow-raw -- Feature-local first write installs only its canonical additive DDL.
  db.exec(extractSqliteTableSchema(OPENCLAW_STATE_SCHEMA_SQL, TABLE));
}

/** MUST run in removeWithPrecondition's owning SQL transaction, before its DELETE. */
export function recordCronRetirementBeforeDelete(
  db: DatabaseSync,
  storeKey: string,
  expectedJob: CronStoredJob,
  captureInput: CronRetirementCapture,
  removedAtMs: number,
): void {
  transaction(db);
  const capture = snapshotCronRetirementCapture(captureInput);
  if (
    !integer(removedAtMs) ||
    !JOB.test(expectedJob.id) ||
    expectedJob.enabled ||
    expectedJob.declarationKey !== `opsys-profile:${capture.intentionId}` ||
    expectedJob.agentId !== `opsys-agent-${capture.profileId}` ||
    resolveCronJobConfigRevision(expectedJob) !== capture.nativeRevision
  ) {
    refuse();
  }
  const currentJobs = loadedCronStoreFromRows(loadCronRows(db, storeKey, new Set([expectedJob.id])))
    .store.jobs;
  if (currentJobs.length !== 1) {
    refuse();
  }
  loadCronRuntimeAuthorities({ db, storeKey, jobs: currentJobs });
  const current = currentJobs[0]!;
  const authority = normalizeCronRuntimeAuthority(current.runtimeAuthority);
  const expectedAuthority = normalizeCronRuntimeAuthority(expectedJob.runtimeAuthority);
  if (
    current.enabled ||
    resolveCronJobConfigRevision(current) !== capture.nativeRevision ||
    current.runtimeAuthorityRecoveryRequired === true ||
    !authority ||
    !expectedAuthority ||
    !isDeepStrictEqual(authority, expectedAuthority) ||
    !authorityMatches(authority, capture)
  ) {
    refuse();
  }
  ensure(db);
  const database = getNodeSqliteKysely<RetirementDatabase>(db);
  const existing = executeSqliteQueryTakeFirstSync(
    db,
    database
      .selectFrom(TABLE)
      .select("receipt_id")
      .where("store_key", "=", storeKey)
      .where("receipt_id", "=", capture.receiptId),
  );
  if (existing) {
    refuse();
  } // A committed receipt's deleted job cannot be recreated for this operation.
  const pending = executeSqliteQueryTakeFirstSync(
    db,
    database
      .selectFrom(TABLE)
      .select((eb) => eb.fn.countAll<number>().as("total"))
      .where("store_key", "=", storeKey)
      .where("profile_id", "=", capture.profileId)
      .where("acknowledged_at_ms", "is", null),
  );
  if (!pending || pending.total >= MAX_PENDING) {
    refuse();
  }
  const inputFingerprint = fingerprint(capture, current.id);
  const proof: CronRetirementProof = {
    version: 1,
    purpose: PURPOSE,
    capture,
    jobId: current.id,
    removedAtMs,
    authority,
  };
  const ciphertext = sealOpsysCronAuthority(
    binding(storeKey, current.id, inputFingerprint),
    JSON.stringify(proof),
  );
  if (!ciphertext) {
    refuse();
  }
  executeSqliteQuerySync(
    db,
    database.insertInto(TABLE).values({
      store_key: storeKey,
      receipt_id: capture.receiptId,
      job_id: current.id,
      profile_id: capture.profileId,
      intention_id: capture.intentionId,
      epoch: capture.epoch,
      source_hash: capture.sourceHash,
      input_fingerprint: inputFingerprint,
      ciphertext,
      removed_at_ms: removedAtMs,
      acknowledged_at_ms: null,
    }),
  );
}

/** Host-private only: never serialize the recovered authority to a Gateway/public response. */
export function readCronRetirementProof(
  db: DatabaseSync,
  storeKey: string,
  receiptId: string,
): CronRetirementProof | undefined {
  if (!HEX.test(receiptId)) {
    refuse();
  }
  if (!tableExists(db, TABLE)) {
    return undefined;
  }
  const database = getNodeSqliteKysely<RetirementDatabase>(db);
  const query = database
    .selectFrom(TABLE)
    .where("store_key", "=", storeKey)
    .where("receipt_id", "=", receiptId);
  const size = executeSqliteQueryTakeFirstSync(
    db,
    query.select((eb) => eb.fn<number>("length", [eb.cast("ciphertext", "blob")]).as("bytes")),
  );
  if (!size) {
    return undefined;
  }
  if (size.bytes > 96 * 1024) {
    refuse();
  }
  const row = executeSqliteQueryTakeFirstSync(db, query.selectAll());
  if (!row) {
    refuse();
  }
  if (Buffer.byteLength(row.ciphertext, "utf8") > 96 * 1024) {
    refuse();
  }
  try {
    const text = openOpsysCronAuthority(
      binding(storeKey, row.job_id, row.input_fingerprint),
      row.ciphertext,
    );
    if (!text) {
      refuse();
    }
    const value: unknown = JSON.parse(text);
    if (
      !isRecord(value) ||
      value.version !== 1 ||
      value.purpose !== PURPOSE ||
      !isRecord(value.capture) ||
      value.jobId !== row.job_id ||
      value.removedAtMs !== row.removed_at_ms
    ) {
      refuse();
    }
    const raw = value.capture;
    // Bounded JSON was sealed by this owner; still validate every restored field.
    if (
      typeof raw.receiptId !== "string" ||
      typeof raw.sourceHash !== "string" ||
      typeof raw.profileId !== "string" ||
      typeof raw.intentionId !== "string" ||
      typeof raw.epoch !== "number" ||
      typeof raw.capabilityFingerprint !== "string" ||
      typeof raw.declarationHash !== "string" ||
      typeof raw.nativeRevision !== "string"
    ) {
      refuse();
    }
    const capture = snapshotCronRetirementCapture({
      receiptId: raw.receiptId,
      sourceHash: raw.sourceHash,
      profileId: raw.profileId,
      intentionId: raw.intentionId,
      epoch: raw.epoch,
      capabilityFingerprint: raw.capabilityFingerprint,
      declarationHash: raw.declarationHash,
      nativeRevision: raw.nativeRevision,
    });
    const authority = normalizeCronRuntimeAuthority(value.authority);
    if (
      capture.receiptId !== receiptId ||
      capture.sourceHash !== row.source_hash ||
      capture.profileId !== row.profile_id ||
      capture.intentionId !== row.intention_id ||
      capture.epoch !== row.epoch ||
      fingerprint(capture, row.job_id) !== row.input_fingerprint ||
      !authority ||
      !authorityMatches(authority, capture) ||
      loadCronRows(db, storeKey, new Set([row.job_id])).length !== 0
    ) {
      refuse();
    }
    const rebound = executeSqliteQueryTakeFirstSync(
      db,
      getCronStoreKysely(db)
        .selectFrom("cron_jobs")
        .select("job_id")
        .where("store_key", "=", storeKey)
        .where("declaration_key", "=", `opsys-profile:${capture.intentionId}`)
        .limit(1),
    );
    if (rebound) {
      refuse();
    }
    return {
      version: 1,
      purpose: PURPOSE,
      capture,
      jobId: row.job_id,
      removedAtMs: row.removed_at_ms,
      authority,
    };
  } catch {
    return refuse();
  }
}

/** Pending receipt IDs are bounded metadata; callers then restore only one encrypted proof. */
export function listPendingCronRetirementIds(
  db: DatabaseSync,
  storeKey: string,
  profileId: string,
): string[] {
  if (!PROFILE.test(profileId)) {
    refuse();
  }
  if (!tableExists(db, TABLE)) {
    return [];
  }
  const database = getNodeSqliteKysely<RetirementDatabase>(db);
  const query = database
    .selectFrom(TABLE)
    .where("store_key", "=", storeKey)
    .where("profile_id", "=", profileId)
    .where("acknowledged_at_ms", "is", null);
  const count = executeSqliteQueryTakeFirstSync(
    db,
    query.select((eb) => eb.fn.countAll<number>().as("total")),
  );
  if (!count || count.total > MAX_PENDING) {
    refuse();
  }
  return executeSqliteQuerySync(
    db,
    query.select("receipt_id").orderBy("removed_at_ms").orderBy("receipt_id").limit(MAX_PENDING),
  ).rows.map((row) => row.receipt_id);
}

/** Global housekeeping reads one bounded page; an incomplete drain blocks new declarations. */
export function listPendingCronRetirements(
  db: DatabaseSync,
  storeKey: string,
  profileId?: string,
): PendingCronRetirements {
  if (profileId !== undefined && !PROFILE.test(profileId)) {
    refuse();
  }
  if (!tableExists(db, TABLE)) {
    return { total: 0, items: [] };
  }
  const database = getNodeSqliteKysely<RetirementDatabase>(db);
  let query = database
    .selectFrom(TABLE)
    .where("store_key", "=", storeKey)
    .where("acknowledged_at_ms", "is", null);
  if (profileId !== undefined) {
    query = query.where("profile_id", "=", profileId);
  }
  const count = executeSqliteQueryTakeFirstSync(
    db,
    query.select((eb) => eb.fn.countAll<number>().as("total")),
  );
  if (
    !count ||
    !Number.isSafeInteger(count.total) ||
    count.total < 0 ||
    (profileId !== undefined && count.total > MAX_PENDING)
  ) {
    refuse();
  }
  const rows = executeSqliteQuerySync(
    db,
    query
      .select(["receipt_id", "profile_id"])
      .orderBy("removed_at_ms")
      .orderBy("receipt_id")
      .limit(MAX_PENDING),
  ).rows;
  if (rows.some((row) => !HEX.test(row.receipt_id) || !PROFILE.test(row.profile_id))) {
    refuse();
  }
  return {
    total: count.total,
    items: rows.map((row) => ({ receiptId: row.receipt_id, profileId: row.profile_id })),
  };
}

/** SQL transaction owner only; its worker admits entry and commit after the exact Python ACK. */
export function acknowledgeCronRetirementProof(
  db: DatabaseSync,
  storeKey: string,
  receiptId: string,
  sourceHash: string,
  nowMs: number,
): void {
  transaction(db);
  if (!HEX.test(sourceHash) || !integer(nowMs)) {
    refuse();
  }
  const proof = readCronRetirementProof(db, storeKey, receiptId);
  if (!proof || proof.capture.sourceHash !== sourceHash) {
    refuse();
  }
  const database = getNodeSqliteKysely<RetirementDatabase>(db);
  executeSqliteQuerySync(
    db,
    database
      .updateTable(TABLE)
      .set({ acknowledged_at_ms: nowMs })
      .where("store_key", "=", storeKey)
      .where("receipt_id", "=", receiptId)
      .where("acknowledged_at_ms", "is", null),
  );
}
