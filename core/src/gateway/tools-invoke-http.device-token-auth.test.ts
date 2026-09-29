// `/tools/invoke` device-token authentication (OPSYS-AI PLAN T1.4-c4, docs/architecture/
// IDEMPOTENCE.md §7 bis, docs/architecture/MOBILE.md "Appairage"): a paired OPSYS mobile device
// authenticates with ITS OWN device token — never the shared secret — `deviceId` comes from that
// verified token match, never the request body, and OPSYS device-role scoping (mocked here, the
// same lightweight mock stack as `tools-invoke-http.opsys-roles.test.ts` and
// `tools-invoke-http.cron-regression.test.ts`; `authorizeOpsysDeviceTool` itself is covered on its
// own in `opsys-device-roles.test.ts`) is mandatory once a device token authenticates.
//
// PLAN T1.4-c6: an authorized device never enters the agent tool list. The department-server side
// of the device door (`resolveOpsysDeviceMcpTarget`) is mocked here; the same door is proven over
// HTTP with a real device token and the real roles/appareils fragments in
// `tools-invoke-http.opsys-device-mcp.test.ts`, and over real stdio servers in
// `src/agents/opsys-device-mcp-target.test.ts`.
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
let coreToolResolutions = 0;
const authorizeCalls: Array<{ deviceId: string; toolName: string }> = [];
const resolveTargetCalls: Array<{ serverName: string; toolName: string }> = [];
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

// The department-server side of the device door (PLAN T1.4-c6): captures the ambient `_meta` the
// door sets, and answers with an OPSYS envelope.
vi.mock("../agents/opsys-device-mcp-target.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  return {
    resolveOpsysDeviceMcpTarget: async (args: { serverName: string; toolName: string }) => {
      resolveTargetCalls.push({ serverName: args.serverName, toolName: args.toolName });
      return {
        kind: "resolved",
        target: {
          call: async () => {
            capturedMeta = currentMcpCallMeta();
            return { ok: true, resultat: { via: OPSYS_TOOL_NAME }, rejoue: false };
          },
          dispose: async () => {},
        },
      };
    },
  };
});

// Core tool resolution, for the trusted shared secret only (a device token never reaches it, which
// the tests below count). Bypasses `security/dangerous-tools.ts`'s owner-only gateway tool
// deny-list (it applies to REAL core tools such as `automations`, and every device-token caller is
// a non-owner HTTP caller by design) so a single fake tool named like the OPSYS tool is visible.
// This list is NOT what a device call is dispatched from: MCP servers' tools are never in it.
vi.mock("./tool-resolution.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  return {
    resolveGatewayScopedTools: () => {
      coreToolResolutions += 1;
      return {
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
      };
    },
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
  coreToolResolutions = 0;
  authorizeCalls.length = 0;
  resolveTargetCalls.length = 0;
  authorization = { ok: false, reason: "device_unknown" };
});

const EMPLOYEE_AUTHORIZATION: OpsysDeviceAuthorization = {
  ok: true,
  personne: "jdupont",
  role: "employee",
  serveur: "opsys_m4",
};

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
    authorization = EMPLOYEE_AUTHORIZATION;
    await withPairedDeviceToken("tel-employe-42", async (deviceToken) => {
      const res = await invoke(deviceToken);

      expect(res.status).toBe(200);
      expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-42", toolName: OPSYS_TOOL_NAME }]);
      expect(capturedMeta).toEqual({ "opsys/personne": "jdupont", "opsys/role": "employee" });
    });
  });

  it("dispatches the bare tool name the app sends to the department server, never to the core tool list (PLAN T1.4-c6)", async () => {
    authorization = EMPLOYEE_AUTHORIZATION;
    await withPairedDeviceToken("tel-employe-47", async (deviceToken) => {
      // The body an app really sends: the bare name, no agentId, no sessionKey.
      const res = await invoke(deviceToken, { sessionKey: undefined });

      expect(res.status).toBe(200);
      const body = (await res.json()) as { ok: boolean; result: unknown };
      expect(body).toEqual({
        ok: true,
        result: { ok: true, resultat: { via: OPSYS_TOOL_NAME }, rejoue: false },
      });
      expect(resolveTargetCalls).toEqual([{ serverName: "opsys_m4", toolName: OPSYS_TOOL_NAME }]);
      expect(coreToolResolutions).toBe(0);
    });
  });

  it("accepts a request body deviceId that matches the authenticated device", async () => {
    authorization = EMPLOYEE_AUTHORIZATION;
    await withPairedDeviceToken("tel-employe-43", async (deviceToken) => {
      const res = await invoke(deviceToken, { deviceId: "tel-employe-43" });

      expect(res.status).toBe(200);
      expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-43", toolName: OPSYS_TOOL_NAME }]);
    });
  });

  it("refuses, closed, a request body deviceId that disagrees with the authenticated device — never silently preferring either one", async () => {
    authorization = EMPLOYEE_AUTHORIZATION;
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
    authorization = EMPLOYEE_AUTHORIZATION;
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
    authorization = EMPLOYEE_AUTHORIZATION;
    const res = await invoke(SHARED_GATEWAY_TOKEN, { deviceId: "tel-employe-42" });

    expect(res.status).toBe(200);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
    // The shared secret keeps the core tool list, and never the device door.
    expect(coreToolResolutions).toBe(1);
    expect(resolveTargetCalls).toEqual([]);
  });
});
