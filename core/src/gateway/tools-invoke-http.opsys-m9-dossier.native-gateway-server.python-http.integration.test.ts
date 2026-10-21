// Native Gateway startup, signed device clients and real fictitious Python MCP/SQLite.
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs/promises";
import { createServer as createPortServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { expect, it } from "vitest";
import { createBoundedChildOutput } from "../../test/helpers/bounded-child-output.js";
import { waitForChildClose } from "../../test/helpers/process-wait.js";
import { stopChildProcess } from "../../test/helpers/stop-child-process.js";
import { getSessionMcpRuntimeManagerForTesting } from "../agents/agent-bundle-mcp-manager-api.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "../agents/agent-bundle-mcp-runtime-shared.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import {
  type DeviceIdentity,
  loadOrCreateDeviceIdentity,
  publicKeyRawBase64UrlFromPem,
} from "../infra/device-identity.js";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import { resetOpsysDeviceRolesCacheForTesting } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";
import {
  connectGatewayClient,
  disconnectGatewayClient,
  startGatewayWithClient,
} from "./test-helpers.e2e.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-m9-dossier-fixture.py");
const TOOL = "m9_diagnostiquer_dossier_direction";
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
async function stopAndCloseOwnedChild(child: ChildProcess): Promise<void> {
  await stopChildProcess(child, 2000);
  const closed = childCloses.get(child);
  if (!closed) {
    throw new Error("owned child closure observer missing");
  }
  await closed;
}

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
  const child = spawn(python, ["-B", FIXTURE, "serve", "--port", String(port)], {
    cwd: REPO,
    env: pythonEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  void retainChildClose(child, 180_000);
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

async function pairNativeDevice(identity: DeviceIdentity): Promise<string> {
  const scopes = ["operator.read", "operator.write"];
  const requested = await requestDevicePairing({
    deviceId: identity.deviceId,
    publicKey: publicKeyRawBase64UrlFromPem(identity.publicKeyPem),
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
    deviceId: identity.deviceId,
    role: "operator",
    scopes,
    issuer: { kind: "shared-gateway-auth", generation },
  });
  if (!issued?.token) {
    throw new Error("Native operator token unavailable");
  }
  return issued.token;
}

const ARGS = {
  question: "Quels faits reçus éclairent les chantiers fictifs ?",
  modules_attendus: ["M5-fictif", "M8-fictif", "M6-fictif"],
  horodatage_reference: "2026-10-18T06:00:00Z",
};

it("binds native signed WS identities to real HTTP M9 roles and drains every producer", async () => {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON locked runtime required");
  }
  await withOpenClawTestState(
    {
      label: "m9-native-gateway-fictif",
      env: {
        OPENCLAW_SKIP_CHANNELS: "1",
        OPENCLAW_SKIP_GMAIL_WATCHER: "1",
        OPENCLAW_SKIP_CRON: "1",
        OPENCLAW_SKIP_CANVAS_HOST: "1",
        OPENCLAW_SKIP_BROWSER_CONTROL_SERVER: "1",
        OPENCLAW_SKIP_PROVIDERS: "1",
      },
    },
    async (state) => {
      const children: ChildProcess[] = [];
      const clients: Awaited<ReturnType<typeof connectGatewayClient>>[] = [];
      const home = await fs.mkdtemp(resolve(tmpdir(), "opsys-m9-native-fictif-"));
      const configDir = dirname(state.configPath);
      const env = pythonEnv(home);
      let gateway: Awaited<ReturnType<typeof startGatewayWithClient>> | undefined;
      let primary: unknown;
      let failed = false;
      const errors: unknown[] = [];
      const evidence: Record<string, unknown> = { fictif: true };
      let assertFinalIngress: (() => Promise<void>) | undefined;
      try {
        const seed: unknown = JSON.parse(
          await runPython(
            python,
            [FIXTURE, "prepare", "--config", configDir, "--tool", TOOL],
            env,
            children,
          ),
        );
        if (!isRecord(seed) || !Array.isArray(seed.chain) || seed.chain.length !== 3) {
          throw new Error("three independent real source rows required");
        }
        const chain = seed.chain;
        // Distinct native Ed25519 identities, kept in this fixture's SQLite only.
        const adminIdentity = loadOrCreateDeviceIdentity({ identityKey: "m9-admin-fictif" });
        const employeeIdentity = loadOrCreateDeviceIdentity({ identityKey: "m9-employee-fictif" });
        expect(adminIdentity.deviceId).not.toBe(employeeIdentity.deviceId);
        expect(adminIdentity.publicKeyPem).not.toBe(employeeIdentity.publicKeyPem);
        const principals = [
          { identity: adminIdentity, person: "admin-dossier-fictif", role: "admin" },
          { identity: employeeIdentity, person: "employee-dossier-fictif", role: "employee" },
        ];
        for (const { identity, person, role } of principals) {
          await runPython(
            python,
            [
              "-m",
              "opsys.cli",
              "appareils",
              "appairer",
              identity.deviceId,
              "--personne",
              person,
              "--role",
              role,
              "--config-dir",
              configDir,
            ],
            env,
            children,
          );
        }
        const pythonPort = await reservePort();
        await startPython(python, home, pythonPort, children);
        const cfg: OpenClawConfig = {
          gateway: { auth: { mode: "token", token: CORE_TOKEN }, controlUi: { enabled: false } },
          agents: { defaults: { workspace: state.workspaceDir } },
          plugins: { enabled: false },
          cron: { enabled: false },
          update: { checkOnStart: false, auto: { enabled: false } },
          discovery: { mdns: { mode: "off" } },
          mcp: {
            servers: Object.fromEntries(
              [
                ["opsys_m9", "m09-strategic-intelligence"],
                ["opsys_m4", "m04-field-ops"],
              ].map(([key, dep]) => [
                key,
                {
                  url: `http://127.0.0.1:${pythonPort}/mcp/${dep}`,
                  transport: "streamable-http",
                  transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${pythonPort}` },
                  headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
                  connectionTimeoutMs: 5000,
                  requestTimeoutMs: 10000,
                },
              ]),
            ),
          },
        };
        resetOpsysDeviceRolesCacheForTesting();
        gateway = await startGatewayWithClient({
          cfg,
          configPath: state.configPath,
          token: CORE_TOKEN,
          clientDisplayName: "m9-bootstrap-fictif",
        });
        await gateway.server.startupSettled;
        const corePort = gateway.port;
        const tokens: string[] = [];
        for (const { identity, person, role } of principals) {
          const token = await pairNativeDevice(identity);
          expect(token).not.toBe(CORE_TOKEN);
          expect(tokens).not.toContain(token);
          tokens.push(token);
          let helloSeen = false;
          const client = await connectGatewayClient({
            url: `ws://127.0.0.1:${corePort}`,
            deviceIdentity: identity,
            deviceToken: token,
            scopes: ["operator.read", "operator.write"],
            clientDisplayName: `m9-${role}-fictif`,
            onHelloOk: (hello) => {
              // No shared token is supplied: the signature and this paired token
              // must be the native authentication path that produced hello-ok.
              expect(hello.auth.method).toBe("device-token");
              expect(hello.auth.role).toBe("operator");
              expect(hello.auth.scopes).toEqual(
                expect.arrayContaining(["operator.read", "operator.write"]),
              );
              helloSeen = true;
            },
          });
          clients.push(client);
          expect(helloSeen).toBe(true);
          evidence[`${role}Hello`] = {
            deviceId: identity.deviceId,
            person,
            role,
            signed: true,
            authMethod: "device-token",
          };
        }
        await disconnectGatewayClient(gateway.client);
        evidence.bootstrapClientClosedBeforeBusinessHttp = true;
        const [admin, employee] = tokens;
        if (!admin || !employee) {
          throw new Error("two signed paired device tokens required");
        }
        const http = async (token: string, path: string, body?: string) => {
          // Every business HTTP request is constrained to the exact two tokens
          // already passed to the corresponding signed WebSocket connections.
          if (token !== admin && token !== employee) {
            throw new Error("HTTP requires the corresponding signed device bearer");
          }
          const response = await fetch(`http://127.0.0.1:${corePort}${path}`, {
            method: body === undefined ? "GET" : "POST",
            headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
            body,
            signal: AbortSignal.timeout(30000),
          });
          const payload: unknown = await response.json();
          return { status: response.status, body: payload };
        };
        for (const [index, { identity, person, role }] of principals.entries()) {
          const response = await http(tokens[index]!, "/opsys/identite");
          evidence[`${role}Identity`] = response;
          expect(response).toStrictEqual({
            status: 200,
            body: { ok: true, identite: { appareilId: identity.deviceId, personne: person, role } },
          });
        }
        const inspect = async () =>
          JSON.parse(await runPython(python, [FIXTURE, "inspect"], env, children)) as {
            business: unknown;
            tables: unknown;
            chain: unknown;
          };
        const dispatched = async () => {
          try {
            return (await fs.readFile(resolve(home, "dispatches.jsonl"), "utf8"))
              .trim()
              .split("\n")
              .filter(Boolean)
              .map((line) => JSON.parse(line) as { name: string; meta: Record<string, unknown> });
          } catch (error) {
            if (isRecord(error) && error.code === "ENOENT") {
              return [];
            }
            throw error;
          }
        };
        assertFinalIngress = async () => {
          const rows = await dispatched();
          evidence.finalDispatches = rows;
          const m9 = rows.filter((row) => row.name === TOOL);
          expect(m9).toHaveLength(1);
          expect(m9[0]?.meta).toMatchObject({
            "opsys/personne": "admin-dossier-fictif",
            "opsys/role": "admin",
          });
          expect(
            m9.filter((row) => row.meta["opsys/personne"] === "employee-dossier-fictif"),
          ).toHaveLength(0);
          console.info(
            JSON.stringify({
              fictif: true,
              oracle: "M9_NATIVE_GATEWAY_FINAL_INGRESS_AFTER_BACKEND_CLOSE",
              startupSettled: true,
              signedDeviceHellos: 2,
              adminM9Ingress: 1,
              employeeM9Ingress: 0,
              deviceBearerOnly: true,
              backendClosedBeforeObservation: true,
              fullM9Report: false,
            }),
          );
        };
        const invoke = (token: string, tool: string, args: Record<string, unknown>) =>
          http(token, "/tools/invoke", JSON.stringify({ tool, args }));
        const unpack = (response: { status: number; body: unknown }) => {
          expect(response.status).toBe(200);
          if (
            !isRecord(response.body) ||
            response.body.ok !== true ||
            !isRecord(response.body.result) ||
            response.body.result.ok !== true ||
            !isRecord(response.body.result.resultat)
          ) {
            throw new Error("real successful complete business envelope required");
          }
          expect(response.body.result).not.toHaveProperty("tronque");
          expect(response.body.result).not.toHaveProperty("apercu");
          return response.body.result.resultat;
        };
        const before = await inspect();
        evidence.before = before;
        const positive = await invoke(employee, "m4_lister_interventions", {});
        evidence.employeePositive = positive;
        expect(positive.status).toBe(200);
        expect(positive.body).toMatchObject({ ok: true, result: { ok: true } });
        expect(await dispatched()).toContainEqual(
          expect.objectContaining({
            name: "m4_lister_interventions",
            meta: expect.objectContaining({
              "opsys/personne": "employee-dossier-fictif",
              "opsys/role": "employee",
            }),
          }),
        );
        const consolidated = unpack(await invoke(admin, "m9_lire_etat_consolide", {}));
        // Identical bytes for both M9 requests; only the bearer changes.
        const businessBody = JSON.stringify({ tool: TOOL, args: ARGS });
        const success = await http(admin, "/tools/invoke", businessBody);
        evidence.adminM9 = success;
        const result = unpack(success);
        const dossier = result.dossier;
        const diagnostic = result.diagnostic;
        if (!isRecord(dossier) || !isRecord(diagnostic)) {
          throw new Error("complete server dossier and diagnostic required");
        }
        expect(dossier.type).toBe("DOSSIER_PREPARATOIRE_DIRECTION");
        expect(dossier.question).toBe(ARGS.question);
        expect(dossier.modules_attendus).toStrictEqual(ARGS.modules_attendus);
        expect(dossier.preuves).toStrictEqual(chain);
        expect(dossier.etat_id).toBe(consolidated.etat_id);
        expect(dossier.dossier_id).toBe(
          await runPython(
            python,
            [FIXTURE, "digest", "--payload", JSON.stringify(dossier)],
            env,
            children,
          ),
        );
        expect(Array.isArray(dossier.limites) && dossier.limites.length > 0).toBe(true);
        expect(dossier.modules_manquants).toStrictEqual(["M6-fictif"]);
        expect(dossier.statut_preparation).toBe("NON_VALIDE");
        expect(dossier.actualite).toBe("NON_EVALUEE");
        expect(dossier.faits_selectionnes).toStrictEqual({
          "M5-fictif": chain[1],
          "M8-fictif": chain[2],
        });
        expect(dossier.contradictions).toEqual([
          expect.objectContaining({ ligne_id_a: 0, ligne_id_b: 1 }),
        ]);
        expect(diagnostic.type).toBe("DIAGNOSTIC_TEMPOREL_DOSSIER");
        expect(diagnostic.dossier_id).toBe(dossier.dossier_id);
        expect(diagnostic.etat_id).toBe(dossier.etat_id);
        expect(diagnostic.reference_source).toBe("2026-10-18T06:00:00Z");
        expect(diagnostic.reference_utc).toBe("2026-10-18T06:00:00+00:00");
        expect(diagnostic.actualite_metier).toBe("NON_EVALUEE");
        expect(diagnostic.modules_manquants).toStrictEqual(dossier.modules_manquants);
        expect(diagnostic.observations).toStrictEqual([
          {
            module_source: "M5-fictif",
            index: 1,
            hash_maillon: (chain[1] as Record<string, unknown>).hash_maillon,
            horodatage_source: "2026-10-18T07:00:00Z",
            ecart_secondes: -3600,
            diagnostic: "OBSERVATION_FUTURE",
          },
          {
            module_source: "M8-fictif",
            index: 2,
            hash_maillon: (chain[2] as Record<string, unknown>).hash_maillon,
            horodatage_source: "2026-10-18T07:01:00Z",
            ecart_secondes: -3660,
            diagnostic: "OBSERVATION_FUTURE",
          },
        ]);
        expect(diagnostic.diagnostic_id).toBe(
          await runPython(
            python,
            [
              FIXTURE,
              "digest",
              "--id-key",
              "diagnostic_id",
              "--payload",
              JSON.stringify(diagnostic),
            ],
            env,
            children,
          ),
        );
        const preDenial = await inspect();
        const preDispatch = await dispatched();
        const denial = await http(employee, "/tools/invoke", businessBody);
        evidence.employeeM9 = denial;
        expect(denial).toStrictEqual({
          status: 403,
          body: {
            ok: false,
            error: {
              type: "tool_call_blocked",
              message: `OPSYS device is not authorized to call "${TOOL}" (tool_out_of_scope).`,
            },
          },
        });
        expect(await dispatched()).toStrictEqual(preDispatch);
        expect(await inspect()).toStrictEqual(preDenial);
        const after = await inspect();
        evidence.after = after;
        expect(after.business).toStrictEqual(before.business);
        expect(after.tables).toStrictEqual(before.tables);
        expect(after.chain).toStrictEqual(chain);
      } catch (error) {
        failed = true;
        primary = error;
      } finally {
        // Join all WS producers before Gateway, MCP and Python. Every shutdown
        // failure is retained and fails the test, even after successful assertions.
        for (const client of [...clients, ...(gateway ? [gateway.client] : [])]) {
          try {
            await disconnectGatewayClient(client);
          } catch (error) {
            errors.push(error);
          }
        }
        try {
          await gateway?.server.close();
        } catch (error) {
          errors.push(error);
        }
        try {
          await getSessionMcpRuntimeManagerForTesting().disposeAll();
          Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
        } catch (error) {
          errors.push(error);
        }
        for (const child of children) {
          try {
            await stopAndCloseOwnedChild(child);
          } catch (error) {
            errors.push(error);
          }
        }
        if (errors.length === 0 && assertFinalIngress) {
          try {
            await assertFinalIngress();
          } catch (error) {
            errors.push(error);
          }
        } else if (!failed && !assertFinalIngress) {
          errors.push(new Error("final post-stop oracle missing"));
        }
        evidence.failed = failed;
        evidence.errors = [...(failed ? [primary] : []), ...errors].map((error) =>
          error instanceof Error
            ? { name: error.name, message: error.message, stack: error.stack }
            : String(error),
        );
        try {
          await fs.writeFile(resolve(home, "evidence.json"), JSON.stringify(evidence, null, 2));
        } catch (error) {
          errors.push(error);
        }
        if (failed || errors.length > 0) {
          console.error(`M9 native Gateway fictitious failure evidence retained: ${home}`);
        } else {
          await fs.rm(home, { recursive: true, force: true });
        }
      }
      if (errors.length > 0) {
        throw new AggregateError(
          failed ? [primary, ...errors] : errors,
          "M9 native Gateway cleanup/oracle failed",
        );
      }
      if (failed) {
        throw primary;
      }
    },
  );
}, 180000);
