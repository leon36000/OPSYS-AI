import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { validateSmsCommand } from "./opsys-runtime-sms-contract.js";

const fixture = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/m1_sms_ingress_v1.json", import.meta.url), "utf8"),
);

const vectors: {
  nom: string;
  arguments: { commande: unknown; permission: unknown; version: unknown };
  operation: string;
  attendu: object;
}[] = fixture.vecteurs;

describe("pure SMS command codec (fictitious vectors)", () => {
  it.each(vectors)("matches literal hashes: $nom", (vector) => {
    expect(fixture.fictif).toBe(true);
    const captured = validateSmsCommand(structuredClone(vector.arguments), vector.operation);
    expect(captured.commande).toEqual(vector.arguments.commande);
    expect(captured.permission).toEqual(vector.arguments.permission);
    expect(captured.operation).toBe(vector.operation);
    expect(captured).toMatchObject(vector.attendu);
  });

  it("copies and freezes every scalar container", () => {
    const vector = fixture.vecteurs[0];
    const input = structuredClone(vector.arguments);
    const captured = validateSmsCommand(input, vector.operation);
    input.commande.texte = "Changed fictitious message";
    input.permission.revision_profil = 3;
    expect(captured.commande).toEqual(vector.arguments.commande);
    expect(captured.permission).toEqual(vector.arguments.permission);
    expect(Object.isFrozen(captured)).toBe(true);
    expect(Object.isFrozen(captured.commande)).toBe(true);
    expect(Object.isFrozen(captured.permission)).toBe(true);
    expect(Reflect.set(captured.commande, "texte", "changed")).toBe(false);
    expect(Reflect.set(captured.permission, "revision_profil", 3)).toBe(false);
  });
});

const operation = "opsys_runtime_recevoir_sms";
const error = "REJ-M1-SMS-COMMANDE-INVALIDE";
const input = () => structuredClone(fixture.vecteurs[0].arguments);
const invalidFields: [string, string, unknown][] = [
  ["permission", "revision_profil", 0],
  ["permission", "revision_profil", -1],
  ["permission", "revision_profil", 1.5],
  ["permission", "revision_profil", 9007199254740992],
  ["permission", "revision_profil", Number.NaN],
  ["permission", "revision_profil", Infinity],
  ["permission", "revision_profil", true],
  ["permission", "revision_profil", 1n],
  ["permission", "profil_id", "a"],
  ["permission", "profil_id", "M1-sms"],
  ["permission", "profil_id", "autre-fictif"],
  ["permission", "outil_m1", "autre"],
  ["commande", "canal", "voice"],
  ["commande", "provider", "autre"],
  ["commande", "compte_id", "Default"],
  ["commande", "compte_id", "_default"],
  ["commande", "compte_id", "a".repeat(65)],
  ["commande", "compte_id", "défaut"],
  ["commande", "compte_id", "__proto__"],
  ["commande", "compte_id", "prototype"],
  ["commande", "compte_id", "constructor"],
  ["commande", "compte_id", "default\n"],
  ["commande", "account_sid", "AC" + "a".repeat(31)],
  ["commande", "account_sid", "AC" + "g".repeat(32)],
  ["commande", "account_sid", "AC" + "a".repeat(32) + "\n"],
  ["commande", "message_sid", "MM" + "b".repeat(32)],
  ["commande", "message_sid", "SM" + "b".repeat(33)],
  ["commande", "expediteur", "+١٥١٤٥٥٥٠١٤٢"],
  ["commande", "expediteur", "+05145550142"],
  ["commande", "expediteur", "+123456"],
  ["commande", "destinataire", "+1234567890123456"],
  ["commande", "session_key", "agent:autre:sms:direct:+15145550142"],
  ["commande", "agent_id", "opsys-agent-autre"],
  ["commande", "preuve_sha256", "A".repeat(64)],
  ["commande", "preuve_sha256", "0".repeat(63)],
  ["commande", "texte", ""],
  ["commande", "texte", " \t\n\u00a0"],
  ["commande", "texte", "\u0085\u001c"],
  ["commande", "texte", "x".repeat(20001)],
  ["commande", "texte", "é".repeat(10001)],
  ["commande", "texte", "\ud800"],
  ["commande", "texte", "\udc00"],
  ["commande", "texte", "\ud800a\udc00"],
  ["commande", "texte", null],
  ["commande", "texte", { secret: "fictitious" }],
  ["commande", "texte", "SECRET-FICTITIOUS".repeat(131072)],
  ["commande", "recu_le", "2026-02-29T12:34:56.789Z"],
  ["commande", "recu_le", "2026-04-31T12:34:56.789Z"],
  ["commande", "recu_le", "2026-10-10T24:00:00.000Z"],
  ["commande", "recu_le", "2026-10-10T12:34:60.789Z"],
  ["commande", "recu_le", "2026-10-10T12:34:56Z"],
  ["commande", "recu_le", "2026-10-10T12:34:56.7890Z"],
  ["commande", "recu_le", "2026-10-10T12:34:56.789+00:00"],
  ["commande", "recu_le", "2026-10-10 12:34:56.789Z"],
  ["commande", "recu_le", "0000-10-10T12:34:56.789Z"],
  ["commande", "recu_le", "2026-13-10T12:34:56.789Z"],
  ["commande", "recu_le", "2026-10-10T12:34:56.789Z\n"],
];

it.each(invalidFields)("rejects invalid field %s.%s (fixed error)", (section, field, value) => {
  const args = input();
  args[section][field] = value;
  expect(() => validateSmsCommand(args, operation)).toThrow(new Error(error));
});

it.each([true, 2, "1", null, Number.NaN, Infinity, 1n])("rejects invalid version %s", (version) => {
  expect(() => validateSmsCommand({ ...input(), version }, operation)).toThrow(new Error(error));
});

it.each([null, "", "opsys_runtime_recevoir_sms ", "opsys_m1__m1_recevoir_message_canal", 1])(
  "rejects invalid full operation %s",
  (value) => {
    expect(() => validateSmsCommand(input(), value)).toThrow(new Error(error));
  },
);

it.each(["envelope", "commande", "permission"])(
  "rejects getters/proxies without executing at %s",
  (level) => {
    for (const kind of [
      "getter",
      "proxy",
      "revoked",
      "hidden",
      "symbol",
      "class",
      "missing",
      "extra",
    ]) {
      const args = input();
      let target = level === "envelope" ? args : args[level];
      let traps = 0;
      const key = Object.keys(target)[0];
      if (key === undefined) {
        throw new Error("Fixture must contain fields");
      }
      if (kind === "getter") {
        Object.defineProperty(target, key, {
          enumerable: true,
          get() {
            traps++;
            throw new Error("private");
          },
        });
      } else if (kind === "proxy") {
        target = new Proxy(target, {
          getPrototypeOf() {
            traps++;
            throw new Error("private");
          },
        });
      } else if (kind === "revoked") {
        const revocable = Proxy.revocable(target, {});
        revocable.revoke();
        target = revocable.proxy;
      } else if (kind === "hidden") {
        Object.defineProperty(target, key, { enumerable: false });
      } else if (kind === "symbol") {
        target[Symbol("private")] = "secret";
      } else if (kind === "class") {
        Object.setPrototypeOf(target, { inherited: true });
      } else if (kind === "missing") {
        delete target[key];
      } else {
        target.secret = "private";
      }
      const candidate = level === "envelope" ? target : { ...args, [level]: target };
      expect(() => validateSmsCommand(candidate, operation)).toThrow(new Error(error));
      expect(traps).toBe(0);
    }
  },
);

it("rejects coercion hooks without executing", () => {
  const args = input();
  let calls = 0;
  args.commande.texte = {
    toString() {
      calls++;
      throw new Error("private");
    },
  };
  expect(() => validateSmsCommand(args, operation)).toThrow(new Error(error));
  expect(calls).toBe(0);
});

it.each([null, [], new Date(), new Map(), "json", 1, false])(
  "rejects non-plain input %s",
  (value) => {
    expect(() => validateSmsCommand(value, operation)).toThrow(new Error(error));
  },
);

it.each([
  "x".repeat(20000),
  "😀".repeat(5000),
  "x" + "\0".repeat(19999),
  " \nRe\u0301paration\t ",
  "\ufeff",
])("preserves exact valid UTF-8 text %#", (texte) => {
  const args = input();
  args.commande.texte = texte;
  expect(validateSmsCommand(args, operation).commande.texte).toBe(texte);
});

it.each(["2024-02-29T00:00:00.000Z", "0001-01-01T00:00:00.001Z", "9999-12-31T23:59:59.999Z"])(
  "accepts valid timestamp without freshness claim %s",
  (recu_le) => {
    const args = input();
    args.commande.recu_le = recu_le;
    expect(validateSmsCommand(args, operation).commande.recu_le).toBe(recu_le);
  },
);

it("preserves exact identifier casing and maximum safe revision", () => {
  const args = input();
  args.commande.compte_id = "a".repeat(64);
  args.commande.account_sid = "AC" + "ABcd".repeat(8);
  args.commande.message_sid = "SM" + "ABcd".repeat(8);
  args.permission.revision_profil = Number.MAX_SAFE_INTEGER;
  expect(validateSmsCommand(args, operation)).toMatchObject({
    commande: args.commande,
    permission: args.permission,
  });
});
