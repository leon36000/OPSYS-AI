import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import {
  acquireSessionMcpRuntime,
  getSessionMcpRuntimeManagerForTesting,
  releaseSessionMcpRuntime,
} from "./agent-bundle-mcp-manager-api.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import type { SessionMcpRuntime } from "./agent-bundle-mcp-types.js";
import { requiresMcpCodexToolApproval } from "./mcp-codex-tool-approval.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const M8_FIXTURE = resolve(REPO, "core/test/opsys-m8-n2-fixture.py");
const TARGET_FIXTURE = resolve(REPO, "core/test/opsys-target-ticket-fixture.py");
const M8_SESSION = "agent:m08-analytics:webchat:direct:core-m8-n2-fictif";
const M8_SESSION_ID = "opsys-real-python-m8-n2";
const M8_N0_TOOL = "m8_resoudre_definition_metrique";
const M8_N2_TOOL = "m8_evaluer_qualite_metrique";
const M8_REFERENCE = "2026-01-11T00:00:00Z";
// Fixed by the existing target ticket fixture, which links this exact session to the lead.
const M2_SESSION = "agent:m02-revenue-crm:webchat:direct:core-c02";
const M2_SESSION_ID = "opsys-real-python-m8-n2-m2-n3";
const M2_TOOL = "m2_enregistrer_interaction";
const M2_LEAD = "LEAD-CORE-C02";
const M2_ARGS = {
  lead_id: M2_LEAD,
  auteur: "nathan-fixture",
  resume: "interaction fictive proposée par l'agent via Core",
  horodatage: "2026-09-30T12:00:00+00:00",
};
const PRIVATE_TOKEN = "synthetic-m8-n2-private-token-2026";
const PUBLIC_TOKEN = "synthetic-m8-n2-public-token-2026";
const MAX_FIXTURE_OUTPUT = 8 * 1024 * 1024;
const children: ChildProcess[] = [];
const tempDirs: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

type M8Inspection = {
  fictif: boolean;
  database: {
    digest: string;
    rows: Record<string, number>;
    schema_version: number;
    meta_tables_covered: boolean;
  };
  outbox: { type_evenement: string; producteur: string; charge: Record<string, unknown> }[];
  approvals: { id: string; departement: string; outil: string; statut: string }[];
};

async function resetSessionMcpRuntimeManagerGeneration(): Promise<void> {
  await getSessionMcpRuntimeManagerForTesting().disposeAll();
  Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
}

beforeEach(async () => {
  await resetSessionMcpRuntimeManagerGeneration();
  releaseContextConfig = await acquireOpsysContextTestConfig();
});

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the Python HTTP M8 integration test");
  }
  return python;
}

function childExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (childExited(child)) {
    return;
  }
  child.kill("SIGTERM");
  const exited = await new Promise<boolean>((resolveExit) => {
    const timeout = setTimeout(() => resolveExit(false), 2_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveExit(true);
    });
  });
  if (exited || childExited(child)) {
    return;
  }
  child.kill("SIGKILL");
  await new Promise<void>((resolveExit, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("Python MCP process survived SIGKILL")),
      2_000,
    );
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveExit();
    });
  });
}

function pythonEnv(home: string): NodeJS.ProcessEnv {
  const departments = [
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
  return {
    OPSYS_HOME: home,
    OPSYS_BASE_URL: `sqlite:///${resolve(home, "opsys.db")}`,
    OPSYS_MCP_JETON: PUBLIC_TOKEN,
    OPSYS_CONTEXT_MCP_JETON: PRIVATE_TOKEN,
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    PYTHONPATH: [
      resolve(REPO, "src"),
      ...departments.map((name) => resolve(REPO, `departments/${name}/src`)),
    ].join(":"),
  };
}

async function runFixture(
  python: string,
  home: string,
  fixture: string,
  command: string,
  extraArgs: string[] = [],
): Promise<string> {
  const child = spawn(python, [fixture, command, ...extraArgs], {
    cwd: REPO,
    env: pythonEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  let stdout = "";
  let stderr = "";
  let overflow = false;
  const collect = (append: (chunk: string) => void) => (chunk: string) => {
    if (stdout.length + stderr.length + chunk.length > MAX_FIXTURE_OUTPUT) {
      overflow = true;
      child.kill("SIGKILL");
      return;
    }
    append(chunk);
  };
  child.stdout?.setEncoding("utf8").on(
    "data",
    collect((chunk) => (stdout += chunk)),
  );
  child.stderr?.setEncoding("utf8").on(
    "data",
    collect((chunk) => (stderr += chunk)),
  );
  const code = await new Promise<number>((resolveExit, reject) => {
    child.once("error", reject);
    child.once("exit", (value) => resolveExit(value ?? 1));
  });
  if (overflow) {
    throw new Error(`Python fixture ${command} exceeded the bounded output`);
  }
  if (code !== 0) {
    throw new Error(`Python fixture ${command} failed (${code}): ${stderr.slice(-2_000)}`);
  }
  return stdout.trim();
}

async function reservePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not allocate loopback port");
  }
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  return address.port;
}

async function startPythonMcp(python: string, home: string, args: string[]): Promise<void> {
  const child = spawn(python, args, {
    cwd: REPO,
    env: pythonEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  let output = "";
  await new Promise<void>((resolveReady, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`Python MCP startup timed out: ${output.slice(-2_000)}`)),
      15_000,
    );
    // The pipes stay drained for the server lifetime; only a bounded tail is retained.
    const onData = (chunk: string) => {
      output = (output + chunk).slice(-65_536);
      if (output.includes("Uvicorn running on")) {
        clearTimeout(timeout);
        resolveReady();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", onData);
    child.stderr?.setEncoding("utf8").on("data", onData);
    child.once("error", reject);
    child.once("exit", (code) =>
      reject(new Error(`Python MCP exited during startup (${code}): ${output.slice(-2_000)}`)),
    );
  });
}

function httpServer(port: number, path: string, bearer: string) {
  return {
    url: `http://127.0.0.1:${port}${path}`,
    transport: "streamable-http" as const,
    transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
    headers: { Authorization: `Bearer ${bearer}` },
    connectionTimeoutMs: 5_000,
    requestTimeoutMs: 10_000,
  };
}

function m8OpsysConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: { servers: { opsys_m8: httpServer(port, "/mcp/m08-analytics", PUBLIC_TOKEN) } },
  };
}

function m2OpsysConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_m2: httpServer(port, "/mcp/m02-revenue-crm", PUBLIC_TOKEN),
        "opsys_context_m02-revenue-crm": httpServer(
          port,
          "/mcp/contexte/m02-revenue-crm",
          PRIVATE_TOKEN,
        ),
      },
    },
  };
}

function envelope(result: CallToolResult): Record<string, unknown> {
  const text = result.content.find((item) => item.type === "text")?.text;
  return JSON.parse(text ?? "null") as Record<string, unknown>;
}

/**
 * Production ownership: the acquired lease stays held through every effect, is released exactly
 * once in finally, and the session's native transports must then confirm closure.
 */
async function withProductionLease<T>(
  params: Parameters<typeof acquireSessionMcpRuntime>[0],
  effect: (runtime: SessionMcpRuntime, activeLeases: () => number) => Promise<T>,
): Promise<T> {
  const manager = getSessionMcpRuntimeManagerForTesting();
  const activeLeases = () => manager.totalActiveLeasesForSession(params.sessionId);
  const acquisition = await acquireSessionMcpRuntime(params);
  const { runtime } = acquisition;
  let outcome: { value: T } | undefined;
  let leasesAfterRelease = -1;
  try {
    outcome = { value: await effect(runtime, activeLeases) };
  } finally {
    await releaseSessionMcpRuntime(acquisition);
    leasesAfterRelease = activeLeases();
    await manager.disposeSession(params.sessionId);
    if (!runtime.joinCleanup) {
      throw new Error("production MCP runtime exposes no cleanup ownership");
    }
    await runtime.joinCleanup();
  }
  expect(leasesAfterRelease).toBe(0);
  if (!outcome) {
    throw new Error("production lease effect produced no outcome");
  }
  return outcome.value;
}

afterEach(async () => {
  const manager = getSessionMcpRuntimeManagerForTesting();
  await manager.disposeSession(M8_SESSION_ID);
  await manager.disposeSession(M2_SESSION_ID);
  opsysContexteGuardStore.clear();
  for (const child of children.splice(0)) {
    await stopChild(child);
  }
  await Promise.all(
    tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
  await releaseContextConfig?.();
  releaseContextConfig = undefined;
  await resetSessionMcpRuntimeManagerGeneration();
});

describe("OPSYS M8 N0/N2 and M2 N3 through a production-leased Core runtime and real Python HTTP", () => {
  it("discovers real M8 annotations, keeps N0 free of SQL writes, and commits one N2 alert without approval", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m8-n2-http-"));
    tempDirs.push(home);
    const traceOracle = JSON.parse(
      await runFixture(python, home, M8_FIXTURE, "verify-sql-trace"),
    ) as Record<string, unknown>;
    expect(traceOracle).toStrictEqual({
      fictif: true,
      readonly_select_observations: 0,
      ambiguous_noop_write_observations: ["UNKNOWN", "UNKNOWN"],
      rows_after_noop_writes: 0,
    });
    const prepared = JSON.parse(await runFixture(python, home, M8_FIXTURE, "prepare-m8")) as {
      fictif: boolean;
      metric_id: string;
      definition: Record<string, unknown>;
    };
    expect(prepared.fictif).toBe(true);
    const inspect = async () =>
      JSON.parse(await runFixture(python, home, M8_FIXTURE, "inspect-m8")) as M8Inspection;
    const seeded = await inspect();
    expect(seeded).toMatchObject({
      fictif: true,
      database: { meta_tables_covered: true },
      outbox: [],
      approvals: [],
    });
    const port = await reservePort();
    await startPythonMcp(python, home, [M8_FIXTURE, "serve-m8", "--port", String(port)]);
    const readSqlWrites = async () =>
      (await readFile(resolve(home, "m8-n2-sql-writes.jsonl"), "utf8"))
        .trim()
        .split("\n")
        .filter(Boolean)
        .map((row) => JSON.parse(row) as { fictif: boolean; operation: string });

    await withProductionLease(
      {
        sessionId: M8_SESSION_ID,
        sessionKey: M8_SESSION,
        workspaceDir: home,
        cfg: m8OpsysConfig(port),
      },
      async (runtime, activeLeases) => {
        expect(activeLeases()).toBe(1);
        const catalog = await runtime.getCatalog();
        const m8Tool = (name: string) => {
          const tool = catalog.tools.find(
            (entry) => entry.serverName === "opsys_m8" && entry.toolName === name,
          );
          if (!tool) {
            throw new Error(`real M8 catalog is missing ${name}`);
          }
          return tool;
        };
        const n0Tool = m8Tool(M8_N0_TOOL);
        const n2Tool = m8Tool(M8_N2_TOOL);
        expect(n0Tool.codexAnnotations).toStrictEqual({
          readOnlyHint: true,
          destructiveHint: false,
          idempotentHint: true,
        });
        // The corrected N2 declaration says it writes; openWorld stays absent.
        expect(n2Tool.codexAnnotations).toStrictEqual({
          readOnlyHint: false,
          destructiveHint: false,
          idempotentHint: false,
        });
        // Characterizes the unchanged conservative Core policy; not a Codex prompt claim.
        const mode = catalog.servers.opsys_m8?.codexApprovalMode;
        expect(mode).toBeUndefined();
        expect(requiresMcpCodexToolApproval({ mode, annotations: n0Tool.codexAnnotations })).toBe(
          false,
        );
        expect(requiresMcpCodexToolApproval({ mode, annotations: n2Tool.codexAnnotations })).toBe(
          true,
        );

        // Discovery has settled: snapshot the whole database and the server's write counter.
        const writesBeforeN0 = await readSqlWrites();
        const beforeN0 = await inspect();
        const n0 = await runtime.callTool("opsys_m8", M8_N0_TOOL, {
          metric_id: prepared.metric_id,
        });
        expect(n0.isError).not.toBe(true);
        expect(envelope(n0)).toMatchObject({
          ok: true,
          resultat: { trouvee: true, verdict: null, definition: prepared.definition },
        });
        const afterN0 = await inspect();
        const writesAfterN0 = await readSqlWrites();
        // A database snapshot alone cannot exclude no-op writes; the SQL counter can.
        expect({ database: afterN0.database, writes: writesAfterN0 }).toStrictEqual({
          database: beforeN0.database,
          writes: writesBeforeN0,
        });
        expect(afterN0.outbox).toEqual([]);
        expect(afterN0.approvals).toEqual([]);

        const n2 = await runtime.callTool("opsys_m8", M8_N2_TOOL, {
          metric_id: prepared.metric_id,
          horodatage_reference: M8_REFERENCE,
        });
        expect(n2.isError).not.toBe(true);
        const n2Envelope = envelope(n2);
        expect(n2Envelope.ok).toBe(true);
        expect(n2Envelope).not.toHaveProperty("statut");
        expect(n2Envelope).not.toHaveProperty("demande_id");
        const proposed = (n2Envelope.resultat as { alertes_proposees: { type_alerte: string }[] })
          .alertes_proposees;
        expect(proposed.map((alert) => alert.type_alerte)).toEqual(["REJ-QUALITE-DONNEE-PERIMEE"]);
        expect(activeLeases()).toBe(1);

        // Independent read-only connection after the awaited native HTTP response.
        const afterN2 = await inspect();
        expect(afterN2.approvals).toEqual([]);
        expect(afterN2.outbox).toHaveLength(1);
        expect(afterN2.outbox[0]).toMatchObject({
          type_evenement: "m8.alerte_proposee",
          producteur: "m08-analytics",
          charge: {
            metric_id: prepared.metric_id,
            type_alerte: "REJ-QUALITE-DONNEE-PERIMEE",
            horodatage_reference: M8_REFERENCE,
          },
        });
        expect(afterN2.database.digest).not.toBe(afterN0.database.digest);
        // Positive witness: the same observer that saw nothing for N0 sees the N2 commit.
        expect((await readSqlWrites()).slice(writesAfterN0.length)).toContainEqual({
          fictif: true,
          operation: "INSERT",
        });
      },
    );
  }, 90_000);

  it("leaves a real M2 N3 agent call pending without an interaction until the native owner approval commits one", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m8-n2-m2-n3-http-"));
    tempDirs.push(home);
    await runFixture(python, home, TARGET_FIXTURE, "prepare");
    const inspect = async () =>
      JSON.parse(await runFixture(python, home, TARGET_FIXTURE, "inspect")) as {
        interactions: number;
        linked: boolean;
      };
    const readApprovals = () => {
      const disk = new DatabaseSync(resolve(home, "opsys.db"), { readOnly: true });
      try {
        return disk
          .prepare(
            "SELECT id, departement, outil, statut, niveau, decide_par, decide_role, ticket_cible_hash FROM approbations ORDER BY cree_le",
          )
          .all();
      } finally {
        disk.close();
      }
    };
    expect(await inspect()).toStrictEqual({ interactions: 0, linked: true });
    expect(readApprovals()).toEqual([]);
    const port = await reservePort();
    await startPythonMcp(python, home, [
      "-m",
      "opsys.serveur_mcp",
      "--http",
      "--hote",
      "127.0.0.1",
      "--port",
      String(port),
    ]);

    await withProductionLease(
      {
        sessionId: M2_SESSION_ID,
        sessionKey: M2_SESSION,
        workspaceDir: home,
        cfg: m2OpsysConfig(port),
      },
      async (runtime, activeLeases) => {
        // The public business server and private target issuer each retain their own lease.
        expect(activeLeases()).toBe(2);
        opsysContexteGuardStore.set(M2_SESSION, {
          kind: "ready",
          affaireId: M2_LEAD,
          nbOuverts: 0,
          atMs: Date.now(),
        });
        // No device identity: the actual Core private issuer seals the target ticket.
        const result = await runtime.callTool("opsys_m2", M2_TOOL, M2_ARGS);
        expect(result.isError).not.toBe(true);
        const pending = envelope(result);
        expect(pending).toMatchObject({ ok: true, statut: "en_attente_approbation" });
        const requestId = pending.demande_id;
        if (typeof requestId !== "string") {
          throw new Error("real M2 N3 call returned no pending request id");
        }
        const [sealed] = readApprovals();
        expect(readApprovals()).toEqual([
          {
            id: requestId,
            departement: "m02-revenue-crm",
            outil: M2_TOOL,
            statut: "en_attente",
            niveau: "N3",
            decide_par: null,
            decide_role: null,
            ticket_cible_hash: expect.stringMatching(/^[a-f0-9]{64}$/),
          },
        ]);
        expect(await inspect()).toStrictEqual({ interactions: 0, linked: true });

        // The existing helper injects the fictive owner's choice into the real native approval.
        const decision = JSON.parse(
          await runFixture(python, home, TARGET_FIXTURE, "approve", ["--request-id", requestId]),
        ) as Record<string, unknown>;
        expect(decision).toMatchObject({ statut: "executee" });
        expect(readApprovals()).toEqual([
          {
            ...sealed,
            statut: "executee",
            decide_par: "nathan-fixture",
            decide_role: "nathan_owner",
          },
        ]);
        expect(await inspect()).toStrictEqual({ interactions: 1, linked: true });
        expect(activeLeases()).toBe(2);
      },
    );
  }, 90_000);
});
