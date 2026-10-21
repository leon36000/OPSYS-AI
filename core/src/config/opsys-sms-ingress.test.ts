import { describe, expect, it } from "vitest";
import { AgentEntrySchema } from "./zod-schema.agent-runtime.js";

const smsIngress = {
  version: 1,
  accountId: "default",
  accountSid: "AC" + "ABcd".repeat(8),
};
const admission = { profileId: "m1-sms-fictif", profileRevision: 2, smsIngress };
const parse = (marker: unknown) =>
  AgentEntrySchema.safeParse({ id: "opsys-agent-m1-sms-fictif", opsysRuntimeAdmission: marker });

describe("OPSYS SMS ingress configuration (not host authority)", () => {
  it.each([1, 2, Number.MAX_SAFE_INTEGER])(
    "preserves selected marker and captured revision %s",
    (profileRevision) => {
      const marker = { ...admission, profileRevision };
      const result = parse(marker);
      expect(result.success).toBe(true);
      if (!result.success) {
        throw new Error("Expected the canonical SMS marker to parse");
      }
      expect(result.data.opsysRuntimeAdmission).toEqual(marker);
    },
  );

  it.each(["a", "a".repeat(64), "m1_sms-42"])(
    "preserves canonical account %s without normalization",
    (accountId) => {
      const marker = { ...admission, smsIngress: { ...smsIngress, accountId } };
      const result = parse(marker);
      expect(result.success).toBe(true);
      if (!result.success) {
        throw new Error("Expected a canonical account");
      }
      expect(result.data.opsysRuntimeAdmission).toEqual(marker);
    },
  );

  it.each([true, 0, 2, "1", null])("rejects invalid marker version %s", (version) => {
    expect(parse({ ...admission, smsIngress: { ...smsIngress, version } }).success).toBe(false);
  });

  it.each([
    "",
    " a",
    "a ",
    "a\n",
    "Default",
    "_default",
    "défaut",
    "a".repeat(65),
    "__proto__",
    "prototype",
    "constructor",
  ])("rejects noncanonical/reserved account %s", (accountId) => {
    expect(parse({ ...admission, smsIngress: { ...smsIngress, accountId } }).success).toBe(false);
  });

  it.each([
    "AC" + "a".repeat(31),
    "AC" + "a".repeat(33),
    "ac" + "a".repeat(32),
    "AC" + "g".repeat(32),
    " " + smsIngress.accountSid,
    smsIngress.accountSid + "\n",
  ])("rejects nonexact AccountSid %s", (accountSid) => {
    expect(parse({ ...admission, smsIngress: { ...smsIngress, accountSid } }).success).toBe(false);
  });

  it.each([undefined, null, true, 0, -1, 1.5, Number.NaN, Infinity, 9007199254740992, "2"])(
    "requires captured positive safe revision for selected marker %s",
    (profileRevision) => {
      expect(parse({ ...admission, profileRevision }).success).toBe(false);
    },
  );

  it.each(["a", "A-profile", "profile\n", " profile", "profile ", "a".repeat(65), "profilé"])(
    "requires canonical profile for selected marker %s",
    (profileId) => {
      expect(parse({ ...admission, profileId }).success).toBe(false);
    },
  );

  it.each([
    null,
    [],
    "sms",
    {},
    { ...smsIngress, extra: true },
    { version: 1, accountId: "default" },
    { version: 1, accountSid: smsIngress.accountSid },
    { accountId: "default", accountSid: smsIngress.accountSid },
  ])("rejects nonobject, incomplete or extended SMS selection %#", (marker) => {
    expect(parse({ ...admission, smsIngress: marker }).success).toBe(false);
  });

  it("keeps the admission envelope closed", () => {
    expect(parse({ ...admission, extra: true }).success).toBe(false);
  });

  it.each([
    { profileId: "existing-profile" },
    { profileId: "existing-profile", profileRevision: 2 },
  ])("preserves existing admission without SMS %#", (marker) => {
    const result = parse(marker);
    expect(result.success).toBe(true);
    if (!result.success) {
      throw new Error("Expected the legacy marker to parse");
    }
    expect(result.data.opsysRuntimeAdmission).toEqual(marker);
  });

  it("does not require OPSYS selection for ordinary agent configuration", () => {
    expect(AgentEntrySchema.parse({ id: "ordinary-agent" }).opsysRuntimeAdmission).toBeUndefined();
  });
});
