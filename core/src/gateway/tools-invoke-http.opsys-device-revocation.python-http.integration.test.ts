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
import type { runBeforeToolCallHook } from "../agents/agent-tools.before-tool-call.js";
import { setRuntimeConfigSnapshot } from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
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
  return {
    arm(next: () => Promise<void>) {
      action = next;
    },
    clear() {
      action = undefined;
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
  return { ...actual, runBeforeToolCallHook: hook.before };
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
): Promise<void> {
  const child = spawn(
    python,
    ["-B", "-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", String(port)],
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
