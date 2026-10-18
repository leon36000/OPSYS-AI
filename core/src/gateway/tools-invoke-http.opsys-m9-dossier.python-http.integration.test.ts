// Real HTTP Core handler, actual paired authority and Python MCP; no authority mocks.
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import { createServer, type Server } from "node:http";
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
import { setRuntimeConfigSnapshot } from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import { resetOpsysDeviceRolesCacheForTesting } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

const { handleToolsInvokeHttpRequest } = await import("./tools-invoke-http.js");
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-m9-dossier-fixture.py");
const ADMIN_DEVICE = "device-dossier-admin-fictif";
const EMPLOYEE_DEVICE = "device-dossier-employee-fictif";
const TOOL = "m9_preparer_dossier_direction";
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

async function pairNativeDevice(deviceId: string): Promise<string> {
  const scopes = ["operator.read", "operator.write"];
  const requested = await requestDevicePairing({
    deviceId,
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
    deviceId,
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

function assertBusinessRefusal(response: { status: number; body: unknown }, code: string) {
  // The native device-MCP adapter returns the parsed OPSYS business envelope in
  // result, including business refusals; transport/auth failures are different.
  expect(response.status).toBe(200);
  if (!isRecord(response.body) || !isRecord(response.body.result)) {
    throw new Error("structured OPSYS business refusal required");
  }
  expect(response.body.ok).toBe(true);
  const refusal = response.body.result;
  expect(refusal.ok).toBe(false);
  if (code === "arguments_invalides") {
    expect(refusal.erreur).toBe(code);
  } else {
    expect(refusal.erreur).toBe("refus_metier");
    expect(typeof refusal.details === "string" && refusal.details.startsWith(code + " :")).toBe(
      true,
    );
  }
  for (const field of ["resultat", "dossier", "diagnostic", "tronque", "apercu"]) {
    expect(refusal).not.toHaveProperty(field);
    expect(response.body).not.toHaveProperty(field);
  }
}

it.each([
  {
    ok: true,
    result: {
      ok: true,
      resultat: { diagnostic: { observations: [] }, message: "REJ-DIAGNOSTIC-BORNE" },
    },
  },
  {
    ok: true,
    result: { ok: true, resultat: { dossier: { preuves: [] }, message: "REJ-DIAGNOSTIC-BORNE" } },
  },
  { ok: false, erreur: "REJ-DIAGNOSTIC-BORNE", resultat: { diagnostic: { observations: [] } } },
  {
    ok: true,
    result: {
      ok: false,
      erreur: "refus_metier",
      details: "REJ-DIAGNOSTIC-BORNE : fictif",
      resultat: { diagnostic: { observations: [] } },
    },
  },
])("refusal oracle rejects a false success or partial payload %#", (body) => {
  expect(() => assertBusinessRefusal({ status: 200, body }, "REJ-DIAGNOSTIC-BORNE")).toThrow();
});

const ARGS = {
  question: "Quels faits reçus éclairent les chantiers fictifs ?",
  modules_attendus: ["M5-fictif", "M8-fictif", "M6-fictif"],
};
for (const { name, tool, args, temporal } of [
  {
    name: "serves exact sourced M9 dossier to paired admin and fences a live employee before MCP dispatch",
    tool: TOOL,
    args: ARGS,
    temporal: false,
  },
  {
    name: "serves server-captured temporal M9 dossier over real MCP with live roles and whole-output refusals",
    tool: "m9_diagnostiquer_dossier_direction",
    args: { ...ARGS, horodatage_reference: "2026-10-18T06:00:00Z" },
    temporal: true,
  },
]) {
  it(
    name,
    async () => {
      const python = process.env.OPSYS_TEST_PYTHON;
      if (!python) {
        throw new Error("OPSYS_TEST_PYTHON locked runtime required");
      }
      await withOpenClawTestState({ label: "m9-dossier-http-fictif" }, async (state) => {
        const children: ChildProcess[] = [];
        const home = await fs.mkdtemp(resolve(tmpdir(), "opsys-m9-dossier-fictif-"));
        const configDir = dirname(state.configPath),
          env = pythonEnv(home);
        let server: Server | undefined;
        let primary: unknown;
        let failed = false;
        const expectedToolIngress = temporal ? 6 : 2;
        let assertFinalIngressAfterStop: (() => Promise<void>) | undefined;
        try {
          const seed: unknown = JSON.parse(
            await runPython(
              python,
              [FIXTURE, "prepare", "--config", configDir, "--tool", tool],
              env,
              children,
            ),
          );
          if (!isRecord(seed) || !Array.isArray(seed.chain) || seed.chain.length !== 3) {
            throw new Error("three independent real source rows required");
          }
          const chain = seed.chain;
          for (const [device, person, role] of [
            [ADMIN_DEVICE, "admin-dossier-fictif", "admin"],
            [EMPLOYEE_DEVICE, "employee-dossier-fictif", "employee"],
          ]) {
            await runPython(
              python,
              [
                "-m",
                "opsys.cli",
                "appareils",
                "appairer",
                device,
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
          const port = await reservePort();
          await startPython(python, home, port, children);
          const cfg: OpenClawConfig = {
            gateway: { auth: { mode: "token", token: CORE_TOKEN } },
            plugins: { enabled: false },
            mcp: {
              servers: Object.fromEntries(
                [
                  ["opsys_m9", "m09-strategic-intelligence"],
                  ["opsys_m4", "m04-field-ops"],
                ].map(([key, dep]) => [
                  key,
                  {
                    url: `http://127.0.0.1:${port}/mcp/${dep}`,
                    transport: "streamable-http",
                    transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
                    headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
                    connectionTimeoutMs: 5000,
                    requestTimeoutMs: 10000,
                  },
                ]),
              ),
            },
          };
          await state.writeConfig(cfg);
          setRuntimeConfigSnapshot(cfg, cfg);
          resetOpsysDeviceRolesCacheForTesting();
          const admin = await pairNativeDevice(ADMIN_DEVICE),
            employee = await pairNativeDevice(EMPLOYEE_DEVICE);
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
              .catch((error) => {
                if (!res.headersSent) {
                  res.statusCode = 500;
                }
                res.end(String(error));
              });
          });
          const corePort = await listen(server);
          const invoke = async (
            token: string,
            requestedTool: string,
            requestedArgs: Record<string, unknown>,
          ) => {
            const response = await fetch(`http://127.0.0.1:${corePort}/tools/invoke`, {
              method: "POST",
              headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
              body: JSON.stringify({ tool: requestedTool, args: requestedArgs }),
              signal: AbortSignal.timeout(30000),
            });
            const body: unknown = await response.json();
            return { status: response.status, body };
          };
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
          assertFinalIngressAfterStop = async () => {
            // Every producer has been drained and the actual Python backend has closed.
            // Nothing can append a delayed MCP ingress after this last retained observation.
            const rows = await dispatched();
            const dossiers = rows.filter((row) => row.name === tool);
            expect(dossiers).toHaveLength(expectedToolIngress);
            for (const row of dossiers) {
              expect(row.meta).toMatchObject({
                "opsys/personne": "admin-dossier-fictif",
                "opsys/role": "admin",
              });
            }
            console.info(
              JSON.stringify({
                fictif: true,
                oracle: temporal
                  ? "M9_TEMPORAL_FINAL_INGRESS_AFTER_BACKEND_CLOSE"
                  : "M9_DOSSIER_FINAL_INGRESS_AFTER_BACKEND_CLOSE",
                dossierIngress: dossiers.length,
                employeeDossierIngress: 0,
                backendClosedBeforeObservation: true,
              }),
            );
          };
          const unpack = (response: { status: number; body: unknown }) => {
            expect(response.status).toBe(200);
            if (
              !isRecord(response.body) ||
              response.body.ok !== true ||
              !isRecord(response.body.result) ||
              response.body.result.ok !== true ||
              !isRecord(response.body.result.resultat)
            ) {
              throw new Error("real successful business envelope required");
            }
            expect(response.body.result).not.toHaveProperty("tronque");
            expect(response.body.result).not.toHaveProperty("apercu");
            return response.body.result.resultat;
          };
          const before = await inspect();
          const consolidated = unpack(await invoke(admin, "m9_lire_etat_consolide", {}));
          const result = unpack(await invoke(admin, tool, args));
          const dossier = temporal ? result.dossier : result;
          if (!isRecord(dossier)) {
            throw new Error("server dossier required");
          }
          expect(dossier.type).toBe("DOSSIER_PREPARATOIRE_DIRECTION");
          expect(dossier.question).toBe(args.question);
          expect(dossier.modules_attendus).toStrictEqual(args.modules_attendus);
          expect(dossier.preuves).toStrictEqual(chain);
          expect(dossier.etat_id).toBe(consolidated.etat_id);
          const canonicalDigest = await runPython(
            python,
            [FIXTURE, "digest", "--payload", JSON.stringify(dossier)],
            env,
            children,
          );
          expect(dossier.dossier_id).toBe(canonicalDigest);
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
          expect((await inspect()).business).toStrictEqual(before.business);
          expect((await inspect()).chain).toStrictEqual(chain);
          const positive = await invoke(employee, "m4_lister_interventions", {});
          expect(positive.status).toBe(200);
          expect(positive.body).toMatchObject({ ok: true, result: { ok: true } });
          const employeeRows = await dispatched();
          expect(employeeRows).toContainEqual(
            expect.objectContaining({
              name: "m4_lister_interventions",
              meta: expect.objectContaining({
                "opsys/personne": "employee-dossier-fictif",
                "opsys/role": "employee",
              }),
            }),
          );
          const preDenial = await inspect(),
            preDispatch = await dispatched();
          const denial = await invoke(employee, tool, args);
          expect(denial.status).toBe(403);
          expect(denial.body).toMatchObject({
            ok: false,
            error: {
              type: "tool_call_blocked",
              message: expect.stringContaining("tool_out_of_scope"),
            },
          });
          expect(denial.body).not.toHaveProperty("result");
          expect(await dispatched()).toStrictEqual(preDispatch);
          expect(await inspect()).toStrictEqual(preDenial);
          const restored = unpack(await invoke(admin, tool, args));
          expect(restored).toStrictEqual(result);
          const finalDispatch = await dispatched();
          expect(finalDispatch.filter((r) => r.name === tool)).toHaveLength(2);
          for (const row of finalDispatch.filter((r) => r.name === tool)) {
            expect(row.meta).toMatchObject({
              "opsys/personne": "admin-dossier-fictif",
              "opsys/role": "admin",
            });
          }
          if (temporal) {
            const diagnostic = result.diagnostic;
            if (!isRecord(diagnostic)) {
              throw new Error("server diagnostic required");
            }
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
            const refuse = async (badArgs: Record<string, unknown>, code: string) => {
              const beforeRefusal = await inspect();
              const ingressBefore = (await dispatched()).filter((row) => row.name === tool).length;
              const response = await invoke(admin, tool, badArgs);
              assertBusinessRefusal(response, code);
              expect((await inspect()).business).toStrictEqual(beforeRefusal.business);
              expect((await inspect()).chain).toStrictEqual(chain);
              expect((await dispatched()).filter((row) => row.name === tool)).toHaveLength(
                ingressBefore + 1,
              );
            };
            await refuse(
              { ...args, horodatage_reference: "2026-10-18T06:00:00" },
              "REJ-DIAGNOSTIC-REFERENCE",
            );
            await refuse(
              { ...args, dossier: { faits_selectionnes: "forgés" } },
              "arguments_invalides",
            );
            const sizes = JSON.parse(
              await runPython(
                python,
                [FIXTURE, "measure", "--payload", JSON.stringify(result)],
                env,
                children,
              ),
            ) as { dossier: number; diagnostic: number; combined: number };
            // Same ASCII question delta increases only the dossier part. Each part still
            // fits the unchanged 5900-char adapter budget; their union must be refused.
            const delta = 5901 - sizes.combined;
            expect(delta).toBeGreaterThan(0);
            expect(args.question.length + delta).toBeLessThanOrEqual(2048);
            expect(sizes.dossier + delta).toBeLessThanOrEqual(5900);
            expect(sizes.diagnostic).toBeLessThanOrEqual(5900);
            await refuse(
              { ...args, question: args.question + "?".repeat(delta) },
              "REJ-DIAGNOSTIC-BORNE",
            );
            const revoked: unknown = JSON.parse(
              await runPython(python, [FIXTURE, "revoke-admin"], env, children),
            );
            expect(revoked).toMatchObject({ admin_role_removed: true });
            await refuse(args, "REJ-IDENTITE-APPAREIL-INVALIDE");
            // Two successes and four separately observed refusals, all admin.
            expect((await dispatched()).filter((row) => row.name === tool)).toHaveLength(
              expectedToolIngress,
            );
            console.info(
              JSON.stringify({
                fictif: true,
                oracle: "M9_TEMPORAL_REAL_HTTP_REFERENCE_PROOFS_ROLES_AND_COMBINED_BOUND",
                explicitReference: diagnostic.reference_source,
                observations: 2,
                sourceRows: chain.length,
                fixedCombinedRefusal: true,
                revokedSqlAdminRefused: true,
                actualMcpIngress: expectedToolIngress,
              }),
            );
          }
          expect((await inspect()).business).toStrictEqual(before.business);
          expect((await inspect()).chain).toStrictEqual(chain);
          console.info(
            JSON.stringify({
              fictif: true,
              oracle: temporal
                ? "M9_TEMPORAL_CORE_HTTP_ADMIN_AND_EMPLOYEE_FENCE"
                : "M9_DOSSIER_CORE_HTTP_ADMIN_AND_EMPLOYEE_FENCE",
              adminStatus: 200,
              employeeStatus: 403,
              adminDossierDispatches: expectedToolIngress,
              employeeDossierDispatches: 0,
              sourceRows: 3,
              fullGatewayHandshake: false,
              fullM9Report: false,
            }),
          );
        } catch (error) {
          failed = true;
          primary = error;
        }
        const errors: unknown[] = [];
        try {
          if (server) {
            server.closeIdleConnections();
            await new Promise<void>((done, reject) => {
              server?.close((error) => (error ? reject(error) : done()));
            });
          }
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
            await stopChildProcess(child, 2000);
            const closed = childCloses.get(child);
            if (!closed) {
              throw new Error("owned closure observer missing");
            }
            await closed;
          } catch (error) {
            errors.push(error);
          }
        }
        if (!failed && errors.length === 0) {
          try {
            if (!assertFinalIngressAfterStop) {
              throw new Error("Final post-stop ingress oracle was not installed");
            }
            await assertFinalIngressAfterStop();
          } catch (error) {
            errors.push(error);
          }
        }
        // Preserve the owned fixture database and dispatch observations on test failure.
        if (!failed && errors.length === 0) {
          await fs.rm(home, { recursive: true, force: true });
        }
        if (errors.length) {
          throw new AggregateError(
            failed ? [primary, ...errors] : errors,
            "M9 owned fixture cleanup failed",
          );
        }
        if (failed) {
          throw primary;
        }
      });
    },
    120000,
  );
}
