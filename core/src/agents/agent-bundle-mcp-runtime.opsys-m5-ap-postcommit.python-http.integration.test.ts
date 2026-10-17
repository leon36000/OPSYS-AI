import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import {
  acquireSessionMcpRuntime,
  getSessionMcpRuntimeManagerForTesting,
  releaseSessionMcpRuntime,
} from "./agent-bundle-mcp-manager-api.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import type { SessionMcpRuntime } from "./agent-bundle-mcp-types.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-m5-ap-postcommit-fixture.py");
const M5 = "m05-financecore";
const M5_TOOL = "m5_corriger_facture_fournisseur";
const M9_TOOL = "m9_decider_demande_approbation";
const M9_ROUTE = "/mcp/m09-strategic-intelligence";
const OWNER = "owner-ap-fictif";
const NON_OWNER = "admin-ap-fictif-non-owner";
const PEOPLE = { [OWNER]: ["admin", "nathan_owner"], [NON_OWNER]: ["admin"] };
const DECISION_T0 = "2026-10-17T12:10:00+00:00";
const DECISION_T1 = "2026-10-17T12:20:00+00:00";
const DEVICE_SESSION = "agent:main:opsys-m5-ap-owner-device-fictif";
const OWNER_DEVICE = "tel-fictif-proprietaire-m5-ap";
const PRIVATE_TOKEN = "synthetic-m5-ap-private-token-2026";
const PUBLIC_TOKEN = "synthetic-m5-ap-public-token-2026";
const MAX_FIXTURE_OUTPUT = 8 * 1024 * 1024;
const children: ChildProcess[] = [];
const tempDirs: string[] = [];
const sessionIds: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

type Row = Record<string, unknown>;
type Invoice = { id: string; seed_demande_id: string; arguments: Row };
type InvoiceState = { rows: Row[]; pieces: Row[]; corrections: number; approvals: Row[] };
type HandlerEvent = { generation: number; tool: string; event: string; arguments_sha256: string };
type Dispatch = {
  generation: number;
  route: string;
  method?: string;
  tool?: string;
  ticket_present?: boolean;
  frame?: Row;
  loss_selected?: boolean;
};
type State = {
  people: Record<string, string[]>;
  invoices: Record<string, InvoiceState>;
  movements: Row[];
  claims: Row[];
  oracle: { demande_id: string; t0: string; rows: Row[]; approval: Row; claim: Row } | null;
  anomalies: string[] | null;
  handler: HandlerEvent[];
  dispatches: Dispatch[];
  origins: Record<string, Record<string, { path: string; sha256: string }>>;
};
type Lost = {
  generation: number;
  demande_id: string;
  native_result: Row;
  t0: string;
  ap_horodatage: string;
  sql_cree_le: string;
  handler_sequence: string[][];
  independent_committed_read_before_headers: boolean;
  response_body_forwarded_bytes: number;
  native_response_bytes_buffered: number;
  original_headers_forwarded: boolean;
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
    throw new Error("OPSYS_TEST_PYTHON is required for the Python HTTP M5 AP integration test");
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
  command: string,
  extraArgs: string[] = [],
): Promise<string> {
  const child = spawn(python, [FIXTURE, command, ...extraArgs], {
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
    const timeout = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`Python fixture ${command} exceeded its 20s deadline`));
    }, 20_000);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("close", (value) => {
      clearTimeout(timeout);
      resolveExit(value ?? 1);
    });
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

async function startPythonMcp(python: string, home: string, args: string[]): Promise<ChildProcess> {
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
  return child;
}

async function startServer(
  python: string,
  home: string,
  generation: number,
  loseDecision: boolean,
): Promise<{ port: number; child: ChildProcess }> {
  const port = await reservePort();
  const child = await startPythonMcp(python, home, [
    FIXTURE,
    "serve",
    "--port",
    String(port),
    "--generation",
    String(generation),
    ...(loseDecision ? ["--lose-decision"] : []),
  ]);
  return { port, child };
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

/** No case-ticket route exists for this M5 AP tool. This is the ordinary production call path. */
function agentConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: { servers: { opsys_m5: httpServer(port, `/mcp/${M5}`, PUBLIC_TOKEN) } },
  };
}

function deviceConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: { servers: { opsys_m9: httpServer(port, M9_ROUTE, PUBLIC_TOKEN) } },
  };
}

/** Host-authenticated frame fixture; the Native/Gateway producer is outside this proof. */
function deviceFrame(person: string, key: string): Record<string, string> {
  return {
    "opsys/idempotencyKey": key,
    "opsys/appareil": OWNER_DEVICE,
    "opsys/horodatageAppareil": "2026-10-17T12:00:00Z",
    "opsys/personne": person,
    "opsys/role": "admin",
  };
}

function envelope(result: CallToolResult, expectedError = false): Row {
  if (expectedError) {
    expect(result.isError).toBe(true);
  } else {
    expect(result.isError).not.toBe(true);
  }
  const texts = result.content.filter((item) => item.type === "text");
  if (texts.length !== 1 || texts[0].type !== "text") {
    throw new Error("native MCP response requires exactly one text result");
  }
  return JSON.parse(texts[0].text) as Row;
}

function decisionArgs(demandeId: string): Row {
  return { demande_id: demandeId, decision: "approuver", motif: "" };
}

/**
 * Production ownership: the acquired lease stays held through every effect, is released exactly
 * once in finally, and the session's native transports must then confirm closure.
 */
class McpLeaseCleanupError extends Error {}

async function withProductionLease<T>(
  params: Parameters<typeof acquireSessionMcpRuntime>[0],
  effect: (runtime: SessionMcpRuntime, activeLeases: () => number) => Promise<T>,
): Promise<T> {
  const manager = getSessionMcpRuntimeManagerForTesting();
  sessionIds.push(params.sessionId);
  const activeLeases = () => manager.totalActiveLeasesForSession(params.sessionId);
  const acquisition = await acquireSessionMcpRuntime(params);
  const { runtime } = acquisition;
  let outcome: { value: T } | undefined;
  let effectFailure: { error: unknown } | undefined;
  let cleanupFailure: { error: unknown } | undefined;
  let leasesAfterRelease: number;
  try {
    if (!runtime.joinCleanup) {
      throw new Error("production MCP runtime exposes no cleanup ownership");
    }
    outcome = { value: await effect(runtime, activeLeases) };
  } catch (error) {
    effectFailure = { error };
  } finally {
    try {
      await releaseSessionMcpRuntime(acquisition);
      leasesAfterRelease = activeLeases();
      await manager.disposeSession(params.sessionId);
      await runtime.joinCleanup?.();
      // This assertion must execute even when the business call throws after its HTTP body is lost.
      expect(leasesAfterRelease).toBe(0);
    } catch (error) {
      cleanupFailure = { error };
    }
  }
  if (cleanupFailure) {
    throw new McpLeaseCleanupError("production MCP lease cleanup failed", {
      cause: cleanupFailure.error,
    });
  }
  if (effectFailure) {
    throw effectFailure.error;
  }
  if (!outcome) {
    throw new Error("production lease effect produced no outcome");
  }
  return outcome.value;
}

async function proposeThroughCore(
  home: string,
  port: number,
  sessionId: string,
  invoice: Invoice,
): Promise<Row> {
  return await withProductionLease(
    {
      sessionId,
      sessionKey: "agent:m05-financecore:ap-fictif",
      workspaceDir: home,
      cfg: agentConfig(port),
    },
    async (runtime, activeLeases) => {
      const held = activeLeases();
      expect(held).toBeGreaterThan(0);
      const result = await runtime.callTool("opsys_m5", M5_TOOL, { ...invoice.arguments });
      expect(activeLeases()).toBe(held);
      return envelope(result);
    },
  );
}

async function decideOnDevice(
  home: string,
  port: number,
  sessionId: string,
  frame: Record<string, string>,
  demandeId: string,
): Promise<CallToolResult> {
  return await withProductionLease(
    { sessionId, sessionKey: DEVICE_SESSION, workspaceDir: home, cfg: deviceConfig(port) },
    async (runtime, activeLeases) => {
      const held = activeLeases();
      expect(held).toBeGreaterThan(0);
      const result = await withMcpCallMeta(frame, () =>
        runtime.callTool("opsys_m9", M9_TOOL, decisionArgs(demandeId)),
      );
      expect(activeLeases()).toBe(held);
      return result;
    },
  );
}

function pendingId(result: Row): string {
  expect(result).toMatchObject({ ok: true, statut: "en_attente_approbation" });
  if (typeof result.demande_id !== "string") {
    throw new Error("genuine M5 proposal returned no pending request id");
  }
  return result.demande_id;
}

function expectPending(state: State, label: string, invoice: Invoice, id: string): void {
  expect(state.people).toStrictEqual(PEOPLE);
  expect(state.movements).toEqual([]);
  const target = state.invoices[label];
  expect(target.corrections).toBe(0);
  expect(target.rows).toHaveLength(1);
  expect(target.pieces[0]).toMatchObject({
    type_entree: "facture_fournisseur_saisie",
    facture_fournisseur_id: invoice.id,
    statut: "SAISIE",
    categorie_depense: "carburant",
    montant_avant_taxes: "100.00",
    montant_apres_taxes: "114.98",
  });
  expect(target.approvals).toHaveLength(1);
  expect(target.approvals[0]).toMatchObject({
    id,
    outil: M5_TOOL,
    departement: M5,
    niveau: "N4",
    statut: "en_attente",
    decide_par: null,
    decide_le: null,
    ticket_cible_hash: null,
  });
  expect(JSON.parse(String(target.approvals[0].arguments))).toStrictEqual(invoice.arguments);
}

function expectDecision(native: Row, id: string, time: string): void {
  expect(native).toMatchObject({
    ok: true,
    rejoue: false,
    resultat: {
      accepte: true,
      resultat: {
        demande_id: id,
        statut: "executee",
        outil: M5_TOOL,
        niveau: "N4",
        departement: M5,
        decide_par: OWNER,
        role: "nathan_owner",
        decide_le: time,
      },
    },
  });
}

function expectCorrected(
  state: State,
  label: string,
  invoice: Invoice,
  id: string,
  time: string,
  before: string,
  after: string,
): void {
  const target = state.invoices[label];
  expect(state.people).toStrictEqual(PEOPLE);
  expect(state.movements).toEqual([]);
  expect(target.rows).toHaveLength(2);
  expect(target.corrections).toBe(1);
  expect(target.approvals).toHaveLength(1);
  expect(target.approvals[0]).toMatchObject({
    id,
    statut: "executee",
    decide_par: OWNER,
    decide_role: "nathan_owner",
    decide_le: time,
    niveau: "N4",
    ticket_cible_hash: null,
  });
  expect(JSON.parse(String(target.approvals[0].arguments))).toStrictEqual(invoice.arguments);
  expect(target.pieces[1]).toMatchObject({
    type_entree: "correction_facture_fournisseur",
    facture_fournisseur_id: invoice.id,
    corrige_par: OWNER,
    horodatage: invoice.arguments.horodatage,
    apres: { montant_avant_taxes: before, montant_apres_taxes: after },
  });
  // AP argument time, approval time and SQL append time are three independent facts.
  expect(target.pieces[1].horodatage).not.toBe(time);
  expect(typeof target.rows[1].cree_le).toBe("string");
  expect(String(target.rows[1].cree_le).length).toBeGreaterThan(0);
}

function expectOrigins(state: State, generation: number): void {
  const origins = state.origins[String(generation)];
  expect(Object.keys(origins).toSorted()).toEqual([
    "m5_financecore.outils",
    "m9_strategic_intelligence.outils",
    "opsys.capacites",
  ]);
  expect(origins["opsys.capacites"].path).toBe(resolve(REPO, "src/opsys/capacites.py"));
  expect(origins["m5_financecore.outils"].path).toBe(
    resolve(REPO, "departments/m05-financecore/src/m5_financecore/outils.py"),
  );
  for (const origin of Object.values(origins)) {
    expect(origin.sha256).toMatch(/^[a-f0-9]{64}$/);
  }
}

function calls(state: State, tool: string): Dispatch[] {
  return state.dispatches.filter((r) => r.method === "tools/call" && r.tool === tool);
}

function originalEntries(state: State, tool: string): HandlerEvent[] {
  return state.handler.filter((r) => r.tool === tool && r.event === "entered");
}

async function readLost(home: string): Promise<Lost> {
  try {
    return JSON.parse(await readFile(resolve(home, "m5-ap-m9-response-lost.json"), "utf8")) as Lost;
  } catch (error) {
    const refused = await readFile(resolve(home, "m5-ap-loss-gate-refused.json"), "utf8").catch(
      () => "no gate report",
    );
    throw new Error(`no independently committed AP response was lost: ${refused}`, {
      cause: error,
    });
  }
}

afterEach(async () => {
  const manager = getSessionMcpRuntimeManagerForTesting();
  try {
    for (const sessionId of sessionIds.splice(0)) {
      await manager.disposeSession(sessionId);
    }
  } finally {
    try {
      for (const child of children.splice(0)) {
        await stopChild(child);
      }
    } finally {
      await Promise.all(
        tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
      );
      await releaseContextConfig?.();
      releaseContextConfig = undefined;
      await resetSessionMcpRuntimeManagerGeneration();
    }
  }
});

describe("OPSYS M5 AP N4 and owner M9 decisions through production Core leases and real Python HTTP", () => {
  it("keeps a real M5 AP N4 correction pending until its legitimate M9 owner decides", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m5-ap-pending-"));
    tempDirs.push(home);
    const { invoice } = JSON.parse(await runFixture(python, home, "prepare")) as {
      invoice: Invoice;
    };
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const seeded = await inspect();
    expect(seeded.invoices.A.approvals).toEqual([]);
    const { port } = await startServer(python, home, 1, false);
    const id = pendingId(await proposeThroughCore(home, port, "m5-ap-pending-agent", invoice));
    const pending = await inspect();
    expectPending(pending, "A", invoice, id);
    expect(pending.handler).toEqual([]);
    expect(calls(pending, M5_TOOL)).toHaveLength(1);
    expect(calls(pending, M5_TOOL)[0].ticket_present).toBe(false);
    expect(calls(pending, M5_TOOL)[0].frame).toStrictEqual({
      personne: null,
      role: null,
      appareil: null,
      idempotencyKey: null,
      horodatageAppareil: null,
    });

    // Same real device, active admin, fresh key: authority refusal does not revoke the owner.
    const refused = envelope(
      await decideOnDevice(
        home,
        port,
        "m5-ap-pending-non-owner",
        deviceFrame(NON_OWNER, "m5-ap-refuse-fresh"),
        id,
      ),
    );
    expect(refused).toMatchObject({
      ok: true,
      resultat: { accepte: false, verdict: { code: "reserve_au_proprietaire" } },
    });
    const afterRefusal = await inspect();
    expectPending(afterRefusal, "A", invoice, id);
    expect(afterRefusal.invoices.A.rows).toStrictEqual(pending.invoices.A.rows);
    expect(originalEntries(afterRefusal, M5_TOOL)).toEqual([]);

    const accepted = envelope(
      await decideOnDevice(
        home,
        port,
        "m5-ap-pending-owner",
        deviceFrame(OWNER, "m5-ap-owner-fresh"),
        id,
      ),
    );
    expectDecision(accepted, id, DECISION_T0);
    const decided = await inspect();
    expectCorrected(decided, "A", invoice, id, DECISION_T0, "310.00", "356.42");
    expect(decided.invoices.A.rows[0]).toStrictEqual(seeded.invoices.A.rows[0]);
    expect(originalEntries(decided, M5_TOOL)).toHaveLength(1);
    expect(calls(decided, M9_TOOL)).toHaveLength(2);
    expect(calls(decided, M9_TOOL).every((r) => r.ticket_present === false)).toBe(true);
    expectOrigins(decided, 1);
  }, 90_000);

  it("preserves one committed M5 AP correction after lost M9 ACK and explicit replay across restart", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m5-ap-lost-"));
    tempDirs.push(home);
    const { invoice } = JSON.parse(await runFixture(python, home, "prepare")) as {
      invoice: Invoice;
    };
    const inspect = async (database?: string) =>
      JSON.parse(
        await runFixture(python, home, "inspect", database ? ["--database", database] : []),
      ) as State;
    const first = await startServer(python, home, 1, true);
    const id = pendingId(await proposeThroughCore(home, first.port, "m5-ap-lost-agent", invoice));
    const before = await inspect();
    expectPending(before, "A", invoice, id);
    const ownerFrame = deviceFrame(OWNER, "m5-ap-owner-lost-key");
    let transportFailure: unknown;
    try {
      await decideOnDevice(home, first.port, "m5-ap-lost-owner", ownerFrame, id);
    } catch (error) {
      transportFailure = error;
    }
    expect(transportFailure).toBeInstanceOf(Error);
    expect(transportFailure).not.toBeInstanceOf(McpLeaseCleanupError);
    const lost = await readLost(home);
    expect(lost).toMatchObject({
      generation: 1,
      demande_id: id,
      t0: DECISION_T0,
      ap_horodatage: invoice.arguments.horodatage,
      independent_committed_read_before_headers: true,
      response_body_forwarded_bytes: 0,
      original_headers_forwarded: true,
      handler_sequence: [
        [M9_TOOL, "entered"],
        [M5_TOOL, "entered"],
        [M5_TOOL, "completed"],
        [M9_TOOL, "completed"],
      ],
    });
    expect(lost.native_response_bytes_buffered).toBeGreaterThan(0);
    expect(typeof lost.sql_cree_le).toBe("string");
    expectDecision(lost.native_result, id, DECISION_T0);
    const committed = await inspect();
    expectCorrected(committed, "A", invoice, id, DECISION_T0, "310.00", "356.42");
    expect(committed.anomalies).toEqual([]);
    expect(originalEntries(committed, M5_TOOL)).toHaveLength(1);
    expect(originalEntries(committed, M9_TOOL)).toHaveLength(1);
    expect(calls(committed, M9_TOOL)).toHaveLength(1);
    expect(committed.claims).toHaveLength(1);
    expect(committed.invoices.A.rows[0]).toStrictEqual(before.invoices.A.rows[0]);
    await stopChild(first.child);
    await resetSessionMcpRuntimeManagerGeneration();

    const second = await startServer(python, home, 2, false);
    const replay = envelope(
      await decideOnDevice(home, second.port, "m5-ap-replay-owner", ownerFrame, id),
    );
    expect(replay).toStrictEqual({ ...lost.native_result, rejoue: true });
    const afterReplay = await inspect();
    expect(afterReplay.invoices.A).toStrictEqual(committed.invoices.A);
    expect(afterReplay.claims).toStrictEqual(committed.claims);
    expect(afterReplay.anomalies).toEqual([]);
    // Cached replay sends a real second RPC, and deliberately does not enter either original handler.
    expect(calls(afterReplay, M9_TOOL)).toHaveLength(2);
    expect(originalEntries(afterReplay, M9_TOOL)).toHaveLength(1);
    expect(originalEntries(afterReplay, M5_TOOL)).toHaveLength(1);

    const wrongActor = envelope(
      await decideOnDevice(
        home,
        second.port,
        "m5-ap-replay-non-owner",
        { ...ownerFrame, "opsys/personne": NON_OWNER },
        id,
      ),
      true,
    );
    expect(wrongActor).toMatchObject({
      ok: false,
      erreur: "confirmation_transport_indisponible",
      issue: "inconnue",
    });
    expect(wrongActor).not.toHaveProperty("resultat");
    expect(wrongActor.rejoue).not.toBe(true);
    const afterWrong = await inspect();
    expect(afterWrong.people).toStrictEqual(PEOPLE);
    expect(afterWrong.invoices.A).toStrictEqual(committed.invoices.A);
    expect(afterWrong.claims).toStrictEqual(committed.claims);
    expect(afterWrong.anomalies).toEqual([]);
    expect(originalEntries(afterWrong, M9_TOOL)).toHaveLength(1);
    expect(originalEntries(afterWrong, M5_TOOL)).toHaveLength(1);

    const { invoice: fresh } = JSON.parse(await runFixture(python, home, "prepare-b")) as {
      invoice: Invoice;
    };
    const freshId = pendingId(
      await proposeThroughCore(home, second.port, "m5-ap-fresh-agent", fresh),
    );
    expect(freshId).not.toBe(id);
    expectPending(await inspect(), "B", fresh, freshId);
    const accepted = envelope(
      await decideOnDevice(
        home,
        second.port,
        "m5-ap-fresh-owner",
        deviceFrame(OWNER, "m5-ap-owner-fresh-after-restart"),
        freshId,
      ),
    );
    expectDecision(accepted, freshId, DECISION_T1);
    expect(DECISION_T1 > DECISION_T0).toBe(true);
    const final = await inspect();
    expectCorrected(final, "B", fresh, freshId, DECISION_T1, "320.00", "367.92");
    expectCorrected(final, "A", invoice, id, DECISION_T0, "310.00", "356.42");
    expect(final.invoices.A).toStrictEqual(committed.invoices.A);
    expect(final.anomalies).toEqual([]);
    expect(originalEntries(final, M5_TOOL)).toHaveLength(2);
    expect(originalEntries(final, M9_TOOL)).toHaveLength(2);
    expectOrigins(final, 1);
    expectOrigins(final, 2);

    // Demonstrate that the frozen witness rejects real corruption, only in owned disposable copies.
    const { snapshots } = JSON.parse(await runFixture(python, home, "snapshot-negatives")) as {
      snapshots: Record<string, string>;
    };
    const expected: Record<string, string[]> = {
      intact: [],
      duplicate_correction: ["AP_ORIGINAL_CHANGED"],
      ap_timestamp: ["AP_ORIGINAL_CHANGED"],
      amount: ["AP_ORIGINAL_CHANGED"],
      decision_timestamp: ["DECISION_T0_CHANGED"],
      claim: ["OWNER_CLAIM_CHANGED"],
    };
    expect(Object.keys(snapshots).toSorted()).toEqual(Object.keys(expected).toSorted());
    for (const [name, database] of Object.entries(snapshots)) {
      expect((await inspect(database)).anomalies).toEqual(expected[name]);
    }
    const afterCopies = await inspect();
    expect(afterCopies.invoices).toStrictEqual(final.invoices);
    expect(afterCopies.claims).toStrictEqual(final.claims);
    expect(afterCopies.anomalies).toEqual([]);
  }, 170_000);
});
