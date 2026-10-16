// Real HTTP/Core/Python/SQLite device revocation; only the two intercalation seams are replaced.
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { createServer as createPortServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { expect, it, vi } from "vitest";
import { createBoundedChildOutput } from "../../test/helpers/bounded-child-output.js";
import { waitForChildClose } from "../../test/helpers/process-wait.js";
import { stopChildProcess } from "../../test/helpers/stop-child-process.js";
import { getSessionMcpRuntimeManagerForTesting } from "../agents/agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "../agents/agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "../agents/agent-bundle-mcp-runtime-shared.js";
import type { runBeforeToolCallHook } from "../agents/agent-tools.before-tool-call.js";
import { setRuntimeConfigSnapshot } from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import { resetOpsysDeviceRolesCacheForTesting } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

type HookArgs = Parameters<typeof runBeforeToolCallHook>[0];
type HookResult = Awaited<ReturnType<typeof runBeforeToolCallHook>>;
const hook = vi.hoisted(() => {
  let action: (() => Promise<void>) | undefined;
  let original = false;
  return {
    useOriginal() {
      original = true;
    },
    callsOriginal() {
      return original;
    },
    arm(next: () => Promise<void>) {
      action = next;
    },
    clear() {
      action = undefined;
      original = false;
    },
    async before(this: void, args: HookArgs): Promise<HookResult> {
      const selected = action;
      action = undefined;
      await selected?.();
      return { blocked: false, params: args.params };
    },
  };
});
const runtimeHook = vi.hoisted(() => {
  let action: (() => Promise<void>) | undefined;
  return {
    arm(next: () => Promise<void>) {
      action = next;
    },
    clear() {
      action = undefined;
    },
    async beforeReturn() {
      const selected = action;
      action = undefined;
      await selected?.();
    },
  };
});
// Only the intercalation seam is replaced, never the transport or any authority reader.
vi.mock("../agents/agent-tools.before-tool-call.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../agents/agent-tools.before-tool-call.js")>();
  return {
    ...actual,
    runBeforeToolCallHook: (args: HookArgs) =>
      hook.callsOriginal() ? actual.runBeforeToolCallHook(args) : hook.before(args),
  };
});
vi.mock("../agents/opsys-memoire-lecture-ticket.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../agents/opsys-memoire-lecture-ticket.js")>();
  return {
    ...actual,
    createOpsysMemoireLectureMeta: async (
      ...args: Parameters<typeof actual.createOpsysMemoireLectureMeta>
    ) => {
      const result = await actual.createOpsysMemoireLectureMeta(...args);
      await runtimeHook.beforeReturn();
      return result;
    },
  };
});
const { handleToolsInvokeHttpRequest } = await import("./tools-invoke-http.js");

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-target-ticket-fixture.py");
const DEVICE = "device-effect-revocation-fictif";
const TOOL = "m2_enregistrer_interaction";
const PUBLIC_TOKEN = "synthetic-device-effect-public-mcp-token-2026";
const CORE_TOKEN = "synthetic-device-effect-core-token-2026";
const AUTH: ResolvedGatewayAuth = {
  mode: "token",
  token: CORE_TOKEN,
  password: undefined,
  allowTailscale: false,
};
const DEPARTMENTS = [
  "m01-front-office",
  "m02-revenue-crm",
  "m03-estimation",
  "m04-field-ops",
  "m05-financecore",
  "m06-material-control",
  "m07-marketing",
  "m08-analytics",
  "m09-strategic-intelligence",
  "m10-memoire",
];
const childCloses = new WeakMap<ChildProcess, ReturnType<typeof waitForChildClose>>();
function retainChildClose(child: ChildProcess, timeoutMs: number) {
  const closed = waitForChildClose(child, timeoutMs);
  childCloses.set(child, closed);
  // Retain failures for explicit awaits, without an unhandled background rejection.
  void closed.catch(() => undefined);
  return closed;
}
const GENERATE_ROLES = [
  "import sys",
  "from pathlib import Path",
  "from opsys import openclaw",
  "from opsys.departements import charger_departements",
  "departements = charger_departements()",
  "openclaw._ecrire_json(Path(sys.argv[1]) / 'opsys' / 'roles.json',",
  "    {'roles': openclaw.roles_outils(departements),",
  "     'serveurs': openclaw.serveurs_outils(departements)})",
].join("\n");
const INSPECT_PAIRING = [
  "import json, sys",
  "from opsys import appareils, identite, stockage",
  "with stockage.transaction() as cnx:",
  "    device = appareils.appareil(cnx, sys.argv[1])",
  "    person = identite.personne_active(cnx, 'nathan-fixture')",
  "    print(json.dumps({'paired': device is not None,",
  "        'active_admin': person is not None and 'admin' in person.roles}))",
].join("\n");
const SNAPSHOT_M2 = [
  "import hashlib, json",
  "from opsys import stockage",
  "from m2_revenue_crm import registre",
  "with stockage.transaction():",
  "    rows = registre.Registre(maillons=stockage.maillons('m02-revenue-crm', 'principal')).lire()",
  "    data = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()",
  "    print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'maillons': len(rows)}))",
].join("\n");

function pythonEnv(home: string): NodeJS.ProcessEnv {
  return {
    OPSYS_HOME: home,
    OPSYS_BASE_URL: `sqlite:///${resolve(home, "opsys.db")}`,
    OPSYS_MCP_JETON: PUBLIC_TOKEN,
    OPSYS_CONTEXT_MCP_JETON: "synthetic-device-effect-private-context-unused-2026",
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    PYTHONPATH: [
      resolve(REPO, "src"),
      ...DEPARTMENTS.map((n) => resolve(REPO, `departments/${n}/src`)),
    ].join(":"),
  };
}

async function runPython(
  python: string,
  args: string[],
  env: NodeJS.ProcessEnv,
  children: ChildProcess[],
): Promise<string> {
  const child = spawn(python, ["-B", ...args], {
    cwd: REPO,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  const completion = retainChildClose(child, 30_000);
  let spawnError: Error | undefined;
  child.once("error", (error) => {
    spawnError = error;
  });
  const output = createBoundedChildOutput();
  const errors = createBoundedChildOutput();
  child.stdout?.on("data", output.append);
  child.stderr?.on("data", errors.append);
  const closed = await completion;
  if (spawnError) {
    throw new Error("Python process could not start", { cause: spawnError });
  }
  if (closed.code !== 0 || closed.signal !== null) {
    throw new Error(
      `Python fixture/CLI failed (${closed.code}/${closed.signal}): ${errors.text()}`,
    );
  }
  return output.text().trim();
}

async function reservePort(): Promise<number> {
  const server = createPortServer();
  await new Promise<void>((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Loopback port unavailable");
  }
  await new Promise<void>((done, reject) => {
    server.close((error) => (error ? reject(error) : done()));
  });
  return address.port;
}

async function startPython(
  python: string,
  home: string,
  port: number,
  children: ChildProcess[],
  observeM9Sql = false,
): Promise<void> {
  const child = spawn(
    python,
    observeM9Sql
      ? ["-B", FIXTURE, "serve-m9-sql-observed", "--port", String(port)]
      : ["-B", "-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
    {
      cwd: REPO,
      env: pythonEnv(home),
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  children.push(child);
  void retainChildClose(child, 120_000);
  const output = createBoundedChildOutput();
  await new Promise<void>((done, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`MCP startup deadline: ${output.text()}`)),
      15_000,
    );
    const onData = (chunk: unknown) => {
      output.append(chunk);
      if (output.text().includes("Uvicorn running on")) {
        clearTimeout(timeout);
        done();
      }
    };
    child.stdout?.on("data", onData);
    child.stderr?.on("data", onData);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("close", (code, signal) => {
      clearTimeout(timeout);
      reject(new Error(`MCP exited during startup (${code}/${signal}): ${output.text()}`));
    });
  });
}

async function pairNativeDevice(): Promise<string> {
  const scopes = ["operator.read", "operator.write"];
  const requested = await requestDevicePairing({
    deviceId: DEVICE,
    publicKey: `synthetic-public-key-${randomUUID()}`,
    role: "operator",
    scopes,
  });
  const approved = await approveDevicePairing(requested.request.requestId, {
    callerScopes: scopes,
  });
  if (approved?.status !== "approved") {
    throw new Error("Native pairing approval refused");
  }
  const generation = resolveSharedGatewaySessionGeneration(AUTH, []);
  if (!generation) {
    throw new Error("Native token generation unavailable");
  }
  const issued = await ensureDeviceToken({
    deviceId: DEVICE,
    role: "operator",
    scopes,
    issuer: { kind: "shared-gateway-auth", generation },
  });
  if (!issued?.token) {
    throw new Error("Native operator token unavailable");
  }
  return issued.token;
}

async function listen(server: Server): Promise<number> {
  await new Promise<void>((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Core HTTP listener unavailable");
  }
  return address.port;
}

it("refuses a normally revoked OPSYS device before real MCP mutation and accepts a fresh re-pair", async () => {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON with locked local dependencies is required");
  }
  await withOpenClawTestState({ label: "device-effect-real-python" }, async (state) => {
    const children: ChildProcess[] = [];
    const home = await fs.mkdtemp(resolve(tmpdir(), "opsys-device-effect-fictif-"));
    const configDir = dirname(state.configPath);
    const env = pythonEnv(home);
    let server: Server | undefined;
    let failed = false;
    let primary: unknown;
    try {
      await runPython(python, [FIXTURE, "prepare"], env, children);
      await runPython(python, ["-c", GENERATE_ROLES, configDir], env, children);
      const appairer = () =>
        runPython(
          python,
          [
            "-m",
            "opsys.cli",
            "appareils",
            "appairer",
            DEVICE,
            "--personne",
            "nathan-fixture",
            "--role",
            "admin",
            "--config-dir",
            configDir,
          ],
          env,
          children,
        );
      await appairer();
      const mcpPort = await reservePort();
      await startPython(python, home, mcpPort, children);
      const cfg: OpenClawConfig = {
        gateway: { auth: { mode: "token", token: CORE_TOKEN } },
        plugins: { enabled: false },
        mcp: {
          servers: {
            opsys_m2: {
              url: `http://127.0.0.1:${mcpPort}/mcp/m02-revenue-crm`,
              transport: "streamable-http",
              transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${mcpPort}` },
              headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
              connectionTimeoutMs: 5_000,
              requestTimeoutMs: 10_000,
            },
          },
        },
      };
      await state.writeConfig(cfg);
      setRuntimeConfigSnapshot(cfg, cfg);
      resetOpsysDeviceRolesCacheForTesting();
      const token = await pairNativeDevice();
      server = createServer((req, res) => {
        void handleToolsInvokeHttpRequest(req, res, {
          auth: AUTH,
          cfg,
          getRuntimeConfig: () => cfg,
        })
          .then((handled) => {
            if (!handled) {
              res.statusCode = 404;
              res.end();
            }
          })
          .catch((error: unknown) => {
            if (!res.headersSent) {
              res.statusCode = 500;
            }
            res.end(String(error));
          });
      });
      const corePort = await listen(server);
      const inspect = async () => {
        const value: unknown = JSON.parse(
          await runPython(python, [FIXTURE, "inspect"], env, children),
        );
        if (
          !isRecord(value) ||
          typeof value.interactions !== "number" ||
          typeof value.linked !== "boolean"
        ) {
          throw new Error("Real fixture inspect shape unavailable");
        }
        return { interactions: value.interactions, linked: value.linked };
      };
      const snapshot = async () => {
        const value: unknown = JSON.parse(
          await runPython(python, ["-c", SNAPSHOT_M2], env, children),
        );
        if (
          !isRecord(value) ||
          typeof value.sha256 !== "string" ||
          typeof value.maillons !== "number"
        ) {
          throw new Error("Real M2 snapshot shape unavailable");
        }
        return { sha256: value.sha256, maillons: value.maillons };
      };
      const invoke = async (key: string) => {
        const response = await fetch(`http://127.0.0.1:${corePort}/tools/invoke`, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
          body: JSON.stringify({
            tool: TOOL,
            idempotencyKey: key,
            deviceTimestamp: "2026-09-30T12:00:00Z",
            args: {
              lead_id: "LEAD-CORE-C02",
              auteur: "nathan-fixture",
              resume: `Note fictive ${key}`,
              horodatage: "2026-09-30T12:00:00+00:00",
            },
          }),
          signal: AbortSignal.timeout(30_000),
        });
        const raw = await response.text();
        let body: unknown;
        try {
          body = JSON.parse(raw);
        } catch {
          body = undefined;
        }
        return { status: response.status, body, raw };
      };
      expect(await inspect()).toStrictEqual({ interactions: 0, linked: true });
      const healthy = await invoke("device-fictif-healthy-before");
      expect(healthy.status, healthy.raw).toBe(200);
      expect(healthy.body).toMatchObject({
        ok: true,
        result: { ok: true, resultat: { accepte: true } },
      });
      expect((await inspect()).interactions).toBe(1);
      const beforeRevocation = await snapshot();
      const pairedBefore: unknown = JSON.parse(
        await runPython(python, ["-c", INSPECT_PAIRING, DEVICE], env, children),
      );
      expect(pairedBefore).toStrictEqual({ paired: true, active_admin: true });
      const attributedBefore: unknown = JSON.parse(
        await fs.readFile(resolve(configDir, "opsys/appareils.json"), "utf8"),
      );
      expect(attributedBefore).toStrictEqual({
        appareils: { [DEVICE]: { personne: "nathan-fixture", role: "admin" } },
      });
      let revocations = 0;
      let hookFailure: unknown;
      const revoke = async () => {
        try {
          await runPython(
            python,
            ["-m", "opsys.cli", "appareils", "revoquer", DEVICE, "--config-dir", configDir],
            env,
            children,
          );
          const pairing: unknown = JSON.parse(
            await runPython(python, ["-c", INSPECT_PAIRING, DEVICE], env, children),
          );
          expect(pairing).toStrictEqual({ paired: false, active_admin: true });
          const fragment: unknown = JSON.parse(
            await fs.readFile(resolve(configDir, "opsys/appareils.json"), "utf8"),
          );
          expect(fragment).toStrictEqual({ appareils: {} });
          revocations += 1;
        } catch (error) {
          hookFailure = error;
          throw error;
        }
      };
      hook.arm(revoke);
      const revoked = await invoke("device-fictif-revoked-in-hook");
      if (hookFailure !== undefined) {
        throw new Error("Normal revocation fixture failed in hook", { cause: hookFailure });
      }
      expect(revocations).toBe(1);
      const afterRevocation = await snapshot();
      const inspectedRevoked = await inspect();
      // Prove the recovered healthy path before the final RED assertions can abort this case.
      await appairer();
      const recovered = await invoke("device-fictif-healthy-after-repair");
      expect(recovered.status, recovered.raw).toBe(200);
      expect(recovered.body).toMatchObject({
        ok: true,
        result: { ok: true, resultat: { accepte: true } },
      });
      expect((await inspect()).interactions).toBe(inspectedRevoked.interactions + 1);
      console.info(
        JSON.stringify({
          fictif: true,
          oracle: "DEVICE_REVOKED_BEFORE_MCP_EMISSION",
          revocations,
          healthyStatus: healthy.status,
          revokedStatus: revoked.status,
          recoveredStatus: recovered.status,
          interactionsBefore: 1,
          interactionsAfterRevocation: inspectedRevoked.interactions,
          beforeRevocation,
          afterRevocation,
        }),
      );
      expect(revoked.status, revoked.raw).toBe(403);
      expect(revoked.body).toMatchObject({ ok: false, error: { type: "tool_call_blocked" } });
      expect(afterRevocation).toStrictEqual(beforeRevocation);
      expect(inspectedRevoked.interactions).toBe(1);
      // Revoke again after the shared Gateway check, while the real transport is awaiting
      // its original memory preparation. Only the final pre-SDK fence can refuse this call.
      const beforeLateRevocation = await snapshot();
      runtimeHook.arm(revoke);
      const lateRevoked = await invoke("device-fictif-revoked-during-runtime-preparation");
      if (hookFailure !== undefined) {
        throw new Error("Normal revocation fixture failed in runtime preparation", {
          cause: hookFailure,
        });
      }
      expect(revocations).toBe(2);
      const afterLateRevocation = await snapshot();
      const lateInspected = await inspect();
      await appairer();
      const lateRecovered = await invoke("device-fictif-healthy-after-late-repair");
      expect(lateRecovered.status, lateRecovered.raw).toBe(200);
      expect(lateRecovered.body).toMatchObject({
        ok: true,
        result: { ok: true, resultat: { accepte: true } },
      });
      expect((await inspect()).interactions).toBe(lateInspected.interactions + 1);
      console.info(
        JSON.stringify({
          fictif: true,
          oracle: "DEVICE_REVOKED_DURING_RUNTIME_PREPARATION_BEFORE_SDK_EMISSION",
          revocations,
          revokedStatus: lateRevoked.status,
          recoveredStatus: lateRecovered.status,
          interactionsBefore: 2,
          interactionsAfterRevocation: lateInspected.interactions,
          beforeRevocation: beforeLateRevocation,
          afterRevocation: afterLateRevocation,
        }),
      );
      expect(lateRevoked.status, lateRevoked.raw).toBe(403);
      expect(lateRevoked.body).toMatchObject({ ok: false, error: { type: "tool_call_blocked" } });
      expect(afterLateRevocation).toStrictEqual(beforeLateRevocation);
      expect(lateInspected.interactions).toBe(2);
    } catch (error) {
      failed = true;
      primary = error;
    }
    hook.clear();
    runtimeHook.clear();
    const cleanupErrors: unknown[] = [];
    if (server) {
      try {
        server.closeIdleConnections();
        await new Promise<void>((done, reject) => {
          server?.close((error) => (error ? reject(error) : done()));
        });
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    for (const child of children) {
      try {
        await stopChildProcess(child, 2_000);
        const closed = childCloses.get(child);
        if (!closed) {
          throw new Error("Owned child close observer absent");
        }
        await closed;
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    try {
      await fs.rm(home, { recursive: true, force: true });
    } catch (error) {
      cleanupErrors.push(error);
    }
    if (cleanupErrors.length > 0) {
      throw new AggregateError(
        failed ? [primary, ...cleanupErrors] : cleanupErrors,
        "Native HTTP/Python fixture cleanup failed",
        { cause: failed ? primary : cleanupErrors[0] },
      );
    }
    if (failed) {
      throw primary;
    }
  });
}, 120_000);

it("approves one genuinely sealed M9 followup through a paired Core owner device and replays without effects", async () => {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON with locked local dependencies is required");
  }
  await withOpenClawTestState({ label: "m9-owner-device-real-python" }, async (state) => {
    const children: ChildProcess[] = [];
    const home = await fs.mkdtemp(resolve(tmpdir(), "opsys-m9-owner-device-fictif-"));
    const configDir = dirname(state.configPath);
    const env = pythonEnv(home);
    let server: Server | undefined;
    let failed = false;
    let primary: unknown;
    try {
      // The M2 intercalation seam must not bypass the original Core hook in this case.
      hook.useOriginal();
      await getSessionMcpRuntimeManagerForTesting().disposeAll();
      Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
      const prepared = JSON.parse(
        await runPython(python, [FIXTURE, "prepare-m9"], env, children),
      ) as {
        fictif: boolean;
        session_key: string;
        affairs: Record<"A" | "B", string>;
        arguments: Record<"A" | "B", Record<string, unknown>>;
      };
      expect(prepared.fictif).toBe(true);
      // Generate the actual contract in this state's config directory, without replacing
      // OPENCLAW_CONFIG_PATH with the shared agent fixture's unrelated roles directory.
      await runPython(
        python,
        [
          "-c",
          [
            GENERATE_ROLES,
            "context = openclaw._configuration_contexte(departements, {'m09-strategic-intelligence': []}, ['m09-strategic-intelligence'])",
            "assert context is not None",
            "openclaw._ecrire_json(Path(sys.argv[1]) / 'opsys' / 'contexte.json', context)",
          ].join("\n"),
          configDir,
        ],
        env,
        children,
      );
      const roles = JSON.parse(
        await fs.readFile(resolve(configDir, "opsys/roles.json"), "utf8"),
      ) as {
        roles: Record<string, string[]>;
        serveurs: Record<string, string>;
      };
      const listTool = "m9_lister_demandes_approbation";
      const decideTool = "m9_decider_demande_approbation";
      for (const tool of [listTool, decideTool]) {
        expect(roles.roles.admin).toContain(tool);
        expect(roles.serveurs[tool]).toBe("opsys_m9");
      }
      const appairer = () =>
        runPython(
          python,
          [
            "-m",
            "opsys.cli",
            "appareils",
            "appairer",
            DEVICE,
            "--personne",
            "nathan-fixture",
            "--role",
            "admin",
            "--config-dir",
            configDir,
          ],
          env,
          children,
        );
      await appairer();
      const mcpPort = await reservePort();
      await startPython(python, home, mcpPort, children, true);
      const origin = `http://127.0.0.1:${mcpPort}`;
      const cfg: OpenClawConfig = {
        gateway: { auth: { mode: "token", token: CORE_TOKEN } },
        plugins: { enabled: false },
        mcp: {
          servers: {
            opsys_m9: {
              url: `${origin}/mcp/m09-strategic-intelligence`,
              transport: "streamable-http",
              transportSecurity: { insecureHttpOrigin: origin },
              headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
              connectionTimeoutMs: 5_000,
              requestTimeoutMs: 10_000,
            },
            "opsys_context_m09-strategic-intelligence": {
              url: `${origin}/mcp/contexte/m09-strategic-intelligence`,
              transport: "streamable-http",
              transportSecurity: { insecureHttpOrigin: origin },
              headers: {
                Authorization: "Bearer synthetic-device-effect-private-context-unused-2026",
              },
              connectionTimeoutMs: 5_000,
              requestTimeoutMs: 10_000,
            },
          },
        },
      };
      await state.writeConfig(cfg);
      setRuntimeConfigSnapshot(cfg, cfg);
      resetOpsysDeviceRolesCacheForTesting();
      const token = await pairNativeDevice();
      const inspect = async () =>
        JSON.parse(await runPython(python, [FIXTURE, "inspect-m9"], env, children)) as {
          owner_active: boolean;
          linked_affair: string;
          tickets: number;
          tables_digest: string;
          requests: { id: string; status: string }[];
          approval_bindings: {
            demande_id: string;
            ticket_cible_hash: string;
            arguments: Record<string, unknown>;
            decide_par: string;
            decide_role: string;
            ticket: Record<string, unknown>;
          }[];
          followups: {
            suivi_id: string;
            statut: string;
            source: Record<string, unknown>;
            decision: Record<string, unknown>;
          }[];
          decision_audits: { par: string; details: Record<string, unknown> }[];
        };
      expect(await inspect()).toMatchObject({
        owner_active: true,
        requests: [],
        tickets: 0,
        followups: [],
      });
      // The provider/agent turn is outside this proof. The real Core private issuer and
      // real Python M10 target fence must create the request; never call fixture approve.
      const runtime = await getOrCreateSessionMcpRuntime({
        sessionId: "opsys-real-python-m9-gateway-owner",
        sessionKey: prepared.session_key,
        workspaceDir: home,
        cfg,
      });
      opsysContexteGuardStore.set(prepared.session_key, {
        kind: "ready",
        affaireId: prepared.affairs.A,
        nbOuverts: 0,
        atMs: Date.now(),
      });
      const proposal = await runtime.callTool(
        "opsys_m9",
        "m9_ouvrir_suivi_decision",
        prepared.arguments.A,
      );
      expect(proposal.isError).not.toBe(true);
      const request = JSON.parse(
        proposal.content.find((item) => item.type === "text")?.text ?? "null",
      ) as {
        demande_id: string;
        statut: string;
      };
      expect(request).toMatchObject({
        statut: "en_attente_approbation",
        demande_id: expect.any(String),
      });
      const pending = await inspect();
      expect(pending).toMatchObject({
        owner_active: true,
        linked_affair: prepared.affairs.A,
        requests: [{ id: request.demande_id, status: "en_attente" }],
        tickets: 1,
        followups: [],
        decision_audits: [],
      });
      expect(pending.approval_bindings).toHaveLength(1);
      const [binding] = pending.approval_bindings;
      expect(binding.ticket_cible_hash).toMatch(/^[a-f0-9]{64}$/);
      expect(binding.arguments).toStrictEqual(prepared.arguments.A);
      expect(binding.ticket).toMatchObject({
        ticket_hash: binding.ticket_cible_hash,
        demande_id: request.demande_id,
        statut: "scelle",
        departement: "m09-strategic-intelligence",
        outil: "m9_ouvrir_suivi_decision",
        affaire_id: prepared.affairs.A,
        cle_session: prepared.session_key,
        ligne_liaison_id: expect.any(String),
        empreinte_arguments: expect.stringMatching(/^[a-f0-9]{64}$/),
      });
      server = createServer((req, res) => {
        void handleToolsInvokeHttpRequest(req, res, {
          auth: AUTH,
          cfg,
          getRuntimeConfig: () => cfg,
        })
          .then((handled) => {
            if (!handled) {
              res.statusCode = 404;
              res.end();
            }
          })
          .catch((error: unknown) => {
            if (!res.headersSent) {
              res.statusCode = 500;
            }
            res.end(String(error));
          });
      });
      const corePort = await listen(server);
      const sqlWriteCount = async () => {
        const lines = (await fs.readFile(resolve(home, "m9-sql-writes.jsonl"), "utf8"))
          .split("\n")
          .filter(Boolean);
        for (const line of lines) {
          expect(JSON.parse(line)).toMatchObject({
            fictif: true,
            operation: expect.stringMatching(/^(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)$/),
          });
        }
        return lines.length;
      };
      const invoke = async (tool: string, args: Record<string, unknown>, key?: string) => {
        const response = await fetch(`http://127.0.0.1:${corePort}/tools/invoke`, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
          body: JSON.stringify({
            tool,
            args,
            ...(key ? { idempotencyKey: key, deviceTimestamp: "2026-10-16T12:00:00Z" } : {}),
          }),
          signal: AbortSignal.timeout(30_000),
        });
        return { status: response.status, body: (await response.json()) as unknown };
      };
      const beforeListWrites = await sqlWriteCount();
      const listed = await invoke(listTool, {});
      expect(listed.status).toBe(200);
      expect(listed.body).toMatchObject({
        ok: true,
        result: {
          ok: true,
          resultat: {
            accepte: true,
            resultat: {
              demandes: [
                { id: request.demande_id, decidable: true, arguments: prepared.arguments.A },
              ],
            },
          },
        },
      });
      expect(await inspect()).toStrictEqual(pending);
      expect(await sqlWriteCount()).toBe(beforeListWrites);
      const choices = { demande_id: request.demande_id, decision: "approuver" };
      await runPython(
        python,
        ["-m", "opsys.cli", "appareils", "revoquer", DEVICE, "--config-dir", configDir],
        env,
        children,
      );
      const revokedBefore = await inspect();
      expect(revokedBefore.owner_active).toBe(true);
      const beforeRefusedWrites = await sqlWriteCount();
      const revoked = await invoke(decideTool, choices, "m9-owner-fictif-revoked");
      expect(revoked.status).toBe(403);
      expect(await inspect()).toStrictEqual(revokedBefore);
      expect(await sqlWriteCount()).toBe(beforeRefusedWrites);
      await appairer();
      const beforeApprovalWrites = await sqlWriteCount();
      const approved = await invoke(decideTool, choices, "m9-owner-fictif-once");
      expect(approved.status).toBe(200);
      expect(approved.body).toMatchObject({
        ok: true,
        result: {
          ok: true,
          rejoue: false,
          resultat: {
            accepte: true,
            resultat: {
              statut: "executee",
              decide_par: "nathan-fixture",
              role: "nathan_owner",
              issue: { ok: true, accepte: true },
            },
          },
        },
      });
      const completed = await inspect();
      const completedWrites = await sqlWriteCount();
      expect(completedWrites).toBeGreaterThan(beforeApprovalWrites);
      expect(completed.owner_active).toBe(true);
      expect(completed.requests).toStrictEqual([{ id: request.demande_id, status: "executee" }]);
      expect(completed.followups).toHaveLength(1);
      expect(completed.followups[0]).toMatchObject({
        suivi_id: request.demande_id,
        statut: "planifiee",
        source: {
          evenement_id: prepared.arguments.A.evenement_id,
          empreinte_source: prepared.arguments.A.empreinte_source,
        },
        decision: { decide_par: "nathan-fixture", decide_role: "nathan_owner" },
      });
      expect(completed.decision_audits).toHaveLength(1);
      expect(completed.decision_audits[0]).toMatchObject({
        par: "nathan-fixture",
        details: { appareil: DEVICE },
      });
      const replay = await invoke(decideTool, choices, "m9-owner-fictif-once");
      expect(replay.status).toBe(200);
      expect(replay.body).toMatchObject({ ok: true, result: { ok: true, rejoue: true } });
      if (
        !isRecord(approved.body) ||
        !isRecord(approved.body.result) ||
        !isRecord(replay.body) ||
        !isRecord(replay.body.result)
      ) {
        throw new Error("Native approval/replay result shape unavailable");
      }
      const { rejoue: initialReplay, ...originalResult } = approved.body.result;
      const { rejoue: replayFlag, ...replayedResult } = replay.body.result;
      expect(initialReplay).toBe(false);
      expect(replayFlag).toBe(true);
      expect(replayedResult).toStrictEqual(originalResult);
      expect(await inspect()).toStrictEqual(completed);
      expect(await sqlWriteCount()).toBe(completedWrites);
    } catch (error) {
      failed = true;
      primary = error;
    }
    hook.clear();
    const cleanupErrors: unknown[] = [];
    try {
      await getSessionMcpRuntimeManagerForTesting().disposeAll();
      Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
    } catch (error) {
      cleanupErrors.push(error);
    }
    if (server) {
      try {
        server.closeIdleConnections();
        await new Promise<void>((done, reject) =>
          server?.close((error) => (error ? reject(error) : done())),
        );
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    for (const child of children) {
      try {
        await stopChildProcess(child, 2_000);
        const closed = childCloses.get(child);
        if (!closed) {
          throw new Error("Owned child close observer absent");
        }
        await closed;
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    try {
      await fs.rm(home, { recursive: true, force: true });
    } catch (error) {
      cleanupErrors.push(error);
    }
    if (cleanupErrors.length) {
      throw new AggregateError(
        failed ? [primary, ...cleanupErrors] : cleanupErrors,
        "Native M9 owner HTTP/Python fixture cleanup failed",
        { cause: failed ? primary : cleanupErrors[0] },
      );
    }
    if (failed) {
      throw primary;
    }
  });
}, 120_000);
