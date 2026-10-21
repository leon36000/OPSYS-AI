/** Pure private SMS codec. A capture is not provider proof or live authority. */
import { createHash } from "node:crypto";
import { types } from "node:util";

const COMMAND_FIELDS = [
  "canal",
  "provider",
  "compte_id",
  "account_sid",
  "message_sid",
  "expediteur",
  "destinataire",
  "recu_le",
  "texte",
  "session_key",
  "agent_id",
  "preuve_sha256",
] as const;
const ERROR = "REJ-M1-SMS-COMMANDE-INVALIDE";
export type SmsOperation = "opsys_runtime_lire_reception_sms" | "opsys_runtime_recevoir_sms";
export type SmsCommand = Readonly<Record<(typeof COMMAND_FIELDS)[number], string>>;
export type SmsPermission = Readonly<{
  profil_id: string;
  revision_profil: number;
  outil_m1: string;
}>;
export type ValidatedSmsCommand = Readonly<{
  commande: SmsCommand;
  permission: SmsPermission;
  operation: SmsOperation;
  intention_id: string;
  commande_sha256: string;
  arguments_sha256: string;
}>;

function requireCondition(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(ERROR);
  }
}

function plainData(value: unknown, fields: readonly string[]): Record<string, unknown> {
  requireCondition(typeof value === "object" && value !== null && !types.isProxy(value));
  const prototype = Object.getPrototypeOf(value);
  requireCondition(prototype === Object.prototype || prototype === null);
  const keys = Reflect.ownKeys(value);
  requireCondition(
    keys.length === fields.length &&
      keys.every((key) => typeof key === "string" && fields.includes(key)),
  );
  const copied: Record<string, unknown> = Object.create(null);
  for (const field of fields) {
    const descriptor = Object.getOwnPropertyDescriptor(value, field);
    requireCondition(descriptor && Object.hasOwn(descriptor, "value") && descriptor.enumerable);
    copied[field] = descriptor.value;
  }
  return copied;
}

function text(value: unknown): string {
  requireCondition(typeof value === "string" && value.length <= 131072);
  for (let index = 0; index < value.length; index++) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(++index);
      requireCondition(next >= 0xdc00 && next <= 0xdfff);
    } else {
      requireCondition(unit < 0xdc00 || unit > 0xdfff);
    }
  }
  return value;
}

function matches(value: string, pattern: RegExp): boolean {
  // JS `$` also matches before a final newline; require the entire match.
  return pattern.exec(value)?.[0] === value;
}

function validateFields(command: SmsCommand, permission: SmsPermission): void {
  requireCondition(command.canal === "sms" && command.provider === "twilio");
  requireCondition(matches(command.compte_id, /^[a-z0-9][a-z0-9_-]{0,63}$/u));
  requireCondition(!["__proto__", "prototype", "constructor"].includes(command.compte_id));
  requireCondition(matches(command.account_sid, /^AC[0-9a-fA-F]{32}$/u));
  requireCondition(matches(command.message_sid, /^SM[0-9a-fA-F]{32}$/u));
  requireCondition(matches(command.expediteur, /^\+[1-9][0-9]{6,14}$/u));
  requireCondition(matches(command.destinataire, /^\+[1-9][0-9]{6,14}$/u));
  requireCondition(matches(permission.profil_id, /^[a-z][a-z0-9-]{1,63}$/u));
  requireCondition(permission.outil_m1 === "opsys_m1__m1_recevoir_message_canal");
  requireCondition(command.agent_id === "opsys-agent-" + permission.profil_id);
  requireCondition(
    command.session_key === `agent:${command.agent_id}:sms:direct:${command.expediteur}`,
  );
  requireCondition(matches(command.preuve_sha256, /^[0-9a-f]{64}$/u));
  // Match Python str.strip whitespace, not JS trim (notably U+0085 and BOM).
  const blank =
    // oxlint-disable-next-line no-control-regex -- Python strip includes these exact control characters.
    /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
  requireCondition(
    !matches(command.texte, blank) && Buffer.byteLength(command.texte, "utf8") <= 20000,
  );
  requireCondition(
    matches(command.recu_le, /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/u),
  );
  requireCondition(!command.recu_le.startsWith("0000-"));
  const parsed = new Date(command.recu_le);
  requireCondition(Number.isFinite(parsed.getTime()) && parsed.toISOString() === command.recu_le);
  // This bounds reserialized decoded JSON, not original HTTP bytes or duplicate keys.
  requireCondition(
    Buffer.byteLength(JSON.stringify({ version: 1, commande: command, permission }), "utf8") <=
      131072,
  );
}

function digest(prefix: string, fields: readonly string[]): string {
  const hash = createHash("sha256").update(prefix, "ascii");
  for (const field of fields) {
    const bytes = Buffer.from(field, "utf8");
    hash.update(String(bytes.length), "ascii").update(":", "ascii").update(bytes);
  }
  return hash.digest("hex");
}

export function validateSmsCommand(input: unknown, operation: unknown): ValidatedSmsCommand {
  requireCondition(
    operation === "opsys_runtime_lire_reception_sms" || operation === "opsys_runtime_recevoir_sms",
  );
  const envelope = plainData(input, ["version", "commande", "permission"]);
  requireCondition(envelope.version === 1);
  const raw = plainData(envelope.commande, COMMAND_FIELDS);
  const p = plainData(envelope.permission, ["profil_id", "revision_profil", "outil_m1"]);
  const commande: SmsCommand = Object.freeze({
    canal: text(raw.canal),
    provider: text(raw.provider),
    compte_id: text(raw.compte_id),
    account_sid: text(raw.account_sid),
    message_sid: text(raw.message_sid),
    expediteur: text(raw.expediteur),
    destinataire: text(raw.destinataire),
    recu_le: text(raw.recu_le),
    texte: text(raw.texte),
    session_key: text(raw.session_key),
    agent_id: text(raw.agent_id),
    preuve_sha256: text(raw.preuve_sha256),
  });
  requireCondition(
    typeof p.revision_profil === "number" &&
      Number.isSafeInteger(p.revision_profil) &&
      p.revision_profil > 0,
  );
  const permission: SmsPermission = Object.freeze({
    profil_id: text(p.profil_id),
    revision_profil: p.revision_profil,
    outil_m1: text(p.outil_m1),
  });
  validateFields(commande, permission);
  const values = COMMAND_FIELDS.map((field) => commande[field]);
  return Object.freeze({
    commande,
    permission,
    operation,
    intention_id:
      "sms-v1:" +
      digest("opsys:m1:sms:intention:v1:", [
        commande.provider,
        commande.account_sid,
        commande.message_sid,
      ]),
    commande_sha256: digest("opsys:m1:sms:commande:v1:", values),
    arguments_sha256: digest("opsys:m1:sms:arguments:v1:", [
      operation,
      "1",
      ...values,
      permission.profil_id,
      String(permission.revision_profil),
      permission.outil_m1,
    ]),
  });
}
