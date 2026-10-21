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
import { opsysContexteGuardStore } from "../context-engine/opsys-contexte-garde.js";
import {
  acquireSessionMcpRuntime,
  getSessionMcpRuntimeManagerForTesting,
  releaseSessionMcpRuntime,
} from "./agent-bundle-mcp-manager-api.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import type { SessionMcpRuntime } from "./agent-bundle-mcp-types.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-m3-n4-postcommit-fixture.py");
const M3 = "m03-estimation";
const M3_TOOL = "m3_demander_envoi_devis";
const M9_TOOL = "m9_decider_demande_approbation";
const M9_ROUTE = "/mcp/m09-strategic-intelligence";
const CONTEXT_TOOL = "opsys_contexte_creer_ticket_cible";
const OWNER = "proprio";
const DECISION_T0 = "2026-10-17T12:10:00+00:00";
const DECISION_T1 = "2026-10-17T12:20:00+00:00";
const NON_OWNER = "admin-fictif-non-proprietaire";
const PEOPLE = { [OWNER]: ["admin", "nathan_owner"], [NON_OWNER]: ["admin"] };
// Host-owned device session for the human decision; it never carries a model-issued ticket.
const DEVICE_SESSION = "agent:main:opsys-m3-n4-owner-device-fictif";
const OWNER_DEVICE = "tel-fictif-proprietaire-m3-n4";
const NON_OWNER_DEVICE = "tel-fictif-admin-non-proprietaire-m3-n4";
const PRIVATE_TOKEN = "synthetic-m3-n4-postcommit-private-token-2026";
const PUBLIC_TOKEN = "synthetic-m3-n4-postcommit-public-token-2026";
const MAX_FIXTURE_OUTPUT = 8 * 1024 * 1024;
const TICKET_HASH = /^[a-f0-9]{64}$/;
const children: ChildProcess[] = [];
const tempDirs: string[] = [];
const sessionIds: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

type Row = Record<string, unknown>;

type Quote = {
  lead_id: string;
  devis_id: string;
  source_hash: string;
  session_key: string;
  arguments: Row;
  devis_avant: Record<string, string | null>;
};

type QuoteState = {
  statuses: string[];
  lines: Row[];
  approvals: Row[];
  outbox: Row[];
  charges: Row[];
  m2_facts: Row[];
  received: { consommateur: string; statut: string; tentatives: number }[];
  tickets: Row[];
};

type Frozen = {
  t0: string;
  demande_id: string;
  devis_id: string;
  lead_id: string;
  arguments: Row;
  source_hash: string;
  approbation: Row;
  lignes_devis_a: Row[];
  outbox_a: Row;
  ticket_a: Row;
  evenement_a: string;
  client_id: unknown;
  approvals_equal_t0: boolean;
  outbox_equal_t0: boolean;
  journal_t0_max: number;
  anomalies: string[];
};

type Dispatch = {
  generation: number;
  route: string;
  http: string;
  method?: string;
  rpc_id?: unknown;
  tool?: string | null;
  ticket_hash?: string | null;
  frame?: Record<string, unknown>;
  issue?: Record<string, unknown>;
  arguments_sha256?: string;
  loss_selected?: boolean;
};

type HandlerEvent = {
  generation: number;
  event: string;
  arguments_sha256: string;
  accepte?: boolean | null;
  verdict?: string | null;
};

type State = {
  people: Record<string, string[]>;
  quotes: Record<string, QuoteState>;
  approvals_total: number;
  events_total: number;
  journal: { id: number; par: string; action: string; cible: string }[];
  mutations: { appareil: string; cle: string; outil: string; statut: string; reponse: unknown }[];
  oracle: Frozen | null;
  handler: HandlerEvent[];
  dispatches: Dispatch[];
};

type Lost = {
  fictif: boolean;
  generation: number;
  rpc_id: unknown;
  demande_id: string;
  devis_id: string;
  t0: string;
  native_result: Row;
  handler_events_before_loss: string[];
  owner_roles: string[];
  independent_committed_read_before_headers: boolean;
  response_body_forwarded_bytes: number;
  native_response_bytes_buffered: number;
  original_headers_forwarded: boolean;
};

type Dispatched = {
  first: Record<string, number>;
  second: Record<string, number>;
  clients: Record<string, unknown>;
};

type Snapshots = { snapshots: Record<string, string> };

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
    throw new Error("OPSYS_TEST_PYTHON is required for the Python HTTP M3 N4 integration test");
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

/** The M3 agent session: public business server plus its private target issuer. */
function agentConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_m3: httpServer(port, `/mcp/${M3}`, PUBLIC_TOKEN),
        [`opsys_context_${M3}`]: httpServer(port, `/mcp/contexte/${M3}`, PRIVATE_TOKEN),
      },
    },
  };
}

/** The human owner-device surface: only the public M9 business server. */
function deviceConfig(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: { servers: { opsys_m9: httpServer(port, M9_ROUTE, PUBLIC_TOKEN) } },
  };
}

/**
 * Explicit test fixture of the host-authenticated device frame consumed by production `callTool`.
 * Its Native/Gateway producer is not exercised here; no model ever supplies these values.
 */
function deviceFrame(
  person: string,
  device: string,
  key: string,
  deviceTime: string,
): Record<string, string> {
  return {
    "opsys/idempotencyKey": key,
    "opsys/appareil": device,
    "opsys/horodatageAppareil": deviceTime,
    "opsys/personne": person,
    "opsys/role": "admin",
  };
}

function frameOnWire(frame: Record<string, string>): Record<string, unknown> {
  return {
    personne: frame["opsys/personne"],
    role: frame["opsys/role"],
    appareil: frame["opsys/appareil"],
    idempotencyKey: frame["opsys/idempotencyKey"],
    horodatageAppareil: frame["opsys/horodatageAppareil"],
  };
}

const NO_FRAME = {
  personne: null,
  role: null,
  appareil: null,
  idempotencyKey: null,
  horodatageAppareil: null,
};

function envelope(result: CallToolResult): Record<string, unknown> {
  const text = result.content.find((item) => item.type === "text")?.text;
  return JSON.parse(text ?? "null") as Record<string, unknown>;
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

/** The real Core agent path: guard ready on the linked case, Core issues the private target. */
async function proposeThroughCore(
  home: string,
  port: number,
  sessionId: string,
  quote: Quote,
): Promise<Record<string, unknown>> {
  return await withProductionLease(
    { sessionId, sessionKey: quote.session_key, workspaceDir: home, cfg: agentConfig(port) },
    async (runtime, activeLeases) => {
      const held = activeLeases();
      expect(held).toBeGreaterThan(0);
      opsysContexteGuardStore.set(quote.session_key, {
        kind: "ready",
        affaireId: quote.lead_id,
        nbOuverts: 0,
        atMs: Date.now(),
      });
      // No ambient frame: this is a model call, so no identity can ride along with it.
      const result = await runtime.callTool("opsys_m3", M3_TOOL, { ...quote.arguments });
      expect(result.isError).not.toBe(true);
      expect(activeLeases()).toBe(held);
      return envelope(result);
    },
  );
}

/** The human owner-device decision through production `callTool` under a host-owned frame. */
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

/** The loss proof; a gate that refused to lose an unproven response reports why instead. */
async function readLost(home: string): Promise<string> {
  try {
    return await readFile(resolve(home, "m3-n4-m9-response-lost.json"), "utf8");
  } catch (error) {
    const report = resolve(home, "m3-n4-m9-loss-gate-refused.json");
    const refused = await readFile(report, "utf8").catch(() => "no gate report");
    throw new Error(`no committed M9 response was lost: ${refused}`, { cause: error });
  }
}

function ownerDeviceFrame(key: string, deviceTime: string): Record<string, string> {
  return deviceFrame(OWNER, OWNER_DEVICE, key, deviceTime);
}

function decidedAtOf(decided: Record<string, unknown>): string {
  return (decided.resultat as { resultat: { decide_le: string } }).resultat.decide_le;
}

function businessCalls(state: State, route: string, tool: string): Dispatch[] {
  return state.dispatches.filter(
    (row) => row.route === route && row.method === "tools/call" && row.tool === tool,
  );
}

/** Frames of the M9 decision POSTs, exactly as they reached the native wire. */
function m9Frames(state: State): unknown[] {
  const calls = businessCalls(state, "m9", M9_TOOL);
  return calls.map((row) => row.frame);
}

/** Entries of the original M9 decision handler, per native server generation. */
function handlerOutcomes(state: State, generation: number): (string | null)[][] {
  const rows = state.handler.filter((row) => row.generation === generation);
  return rows.map((row) => [row.event, row.verdict ?? null]);
}

function audits(state: State, action: string): State["journal"] {
  return state.journal.filter((row) => row.action === action);
}

/** One pending N4 request created through the Core-issued target; no M3 effect at all. */
function expectPendingProposal(
  state: State,
  label: string,
  quote: Quote,
  demandeId: string,
  generation: number,
): Row {
  const target = state.quotes[label];
  expect(target.statuses).toEqual(["brouillon"]);
  expect(target.outbox).toEqual([]);
  expect(target.m2_facts).toEqual([]);
  expect(target.received).toEqual([]);
  expect(target.approvals).toHaveLength(1);
  const [approval] = target.approvals;
  expect(approval).toMatchObject({
    id: demandeId,
    departement: M3,
    outil: M3_TOOL,
    statut: "en_attente",
    niveau: "N4",
    decide_par: null,
    decide_le: null,
    ticket_cible_hash: expect.stringMatching(TICKET_HASH),
  });
  expect(JSON.parse(String(approval.arguments))).toStrictEqual(quote.arguments);
  expect(target.tickets).toEqual([
    expect.objectContaining({
      ticket_hash: approval.ticket_cible_hash,
      statut: "scelle",
      demande_id: demandeId,
      cle_session: quote.session_key,
      affaire_id: quote.lead_id,
      outil: M3_TOOL,
    }),
  ]);
  // Core itself asked the private context server for this exact target, then sent it once.
  const issued = businessCalls(state, "context-m3", CONTEXT_TOOL).filter(
    (row) => row.generation === generation && row.issue?.cle_session === quote.session_key,
  );
  expect(issued.map((row) => row.issue)).toEqual([
    { agent_id: M3, cle_session: quote.session_key, affaire_id: quote.lead_id, outil: M3_TOOL },
  ]);
  const proposals = businessCalls(state, "m3", M3_TOOL).filter(
    (row) => row.generation === generation && row.ticket_hash === approval.ticket_cible_hash,
  );
  expect(proposals).toHaveLength(1);
  expect(proposals[0]?.frame).toStrictEqual(NO_FRAME);
  return approval;
}

function decidedQuote(state: State, label: string, quote: Quote, decidedAt: string): void {
  const target = state.quotes[label];
  expect(target.statuses).toEqual(["brouillon", "envoye"]);
  expect(target.approvals).toEqual([
    expect.objectContaining({
      statut: "executee",
      decide_par: OWNER,
      decide_role: "nathan_owner",
      decide_le: decidedAt,
    }),
  ]);
  expect(target.charges).toStrictEqual([
    {
      devis_id: quote.devis_id,
      lead_id: quote.lead_id,
      chantier_id: null,
      horodatage_envoi: decidedAt,
    },
  ]);
  expect(target.tickets).toEqual([expect.objectContaining({ statut: "consomme" })]);
}

/** Every committed fact of target A still equals the independent witness frozen before the loss. */
function expectFrozenTarget(state: State, frozen: Frozen, delivered: boolean): void {
  const target = state.quotes.A;
  expect(state.oracle?.anomalies).toEqual([]);
  expect(target.approvals).toStrictEqual([frozen.approbation]);
  expect(target.lines).toStrictEqual(frozen.lignes_devis_a);
  expect(target.outbox).toStrictEqual([frozen.outbox_a]);
  expect(target.charges).toStrictEqual([
    {
      devis_id: frozen.devis_id,
      lead_id: frozen.lead_id,
      chantier_id: null,
      horodatage_envoi: frozen.t0,
    },
  ]);
  expect(target.tickets).toStrictEqual([
    expect.objectContaining({ ticket_hash: frozen.ticket_a.ticket_hash, statut: "consomme" }),
  ]);
  if (delivered) {
    expect(target.m2_facts).toEqual([
      expect.objectContaining({
        devis_id: frozen.devis_id,
        lead_id: frozen.lead_id,
        horodatage_envoi: frozen.t0,
        client_id: frozen.client_id,
      }),
    ]);
    expect(target.received).toEqual([
      { consommateur: "m02-revenue-crm", statut: "traite", tentatives: 1 },
    ]);
  } else {
    expect(target.m2_facts).toEqual([]);
    expect(target.received).toEqual([]);
  }
  const decisions = state.journal.filter(
    (row) =>
      row.id > frozen.journal_t0_max &&
      row.cible === frozen.demande_id &&
      ["approbation.approuver", "approbation.refuser"].includes(row.action),
  );
  expect(decisions).toEqual([]);
}

afterEach(async () => {
  const manager = getSessionMcpRuntimeManagerForTesting();
  for (const sessionId of sessionIds.splice(0)) {
    await manager.disposeSession(sessionId);
  }
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

describe("OPSYS M3 N4 Core target and owner-device M9 decision through production leases and real Python HTTP", () => {
  it("keeps an M3 N4 proposal pending until its native owner decides", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m3-n4-pending-"));
    tempDirs.push(home);
    const prepared = JSON.parse(await runFixture(python, home, "prepare")) as { quote: Quote };
    const quote = prepared.quote;
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    expect(quote.devis_avant).toMatchObject({
      devis_id: quote.devis_id,
      lead_id: quote.lead_id,
      statut: "brouillon",
      estimation_source_hash: quote.source_hash,
      envoi_approuve_par: null,
    });
    const seeded = await inspect();
    expect(seeded.people).toStrictEqual(PEOPLE);
    expect(seeded.quotes.A).toMatchObject({
      statuses: ["brouillon"],
      approvals: [],
      tickets: [],
      outbox: [],
    });
    const { port } = await startServer(python, home, 1, false);

    const pending = await proposeThroughCore(home, port, "m3n4-pending-agent", quote);
    expect(pending).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    const demandeId = pending.demande_id;
    if (typeof demandeId !== "string") {
      throw new Error("real M3 N4 Core call returned no pending request id");
    }
    const proposed = await inspect();
    expectPendingProposal(proposed, "A", quote, demandeId, 1);
    // The proposal alone never reaches the human decision handler.
    expect(proposed.handler).toEqual([]);
    expect(m9Frames(proposed)).toEqual([]);

    const frame = ownerDeviceFrame("fictif-m3-n4-pending-owner", "2026-10-17T12:00:00Z");
    const decision = await decideOnDevice(home, port, "m3n4-pending-owner", frame, demandeId);
    expect(decision.isError).not.toBe(true);
    const decided = envelope(decision);
    expect(decided).toMatchObject({
      ok: true,
      rejoue: false,
      resultat: {
        accepte: true,
        resultat: {
          demande_id: demandeId,
          decision: "approuver",
          statut: "executee",
          outil: M3_TOOL,
          departement: M3,
          niveau: "N4",
          decide_par: OWNER,
          role: "nathan_owner",
        },
      },
    });
    const after = await inspect();
    decidedQuote(after, "A", quote, decidedAtOf(decided));
    expect(handlerOutcomes(after, 1)).toEqual([
      ["entered", null],
      ["completed", null],
    ]);
    expect(after.handler.map((row) => row.accepte ?? null)).toEqual([null, true]);
    expect(m9Frames(after)).toEqual([frameOnWire(frame)]);
  }, 90_000);

  it("rejects an active non-owner before an M3 N4 effect", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m3-n4-non-owner-"));
    tempDirs.push(home);
    const prepared = JSON.parse(await runFixture(python, home, "prepare")) as { quote: Quote };
    const quote = prepared.quote;
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const { port } = await startServer(python, home, 1, false);
    const pending = await proposeThroughCore(home, port, "m3n4-non-owner-agent", quote);
    const demandeId = String(pending.demande_id);
    const proposed = await inspect();
    const sealed = expectPendingProposal(proposed, "A", quote, demandeId, 1);

    // A valid, active admin who is not the owner, on their own device with their own key.
    const nonOwnerFrame = deviceFrame(
      NON_OWNER,
      NON_OWNER_DEVICE,
      "fictif-m3-n4-non-owner",
      "2026-10-17T12:01:00Z",
    );
    const refused = await decideOnDevice(home, port, "m3n4-non-owner", nonOwnerFrame, demandeId);
    expect(envelope(refused)).toMatchObject({
      resultat: { accepte: false, verdict: { code: "reserve_au_proprietaire" } },
    });
    const afterRefusal = await inspect();
    expect(afterRefusal.people).toStrictEqual(PEOPLE);
    // Before any effect: same pending request, same sealed target, no transition or publication.
    expect(expectPendingProposal(afterRefusal, "A", quote, demandeId, 1)).toStrictEqual(sealed);
    expect(afterRefusal.quotes.A).toStrictEqual(proposed.quotes.A);
    expect(afterRefusal.events_total).toBe(proposed.events_total);
    expect(audits(afterRefusal, "approbation.approuver")).toEqual([]);
    expect(handlerOutcomes(afterRefusal, 1)).toEqual([
      ["entered", null],
      ["completed", "reserve_au_proprietaire"],
    ]);
    expect(m9Frames(afterRefusal)).toEqual([frameOnWire(nonOwnerFrame)]);

    // The owner stays the legitimate decider of the very same request.
    const ownerFrame = ownerDeviceFrame("fictif-m3-n4-owner-later", "2026-10-17T12:02:00Z");
    const decision = await decideOnDevice(home, port, "m3n4-owner", ownerFrame, demandeId);
    expect(decision.isError).not.toBe(true);
    const decided = envelope(decision);
    expect(decided).toMatchObject({
      ok: true,
      rejoue: false,
      resultat: {
        accepte: true,
        resultat: { demande_id: demandeId, statut: "executee", decide_par: OWNER },
      },
    });
    decidedQuote(await inspect(), "A", quote, decidedAtOf(decided));
  }, 90_000);

  it("reopens after a committed M9 decision loses its HTTP ACK and preserves the original M3 effect across explicit replay", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-m3-n4-postcommit-"));
    tempDirs.push(home);
    const prepared = JSON.parse(await runFixture(python, home, "prepare")) as { quote: Quote };
    const quoteA = prepared.quote;
    const inspect = async (extra: string[] = []) =>
      JSON.parse(await runFixture(python, home, "inspect", extra)) as State;
    const { port: port1, child: server1 } = await startServer(python, home, 1, true);

    // 1. Real Core M3 proposal: pending only.
    const pending = await proposeThroughCore(home, port1, "m3n4-pc-agent-a", quoteA);
    expect(pending).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    const demandeA = String(pending.demande_id);
    expectPendingProposal(await inspect(), "A", quoteA, demandeA, 1);

    // 2. The owner decision commits, then only its native HTTP body is lost.
    const ownerFrame = ownerDeviceFrame("fictif-m3-n4-pc-owner-a", "2026-10-17T12:10:00Z");
    let transportError: unknown;
    try {
      await decideOnDevice(home, port1, "m3n4-pc-owner-1", ownerFrame, demandeA);
    } catch (error) {
      transportError = error;
    }
    expect(transportError).toBeInstanceOf(Error);
    // A cleanup failure after a real commit must never satisfy the lost-HTTP-body oracle.
    expect(transportError).not.toBeInstanceOf(McpLeaseCleanupError);
    const lost = JSON.parse(await readLost(home)) as Lost;
    expect(lost.t0).toBe(DECISION_T0);
    expect(lost).toMatchObject({
      fictif: true,
      generation: 1,
      demande_id: demandeA,
      devis_id: quoteA.devis_id,
      handler_events_before_loss: ["entered", "completed"],
      owner_roles: ["admin", "nathan_owner"],
      independent_committed_read_before_headers: true,
      original_headers_forwarded: true,
      response_body_forwarded_bytes: 0,
      native_result: {
        ok: true,
        rejoue: false,
        resultat: {
          accepte: true,
          resultat: {
            demande_id: demandeA,
            statut: "executee",
            decide_par: OWNER,
            role: "nathan_owner",
            decide_le: lost.t0,
          },
        },
      },
    });
    expect(lost.native_response_bytes_buffered).toBeGreaterThan(0);
    const settled = await inspect();
    const frozen = settled.oracle;
    if (!frozen) {
      throw new Error("the independent witness froze no T0 oracle before the loss");
    }
    expect(frozen).toMatchObject({ t0: lost.t0, demande_id: demandeA, devis_id: quoteA.devis_id });
    expect(frozen.arguments).toStrictEqual(quoteA.arguments);
    expect(Number.isNaN(Date.parse(frozen.t0))).toBe(false);
    expect(frozen.approbation).toMatchObject({
      statut: "executee",
      decide_par: OWNER,
      decide_role: "nathan_owner",
      decide_le: frozen.t0,
      niveau: "N4",
    });
    const creation = frozen.lignes_devis_a.filter((line) => line.statut !== "envoye");
    const transition = frozen.lignes_devis_a.filter((line) => line.statut === "envoye");
    expect(creation).toEqual([
      expect.objectContaining({
        lead_id: quoteA.lead_id,
        estimation_source_hash: quoteA.source_hash,
      }),
    ]);
    expect(transition).toEqual([
      expect.objectContaining({
        horodatage: frozen.t0,
        envoi_approuve_par: OWNER,
        envoi_approuve_role: "nathan_owner",
      }),
    ]);
    expect(frozen.outbox_a).toMatchObject({
      evenement_id: `m3-devis-envoye-${quoteA.devis_id}`,
      type_evenement: "m3.devis_envoye",
      producteur: M3,
    });
    expectFrozenTarget(settled, frozen, false);
    expect(settled.oracle?.approvals_equal_t0).toBe(true);
    expect(settled.oracle?.outbox_equal_t0).toBe(true);
    // Exactly one real handler entry and one business POST through settlement: no implicit retry.
    expect(handlerOutcomes(settled, 1)).toEqual([
      ["entered", null],
      ["completed", null],
    ]);
    expect(settled.handler.map((row) => row.accepte ?? null)).toEqual([null, true]);
    const lostCalls = businessCalls(settled, "m9", M9_TOOL);
    expect(lostCalls).toHaveLength(1);
    expect(lostCalls[0]).toMatchObject({
      rpc_id: lost.rpc_id,
      loss_selected: true,
      frame: frameOnWire(ownerFrame),
    });
    const ownerKey = ownerFrame["opsys/idempotencyKey"];
    const ownerClaim = settled.mutations.filter(
      (row) => row.appareil === OWNER_DEVICE && row.cle === ownerKey,
    );
    expect(ownerClaim.map((row) => row.outil)).toEqual([M9_TOOL]);

    // 3. Reopen: the first server is gone; a new server and fresh leases use the same SQLite.
    await stopChild(server1);
    const reopened = await inspect();
    expect({ ...reopened, dispatches: [] }).toStrictEqual({ ...settled, dispatches: [] });
    const { port: port2 } = await startServer(python, home, 2, false);
    const replay = await decideOnDevice(home, port2, "m3n4-pc-owner-2", ownerFrame, demandeA);
    expect(replay.isError).not.toBe(true);
    // Observed branch: the persisted idempotency claim returns the canonical committed response.
    expect(envelope(replay)).toStrictEqual({ ...lost.native_result, rejoue: true });
    const replayed = await inspect();
    expect(handlerOutcomes(replayed, 2)).toEqual([]);
    const m9Calls = businessCalls(replayed, "m9", M9_TOOL);
    const replayCalls = m9Calls.filter((row) => row.generation === 2);
    expect(replayCalls).toEqual([
      expect.objectContaining({ loss_selected: false, frame: frameOnWire(ownerFrame) }),
    ]);
    expectFrozenTarget(replayed, frozen, false);
    expect(replayed.oracle?.approvals_equal_t0).toBe(true);
    expect(replayed.oracle?.outbox_equal_t0).toBe(true);
    expect(replayed.mutations).toStrictEqual(settled.mutations);

    // 4. A different, active admin reusing the owner's key and device frame must be refused without
    // effect. Kept soft so the rest of the lifecycle still executes; any failure stays red here.
    const wrongActor = { ...ownerFrame, "opsys/personne": NON_OWNER };
    const impostor = await decideOnDevice(home, port2, "m3n4-pc-impostor", wrongActor, demandeA);
    const impostorEnvelope = envelope(impostor);
    const observed = `wrong actor, same device/key observed: ${JSON.stringify(impostorEnvelope)}`;
    expect.soft(impostorEnvelope, observed).not.toMatchObject({ resultat: { accepte: true } });
    expect.soft(JSON.stringify(impostorEnvelope), observed).not.toContain(frozen.t0);
    const afterImpostor = await inspect();
    expectFrozenTarget(afterImpostor, frozen, false);
    expect(afterImpostor.oracle?.approvals_equal_t0).toBe(true);
    expect(afterImpostor.oracle?.outbox_equal_t0).toBe(true);
    expect(afterImpostor.mutations).toStrictEqual(settled.mutations);
    expect(afterImpostor.people).toStrictEqual(PEOPLE);
    // The same key from the non-owner's own device is a fresh claim: the real handler refuses it.
    const ownDevice = { ...wrongActor, "opsys/appareil": NON_OWNER_DEVICE };
    const refused = await decideOnDevice(home, port2, "m3n4-pc-non-owner", ownDevice, demandeA);
    const refusedEnvelope = envelope(refused);
    expect(refusedEnvelope).toMatchObject({
      resultat: { accepte: false, verdict: { code: "reserve_au_proprietaire" } },
    });
    expect(JSON.stringify(refusedEnvelope)).not.toContain(frozen.t0);
    const afterRefusal = await inspect();
    expectFrozenTarget(afterRefusal, frozen, false);
    expect(afterRefusal.oracle?.approvals_equal_t0).toBe(true);
    expect(afterRefusal.oracle?.outbox_equal_t0).toBe(true);
    expect(handlerOutcomes(afterRefusal, 2)).toEqual([
      ...handlerOutcomes(afterImpostor, 2),
      ["entered", null],
      ["completed", "reserve_au_proprietaire"],
    ]);

    // 5. The real M2 dispatcher twice: one original contribution only.
    const dispatched = JSON.parse(await runFixture(python, home, "dispatch-m2")) as Dispatched;
    expect(dispatched.first.traites).toBeGreaterThanOrEqual(1);
    expect([dispatched.first.echecs, dispatched.first.quarantaines]).toEqual([0, 0]);
    expect(dispatched.second.livres).toBe(0);
    expect(dispatched.clients.A).toBe(frozen.client_id);
    const delivered = await inspect(["--delivered"]);
    expectFrozenTarget(delivered, frozen, true);

    // 6. Positive control: fresh quote B, fresh Core target, legitimate owner choice at T1 > T0.
    const preparedB = JSON.parse(await runFixture(python, home, "prepare-b")) as { quote: Quote };
    const quoteB = preparedB.quote;
    expect(quoteB.devis_id).not.toBe(quoteA.devis_id);
    expect(quoteB.source_hash).not.toBe(quoteA.source_hash);
    const pendingB = await proposeThroughCore(home, port2, "m3n4-pc-agent-b", quoteB);
    expect(pendingB).toMatchObject({ ok: true, statut: "en_attente_approbation" });
    const demandeB = String(pendingB.demande_id);
    expect(demandeB).not.toBe(demandeA);
    const proposedB = await inspect(["--delivered"]);
    const sealedB = expectPendingProposal(proposedB, "B", quoteB, demandeB, 2);
    expect(sealedB.ticket_cible_hash).not.toBe(frozen.approbation.ticket_cible_hash);
    expectFrozenTarget(proposedB, frozen, true);
    const frameB = ownerDeviceFrame("fictif-m3-n4-pc-owner-b", "2026-10-17T12:20:00Z");
    const decisionB = await decideOnDevice(home, port2, "m3n4-pc-owner-b", frameB, demandeB);
    expect(decisionB.isError).not.toBe(true);
    const decidedB = envelope(decisionB);
    expect(decidedB).toMatchObject({
      ok: true,
      rejoue: false,
      resultat: {
        accepte: true,
        resultat: { demande_id: demandeB, statut: "executee", decide_par: OWNER },
      },
    });
    const t1 = decidedAtOf(decidedB);
    expect(t1).toBe(DECISION_T1);
    expect(Date.parse(t1)).toBeGreaterThan(Date.parse(frozen.t0));
    const dispatchedB = JSON.parse(await runFixture(python, home, "dispatch-m2")) as Dispatched;
    expect(dispatchedB.first.traites).toBeGreaterThanOrEqual(1);
    expect([dispatchedB.first.echecs, dispatchedB.first.quarantaines]).toEqual([0, 0]);
    expect(dispatchedB.second.livres).toBe(0);
    const withB = await inspect(["--delivered"]);
    decidedQuote(withB, "B", quoteB, t1);
    expect(withB.quotes.B.m2_facts).toEqual([
      expect.objectContaining({
        devis_id: quoteB.devis_id,
        lead_id: quoteB.lead_id,
        horodatage_envoi: t1,
      }),
    ]);
    expectFrozenTarget(withB, frozen, true);
    expect(handlerOutcomes(withB, 2)).toEqual([
      ...handlerOutcomes(afterRefusal, 2),
      ["entered", null],
      ["completed", null],
    ]);

    // 7. Oracle sensitivity on disposable snapshots only; the live database is never mutated.
    const copies = JSON.parse(await runFixture(python, home, "snapshot-negatives")) as Snapshots;
    const expected: Record<string, string> = {
      date_recalculee: "A_DATE_T0",
      doublon_transition: "A_TRANSITION_ENVOYE_DOUBLE",
      doublon_fait_m2: "M2_FAIT_DOUBLE",
      doublon_outbox: "A_OUTBOX_DOUBLE",
      lead_recalcule: "A_LEAD",
      source_recalculee: "A_SOURCE",
    };
    expect(Object.keys(copies.snapshots)).toEqual(["intact", ...Object.keys(expected)]);
    const intact = await inspect(["--database", copies.snapshots.intact, "--delivered"]);
    expectFrozenTarget(intact, frozen, true);
    for (const [name, anomaly] of Object.entries(expected)) {
      const altered = await inspect(["--database", copies.snapshots[name], "--delivered"]);
      expect(altered.oracle?.anomalies).toContain(anomaly);
      expect(() => expectFrozenTarget(altered, frozen, true)).toThrow();
    }
    expectFrozenTarget(await inspect(["--delivered"]), frozen, true);
  }, 170_000);
});
