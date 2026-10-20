import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";

const hooks = vi.hoisted(() => ({
  connected: undefined as (() => void) | undefined,
  cleanup: "closed" as "closed" | "uncertain" | "throw",
  closed: 0,
  pids: [] as number[],
}));
// Only the lifecycle outcome is controllable; connection, wire and child closure stay real.
vi.mock("../agents/mcp-client-lifecycle.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../agents/mcp-client-lifecycle.js")>();
  return {
    ...actual,
    connectMcpClient: async (...args: Parameters<typeof actual.connectMcpClient>) => {
      await actual.connectMcpClient(...args);
      const transport = args[0].transport;
      if ("pid" in transport && typeof transport.pid === "number") {
        hooks.pids.push(transport.pid);
      }
      hooks.connected?.();
    },
    disposeMcpClient: async (...args: Parameters<typeof actual.disposeMcpClient>) => {
      const status = await actual.disposeMcpClient(...args);
      if (status === "closed") {
        hooks.closed++;
      }
      if (hooks.cleanup === "throw") {
        throw new Error("fictif-private-cleanup-error");
      }
      return hooks.cleanup === "uncertain" ? "uncertain" : status;
    },
  };
});
import { callOpsysMcpTool } from "./opsys-contexte-mcp.js";

const dirs: string[] = [];
beforeEach(() => {
  hooks.connected = undefined;
  hooks.cleanup = "closed";
  hooks.closed = 0;
  hooks.pids = [];
});
afterEach(() => cleanupTempDirs(dirs));

async function fixture(text = '{"fictif":true}', multipart = false, isError?: boolean) {
  const dir = makeTempDir(dirs, "opsys-mcp-guarded-");
  const script = path.join(dir, "server.mjs");
  const journal = path.join(dir, "wire.jsonl");
  await fs.writeFile(journal, "");
  await fs.writeFile(
    script,
    `
import readline from "node:readline";
import fs from "node:fs";
const journal = ${JSON.stringify(journal)};
const text = ${JSON.stringify(text)};
for await (const line of readline.createInterface({ input: process.stdin })) {
  const m = JSON.parse(line);
  fs.appendFileSync(journal, JSON.stringify(m) + "\\n");
  let result;
  if (m.method === "initialize") result = { protocolVersion:m.params.protocolVersion, capabilities:{tools:{}}, serverInfo:{name:"fictif",version:"1"} };
  if (m.method === "tools/call") result = { content: ${multipart ? '[{type:"text",text:text.slice(0,1)},{type:"text",text:text.slice(1)}]' : '[{type:"text",text}]'}${isError === undefined ? "" : `, isError: ${JSON.stringify(isError)}`} };
  if (result) process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:m.id,result}) + "\\n");
}
`,
  );
  const config: OpenClawConfig = {
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_runtime_fictif: { command: process.execPath, args: [script] },
      },
    },
  };
  return {
    params: {
      config,
      server: "opsys_runtime_fictif",
      tool: "opsys_runtime_lire_reception_sms",
      args: { version: 1, fictif: true },
      timeoutMs: 5000,
      signal: new AbortController().signal,
      awaitCleanup: true,
    },
    wire: async () =>
      (await fs.readFile(journal, "utf8"))
        .split("\n")
        .filter(Boolean)
        .map((s) => JSON.parse(s)),
  };
}

describe("private MCP request boundary", () => {
  it("rechecks a revocation after real connection and sends no tools/call", async () => {
    const f = await fixture();
    let current = true;
    hooks.connected = () => {
      current = false;
    };
    const request = callOpsysMcpTool({
      ...f.params,
      beforeRequest: () => {
        if (!current) {
          throw new Error("fictif-private-revocation");
        }
      },
    });
    await expect(request).rejects.toThrow("MCP request boundary rejected");
    expect((await f.wire()).some((m) => m.method === "initialize")).toBe(true);
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.closed).toBe(1);
    expect(hooks.pids).toHaveLength(1);
    expect(() => process.kill(hooks.pids[0], 0)).toThrow();
  });

  it("sends unchanged arguments without business metadata and awaits real child closure", async () => {
    const f = await fixture();
    const guard = vi.fn(() => undefined);
    await expect(
      callOpsysMcpTool({ ...f.params, beforeRequest: guard, maxResponseBytes: 15 }),
    ).resolves.toEqual({ fictif: true });
    expect(guard).toHaveBeenCalledOnce();
    const calls = (await f.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params).toEqual({ name: f.params.tool, arguments: f.params.args });
    expect(hooks.closed).toBe(1);
  });

  it("refuses a Promise returned by the synchronous guard before tools/call", async () => {
    const f = await fixture();
    await expect(
      callOpsysMcpTool({ ...f.params, beforeRequest: () => Promise.resolve() }),
    ).rejects.toThrow("MCP request boundary rejected");
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.closed).toBe(1);
  });

  it("captures the guard and cleanup policy before the connection await", async () => {
    const f = await fixture();
    const params = {
      ...f.params,
      beforeRequest: () => {
        throw new Error("fictif-revoked");
      },
    };
    hooks.connected = () => {
      Object.assign(params, { beforeRequest: () => undefined, awaitCleanup: false });
    };
    await expect(callOpsysMcpTool(params)).rejects.toThrow("MCP request boundary rejected");
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.closed).toBe(1);
  });

  it("contains a rejected Promise from an invalid asynchronous guard", async () => {
    const f = await fixture();
    await expect(
      callOpsysMcpTool({
        ...f.params,
        beforeRequest: () => Promise.reject(new Error("fictif-async-guard")),
      }),
    ).rejects.toThrow("MCP request boundary rejected");
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.closed).toBe(1);
  });

  it("captures the response quota before the connection await", async () => {
    const f = await fixture();
    const params = { ...f.params, maxResponseBytes: 1 };
    hooks.connected = () => {
      params.maxResponseBytes = 100;
    };
    await expect(callOpsysMcpTool(params)).rejects.toThrow("MCP response boundary rejected");
  });

  it("checks the signal again when the synchronous guard aborts", async () => {
    const f = await fixture();
    const controller = new AbortController();
    await expect(
      callOpsysMcpTool({
        ...f.params,
        signal: controller.signal,
        beforeRequest: () => controller.abort(),
      }),
    ).rejects.toThrow();
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.closed).toBe(1);
  });

  it.each([0, -1, 1.5, Number.NaN, Infinity, Number.MAX_SAFE_INTEGER, 16 * 1024 * 1024 + 1])(
    "refuses invalid quota %s before connection",
    async (maxResponseBytes) => {
      const f = await fixture();
      await expect(callOpsysMcpTool({ ...f.params, maxResponseBytes })).rejects.toThrow(
        "MCP response limit is invalid",
      );
      expect(await f.wire()).toEqual([]);
    },
  );

  it("accepts the exact UTF-8 byte limit", async () => {
    const text = '{"fictif":"é😀"}';
    const f = await fixture(text);
    await expect(
      callOpsysMcpTool({ ...f.params, maxResponseBytes: Buffer.byteLength(text, "utf8") }),
    ).resolves.toEqual({ fictif: "é😀" });
    expect(hooks.closed).toBe(1);
  });

  it("rejects one UTF-8 byte over the quota before parsing JSON", async () => {
    const text = '{"fictif":"é😀"}';
    const f = await fixture(text);
    await expect(
      callOpsysMcpTool({ ...f.params, maxResponseBytes: Buffer.byteLength(text, "utf8") - 1 }),
    ).rejects.toThrow("MCP response boundary rejected");
    expect(hooks.closed).toBe(1);
  });

  it("rejects multiple text blocks with a response limit", async () => {
    const f = await fixture('{"fictif":true}', true);
    await expect(callOpsysMcpTool({ ...f.params, maxResponseBytes: 100 })).rejects.toThrow(
      "MCP response boundary rejected",
    );
    expect(hooks.closed).toBe(1);
  });

  it("keeps legacy multipart parsing when no limit is requested", async () => {
    const f = await fixture('{"fictif":true}', true);
    await expect(callOpsysMcpTool(f.params)).resolves.toEqual({ fictif: true });
  });

  it.each(["uncertain", "throw"] as const)(
    "does not return an ACK on cleanup %s",
    async (outcome) => {
      const f = await fixture();
      hooks.cleanup = outcome;
      await expect(callOpsysMcpTool(f.params)).rejects.toThrow("MCP cleanup is uncertain");
      expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
      expect(hooks.closed).toBe(1);
    },
  );
  // Future opt-in boundary: MCP metadata must be checked before JSON envelope parsing.
  const historyText = JSON.stringify({
    ok: true,
    resultat: {
      schema: 1,
      confirme: true,
      instance_id: "00000000-0000-0000-0000-000000000001",
      demande_id: "abcdef012345",
      outil: "m9_clore_suivi_decision",
    },
  });

  it("refuses a marked MCP error even when its text claims confirmed Native history", async () => {
    const f = await fixture(historyText, false, true);
    const params = { ...f.params, requireSuccessfulResult: true, maxResponseBytes: 4096 };
    await expect(callOpsysMcpTool(params)).rejects.toThrow("MCP tool reported an error");
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    expect(hooks.closed).toBe(1);
    expect(hooks.pids).toHaveLength(1);
    expect(() => process.kill(hooks.pids[0], 0)).toThrow();
  });

  it.each([undefined, false])("accepts an unmarked successful MCP answer (%s)", async (isError) => {
    const f = await fixture(historyText, false, isError);
    const params = { ...f.params, requireSuccessfulResult: true, maxResponseBytes: 4096 };
    await expect(callOpsysMcpTool(params)).resolves.toEqual(JSON.parse(historyText));
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    expect(hooks.closed).toBe(1);
  });

  it.each([undefined, false])(
    "keeps legacy MCP error-envelope handling without opt-in (%s)",
    async (policy) => {
      const f = await fixture('{"ok":false,"erreur":"refus_metier_fictif"}', false, true);
      const params = { ...f.params, requireSuccessfulResult: policy };
      await expect(callOpsysMcpTool(params)).resolves.toEqual({
        ok: false,
        erreur: "refus_metier_fictif",
      });
      expect(hooks.closed).toBe(1);
    },
  );

  it("captures the MCP success policy before the real connection await", async () => {
    const f = await fixture(historyText, false, true);
    const params = { ...f.params, requireSuccessfulResult: true, maxResponseBytes: 4096 };
    hooks.connected = () => {
      params.requireSuccessfulResult = false;
    };
    await expect(callOpsysMcpTool(params)).rejects.toThrow("MCP tool reported an error");
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    expect(hooks.closed).toBe(1);
  });

  it("refuses the marked MCP error before parsing its private invalid JSON", async () => {
    const f = await fixture("fictif-private-non-json-history-body", false, true);
    const params = { ...f.params, requireSuccessfulResult: true, maxResponseBytes: 4096 };
    await expect(callOpsysMcpTool(params)).rejects.toThrow("MCP tool reported an error");
    expect(hooks.closed).toBe(1);
  });

  it("keeps the initial disabled MCP success policy after a connection-time escalation", async () => {
    const text = '{"ok":false,"erreur":"refus_metier_fictif"}';
    const f = await fixture(text, false, true);
    const params = { ...f.params, requireSuccessfulResult: false, maxResponseBytes: 4096 };
    hooks.connected = () => {
      params.requireSuccessfulResult = true;
    };
    await expect(callOpsysMcpTool(params)).resolves.toEqual(JSON.parse(text));
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    expect(hooks.closed).toBe(1);
  });
});
