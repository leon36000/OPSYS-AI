import { createHash, createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { createTempDirTracker } from "../../test/helpers/temp-dir.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import * as publicLoader from "../plugins/public-surface-loader.js";
import {
  createOpsysSmsIngressCapture,
  OPSYS_SMS_INGRESS_CAPTURE_REFUSED,
} from "./opsys-sms-ingress-capture.js";

// Fictitious owner/config/signature vectors only. No provider, HTTP, SQL or queue.
const ACCOUNT_SID = "AC" + "1".repeat(32);
const MESSAGE_SID = "SM" + "2".repeat(32);
const DESTINATION = "a".repeat(64);
const RECEIVED_AT = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const URL = "https://sms-fictif.example/webhooks/sms";
const SECRET = "cle-HMAC-fictive-unit-only";
const tempDirs = createTempDirTracker();
const permission = {
  profil_id: "sms-demo",
  revision_profil: 7,
  outil_m1: "opsys_m1__m1_recevoir_message_canal",
};
const form = () => ({
  AccountSid: ACCOUNT_SID,
  MessageSid: MESSAGE_SID,
  SmsSid: MESSAGE_SID,
  From: "+15145550102",
  To: "+15145550101",
  Body: "Québec 😀\r\n",
  NumMedia: "0",
});
function signed(input: Record<string, string> = form(), url = URL, credential = SECRET) {
  const base =
    url +
    Object.keys(input)
      .toSorted()
      .map((key) => `${key}${input[key]}`)
      .join("");
  return {
    form: input,
    signatureUrl: url,
    signature: createHmac("sha1", credential).update(base).digest("base64"),
  };
}
function fixture(publicWebhookUrl = URL) {
  let credential = SECRET;
  let current = true;
  const owner = {
    id: "sms",
    origin: "bundled" as const,
    rootDir: path.resolve("extensions/sms"),
    source: path.resolve("extensions/sms/index.ts"),
  };
  const selection = {
    accountId: "default",
    accountSid: ACCOUNT_SID,
    fromNumber: "+15145550101",
    publicWebhookUrl,
    permission: { ...permission },
  };
  const loader = vi
    .spyOn(publicLoader, "loadBundledPluginPublicArtifactModuleFromCandidatesSync")
    .mockReturnValue({ verifyTwilioSignature: smsApi.verifyTwilioSignature });
  const controller = createOpsysSmsIngressCapture({
    owner,
    selection,
    assertCurrent: () => {
      if (!current) {
        throw new Error("PRIVATE_OWNER_ERROR_FICTIF");
      }
    },
    getCurrentCredential: () => credential,
  });
  return {
    controller,
    owner,
    selection,
    loader,
    setCurrent: (value: boolean) => {
      current = value;
    },
    setCredential: (value: string) => {
      credential = value;
    },
  };
}
function payload(f = fixture()) {
  return f.controller.seal(f.controller.capture(signed()), RECEIVED_AT, DESTINATION);
}
function refused(run: () => unknown) {
  expect(run).toThrow(OPSYS_SMS_INGRESS_CAPTURE_REFUSED);
}
function mutable(value: unknown): Record<string, any> {
  // oxlint-disable-next-line prefer-structured-clone -- Exercise exact JSON storage, not RAM structured clone.
  return JSON.parse(JSON.stringify(value));
}
afterEach(() => {
  vi.restoreAllMocks();
  tempDirs.cleanup();
});

describe("SMS ingress capture standalone", () => {
  it("exports the real verifier and preserves both historical public exports", () => {
    expect(smsApi.getSmsRuntime).toBeTypeOf("function");
    expect(smsApi.setSmsRuntime).toBeTypeOf("function");
    expect(smsApi.verifyTwilioSignature({ ...signed(), url: URL, authToken: "" })).toBe(false);
    const input = signed();
    expect(
      smsApi.verifyTwilioSignature({ ...input, url: input.signatureUrl, authToken: SECRET }),
    ).toBe(true);
    expect(
      smsApi.verifyTwilioSignature({
        ...input,
        form: { ...input.form, Body: "modifié" },
        url: input.signatureUrl,
        authToken: SECRET,
      }),
    ).toBe(false);
  });
  it("uses the captured owner for the canonical public loader", () => {
    const f = fixture();
    expect(f.loader).toHaveBeenCalledWith({
      dirName: "sms",
      artifactCandidates: ["api"],
      owner: f.owner,
    });
    expect(Object.isFrozen(f.controller.capture(signed()))).toBe(true);
  });
  it("loads a real owner-bound public surface fixture independently of the HMAC test", () => {
    const root = tempDirs.make("fictif-sms-public-helper-");
    fs.writeFileSync(path.join(root, "package.json"), '{"type":"commonjs"}\n');
    fs.writeFileSync(path.join(root, "index.js"), "module.exports = {};\n");
    fs.writeFileSync(
      path.join(root, "api.js"),
      "module.exports = { verifyTwilioSignature: () => false };\n",
    );
    const c = createOpsysSmsIngressCapture({
      owner: { id: "sms", origin: "bundled", rootDir: root, source: path.join(root, "index.js") },
      selection: {
        accountId: "default",
        accountSid: ACCOUNT_SID,
        fromNumber: "+15145550101",
        publicWebhookUrl: URL,
        permission,
      },
      assertCurrent: () => {},
      getCurrentCredential: () => SECRET,
    });
    refused(() => c.capture(signed())); // real module loading; this fixture is not a positive HMAC proof
  });
  it("copies before mutation, seals one exact v2 and opens the same C/P", () => {
    const f = fixture();
    const input = signed();
    const handle = f.controller.capture(input);
    input.form.Body = "après capture";
    input.signature = "après capture";
    const p = f.controller.seal(handle, RECEIVED_AT, DESTINATION);
    expect(Object.keys(p)).toEqual(["version", "form", "capsule"]);
    expect(Object.keys(p.capsule)).toEqual([
      "version",
      "signature_url",
      "signature",
      "compte_id",
      "permission",
      "received_at",
      "commande_sha256",
      "destination_sha256",
    ]);
    expect(Object.keys(p.capsule.permission)).toEqual(["profil_id", "revision_profil", "outil_m1"]);
    expect(p.form.Body).toBe("Québec 😀\r\n");
    expect(p.capsule.signature).toBe(signed().signature);
    expect(p.capsule.received_at).toBe(RECEIVED_AT);
    expect(p.capsule.destination_sha256).toBe(DESTINATION);
    expect(JSON.stringify(p)).not.toContain(SECRET);
    expect(Object.isFrozen(p)).toBe(true);
    expect(Object.isFrozen(p.form)).toBe(true);
    expect(Object.isFrozen(p.capsule.permission)).toBe(true);
    const opened = f.controller.open(mutable(p), {
      id: MESSAGE_SID,
      receivedAt: RECEIVED_AT,
      destinationSha256: DESTINATION,
    });
    expect(opened.commande.recu_le).toBe("2026-10-10T12:00:00.123Z");
    expect(opened.commande.texte).toBe("Québec 😀\r\n");
    expect(opened.permission).toEqual(permission);
    expect(opened.commande.session_key).toBe("agent:opsys-agent-sms-demo:sms:direct:+15145550102");
    expect(opened.commande_sha256).toBe(p.capsule.commande_sha256);
    expect(opened).toEqual(
      validateSmsCommand(
        { version: 1, commande: opened.commande, permission },
        "opsys_runtime_recevoir_sms",
      ),
    );
    // Independent manual length-frame composition of the proof, not implementation helper reuse.
    const original = signed();
    const fields = [
      original.signatureUrl,
      original.signature,
      ...Object.keys(original.form)
        .toSorted()
        .flatMap((key) => [key, original.form[key as keyof typeof original.form]]),
    ];
    const manual =
      "opsys:m1:sms:preuve:v1:" +
      fields.map((v) => `${Buffer.byteLength(v, "utf8")}:${v}`).join("");
    expect(opened.commande.preuve_sha256).toBe(
      createHash("sha256").update(manual, "utf8").digest("hex"),
    );
  });
  it("is deterministic after JSON storage and does not change NFC or original time", () => {
    const f = fixture();
    const input = signed({ ...form(), Body: "e\u0301\t\r\n𐐀" });
    const p = f.controller.seal(f.controller.capture(input), RECEIVED_AT, DESTINATION);
    const opened = f.controller.open(mutable(p), {
      id: MESSAGE_SID,
      receivedAt: RECEIVED_AT,
      destinationSha256: DESTINATION,
    });
    expect(opened.commande.texte).toBe("e\u0301\t\r\n𐐀");
    expect(p.form.Body).not.toBe(p.form.Body.normalize("NFC"));
    expect(f.controller.seal(opened, RECEIVED_AT, DESTINATION)).toEqual(p);
  });
  it("refuses forged/foreign handles and contradictory second seal", () => {
    const f = fixture();
    const handle = f.controller.capture(signed());
    const p = f.controller.seal(handle, RECEIVED_AT, DESTINATION);
    expect(f.controller.seal(handle, RECEIVED_AT, DESTINATION)).toBe(p);
    refused(() => f.controller.seal({}, RECEIVED_AT, DESTINATION));
    refused(() => fixture().controller.seal(handle, RECEIVED_AT, DESTINATION));
    refused(() => f.controller.seal(handle, RECEIVED_AT + 1, DESTINATION));
    refused(() => f.controller.seal(handle, RECEIVED_AT, "b".repeat(64)));
  });
  it("rechecks owner closure and never echoes its exception", () => {
    const f = fixture();
    const p = payload(f);
    f.setCurrent(false);
    refused(() => f.controller.capture(signed()));
    refused(() =>
      f.controller.open(p, {
        id: MESSAGE_SID,
        receivedAt: RECEIVED_AT,
        destinationSha256: DESTINATION,
      }),
    );
    try {
      f.controller.seal({}, RECEIVED_AT, DESTINATION);
    } catch (e) {
      expect(String(e)).not.toContain("PRIVATE_OWNER_ERROR_FICTIF");
    }
    f.setCurrent(true);
    refused(() => f.controller.capture(signed()));
  });
  it("makes credential rotation sticky without resigning the old payload", () => {
    const f = fixture();
    const p = payload(f);
    const original = JSON.stringify(p);
    f.setCredential("autre-cle-fictive");
    refused(() =>
      f.controller.open(p, {
        id: MESSAGE_SID,
        receivedAt: RECEIVED_AT,
        destinationSha256: DESTINATION,
      }),
    );
    f.setCredential(SECRET);
    refused(() => f.controller.capture(signed()));
    expect(JSON.stringify(p)).toBe(original);
  });
  it("invalid signature fails without granting or retiring a valid current controller", () => {
    const f = fixture();
    refused(() => f.controller.capture({ ...signed(), signature: "fausse" }));
    expect(f.controller.capture(signed())).toBeDefined();
  });
  it.each([
    ["RCS", { From: "rcs:+15145550102" }],
    ["wrong SID", { AccountSid: "AC" + "3".repeat(32) }],
    ["conflicting aliases", { SmsSid: "SM" + "3".repeat(32) }],
    ["wrong recipient", { To: "+15145550109" }],
    ["media count", { NumMedia: "1" }],
    ["media field", { MediaUrl0: "https://media-fictif.example/x" }],
    ["blank body", { Body: " \t\u0085" }],
    ["media only", { Body: "", NumMedia: "1" }],
  ] as const)("closes %s despite a cryptographically valid signature", (_label, changes) => {
    const f = fixture();
    refused(() => f.controller.capture(signed({ ...form(), ...changes })));
  });
  it.each([
    "https://other-fictif.example/webhooks/sms",
    "https://sms-fictif.example/other",
    URL + "#fragment",
  ])("refuses signed URL substitution %s", (url) => {
    const f = fixture();
    refused(() => f.controller.capture(signed(form(), url)));
  });
  it("preserves configured query and strips only configured fragment", () => {
    const f = fixture(URL + "?fixed=1#rp=all");
    expect(f.controller.capture(signed(form(), URL + "?fixed=1"))).toBeDefined();
    refused(() => f.controller.capture(signed(form(), URL + "?fixed=2")));
    const g = fixture();
    expect(g.controller.capture(signed(form(), URL + "?request=%2f"))).toBeDefined();
  });
  it("rejects proxy/accessor without executing traps or getters", () => {
    const f = fixture();
    let reads = 0;
    const v = { ...signed() };
    Object.defineProperty(v, "form", {
      enumerable: true,
      get: () => {
        reads++;
        return form();
      },
    });
    refused(() => f.controller.capture(v));
    const proxy = new Proxy(signed(), {
      ownKeys: () => {
        reads++;
        return [];
      },
    });
    refused(() => f.controller.capture(proxy));
    const p = mutable(payload(f));
    Object.defineProperty(p.capsule, "permission", {
      enumerable: true,
      get: () => {
        reads++;
        return permission;
      },
    });
    refused(() =>
      f.controller.open(p, {
        id: MESSAGE_SID,
        receivedAt: RECEIVED_AT,
        destinationSha256: DESTINATION,
      }),
    );
    expect(reads).toBe(0);
  });
  it.each([true, Number.NaN, Infinity, -1, Number.MAX_SAFE_INTEGER])(
    "rejects unsafe monitor time %s",
    (time) => {
      const f = fixture();
      refused(() => f.controller.seal(f.controller.capture(signed()), time, DESTINATION));
    },
  );
  it("bounds the entire sealed payload at the exact UTF8 byte limit", () => {
    const f = fixture();
    const base = f.controller.seal(
      f.controller.capture(signed({ ...form(), Opaque: "" })),
      RECEIVED_AT,
      DESTINATION,
    );
    const bytes = Buffer.byteLength(JSON.stringify(base), "utf8");
    const exactInput = signed({ ...form(), Opaque: "x".repeat(262144 - bytes) });
    const exact = f.controller.seal(f.controller.capture(exactInput), RECEIVED_AT, DESTINATION);
    expect(Buffer.byteLength(JSON.stringify(exact), "utf8")).toBe(262144);
    const tooBig = f.controller.capture(signed({ ...form(), Opaque: "x".repeat(262145 - bytes) }));
    refused(() => f.controller.seal(tooBig, RECEIVED_AT, DESTINATION));
  });
  it("rejects malformed strings and exact UTF8 payload bounds", () => {
    const f = fixture();
    refused(() => f.controller.capture(signed({ ...form(), Body: "\ud800" })));
    refused(() => f.controller.capture(signed({ ...form(), "\ud800": "valid" })));
    refused(() => f.controller.capture(signed({ ...form(), Body: "😀".repeat(5001) })));
    refused(() => f.controller.capture(signed({ ...form(), Opaque: "x".repeat(262144) })));
    refused(() => f.controller.capture({ ...signed(), signature: "x".repeat(129) }));
    refused(() => f.controller.seal(f.controller.capture(signed()), RECEIVED_AT, "A".repeat(64)));
  });
  it.each([
    "outer-extra",
    "capsule-extra",
    "permission-extra",
    "version",
    "body",
    "hash",
    "permission",
    "time",
    "destination",
  ])("refuses stored %s without resealing", (kind) => {
    const f = fixture();
    const p = mutable(payload(f));
    if (kind === "outer-extra") {
      p.extra = true;
    }
    if (kind === "capsule-extra") {
      p.capsule.extra = true;
    }
    if (kind === "permission-extra") {
      p.capsule.permission.extra = true;
    }
    if (kind === "version") {
      p.version = 1;
    }
    if (kind === "body") {
      p.form.Body = "altéré";
    }
    if (kind === "hash") {
      p.capsule.commande_sha256 = "0".repeat(64);
    }
    if (kind === "permission") {
      p.capsule.permission.revision_profil++;
    }
    if (kind === "time") {
      p.capsule.received_at = true;
    }
    if (kind === "destination") {
      p.capsule.destination_sha256 = "b".repeat(64);
    }
    const original = JSON.stringify(p);
    refused(() =>
      f.controller.open(p, {
        id: MESSAGE_SID,
        receivedAt: RECEIVED_AT,
        destinationSha256: DESTINATION,
      }),
    );
    expect(JSON.stringify(p)).toBe(original);
  });
  it.each(["id", "time", "destination"])("binds open to original %s", (kind) => {
    const f = fixture();
    const p = payload(f);
    const context = { id: MESSAGE_SID, receivedAt: RECEIVED_AT, destinationSha256: DESTINATION };
    if (kind === "id") {
      context.id = "SM" + "3".repeat(32);
    }
    if (kind === "time") {
      context.receivedAt++;
    }
    if (kind === "destination") {
      context.destinationSha256 = "b".repeat(64);
    }
    refused(() => f.controller.open(p, context));
  });
});
