import { createHash } from "node:crypto";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import { cancelUnreadResponseBody, readResponseWithLimit } from "../infra/http-body.js";
import { registerSecretValueForRedaction } from "../logging/secret-redaction-registry.js";

const PREFIX = "/cron-operateur/v1/";
const MAX_BODY_BYTES = 20 * 1024;
const MAX_OWNER_INTENTS = 16;
const REQUEST_TIMEOUT_MS = 5_000;
const HEX64 = /^[0-9a-f]{64}$/u;
const PROFILE = /^[a-z][a-z0-9-]{1,63}$/u;
const JOB = /^[A-Za-z0-9._:-]{1,128}$/u;
const CORE_REVISION = /^sha256:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/u;

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type NativeRevision = number | string;
export type CronDeclaration = Record<string, JsonValue>;
export type CronIntent = Readonly<{
  intention_id: string;
  etat: "a_declarer" | "a_retirer";
  revision_profil: number;
  fuseau: string;
}>;
export type CronList = Readonly<{
  total: number;
  retournes: number;
  omis: number;
  items: readonly CronIntent[];
}>;
export type CronProjection = Readonly<{
  intention: string;
  etat: "a_declarer" | "a_retirer";
  execute: false;
  native: null | Readonly<{ method: "cron.add"; params: CronDeclaration }>;
  declaration_key?: string;
  reconciliation?: "rechercher_id_natif_puis_retirer";
}>;
export type CronGrantStatus = Readonly<{
  intention: string;
  epoch: number;
  lease_epoch: number;
  etat: "preparation" | "remise" | "revoquee";
  job_id: string | null;
  config_revision: NativeRevision | null;
  execute: false;
}>;
export type CronPreparation = CronGrantStatus &
  Readonly<{
    lease_until: string;
    revision_native_attendue: NativeRevision | null;
    native: Readonly<{ method: "cron.add"; params: CronDeclaration }>;
  }>;

export type CronPrivateClientOptions = Readonly<{
  healthUrl: string;
  operatorToken: string;
  publicMcpToken: string;
  contextToken?: string;
  fetchImpl?: typeof fetch;
}>;

export type PrepareCronGrant = Readonly<{
  capabilityFingerprint: string;
  declaration: CronDeclaration;
  expectedEpoch: number;
  expectedNativeRevision: NativeRevision | null;
  leaseSeconds: number;
}>;
export type AcknowledgeCronGrant = Readonly<{
  intentionId: string;
  capability: string;
  epoch: number;
  leaseEpoch: number;
  jobId: string;
  configRevision: NativeRevision;
  declaration: CronDeclaration;
}>;
export type ValidateCronGrant = Omit<AcknowledgeCronGrant, "leaseEpoch">;
export type RenewCronGrant = Readonly<{
  intentionId: string;
  capability: string;
  epoch: number;
  leaseEpoch: number;
  declaration: CronDeclaration;
  leaseSeconds: number;
}>;

/** Host-only cleanup input: nativeRevision is the disabled job CAS, not its old activation ACK. */
export type PrepareCronRetirement = Readonly<{
  intentionId: string;
  capability: string;
  epoch: number;
  jobId: string;
  nativeRevision: string;
  declaration: CronDeclaration;
}>;
export type AcknowledgeCronRetirement = PrepareCronRetirement &
  Readonly<{
    sourceHash: string;
    receiptId: string;
  }>;
export type CronRetirementPreparation = Readonly<{
  version: 1;
  intention: string;
  source_hash: string;
  epoch: number;
  job_id: string;
  native_revision: string;
  declaration_hash: string;
  declaration_key: string;
  receipt_id: string;
  execute: false;
}>;
export type CronRetirementAcknowledgement = Readonly<{
  intention: string;
  receipt_id: string;
  source_hash: string;
  epoch: number;
  job_id: string;
  etat: "retiree";
  execute: false;
}>;

export class OpsysCronPrivateClientError extends Error {
  constructor(readonly kind: "configuration" | "refused" | "unavailable") {
    super(
      kind === "configuration"
        ? "Cron privé indisponible: configuration refusée"
        : kind === "refused"
          ? "Cron privé a refusé l’opération"
          : "Cron privé indisponible ou réponse invalide",
    );
    this.name = "OpsysCronPrivateClientError";
  }
}

function fail(kind: OpsysCronPrivateClientError["kind"]): never {
  throw new OpsysCronPrivateClientError(kind);
}

function closedConfiguration<T>(read: () => T): T {
  try {
    return read();
  } catch {
    fail("configuration");
  }
}

async function closedOperation<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    // Never forward caller-controlled getter/serialization/transport error text.
    fail(error instanceof OpsysCronPrivateClientError ? error.kind : "configuration");
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return (
    record(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}

function positive(value: unknown, allowZero = false): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= (allowZero ? 0 : 1) &&
    value <= 2 ** 31 - 1
  );
}

function revision(value: unknown, nullable = false): value is NativeRevision | null {
  if (nullable && value === null) return true;
  return positive(value) || (typeof value === "string" && CORE_REVISION.test(value));
}

function validJob(value: unknown): value is string {
  return typeof value === "string" && JOB.test(value);
}

function validToken(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 24 &&
    value.length <= 4096 &&
    !/[\s\u0000-\u001f\u007f-\u009f]/u.test(value)
  );
}

function validateProfile(profileId: string): void {
  if (typeof profileId !== "string" || !PROFILE.test(profileId)) fail("configuration");
}

function validateIntent(intentId: string): void {
  if (typeof intentId !== "string" || !HEX64.test(intentId)) fail("configuration");
}

function validateJson(
  value: unknown,
  depth = 0,
  state = { nodes: 0, bytes: 0 },
): value is JsonValue {
  state.nodes += 1;
  if (state.nodes > 512 || depth > 8) return false;
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "string") {
    state.bytes += Buffer.byteLength(value, "utf8");
    return state.bytes <= 16 * 1024;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value))
    return value.length <= 512 && value.every((item) => validateJson(item, depth + 1, state));
  if (record(value)) {
    const entries = Object.entries(value);
    if (entries.length > 512) return false;
    for (const [key, item] of entries) {
      state.bytes += Buffer.byteLength(key, "utf8");
      if (state.bytes > 16 * 1024 || !validateJson(item, depth + 1, state)) return false;
    }
    return true;
  }
  return false;
}

function jsonObject(value: unknown): value is CronDeclaration {
  return record(value) && validateJson(value);
}

function validateRevision(value: NativeRevision | null, nullable: boolean): void {
  if (!revision(value, nullable)) fail("configuration");
}

function snapshotDeclaration(value: unknown): CronDeclaration {
  try {
    if (!record(value) || !validateJson(value)) fail("configuration");
    const encoded = JSON.stringify(value);
    if (typeof encoded !== "string" || Buffer.byteLength(encoded, "utf8") > 16 * 1024)
      fail("configuration");
    const snapshot = parseStrictJson(encoded);
    if (!jsonObject(snapshot)) fail("configuration");
    return snapshot;
  } catch {
    fail("configuration");
  }
}

function validateEndpoint(healthUrl: string): string {
  let url: URL;
  try {
    url = new URL(healthUrl);
  } catch {
    return fail("configuration");
  }
  const host = url.hostname.toLowerCase();
  if (
    url.protocol !== "http:" ||
    url.username ||
    url.password ||
    url.pathname !== "/sante" ||
    url.search ||
    url.hash ||
    !["127.0.0.1", "localhost", "[::1]", "::1"].includes(host) ||
    !url.port
  ) {
    return fail("configuration");
  }
  return url.origin;
}

function validLease(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00$/u.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function parseStrictJson(text: string): unknown {
  let offset = 0;
  let nodes = 0;
  const whitespace = () => {
    while ([" ", "\t", "\r", "\n"].includes(text[offset] ?? "")) offset += 1;
  };
  const parseString = (): string => {
    const start = offset;
    if (text[offset] !== '"') throw new Error("invalid JSON");
    offset += 1;
    while (offset < text.length) {
      const code = text.charCodeAt(offset);
      if (code === 0x22) {
        offset += 1;
        return JSON.parse(text.slice(start, offset)) as string;
      }
      if (code < 0x20) throw new Error("invalid JSON");
      if (code === 0x5c) offset += 1;
      offset += 1;
    }
    throw new Error("invalid JSON");
  };
  const value = (depth: number): unknown => {
    whitespace();
    nodes += 1;
    if (depth > 32 || nodes > 10_000) throw new Error("invalid JSON");
    const ch = text[offset];
    if (ch === '"') return parseString();
    if (ch === "{") {
      offset += 1;
      whitespace();
      const out: Record<string, unknown> = {};
      const keys = new Set<string>();
      if (text[offset] === "}") {
        offset += 1;
        return out;
      }
      while (offset < text.length) {
        whitespace();
        const key = parseString();
        whitespace();
        if (keys.has(key) || text[offset] !== ":") throw new Error("invalid JSON");
        keys.add(key);
        offset += 1;
        Object.defineProperty(out, key, {
          value: value(depth + 1),
          enumerable: true,
          configurable: true,
          writable: true,
        });
        whitespace();
        if (text[offset] === "}") {
          offset += 1;
          return out;
        }
        if (text[offset] !== ",") throw new Error("invalid JSON");
        offset += 1;
      }
      throw new Error("invalid JSON");
    }
    if (ch === "[") {
      offset += 1;
      whitespace();
      const out: unknown[] = [];
      if (text[offset] === "]") {
        offset += 1;
        return out;
      }
      while (offset < text.length) {
        out.push(value(depth + 1));
        whitespace();
        if (text[offset] === "]") {
          offset += 1;
          return out;
        }
        if (text[offset] !== ",") throw new Error("invalid JSON");
        offset += 1;
      }
      throw new Error("invalid JSON");
    }
    for (const [literal, parsed] of [
      ["true", true],
      ["false", false],
      ["null", null],
    ] as const) {
      if (text.startsWith(literal, offset)) {
        offset += literal.length;
        return parsed;
      }
    }
    const number = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/u.exec(text.slice(offset));
    if (number) {
      offset += number[0].length;
      const parsed = Number(number[0]);
      if (!Number.isFinite(parsed)) throw new Error("invalid JSON");
      return parsed;
    }
    throw new Error("invalid JSON");
  };
  const parsed = value(0);
  whitespace();
  if (offset !== text.length) throw new Error("invalid JSON");
  return parsed;
}

function parseIntent(value: unknown): CronIntent | undefined {
  if (!exact(value, ["intention_id", "etat", "revision_profil", "fuseau"])) return;
  if (
    typeof value.intention_id !== "string" ||
    !HEX64.test(value.intention_id) ||
    (value.etat !== "a_declarer" && value.etat !== "a_retirer") ||
    !positive(value.revision_profil) ||
    typeof value.fuseau !== "string" ||
    !value.fuseau ||
    Buffer.byteLength(value.fuseau, "utf8") > 64
  )
    return;
  return {
    intention_id: value.intention_id,
    etat: value.etat,
    revision_profil: value.revision_profil,
    fuseau: value.fuseau,
  };
}

function parseProjection(value: unknown, intentionId: string): CronProjection | undefined {
  if (
    !record(value) ||
    value.intention !== intentionId ||
    (value.etat !== "a_declarer" && value.etat !== "a_retirer") ||
    value.execute !== false
  )
    return;
  if (value.etat === "a_retirer") {
    if (
      !exact(value, [
        "intention",
        "etat",
        "execute",
        "declaration_key",
        "reconciliation",
        "native",
      ]) ||
      value.declaration_key !== `opsys-profile:${intentionId}` ||
      value.reconciliation !== "rechercher_id_natif_puis_retirer" ||
      value.native !== null
    )
      return;
    return {
      intention: value.intention,
      etat: "a_retirer",
      execute: false,
      native: null,
      declaration_key: value.declaration_key,
      reconciliation: "rechercher_id_natif_puis_retirer",
    };
  }
  if (
    !exact(value, ["intention", "etat", "execute", "native"]) ||
    !record(value.native) ||
    !exact(value.native, ["method", "params"]) ||
    value.native.method !== "cron.add" ||
    !record(value.native.params) ||
    !jsonObject(value.native.params) ||
    Buffer.byteLength(JSON.stringify(value.native.params), "utf8") > 16 * 1024
  )
    return;
  return {
    intention: value.intention,
    etat: "a_declarer",
    execute: false,
    native: { method: "cron.add", params: value.native.params },
  };
}

function parseStatus(value: unknown): CronGrantStatus | undefined {
  if (
    !exact(value, [
      "intention",
      "epoch",
      "lease_epoch",
      "etat",
      "job_id",
      "config_revision",
      "execute",
    ]) ||
    typeof value.intention !== "string" ||
    !HEX64.test(value.intention) ||
    !positive(value.epoch) ||
    !positive(value.lease_epoch) ||
    (value.etat !== "preparation" && value.etat !== "remise" && value.etat !== "revoquee") ||
    (value.job_id !== null && !validJob(value.job_id)) ||
    !revision(value.config_revision, true) ||
    value.execute !== false
  )
    return;
  return {
    intention: value.intention,
    epoch: value.epoch,
    lease_epoch: value.lease_epoch,
    etat: value.etat,
    job_id: value.job_id,
    config_revision: value.config_revision,
    execute: false,
  };
}

/** Direct private HTTP client for the authenticated Python Cron owner; it never dispatches jobs. */
export class OpsysCronPrivateClient {
  readonly #origin: string;
  readonly #token: string;
  readonly #fetch: typeof fetch;

  constructor(options: CronPrivateClientOptions) {
    options = closedConfiguration(() => ({
      healthUrl: options.healthUrl,
      operatorToken: options.operatorToken,
      publicMcpToken: options.publicMcpToken,
      contextToken: options.contextToken,
      fetchImpl: options.fetchImpl,
    }));
    this.#origin = validateEndpoint(options.healthUrl);
    if (
      !validToken(options.operatorToken) ||
      !validToken(options.publicMcpToken) ||
      (options.contextToken !== undefined && !validToken(options.contextToken)) ||
      options.operatorToken === options.publicMcpToken ||
      (options.contextToken !== undefined &&
        (options.contextToken === options.operatorToken ||
          options.contextToken === options.publicMcpToken))
    ) {
      fail("configuration");
    }
    this.#token = options.operatorToken;
    this.#fetch = options.fetchImpl ?? fetch;
    registerSecretValueForRedaction(this.#token);
  }

  async list(profileId: string): Promise<CronList> {
    return await closedOperation(async () => {
      validateProfile(profileId);
      const result = await this.#post(profileId, "lire", {});
      if (
        !exact(result, ["total", "retournes", "omis", "items"]) ||
        !positive(result.total, true) ||
        !positive(result.retournes, true) ||
        !positive(result.omis, true) ||
        !Array.isArray(result.items) ||
        result.items.length !== result.retournes ||
        result.total !== result.retournes + result.omis ||
        result.total > MAX_OWNER_INTENTS ||
        result.omis !== 0 ||
        result.items.length > MAX_OWNER_INTENTS
      )
        fail("unavailable");
      const items: CronIntent[] = [];
      const seen = new Set<string>();
      for (const raw of result.items) {
        const item = parseIntent(raw);
        if (!item || seen.has(item.intention_id)) fail("unavailable");
        seen.add(item.intention_id);
        items.push(item);
      }
      return { total: result.total, retournes: result.retournes, omis: result.omis, items };
    });
  }

  async project(profileId: string, intentionId: string): Promise<CronProjection> {
    return await closedOperation(async () => {
      validateProfile(profileId);
      validateIntent(intentionId);
      const projection = parseProjection(
        await this.#post(profileId, "projeter", { intention_id: intentionId }),
        intentionId,
      );
      if (!projection) fail("unavailable");
      return projection;
    });
  }

  async prepare(
    profileId: string,
    intentionId: string,
    input: PrepareCronGrant,
  ): Promise<CronPreparation> {
    return await closedOperation(async () => {
      const request = {
        capabilityFingerprint: input.capabilityFingerprint,
        expectedEpoch: input.expectedEpoch,
        expectedNativeRevision: input.expectedNativeRevision,
        leaseSeconds: input.leaseSeconds,
        declaration: input.declaration,
      };
      validateProfile(profileId);
      validateIntent(intentionId);
      if (
        typeof request.capabilityFingerprint !== "string" ||
        !HEX64.test(request.capabilityFingerprint) ||
        !positive(request.expectedEpoch, true) ||
        !positive(request.leaseSeconds) ||
        request.leaseSeconds > 120
      )
        fail("configuration");
      validateRevision(request.expectedNativeRevision, true);
      const declaration = snapshotDeclaration(request.declaration);
      const result = await this.#post(profileId, "preparer", {
        intention_id: intentionId,
        empreinte_capacite: request.capabilityFingerprint,
        declaration,
        epoch_attendue: request.expectedEpoch,
        revision_native_attendue: request.expectedNativeRevision,
        lease_secondes: request.leaseSeconds,
      });
      const { status, extra } = parseStatusExtra(result, [
        "lease_until",
        "revision_native_attendue",
        "native",
      ]);
      if (
        !status ||
        !validLease(extra.lease_until) ||
        !revision(extra.revision_native_attendue, true) ||
        !record(extra.native) ||
        !exact(extra.native, ["method", "params"]) ||
        extra.native.method !== "cron.add" ||
        !jsonObject(extra.native.params) ||
        !sameJson(extra.native.params, declaration)
      )
        fail("unavailable");
      if (
        status.intention !== intentionId ||
        status.epoch !== request.expectedEpoch + 1 ||
        status.etat !== "preparation" ||
        status.job_id !== null ||
        status.config_revision !== null ||
        extra.revision_native_attendue !== request.expectedNativeRevision
      )
        fail("unavailable");
      return {
        ...status,
        lease_until: extra.lease_until,
        revision_native_attendue: extra.revision_native_attendue,
        native: { method: "cron.add", params: extra.native.params },
      };
    });
  }

  async acknowledge(profileId: string, input: AcknowledgeCronGrant): Promise<CronGrantStatus> {
    return await closedOperation(async () => {
      const request = {
        intentionId: input.intentionId,
        capability: input.capability,
        epoch: input.epoch,
        leaseEpoch: input.leaseEpoch,
        jobId: input.jobId,
        configRevision: input.configRevision,
        declaration: input.declaration,
      };
      validateProfile(profileId);
      validateIntent(request.intentionId);
      const declaration = validateGrantFields(request);
      const status = parseStatus(
        await this.#post(profileId, "accuser", {
          intention_id: request.intentionId,
          capabilite: request.capability,
          epoch: request.epoch,
          lease_epoch: request.leaseEpoch,
          job_id: request.jobId,
          config_revision: request.configRevision,
          declaration,
        }),
      );
      if (
        !status ||
        status.intention !== request.intentionId ||
        status.epoch !== request.epoch ||
        status.lease_epoch !== request.leaseEpoch ||
        status.etat !== "remise" ||
        status.job_id !== request.jobId ||
        status.config_revision !== request.configRevision
      )
        fail("unavailable");
      return status;
    });
  }

  async validate(
    profileId: string,
    input: ValidateCronGrant,
    options: { signal?: AbortSignal } = {},
  ): Promise<void> {
    return await closedOperation(async () => {
      const signal = options.signal;
      const request = {
        intentionId: input.intentionId,
        capability: input.capability,
        epoch: input.epoch,
        jobId: input.jobId,
        configRevision: input.configRevision,
        declaration: input.declaration,
      };
      validateProfile(profileId);
      validateIntent(request.intentionId);
      const declaration = validateGrantFields(request);
      const result = await this.#post(
        profileId,
        "valider",
        {
          intention_id: request.intentionId,
          capabilite: request.capability,
          epoch: request.epoch,
          job_id: request.jobId,
          config_revision: request.configRevision,
          declaration,
        },
        signal,
      );
      if (!exact(result, ["valide"]) || result.valide !== true) fail("unavailable");
    });
  }

  async renew(
    profileId: string,
    input: RenewCronGrant,
  ): Promise<CronGrantStatus & { lease_until: string }> {
    return await closedOperation(async () => {
      const request = {
        intentionId: input.intentionId,
        capability: input.capability,
        epoch: input.epoch,
        leaseEpoch: input.leaseEpoch,
        leaseSeconds: input.leaseSeconds,
        declaration: input.declaration,
      };
      validateProfile(profileId);
      validateIntent(request.intentionId);
      if (
        typeof request.capability !== "string" ||
        !HEX64.test(request.capability) ||
        !positive(request.epoch) ||
        !positive(request.leaseEpoch) ||
        !positive(request.leaseSeconds) ||
        request.leaseSeconds > 120
      )
        fail("configuration");
      const declaration = snapshotDeclaration(request.declaration);
      const result = await this.#post(profileId, "renouveler", {
        intention_id: request.intentionId,
        capabilite: request.capability,
        epoch: request.epoch,
        lease_epoch: request.leaseEpoch,
        declaration,
        lease_secondes: request.leaseSeconds,
      });
      const { status, extra } = parseStatusExtra(result, ["lease_until"]);
      if (
        !status ||
        !validLease(extra.lease_until) ||
        status.intention !== request.intentionId ||
        status.epoch !== request.epoch ||
        status.lease_epoch !== request.leaseEpoch + 1 ||
        status.etat !== "preparation"
      )
        fail("unavailable");
      return { ...status, lease_until: extra.lease_until };
    });
  }

  async prepareRetirement(
    profileId: string,
    input: PrepareCronRetirement,
  ): Promise<CronRetirementPreparation> {
    return await closedOperation(async () => {
      const request = snapshotRetirementRequest(profileId, input);
      const result = await this.#post(profileId, "preparer-retrait", retirementBody(request));
      if (
        !exact(result, [
          "version",
          "intention",
          "source_hash",
          "epoch",
          "job_id",
          "native_revision",
          "declaration_hash",
          "declaration_key",
          "receipt_id",
          "execute",
        ]) ||
        result.version !== 1 ||
        result.intention !== request.intentionId ||
        typeof result.source_hash !== "string" ||
        !HEX64.test(result.source_hash) ||
        result.epoch !== request.epoch ||
        result.job_id !== request.jobId ||
        result.native_revision !== request.nativeRevision ||
        result.declaration_hash !== digestJson(request.declaration) ||
        result.declaration_key !== `opsys-profile:${request.intentionId}` ||
        typeof result.receipt_id !== "string" ||
        !HEX64.test(result.receipt_id) ||
        result.execute !== false
      )
        fail("unavailable");
      const proof = {
        version: 1 as const,
        intention: request.intentionId,
        source_hash: result.source_hash,
        epoch: request.epoch,
        job_id: request.jobId,
        native_revision: request.nativeRevision,
        declaration_hash: digestJson(request.declaration),
        declaration_key: `opsys-profile:${request.intentionId}`,
      };
      if (result.receipt_id !== digestJson(proof)) fail("unavailable");
      return { ...proof, receipt_id: result.receipt_id, execute: false };
    });
  }

  async acknowledgeRetirement(
    profileId: string,
    input: AcknowledgeCronRetirement,
  ): Promise<CronRetirementAcknowledgement> {
    return await closedOperation(async () => {
      // Snapshot scalars and wire JSON before the first HTTP await, including ACK bindings.
      const sourceHash = input.sourceHash;
      const receiptId = input.receiptId;
      const request = snapshotRetirementRequest(profileId, input);
      if (
        typeof sourceHash !== "string" ||
        !HEX64.test(sourceHash) ||
        typeof receiptId !== "string" ||
        !HEX64.test(receiptId)
      )
        fail("configuration");
      const result = await this.#post(profileId, "accuser-retrait", {
        ...retirementBody(request),
        source_hash: sourceHash,
        receipt_id: receiptId,
      });
      if (
        !exact(result, [
          "intention",
          "receipt_id",
          "source_hash",
          "epoch",
          "job_id",
          "etat",
          "execute",
        ]) ||
        result.intention !== request.intentionId ||
        result.receipt_id !== receiptId ||
        result.source_hash !== sourceHash ||
        result.epoch !== request.epoch ||
        result.job_id !== request.jobId ||
        result.etat !== "retiree" ||
        result.execute !== false
      )
        fail("unavailable");
      return {
        intention: request.intentionId,
        receipt_id: receiptId,
        source_hash: sourceHash,
        epoch: request.epoch,
        job_id: request.jobId,
        etat: "retiree",
        execute: false,
      };
    });
  }

  async #post(
    profileId: string,
    operation: string,
    body: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    let response: Response | undefined;
    try {
      const encoded = JSON.stringify(body);
      if (Buffer.byteLength(encoded, "utf8") > MAX_BODY_BYTES) fail("configuration");
      const requestSignal = signal
        ? AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)])
        : AbortSignal.timeout(REQUEST_TIMEOUT_MS);
      requestSignal.throwIfAborted();
      response = await this.#fetch(`${this.#origin}${PREFIX}${profileId}/${operation}`, {
        method: "POST",
        redirect: "error",
        cache: "no-store",
        signal: requestSignal,
        headers: { authorization: `Bearer ${this.#token}`, "content-type": "application/json" },
        body: encoded,
      });
      requestSignal.throwIfAborted();
      if (response.status !== 200) {
        await cancelUnreadResponseBody(response);
        fail(response.status === 400 || response.status === 409 ? "refused" : "unavailable");
      }
      const contentType = response.headers.get("content-type")?.toLowerCase();
      const cacheControl = response.headers.get("cache-control")?.toLowerCase() ?? "";
      if (
        contentType !== "application/json" ||
        !cacheControl.split(",").some((item) => item.trim() === "no-store")
      ) {
        await cancelUnreadResponseBody(response);
        fail("unavailable");
      }
      const bytes = await readResponseWithLimit(response, MAX_BODY_BYTES, {
        timeoutMs: REQUEST_TIMEOUT_MS,
        signal: requestSignal,
      });
      requestSignal.throwIfAborted();
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const envelope = parseStrictJson(text);
      if (!exact(envelope, ["ok", "resultat"]) || envelope.ok !== true) fail("unavailable");
      return envelope.resultat;
    } catch (error) {
      if (error instanceof OpsysCronPrivateClientError) throw error;
      if (response) await cancelUnreadResponseBody(response);
      fail("unavailable");
    }
  }
}

function parseStatusExtra(
  value: unknown,
  extraKeys: readonly string[],
): { status?: CronGrantStatus; extra: Record<string, unknown> } {
  if (!record(value)) return { extra: {} };
  const keys = [
    "intention",
    "epoch",
    "lease_epoch",
    "etat",
    "job_id",
    "config_revision",
    "execute",
    ...extraKeys,
  ];
  if (!exact(value, keys)) return { extra: {} };
  const statusValue: Record<string, unknown> = {};
  for (const key of keys.slice(0, 7)) statusValue[key] = value[key];
  return { status: parseStatus(statusValue), extra: value };
}

function sameJson(left: unknown, right: unknown): boolean {
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical);
    if (record(value))
      return Object.fromEntries(
        Object.keys(value)
          .sort()
          .map((key) => [key, canonical(value[key])]),
      );
    return value;
  };
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function validateGrantFields(input: AcknowledgeCronGrant | ValidateCronGrant): CronDeclaration {
  if (
    typeof input.capability !== "string" ||
    !HEX64.test(input.capability) ||
    !positive(input.epoch) ||
    !validJob(input.jobId)
  )
    fail("configuration");
  if ("leaseEpoch" in input && !positive(input.leaseEpoch)) fail("configuration");
  validateRevision(input.configRevision, false);
  return snapshotDeclaration(input.declaration);
}

function digestJson(value: unknown): string {
  return createHash("sha256").update(stableStringify(value), "utf8").digest("hex");
}

function snapshotRetirementRequest(
  profileId: string,
  input: PrepareCronRetirement,
): PrepareCronRetirement {
  const request = {
    intentionId: input.intentionId,
    capability: input.capability,
    epoch: input.epoch,
    jobId: input.jobId,
    nativeRevision: input.nativeRevision,
    declaration: input.declaration,
  };
  validateProfile(profileId);
  validateIntent(request.intentionId);
  if (typeof request.nativeRevision !== "string" || !CORE_REVISION.test(request.nativeRevision))
    fail("configuration");
  const declaration = validateGrantFields({ ...request, configRevision: request.nativeRevision });
  if (
    declaration.declarationKey !== `opsys-profile:${request.intentionId}` ||
    declaration.agentId !== `opsys-agent-${profileId}`
  )
    fail("configuration");
  registerSecretValueForRedaction(request.capability);
  return { ...request, declaration };
}

function retirementBody(request: PrepareCronRetirement): Record<string, unknown> {
  return {
    intention_id: request.intentionId,
    capabilite: request.capability,
    epoch: request.epoch,
    declaration: request.declaration,
    job_id: request.jobId,
    native_revision: request.nativeRevision,
  };
}
