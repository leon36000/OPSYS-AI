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
const FIXTURE = resolve(REPO, "core/test/opsys-m6-po-authority-fixture.py");
const M6 = "m06-material-control";
const M9 = "m09-strategic-intelligence";
const CREATE = "m6_creer_po_brouillon";
const APPROVE = "m6_approuver_po";
const EMAIL = "m6_generer_courriel_po";
const SEND = "m6_marquer_po_envoye";
const DECIDE = "m9_decider_demande_approbation";
const OWNER = "nathan";
const NON_OWNER = "marie-po-fictive";
const MANAGER = "manager-po-fictif";
const GUTTER = "gouttiere-cf027-fictive";
const SCREW = "vis-cf027-fictive";
const DEVICE = "tel-cf027-proprietaire-fictif";
const T0 = "2026-10-17T12:10:00+00:00";
const PRIVATE_TOKEN = "synthetic-m6-po-private-token-2026";
const PUBLIC_TOKEN = "synthetic-m6-po-public-token-2026";
const MAX_FIXTURE_OUTPUT = 8 * 1024 * 1024;
const children: ChildProcess[] = [];
const closedChildren = new WeakSet<ChildProcess>();
const tempDirs: string[] = [];
const sessionIds: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;
let callNumber = 0;

type Row = Record<string, unknown>;
type Prepared = {
  fictif: boolean;
  M3_references_fixture_only: boolean;
  setup_requests: string[];
  needs: { chantier_id: string; devis_id: string; lignes: Row[] };
  supplier: string;
  unpriced_supplier: string;
};
type Approval = {
  id: string;
  outil: string;
  niveau: string;
  departement: string;
  statut: string;
  arguments: string;
  resultat: string | null;
  decide_par: string | null;
  decide_role: string | null;
  decide_le: string | null;
  ticket_cible_hash: string | null;
};
type SqlPo = {
  departement: string;
  registre: string;
  rang: number;
  maillon: string;
  cree_le: string;
};
type Claim = {
  appareil: string;
  cle_idempotence: string;
  outil: string;
  statut: string;
  reponse: string;
  empreinte_arguments: string;
};
type Journal = { id: number; par: string; action: string; cible: string; details: string };
type HandlerEvent = { generation: number; tool: string; event: string; arguments_sha256: string };
type Dispatch = {
  generation: number;
  route: string;
  method?: string;
  tool?: string;
  arguments_sha256?: string;
  ticket_present?: boolean;
  frame?: Row;
};
type State = {
  protected: Record<string, string>;
  po_rows: SqlPo[];
  po_pieces: Row[];
  approvals: Approval[];
  claims: Claim[];
  journal: Journal[];
  people: Record<string, string[]>;
  sources: Record<string, Row[]>;
  tables: Record<string, string>;
  handler: HandlerEvent[];
  dispatches: Dispatch[];
  oracle: Row | null;
  origins: Record<string, Record<string, { path: string; sha256: string }>>;
};
type Lost = {
  generation: number;
  demande_id: string;
  native_result: Row;
  t0: string;
  independent_committed_read_before_headers: boolean;
  response_body_forwarded_bytes: number;
  native_response_bytes_buffered: number;
  original_headers_forwarded: boolean;
  handler_sequence: string[][];
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
    throw new Error(
      "OPSYS_TEST_PYTHON is required for the Python HTTP M6 PO authority integration test",
    );
  }
  return python;
}

function childExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function waitChildClosed(child: ChildProcess, milliseconds: number): Promise<boolean> {
  if (closedChildren.has(child)) {
    return true;
  }
  return await new Promise<boolean>((resolveClosed) => {
    const onClose = () => {
      clearTimeout(timeout);
      resolveClosed(true);
    };
    const timeout = setTimeout(() => {
      child.off("close", onClose);
      resolveClosed(false);
    }, milliseconds);
    child.once("close", onClose);
  });
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (closedChildren.has(child)) {
    return;
  }
  if (!childExited(child)) {
    child.kill("SIGTERM");
  }
  if (await waitChildClosed(child, 2_000)) {
    return;
  }
  if (!childExited(child)) {
    child.kill("SIGKILL");
  }
  if (!(await waitChildClosed(child, 2_000))) {
    throw new Error("Owned Python process did not close its stdout/stderr after bounded cleanup");
  }
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
  child.once("close", () => closedChildren.add(child));
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
    const timeout = setTimeout(
      () => {
        child.kill("SIGKILL");
        reject(new Error(`Python fixture ${command} exceeded its bounded command deadline`));
      },
      command === "prepare" ? 60_000 : 20_000,
    );
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("close", (exitCode) => {
      clearTimeout(timeout);
      resolveExit(exitCode ?? 1);
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
  child.once("close", () => closedChildren.add(child));
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

function config(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_m6: httpServer(port, `/mcp/${M6}`, PUBLIC_TOKEN),
        opsys_m9: httpServer(port, `/mcp/${M9}`, PUBLIC_TOKEN),
      },
    },
  };
}

/** Host-owned frame fixture. The Native/Gateway identity producer is outside this proof. */
function frame(person: string, key: string, role = "admin"): Record<string, string> {
  return {
    "opsys/personne": person,
    "opsys/role": role,
    "opsys/appareil": DEVICE,
    "opsys/idempotencyKey": key,
    "opsys/horodatageAppareil": "2026-10-17T12:00:00+00:00",
  };
}

function envelope(result: CallToolResult, expectedError = false): Row {
  const texts = result.content.filter((item) => item.type === "text");
  if (texts.length !== 1 || texts[0].type !== "text") {
    throw new Error("native PO MCP response requires exactly one text result");
  }
  const native = JSON.parse(texts[0].text) as Row;
  if (expectedError) {
    expect(result.isError, JSON.stringify(native)).toBe(true);
  } else {
    expect(result.isError, JSON.stringify(native)).not.toBe(true);
  }
  return native;
}

async function call(
  home: string,
  port: number,
  tool: string,
  args: Row,
  meta?: Record<string, string>,
  expectedError = false,
): Promise<Row> {
  callNumber += 1;
  const server = tool === DECIDE ? "opsys_m9" : "opsys_m6";
  return await withProductionLease(
    {
      sessionId: `cf027-po-call-${callNumber}`,
      sessionKey: meta
        ? "agent:main:cf027-owner-device-fictif"
        : "agent:m06-material-control:cf027-po-fictif",
      workspaceDir: home,
      cfg: config(port),
    },
    async (runtime, activeLeases) => {
      const held = activeLeases();
      expect(held).toBeGreaterThan(0);
      const invoke = () => runtime.callTool(server, tool, args);
      const result = meta ? await withMcpCallMeta(meta, invoke) : await invoke();
      expect(activeLeases()).toBe(held);
      return envelope(result, expectedError);
    },
  );
}

function decisionArgs(id: string): Row {
  return { demande_id: id, decision: "approuver", motif: "" };
}

function pendingId(native: Row): string {
  expect(native).toMatchObject({ ok: true, statut: "en_attente_approbation" });
  expect(native).not.toHaveProperty("resultat");
  if (typeof native.demande_id !== "string" || !native.demande_id) {
    throw new Error("real PO capability returned no pending request identifier");
  }
  return native.demande_id;
}

function approval(state: State, id: string): Approval {
  const found = state.approvals.filter((row) => row.id === id);
  expect(found).toHaveLength(1);
  return found[0];
}

function pieces(state: State, poId: string): Row[] {
  return state.po_pieces.filter((piece) => piece.po_id === poId);
}

function originalEntries(state: State, tool: string): HandlerEvent[] {
  return state.handler.filter((event) => event.tool === tool && event.event === "entered");
}

function rpcCalls(state: State, tool: string): Dispatch[] {
  return state.dispatches.filter((event) => event.method === "tools/call" && event.tool === tool);
}

function expectPeople(state: State): void {
  expect(state.people).toStrictEqual({
    [OWNER]: ["admin", "nathan_owner"],
    [NON_OWNER]: ["admin"],
    [MANAGER]: ["manager"],
  });
}

function expectProtected(state: State, baseline: State): void {
  expect(state.protected).toStrictEqual(baseline.protected);
  expect(state.sources).toStrictEqual(baseline.sources);
  expectPeople(state);
}

function expectOrigins(state: State, generation: number): void {
  const origins = state.origins[String(generation)];
  expect(Object.keys(origins).toSorted()).toEqual([
    "m6_material_control.outils",
    "m9_strategic_intelligence.outils",
    "opsys.capacites",
  ]);
  expect(origins["opsys.capacites"].path).toBe(resolve(REPO, "src/opsys/capacites.py"));
  expect(origins["m6_material_control.outils"].path).toBe(
    resolve(REPO, `departments/${M6}/src/m6_material_control/outils.py`),
  );
  expect(origins["m9_strategic_intelligence.outils"].path).toBe(
    resolve(REPO, `departments/${M9}/src/m9_strategic_intelligence/outils.py`),
  );
  for (const row of Object.values(origins)) {
    expect(row.sha256).toMatch(/^[a-f0-9]{64}$/);
  }
}

function expectPrepared(data: Prepared, seeded: State): void {
  expect(data).toMatchObject({ fictif: true, M3_references_fixture_only: true });
  expect(data.setup_requests).toHaveLength(5);
  expect(seeded.approvals.map((row) => row.id).toSorted()).toStrictEqual(
    data.setup_requests.toSorted(),
  );
  for (const row of seeded.approvals) {
    expect(row).toMatchObject({ statut: "executee", decide_par: OWNER, ticket_cible_hash: null });
  }
  expectPeople(seeded);
  expect(seeded.po_rows).toEqual([]);
  expect(seeded.sources.principal).toEqual([]);
  expect(seeded.sources.besoins_prevus).toStrictEqual([
    {
      chantier_id: "CHANTIER-CF027-FICTIF",
      devis_id: "DEVIS-M3-CF027-FICTIF",
      lignes: [
        { materiau_id: GUTTER, quantite_estimee: 10, unite: "pi" },
        { materiau_id: SCREW, quantite_estimee: 4, unite: "boite" },
      ],
    },
  ]);
  expect(seeded.sources.livre_prix).toStrictEqual([
    {
      materiau_id: GUTTER,
      fournisseur_id: data.supplier,
      prix_unitaire: 12.5,
      devise: "CAD",
      date_effet: "2026-10-01",
      source_document: "FACT-PRIX-CF027-FICTIVE",
    },
    {
      materiau_id: SCREW,
      fournisseur_id: data.supplier,
      prix_unitaire: 0.5,
      devise: "CAD",
      date_effet: "2026-10-01",
      source_document: null,
    },
  ]);
  expect(seeded.sources.fournisseurs.map((supplier) => supplier.fournisseur_id)).toEqual([
    data.supplier,
    data.unpriced_supplier,
  ]);
}

function createArgs(data: Prepared, poId: string, supplier = data.supplier): Row {
  return {
    po_id: poId,
    devis_id: data.needs.devis_id,
    fournisseur_id: supplier,
    horodatage: "2026-10-17T11:00:00+00:00",
  };
}

function expectDecision(
  native: Row,
  id: string,
  tool: string,
  status = "executee",
  issue: Row = {
    ok: true,
    accepte: true,
  },
): void {
  expect(native).toMatchObject({
    ok: true,
    rejoue: false,
    resultat: {
      accepte: true,
      resultat: {
        demande_id: id,
        decision: "approuver",
        statut: status,
        outil: tool,
        departement: M6,
        decide_par: OWNER,
        role: "nathan_owner",
        decide_le: T0,
        issue,
      },
    },
  });
}

async function performM6(
  home: string,
  port: number,
  key: string,
  tool: string,
  args: Row,
  inspect: () => Promise<State>,
): Promise<{ id: string; native: Row }> {
  const before = await inspect();
  const id = pendingId(await call(home, port, tool, args));
  const pending = await inspect();
  expect(pending.po_rows).toStrictEqual(before.po_rows);
  expect(originalEntries(pending, tool)).toHaveLength(originalEntries(before, tool).length);
  expect(approval(pending, id)).toMatchObject({
    outil: tool,
    niveau: "N3",
    statut: "en_attente",
    ticket_cible_hash: null,
  });
  expect(JSON.parse(approval(pending, id).arguments)).toStrictEqual(args);
  const native = await call(home, port, DECIDE, decisionArgs(id), frame(OWNER, key));
  return { id, native };
}

function expectPricedCreation(state: State, data: Prepared, poId: string): void {
  const [created] = pieces(state, poId);
  expect(created).toStrictEqual({
    type_entree: "po_cree",
    po_id: poId,
    chantier_id: data.needs.chantier_id,
    fournisseur_id: data.supplier,
    statut: "draft",
    horodatage: "2026-10-17T11:00:00+00:00",
    lignes: [
      {
        materiau_id: GUTTER,
        quantite_demandee: 10,
        verdict_prix: "PRIX_LIVRE",
        prix_unitaire_prevu: 12.5,
        devise_prevue: "CAD",
        montant_ligne_prevu: 125,
      },
      {
        materiau_id: SCREW,
        quantite_demandee: 4,
        verdict_prix: "PRIX_LIVRE",
        prix_unitaire_prevu: 0.5,
        devise_prevue: "CAD",
        montant_ligne_prevu: 2,
      },
    ],
    montant_total_prevu: 127,
    // A declared document reference is provenance, never proof of invoice authenticity.
    provenance_prix_lignes: [
      {
        materiau_id: GUTTER,
        capture: "CAPTURE",
        date_effet: "2026-10-01",
        source_document: "FACT-PRIX-CF027-FICTIVE",
        marquage_source: "SOURCE_DECLAREE",
      },
      {
        materiau_id: SCREW,
        capture: "CAPTURE",
        date_effet: "2026-10-01",
        source_document: null,
        marquage_source: "FALLBACK_PRICE_BOOK",
      },
    ],
  });
}

async function emailReady(
  home: string,
  port: number,
  data: Prepared,
  inspect: () => Promise<State>,
  poId: string,
): Promise<State> {
  const created = await performM6(
    home,
    port,
    `${poId}-create`,
    CREATE,
    createArgs(data, poId),
    inspect,
  );
  expectDecision(created.native, created.id, CREATE);
  const draft = await inspect();
  expect(pieces(draft, poId)).toHaveLength(1);
  expectPricedCreation(draft, data, poId);
  const approved = await performM6(
    home,
    port,
    `${poId}-approve`,
    APPROVE,
    {
      po_id: poId,
      horodatage: "2026-10-17T11:01:00+00:00",
    },
    inspect,
  );
  expectDecision(approved.native, approved.id, APPROVE);
  const afterApproval = await inspect();
  expect(pieces(afterApproval, poId)).toHaveLength(2);
  expect(pieces(afterApproval, poId)[1]).toStrictEqual({
    type_entree: "transition_po",
    po_id: poId,
    statut: "approved",
    horodatage: "2026-10-17T11:01:00+00:00",
  });
  const email = await performM6(
    home,
    port,
    `${poId}-email`,
    EMAIL,
    {
      po_id: poId,
      horodatage: "2026-10-17T11:02:00+00:00",
      nom_entreprise: "Entreprise CF027 fictive",
    },
    inspect,
  );
  expectDecision(email.native, email.id, EMAIL);
  const ready = await inspect();
  expect(pieces(ready, poId)).toHaveLength(3);
  expect(pieces(ready, poId)[2]).toMatchObject({
    type_entree: "transition_po",
    po_id: poId,
    statut: "email_ready",
    courriel: {
      destinataire: "commandes@fournisseur.exemple-fictif.test",
      repli_manuel_requis: false,
    },
  });
  expectPricedCreation(ready, data, poId);
  return ready;
}

function expectFreshRefusal(
  before: State,
  after: State,
  native: Row,
  key: string,
  id: string,
  code: string,
  audit: boolean,
): void {
  expect(native).toMatchObject({
    ok: true,
    rejoue: false,
    resultat: { accepte: false, verdict: { code } },
  });
  expect(after.po_rows).toStrictEqual(before.po_rows);
  expect(after.approvals).toStrictEqual(before.approvals);
  expectProtected(after, before);
  for (const [table, hash] of Object.entries(before.tables)) {
    if (table !== "journal" && table !== "mutations_appliquees") {
      expect(after.tables[table], table).toBe(hash);
    }
  }
  expect(after.claims.filter((claim) => claim.cle_idempotence !== key)).toStrictEqual(
    before.claims,
  );
  const newClaims = after.claims.filter((claim) => claim.cle_idempotence === key);
  expect(newClaims).toHaveLength(1);
  expect(newClaims[0]).toMatchObject({ appareil: DEVICE, outil: DECIDE, statut: "ok" });
  expect({ ...JSON.parse(newClaims[0].reponse), rejoue: false }).toStrictEqual(native);
  expect(after.journal.slice(0, before.journal.length)).toStrictEqual(before.journal);
  const newJournal = after.journal.slice(before.journal.length);
  expect(newJournal).toHaveLength(audit ? 1 : 0);
  if (audit) {
    expect(newJournal[0]).toMatchObject({
      par: NON_OWNER,
      action: "approbation.refus_appareil",
      cible: id,
    });
    expect(JSON.parse(newJournal[0].details)).toStrictEqual({
      code,
      decision: "approuver",
      appareil: DEVICE,
      role_appareil: "admin",
    });
  }
}

async function readLost(home: string): Promise<Lost> {
  try {
    return JSON.parse(await readFile(resolve(home, "m6-po-m9-response-lost.json"), "utf8")) as Lost;
  } catch (error) {
    const refused = await readFile(resolve(home, "m6-po-loss-gate-refused.json"), "utf8").catch(
      () => "no gate report",
    );
    throw new Error(`no independently committed PO decision ACK was lost: ${refused}`, {
      cause: error,
    });
  }
}

describe("CF027 persisted M6 PO authority through production Core leases and real Python HTTP", () => {
  it("sources PO prices from the durable book and refuses unknown supplier or unresolved-price approval", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-core-m6-po-prices-"));
    tempDirs.push(home);
    const data = JSON.parse(await runFixture(python, home, "prepare")) as Prepared;
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const seeded = await inspect();
    expectPrepared(data, seeded);
    const { port } = await startServer(python, home, 1, false);

    const unknown = await performM6(
      home,
      port,
      "unknown-supplier",
      CREATE,
      createArgs(data, "PO-CF027-UNKNOWN-FICTIF", "fournisseur-inconnu-fictif"),
      inspect,
    );
    expectDecision(unknown.native, unknown.id, CREATE, "echec", {
      ok: true,
      accepte: false,
      verdict: { code: "REJ-PO-FOURNISSEUR-INCONNU" },
    });
    const afterUnknown = await inspect();
    expect(afterUnknown.po_rows).toStrictEqual(seeded.po_rows);
    expectProtected(afterUnknown, seeded);

    const unpricedId = "PO-CF027-SANS-PRIX-FICTIF";
    const unpriced = await performM6(
      home,
      port,
      "unpriced-create",
      CREATE,
      createArgs(data, unpricedId, data.unpriced_supplier),
      inspect,
    );
    expectDecision(unpriced.native, unpriced.id, CREATE);
    const unknownPrices = await inspect();
    expect(pieces(unknownPrices, unpricedId)).toHaveLength(1);
    expect(pieces(unknownPrices, unpricedId)[0]).toMatchObject({
      statut: "draft",
      fournisseur_id: data.unpriced_supplier,
      montant_total_prevu: null,
      lignes: [
        {
          materiau_id: GUTTER,
          quantite_demandee: 10,
          verdict_prix: "INDETERMINE",
          prix_unitaire_prevu: null,
          devise_prevue: null,
          montant_ligne_prevu: null,
        },
        {
          materiau_id: SCREW,
          quantite_demandee: 4,
          verdict_prix: "INDETERMINE",
          prix_unitaire_prevu: null,
          devise_prevue: null,
          montant_ligne_prevu: null,
        },
      ],
    });
    const refused = await performM6(
      home,
      port,
      "unpriced-approve",
      APPROVE,
      {
        po_id: unpricedId,
        horodatage: "2026-10-17T11:01:00+00:00",
      },
      inspect,
    );
    expectDecision(refused.native, refused.id, APPROVE, "echec", {
      ok: true,
      accepte: false,
      verdict: { code: "REJ-PO-PRIX-INDETERMINE" },
    });
    const afterRefusal = await inspect();
    expect(afterRefusal.po_rows).toStrictEqual(unknownPrices.po_rows);
    expect(approval(afterRefusal, refused.id)).toMatchObject({ statut: "echec", niveau: "N3" });

    const ready = await emailReady(home, port, data, inspect, "PO-CF027-PRICE-FICTIF");
    expectProtected(ready, seeded);
    expect(originalEntries(ready, CREATE)).toHaveLength(3);
    expect(originalEntries(ready, APPROVE)).toHaveLength(2);
    expect(originalEntries(ready, EMAIL)).toHaveLength(1);
    expect(originalEntries(ready, SEND)).toEqual([]);
    expect(ready.approvals.every((row) => row.ticket_cible_hash === null)).toBe(true);
    for (const tool of [CREATE, APPROVE, EMAIL]) {
      for (const rpc of rpcCalls(ready, tool)) {
        expect(rpc.ticket_present).toBe(false);
        expect(rpc.frame).toStrictEqual({
          personne: null,
          role: null,
          appareil: null,
          idempotencyKey: null,
          horodatageAppareil: null,
        });
      }
    }
    expectOrigins(ready, 1);
  }, 170_000);

  it("keeps PO N4 pending for its valid DEVICE owner and replays one committed decision after ACK loss", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-core-m6-po-authority-"));
    tempDirs.push(home);
    const data = JSON.parse(await runFixture(python, home, "prepare")) as Prepared;
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const seeded = await inspect();
    expectPrepared(data, seeded);
    const first = await startServer(python, home, 1, true);
    const poId = "PO-CF027-N4-FICTIF";
    const ready = await emailReady(home, first.port, data, inspect, poId);
    const sendArgs = { po_id: poId, horodatage: "2026-10-17T11:03:00+00:00" };
    const pending = pendingId(await call(home, first.port, SEND, sendArgs));
    const proposed = await inspect();
    expect(proposed.po_rows).toStrictEqual(ready.po_rows);
    expectProtected(proposed, seeded);
    expect(originalEntries(proposed, SEND)).toEqual([]);
    const demands = proposed.approvals.filter((row) => row.outil === SEND);
    expect(demands).toHaveLength(1);
    expect(approval(proposed, pending)).toMatchObject({
      statut: "en_attente",
      niveau: "N4",
      departement: M6,
      outil: SEND,
      ticket_cible_hash: null,
      decide_par: null,
      decide_role: null,
    });
    expect(JSON.parse(approval(proposed, pending).arguments)).toStrictEqual(sendArgs);
    expect(rpcCalls(proposed, SEND)).toHaveLength(1);
    expect(rpcCalls(proposed, SEND)[0]).toMatchObject({
      ticket_present: false,
      frame: {
        personne: null,
        role: null,
        appareil: null,
        idempotencyKey: null,
        horodatageAppareil: null,
      },
    });

    // This matching manager frame reaches the DEVICE role guard. It is not a forged admin frame,
    // nor evidence that the socle's separate manager N3/N4 policy ran here.
    const managerKey = "cf027-manager-fresh-fictif";
    const managerRefused = await call(
      home,
      first.port,
      DECIDE,
      decisionArgs(pending),
      frame(MANAGER, managerKey, "manager"),
    );
    const afterManager = await inspect();
    expectFreshRefusal(
      proposed,
      afterManager,
      managerRefused,
      managerKey,
      pending,
      "role_appareil_insuffisant",
      false,
    );

    const adminKey = "cf027-admin-fresh-fictif";
    const freshRefused = await call(
      home,
      first.port,
      DECIDE,
      decisionArgs(pending),
      frame(NON_OWNER, adminKey),
    );
    const afterAdmin = await inspect();
    expectFreshRefusal(
      afterManager,
      afterAdmin,
      freshRefused,
      adminKey,
      pending,
      "reserve_au_proprietaire",
      true,
    );
    expect(originalEntries(afterAdmin, SEND)).toEqual([]);
    expectPeople(afterAdmin); // Nathan remains active with BOTH roles throughout these negatives.

    await runFixture(python, home, "baseline");
    const originalFrame = frame(OWNER, "cf027-owner-commit-fictif");
    const originalArgs = decisionArgs(pending);
    const intention = JSON.stringify({ originalFrame, originalArgs });
    let transportFailure: unknown;
    try {
      await call(home, first.port, DECIDE, originalArgs, originalFrame);
    } catch (error) {
      transportFailure = error;
    }
    expect(transportFailure).toBeInstanceOf(Error);
    expect(transportFailure).not.toBeInstanceOf(McpLeaseCleanupError);
    const lost = await readLost(home);
    expect(lost).toMatchObject({
      generation: 1,
      demande_id: pending,
      t0: T0,
      independent_committed_read_before_headers: true,
      response_body_forwarded_bytes: 0,
      original_headers_forwarded: true,
      handler_sequence: [
        [DECIDE, "entered"],
        [SEND, "entered"],
        [SEND, "completed"],
        [DECIDE, "completed"],
      ],
    });
    expect(lost.native_response_bytes_buffered).toBeGreaterThan(0);
    expectDecision(lost.native_result, pending, SEND);
    const committed = await inspect();
    expectProtected(committed, seeded);
    expect(committed.po_rows.slice(0, -1)).toStrictEqual(ready.po_rows);
    expect(pieces(committed, poId)).toHaveLength(4);
    expect(pieces(committed, poId)[3]).toStrictEqual({
      type_entree: "transition_po",
      po_id: poId,
      statut: "sent_to_supplier",
      horodatage: sendArgs.horodatage,
    });
    expectPricedCreation(committed, data, poId);
    expect(approval(committed, pending)).toMatchObject({
      statut: "executee",
      decide_par: OWNER,
      decide_role: "nathan_owner",
      decide_le: T0,
      ticket_cible_hash: null,
    });
    expect(committed.claims).toHaveLength(afterAdmin.claims.length + 1);
    expect(originalEntries(committed, SEND)).toHaveLength(1);
    const decisionEntries = originalEntries(committed, DECIDE).length;
    const decisionCalls = rpcCalls(committed, DECIDE).length;
    await stopChild(first.child);
    await resetSessionMcpRuntimeManagerGeneration();

    const second = await startServer(python, home, 2, false);
    const replay = await call(home, second.port, DECIDE, originalArgs, originalFrame);
    expect(replay).toStrictEqual({ ...lost.native_result, rejoue: true });
    const afterReplay = await inspect();
    expect(afterReplay.tables).toStrictEqual(committed.tables);
    expect(afterReplay.po_rows).toStrictEqual(committed.po_rows);
    expect(afterReplay.approvals).toStrictEqual(committed.approvals);
    expect(afterReplay.claims).toStrictEqual(committed.claims);
    expect(originalEntries(afterReplay, SEND)).toHaveLength(1);
    expect(originalEntries(afterReplay, DECIDE)).toHaveLength(decisionEntries);
    expect(rpcCalls(afterReplay, DECIDE)).toHaveLength(decisionCalls + 1);
    expectOrigins(afterReplay, 1);
    expectOrigins(afterReplay, 2);

    // Keep the exact committed device/key/arguments, but supply a different active admin fixture.
    // The cache must refuse current authority without exposing its original owner's summary.
    const cacheRefused = await call(
      home,
      second.port,
      DECIDE,
      originalArgs,
      { ...originalFrame, "opsys/personne": NON_OWNER },
      true,
    );
    expect(cacheRefused).toMatchObject({
      ok: false,
      erreur: "confirmation_transport_indisponible",
      issue: "inconnue",
    });
    expect(cacheRefused).not.toHaveProperty("resultat");
    expect(cacheRefused.rejoue).not.toBe(true);
    expect(JSON.stringify(cacheRefused)).not.toContain(pending);
    const final = await inspect();
    expect(final.tables).toStrictEqual(committed.tables);
    expect(final.po_rows).toStrictEqual(committed.po_rows);
    expect(final.claims).toStrictEqual(committed.claims);
    expectProtected(final, seeded);
    expect(originalEntries(final, SEND)).toHaveLength(1);
    expect(originalEntries(final, DECIDE)).toHaveLength(decisionEntries);
    expect(rpcCalls(final, DECIDE)).toHaveLength(decisionCalls + 2);
    expect(JSON.stringify({ originalFrame, originalArgs })).toBe(intention);
  }, 170_000);
});
