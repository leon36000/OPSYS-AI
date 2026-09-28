// OPSYS named device roles at the `/tools/invoke` boundary (docs/architecture/IDEMPOTENCE.md §7
// bis): a device without OPSYS identity is unaffected; a device outside its role's tool scope is
// refused, closed by default, before the tool ever runs; an authorized device's `opsys/personne`/
// `opsys/role` reach the tool's ambient `_meta`. `authorizeOpsysDeviceTool` itself (reading the
// role/appareils fragments from disk) is covered on its own in `opsys-device-roles.test.ts`; this
// file mocks it to test only `tools-invoke-shared.ts`'s use of the decision, on the same
// lightweight mock stack as `tools-invoke-http.cron-regression.test.ts`.
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
      name: "automations",
      parameters: { type: "object", properties: { action: { type: "string" } } },
      execute: async () => {
        capturedMeta = currentMcpCallMeta();
        return { ok: true, via: "automations" };
      },
    },
  ];
  return {
    createOpenClawTools: () => tools,
  };
});

const { handleToolsInvokeHttpRequest } = await import("./tools-invoke-http.js");

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
      "x-openclaw-scopes": "operator.write",
    },
    body: JSON.stringify({ tool: "automations", action: "status", args: {}, sessionKey: "main", ...body }),
  });
}

describe("tools invoke HTTP OPSYS named device roles", () => {
  it("never calls the device authorization check when deviceId is absent (unaffected callers)", async () => {
    const res = await invoke({});

    expect(res.status).toBe(200);
    expect(authorizeCalls).toEqual([]);
    expect(capturedMeta).toBeUndefined();
  });

  it("refuses, closed, a device outside its role's tool scope, before the tool runs", async () => {
    authorization = { ok: false, reason: "tool_out_of_scope" };
    const res = await invoke({ deviceId: "tel-employe-42" });

    expect(res.status).toBe(403);
    const body = (await res.json()) as { ok: boolean; error: { type: string; message: string } };
    expect(body.ok).toBe(false);
    expect(body.error.type).toBe("tool_call_blocked");
    expect(body.error.message).toContain("tool_out_of_scope");
    expect(authorizeCalls).toEqual([{ deviceId: "tel-employe-42", toolName: "automations" }]);
    expect(capturedMeta).toBeUndefined(); // the tool never ran
  });

  it("refuses, closed, an unrecognized device", async () => {
    authorization = { ok: false, reason: "device_unknown" };
    const res = await invoke({ deviceId: "tel-inconnu" });

    expect(res.status).toBe(403);
  });

  it("refuses, closed, a device paired to a role with no tools.json entry", async () => {
    authorization = { ok: false, reason: "role_unknown" };
    const res = await invoke({ deviceId: "tel-employe-42" });

    expect(res.status).toBe(403);
  });

  it("puts opsys/personne and opsys/role in the ambient _meta for an authorized device", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
    const res = await invoke({ deviceId: "tel-employe-42" });

    expect(res.status).toBe(200);
    expect(capturedMeta).toEqual({ "opsys/personne": "jdupont", "opsys/role": "employee" });
  });

  it("combines opsys/personne, opsys/role and the idempotence keys in the same _meta", async () => {
    authorization = { ok: true, personne: "jdupont", role: "employee" };
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
      "opsys/personne": "jdupont",
      "opsys/role": "employee",
    });
  });
});
