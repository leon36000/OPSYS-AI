// OPSYS named device roles at the `/tools/invoke` boundary (docs/architecture/IDEMPOTENCE.md §7
// bis, hardened by PLAN T1.4-c4): the OPSYS device-role check runs off `authenticatedDeviceId` —
// host-minted by the HTTP boundary from a VERIFIED device token (see
// `tools-invoke-http.device-token-auth.test.ts` for that wiring, exercised end to end against a
// real paired device) — never off a client-declared `deviceId` in the request body. A device
// outside its role's tool scope is refused, closed by default, before the tool ever runs; an
// authorized device's `opsys/personne`/`opsys/role` reach the tool's ambient `_meta`; a body
// `deviceId` that disagrees with the authenticated one is refused outright. `authorizeOpsysDeviceTool`
// itself (reading the role/appareils fragments from disk) is covered on its own in
// `opsys-device-roles.test.ts`; this file mocks it to test only `tools-invoke-shared.ts`'s use of
// the decision.
//
// Two describe blocks:
// - HTTP, shared-secret bearer auth (same lightweight mock stack as
//   `tools-invoke-http.cron-regression.test.ts`): proves the shared secret can never trigger, nor
//   "borrow", an OPSYS device identity, no matter what `deviceId` a request body claims — the
//   identity fields are simply never populated for it (PLAN T1.4-c4 requirement 2).
// - `invokeGatewayTool` called directly with `authenticatedDeviceId` (the exact shape
//   `tools-invoke-http.ts` passes once it has verified a device token): exercises the identity
//   resolution logic itself — mismatch refusal, mandatory closed refusal, and `_meta`
//   construction — without needing a real paired device or the HTTP layer.
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { OpsysDeviceAuthorization } from "./opsys-device-roles.js";

const TEST_GATEWAY_TOKEN = "test-gateway-token-1234567890";
const resolveToolLoopDetectionConfig = () => ({ warnAt: 3 });
const runBeforeToolCallHook = async (args: { params: unknown }) => ({
  blocked: false as const,
  params: args.params,
});

let cfg: Record<string, unknown> = {};
let capturedMeta: Record<string, unknown> | undefined;
let authorization: OpsysDeviceAuthorization = { ok: false, reason: "device_unknown" };
const authorizeCalls: Array<{ deviceId: string; toolName: string }> = [];
const alwaysAuthorized = async () => ({ ok: true as const });
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

vi.mock("./auth.js", () => ({
  authorizeHttpGatewayConnect: alwaysAuthorized,
}));

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

vi.mock("../agents/openclaw-tools.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  const tools = [
    {
      name: "opsys_sonde",
      parameters: { type: "object", properties: { action: { type: "string" } } },
      execute: async () => {
        capturedMeta = currentMcpCallMeta();
        return { ok: true, via: "opsys_sonde" };
      },
    },
  ];
  return {
    createOpenClawTools: () => tools,
  };
});

const { handleToolsInvokeHttpRequest } = await import("./tools-invoke-http.js");
const { invokeGatewayTool } = await import("./tools-invoke-shared.js");

let port = 0;
let server: ReturnType<typeof createServer> | undefined;

beforeAll(async () => {
  server = createServer((req, res) => {
    void (async () => {
      const handled = await handleToolsInvokeHttpRequest(req, res, {
        auth: { mode: "token", token: TEST_GATEWAY_TOKEN, allowTailscale: false },
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

async function invoke(body: Record<string, unknown>) {
  return await fetch(`http://127.0.0.1:${port}/tools/invoke`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${TEST_GATEWAY_TOKEN}`,
    },
    body: JSON.stringify({ tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main", ...body }),
  });
}

describe("tools invoke HTTP: shared-secret bearer auth never borrows an OPSYS device identity", () => {
  it("never calls the device authorization check when deviceId is absent (unaffected callers)", async () => {
    const res = await invoke({});

    expect(res.status).toBe(200);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
  });

  it("never calls the device authorization check for a shared-secret caller even WITH a body deviceId (PLAN T1.4-c4: the shared secret can't \"borrow\" a device's identity)", async () => {
    // Configured to authorize, to prove the point: it is never even consulted for this caller.
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const res = await invoke({ deviceId: "tel-employe-42" });

    expect(res.status).toBe(200);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
  });

  it("still carries opsys/appareil for idempotence bookkeeping from a shared-secret caller's body deviceId, but never opsys/personne or opsys/role", async () => {
    const res = await invoke({
      deviceId: "tel-employe-42",
      idempotencyKey: "mut-1",
      deviceTimestamp: "2026-09-28T14:32:05-04:00",
    });

    expect(res.status).toBe(200);
    expect(capturedMeta).toEqual({
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
    });
    expect(authorizeCalls).toEqual([]);
  });
});

describe("invokeGatewayTool: OPSYS device identity resolution from authenticatedDeviceId (PLAN T1.4-c4)", () => {
  // Exactly the shape `tools-invoke-http.ts` passes once it has verified a device token: a
  // trusted-operator-equivalent caller otherwise. The probe tool is a neutral `opsys_sonde`: the
  // REAL (unmocked in this file) tool-resolution policy denies `automations` on the HTTP surface by
  // default (`security/dangerous-tools.ts`), whoever the caller — isolating these tests to the
  // identity logic in `tools-invoke-shared.ts`, not tool-visibility policy.
  const baseParams = () => ({
    cfg,
    toolCallIdPrefix: "test",
    senderIsOwner: true,
    operatorScopes: ["operator.admin"],
    conversationReadOrigin: "direct-operator" as const,
  });

  it("refuses, closed, an unrecognized authenticated device", async () => {
    authorization = { ok: false, reason: "device_unknown" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-inconnu",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(403);
      expect(outcome.error.type).toBe("tool_call_blocked");
      expect(outcome.error.message).toContain("device_unknown");
    }
    expect(authorizeCalls).toEqual([{ deviceId: "tel-inconnu", toolName: "opsys_sonde" }]);
    expect(capturedMeta).toBeUndefined();
  });

  it("refuses, closed, an authenticated device outside its role's tool scope, before the tool runs", async () => {
    authorization = { ok: false, reason: "tool_out_of_scope" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(403);
      expect(outcome.error.message).toContain("tool_out_of_scope");
    }
    expect(capturedMeta).toBeUndefined(); // the tool never ran
  });

  it("refuses, closed, an authenticated device paired to a role with no tools.json entry", async () => {
    authorization = { ok: false, reason: "role_unknown" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(403);
    }
  });

  it("puts opsys/personne and opsys/role in the ambient _meta for an authorized authenticated device", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-42", toolName: "opsys_sonde" }]);
    expect(capturedMeta).toEqual({ "opsys/personne": "jdupont", "opsys/role": "employee" });
  });

  it("combines opsys/personne, opsys/role and the idempotence keys in the same _meta", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: {
        tool: "opsys_sonde",
        action: "status",
        args: {},
        sessionKey: "main",
        idempotencyKey: "mut-1",
        deviceTimestamp: "2026-09-28T14:32:05-04:00",
      },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    expect(capturedMeta).toEqual({
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
      "opsys/personne": "jdupont",
      "opsys/role": "employee",
    });
  });

  it("refuses, closed, a request body deviceId that disagrees with the authenticated device — never silently preferring either one", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: {
        tool: "opsys_sonde",
        action: "status",
        args: {},
        sessionKey: "main",
        deviceId: "tel-dun-autre-appareil",
      },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(403);
      expect(outcome.error.message).toContain("does not match the authenticated device");
    }
    expect(authorizeCalls).toEqual([]); // refused before the OPSYS role check even runs
    expect(capturedMeta).toBeUndefined();
  });

  it("accepts a request body deviceId that matches the authenticated device", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: {
        tool: "opsys_sonde",
        action: "status",
        args: {},
        sessionKey: "main",
        deviceId: "tel-employe-42",
      },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-42", toolName: "opsys_sonde" }]);
  });

  it("never attaches an OPSYS identity, and never queries the role check, without an authenticated device — a body-only deviceId is not enough (the shared-secret/CLI/RPC caller shape)", async () => {
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: {
        tool: "opsys_sonde",
        action: "status",
        args: {},
        sessionKey: "main",
        deviceId: "tel-employe-42",
      },
      // No `authenticatedDeviceId`.
    });

    expect(outcome.ok).toBe(true);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
  });
});
