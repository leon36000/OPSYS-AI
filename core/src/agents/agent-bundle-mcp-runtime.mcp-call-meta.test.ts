import { existsSync } from "node:fs";
/**
 * OPSYS `_meta` propagation into the outbound MCP `tools/call` (docs/architecture/IDEMPOTENCE.md
 * §7 in OPSYS-AI): `ServerMcpRuntime.callTool` (`agent-bundle-mcp-runtime.ts`) must add the ambient
 * `withMcpCallMeta` payload as `_meta` on the real wire request when one is in scope, and send the
 * exact same request as before (no `_meta` key at all) otherwise. Verified over a real stdio
 * JSON-RPC child process (the same transport OPSYS MCP servers use), not a mocked SDK client, so
 * the assertion is on what the MCP server actually receives on the wire.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import { createSessionMcpRuntime, testing } from "./agent-bundle-mcp-runtime.js";
import type { SessionMcpRuntime } from "./agent-bundle-mcp-types.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";
import { ToolAuthorizationError } from "./tool-input-error.js";

const tempDirs: string[] = [];

afterEach(async () => {
  cleanupTempDirs(tempDirs);
  await testing.resetSessionMcpRuntimeManager();
});

/** A minimal stdio MCP server that echoes back the `_meta` it received on `tools/call`. */
async function startEchoMetaServer(): Promise<{ command: string; args: string[] }> {
  const workspaceDir = makeTempDir(tempDirs, "mcp-call-meta-");
  const serverPath = path.join(workspaceDir, "echo-meta-server.mjs");
  await fs.writeFile(
    serverPath,
    `
import readline from "node:readline";
async function handle(message) {
  let result;
  if (message.method === "initialize") {
    result = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "echo-meta", version: "1" } };
  }
  if (message.method === "tools/list") {
    result = { tools: [{ name: "echo_meta", inputSchema: { type: "object" } }] };
  }
  if (message.method === "tools/call") {
    (await import("node:fs")).appendFileSync(process.argv[1] + ".called", "1");
    const meta = message.params._meta ?? null;
    result = { content: [{ type: "text", text: JSON.stringify({ meta }) }] };
  }
  if (result) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\\n");
}
for await (const line of readline.createInterface({ input: process.stdin })) void handle(JSON.parse(line));
`,
  );
  return { command: process.execPath, args: [serverPath] };
}

async function callEchoMeta(
  options: {
    serverName?: string;
    sessionKey?: string;
    profile?: { agentId: string; profileId: string; profileRevision: number };
    beforeCall?: () => void;
    observeEmission?: (emitted: boolean) => void;
    observeCalls?: (count: number) => void;
    callTool?: (
      call: () => ReturnType<SessionMcpRuntime["callTool"]>,
    ) => ReturnType<SessionMcpRuntime["callTool"]>;
  } = {},
) {
  const server = await startEchoMetaServer();
  const serverName = options.serverName ?? "echo";
  const agents = options.profile
    ? {
        entries: {
          [options.profile.agentId]: {
            opsysRuntimeAdmission: {
              profileId: options.profile.profileId,
              profileRevision: options.profile.profileRevision,
            },
          },
        },
      }
    : undefined;
  const runtime = createSessionMcpRuntime({
    sessionId: "session-mcp-call-meta",
    sessionKey: options.sessionKey ?? "agent:test:session-mcp-call-meta",
    workspaceDir: makeTempDir(tempDirs, "mcp-call-meta-workspace-"),
    manifestRegistry: { plugins: [] },
    cfg: {
      plugins: { enabled: false },
      ...(agents ? { agents } : {}),
      mcp: { servers: { [serverName]: server } },
    },
  });
  try {
    if (options.beforeCall) {
      await runtime.getCatalog();
      options.beforeCall();
    }
    const call = () => runtime.callTool(serverName, "echo_meta", {});
    const result = options.callTool ? await options.callTool(call) : await call();
    const text = result.content.find((item) => item.type === "text")?.text;
    return JSON.parse(String(text)) as { meta: Record<string, unknown> | null };
  } finally {
    await runtime.dispose();
    const marker = `${server.args[0]}.called`;
    const emitted = existsSync(marker);
    options.observeEmission?.(emitted);
    options.observeCalls?.(emitted ? (await fs.readFile(marker, "utf8")).length : 0);
  }
}

describe("agent-bundle-mcp-runtime callTool OPSYS _meta", () => {
  it("does not back off a healthy server after repeated host authorization refusals", async () => {
    const meta = { "opsys/personne": "person.synthetic", "opsys/role": "owner" };
    const refusal = new ToolAuthorizationError("Synthetic caller revoked");
    let checks = 0;
    let emittedCalls: number | undefined;
    const received = await callEchoMeta({
      observeCalls: (count) => {
        emittedCalls = count;
      },
      callTool: async (call) => {
        for (let attempt = 0; attempt < 5; attempt += 1) {
          await expect(
            withMcpCallMeta(meta, call, () => {
              checks += 1;
              throw refusal;
            }),
          ).rejects.toBe(refusal);
        }
        return await withMcpCallMeta(meta, call, () => {
          checks += 1;
        });
      },
    });
    expect(checks).toBe(6);
    expect(emittedCalls).toBe(1);
    expect(received.meta).toStrictEqual(meta);
  });

  it("isolates denied and allowed host authorities on concurrent real wire requests", async () => {
    const deniedMeta = { "opsys/personne": "denied.synthetic", "opsys/role": "owner" };
    const allowedMeta = { "opsys/personne": "allowed.synthetic", "opsys/role": "owner" };
    const refusal = new ToolAuthorizationError("Synthetic concurrent caller revoked");
    let deniedCalls: number | undefined;
    let allowedCalls: number | undefined;
    const [denied, allowed] = await Promise.allSettled([
      withMcpCallMeta(
        deniedMeta,
        () => callEchoMeta({ observeCalls: (count) => (deniedCalls = count) }),
        () => {
          throw refusal;
        },
      ),
      withMcpCallMeta(
        allowedMeta,
        () => callEchoMeta({ observeCalls: (count) => (allowedCalls = count) }),
        () => {},
      ),
    ]);
    expect(denied).toStrictEqual({ status: "rejected", reason: refusal });
    expect(allowed).toStrictEqual({ status: "fulfilled", value: { meta: allowedMeta } });
    expect(deniedCalls).toBe(0);
    expect(allowedCalls).toBe(1);
  });

  it("rechecks host authority after awaited preparation and refuses before any tools/call emission", async () => {
    let authorityCurrent = true;
    let guardChecks = 0;
    let emitted: boolean | undefined;
    const refusal = new ToolAuthorizationError("Synthetic device revoked before emission");
    const meta = { "opsys/personne": "person.synthetic", "opsys/role": "owner" };
    await expect(
      withMcpCallMeta(
        meta,
        () =>
          callEchoMeta({
            beforeCall: () => {
              authorityCurrent = false;
            },
            observeEmission: (observed) => {
              emitted = observed;
            },
          }),
        () => {
          guardChecks += 1;
          if (!authorityCurrent) {
            throw refusal;
          }
        },
      ),
    ).rejects.toBe(refusal);
    expect(guardChecks).toBe(1);
    expect(emitted).toBe(false);
  });

  it("checks a current host authority without adding its callback to wire metadata", async () => {
    let guardChecks = 0;
    let emitted: boolean | undefined;
    const meta = { "opsys/personne": "person.synthetic", "opsys/role": "owner" };
    const received = await withMcpCallMeta(
      meta,
      () =>
        callEchoMeta({
          observeEmission: (observed) => {
            emitted = observed;
          },
        }),
      () => {
        guardChecks += 1;
      },
    );
    expect(guardChecks).toBe(1);
    expect(emitted).toBe(true);
    expect(received.meta).toStrictEqual(meta);
  });

  it("sends no _meta at all when no OPSYS call is in scope (unchanged behavior)", async () => {
    const received = await callEchoMeta();
    expect(received.meta).toBeNull();
  });

  it("forwards the ambient withMcpCallMeta payload as _meta on the real tools/call request", async () => {
    const meta = {
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
      "opsys/personne": "personne.synthetic",
      "opsys/role": "admin",
    };
    const received = await withMcpCallMeta(meta, callEchoMeta);
    expect(received.meta).toStrictEqual(meta);
  });

  it("forwards authenticated read identity and strips caller profile binding on the actual wire", async () => {
    const received = await withMcpCallMeta(
      {
        "opsys/personne": "person.synthetic",
        "opsys/role": "owner",
        "opsys/runtimeProfileId": "spoofed",
        "opsys/runtimeProfileRevision": "999",
        "opsys/runtimeServer": "attacker",
      },
      () =>
        callEchoMeta({
          serverName: "opsys_m5",
          sessionKey: "agent:opsys-agent-worker:session-mcp-call-meta",
          profile: { agentId: "opsys-agent-worker", profileId: "worker", profileRevision: 7 },
        }),
    );
    expect(received.meta).toStrictEqual({
      "opsys/personne": "person.synthetic",
      "opsys/role": "owner",
    });
  });

  it("preserves internal idempotency without inferring a device identity on the actual wire", async () => {
    const meta = {
      "opsys/idempotencyKey": "internal-call-synthetic-1",
      "opsys/appareil": "internal-synthetic",
      "opsys/horodatageAppareil": "2026-10-04T00:00:00Z",
    };
    const received = await withMcpCallMeta(meta, () =>
      callEchoMeta({
        serverName: "opsys_m5",
        sessionKey: "agent:opsys-agent-worker:session-mcp-call-meta",
        profile: { agentId: "opsys-agent-worker", profileId: "worker", profileRevision: 7 },
      }),
    );
    expect(received.meta).toStrictEqual({
      ...meta,
      "opsys/runtimeProfileId": "worker",
      "opsys/runtimeProfileRevision": "7",
      "opsys/runtimeServer": "opsys_m5",
    });
  });

  it("sends the host profile binding as flat MCP _meta on the actual stdio wire", async () => {
    const received = await withMcpCallMeta(
      {
        "opsys/runtimeProfileId": "spoofed",
        "opsys/runtimeProfileRevision": "999",
        "opsys/runtimeServer": "attacker",
      },
      () =>
        callEchoMeta({
          serverName: "opsys_m5",
          sessionKey: "agent:opsys-agent-worker:session-mcp-call-meta",
          profile: { agentId: "opsys-agent-worker", profileId: "worker", profileRevision: 7 },
        }),
    );
    expect(received.meta).toStrictEqual({
      "opsys/runtimeProfileId": "worker",
      "opsys/runtimeProfileRevision": "7",
      "opsys/runtimeServer": "opsys_m5",
    });
  });

  it("keeps authenticated device metadata and strips profile binding", async () => {
    const deviceMeta = {
      "opsys/idempotencyKey": "device-call-1",
      "opsys/appareil": "device.synthetic",
      "opsys/horodatageAppareil": "2026-10-01T10:00:00Z",
      "opsys/personne": "person.synthetic",
      "opsys/role": "owner",
      "opsys/runtimeProfileId": "spoofed",
      "opsys/runtimeProfileRevision": "999",
      "opsys/runtimeServer": "attacker",
    };
    const received = await withMcpCallMeta(deviceMeta, () =>
      callEchoMeta({
        serverName: "opsys_m5",
        sessionKey: "agent:opsys-agent-worker:session-mcp-call-meta",
        profile: { agentId: "opsys-agent-worker", profileId: "worker", profileRevision: 7 },
      }),
    );
    expect(received.meta).toStrictEqual({
      "opsys/idempotencyKey": "device-call-1",
      "opsys/appareil": "device.synthetic",
      "opsys/horodatageAppareil": "2026-10-01T10:00:00Z",
      "opsys/personne": "person.synthetic",
      "opsys/role": "owner",
    });
  });
});
