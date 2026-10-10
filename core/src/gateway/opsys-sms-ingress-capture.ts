/** Private standalone Host capture. No queue, RPC or model delivery is performed here. */
import { createHash } from "node:crypto";
import path from "node:path";
import { types } from "node:util";
import {
  validateSmsCommand,
  type SmsPermission,
  type ValidatedSmsCommand,
} from "../agents/opsys-runtime-sms-contract.js";
import type { PluginManifestRecord } from "../plugins/manifest-registry.js";
import { loadBundledPluginPublicArtifactModuleFromCandidatesSync } from "../plugins/public-surface-loader.js";

export const OPSYS_SMS_INGRESS_CAPTURE_REFUSED = "REJ-M1-SMS-INGRESS-CAPTURE";
const MAX_CAPSULE_BYTES = 262144;
const CAPSULE_FIELDS = [
  "version",
  "signature_url",
  "signature",
  "compte_id",
  "permission",
  "received_at",
  "commande_sha256",
  "destination_sha256",
];
const PERMISSION_FIELDS = ["profil_id", "revision_profil", "outil_m1"];
type Owner = Pick<PluginManifestRecord, "id" | "origin" | "rootDir" | "source">;
type Selection = Readonly<{
  accountId: string;
  accountSid: string;
  fromNumber: string;
  publicWebhookUrl: string;
  permission: SmsPermission;
}>;
export type CreateOpsysSmsIngressCaptureParams = {
  owner: Owner;
  selection: Selection;
  /** Trusted Host callback; failure invalidates this controller permanently. */
  assertCurrent: () => void;
  /** Explicit current config credential, never an ENV fallback or plugin verdict. */
  getCurrentCredential: () => string;
};
export type SmsIngressCapturePayloadV2 = Readonly<{
  version: 2;
  form: Readonly<Record<string, string>>;
  capsule: Readonly<{
    version: 1;
    signature_url: string;
    signature: string;
    compte_id: string;
    permission: SmsPermission;
    received_at: number;
    commande_sha256: string;
    destination_sha256: string;
  }>;
}>;
type RawCapture = {
  form: Readonly<Record<string, string>>;
  signature: string;
  signatureUrl: string;
};
type CaptureState = { raw: RawCapture; sealed?: SmsIngressCapturePayloadV2 };
export type OpsysSmsIngressCapture = Readonly<{
  capture: (input: unknown) => object;
  seal: (
    handle: unknown,
    receivedAt: unknown,
    destinationSha256: unknown,
  ) => SmsIngressCapturePayloadV2;
  open: (payload: unknown, context: unknown) => ValidatedSmsCommand;
}>;
function requireCapture(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(OPSYS_SMS_INGRESS_CAPTURE_REFUSED);
  }
}
function plain(value: unknown, fields?: readonly string[]): Record<string, unknown> {
  requireCapture(typeof value === "object" && value !== null && !types.isProxy(value));
  const prototype = Object.getPrototypeOf(value);
  requireCapture(prototype === Object.prototype || prototype === null);
  const keys = Reflect.ownKeys(value);
  requireCapture(keys.every((key) => typeof key === "string"));
  if (fields) {
    requireCapture(
      keys.length === fields.length && keys.every((key) => fields.includes(key as string)),
    );
  }
  const copy: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    requireCapture(d && d.enumerable && Object.hasOwn(d, "value"));
    copy[key as string] = d.value;
  }
  return copy;
}
function text(value: unknown, max = MAX_CAPSULE_BYTES): string {
  requireCapture(typeof value === "string" && value.length <= max);
  // Reject malformed UTF16 before UTF8 conversion; ES2023 has no isWellFormed type.
  for (let index = 0; index < value.length; index++) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(++index);
      requireCapture(next >= 0xdc00 && next <= 0xdfff);
    } else {
      requireCapture(unit < 0xdc00 || unit > 0xdfff);
    }
  }
  return value;
}
function matches(value: string, pattern: RegExp): boolean {
  return pattern.exec(value)?.[0] === value;
}
function digest(value: unknown): string {
  const s = text(value, 64);
  requireCapture(matches(s, /^[0-9a-f]{64}$/u));
  return s;
}
function permission(value: unknown): SmsPermission {
  const p = plain(value, PERMISSION_FIELDS);
  requireCapture(
    typeof p.revision_profil === "number" &&
      Number.isSafeInteger(p.revision_profil) &&
      p.revision_profil > 0,
  );
  const profil_id = text(p.profil_id, 64),
    outil_m1 = text(p.outil_m1, 128);
  requireCapture(
    matches(profil_id, /^[a-z][a-z0-9-]{1,63}$/u) &&
      outil_m1 === "opsys_m1__m1_recevoir_message_canal",
  );
  return Object.freeze({ profil_id, revision_profil: p.revision_profil, outil_m1 });
}
function samePermission(left: SmsPermission, right: SmsPermission): boolean {
  return (
    left.profil_id === right.profil_id &&
    left.revision_profil === right.revision_profil &&
    left.outil_m1 === right.outil_m1
  );
}
function monitorTime(value: unknown): number {
  requireCapture(typeof value === "number" && Number.isSafeInteger(value) && value >= 0);
  const iso = new Date(value).toISOString();
  requireCapture(
    matches(iso, /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/u) &&
      !iso.startsWith("0000-"),
  );
  return value;
}
function boundedJson(value: unknown) {
  requireCapture(Buffer.byteLength(JSON.stringify(value), "utf8") <= MAX_CAPSULE_BYTES);
}
function copyForm(value: unknown): Readonly<Record<string, string>> {
  const p = plain(value);
  const copy: Record<string, string> = Object.create(null);
  let bytes = 0;
  for (const key of Object.keys(p)) {
    text(key);
    const v = text(p[key]);
    bytes += Buffer.byteLength(key, "utf8") + Buffer.byteLength(v, "utf8");
    requireCapture(bytes <= MAX_CAPSULE_BYTES);
    copy[key] = v;
  }
  boundedJson(copy);
  return Object.freeze(copy);
}
function messageSid(form: Readonly<Record<string, string>>): string {
  const primary = form.MessageSid,
    alias = form.SmsSid;
  requireCapture(primary !== undefined || alias !== undefined);
  if (primary !== undefined && alias !== undefined) {
    requireCapture(primary === alias);
  }
  const sid = primary ?? alias;
  requireCapture(typeof sid === "string" && matches(sid, /^SM[0-9a-fA-F]{32}$/u));
  return sid;
}
function proof(raw: RawCapture): string {
  const h = createHash("sha256").update("opsys:m1:sms:preuve:v1:", "ascii");
  const fields = [
    raw.signatureUrl,
    raw.signature,
    ...Object.keys(raw.form)
      .toSorted()
      .flatMap((key) => [key, raw.form[key]!]),
  ];
  for (const field of fields) {
    const bytes = Buffer.from(field, "utf8");
    h.update(String(bytes.length), "ascii").update(":", "ascii").update(bytes);
  }
  return h.digest("hex");
}

/** Caller supplies trusted Host closures, not plugin/RPC input. The standalone factory is not publication. */
export function createOpsysSmsIngressCapture(
  params: CreateOpsysSmsIngressCaptureParams,
): OpsysSmsIngressCapture {
  try {
    const parameters = plain(params, [
      "owner",
      "selection",
      "assertCurrent",
      "getCurrentCredential",
    ]);
    requireCapture(
      typeof parameters.assertCurrent === "function" && !types.isProxy(parameters.assertCurrent),
    );
    requireCapture(
      typeof parameters.getCurrentCredential === "function" &&
        !types.isProxy(parameters.getCurrentCredential),
    );
    const assertCurrent = parameters.assertCurrent as () => void,
      getCurrentCredential = parameters.getCurrentCredential as () => string;
    const o = plain(parameters.owner, ["id", "origin", "rootDir", "source"]);
    requireCapture(o.id === "sms" && o.origin === "bundled");
    const rootDir = text(o.rootDir),
      source = text(o.source);
    requireCapture(path.isAbsolute(rootDir) && source.length > 0);
    const owner: Owner = Object.freeze({ id: "sms", origin: "bundled", rootDir, source });
    const s = plain(parameters.selection, [
      "accountId",
      "accountSid",
      "fromNumber",
      "publicWebhookUrl",
      "permission",
    ]);
    const selected: Selection = Object.freeze({
      accountId: text(s.accountId, 64),
      accountSid: text(s.accountSid, 34),
      fromNumber: text(s.fromNumber, 16),
      publicWebhookUrl: text(s.publicWebhookUrl, 4096),
      permission: permission(s.permission),
    });
    requireCapture(
      matches(selected.accountId, /^[a-z0-9][a-z0-9_-]{0,63}$/u) &&
        !["__proto__", "prototype", "constructor"].includes(selected.accountId),
    );
    requireCapture(
      matches(selected.accountSid, /^AC[0-9a-fA-F]{32}$/u) &&
        matches(selected.fromNumber, /^\+[1-9][0-9]{6,14}$/u),
    );
    const baseUrl = selected.publicWebhookUrl.split("#", 1)[0]!;
    const parsedUrl = new URL(baseUrl);
    requireCapture(
      (parsedUrl.protocol === "https:" || parsedUrl.protocol === "http:") &&
        !parsedUrl.username &&
        !parsedUrl.password &&
        baseUrl.length > 0,
    );
    let retired = false;
    requireCapture(assertCurrent() === undefined);
    const credential = text(getCurrentCredential());
    requireCapture(credential.length > 0);
    const current = () => {
      try {
        requireCapture(
          !retired && assertCurrent() === undefined && getCurrentCredential() === credential,
        );
      } catch {
        retired = true;
        throw new Error(OPSYS_SMS_INGRESS_CAPTURE_REFUSED);
      }
    };
    const api = loadBundledPluginPublicArtifactModuleFromCandidatesSync<{
      verifyTwilioSignature: (input: {
        signature: string;
        url: string;
        authToken: string;
        form: Record<string, string>;
      }) => boolean;
    }>({ dirName: "sms", artifactCandidates: ["api"], owner });
    current();
    requireCapture(api && typeof api.verifyTwilioSignature === "function");
    const verify = api.verifyTwilioSignature;
    const records = new WeakMap<object, CaptureState>();
    const safe = <T>(run: () => T): T => {
      try {
        return run();
      } catch {
        throw new Error(OPSYS_SMS_INGRESS_CAPTURE_REFUSED);
      }
    };
    const rawCapture = (input: unknown): RawCapture => {
      const r = plain(input, ["form", "signature", "signatureUrl"]);
      const form = copyForm(r.form),
        signature = text(r.signature, 128),
        signatureUrl = text(r.signatureUrl, 4096);
      requireCapture(signature.length > 0 && !signatureUrl.includes("#"));
      requireCapture(
        signatureUrl === baseUrl ||
          (!baseUrl.includes("?") && signatureUrl.startsWith(baseUrl + "?")),
      );
      requireCapture(
        form.AccountSid === selected.accountSid &&
          form.To === selected.fromNumber &&
          matches(text(form.From), /^\+[1-9][0-9]{6,14}$/u),
      );
      messageSid(form);
      requireCapture(form.NumMedia === undefined || form.NumMedia === "0");
      requireCapture(!Object.keys(form).some((key) => key.startsWith("Media")));
      const body = text(form.Body);
      // Match the existing codec's Python-str.strip blank policy without changing original text.
      const blank =
        // oxlint-disable-next-line no-control-regex -- The canonical SMS codec includes exactly these controls.
        /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
      requireCapture(!matches(body, blank) && Buffer.byteLength(body, "utf8") <= 20000);
      current();
      requireCapture(
        verify({
          signature,
          url: signatureUrl,
          authToken: credential,
          form: form as Record<string, string>,
        }) === true,
      );
      current();
      return Object.freeze({ form, signature, signatureUrl });
    };
    const validated = (raw: RawCapture, receivedAt: number): ValidatedSmsCommand => {
      const sender = raw.form.From;
      return validateSmsCommand(
        {
          version: 1,
          commande: {
            canal: "sms",
            provider: "twilio",
            compte_id: selected.accountId,
            account_sid: selected.accountSid,
            message_sid: messageSid(raw.form),
            expediteur: sender,
            destinataire: raw.form.To,
            recu_le: new Date(receivedAt).toISOString(),
            texte: raw.form.Body,
            session_key: `agent:opsys-agent-${selected.permission.profil_id}:sms:direct:${sender}`,
            agent_id: `opsys-agent-${selected.permission.profil_id}`,
            preuve_sha256: proof(raw),
          },
          permission: selected.permission,
        },
        "opsys_runtime_recevoir_sms",
      );
    };
    const state = (handle: unknown): CaptureState => {
      requireCapture(typeof handle === "object" && handle !== null && !types.isProxy(handle));
      const record = records.get(handle);
      requireCapture(record);
      return record;
    };
    return Object.freeze({
      capture(input: unknown): object {
        return safe(() => {
          current();
          const raw = rawCapture(input);
          const handle = Object.freeze({});
          records.set(handle, { raw });
          return handle;
        });
      },
      seal(handle: unknown, time: unknown, destination: unknown): SmsIngressCapturePayloadV2 {
        return safe(() => {
          current();
          const rec = state(handle),
            receivedAt = monitorTime(time),
            destinationSha256 = digest(destination);
          if (rec.sealed) {
            requireCapture(
              rec.sealed.capsule.received_at === receivedAt &&
                rec.sealed.capsule.destination_sha256 === destinationSha256,
            );
            return rec.sealed;
          }
          const command = validated(rec.raw, receivedAt);
          const payload: SmsIngressCapturePayloadV2 = Object.freeze({
            version: 2,
            form: rec.raw.form,
            capsule: Object.freeze({
              version: 1,
              signature_url: rec.raw.signatureUrl,
              signature: rec.raw.signature,
              compte_id: selected.accountId,
              permission: selected.permission,
              received_at: receivedAt,
              commande_sha256: command.commande_sha256,
              destination_sha256: destinationSha256,
            }),
          });
          boundedJson(payload);
          current();
          rec.sealed = payload;
          return payload;
        });
      },
      open(payload: unknown, context: unknown): ValidatedSmsCommand {
        return safe(() => {
          current();
          const p = plain(payload, ["version", "form", "capsule"]);
          requireCapture(p.version === 2);
          const c = plain(p.capsule, CAPSULE_FIELDS);
          requireCapture(c.version === 1 && c.compte_id === selected.accountId);
          const capturedPermission = permission(c.permission);
          requireCapture(samePermission(capturedPermission, selected.permission));
          const expected = plain(context, ["id", "receivedAt", "destinationSha256"]);
          const receivedAt = monitorTime(c.received_at),
            destinationSha256 = digest(c.destination_sha256);
          requireCapture(
            monitorTime(expected.receivedAt) === receivedAt &&
              digest(expected.destinationSha256) === destinationSha256,
          );
          const raw = rawCapture({
            form: p.form,
            signature: c.signature,
            signatureUrl: c.signature_url,
          });
          requireCapture(text(expected.id, 34) === messageSid(raw.form));
          const command = validated(raw, receivedAt);
          requireCapture(digest(c.commande_sha256) === command.commande_sha256);
          const stored: SmsIngressCapturePayloadV2 = Object.freeze({
            version: 2,
            form: raw.form,
            capsule: Object.freeze({
              version: 1,
              signature_url: raw.signatureUrl,
              signature: raw.signature,
              compte_id: selected.accountId,
              permission: capturedPermission,
              received_at: receivedAt,
              commande_sha256: command.commande_sha256,
              destination_sha256: destinationSha256,
            }),
          });
          boundedJson(stored);
          current();
          records.set(command, { raw, sealed: stored });
          return command;
        });
      },
    });
  } catch {
    throw new Error(OPSYS_SMS_INGRESS_CAPTURE_REFUSED);
  }
}
