import { createHash } from "node:crypto";
import type { DatabaseSync } from "node:sqlite";
import type { Insertable, Selectable } from "kysely";
import type { OpsysM9CibleTicketBinding } from "../../context-engine/opsys-contexte-cible-ticket.js";
import {
  isOpsysCibleTicketTool,
  OPSYS_CIBLE_TICKET_SERVERS,
} from "../../context-engine/opsys-contexte-cibles.js";
import {
  executeSqliteQuerySync,
  executeSqliteQueryTakeFirstSync,
  getNodeSqliteKysely,
} from "../../infra/kysely-sync.js";
import { extractSqliteTableSchema } from "../../infra/sqlite-schema-sql.js";
import {
  assertTransactionUsable,
  runSqliteImmediateTransactionSync,
} from "../../infra/sqlite-transaction.js";
import type { SqliteWorkerBackend } from "../../infra/sqlite-worker-contract.js";
import type { DB as AgentDatabaseSchema } from "../../state/openclaw-agent-db.generated.js";
import { OPENCLAW_AGENT_SCHEMA_SQL } from "../../state/openclaw-agent-schema.js";
import { OPENCLAW_SQLITE_BUSY_TIMEOUT_MS } from "../../state/openclaw-state-db-contract.js";

export const OPSYS_POSTFLIGHT_OUTBOX_TABLE = "opsys_postflight_outbox";
export const OPSYS_POSTFLIGHT_INTENTS_TABLE = "opsys_postflight_intents";
const INTENT_RESERVED_BYTES = 4096;
const MAX_LOTS = 256;
const MAX_BYTES = 1024 * 1024;
const MAX_FACTS = 20;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const RETRY_DELAYS_MS = [60_000, 5 * 60_000, 15 * 60_000, 60 * 60_000, 24 * 60 * 60_000];
const AFFAIRE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$/u;
const DEPARTMENT = /^m(0[1-9]|10)-[a-z][a-z0-9-]*$/u;
const PROFILE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/u;
const ENGINE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const FACT_KEY = /^tc-(?:[0-9a-f]{40}|[0-9a-f]{64})$/u;
const TOOL = /^m(10|[1-9])_[a-z][a-z0-9_]{1,60}$/u;
const CODE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/u;

export type OpsysPostflightFact = Readonly<{
  cle: string;
  outil: string;
  resultat: "ok" | "refus";
  code: string | null;
}>;

export type OpsysPostflightLotInput = Readonly<{
  affaireId: string;
  departementSource: string;
  profilId: string;
  revision: number;
  engineId: string;
  facts: readonly OpsysPostflightFact[];
}>;

export type OpsysPostflightLot = OpsysPostflightLotInput &
  Readonly<{
    lotKey: string;
    state: "pending" | "retry" | "needs_review";
    attemptCount: number;
    createdAt: number;
    updatedAt: number;
    nextAttemptAt: number | null;
    lastAttemptAt: number | null;
    lastErrorCode: string | null;
    needsReviewAt: number | null;
  }>;

/** Host metadata only. Uncertainty is not an assertion that the source RPC ran. */
export type OpsysPostflightIntentInput = Readonly<{
  factKey: string;
  affaireId: string;
  departementSource: string;
  profilId: string;
  revision: number;
  engineId: "opsys";
  outil: string;
  serverName: string;
  ownerKey: string;
  m9Binding?: OpsysM9CibleTicketBinding;
}>;

export type OpsysPostflightIntent = OpsysPostflightIntentInput &
  Readonly<{ state: "uncertain"; createdAt: number; approvalPendingRequestId?: string }>;

const M9_OPEN_FOLLOWUP = "m9_ouvrir_suivi_decision";
const APPROVAL_REQUEST_ID = /^[0-9a-f]{12}$/u;

type OutboxTable = AgentDatabaseSchema["opsys_postflight_outbox"];
type OutboxRow = Selectable<OutboxTable>;
type OutboxInsert = Insertable<OutboxTable>;
type OutboxDatabase = Pick<
  AgentDatabaseSchema,
  "opsys_postflight_outbox" | "opsys_postflight_intents"
>;
type IntentRow = Selectable<AgentDatabaseSchema["opsys_postflight_intents"]>;

export type OpsysPostflightOutboxOperations = {
  reserveIntent: {
    input: { intent: OpsysPostflightIntentInput; now: number };
    output: OpsysPostflightIntent;
  };
  listIntents: { input: { now: number }; output: OpsysPostflightIntent[] };
  observeM9ApprovalPending: {
    input: { expected: OpsysPostflightIntentInput; requestId: string; now: number };
    output: OpsysPostflightIntent;
  };
  completeIntent: {
    input: { expected: OpsysPostflightIntentInput; fact: OpsysPostflightFact; now: number };
    output: OpsysPostflightLot;
  };
  enqueue: {
    input: { lots: readonly OpsysPostflightLotInput[]; now: number };
    output: Array<{ lot: OpsysPostflightLot; created: boolean }>;
  };
  list: { input: { now: number }; output: OpsysPostflightLot[] };
  listDue: { input: { now: number }; output: OpsysPostflightLot[] };
  beginAttempt: {
    input: { lotKey: string; expected: OpsysPostflightLotInput; now: number };
    output: OpsysPostflightLot | undefined;
  };
  acknowledge: {
    input: { lotKey: string; expected: OpsysPostflightLotInput; now: number };
    output: boolean;
  };
  recordFailure: {
    input: { lotKey: string; expected: OpsysPostflightLotInput; code: string; now: number };
    output: OpsysPostflightLot;
  };
};

function fail(code: string): never {
  throw new Error(code);
}

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null)
  ) {
    return false;
  }
  const actual = Reflect.ownKeys(value);
  const expected = keys.toSorted();
  if (actual.length !== expected.length || actual.some((key) => typeof key !== "string")) {
    return false;
  }
  return (actual as string[]).toSorted().every((key, index) => key === expected[index]);
}

function validateFact(value: unknown): OpsysPostflightFact {
  if (!exactKeys(value, ["cle", "outil", "resultat", "code"])) {
    return fail("POSTFLIGHT_FACT_SCHEMA_REFUSE");
  }
  if (
    typeof value.cle !== "string" ||
    !FACT_KEY.test(value.cle) ||
    typeof value.outil !== "string" ||
    !TOOL.test(value.outil) ||
    (value.resultat !== "ok" && value.resultat !== "refus") ||
    (value.code !== null && (typeof value.code !== "string" || !CODE.test(value.code)))
  ) {
    return fail("POSTFLIGHT_FACT_VALUE_REFUSE");
  }
  return { cle: value.cle, outil: value.outil, resultat: value.resultat, code: value.code };
}

function normalizeLot(value: unknown): OpsysPostflightLotInput {
  if (
    !exactKeys(value, [
      "affaireId",
      "departementSource",
      "profilId",
      "revision",
      "engineId",
      "facts",
    ])
  ) {
    return fail("POSTFLIGHT_LOT_SCHEMA_REFUSE");
  }
  if (
    typeof value.affaireId !== "string" ||
    !AFFAIRE.test(value.affaireId) ||
    typeof value.departementSource !== "string" ||
    !DEPARTMENT.test(value.departementSource) ||
    typeof value.profilId !== "string" ||
    !PROFILE.test(value.profilId) ||
    typeof value.engineId !== "string" ||
    !ENGINE.test(value.engineId) ||
    !Number.isSafeInteger(value.revision) ||
    (value.revision as number) < 1 ||
    (value.revision as number) > 2_147_483_647 ||
    !Array.isArray(value.facts) ||
    value.facts.length < 1 ||
    value.facts.length > MAX_FACTS
  ) {
    return fail("POSTFLIGHT_LOT_VALUE_REFUSE");
  }
  const facts = value.facts
    .map(validateFact)
    .toSorted((left, right) => left.cle.localeCompare(right.cle));
  if (new Set(facts.map((fact) => fact.cle)).size !== facts.length) {
    return fail("POSTFLIGHT_FACT_DUPLICATE_REFUSE");
  }
  return {
    affaireId: value.affaireId,
    departementSource: value.departementSource,
    profilId: value.profilId,
    revision: value.revision as number,
    engineId: value.engineId,
    facts,
  };
}

function normalizeIntent(value: unknown): OpsysPostflightIntentInput {
  const keys = [
    "factKey",
    "affaireId",
    "departementSource",
    "profilId",
    "revision",
    "engineId",
    "outil",
    "serverName",
    "ownerKey",
  ];
  if (!exactKeys(value, keys) && !exactKeys(value, [...keys, "m9Binding"])) {
    return fail("POSTFLIGHT_INTENT_SCHEMA_REFUSE");
  }
  if (
    typeof value.factKey !== "string" ||
    !/^tc-[0-9a-f]{40}$/u.test(value.factKey) ||
    typeof value.ownerKey !== "string" ||
    !/^[0-9a-f]{64}$/u.test(value.ownerKey) ||
    typeof value.outil !== "string" ||
    !isOpsysCibleTicketTool(value.outil) ||
    value.serverName !== OPSYS_CIBLE_TICKET_SERVERS[value.outil] ||
    value.engineId !== "opsys"
  ) {
    return fail("POSTFLIGHT_INTENT_VALUE_REFUSE");
  }
  const closedLot = normalizeLot({
    affaireId: value.affaireId,
    departementSource: value.departementSource,
    profilId: value.profilId,
    revision: value.revision,
    engineId: value.engineId,
    facts: [{ cle: value.factKey, outil: value.outil, resultat: "refus", code: null }],
  });
  let m9Binding: OpsysM9CibleTicketBinding | undefined;
  if (Object.hasOwn(value, "m9Binding")) {
    const binding = value.m9Binding;
    if (
      value.outil !== M9_OPEN_FOLLOWUP ||
      !exactKeys(binding, [
        "nativeInstanceId",
        "ticketHash",
        "agentId",
        "sessionKey",
        "contextServerName",
      ]) ||
      typeof binding.nativeInstanceId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(
        binding.nativeInstanceId,
      ) ||
      typeof binding.ticketHash !== "string" ||
      !/^[0-9a-f]{64}$/u.test(binding.ticketHash) ||
      typeof binding.agentId !== "string" ||
      binding.agentId.length === 0 ||
      typeof binding.sessionKey !== "string" ||
      binding.sessionKey.length === 0 ||
      typeof binding.contextServerName !== "string" ||
      binding.contextServerName.length === 0
    ) {
      return fail("POSTFLIGHT_INTENT_VALUE_REFUSE");
    }
    // Historical correlation only; a logical Native UUID is not live authority.
    m9Binding = {
      nativeInstanceId: binding.nativeInstanceId,
      ticketHash: binding.ticketHash,
      agentId: binding.agentId,
      sessionKey: binding.sessionKey,
      contextServerName: binding.contextServerName,
    };
  }
  const normalized: OpsysPostflightIntentInput = {
    factKey: value.factKey,
    affaireId: closedLot.affaireId,
    departementSource: closedLot.departementSource,
    profilId: closedLot.profilId,
    revision: closedLot.revision,
    engineId: "opsys",
    outil: value.outil,
    serverName: OPSYS_CIBLE_TICKET_SERVERS[value.outil],
    ownerKey: value.ownerKey,
    ...(m9Binding === undefined ? {} : { m9Binding }),
  };
  // The synthetic shape above is validation only; it is never written as a fact.
  // Keep at least half the reserved budget for the worst closed singleton outcome.
  const worstOutcome = {
    ...closedLot,
    facts: [
      {
        cle: normalized.factKey,
        outil: normalized.outil,
        resultat: "refus" as const,
        code: "C".repeat(80),
      },
    ],
  };
  if (
    Buffer.byteLength(JSON.stringify(normalized), "utf8") > INTENT_RESERVED_BYTES / 2 ||
    Buffer.byteLength(payloadFor(worstOutcome), "utf8") > INTENT_RESERVED_BYTES / 2
  ) {
    return fail("POSTFLIGHT_INTENT_VALUE_REFUSE");
  }
  return normalized;
}

function decodeIntentRow(row: IntentRow): {
  input: OpsysPostflightIntentInput;
  approvalPendingRequestId?: string;
} {
  let decoded: unknown;
  try {
    decoded = JSON.parse(row.payload_json);
  } catch {
    return fail("POSTFLIGHT_INTENT_ROW_CORRUPT");
  }
  let approvalPendingRequestId: string | undefined;
  if (
    decoded !== null &&
    typeof decoded === "object" &&
    !Array.isArray(decoded) &&
    Object.hasOwn(decoded, "approvalPendingRequestId")
  ) {
    if (
      !exactKeys(decoded, [
        "factKey",
        "affaireId",
        "departementSource",
        "profilId",
        "revision",
        "engineId",
        "outil",
        "serverName",
        "ownerKey",
        ...(Object.hasOwn(decoded, "m9Binding") ? ["m9Binding"] : []),
        "approvalPendingRequestId",
      ])
    ) {
      return fail("POSTFLIGHT_INTENT_ROW_CORRUPT");
    }
    const record = decoded;
    if (
      typeof record.approvalPendingRequestId !== "string" ||
      !APPROVAL_REQUEST_ID.test(record.approvalPendingRequestId)
    ) {
      return fail("POSTFLIGHT_INTENT_ROW_CORRUPT");
    }
    approvalPendingRequestId = record.approvalPendingRequestId;
    const { approvalPendingRequestId: _observed, ...input } = record;
    decoded = input;
  }
  const input = normalizeIntent(decoded);
  const payload = JSON.stringify({
    ...input,
    ...(approvalPendingRequestId === undefined ? {} : { approvalPendingRequestId }),
  });
  if (
    payload !== row.payload_json ||
    (approvalPendingRequestId !== undefined && input.outil !== M9_OPEN_FOLLOWUP) ||
    input.factKey !== row.fact_key ||
    row.state !== "uncertain" ||
    !Number.isSafeInteger(row.created_at) ||
    row.created_at < 0
  ) {
    return fail("POSTFLIGHT_INTENT_ROW_CORRUPT");
  }
  return { input, ...(approvalPendingRequestId === undefined ? {} : { approvalPendingRequestId }) };
}

function intentRowToIntent(row: IntentRow): OpsysPostflightIntent {
  const { input, approvalPendingRequestId } = decodeIntentRow(row);
  return {
    ...input,
    state: "uncertain",
    createdAt: row.created_at,
    ...(approvalPendingRequestId === undefined ? {} : { approvalPendingRequestId }),
  };
}

function readIntentRows(db: DatabaseSync): IntentRow[] {
  const table = getNodeSqliteKysely<OutboxDatabase>(db);
  const rows = executeSqliteQuerySync(
    db,
    table
      .selectFrom(OPSYS_POSTFLIGHT_INTENTS_TABLE)
      .selectAll()
      .orderBy("created_at")
      .orderBy("fact_key"),
  ).rows;
  // Invalid retained metadata must never quietly release pre-effect capacity.
  for (const row of rows) {
    intentRowToIntent(row);
  }
  return rows;
}

function nowValue(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    return fail("POSTFLIGHT_HORLOGE_REFUSE");
  }
  return value as number;
}

function payloadFor(lot: OpsysPostflightLotInput): string {
  return JSON.stringify({
    affaire_id: lot.affaireId,
    departement_source: lot.departementSource,
    profil_id: lot.profilId,
    revision: lot.revision,
    engine_id: lot.engineId,
    faits: lot.facts,
  });
}

function keyFor(lot: OpsysPostflightLotInput): string {
  const keys = lot.facts.map((fact) => fact.cle).toSorted();
  return `postflight-${createHash("sha256").update(keys.join("\n"), "utf8").digest("hex")}`;
}

/** Produces an opaque stable M10 key without retaining the call or session identifiers. */
export function deriveOpsysPostflightFactKey(sessionId: string, toolCallId: string): string {
  if (
    typeof sessionId !== "string" ||
    !sessionId ||
    Buffer.byteLength(sessionId, "utf8") > 4096 ||
    typeof toolCallId !== "string" ||
    !toolCallId ||
    Buffer.byteLength(toolCallId, "utf8") > 1024
  ) {
    return fail("POSTFLIGHT_CALL_ID_REFUSE");
  }
  const material = `opsys-postflight-candidate-v1\0${Buffer.byteLength(sessionId, "utf8")}:${sessionId}\0${Buffer.byteLength(toolCallId, "utf8")}:${toolCallId}`;
  return `tc-${createHash("sha256").update(material, "utf8").digest("hex")}`;
}

function decodePayload(payload: string): OpsysPostflightLotInput {
  let decoded: unknown;
  try {
    decoded = JSON.parse(payload);
  } catch {
    return fail("POSTFLIGHT_ROW_CORRUPT");
  }
  if (
    !exactKeys(decoded, [
      "affaire_id",
      "departement_source",
      "profil_id",
      "revision",
      "engine_id",
      "faits",
    ])
  ) {
    return fail("POSTFLIGHT_ROW_CORRUPT");
  }
  const content = normalizeLot({
    affaireId: decoded.affaire_id,
    departementSource: decoded.departement_source,
    profilId: decoded.profil_id,
    revision: decoded.revision,
    engineId: decoded.engine_id,
    facts: decoded.faits,
  });
  if (payloadFor(content) !== payload) {
    return fail("POSTFLIGHT_ROW_CORRUPT");
  }
  return content;
}

function rowToLot(row: OutboxRow): OpsysPostflightLot {
  const content = decodePayload(row.payload_json);
  if (
    row.lot_key !== keyFor(content) ||
    row.affaire_id !== content.affaireId ||
    row.departement_source !== content.departementSource ||
    row.profil_id !== content.profilId ||
    row.revision_admission !== content.revision ||
    row.engine_id !== content.engineId ||
    !["pending", "retry", "needs_review"].includes(row.state) ||
    !Number.isInteger(row.attempt_count) ||
    row.attempt_count < 0 ||
    row.attempt_count > 8
  ) {
    return fail("POSTFLIGHT_ROW_CORRUPT");
  }
  return {
    ...content,
    lotKey: row.lot_key,
    state: row.state as OpsysPostflightLot["state"],
    attemptCount: row.attempt_count,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    nextAttemptAt: row.next_attempt_at,
    lastAttemptAt: row.last_attempt_at,
    lastErrorCode: row.last_error_code,
    needsReviewAt: row.needs_review_at,
  };
}

function ensureSchema(db: DatabaseSync): void {
  // sqlite-allow-raw -- Extract the canonical additive DDL on first use for old owner databases.
  db.exec(
    extractSqliteTableSchema(OPENCLAW_AGENT_SCHEMA_SQL, OPSYS_POSTFLIGHT_OUTBOX_TABLE, {
      endMarker: "CREATE TABLE IF NOT EXISTS cache_entries (",
      includeEndMarker: false,
      errorMessage: "OpenClaw postflight outbox DDL marker missing.",
    }),
  );
}

function readRows(db: DatabaseSync): OutboxRow[] {
  const table = getNodeSqliteKysely<OutboxDatabase>(db);
  return executeSqliteQuerySync(
    db,
    table
      .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
      .selectAll()
      .orderBy("created_at")
      .orderBy("lot_key"),
  ).rows;
}

export type OpsysPostflightDiagnosticSnapshot = {
  observedAt: number;
  limits: { maxSlots: number; maxBytes: number; intentReservedBytes: number };
  capacity: { occupiedSlots: number; freeSlots: number; reservedBytes: number; freeBytes: number };
  counts: {
    uncertain: number;
    pending: number;
    retry: number;
    reviewRequired: number;
    due: number;
  };
  uncertainIntents: Array<
    Pick<
      OpsysPostflightIntent,
      "affaireId" | "departementSource" | "profilId" | "revision" | "outil" | "createdAt"
    >
  >;
  lots: Array<
    Pick<
      OpsysPostflightLot,
      | "affaireId"
      | "departementSource"
      | "profilId"
      | "revision"
      | "state"
      | "attemptCount"
      | "createdAt"
      | "nextAttemptAt"
      | "lastErrorCode"
    > & { factCount: number; reviewRequired: boolean; dueForDelivery: boolean }
  >;
};

/** Owner's diagnostic projection. No DDL, expiry transition, source RPC or acknowledgement. */
export function readOpsysPostflightDiagnosticSnapshot(
  db: DatabaseSync,
  observedAt: number,
):
  | { status: "available"; snapshot: OpsysPostflightDiagnosticSnapshot }
  | { status: "unavailable"; reason: "tables-missing" } {
  const now = nowValue(observedAt);
  if (db.isTransaction) {
    return fail("POSTFLIGHT_DIAGNOSTIC_TRANSACTION_REFUSE");
  }
  // sqlite-allow-raw -- Deferred read transaction pins the two queues to one committed snapshot.
  db.exec("BEGIN");
  try {
    const schema = getNodeSqliteKysely<{ sqlite_schema: { name: string; type: string } }>(db);
    const names = executeSqliteQuerySync(
      db,
      schema
        .selectFrom("sqlite_schema")
        .select("name")
        .where("type", "=", "table")
        .where("name", "in", [OPSYS_POSTFLIGHT_OUTBOX_TABLE, OPSYS_POSTFLIGHT_INTENTS_TABLE]),
    ).rows;
    if (names.length !== 2) {
      // sqlite-allow-raw -- Settle this read snapshot without any schema change.
      db.exec("COMMIT");
      return { status: "unavailable", reason: "tables-missing" };
    }
    const table = getNodeSqliteKysely<OutboxDatabase>(db);
    const measure = (name: keyof OutboxDatabase) =>
      executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(
            table
              .selectFrom(name)
              .select("payload_json")
              .limit(MAX_LOTS + 1)
              .as("bounded"),
          )
          .select((eb) => [
            eb.fn.countAll<number>().as("count"),
            eb.fn
              .coalesce(
                eb.fn.sum<number>(eb.fn<number>("length", [eb.cast("payload_json", "blob")])),
                eb.val(0),
              )
              .as("bytes"),
          ]),
      )!;
    const intentMeasure = measure(OPSYS_POSTFLIGHT_INTENTS_TABLE);
    const lotMeasure = measure(OPSYS_POSTFLIGHT_OUTBOX_TABLE);
    const occupiedSlots = intentMeasure.count + lotMeasure.count;
    const reservedBytes = intentMeasure.count * INTENT_RESERVED_BYTES + lotMeasure.bytes;
    if (
      ![
        intentMeasure.count,
        intentMeasure.bytes,
        lotMeasure.count,
        lotMeasure.bytes,
        occupiedSlots,
        reservedBytes,
      ].every((n) => Number.isSafeInteger(n) && n >= 0) ||
      occupiedSlots > MAX_LOTS ||
      reservedBytes > MAX_BYTES ||
      intentMeasure.bytes > (intentMeasure.count * INTENT_RESERVED_BYTES) / 2
    ) {
      return fail("POSTFLIGHT_DIAGNOSTIC_QUOTA_REFUSE");
    }
    const intents = executeSqliteQuerySync(
      db,
      table
        .selectFrom(OPSYS_POSTFLIGHT_INTENTS_TABLE)
        .selectAll()
        .orderBy("created_at")
        .orderBy("fact_key")
        .limit(MAX_LOTS),
    ).rows.map(intentRowToIntent);
    const lots = executeSqliteQuerySync(
      db,
      table
        .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
        .selectAll()
        .orderBy("created_at")
        .orderBy("lot_key")
        .limit(MAX_LOTS),
    ).rows.map(rowToLot);
    if (intents.length !== intentMeasure.count || lots.length !== lotMeasure.count) {
      return fail("POSTFLIGHT_DIAGNOSTIC_SNAPSHOT_REFUSE");
    }
    const projection = lots.map((lot) => {
      if (
        ![
          lot.createdAt,
          lot.updatedAt,
          lot.nextAttemptAt,
          lot.lastAttemptAt,
          lot.needsReviewAt,
        ].every((n) => n === null || (Number.isSafeInteger(n) && n >= 0)) ||
        lot.createdAt === null ||
        lot.updatedAt === null ||
        (lot.state === "needs_review"
          ? lot.nextAttemptAt !== null || lot.needsReviewAt === null
          : lot.nextAttemptAt === null || lot.needsReviewAt !== null) ||
        (lot.lastErrorCode !== null && !CODE.test(lot.lastErrorCode))
      ) {
        return fail("POSTFLIGHT_DIAGNOSTIC_ROW_REFUSE");
      }
      const reviewRequired =
        lot.state === "needs_review" || now - lot.createdAt >= MAX_AGE_MS || lot.attemptCount >= 8;
      return {
        affaireId: lot.affaireId,
        departementSource: lot.departementSource,
        profilId: lot.profilId,
        revision: lot.revision,
        state: lot.state,
        attemptCount: lot.attemptCount,
        createdAt: lot.createdAt,
        nextAttemptAt: lot.nextAttemptAt,
        lastErrorCode: lot.lastErrorCode,
        factCount: lot.facts.length,
        reviewRequired,
        dueForDelivery: !reviewRequired && lot.nextAttemptAt !== null && lot.nextAttemptAt <= now,
      };
    });
    const snapshot: OpsysPostflightDiagnosticSnapshot = {
      observedAt: now,
      limits: {
        maxSlots: MAX_LOTS,
        maxBytes: MAX_BYTES,
        intentReservedBytes: INTENT_RESERVED_BYTES,
      },
      capacity: {
        occupiedSlots,
        freeSlots: MAX_LOTS - occupiedSlots,
        reservedBytes,
        freeBytes: MAX_BYTES - reservedBytes,
      },
      counts: {
        uncertain: intents.length,
        pending: lots.filter((lot) => lot.state === "pending").length,
        retry: lots.filter((lot) => lot.state === "retry").length,
        reviewRequired: projection.filter((lot) => lot.reviewRequired).length,
        due: projection.filter((lot) => lot.dueForDelivery).length,
      },
      uncertainIntents: intents.map(
        ({ affaireId, departementSource, profilId, revision, outil, createdAt }) => ({
          affaireId,
          departementSource,
          profilId,
          revision,
          outil,
          createdAt,
        }),
      ),
      lots: projection,
    };
    // sqlite-allow-raw -- Settle the committed read snapshot, never a writer transaction.
    db.exec("COMMIT");
    return { status: "available", snapshot };
  } catch (error) {
    if (db.isTransaction) {
      // sqlite-allow-raw -- Release only the diagnostic's own failed read transaction.
      db.exec("ROLLBACK");
    }
    throw error;
  }
}

function write(
  db: DatabaseSync,
  commandType: keyof OpsysPostflightOutboxOperations,
  command: OpsysPostflightOutboxOperations[keyof OpsysPostflightOutboxOperations]["input"],
): OpsysPostflightOutboxOperations[keyof OpsysPostflightOutboxOperations]["output"] {
  const table = getNodeSqliteKysely<OutboxDatabase>(db);
  if (!command || typeof command !== "object" || !Object.hasOwn(command, "now")) {
    return fail("POSTFLIGHT_COMMAND_REFUSE");
  }
  const now = nowValue(command.now);
  const lots = command as Record<string, unknown>;
  switch (commandType) {
    case "listIntents": {
      if (!exactKeys(command, ["now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      return readIntentRows(db).map(intentRowToIntent);
    }
    case "reserveIntent": {
      if (!exactKeys(command, ["intent", "now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const input = normalizeIntent(lots.intent);
      const intents = readIntentRows(db);
      if (intents.some((row) => row.fact_key === input.factKey)) {
        return fail("POSTFLIGHT_INTENT_ALREADY_RESERVED");
      }
      // A fresh call id cannot release an ambiguous M9 opening. Serialize this
      // one tool per affair; do not infer a cohort or block other departments.
      // Legacy rows and a crash before a known-response write remain fenced.
      if (
        input.outil === M9_OPEN_FOLLOWUP &&
        intents.some((row) => {
          const retained = intentRowToIntent(row);
          return (
            retained.outil === M9_OPEN_FOLLOWUP &&
            retained.affaireId === input.affaireId &&
            retained.approvalPendingRequestId === undefined
          );
        })
      ) {
        return fail("POSTFLIGHT_UNRESOLVED_INTENT");
      }
      const rows = readRows(db);
      if (
        rows.some((row) =>
          decodePayload(row.payload_json).facts.some((fact) => fact.cle === input.factKey),
        )
      ) {
        return fail("POSTFLIGHT_CLE_DEJA_UTILISEE");
      }
      if (rows.length + intents.length + 1 > MAX_LOTS) {
        return fail("POSTFLIGHT_QUOTA_LOTS");
      }
      const bytes =
        rows.reduce((sum, row) => sum + Buffer.byteLength(row.payload_json, "utf8"), 0) +
        (intents.length + 1) * INTENT_RESERVED_BYTES;
      if (bytes > MAX_BYTES) {
        return fail("POSTFLIGHT_QUOTA_BYTES");
      }
      executeSqliteQuerySync(
        db,
        table.insertInto(OPSYS_POSTFLIGHT_INTENTS_TABLE).values({
          fact_key: input.factKey,
          payload_json: JSON.stringify(input),
          state: "uncertain",
          created_at: now,
        }),
      );
      return { ...input, state: "uncertain", createdAt: now };
    }
    case "observeM9ApprovalPending": {
      if (!exactKeys(command, ["expected", "requestId", "now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const expected = normalizeIntent(lots.expected);
      if (
        expected.outil !== M9_OPEN_FOLLOWUP ||
        typeof lots.requestId !== "string" ||
        !APPROVAL_REQUEST_ID.test(lots.requestId)
      ) {
        return fail("POSTFLIGHT_APPROVAL_OBSERVATION_REFUSE");
      }
      const row = readIntentRows(db).find((entry) => entry.fact_key === expected.factKey);
      if (!row) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      const retained = decodeIntentRow(row);
      if (
        JSON.stringify(retained.input) !== JSON.stringify(expected) ||
        (retained.approvalPendingRequestId !== undefined &&
          retained.approvalPendingRequestId !== lots.requestId)
      ) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      if (retained.approvalPendingRequestId !== undefined) {
        return intentRowToIntent(row);
      }
      const payload = JSON.stringify({ ...expected, approvalPendingRequestId: lots.requestId });
      if (Buffer.byteLength(payload, "utf8") > INTENT_RESERVED_BYTES / 2) {
        return fail("POSTFLIGHT_INTENT_VALUE_REFUSE");
      }
      const updated = executeSqliteQuerySync(
        db,
        table
          .updateTable(OPSYS_POSTFLIGHT_INTENTS_TABLE)
          .set({ payload_json: payload })
          .where("fact_key", "=", expected.factKey)
          .where("payload_json", "=", row.payload_json),
      );
      if (updated.numAffectedRows !== 1n) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      // A received proposal is not a final fact, approval, or replay permission.
      return intentRowToIntent({ ...row, payload_json: payload });
    }
    case "completeIntent": {
      if (!exactKeys(command, ["expected", "fact", "now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const expected = normalizeIntent(lots.expected);
      const observed = validateFact(lots.fact);
      if (observed.cle !== expected.factKey || observed.outil !== expected.outil) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      const content = normalizeLot({
        affaireId: expected.affaireId,
        departementSource: expected.departementSource,
        profilId: expected.profilId,
        revision: expected.revision,
        engineId: expected.engineId,
        facts: [observed],
      });
      if (Buffer.byteLength(payloadFor(content), "utf8") > INTENT_RESERVED_BYTES / 2) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      const row = readIntentRows(db).find((entry) => entry.fact_key === expected.factKey);
      if (!row) {
        const existing = readRows(db).find((entry) => entry.lot_key === keyFor(content));
        if (!existing || existing.payload_json !== payloadFor(content)) {
          return fail("POSTFLIGHT_INTENT_MISMATCH");
        }
        // This acknowledges local capture only; it never authorizes a source-tool replay.
        return rowToLot(existing);
      }
      if (JSON.stringify(decodeIntentRow(row).input) !== JSON.stringify(expected)) {
        return fail("POSTFLIGHT_INTENT_MISMATCH");
      }
      executeSqliteQuerySync(
        db,
        table
          .deleteFrom(OPSYS_POSTFLIGHT_INTENTS_TABLE)
          .where("fact_key", "=", row.fact_key)
          .where("payload_json", "=", row.payload_json),
      );
      const queued = write(db, "enqueue", { lots: [content], now });
      if (!Array.isArray(queued) || queued.length !== 1 || !queued[0] || !("lot" in queued[0])) {
        return fail("POSTFLIGHT_INSERT_FAILED");
      }
      return queued[0].lot;
    }
    case "enqueue": {
      if (
        !exactKeys(command, ["lots", "now"]) ||
        !Array.isArray(lots.lots) ||
        lots.lots.length < 1 ||
        lots.lots.length > MAX_LOTS
      ) {
        return fail("POSTFLIGHT_LOT_LISTE_REFUSE");
      }
      const prepared = lots.lots.map((entry) => {
        const content = normalizeLot(entry);
        const payload = payloadFor(content);
        if (Buffer.byteLength(payload, "utf8") > MAX_BYTES) {
          return fail("POSTFLIGHT_QUOTA_BYTES");
        }
        return { content, payload, lotKey: keyFor(content) };
      });
      if (new Set(prepared.map((item) => item.lotKey)).size !== prepared.length) {
        return fail("POSTFLIGHT_LOT_DUPLICATE_REFUSE");
      }
      const batchFactKeys = prepared.flatMap((item) => item.content.facts.map((fact) => fact.cle));
      if (new Set(batchFactKeys).size !== batchFactKeys.length) {
        return fail("POSTFLIGHT_CLE_DEJA_UTILISEE");
      }
      const reservedIntents = readIntentRows(db);
      if (batchFactKeys.some((key) => reservedIntents.some((row) => row.fact_key === key))) {
        return fail("POSTFLIGHT_INTENT_ALREADY_RESERVED");
      }
      const current = readRows(db);
      const existingByKey = new Map(current.map((row) => [row.lot_key, row]));
      const existingFactKeys = new Map<string, string>();
      for (const row of current) {
        const existing = decodePayload(row.payload_json);
        for (const fact of existing.facts) {
          existingFactKeys.set(fact.cle, row.lot_key);
        }
      }
      let addCount = 0;
      let addBytes = 0;
      const results: Array<{ lot: OpsysPostflightLot; created: boolean }> = [];
      for (const item of prepared) {
        const existing = existingByKey.get(item.lotKey);
        if (existing) {
          if (existing.payload_json !== item.payload) {
            return fail("POSTFLIGHT_CLE_CONTENU_DIVERGENT");
          }
          results.push({ lot: rowToLot(existing), created: false });
          continue;
        }
        if (item.content.facts.some((fact) => existingFactKeys.has(fact.cle))) {
          return fail("POSTFLIGHT_CLE_DEJA_UTILISEE");
        }
        addCount++;
        addBytes += Buffer.byteLength(item.payload, "utf8");
      }
      const totals = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .select((eb) => [
            eb.fn.countAll<number>().as("lots"),
            eb.fn
              .coalesce(
                eb.fn.sum<number>(eb.fn<number>("length", [eb.cast("payload_json", "blob")])),
                eb.val(0),
              )
              .as("bytes"),
          ]),
      );
      if (!totals || totals.lots + reservedIntents.length + addCount > MAX_LOTS) {
        return fail("POSTFLIGHT_QUOTA_LOTS");
      }
      if (totals.bytes + reservedIntents.length * INTENT_RESERVED_BYTES + addBytes > MAX_BYTES) {
        return fail("POSTFLIGHT_QUOTA_BYTES");
      }
      for (const item of prepared) {
        if (existingByKey.has(item.lotKey)) {
          continue;
        }
        const insert: OutboxInsert = {
          lot_key: item.lotKey,
          affaire_id: item.content.affaireId,
          departement_source: item.content.departementSource,
          profil_id: item.content.profilId,
          revision_admission: item.content.revision,
          engine_id: item.content.engineId,
          payload_json: item.payload,
          state: "pending",
          attempt_count: 0,
          created_at: now,
          updated_at: now,
          next_attempt_at: now,
          last_attempt_at: null,
          last_error_code: null,
          needs_review_at: null,
        };
        executeSqliteQuerySync(db, table.insertInto(OPSYS_POSTFLIGHT_OUTBOX_TABLE).values(insert));
        const row = executeSqliteQueryTakeFirstSync(
          db,
          table
            .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
            .selectAll()
            .where("lot_key", "=", item.lotKey),
        );
        if (!row) {
          return fail("POSTFLIGHT_INSERT_FAILED");
        }
        results.push({ lot: rowToLot(row), created: true });
      }
      return results;
    }
    case "recordFailure": {
      if (
        !exactKeys(command, ["lotKey", "expected", "code", "now"]) ||
        typeof lots.code !== "string" ||
        !CODE.test(lots.code)
      ) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const expected = normalizeLot(lots.expected);
      const row = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .where("lot_key", "=", lots.lotKey as string),
      );
      if (
        !row ||
        keyFor(expected) !== row.lot_key ||
        payloadFor(expected) !== row.payload_json ||
        row.state === "needs_review"
      ) {
        return fail("POSTFLIGHT_ACK_CORRESPONDANCE_REFUSE");
      }
      if (row.attempt_count < 1) {
        return fail("POSTFLIGHT_ATTEMPT_ABSENT");
      }
      const needsReview = now - row.created_at >= MAX_AGE_MS || row.attempt_count >= 8;
      executeSqliteQuerySync(
        db,
        table
          .updateTable(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .set({
            state: needsReview ? "needs_review" : "retry",
            next_attempt_at: needsReview ? null : row.next_attempt_at,
            updated_at: now,
            last_error_code: lots.code,
            needs_review_at: needsReview ? now : null,
          })
          .where("lot_key", "=", row.lot_key)
          .where("payload_json", "=", row.payload_json),
      );
      const updated = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .where("lot_key", "=", row.lot_key),
      );
      if (!updated) {
        return fail("POSTFLIGHT_UPDATE_FAILED");
      }
      return rowToLot(updated);
    }
    case "beginAttempt": {
      if (!exactKeys(command, ["lotKey", "expected", "now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const expected = normalizeLot(lots.expected);
      const row = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .where("lot_key", "=", lots.lotKey as string),
      );
      if (!row || keyFor(expected) !== row.lot_key || payloadFor(expected) !== row.payload_json) {
        return fail("POSTFLIGHT_ACK_CORRESPONDANCE_REFUSE");
      }
      if (row.state === "needs_review") {
        return undefined;
      }
      if (now - row.created_at >= MAX_AGE_MS || row.attempt_count >= 8) {
        executeSqliteQuerySync(
          db,
          table
            .updateTable(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
            .set({
              state: "needs_review",
              next_attempt_at: null,
              needs_review_at: now,
              updated_at: now,
            })
            .where("lot_key", "=", row.lot_key),
        );
        return undefined;
      }
      if (row.next_attempt_at === null || row.next_attempt_at > now) {
        return undefined;
      }
      const attemptCount = row.attempt_count + 1;
      const delay = RETRY_DELAYS_MS[Math.min(attemptCount - 1, RETRY_DELAYS_MS.length - 1)];
      if (delay === undefined) {
        return fail("POSTFLIGHT_ROW_CORRUPT");
      }
      executeSqliteQuerySync(
        db,
        table
          .updateTable(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .set({
            state: attemptCount === 1 ? "pending" : "retry",
            attempt_count: attemptCount,
            last_attempt_at: now,
            next_attempt_at: now + delay,
            updated_at: now,
          })
          .where("lot_key", "=", row.lot_key)
          .where("payload_json", "=", row.payload_json),
      );
      const updated = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .where("lot_key", "=", row.lot_key),
      );
      return updated ? rowToLot(updated) : fail("POSTFLIGHT_UPDATE_FAILED");
    }
    case "acknowledge": {
      if (!exactKeys(command, ["lotKey", "expected", "now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      const expected = normalizeLot(lots.expected);
      const row = executeSqliteQueryTakeFirstSync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .where("lot_key", "=", lots.lotKey as string),
      );
      if (!row || keyFor(expected) !== row.lot_key || payloadFor(expected) !== row.payload_json) {
        return fail("POSTFLIGHT_ACK_CORRESPONDANCE_REFUSE");
      }
      if (row.attempt_count < 1) {
        return fail("POSTFLIGHT_ACK_ATTEMPT_ABSENT");
      }
      const deleted = executeSqliteQuerySync(
        db,
        table
          .deleteFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .where("lot_key", "=", row.lot_key)
          .where("payload_json", "=", row.payload_json),
      );
      return deleted.numAffectedRows === 1n;
    }
    case "list":
    case "listDue": {
      if (!exactKeys(command, ["now"])) {
        return fail("POSTFLIGHT_COMMAND_REFUSE");
      }
      executeSqliteQuerySync(
        db,
        table
          .updateTable(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .set({
            state: "needs_review",
            next_attempt_at: null,
            needs_review_at: now,
            updated_at: now,
          })
          .where("state", "!=", "needs_review")
          .where((eb) =>
            eb.or([eb("created_at", "<=", now - MAX_AGE_MS), eb("attempt_count", ">=", 8)]),
          ),
      );
      if (commandType === "listDue") {
        return executeSqliteQuerySync(
          db,
          table
            .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
            .selectAll()
            .where("state", "in", ["pending", "retry"])
            .where("next_attempt_at", "<=", now)
            .orderBy("created_at")
            .orderBy("lot_key"),
        ).rows.map(rowToLot);
      }
      return executeSqliteQuerySync(
        db,
        table
          .selectFrom(OPSYS_POSTFLIGHT_OUTBOX_TABLE)
          .selectAll()
          .orderBy("created_at")
          .orderBy("lot_key"),
      ).rows.map(rowToLot);
    }
    default:
      return fail("POSTFLIGHT_COMMAND_REFUSE");
  }
}

export function bindSqliteWorkerBackend(
  _input: undefined,
  context: {
    databasePath: string;
    database: DatabaseSync;
    admit(stage: "transaction" | "commit"): void;
  },
): SqliteWorkerBackend<OpsysPostflightOutboxOperations> {
  const db = context.database;
  return {
    execute(command) {
      return runSqliteImmediateTransactionSync(
        db,
        () => {
          context.admit("transaction");
          ensureSchema(db);
          return write(db, command.type, command.input);
        },
        {
          operationLabel: `opsys.postflight.outbox.${command.type}`,
          busyTimeoutMs: OPENCLAW_SQLITE_BUSY_TIMEOUT_MS,
          databaseLabel: context.databasePath,
          withCommit(commit) {
            context.admit("commit");
            commit();
          },
        },
      );
    },
    assertSettled() {
      assertTransactionUsable(db);
      if (db.isTransaction) {
        throw new Error("Postflight outbox transaction did not settle");
      }
    },
    close() {},
  };
}
