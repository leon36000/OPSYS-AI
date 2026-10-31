// `/tools/invoke` for a paired OPSYS device, end to end through the device door (OPSYS-AI PLAN
// T1.4-c6, docs/architecture/MOBILE.md "Nom d'un outil de l'app au moteur").
//
// What is REAL here: the HTTP handler, the device-token authentication (a real pairing and a real
// bearer, like `tools-invoke-http.device-token-auth.test.ts`), the role check reading the REAL
// `opsys/roles.json` and `opsys/appareils.json` fragments from disk (the shape
// `src/opsys/openclaw.py` generates, `serveurs` included), the device door itself
// (`invokeOpsysDeviceTool`) and the department-server resolver (`resolveOpsysDeviceMcpTarget`).
//
// What is FAKED: only the transport to the department servers, i.e. `createSessionMcpRuntime` (a
// fake runtime that records the servers it was asked to include and every `tools/call`). The real
// runtime over real stdio child processes is exercised in
// `src/agents/opsys-device-mcp-target.test.ts`; `_meta` on the wire in
// `src/agents/agent-bundle-mcp-runtime.mcp-call-meta.test.ts`.
//
// The configuration mimics the generated OPSYS one: two departments, each with its own agent (none
// marked default, each denying the other's `opsys_mN__*` tools) and its own MCP server. Both servers
// list a tool named `m4_pointer`, the collision the device door must not fall for.
import { createHash, createHmac, randomUUID } from "node:crypto";
import fs from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import {
  withOpenClawTestState,
  type OpenClawTestState,
} from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import { resetOpsysDeviceRolesCacheForTesting } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

const SHARED_GATEWAY_TOKEN = "test-gateway-token-shared-1234567890";
const SHARED_GATEWAY_AUTH: ResolvedGatewayAuth = {
  mode: "token",
  token: SHARED_GATEWAY_TOKEN,
  password: undefined,
  allowTailscale: false,
};
const DEVICE_ID = "tel-employe-42";
const resolveToolLoopDetectionConfig = () => ({ warnAt: 3 });
let beforeToolCall: (() => void) | undefined;
const runBeforeToolCallHook = async (args: { params: unknown }) => {
  const before = beforeToolCall;
  beforeToolCall = undefined;
  before?.();
  return { blocked: false as const, params: args.params };
};

// The tools each fake department server lists (`tools/list`). `m4_pointer` is on BOTH servers.
const TOOLS_BY_SERVER: Record<string, string[]> = {
  opsys_m2: ["m2_lire_leads", "m4_pointer", "m3_lire_apprentissage_chantier"],
  opsys_m4: ["m4_pointer", "m4_lister_interventions"],
};

type ToolCall = { serverName: string; toolName: string; input: unknown; meta: unknown };
type FakeRuntime = { includeServerNames: string[]; toolCalls: ToolCall[]; disposed: boolean };

let cfg: Record<string, unknown> = {};
let coreToolResolutions = 0;
const runtimes: FakeRuntime[] = [];
const noWarnLog = () => {};
const disableDefaultMemorySlot = () => false;

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

// The agent tool list must never be consulted for a device call: it holds core tools, and it never
// holds a configured MCP server's tools. Calling it here is a failure, not a fallback.
vi.mock("./tool-resolution.js", () => ({
  resolveGatewayScopedTools: () => {
    coreToolResolutions += 1;
    throw new Error("the agent tool list must not be consulted for a device call");
  },
}));

// The one faked layer: the transport to the department servers. It honors `includeServerNames` the
// way the real runtime does (`loadSessionMcpConfig`), lists `TOOLS_BY_SERVER`, and refuses a
// `tools/call` for a server it does not hold, like the combined runtime ("not connected").
vi.mock("../agents/agent-bundle-mcp-runtime.js", async () => {
  const { currentMcpCallMeta } = await import("../agents/mcp-call-meta.js");
  return {
    createSessionMcpRuntime: (params: {
      cfg?: { mcp?: { servers?: Record<string, unknown> } };
      includeServerNames?: ReadonlySet<string>;
    }) => {
      const included = [...(params.includeServerNames ?? [])];
      const held = Object.keys(params.cfg?.mcp?.servers ?? {}).filter((name) =>
        included.includes(name),
      );
      const record: FakeRuntime = { includeServerNames: included, toolCalls: [], disposed: false };
      runtimes.push(record);
      const catalog = {
        version: 1,
        generatedAt: 0,
        servers: Object.fromEntries(
          held.map((name) => [
            name,
            {
              serverName: name,
              launchSummary: name,
              toolCount: TOOLS_BY_SERVER[name]?.length ?? 0,
            },
          ]),
        ),
        tools: held.flatMap((serverName) =>
          (TOOLS_BY_SERVER[serverName] ?? []).map((toolName) => ({
            serverName,
            safeServerName: serverName,
            toolName,
            inputSchema: { type: "object" },
            fallbackDescription: toolName,
          })),
        ),
      };
      return {
        getCatalog: async () => catalog,
        callTool: async (serverName: string, toolName: string, input: unknown) => {
          if (!held.includes(serverName)) {
            throw new Error(`bundle-mcp server "${serverName}" is not connected`);
          }
          record.toolCalls.push({ serverName, toolName, input, meta: currentMcpCallMeta() });
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  ok: true,
                  resultat: { serveur: serverName, outil: toolName },
                  rejoue: false,
                }),
              },
            ],
          };
        },
        dispose: async () => {
          record.disposed = true;
        },
        joinCleanup: async () => {},
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
  // The generated OPSYS shape: an agent and an MCP server per department, no default agent, and
  // each agent denying the other department's server (`opsys_mN__*`).
  cfg = {
    agents: {
      entries: {
        "m02-demo": { name: "M2 démo", tools: { deny: ["opsys_m4__*"] } },
        "m04-demo": { name: "M4 démo", tools: { deny: ["opsys_m2__*"] } },
      },
    },
    mcp: {
      servers: {
        opsys_m2: { url: "http://127.0.0.1:1/mcp/m02-demo", transport: "streamable-http" },
        opsys_m4: { url: "http://127.0.0.1:1/mcp/m04-demo", transport: "streamable-http" },
      },
    },
  };
  coreToolResolutions = 0;
  runtimes.length = 0;
  beforeToolCall = undefined;
  resetOpsysDeviceRolesCacheForTesting();
});

/** What `opsys metier openclaw configurer` and `opsys metier appareils appairer` write next to openclaw.json. */
function writeOpsysFragments(
  state: OpenClawTestState,
  fragments: { roles: unknown; appareils: unknown },
): void {
  const dir = path.join(path.dirname(state.configPath), "opsys");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "roles.json"), JSON.stringify(fragments.roles));
  fs.writeFileSync(path.join(dir, "appareils.json"), JSON.stringify(fragments.appareils));
}

const ROLES_FRAGMENT = {
  roles: {
    employee: [
      "m4_pointer",
      "m4_lister_interventions",
      "m4_statut_intervention",
      "m4_sans_serveur",
    ],
    seller: ["m2_lire_leads"],
    admin: ["m2_lire_leads", "m4_pointer", "m4_lister_interventions"],
  },
  serveurs: {
    m4_pointer: "opsys_m4",
    m4_lister_interventions: "opsys_m4",
    // Carried by opsys_m4 according to the file, but that server does not list it.
    m4_statut_intervention: "opsys_m4",
    m2_lire_leads: "opsys_m2",
    // `m4_sans_serveur` has no entry: in scope, but the core will not guess its server.
  },
};

const APPAREILS_FRAGMENT = {
  appareils: {
    [DEVICE_ID]: { personne: "jdupont", role: "employee" },
    "tel-vendeur-7": { personne: "mtremblay", role: "seller" },
  },
};

/** A real approved "operator"-role paired device in an isolated OpenClaw test state (the same
 * pairing and token issuance the mobile appairage flow uses), with the OPSYS fragments on disk. */
async function withPairedDevice<T>(
  deviceId: string,
  fn: (deviceToken: string, state: OpenClawTestState) => Promise<T>,
): Promise<T> {
  return await withOpenClawTestState({ label: "opsys-tools-invoke-device-mcp" }, async (state) => {
    writeOpsysFragments(state, { roles: ROLES_FRAGMENT, appareils: APPAREILS_FRAGMENT });
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
    return await fn(issued.token, state);
  });
}

/** The body the mobile app sends (`mobile/src/protocole/client.ts`): the bare tool name, and no
 * `agentId` and no `sessionKey`. */
async function invokeAsApp(token: string, body: Record<string, unknown>) {
  return await fetch(`http://127.0.0.1:${port}/tools/invoke`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
}

type InvokeBody = {
  ok: boolean;
  result?: unknown;
  error?: { type: string; message: string };
};

describe("tools invoke HTTP: a device token reaches the department MCP tool by the bare name the app sends", () => {
  it("attests only the verified admin device and exact read arguments", async () => {
    const secret = "qa-device-attestation-secret-01234567890123456789";
    const mcpToken = "qa-mcp-bearer-distinct-01234567890123456789";
    const generation = "ab".repeat(16);
    const proof = createHmac("sha256", secret).update("opsys.device.generation.v1").digest("hex");
    const generationServer = createServer((req, res) => {
      if (req.url !== "/internal/opsys-device-generation" || req.headers.authorization !== `Bearer ${mcpToken}` ||
          req.headers["x-opsys-gateway-proof"] !== proof) {
        res.writeHead(403).end();
        return;
      }
      res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ generation }));
    });
    await new Promise<void>((resolve) => generationServer.listen(0, "127.0.0.1", resolve));
    const generationPort = (generationServer.address() as AddressInfo).port;
    vi.stubEnv("OPSYS_MCP_DEVICE_ATTESTATION_SECRET", secret);
    vi.stubEnv("OPSYS_MCP_JETON", mcpToken);
    vi.stubEnv("OPSYS_MCP_DEVICE_GENERATION_URL", `http://127.0.0.1:${generationPort}/internal/opsys-device-generation`);
    try {
      await withPairedDevice(DEVICE_ID, async (deviceToken, state) => {
        writeOpsysFragments(state, {
          roles: { roles: { ...ROLES_FRAGMENT.roles, admin: ["m3_lire_apprentissage_chantier"] },
                   serveurs: { ...ROLES_FRAGMENT.serveurs, m3_lire_apprentissage_chantier: "opsys_m2" } },
          appareils: { appareils: { [DEVICE_ID]: { personne: "nathan.fictif", role: "admin" } } },
        });
        resetOpsysDeviceRolesCacheForTesting();
        const args = { wct_id: "f".repeat(64), coupure_utc: "2030-06-08T12:00:00-04:00" };
        const forged = await invokeAsApp(deviceToken, {
          tool: "m3_lire_apprentissage_chantier", deviceId: "autre-appareil", args,
        });
        expect(forged.status).toBe(403);
        const response = await invokeAsApp(deviceToken, { tool: "m3_lire_apprentissage_chantier", args });
        expect(response.status).toBe(200);
        const meta = runtimes.at(-1)?.toolCalls[0]?.meta as Record<string, string>;
        expect(meta["opsys/personne"]).toBe("nathan.fictif");
        expect(meta["opsys/role"]).toBe("admin");
        const [content, signature] = meta["opsys/attestationAppareil"].split(".");
        expect(signature).toBe(createHmac("sha256", secret).update(content).digest("hex"));
        const packet = JSON.parse(Buffer.from(content, "base64url").toString("utf8")) as unknown[];
        expect(packet.slice(0, 6)).toEqual([1, generation, DEVICE_ID, "nathan.fictif", "admin",
                                          "m3_lire_apprentissage_chantier"]);
        expect(packet[6]).toBe(createHash("sha256").update(JSON.stringify([args.wct_id, args.coupure_utc])).digest("hex"));
      });
    } finally {
      vi.unstubAllEnvs();
      await new Promise<void>((resolve, reject) => generationServer.close((err) => err ? reject(err) : resolve()));
    }
  });

  it.each(["personne", "role", "serveur", "scope"] as const)(
    "refuses an in-flight %s change without redirecting and admits a fresh legitimate request",
    async (changed) => {
      await withPairedDevice(DEVICE_ID, async (deviceToken, state) => {
        const roles = {
          roles: { ...ROLES_FRAGMENT.roles },
          serveurs: { ...ROLES_FRAGMENT.serveurs },
        };
        const appareils = { appareils: { ...APPAREILS_FRAGMENT.appareils } };
        const fragmentPath = path.join(path.dirname(state.configPath), "opsys", "appareils.json");
        fs.utimesSync(fragmentPath, 1000, 1000);
        const originalStat = fs.statSync(fragmentPath);
        beforeToolCall = () => {
          if (changed === "personne") {
            appareils.appareils[DEVICE_ID] = { personne: "mdurand", role: "employee" };
          } else if (changed === "role") {
            appareils.appareils[DEVICE_ID] = { personne: "jdupont", role: "admin" };
          } else if (changed === "serveur") {
            roles.serveurs.m4_pointer = "opsys_m2";
          } else {
            roles.roles.employee = roles.roles.employee.filter((tool) => tool !== "m4_pointer");
          }
          writeOpsysFragments(state, { roles, appareils });
          // The person replacement aliases both cache keys; live authority must still win.
          if (changed === "personne") {
            fs.utimesSync(fragmentPath, originalStat.atime, originalStat.mtime);
            expect(fs.statSync(fragmentPath).size).toBe(originalStat.size);
            expect(fs.statSync(fragmentPath).mtimeMs).toBe(originalStat.mtimeMs);
          }
        };
        const denied = await invokeAsApp(deviceToken, { tool: "m4_pointer", args: {} });
        expect(denied.status).toBe(403);
        expect(((await denied.json()) as InvokeBody).error?.type).toBe("tool_call_blocked");
        expect(runtimes).toHaveLength(1);
        expect(runtimes[0]?.toolCalls).toStrictEqual([]);
        expect(runtimes[0]?.disposed).toBe(true);
        const tool = changed === "scope" ? "m4_lister_interventions" : "m4_pointer";
        const allowed = await invokeAsApp(deviceToken, { tool, args: {} });
        expect(allowed.status).toBe(200);
        expect(runtimes).toHaveLength(2);
        expect(runtimes[1]?.disposed).toBe(true);
        expect(runtimes[1]?.toolCalls).toStrictEqual([
          {
            serverName: changed === "serveur" ? "opsys_m2" : "opsys_m4",
            toolName: tool,
            input: {},
            meta: {
              "opsys/personne": changed === "personne" ? "mdurand" : "jdupont",
              "opsys/role": changed === "role" ? "admin" : "employee",
            },
          },
        ]);
        expect(coreToolResolutions).toBe(0);
      });
    },
  );

  it("resolves m4_pointer on opsys_m4 only, calls it under that raw name with the authenticated identity, and returns the OPSYS envelope", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, {
        tool: "m4_pointer",
        args: { intervention_id: "int-1" },
        idempotencyKey: "mut-1",
        deviceId: DEVICE_ID,
        deviceTimestamp: "2026-09-28T14:32:05-04:00",
      });

      expect(res.status).toBe(200);
      // The envelope the department server wrote, as is: what the app's interpreters read.
      expect((await res.json()) as InvokeBody).toEqual({
        ok: true,
        result: { ok: true, resultat: { serveur: "opsys_m4", outil: "m4_pointer" }, rejoue: false },
      });
      // One private runtime, holding opsys_m4 and nothing else, closed after the call.
      expect(runtimes).toHaveLength(1);
      expect(runtimes[0]?.includeServerNames).toEqual(["opsys_m4"]);
      expect(runtimes[0]?.disposed).toBe(true);
      // The raw tool name went to opsys_m4 (not opsys_m2, which also lists m4_pointer), with the
      // identity from the VERIFIED token and the idempotence keys, and the arguments as sent.
      expect(runtimes[0]?.toolCalls).toEqual([
        {
          serverName: "opsys_m4",
          toolName: "m4_pointer",
          input: { intervention_id: "int-1" },
          meta: {
            "opsys/idempotencyKey": "mut-1",
            "opsys/appareil": DEVICE_ID,
            "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00",
            "opsys/personne": "jdupont",
            "opsys/role": "employee",
          },
        },
      ]);
      // Neither the agent tool list nor any session or agent was needed.
      expect(coreToolResolutions).toBe(0);
    });
  });

  it("serves a read-only call (no idempotency key) with the identity alone in _meta", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m4_lister_interventions", args: {} });

      expect(res.status).toBe(200);
      expect(runtimes[0]?.toolCalls[0]).toMatchObject({
        serverName: "opsys_m4",
        toolName: "m4_lister_interventions",
        meta: { "opsys/personne": "jdupont", "opsys/role": "employee" },
      });
    });
  });

  it("refuses the model-facing materialized name: only the bare name is in scope", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "opsys_m4__m4_pointer", args: {} });

      expect(res.status).toBe(403);
      const body = (await res.json()) as InvokeBody;
      expect(body.error?.type).toBe("tool_call_blocked");
      expect(body.error?.message).toContain("tool_out_of_scope");
      expect(runtimes).toHaveLength(0); // no department server was contacted
    });
  });

  it("refuses a tool outside the role's scope, even one that exists on a department server", async () => {
    await withPairedDevice("tel-vendeur-7", async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m4_pointer", args: {} });

      expect(res.status).toBe(403);
      expect(((await res.json()) as InvokeBody).error?.message).toContain("tool_out_of_scope");
      expect(runtimes).toHaveLength(0);
    });
  });

  it("serves the seller's own tool from ITS server, not from the employee's", async () => {
    await withPairedDevice("tel-vendeur-7", async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m2_lire_leads", args: {} });

      expect(res.status).toBe(200);
      expect(runtimes).toHaveLength(1);
      expect(runtimes[0]?.includeServerNames).toEqual(["opsys_m2"]);
      expect(runtimes[0]?.toolCalls[0]).toMatchObject({
        serverName: "opsys_m2",
        toolName: "m2_lire_leads",
        meta: { "opsys/personne": "mtremblay", "opsys/role": "seller" },
      });
    });
  });

  it("refuses a tool in scope that roles.json gives no server: the core never guesses one", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m4_sans_serveur", args: {} });

      expect(res.status).toBe(403);
      expect(((await res.json()) as InvokeBody).error?.message).toContain("server_unknown");
      expect(runtimes).toHaveLength(0);
    });
  });

  it("answers 404 when the named server does not list the tool", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m4_statut_intervention", args: {} });

      expect(res.status).toBe(404);
      expect(((await res.json()) as InvokeBody).error?.type).toBe("not_found");
      expect(runtimes).toHaveLength(1);
      expect(runtimes[0]?.disposed).toBe(true);
      expect(runtimes[0]?.toolCalls).toEqual([]);
    });
  });

  it("honors the operator's gateway.tools.deny on the server namespace, with no server contacted", async () => {
    cfg = { ...cfg, gateway: { tools: { deny: ["opsys_m4__*"] } } };
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, { tool: "m4_pointer", args: {} });

      expect(res.status).toBe(403);
      expect(((await res.json()) as InvokeBody).error?.message).toContain("gateway.tools.deny");
      expect(runtimes).toHaveLength(0);
    });
  });

  it("does not let a body agentId or sessionKey redirect or block the call", async () => {
    await withPairedDevice(DEVICE_ID, async (deviceToken) => {
      const res = await invokeAsApp(deviceToken, {
        tool: "m4_pointer",
        args: {},
        agentId: "m02-demo",
        sessionKey: "agent:m02-demo:main",
      });

      // The agent m02-demo denies `opsys_m4__*`: an agent policy filters what a MODEL may call and
      // does not apply to the role-scoped device door. Nothing in the body selects the server.
      expect(res.status).toBe(200);
      expect(runtimes).toHaveLength(1);
      expect(runtimes[0]?.includeServerNames).toEqual(["opsys_m4"]);
      expect(runtimes[0]?.toolCalls[0]).toMatchObject({ serverName: "opsys_m4" });
    });
  });
});
