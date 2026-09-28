// OPSYS device identity tests cover `POST /tools/invoke` building the OPSYS `_meta` MCP payload
// (docs/architecture/IDEMPOTENCE.md §7) from `idempotencyKey`/`deviceId`/`deviceTimestamp`, on the
// same lightweight mock stack as `tools-invoke-http.cron-regression.test.ts`.
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const TEST_GATEWAY_TOKEN = "test-gateway-token-1234567890";
const resolveToolLoopDetectionConfig = () => ({ warnAt: 3 });
const runBeforeToolCallHook = async (args: { params: unknown }) => ({
  blocked: false as const,
  params: args.params,
});

let cfg: Record<string, unknown> = {};
let capturedMeta: Record<string, unknown> | undefined;
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

// The probe tool captures the ambient OPSYS `_meta` (real module, not mocked) at the moment
// `execute` runs, proving `invokeGatewayTool` sets it up (or not) before dispatch — exactly the
// boundary `tools-invoke-shared.ts` owns; whether `agent-bundle-mcp-runtime.ts` then forwards it
// onto the wire is covered separately (`agent-bundle-mcp-runtime.mcp-call-meta.test.ts`).
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

describe("tools invoke HTTP OPSYS device identity", () => {
  it("sets no ambient _meta when idempotencyKey is absent, even with a deviceId", async () => {
    const res = await invoke({ deviceId: "tel-employe-42", deviceTimestamp: "2026-09-28T14:32:05-04:00" });

    expect(res.status).toBe(200);
    expect(capturedMeta).toBeUndefined();
  });

  it("builds opsys/idempotencyKey, opsys/appareil, opsys/horodatageAppareil from the request body", async () => {
    const res = await invoke({
      idempotencyKey: "mut-1",
      deviceId: "tel-employe-42",
      deviceTimestamp: "2026-09-28T14:32:05-04:00",
    });

    expect(res.status).toBe(200);
    expect(capturedMeta).toEqual({
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
    });
  });

  it("omits opsys/appareil and opsys/horodatageAppareil when the device fields are absent", async () => {
    const res = await invoke({ idempotencyKey: "mut-2" });

    expect(res.status).toBe(200);
    expect(capturedMeta).toEqual({ "opsys/idempotencyKey": "mut-2" });
  });
});
