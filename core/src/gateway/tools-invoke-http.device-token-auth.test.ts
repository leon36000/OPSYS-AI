// `/tools/invoke` device-token authentication (OPSYS-AI PLAN T1.4-c4, docs/architecture/
// IDEMPOTENCE.md §7 bis, docs/architecture/MOBILE.md "Appairage"): a paired OPSYS mobile device
// authenticates with ITS OWN device token — never the shared secret — `deviceId` comes from that
// verified token match, never the request body, and OPSYS device-role scoping (mocked here, the
// same lightweight mock stack as `tools-invoke-http.opsys-roles.test.ts` and
// `tools-invoke-http.cron-regression.test.ts`; `authorizeOpsysDeviceTool` itself is covered on its
// own in `opsys-device-roles.test.ts`) is mandatory once a device token authenticates.
//
// Auth is exercised for real: `requestDevicePairing`/`approveDevicePairing`/`ensureDeviceToken`/
// `revokeDeviceToken` inside `withOpenClawTestState` per test (same pattern as
// `http-auth-utils.paired-device.test.ts`, which provides the shared-state admission a vitest
// worker thread needs — a bare `OPENCLAW_HOME` fails with "Shared-state admission requires the
// host broker" in this project), so a bearer is verified by the
// REAL `checkGatewayHttpRequestAuth`/`checkHttpOperatorCredentials`/`verifyHttpOperatorDeviceToken`
// chain, not a stub. Tool dispatch itself is mocked (`./tool-resolution.js`) so these tests stay
// about authentication and OPSYS identity, not the unrelated owner-only gateway tool deny-list
// (`security/dangerous-tools.ts`) that a non-owner HTTP caller — which every device-token caller
// is, by design (`resolveOpenAiCompatibleHttpSenderIsOwner`, unchanged by this PLAN) — is subject
// to for REAL core tools.
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken, revokeDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import type { OpsysDeviceAuthorization } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

const SHARED_GATEWAY_TOKEN = "test-gateway-token-shared-1234567890";
const SHARED_GATEWAY_AUTH: ResolvedGatewayAuth = {
  mode: "token",
  token: SHARED_GATEWAY_TOKEN,
  password: undefined,
  allowTailscale: false,
};
const OPSYS_TOOL_NAME = "m4_pointer";
const resolveToolLoopDetectionConfig = () => ({ warnAt: 3 });
const runBeforeToolCallHook = async (args: { params: unknown }) => ({
  blocked: false as const,
  params: args.params,
});

let cfg: Record<string, unknown> = {};
let capturedMeta: Record<string, unknown> | undefined;
let authorization: OpsysDeviceAuthorization = { ok: false, reason: "device_unknown" };
const authorizeCalls: Array<{ deviceId: string; toolName: string }> = [];
const disableDefaultMemorySlot = () => false;
const noWarnLog = () => {};

vi.mock("../config/config.js", () => ({
  getRuntimeConfig: () => cfg,
}));

vi.mock("../config/io.js", () => ({
  getRuntimeConfig: () => cfg,
}));

vi.mock("../config/sessions.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../config/sessions.js")>();
  return {
    ...actual,
    resolveMainSessionKey: () => "agent:main:main",
  };
});

vi.mock("../logger.js", () => ({
  logWarn: noWarnLog,
}));

vi.mock("../agents/agent-tools.js", () => ({
  resolveToolLoopDetectionConfig,
}));

vi.mock("../agents/agent-tools.before-tool-call.js", () => ({
  runBeforeToolCallHook,
}));

vi.mock("../plugins/config-state.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../plugins/config-state.js")>();
  return {
    ...actual,
    isTestDefaultMemorySlotDisabled: disableDefaultMemorySlot,
  };
});

vi.mock("./opsys-device-roles.js", () => ({
  authorizeOpsysDeviceTool: (deviceId: string, toolName: string) => {
    authorizeCalls.push({ deviceId, toolName });
    return authorization;
  },
}));

// Bypasses `security/dangerous-tools.ts`'s owner-only gateway tool deny-list (unrelated to this
// PLAN: it applies to REAL core tools such as `automations`, and every device-token caller is a
// non-owner HTTP caller by design) so a single fake OPSYS-shaped tool is always visible, exactly
// like the real MCP-materialized tools `/tools/invoke` actually dispatches to in production.
vi.mock("./tool-resolution.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  return {
    resolveGatewayScopedTools: () => ({
      agentId: "main",
      workspaceDir: "/tmp/opsys-tools-invoke-device-token-test",
      tools: [
        {
          name: OPSYS_TOOL_NAME,
          parameters: { type: "object", properties: {} },
          execute: async () => {
            capturedMeta = currentMcpCallMeta();
            return { ok: true, via: OPSYS_TOOL_NAME };
          },
        },
      ],
    }),
  };
});

const { handleToolsInvokeHttpRequest } = await import("./tools-invoke-http.js");

let port = 0;
let server: ReturnType<typeof createServer> | undefined;

beforeAll(async () => {
  server = createServer((req, res) => {
    void (async () => {
      const handled = await handleToolsInvokeHttpRequest(req, res, {
        auth: SHARED_GATEWAY_AUTH,
      });
      if (handled) {
        return;
      }
      res.statusCode = 404;
      res.end("not found");
    })().catch((err: unknown) => {
      res.statusCode = 500;
      res.end(String(err));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server?.once("error", reject);
    server?.listen(0, "127.0.0.1", () => {
      const address = server?.address() as AddressInfo | null;
      port = address?.port ?? 0;
      resolve();
    });
  });
});

afterAll(async () => {
  if (!server) {
    return;
  }
  await new Promise<void>((resolve) => {
    server?.close(() => resolve());
  });
  server = undefined;
});

beforeEach(() => {
  cfg = {};
  capturedMeta = undefined;
  authorizeCalls.length = 0;
  authorization = { ok: false, reason: "device_unknown" };
});

/** A real approved "operator"-role paired device, in an isolated OpenClaw test state, per PLAN
 * T1.4-c4 ("réutilise le mécanisme natif" — same pairing/token issuance the mobile appairage flow
 * uses, R12 §1.3): `fn` gets the device's own real bearer token, verified by the unmocked auth
 * chain. The token is issued for the CURRENT shared gateway session generation, exactly like
 * `http-auth-utils.paired-device.test.ts`, since `verifyHttpOperatorDeviceToken` checks it. */
async function withPairedDeviceToken<T>(
  deviceId: string,
  fn: (deviceToken: string, ctx: { revoke: () => Promise<void> }) => Promise<T>,
): Promise<T> {
  return await withOpenClawTestState({ label: "opsys-tools-invoke-device-token" }, async () => {
    const scopes = ["operator.read", "operator.write"];
    const requested = await requestDevicePairing({
      deviceId,
      publicKey: `test-public-key-${randomUUID()}`,
      role: "operator",
      scopes,
    });
    const approved = await approveDevicePairing(requested.request.requestId, {
      callerScopes: scopes,
    });
    if (approved?.status !== "approved") {
      throw new Error(`pairing approval failed: ${approved?.status}`);
    }
    const generation = resolveSharedGatewaySessionGeneration(SHARED_GATEWAY_AUTH, []);
    if (!generation) {
      throw new Error("no shared gateway session generation for the test auth");
    }
    const issued = await ensureDeviceToken({
      deviceId,
      role: "operator",
      scopes,
      issuer: { kind: "shared-gateway-auth", generation },
    });
    if (!issued?.token) {
      throw new Error("no operator device token issued");
    }
    return await fn(issued.token, {
      revoke: async () => {
        const revoked = await revokeDeviceToken({ deviceId, role: "operator" });
        if (revoked.ok !== true) {
          throw new Error(`revoke failed: ${JSON.stringify(revoked)}`);
        }
      },
    });
  });
}

async function invoke(token: string, body: Record<string, unknown> = {}) {
  return await fetch(`http://127.0.0.1:${port}/tools/invoke`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ tool: OPSYS_TOOL_NAME, args: {}, sessionKey: "main", ...body }),
  });
}

describe("tools invoke HTTP device-token authentication", () => {
  it("authenticates a paired device by its own token; deviceId (and OPSYS identity) come from the verified token, not the body", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    await withPairedDeviceToken("tel-employe-42", async (deviceToken) => {
      const res = await invoke(deviceToken);

      expect(res.status).toBe(200);
      expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-42", toolName: OPSYS_TOOL_NAME }]);
      expect(capturedMeta).toEqual({ "opsys/personne": "jdupont", "opsys/role": "employee" });
    });
  });

  it("accepts a request body deviceId that matches the authenticated device", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    await withPairedDeviceToken("tel-employe-43", async (deviceToken) => {
      const res = await invoke(deviceToken, { deviceId: "tel-employe-43" });

      expect(res.status).toBe(200);
      expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-43", toolName: OPSYS_TOOL_NAME }]);
    });
  });

  it("refuses, closed, a request body deviceId that disagrees with the authenticated device — never silently preferring either one", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    await withPairedDeviceToken("tel-employe-44", async (deviceToken) => {
      const res = await invoke(deviceToken, { deviceId: "tel-dun-autre-appareil" });

      expect(res.status).toBe(403);
      const body = (await res.json()) as { ok: boolean; error: { type: string; message: string } };
      expect(body.ok).toBe(false);
      expect(body.error.type).toBe("tool_call_blocked");
      expect(body.error.message).toContain("does not match the authenticated device");
      // Refused before the OPSYS role check even runs — no ambiguity about which identity "won".
      expect(authorizeCalls).toEqual([]);
      expect(capturedMeta).toBeUndefined();
    });
  });

  it("refuses, closed, a device-token caller with no OPSYS role entry — never falling back to unscoped access", async () => {
    authorization = { ok: false, reason: "device_unknown" };
    await withPairedDeviceToken("tel-non-attribue", async (deviceToken) => {
      const res = await invoke(deviceToken);

      expect(res.status).toBe(403);
      const body = (await res.json()) as { ok: boolean; error: { type: string; message: string } };
      expect(body.error.type).toBe("tool_call_blocked");
      expect(body.error.message).toContain("device_unknown");
      expect(capturedMeta).toBeUndefined(); // the tool never ran
    });
  });

  it("rejects a revoked device token with 401, never falling back to shared-secret-style full access", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    await withPairedDeviceToken("tel-employe-45", async (deviceToken, ctx) => {
      await ctx.revoke();
      const res = await invoke(deviceToken);

      expect(res.status).toBe(401);
      expect(authorizeCalls).toEqual([]);
    });
  });

  it("rejects a bearer that matches no paired device's token with 401", async () => {
    await withPairedDeviceToken("tel-employe-46", async () => {
      const res = await invoke("un-jeton-invente-qui-ne-correspond-a-aucun-appareil");

      expect(res.status).toBe(401);
      expect(authorizeCalls).toEqual([]);
    });
  });

  it("still authenticates the trusted shared secret, and never attaches an OPSYS identity for it, even with a plausible body deviceId", async () => {
    // The shared secret proves possession of the gateway operator secret, not a specific device's
    // identity: it can never "borrow" a real deviceId the way the pre-T1.4-c4 code allowed.
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const res = await invoke(SHARED_GATEWAY_TOKEN, { deviceId: "tel-employe-42" });

    expect(res.status).toBe(200);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
  });
});
