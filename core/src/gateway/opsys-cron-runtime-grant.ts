import { isDeepStrictEqual } from "node:util";
import { createTrustedCronScheduledToolPolicy } from "../cron/scheduled-tool-policy.js";
import {
  OPSYS_CRON_AUTHORITY_NAMESPACE,
  OPSYS_CRON_AUTHORITY_RUNTIME_ID,
} from "../cron/store/opsys-runtime-authority-crypto.js";
import type { CronJob, CronJobCreate } from "../cron/types.js";
import type { CronDeclaration } from "./opsys-cron-private-client.js";

export const OPSYS_CRON_RUNTIME_AUTHORITY_RUNTIME = OPSYS_CRON_AUTHORITY_RUNTIME_ID;
export const OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE = OPSYS_CRON_AUTHORITY_NAMESPACE;

export type OpsysCronRuntimeDeclaration = Readonly<{
  wire: CronDeclaration;
  cron: CronJobCreate;
}>;

export type OpsysCronRuntimeGrant = Readonly<{
  capability: string;
  epoch: number;
  leaseEpoch: number;
  intentionId: string;
  profileId: string;
  profileRevision: number;
  declaration: OpsysCronRuntimeDeclaration;
}>;

export type OpsysCronRuntimeGrantExpectation = Readonly<{
  profileId?: string;
  intentionId?: string;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

/** Decode the single supported human declaration into JSON wire and CronService forms. */
export function decodeOpsysCronRuntimeDeclaration(
  value: unknown,
  profileId: string,
  intentionId: string,
  profileRevision: number,
): OpsysCronRuntimeDeclaration | undefined {
  if (
    !/^[a-z][a-z0-9-]{1,63}$/u.test(profileId) ||
    !/^[a-f0-9]{64}$/u.test(intentionId) ||
    !Number.isSafeInteger(profileRevision) ||
    profileRevision < 1 ||
    !isRecord(value) ||
    !hasExactKeys(value, [
      "name",
      "declarationKey",
      "agentId",
      "sessionTarget",
      "wakeMode",
      "schedule",
      "payload",
      "delivery",
    ])
  ) {
    return undefined;
  }
  const schedule = value.schedule;
  const payload = value.payload;
  const delivery = value.delivery;
  if (
    !isRecord(schedule) ||
    !hasExactKeys(schedule, ["kind", "expr", "tz"]) ||
    schedule.kind !== "cron" ||
    typeof schedule.expr !== "string" ||
    typeof schedule.tz !== "string" ||
    !isRecord(payload) ||
    !hasExactKeys(payload, ["kind", "message", "timeoutSeconds", "toolsAllow"]) ||
    payload.kind !== "agentTurn" ||
    typeof payload.message !== "string" ||
    payload.message !==
      `Exécute le mandat interne canonique du profil ${profileId}, révision ${profileRevision}.` ||
    payload.timeoutSeconds !== 120 ||
    !Array.isArray(payload.toolsAllow) ||
    !payload.toolsAllow.every((tool): tool is string => typeof tool === "string") ||
    !isRecord(delivery) ||
    !hasExactKeys(delivery, ["mode"]) ||
    delivery.mode !== "none" ||
    value.name !== `OPSYS profil ${profileId}` ||
    value.declarationKey !== `opsys-profile:${intentionId}` ||
    value.agentId !== `opsys-agent-${profileId}` ||
    value.sessionTarget !== "isolated" ||
    value.wakeMode !== "now"
  ) {
    return undefined;
  }
  const toolsAllow = [...payload.toolsAllow];
  const wire: CronDeclaration = {
    name: `OPSYS profil ${profileId}`,
    declarationKey: `opsys-profile:${intentionId}`,
    agentId: `opsys-agent-${profileId}`,
    sessionTarget: "isolated",
    wakeMode: "now",
    schedule: { kind: "cron", expr: schedule.expr, tz: schedule.tz },
    payload: { kind: "agentTurn", message: payload.message, timeoutSeconds: 120, toolsAllow },
    delivery: { mode: "none" },
  };
  const cron: CronJobCreate = {
    enabled: false,
    name: `OPSYS profil ${profileId}`,
    declarationKey: `opsys-profile:${intentionId}`,
    agentId: `opsys-agent-${profileId}`,
    sessionTarget: "isolated",
    wakeMode: "now",
    schedule: { kind: "cron", expr: schedule.expr, tz: schedule.tz },
    payload: { kind: "agentTurn", message: payload.message, timeoutSeconds: 120, toolsAllow },
    delivery: { mode: "none" },
  };
  return { wire, cron };
}

function revisionFromDeclaration(value: unknown, profileId: string): number | undefined {
  if (!isRecord(value) || !isRecord(value.payload) || typeof value.payload.message !== "string") {
    return undefined;
  }
  const match = new RegExp(
    `^Exécute le mandat interne canonique du profil ${profileId}, révision ([1-9][0-9]*)\\.$`,
    "u",
  ).exec(value.payload.message);
  if (!match?.[1]) {
    return undefined;
  }
  const revision = Number(match[1]);
  return Number.isSafeInteger(revision) && revision > 0 ? revision : undefined;
}

/** Read and validate the decrypted CronService sidecar; rejects malformed or foreign grants. */
export function decodeOpsysCronRuntimeGrant(
  job: CronJob,
  expected: OpsysCronRuntimeGrantExpectation = {},
): OpsysCronRuntimeGrant | undefined {
  const value: unknown = job;
  if (!isRecord(value) || value.runtimeAuthorityRecoveryRequired === true) {
    return undefined;
  }
  return decodeOpsysCronRuntimeAuthority(value.runtimeAuthority, expected);
}

/** Same private decoder for an encrypted retirement receipt; no fake live job is constructed. */
export function decodeOpsysCronRuntimeAuthority(
  authority: unknown,
  expected: OpsysCronRuntimeGrantExpectation = {},
): OpsysCronRuntimeGrant | undefined {
  if (
    !isRecord(authority) ||
    !hasExactKeys(authority, ["version", "runtimeId", "namespace", "payload"]) ||
    authority.version !== 1 ||
    authority.runtimeId !== OPSYS_CRON_RUNTIME_AUTHORITY_RUNTIME ||
    authority.namespace !== OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE ||
    !isRecord(authority.payload)
  ) {
    return undefined;
  }
  const payload = authority.payload;
  if (
    !hasExactKeys(payload, [
      "version",
      "profil_id",
      "intention_id",
      "epoch",
      "lease_epoch",
      "capabilite",
      "declaration",
    ]) ||
    payload.version !== 1 ||
    typeof payload.profil_id !== "string" ||
    !/^[a-z][a-z0-9-]{1,63}$/u.test(payload.profil_id) ||
    typeof payload.intention_id !== "string" ||
    !/^[a-f0-9]{64}$/u.test(payload.intention_id) ||
    typeof payload.epoch !== "number" ||
    !Number.isSafeInteger(payload.epoch) ||
    payload.epoch < 1 ||
    typeof payload.lease_epoch !== "number" ||
    !Number.isSafeInteger(payload.lease_epoch) ||
    payload.lease_epoch < 1 ||
    typeof payload.capabilite !== "string" ||
    !/^[a-f0-9]{64}$/u.test(payload.capabilite) ||
    !isRecord(payload.declaration)
  ) {
    return undefined;
  }
  if (
    (expected.profileId !== undefined && expected.profileId !== payload.profil_id) ||
    (expected.intentionId !== undefined && expected.intentionId !== payload.intention_id)
  ) {
    return undefined;
  }
  const profileRevision = revisionFromDeclaration(payload.declaration, payload.profil_id);
  if (profileRevision === undefined) {
    return undefined;
  }
  const declaration = decodeOpsysCronRuntimeDeclaration(
    payload.declaration,
    payload.profil_id,
    payload.intention_id,
    profileRevision,
  );
  if (!declaration) {
    return undefined;
  }
  return {
    capability: payload.capabilite,
    epoch: payload.epoch,
    leaseEpoch: payload.lease_epoch,
    intentionId: payload.intention_id,
    profileId: payload.profil_id,
    profileRevision,
    declaration,
  };
}

/** Compare only the supported canonical fields, allowing CronService's derived cron stagger. */
export function opsysCronRuntimeDeclarationMatchesJob(
  declaration: CronJobCreate,
  job: CronJob,
): boolean {
  const unsupportedConfigKeys = [
    "description",
    "deleteAfterRun",
    "sessionKey",
    "pacing",
    "failureAlert",
    "owner",
    "trigger",
    "displayName",
    "toolsAllowProvenance",
    "toolsAllowExecTarget",
    "toolsAllowExecTargetRequirement",
    "createdActor",
    "skillLibrarySelections",
  ];
  if (unsupportedConfigKeys.some((key) => Reflect.get(job, key) !== undefined)) {
    return false;
  }
  if (!isDeepStrictEqual(job.scheduledToolPolicy, createTrustedCronScheduledToolPolicy())) {
    return false;
  }
  return isDeepStrictEqual(
    {
      name: job.name,
      declarationKey: job.declarationKey,
      agentId: job.agentId,
      sessionTarget: job.sessionTarget,
      wakeMode: job.wakeMode,
      schedule: {
        kind: job.schedule.kind,
        expr: job.schedule.kind === "cron" ? job.schedule.expr : undefined,
        tz: job.schedule.kind === "cron" ? job.schedule.tz : undefined,
      },
      payload: job.payload,
      delivery: job.delivery,
    },
    {
      name: declaration.name,
      declarationKey: declaration.declarationKey,
      agentId: declaration.agentId,
      sessionTarget: declaration.sessionTarget,
      wakeMode: declaration.wakeMode,
      schedule: {
        kind: declaration.schedule.kind,
        expr: declaration.schedule.kind === "cron" ? declaration.schedule.expr : undefined,
        tz: declaration.schedule.kind === "cron" ? declaration.schedule.tz : undefined,
      },
      payload: declaration.payload,
      delivery: declaration.delivery,
    },
  );
}
