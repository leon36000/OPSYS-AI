import { createHmac } from "node:crypto";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import * as loader from "../plugins/public-surface-loader.js";
import { createOpsysSmsIngressCapture } from "./opsys-sms-ingress-capture.js";
import {
  createOpsysSmsReceiptGate,
  readSmsReceiptHostDestinationAssertion,
} from "./opsys-sms-receipt-gate.js";

it("exports the standalone receipt gate without introducing a production stub", async () => {
  const modulePath = "./opsys-sms-receipt-gate.js";
  await expect(import(modulePath)).resolves.toHaveProperty("createOpsysSmsReceiptGate");
});

type Call = Parameters<typeof callOpsysMcpTool>[0];
const REASON = "M1-SMS-RECEPTION-NON-RESOLUE";
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const PERMISSION = {
  profil_id: "sms-demo",
  revision_profil: 7,
  outil_m1: "opsys_m1__m1_recevoir_message_canal",
};
const decisions = [
  "DEMANDER_PRECISIONS",
  "TRANSMETTRE_M2",
  "CONVERSATION_DEJA_QUALIFIEE",
  "RETRAIT_CONSENTEMENT",
  "ESCALADE_PLAINTE",
  "ESCALADE_URGENCE",
  "TRANSFERT_EN_COURS",
];

function ack(
  call: Call,
  absent = false,
  decision = "DEMANDER_PRECISIONS",
): Record<string, unknown> {
  const operation =
    call.tool === "opsys_runtime_recevoir_sms"
      ? "opsys_runtime_recevoir_sms"
      : "opsys_runtime_lire_reception_sms";
  const c = validateSmsCommand(call.args, operation);
  return {
    version: 1,
    operation: operation === "opsys_runtime_recevoir_sms" ? "recevoir" : "lire",
    ok: true,
    etat: absent ? "absent" : "recu",
    intention_id: c.intention_id,
    commande_sha256: c.commande_sha256,
    arguments_sha256: c.arguments_sha256,
    permission: { ...c.permission },
    recu: absent
      ? null
      : {
          source: "sms:twilio",
          compte_id: c.commande.compte_id,
          account_sid: c.commande.account_sid,
          message_sid: c.commande.message_sid,
          agent_id: c.commande.agent_id,
          session_key: c.commande.session_key,
          signal_id: "sms:" + SID,
          signal_ligne_id: "a".repeat(64),
          decision,
          lead_ligne_id: ["TRANSMETTRE_M2", "CONVERSATION_DEJA_QUALIFIEE"].includes(decision)
            ? "b".repeat(64)
            : null,
          transfert_id: ["ESCALADE_PLAINTE", "ESCALADE_URGENCE", "TRANSFERT_EN_COURS"].includes(
            decision,
          )
            ? "tr-" + "c".repeat(20)
            : null,
        },
  };
}

// Real capture, HMAC and codec; the RPC seam is explicitly fictional, with no SQL credit.
function fixture(targetPatch: Record<string, unknown> = {}) {
  vi.spyOn(loader, "loadBundledPluginPublicArtifactModuleFromCandidatesSync").mockReturnValue({
    verifyTwilioSignature: smsApi.verifyTwilioSignature,
  });
  let current = true;
  let claim = true;
  const abort = new AbortController();
  const config: OpenClawConfig = {
    plugins: { enabled: false },
    mcp: {
      servers: {
        "opsys_runtime_sms-demo": {
          transport: "streamable-http",
          url: "https://mcp-fictif.example/runtime/sms-demo",
          headers: { Authorization: "Bearer fictif-unit-only" },
        },
      },
    },
  };
  const assertCurrent = () => {
    if (!current) {
      throw new Error("private-fictif-host");
    }
  };
  Object.assign(config.mcp!.servers!["opsys_runtime_sms-demo"], targetPatch);
  const capture = createOpsysSmsIngressCapture({
    owner: {
      id: "sms",
      origin: "bundled",
      rootDir: path.resolve("extensions/sms"),
      source: path.resolve("extensions/sms/index.ts"),
    },
    selection: {
      accountId: "default",
      accountSid: "AC" + "1".repeat(32),
      fromNumber: "+15145550101",
      publicWebhookUrl: "https://sms-fictif.example/webhook",
      permission: PERMISSION,
    },
    assertCurrent,
    getCurrentCredential: () => "fictif-hmac-only",
  });
  const form = {
    AccountSid: "AC" + "1".repeat(32),
    MessageSid: SID,
    From: "+15145550102",
    To: "+15145550101",
    Body: "Québec e\u0301 😀\r\n",
    NumMedia: "0",
  };
  const url = "https://sms-fictif.example/webhook";
  const signature = createHmac("sha1", "fictif-hmac-only")
    .update(
      url +
        Object.keys(form)
          .toSorted()
          .map((k) => k + form[k as keyof typeof form])
          .join(""),
    )
    .digest("base64");
  const handle = capture.capture({ form, signature, signatureUrl: url });
  const calls: Call[] = [];
  let respond: (call: Call) => Promise<unknown> = async (call) => ack(call);
  let beforeSend = () => {};
  const callTool = async (call: Call) => {
    beforeSend();
    call.beforeRequest?.();
    calls.push(call);
    return respond(call);
  };
  const gate = createOpsysSmsReceiptGate({
    capture,
    profileId: "sms-demo",
    getCurrentConfig: () => config,
    assertCurrent,
    signal: abort.signal,
    callTool,
  });
  const payload = gate.encodeCaptured(handle, TIME);
  const context = {
    id: SID,
    receivedAt: TIME,
    signal: abort.signal,
    assertClaimCurrent: () => {
      if (!claim) {
        throw new Error("private-fictif-claim");
      }
    },
  };
  return {
    gate,
    payload,
    context,
    calls,
    config,
    form,
    abort,
    setCurrent: (v: boolean) => {
      current = v;
    },
    setClaim: (v: boolean) => {
      claim = v;
    },
    respond: (fn: typeof respond) => {
      respond = fn;
    },
    beforeSend: (fn: () => void) => {
      beforeSend = fn;
    },
  };
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("standalone SMS receipt gate", () => {
  it("bounds an unresolved RPC and clears its deadline timer", async () => {
    const f = fixture();
    vi.useFakeTimers();
    f.respond(
      (call) =>
        new Promise((_, reject) => {
          call.signal.addEventListener("abort", () => reject(new Error("fictif-timeout")), {
            once: true,
          });
        }),
    );
    const pending = f.gate.resolveReceipt(f.payload, f.context);
    await vi.advanceTimersByTimeAsync(8000);
    expect(await pending).toEqual({ status: "unresolved", code: REASON });
    expect(f.calls).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(decisions)("accepts the actual Python decision %s through T0 only", async (decision) => {
    const f = fixture();
    f.respond(async (c) => ack(c, false, decision));
    const result = await f.gate.resolveReceipt(f.payload, f.context);
    expect(result.status).toBe("received");
    expect(f.calls).toHaveLength(1);
    expect(f.calls[0].tool).toBe("opsys_runtime_lire_reception_sms");
    if (result.status === "received") {
      expect(result.command.commande.texte).toBe(f.form.Body);
      expect(Object.isFrozen(result.receipt)).toBe(true);
      expect(result.receipt.decision).toBe(decision);
    }
  });

  it("receives only after proven absence using identical original C/P", async () => {
    const f = fixture();
    f.respond(async (c) => ack(c, c.tool === "opsys_runtime_lire_reception_sms"));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("received");
    expect(f.calls.map((c) => c.tool)).toEqual([
      "opsys_runtime_lire_reception_sms",
      "opsys_runtime_recevoir_sms",
    ]);
    expect(f.calls[0].args).toEqual(f.calls[1].args);
    expect(
      f.calls.every(
        (c) => c.maxResponseBytes === 8192 && c.awaitCleanup === true && c.timeoutMs === 8000,
      ),
    ).toBe(true);
  });

  it("resumes a lost receiving ACK with T0 and no duplicate receive", async () => {
    const f = fixture();
    let committed = false;
    f.respond(async (c) => {
      if (c.tool === "opsys_runtime_recevoir_sms") {
        committed = true;
        throw new Error("fictif-ack-lost");
      }
      return ack(c, !committed);
    });
    expect(await f.gate.resolveReceipt(f.payload, f.context)).toEqual({
      status: "unresolved",
      code: REASON,
    });
    expect(
      // oxlint-disable-next-line prefer-structured-clone -- Exercise the durable JSON payload round trip.
      (await f.gate.resolveReceipt(JSON.parse(JSON.stringify(f.payload)), f.context)).status,
    ).toBe("received");
    expect(f.calls.map((c) => c.tool)).toEqual([
      "opsys_runtime_lire_reception_sms",
      "opsys_runtime_recevoir_sms",
      "opsys_runtime_lire_reception_sms",
    ]);
    expect(f.calls[0].args).toEqual(f.calls[2].args);
  });

  it.each(["refus", "revision_perimee", "conflit", "forme_invalide", "inconnu"])(
    "does not receive for Python error %s",
    async (etat) => {
      const codes: Record<string, string> = {
        refus: "REJ-M1-SMS-AUTORITE-REFUSEE",
        revision_perimee: "REJ-M1-SMS-REVISION-PERIMEE",
        conflit: "REJ-M1-SMS-PROVENANCE-CONFLICTUELLE",
        forme_invalide: "REJ-M1-SMS-FORME-INVALIDE",
        inconnu: "M1-SMS-INCONNU",
      };
      const f = fixture();
      f.respond(async () => ({
        version: 1,
        operation: "lire",
        ok: false,
        etat,
        code: codes[etat],
      }));
      expect(await f.gate.resolveReceipt(f.payload, f.context)).toEqual({
        status: "unresolved",
        code: REASON,
      });
      expect(f.calls).toHaveLength(1);
    },
  );

  it.each([
    "operation",
    "intention_id",
    "commande_sha256",
    "arguments_sha256",
    "permission",
    "extra",
    "recu",
  ])("refuses changed ACK %s", async (field) => {
    const f = fixture();
    f.respond(async (c) => ({ ...ack(c, true), [field]: "fictif-invalid" }));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(1);
  });

  it.each([
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
  ])("refuses invalid receipt field %s", async (field) => {
    const f = fixture();
    f.respond(async (c) => {
      const a = ack(c);
      a.recu = { ...(a.recu as object), [field]: "fictif-invalid" };
      return a;
    });
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(1);
  });

  it.each(["host", "claim", "destination", "signal"])(
    "rechecks %s after connection before a mocked send",
    async (kind) => {
      const f = fixture();
      f.beforeSend(() => {
        if (kind === "host") {
          f.setCurrent(false);
        }
        if (kind === "claim") {
          f.setClaim(false);
        }
        if (kind === "signal") {
          f.abort.abort();
        }
        if (kind === "destination") {
          f.config.mcp!.servers!["opsys_runtime_sms-demo"].url =
            "https://different-fictif.example/";
        }
      });
      expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
      expect(f.calls).toHaveLength(0);
    },
  );

  it("does not accept an ACK after live destination changes", async () => {
    const f = fixture();
    f.respond(async (c) => {
      f.config.mcp!.servers!["opsys_runtime_sms-demo"].url = "https://changed-fictif.example/";
      return ack(c);
    });
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(1);
  });

  it.each(["host", "claim", "signal"])(
    "does not accept an ACK after %s revocation",
    async (kind) => {
      const f = fixture();
      f.respond(async (c) => {
        if (kind === "host") {
          f.setCurrent(false);
        }
        if (kind === "claim") {
          f.setClaim(false);
        }
        if (kind === "signal") {
          f.abort.abort();
        }
        return ack(c, true);
      });
      expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
      expect(f.calls).toHaveLength(1);
    },
  );

  it.each(decisions)("enforces conditional references for %s", async (decision) => {
    const f = fixture();
    f.respond(async (c) => {
      const a = ack(c, false, decision);
      a.recu = {
        ...(a.recu as object),
        lead_ligne_id: ["TRANSMETTRE_M2", "CONVERSATION_DEJA_QUALIFIEE"].includes(decision)
          ? null
          : "b".repeat(64),
        transfert_id: null,
      };
      return a;
    });
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(1);
  });

  it("refuses changed durable P before any request", async () => {
    const f = fixture();
    const payload = {
      ...f.payload,
      capsule: {
        ...f.payload.capsule,
        permission: { ...f.payload.capsule.permission, revision_profil: 8 },
      },
    };
    expect((await f.gate.resolveReceipt(payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(0);
  });

  it("does not change destination identity on Bearer rotation and uses a frozen target", async () => {
    const f = fixture();
    f.config.mcp!.servers!["opsys_runtime_sms-demo"].headers = {
      authorization: "Bearer fictif-rotated",
    };
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("received");
    expect(Object.isFrozen(f.calls[0].config?.mcp?.servers?.["opsys_runtime_sms-demo"])).toBe(true);
    expect(f.calls[0].config?.mcp?.servers?.["opsys_runtime_sms-demo"].headers).toEqual({
      authorization: "Bearer fictif-rotated",
    });
  });

  it.each([
    { command: "node" },
    { transport: "sse" },
    { enabled: false },
    { auth: "oauth" },
    { oauth: {} },
    { authProfileId: "fictif" },
    { sslVerify: false },
    { clientCert: "fictif" },
    { headers: { "x-secret": "fictif" } },
    { url: "https://u:p@fictif.example/" },
    { url: "https://fictif.example/?x=1" },
    { url: "https://fictif.example/#frag" },
  ])("refuses unsupported target %j", async (patch) => {
    const f = fixture();
    Object.assign(f.config.mcp!.servers!["opsys_runtime_sms-demo"], patch);
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(0);
  });

  it("refuses receiving absent and oversized decoded answers", async () => {
    const f = fixture();
    f.respond(async (c) => ack(c, true));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(2);
    f.respond(async (c) => ({ ...ack(c), extra: "x".repeat(8193) }));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(f.calls).toHaveLength(3);
  });

  it.each(["?", "#"])("refuses even an empty URL suffix %s before sealing", (suffix) => {
    expect(() => fixture({ url: "https://mcp-fictif.example/runtime/sms-demo" + suffix })).toThrow(
      REASON,
    );
  });

  it("rejects hostile ACK getters and proxies without invoking them", async () => {
    const f = fixture();
    const trap = vi.fn(() => {
      throw new Error("must-not-run");
    });
    f.respond(async () => new Proxy({}, { ownKeys: trap, getPrototypeOf: trap }));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(trap).not.toHaveBeenCalled();
    f.respond(async (c) => Object.defineProperty(ack(c), "recu", { get: trap }));
    expect((await f.gate.resolveReceipt(f.payload, f.context)).status).toBe("unresolved");
    expect(trap).not.toHaveBeenCalled();
  });
});

it("keeps the exact Gate received guard claim-independent, without native binding or adoption credit", async () => {
  const f = fixture();
  const result = await f.gate.resolveReceipt(f.payload, f.context);
  expect(result.status).toBe("received");
  const guard = readSmsReceiptHostDestinationAssertion(result)!;
  expect(typeof guard).toBe("function");
  f.setClaim(false);
  expect(() => guard()).not.toThrow();
  expect(f.calls).toHaveLength(1);
  expect(readSmsReceiptHostDestinationAssertion({ ...result })).toBeUndefined();
  const server = f.config.mcp!.servers!["opsys_runtime_sms-demo"];
  const old = server.url;
  server.url = "https://different-fictif.example/mcp";
  expect(() => guard()).toThrow(REASON);
  server.url = old;
  expect(() => guard()).toThrow(REASON);
  expect(readSmsReceiptHostDestinationAssertion(result)).toBeUndefined();
});
