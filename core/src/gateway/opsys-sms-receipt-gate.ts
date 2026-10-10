/** Standalone private Host composition; no queue adoption, model dispatch or SQL access. */
import { createHash } from "node:crypto";
import { isDeepStrictEqual, types } from "node:util";
import { resolveMcpTransportConfig } from "../agents/mcp-transport-config.js";
import {
  validateSmsCommand,
  type SmsOperation,
  type ValidatedSmsCommand,
} from "../agents/opsys-runtime-sms-contract.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import type { OpsysSmsIngressCapture } from "./opsys-sms-ingress-capture.js";

const UNRESOLVED = Object.freeze({
  status: "unresolved" as const,
  code: "M1-SMS-RECEPTION-NON-RESOLUE",
});
const READ = "opsys_runtime_lire_reception_sms";
const RECEIVE = "opsys_runtime_recevoir_sms";
const ACK_KEYS = [
  "version",
  "operation",
  "ok",
  "etat",
  "intention_id",
  "commande_sha256",
  "arguments_sha256",
  "permission",
  "recu",
];
const RECEIPT_KEYS = [
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
];
const ERRORS: Readonly<Record<string, string>> = Object.freeze({
  refus: "REJ-M1-SMS-AUTORITE-REFUSEE",
  revision_perimee: "REJ-M1-SMS-REVISION-PERIMEE",
  conflit: "REJ-M1-SMS-PROVENANCE-CONFLICTUELLE",
  forme_invalide: "REJ-M1-SMS-FORME-INVALIDE",
  inconnu: "M1-SMS-INCONNU",
});
const DECISIONS = [
  "DEMANDER_PRECISIONS",
  "TRANSMETTRE_M2",
  "CONVERSATION_DEJA_QUALIFIEE",
  "RETRAIT_CONSENTEMENT",
  "ESCALADE_PLAINTE",
  "ESCALADE_URGENCE",
  "TRANSFERT_EN_COURS",
] as const;
export type SmsHostReceipt = Readonly<{
  source: string;
  compte_id: string;
  account_sid: string;
  message_sid: string;
  agent_id: string;
  session_key: string;
  signal_id: string;
  signal_ligne_id: string;
  decision: (typeof DECISIONS)[number];
  lead_ligne_id: string | null;
  transfert_id: string | null;
}>;
export type SmsReceiptResolution =
  | typeof UNRESOLVED
  | Readonly<{ status: "received"; command: ValidatedSmsCommand; receipt: SmsHostReceipt }>;
const receivedDestinationAssertions = new WeakMap<object, () => void>();

/** Private Core lookup: the exact Gate result is required; no public receipt field carries authority. */
export function readSmsReceiptHostDestinationAssertion(result: unknown): (() => void) | undefined {
  if (result === null || typeof result !== "object") {
    return undefined;
  }
  const guard = receivedDestinationAssertions.get(result);
  if (!guard) {
    return undefined;
  }
  try {
    guard();
    return guard;
  } catch {
    receivedDestinationAssertions.delete(result);
    return undefined;
  }
}
type Params = {
  capture: OpsysSmsIngressCapture;
  profileId: string;
  getCurrentConfig: () => OpenClawConfig;
  assertCurrent: () => void;
  signal: AbortSignal;
  /** Private transport injection; callers must not expose this capability to plugins. */
  callTool?: typeof callOpsysMcpTool;
};
type ClaimContext = {
  /** Trusted adapter-only original. Its absence never creates native provenance proof. */
  nativeOriginal?: Readonly<{ payload: unknown; receivedAt: number }>;
  id: string;
  receivedAt: number;
  assertClaimCurrent: () => void;
  signal: AbortSignal;
};

function requireGate(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(UNRESOLVED.code);
  }
}
function plain(value: unknown, fields?: readonly string[]): Record<string, unknown> {
  requireGate(typeof value === "object" && value !== null && !types.isProxy(value));
  requireGate(
    Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null,
  );
  const keys = Reflect.ownKeys(value);
  requireGate(keys.every((k) => typeof k === "string"));
  if (fields) {
    requireGate(keys.length === fields.length && keys.every((k) => fields.includes(k as string)));
  }
  const copy: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    requireGate(descriptor?.enumerable && Object.hasOwn(descriptor, "value"));
    copy[key as string] = descriptor.value;
  }
  return copy;
}
function matches(value: unknown, pattern: RegExp): value is string {
  return typeof value === "string" && pattern.exec(value)?.[0] === value;
}
function destination(config: OpenClawConfig, server: string) {
  const raw = plain(config.mcp?.servers?.[server]);
  const resolved = resolveMcpTransportConfig(server, raw, { logWarnings: false });
  requireGate(resolved?.kind === "http" && resolved.transportType === "streamable-http");
  requireGate(raw.transport === "streamable-http" && raw.enabled !== false);
  const allowed = new Set([
    "transport",
    "url",
    "headers",
    "enabled",
    "sslVerify",
    "connectionTimeoutMs",
    "requestTimeoutMs",
    "supportsParallelToolCalls",
  ]);
  requireGate(Object.keys(raw).every((k) => allowed.has(k)) && raw.sslVerify !== false);
  requireGate(!resolved.auth && !resolved.oauth && !resolved.clientCert && !resolved.clientKey);
  const url = new URL(resolved.url);
  requireGate(
    !url.username && !url.password && !resolved.url.includes("?") && !resolved.url.includes("#"),
  );
  const headers = plain(raw.headers);
  requireGate(Object.keys(headers).length === 1);
  const snapshotHeaders: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    requireGate(
      name.toLowerCase() === "authorization" &&
        typeof value === "string" &&
        /^Bearer [^\r\n]+$/u.exec(value)?.[0] === value,
    );
    snapshotHeaders[name] = value;
  }
  const hash = createHash("sha256").update("opsys:m1:sms:destination:v1:", "ascii");
  for (const value of [server, resolved.transportType, url.href]) {
    const bytes = Buffer.from(value, "utf8");
    hash.update(String(bytes.length) + ":", "ascii").update(bytes);
  }
  // Freeze a dedicated target; unrelated runtime configuration is never passed to the caller.
  const snapshot: OpenClawConfig = Object.freeze({
    plugins: Object.freeze({ enabled: false }),
    mcp: Object.freeze({
      servers: Object.freeze({
        [server]: Object.freeze({
          transport: "streamable-http",
          url: url.href,
          headers: Object.freeze(snapshotHeaders),
        }),
      }),
    }),
  });
  return { fingerprint: hash.digest("hex"), config: snapshot };
}
function receipt(value: unknown, command: ValidatedSmsCommand): SmsHostReceipt {
  const r = plain(value, RECEIPT_KEYS),
    c = command.commande;
  requireGate(r.source === "sms:twilio");
  for (const key of [
    "compte_id",
    "account_sid",
    "message_sid",
    "agent_id",
    "session_key",
  ] as const) {
    requireGate(r[key] === c[key]);
  }
  requireGate(
    r.signal_id === "sms:" + c.message_sid && matches(r.signal_ligne_id, /^[0-9a-f]{64}$/u),
  );
  requireGate(typeof r.decision === "string" && DECISIONS.some((d) => d === r.decision));
  requireGate(r.lead_ligne_id === null || matches(r.lead_ligne_id, /^[0-9a-f]{64}$/u));
  requireGate(r.transfert_id === null || matches(r.transfert_id, /^tr-[0-9a-f]{20}$/u));
  if (r.decision === "TRANSMETTRE_M2" || r.decision === "CONVERSATION_DEJA_QUALIFIEE") {
    requireGate(
      r.lead_ligne_id !== null && r.lead_ligne_id !== r.signal_ligne_id && r.transfert_id === null,
    );
  } else if (["ESCALADE_PLAINTE", "ESCALADE_URGENCE", "TRANSFERT_EN_COURS"].includes(r.decision)) {
    requireGate(r.lead_ligne_id === null && r.transfert_id !== null);
  } else {
    requireGate(r.lead_ligne_id === null && r.transfert_id === null);
  }
  // All fields above are copied data scalars, narrowed to the exact wire contract.
  return Object.freeze(r) as SmsHostReceipt;
}
function acknowledgment(value: unknown, command: ValidatedSmsCommand): SmsHostReceipt | null {
  const a = plain(value);
  const short = command.operation === READ ? "lire" : "recevoir";
  if (a.ok === false) {
    plain(a, ["version", "operation", "ok", "etat", "code"]);
    requireGate(
      a.version === 1 &&
        a.operation === short &&
        typeof a.etat === "string" &&
        Object.hasOwn(ERRORS, a.etat) &&
        a.code === ERRORS[a.etat],
    );
    throw new Error(UNRESOLVED.code);
  }
  plain(a, ACK_KEYS);
  requireGate(a.version === 1 && a.operation === short && a.ok === true);
  requireGate(
    a.intention_id === command.intention_id &&
      a.commande_sha256 === command.commande_sha256 &&
      a.arguments_sha256 === command.arguments_sha256,
  );
  const p = plain(a.permission, ["profil_id", "revision_profil", "outil_m1"]);
  requireGate(
    p.profil_id === command.permission.profil_id &&
      p.revision_profil === command.permission.revision_profil &&
      p.outil_m1 === command.permission.outil_m1,
  );
  let r: SmsHostReceipt | null;
  if (a.etat === "absent") {
    requireGate(command.operation === READ && a.recu === null);
    r = null;
  } else {
    requireGate(a.etat === "recu");
    r = receipt(a.recu, command);
  }
  // Measure a fully checked data-only representation, never an arbitrary toJSON callback.
  requireGate(Buffer.byteLength(JSON.stringify({ ...a, permission: p, recu: r }), "utf8") <= 8192);
  return r;
}

export function createOpsysSmsReceiptGate(params: Params) {
  const {
    capture,
    profileId,
    getCurrentConfig,
    assertCurrent,
    signal: hostSignal,
    callTool,
  } = params;
  requireGate(matches(profileId, /^[a-z][a-z0-9-]{1,63}$/u));
  const server = `opsys_runtime_${profileId}`;
  const current = () => {
    hostSignal.throwIfAborted();
    requireGate(assertCurrent() === undefined);
    return destination(getCurrentConfig(), server);
  };
  return Object.freeze({
    encodeCaptured(handle: unknown, receivedAt: number) {
      try {
        const target = current();
        const payload = capture.seal(handle, receivedAt, target.fingerprint);
        requireGate(current().fingerprint === target.fingerprint);
        return payload;
      } catch {
        throw new Error(UNRESOLVED.code);
      }
    },
    async resolveReceipt(payload: unknown, context: ClaimContext): Promise<SmsReceiptResolution> {
      try {
        const { id, receivedAt, assertClaimCurrent, signal } = context;
        const target = current();
        // The baseline remains the original target. Claim ownership is checked separately.
        let destinationClosed = false;
        const assertHostDestinationCurrent = () => {
          try {
            requireGate(!destinationClosed);
            signal.throwIfAborted();
            requireGate(current().fingerprint === target.fingerprint);
            hostSignal.throwIfAborted();
            signal.throwIfAborted();
          } catch {
            destinationClosed = true;
            throw new Error(UNRESOLVED.code);
          }
        };
        const check = () => {
          assertHostDestinationCurrent();
          requireGate(assertClaimCurrent() === undefined);
          assertHostDestinationCurrent();
        };
        check();
        const owned = capture.open(payload, {
          id,
          receivedAt,
          destinationSha256: target.fingerprint,
        });
        requireGate(owned.permission.profil_id === profileId);
        if (context.nativeOriginal) {
          const original = context.nativeOriginal;
          requireGate(original.receivedAt === receivedAt);
          const originalOwned = capture.open(original.payload, {
            id,
            receivedAt: original.receivedAt,
            destinationSha256: target.fingerprint,
          });
          // Both values are already owned frozen scalar projections: no hostile getter/toJSON.
          // seal(open(...)) reuses the capture's private records, without recapturing a new time.
          requireGate(
            isDeepStrictEqual(
              capture.seal(owned, receivedAt, target.fingerprint),
              capture.seal(originalOwned, receivedAt, target.fingerprint),
            ),
          );
        }
        check();
        const caller =
          callTool ?? (await import("../context-engine/opsys-contexte-mcp.js")).callOpsysMcpTool;
        check();
        const args = Object.freeze({
          version: 1,
          commande: owned.commande,
          permission: owned.permission,
        });
        const request = async (operation: SmsOperation) => {
          const command = validateSmsCommand(args, operation);
          check();
          const selected = current();
          const deadline = new AbortController();
          const timer = setTimeout(() => deadline.abort(), 8000);
          timer.unref();
          try {
            const combined = AbortSignal.any([hostSignal, signal, deadline.signal]);
            const value = await caller({
              config: selected.config,
              server,
              tool: operation,
              args,
              timeoutMs: 8000,
              signal: combined,
              maxResponseBytes: 8192,
              awaitCleanup: true,
              beforeRequest: () => {
                combined.throwIfAborted();
                check();
              },
            });
            combined.throwIfAborted();
            check();
            const result = acknowledgment(value, command);
            check();
            return result;
          } finally {
            clearTimeout(timer);
          }
        };
        const existing = await request(READ);
        check();
        const result = existing ?? (await request(RECEIVE));
        check();
        requireGate(result !== null);
        const resolution = Object.freeze({
          status: "received" as const,
          command: owned,
          receipt: result,
        });
        receivedDestinationAssertions.set(resolution, assertHostDestinationCurrent);
        return resolution;
      } catch {
        return UNRESOLVED;
      }
    },
  });
}
