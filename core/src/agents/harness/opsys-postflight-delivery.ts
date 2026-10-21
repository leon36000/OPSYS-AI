import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import type {
  OpenClawAgentDatabase,
  OpenClawAgentDatabaseOptions,
} from "../../state/openclaw-agent-db-contract.js";
import {
  acknowledgeOpsysPostflightLot,
  beginOpsysPostflightAttempt,
  failOpsysPostflightAttempt,
  listDueOpsysPostflightLots,
  type OpsysPostflightLot,
  type OpsysPostflightLotInput,
} from "./opsys-postflight-outbox.js";

const MAX_LOTS_PER_PASS = 4;
const DELIVERY_TOOL = "opsys_runtime_deposer_faits";
const PROFILE_ID = /^[a-z][a-z0-9-]{1,63}$/u;
const DEPARTMENT_ID = /^m(0[1-9]|10)-[a-z][a-z0-9-]*$/u;

type DeliveryFailureCode =
  | "M10-POSTFLIGHT-INDISPONIBLE"
  | "M10-POSTFLIGHT-REPONSE-INVALIDE"
  | "M10-POSTFLIGHT-AUTORITE-REVOQUEE"
  | "M10-POSTFLIGHT-INTERRUPPU";

export type OpsysPostflightDeliveryProfile = Readonly<{
  id: string;
  revision: number;
  departement: string;
}>;

/** Narrow store seam for deterministic behavior tests; production binds it to the canonical outbox. */
export type OpsysPostflightDeliveryStore = Readonly<{
  listDue(now: number): Promise<OpsysPostflightLot[]>;
  beginAttempt(
    lotKey: string,
    expected: OpsysPostflightLotInput,
    now: number,
  ): Promise<OpsysPostflightLot | undefined>;
  fail(
    lotKey: string,
    expected: OpsysPostflightLotInput,
    code: string,
    now: number,
  ): Promise<OpsysPostflightLot>;
  acknowledge(lotKey: string, expected: OpsysPostflightLotInput, now: number): Promise<boolean>;
}>;

export type OpsysPostflightDeliveryDeps = Readonly<{
  store?: OpsysPostflightDeliveryStore;
  callTool?: typeof callOpsysMcpTool;
}>;

export type OpsysPostflightDeliveryResult = Readonly<{
  selected: number;
  attempted: number;
  delivered: number;
  failed: number;
  acknowledgementFailures: number;
}>;

function validProfile(profile: OpsysPostflightDeliveryProfile): boolean {
  return (
    PROFILE_ID.test(profile.id) &&
    Number.isSafeInteger(profile.revision) &&
    profile.revision > 0 &&
    DEPARTMENT_ID.test(profile.departement)
  );
}

function matchesProfile(lot: OpsysPostflightLot, profile: OpsysPostflightDeliveryProfile): boolean {
  return (
    lot.engineId === "opsys" &&
    lot.profilId === profile.id &&
    lot.revision === profile.revision &&
    lot.departementSource === profile.departement
  );
}

function expectedPayload(lot: OpsysPostflightLot): OpsysPostflightLotInput {
  return {
    affaireId: lot.affaireId,
    departementSource: lot.departementSource,
    profilId: lot.profilId,
    revision: lot.revision,
    engineId: lot.engineId,
    facts: lot.facts,
  };
}

function samePayload(left: OpsysPostflightLot, right: OpsysPostflightLot): boolean {
  return (
    left.affaireId === right.affaireId &&
    left.departementSource === right.departementSource &&
    left.profilId === right.profilId &&
    left.revision === right.revision &&
    left.engineId === right.engineId &&
    left.facts.length === right.facts.length &&
    left.facts.every((fact, index) => {
      const other = right.facts[index];
      return (
        other !== undefined &&
        fact.cle === other.cle &&
        fact.outil === other.outil &&
        fact.resultat === other.resultat &&
        fact.code === other.code
      );
    })
  );
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).toSorted();
  return (
    actual.length === keys.length && actual.every((key, index) => key === keys.toSorted()[index])
  );
}

function readAcknowledgement(envelope: unknown, lot: OpsysPostflightLotInput): boolean {
  if (!isRecord(envelope) || !exactKeys(envelope, ["ok", "resultat"]) || envelope.ok !== true) {
    return false;
  }
  const answer = envelope.resultat;
  if (
    !isRecord(answer) ||
    !exactKeys(answer, ["accepte", "source", "affaire_id", "cles", "resultat"]) ||
    answer.accepte !== true ||
    answer.affaire_id !== lot.affaireId
  ) {
    return false;
  }
  const source = answer.source;
  if (
    !isRecord(source) ||
    !exactKeys(source, ["profil_id", "revision", "departement", "engine_id"]) ||
    source.profil_id !== lot.profilId ||
    source.revision !== lot.revision ||
    source.departement !== lot.departementSource ||
    source.engine_id !== "opsys"
  ) {
    return false;
  }
  if (
    !Array.isArray(answer.cles) ||
    answer.cles.length !== lot.facts.length ||
    !answer.cles.every((key, index) => key === lot.facts[index]?.cle)
  ) {
    return false;
  }
  const result = answer.resultat;
  if (!isRecord(result) || !exactKeys(result, ["ecrits", "deja_deposes", "lignes"])) {
    return false;
  }
  const ecrits = result.ecrits;
  const dejaDeposes = result.deja_deposes;
  const lignes = result.lignes;
  if (
    typeof ecrits !== "number" ||
    typeof dejaDeposes !== "number" ||
    !Number.isSafeInteger(ecrits) ||
    !Number.isSafeInteger(dejaDeposes) ||
    ecrits < 0 ||
    dejaDeposes < 0 ||
    ecrits + dejaDeposes !== lot.facts.length ||
    !Array.isArray(lignes) ||
    lignes.length !== ecrits ||
    !lignes.every((line) => typeof line === "string" && line.length > 0)
  ) {
    return false;
  }
  return true;
}

function assertDeliveryCurrent(assertCurrent: () => void): void {
  try {
    assertCurrent();
  } catch {
    throw new Error("POSTFLIGHT_AUTHORITY_REVOKED");
  }
}

function failureCode(signal: AbortSignal, cause: unknown): DeliveryFailureCode {
  if (signal.aborted) {
    return "M10-POSTFLIGHT-INTERRUPPU";
  }
  if (cause instanceof Error && cause.message === "POSTFLIGHT_AUTHORITY_REVOKED") {
    return "M10-POSTFLIGHT-AUTORITE-REVOQUEE";
  }
  return "M10-POSTFLIGHT-INDISPONIBLE";
}

/** Sends at most four due lots to the profile-bound private runtime route. */
export async function deliverOpsysPostflightLots(
  params: {
    database: OpenClawAgentDatabase;
    options: OpenClawAgentDatabaseOptions;
    config: OpenClawConfig | undefined;
    timeoutMs: number;
    profile: OpsysPostflightDeliveryProfile;
    assertCurrent: () => void;
    signal: AbortSignal;
    nowMs: () => number;
  },
  deps: OpsysPostflightDeliveryDeps = {},
): Promise<OpsysPostflightDeliveryResult> {
  if (!validProfile(params.profile)) {
    throw new Error("POSTFLIGHT_PROFILE_REFUSE");
  }
  if (
    !Number.isSafeInteger(params.timeoutMs) ||
    params.timeoutMs < 100 ||
    params.timeoutMs > 30_000
  ) {
    throw new Error("POSTFLIGHT_TIMEOUT_REFUSE");
  }
  const now = () => {
    const value = params.nowMs();
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new Error("POSTFLIGHT_CLOCK_REFUSE");
    }
    return value;
  };
  const store: OpsysPostflightDeliveryStore = deps.store ?? {
    listDue: async (at) =>
      await listDueOpsysPostflightLots({
        database: params.database,
        options: params.options,
        now: at,
        assertCurrent: params.assertCurrent,
      }),
    beginAttempt: async (lotKey, expected, at) =>
      await beginOpsysPostflightAttempt({
        database: params.database,
        options: params.options,
        lotKey,
        expected,
        now: at,
        assertCurrent: params.assertCurrent,
      }),
    fail: async (lotKey, expected, code, at) =>
      await failOpsysPostflightAttempt({
        database: params.database,
        options: params.options,
        lotKey,
        expected,
        code,
        now: at,
        assertCurrent: params.assertCurrent,
      }),
    acknowledge: async (lotKey, expected, at) =>
      await acknowledgeOpsysPostflightLot({
        database: params.database,
        options: params.options,
        lotKey,
        expected,
        now: at,
        assertCurrent: params.assertCurrent,
      }),
  };
  const callTool = deps.callTool ?? callOpsysMcpTool;
  params.assertCurrent();
  if (params.signal.aborted) {
    return Object.freeze({
      selected: 0,
      attempted: 0,
      delivered: 0,
      failed: 0,
      acknowledgementFailures: 0,
    });
  }
  const due = await store.listDue(now());
  const selected = due
    .filter((lot) => matchesProfile(lot, params.profile))
    .slice(0, MAX_LOTS_PER_PASS);
  let attempted = 0;
  let delivered = 0;
  let failed = 0;
  let acknowledgementFailures = 0;

  for (const lot of selected) {
    if (params.signal.aborted) {
      break;
    }
    const expected = expectedPayload(lot);
    params.assertCurrent();
    if (params.signal.aborted) {
      break;
    }
    let attempt: OpsysPostflightLot | undefined;
    try {
      attempt = await store.beginAttempt(lot.lotKey, expected, now());
    } catch {
      failed += 1;
      continue;
    }
    if (!attempt) {
      continue;
    }
    if (
      attempt.lotKey !== lot.lotKey ||
      !samePayload(attempt, lot) ||
      attempt.attemptCount < 1 ||
      (attempt.state !== "pending" && attempt.state !== "retry")
    ) {
      failed += 1;
      continue;
    }
    attempted += 1;

    let envelope: unknown;
    try {
      assertDeliveryCurrent(params.assertCurrent);
      if (params.signal.aborted) {
        throw new Error("POSTFLIGHT_ABORTED");
      }
      const timestamp = new Date(now()).toISOString().replace("Z", "+00:00");
      envelope = await callTool({
        config: params.config,
        server: `opsys_runtime_${params.profile.id}`,
        tool: DELIVERY_TOOL,
        args: {
          affaire_id: lot.affaireId,
          faits: lot.facts,
          horodatage: timestamp,
          revision_profil: params.profile.revision,
        },
        timeoutMs: params.timeoutMs,
        signal: params.signal,
      });
      assertDeliveryCurrent(params.assertCurrent);
      if (params.signal.aborted) {
        throw new Error("POSTFLIGHT_ABORTED");
      }
    } catch (cause) {
      const code = failureCode(params.signal, cause);
      await recordFailure(store, lot, expected, code, now, () => {
        failed += 1;
      });
      continue;
    }

    if (!readAcknowledgement(envelope, expected)) {
      await recordFailure(store, lot, expected, "M10-POSTFLIGHT-REPONSE-INVALIDE", now, () => {
        failed += 1;
      });
      continue;
    }

    try {
      const removed = await store.acknowledge(lot.lotKey, expected, now());
      if (removed) {
        delivered += 1;
      } else {
        acknowledgementFailures += 1;
      }
    } catch {
      acknowledgementFailures += 1;
    }
  }

  return Object.freeze({
    selected: selected.length,
    attempted,
    delivered,
    failed,
    acknowledgementFailures,
  });
}

async function recordFailure(
  store: OpsysPostflightDeliveryStore,
  lot: OpsysPostflightLot,
  expected: OpsysPostflightLotInput,
  code: DeliveryFailureCode,
  now: () => number,
  onFailure: () => void,
): Promise<void> {
  try {
    await store.fail(lot.lotKey, expected, code, now());
  } catch {
    // beginAttempt has already reserved a retry time; a later pass can safely replay the same key.
  }
  onFailure();
}
