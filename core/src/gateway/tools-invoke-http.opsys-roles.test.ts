// OPSYS named device roles at the `/tools/invoke` boundary (docs/architecture/IDEMPOTENCE.md §7
// bis, hardened by PLAN T1.4-c4): the OPSYS device-role check runs off `authenticatedDeviceId` —
// host-minted by the HTTP boundary from a VERIFIED device token (see
// `tools-invoke-http.device-token-auth.test.ts` for that wiring, exercised end to end against a
// real paired device) — never off a client-declared `deviceId` in the request body. A device
// outside its role's tool scope is refused, closed by default, before the tool ever runs; an
// authorized device's `opsys/personne`/`opsys/role` reach the tool's ambient `_meta`; a body
// `deviceId` that disagrees with the authenticated one is refused outright. `authorizeOpsysDeviceToolFresh`
// itself (reading the role/appareils fragments from disk) is covered on its own in
// `opsys-device-roles.test.ts`; this file mocks it to test only `tools-invoke-shared.ts`'s use of
// the decision.
//
// PLAN T1.4-c6: an authorized device call never enters the agent tool list. It reaches the ONE
// department MCP server that `roles.json` names for the BARE tool name, through
// `resolveOpsysDeviceMcpTarget` (mocked here; covered over real stdio servers in
// `src/agents/opsys-device-mcp-target.test.ts` and over HTTP with a real device token in
// `tools-invoke-http.opsys-device-mcp.test.ts`). The core mock below therefore still lists a tool
// named `opsys_sonde`, the SAME name the device asks for: the device call must never be answered
// by it.
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
let capturedArgs: Record<string, unknown> | undefined;
let authorization: OpsysDeviceAuthorization = { ok: false, reason: "device_unknown" };
let deviceTargetKind: "resolved" | "not_found" | "unavailable" = "resolved";
let deviceCallFails = false;
const authorizeCalls: Array<{ deviceId: string; toolName: string }> = [];
const resolveTargetCalls: Array<{ serverName: string; toolName: string }> = [];
let disposeCount = 0;
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
  authorizeOpsysDeviceToolFresh: (deviceId: string, toolName: string) => {
    authorizeCalls.push({ deviceId, toolName });
    return authorization;
  },
}));

// The department-server side of the device door (PLAN T1.4-c6). The target answers with a marker
// that no core tool produces, and captures the ambient `_meta` and the arguments it was called with.
vi.mock("../agents/opsys-device-mcp-target.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  return {
    resolveOpsysDeviceMcpTarget: async (args: { serverName: string; toolName: string }) => {
      resolveTargetCalls.push({ serverName: args.serverName, toolName: args.toolName });
      if (deviceTargetKind !== "resolved") {
        return { kind: deviceTargetKind };
      }
      return {
        kind: "resolved",
        target: {
          call: async (callArgs: Record<string, unknown>) => {
            capturedMeta = currentMcpCallMeta();
            capturedArgs = callArgs;
            if (deviceCallFails) {
              throw new Error("department server closed the connection");
            }
            return { ok: true, resultat: { via: "department-server" }, rejoue: false };
          },
          dispose: async () => {
            disposeCount += 1;
          },
        },
      };
    },
  };
});

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
  capturedArgs = undefined;
  authorizeCalls.length = 0;
  authorization = { ok: false, reason: "device_unknown" };
  deviceTargetKind = "resolved";
  deviceCallFails = false;
  resolveTargetCalls.length = 0;
  disposeCount = 0;
});

async function invoke(body: Record<string, unknown>) {
  return await fetch(`http://127.0.0.1:${port}/tools/invoke`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${TEST_GATEWAY_TOKEN}`,
    },
    body: JSON.stringify({
      tool: "opsys_sonde",
      action: "status",
      args: {},
      sessionKey: "main",
      ...body,
    }),
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
    authorization = { ok: true, personne: "jdupont", role: "employee", serveur: "opsys_m4" };
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

describe("invokeGatewayTool: OPSYS device identity resolution from authenticatedDeviceId (PLAN T1.4-c4, T1.4-c6)", () => {
  // Exactly the shape `tools-invoke-http.ts` passes once it has verified a device token: a
  // trusted-operator-equivalent caller otherwise. The core mock lists a neutral `opsys_sonde`: the
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
  const authorized = (): OpsysDeviceAuthorization => ({
    ok: true,
    personne: "jdupont",
    role: "employee",
    serveur: "opsys_m4",
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
    expect(resolveTargetCalls).toEqual([]);
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
    expect(resolveTargetCalls).toEqual([]); // no department server was even contacted
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

  it("refuses, closed, a tool in the role's scope that names no department server (server_unknown)", async () => {
    authorization = { ok: false, reason: "server_unknown" };
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(403);
      expect(outcome.error.message).toContain("server_unknown");
    }
    expect(resolveTargetCalls).toEqual([]);
  });

  it("puts opsys/personne and opsys/role in the ambient _meta for an authorized authenticated device", async () => {
    authorization = authorized();
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", action: "status", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    expect(authorizeCalls).toEqual([
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
    ]);
    expect(capturedMeta).toEqual({ "opsys/personne": "jdupont", "opsys/role": "employee" });
  });

  it("combines opsys/personne, opsys/role and the idempotence keys in the same _meta", async () => {
    authorization = authorized();
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
    authorization = authorized();
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
    expect(resolveTargetCalls).toEqual([]);
  });

  it("accepts a request body deviceId that matches the authenticated device", async () => {
    authorization = authorized();
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
    expect(authorizeCalls).toEqual([
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
    ]);
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
    expect(resolveTargetCalls).toEqual([]); // the shared-secret caller keeps the core tool list
  });
});

describe("invokeGatewayTool: the OPSYS device door (PLAN T1.4-c6)", () => {
  const baseParams = () => ({
    cfg,
    toolCallIdPrefix: "test",
    senderIsOwner: true,
    operatorScopes: ["operator.admin"],
    conversationReadOrigin: "direct-operator" as const,
  });
  const asDevice = () => {
    authorization = { ok: true, personne: "jdupont", role: "employee", serveur: "opsys_m4" };
  };

  it("answers an authorized device from the department server, never from a core tool of the same name", async () => {
    asDevice();
    // The core mock lists an `opsys_sonde` that answers `via: "opsys_sonde"`; a shared-secret caller
    // gets it (previous describe). The device asks for the very same bare name.
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: { intervention_id: "int-1" }, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      // The OPSYS envelope of the department server, as is: what the app's interpreters read.
      expect(outcome.result).toEqual({
        ok: true,
        resultat: { via: "department-server" },
        rejoue: false,
      });
    }
    expect(capturedArgs).toEqual({ intervention_id: "int-1" });
  });

  it("looks the tool up on the ONE server the authorization names, under the same bare name it authorized", async () => {
    asDevice();
    await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(authorizeCalls).toEqual([
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
      { deviceId: "tel-employe-42", toolName: "opsys_sonde" },
    ]);
    expect(resolveTargetCalls).toEqual([{ serverName: "opsys_m4", toolName: "opsys_sonde" }]);
    expect(disposeCount).toBe(1); // the private MCP session is closed after the call
  });

  it("closes the private MCP session even when the department server call fails, and answers 500 (retryable)", async () => {
    asDevice();
    deviceCallFails = true;
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(500);
      expect(outcome.error.type).toBe("tool_error");
      // The wire error is generic: nothing of the department server's own failure reaches the phone.
      expect(outcome.error.message).toBe("tool execution failed");
    }
    expect(disposeCount).toBe(1);
  });

  it("reads non-object args as an empty object, like every other /tools/invoke tool", async () => {
    asDevice();
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: "pas-un-objet", sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(true);
    expect(capturedArgs).toEqual({});
  });

  it("answers 404 not_found when the department server does not list the tool", async () => {
    asDevice();
    deviceTargetKind = "not_found";
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(404);
      expect(outcome.error.type).toBe("not_found");
    }
    expect(capturedMeta).toBeUndefined();
  });

  it("answers 500 (retryable by the app) when the department server cannot be reached", async () => {
    asDevice();
    deviceTargetKind = "unavailable";
    const outcome = await invokeGatewayTool({
      ...baseParams(),
      input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
      authenticatedDeviceId: "tel-employe-42",
    });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(500);
      expect(outcome.error.type).toBe("tool_error");
    }
    expect(capturedMeta).toBeUndefined();
  });

  it.each([
    ["the bare tool name", ["opsys_sonde"]],
    ["the server namespace glob an agent policy would use", ["opsys_m4__*"]],
    ["the server__tool form", ["opsys_m4__opsys_sonde"]],
  ])(
    "honors the operator's gateway.tools.deny on %s, before any server is contacted",
    async (_label, deny) => {
      asDevice();
      cfg = { gateway: { tools: { deny } } };
      const outcome = await invokeGatewayTool({
        ...baseParams(),
        input: { tool: "opsys_sonde", args: {}, sessionKey: "main" },
        authenticatedDeviceId: "tel-employe-42",
      });

      expect(outcome.ok).toBe(false);
      if (!outcome.ok) {
        expect(outcome.status).toBe(403);
        expect(outcome.error.type).toBe("tool_call_blocked");
        expect(outcome.error.message).toContain("gateway.tools.deny");
      }
      expect(resolveTargetCalls).toEqual([]);
    },
  );

  it("does not need an owning agent or a session: several department agents and no default one", async () => {
    asDevice();
    // The generated OPSYS configuration: one agent per department, none marked default. A body with
    // no `agentId` and no agent-prefixed session key has no owner in that configuration.
    cfg = {
      agents: {
        entries: {
          "m01-demo": { name: "M1 démo" },
          "m04-demo": { name: "M4 démo" },
        },
      },
    };
    const app = { tool: "opsys_sonde", args: {} }; // what the mobile app sends: no agentId, no sessionKey

    const asSharedSecret = await invokeGatewayTool({ ...baseParams(), input: app });
    const asDeviceCall = await invokeGatewayTool({
      ...baseParams(),
      input: app,
      authenticatedDeviceId: "tel-employe-42",
    });

    // The agent path cannot serve that body (which is why the device door does not use it)...
    expect(asSharedSecret.ok).toBe(false);
    if (!asSharedSecret.ok) {
      expect(asSharedSecret.status).toBe(400);
      expect(asSharedSecret.error.type).toBe("invalid_request");
    }
    // ...and the device door does not need it.
    expect(asDeviceCall.ok).toBe(true);
  });
});
