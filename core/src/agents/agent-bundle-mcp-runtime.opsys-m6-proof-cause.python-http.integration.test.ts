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
const FIXTURE = resolve(REPO, "core/test/opsys-m6-proof-cause-fixture.py");
const M6 = "m06-material-control";
const DECLARE = "m6_declarer_materiaux_avec_preuves_appareil";
const LIST = "m6_lister_variances_classables_wct_appareil";
const CLASSIFY = "m6_classer_cause_variance_appareil";
const PRIVATE_TOKEN = "synthetic-m6-proof-private-token-2026";
const PUBLIC_TOKEN = "synthetic-m6-proof-public-token-2026";
const MAX_FIXTURE_OUTPUT = 8 * 1024 * 1024;
const children: ChildProcess[] = [];
const closedChildren = new WeakSet<ChildProcess>();
const tempDirs: string[] = [];
const sessionIds: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;
type Row = Record<string, unknown>;
type Prepared = {
  fictif: boolean;
  setup_pid: number;
  setup_bus_pid: number;
  setup_HTTP_thread_stopped: boolean;
  setup_HTTP_threads_closed: number;
  wct_id: string;
  intervention_id: string;
  chantier_id: string;
  material_id: string;
  employee: string;
  admin: string;
  employee_device: string;
  admin_device: string;
  owner_device: string;
  device_time: string;
  photo_reference: string;
  photo_sha256: string;
  photo_bytes: number;
  declaration: Row;
  M4_initial_status: string;
  helper_pins: Record<string, string>;
};
type HandlerEvent = { generation: number; tool: string; event: string; arguments_sha256: string };
type Dispatch = { generation: number; route: string; method?: string; tool?: string; frame?: Row };
type State = {
  cas: { sha256: string; bytes: number; blocks: number };
  stock: string;
  movements: Row[];
  proofs: Row[];
  classifications: Row[];
  refusals: Row[];
  protected: Row;
  tables: Record<string, string>;
  claims: Row[];
  people: Record<string, string[]>;
  handler: HandlerEvent[];
  dispatches: Dispatch[];
  oracle: Row | null;
  origins: Record<string, Record<string, { path: string; sha256: string }>>;
};
type Lost = {
  generation: number;
  native_result: Row;
  independent_committed_read_before_headers: boolean;
  response_body_forwarded_bytes: number;
  original_headers_forwarded: boolean;
  native_response_bytes_buffered: number;
  handler_events_before_loss: string[];
  classification_reference: Row;
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
      "OPSYS_TEST_PYTHON is required for the Python HTTP M6 proof/cause integration test",
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
  loseClassification: boolean,
): Promise<{ port: number; child: ChildProcess }> {
  const port = await reservePort();
  const child = await startPythonMcp(python, home, [
    FIXTURE,
    "serve",
    "--port",
    String(port),
    "--generation",
    String(generation),
    ...(loseClassification ? ["--lose-classification"] : []),
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

/** Explicit fixture of the host-owned device frame; no Native/Gateway producer is proved. */
function frame(data: Prepared, person: "admin" | "employee", key?: string): Record<string, string> {
  const admin = person === "admin";
  return {
    "opsys/personne": admin ? data.admin : data.employee,
    "opsys/role": admin ? "admin" : "employee",
    ...(key
      ? {
          "opsys/idempotencyKey": key,
          "opsys/appareil": admin ? data.admin_device : data.employee_device,
          "opsys/horodatageAppareil": data.device_time,
        }
      : {}),
  };
}

function config(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_m6: httpServer(port, `/mcp/${M6}`, PUBLIC_TOKEN),
      },
    },
  };
}

function envelope(result: CallToolResult, expectedError = false): Row {
  const texts = result.content.filter((item) => item.type === "text");
  if (texts.length !== 1 || texts[0].type !== "text") {
    throw new Error(
      `M6 fictive result requires one native text: ${JSON.stringify(result.content).slice(0, 2000)}`,
    );
  }
  const native = JSON.parse(texts[0].text) as Row;
  if (expectedError) {
    expect(result.isError, JSON.stringify(native)).toBe(true);
  } else {
    expect(result.isError, JSON.stringify(native)).not.toBe(true);
  }
  return native;
}

function value(native: Row): Row {
  expect(native).toMatchObject({ ok: true, resultat: { accepte: true } });
  return (native.resultat as { resultat: Row }).resultat;
}

async function call(
  home: string,
  port: number,
  sessionId: string,
  meta: Record<string, string>,
  tool: string,
  args: Row,
  expectedError = false,
): Promise<Row> {
  return await withProductionLease(
    {
      sessionId,
      sessionKey: "agent:main:opsys-m6-proof-device-fictif",
      workspaceDir: home,
      cfg: config(port),
    },
    async (runtime, activeLeases) => {
      const held = activeLeases();
      expect(held).toBeGreaterThan(0);
      const result = await withMcpCallMeta(meta, () => runtime.callTool("opsys_m6", tool, args));
      expect(activeLeases()).toBe(held);
      return envelope(result, expectedError);
    },
  );
}

function entries(state: State, tool: string): HandlerEvent[] {
  return state.handler.filter((r) => r.tool === tool && r.event === "entered");
}
function calls(state: State, tool: string): Dispatch[] {
  return state.dispatches.filter((r) => r.method === "tools/call" && r.tool === tool);
}
function expectOrigins(state: State, generation: number): void {
  const origins = state.origins[String(generation)];
  expect(Object.keys(origins).toSorted()).toEqual([
    "m6_material_control.outils",
    "opsys.capacites",
  ]);
  expect(origins["opsys.capacites"].path).toBe(resolve(REPO, "src/opsys/capacites.py"));
  expect(origins["m6_material_control.outils"].path).toBe(
    resolve(REPO, "departments/m06-material-control/src/m6_material_control/outils.py"),
  );
  for (const row of Object.values(origins)) {
    expect(row.sha256).toMatch(/^[a-f0-9]{64}$/);
  }
}
function expectPrepared(data: Prepared): void {
  expect(data).toMatchObject({
    fictif: true,
    setup_HTTP_thread_stopped: true,
    M4_initial_status: "completed_pending_review",
  });
  expect(data.setup_bus_pid).not.toBe(data.setup_pid);
  expect(data.setup_HTTP_threads_closed).toBeGreaterThan(0);
  expect(Object.keys(data.helper_pins).toSorted()).toEqual([
    resolve(REPO, "tests/e2e/test_verticale_affaire_durable.py"),
    resolve(REPO, "tests/fixtures/harnais_e2e.py"),
    resolve(REPO, "tests/fixtures/harnais_e2e_chantier.py"),
  ]);
}
function expectDeclaration(state: State, data: Prepared, native: Row, seeded: State): void {
  expect(native).toMatchObject({ ok: true, rejoue: false });
  const ack = value(native);
  expect(state.cas).toStrictEqual({
    sha256: data.photo_sha256,
    bytes: data.photo_bytes,
    blocks: 1,
  });
  expect(ack.wct_id).toBe(data.wct_id);
  expect(Number(state.stock)).toBe(Number(seeded.stock) - 56);
  expect(state.movements).toHaveLength(2);
  expect(state.movements.map((m) => [m.type_mouvement, Number(m.quantite)])).toEqual([
    ["CONSOMMATION", -55],
    ["PERTE", -1],
  ]);
  for (const movement of state.movements) {
    expect(movement).toMatchObject({
      wct_id: data.wct_id,
      chantier_id: data.chantier_id,
      materiau_id: data.material_id,
    });
  }
  expect(state.proofs).toHaveLength(1);
  const proof = state.proofs[0];
  const loss = state.movements[1];
  const movementReference = {
    registre: "principal",
    index: loss.index,
    hash_maillon: loss.hash_maillon,
  };
  expect(proof).toMatchObject({
    wct_id: data.wct_id,
    intervention_id: data.intervention_id,
    chantier_id: data.chantier_id,
    position_ligne: 1,
    reference_mouvement: movementReference,
    auteur: { personne: data.employee, role: "employee" },
    appareil: data.employee_device,
    photos: [
      {
        reference: data.photo_reference,
        empreinte_sha256: data.photo_sha256,
        type_mime: "image/png",
        taille_octets: data.photo_bytes,
      },
    ],
  });
  expect(ack.preuves).toEqual([
    expect.objectContaining({
      position_ligne: 1,
      reference_mouvement: movementReference,
      reference_preuve: {
        registre: "preuves_pertes_bris",
        index: proof.index,
        hash_maillon: proof.hash_maillon,
      },
    }),
  ]);
  expect(entries(state, DECLARE)).toHaveLength(1);
  expect(state.classifications).toEqual([]);
}
function classificationArgs(listNative: Row, data: Prepared, proof: Row): Row {
  const list = value(listNative);
  const lines = list.lignes as {
    selection: Row;
    source_ligne: Row;
    classement_courant: unknown;
    pieces_disponibles_a_selectionner: Row[];
  }[];
  const matching = lines.filter((r) => r.selection.materiau_id === data.material_id);
  expect(matching).toHaveLength(1);
  const [line] = matching;
  expect(line.selection.wct_id).toBe(data.wct_id);
  expect(line.source_ligne.critique).toBe(true);
  expect(line.classement_courant).toBe(null);
  const expectedMovement = proof.reference_mouvement as Row;
  const pieces = line.pieces_disponibles_a_selectionner.filter((p) => {
    const actual = p.reference_mouvement as Row;
    return (
      actual.registre === expectedMovement.registre &&
      actual.index === expectedMovement.index &&
      actual.hash_maillon === expectedMovement.hash_maillon
    );
  });
  expect(pieces).toHaveLength(1);
  expect(pieces[0]).toMatchObject({
    reference_preuve: {
      registre: "preuves_pertes_bris",
      index: proof.index,
      hash_maillon: proof.hash_maillon,
    },
    positions_photos: [0],
  });
  return {
    selection: structuredClone(line.selection),
    cause: "breakage",
    motif: "FICTIF : cause humaine relue.",
    classement_attendu: null,
    references_pieces: structuredClone(pieces),
  };
}
function expectClassified(
  state: State,
  native: Row,
  args: Row,
  baseline: State,
  data: Prepared,
): void {
  expect(native).toMatchObject({ ok: true, resultat: { accepte: true } });
  const ack = value(native);
  expect(state.classifications).toHaveLength(1);
  const [piece] = state.classifications;
  const reference = {
    registre: "classements_variance",
    index: piece.index,
    hash_maillon: piece.hash_maillon,
  };
  expect(ack).toMatchObject({
    selection: args.selection,
    cause: args.cause,
    motif: args.motif,
    references_pieces: args.references_pieces,
    reference,
    auteur: { personne: data.admin, role: "admin", source: "appareil" },
  });
  for (const field of ["selection", "cause", "motif", "references_pieces", "auteur"]) {
    expect(piece[field]).toStrictEqual(ack[field]);
  }
  expect(piece.reference_precedente).toBe(null);
  expect(piece.appareil_id).toBe(data.admin_device);
  expect(state.stock).toBe(baseline.stock);
  expect(state.protected).toStrictEqual(baseline.protected);
  expect(state.proofs).toStrictEqual(baseline.proofs);
  expect(state.refusals).toStrictEqual(baseline.refusals);
  expect(entries(state, CLASSIFY)).toHaveLength(1);
}
async function readLost(home: string): Promise<Lost> {
  try {
    return JSON.parse(await readFile(resolve(home, "m6-proof-response-lost.json"), "utf8")) as Lost;
  } catch (error) {
    const refused = await readFile(resolve(home, "m6-proof-loss-gate-refused.json"), "utf8").catch(
      () => "no gate report",
    );
    throw new Error(`M6 fictive ACK was not independently committed before loss: ${refused}`, {
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

describe("CF026 real Core leases and Python HTTP M6 loss evidence and human classification", () => {
  it("records one real M6 WCT loss with CAS evidence and classifies its cause without stock, cost or M4 effects", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-core-m6-proof-"));
    tempDirs.push(home);
    const data = JSON.parse(await runFixture(python, home, "prepare")) as Prepared;
    expectPrepared(data);
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const seeded = await inspect();
    expect(seeded.movements).toEqual([]);
    expect(seeded.proofs).toEqual([]);
    const server = await startServer(python, home, 1, false);
    const declaration = await call(
      home,
      server.port,
      "m6-proof-declare",
      frame(data, "employee", "core-m6-declare-fictif"),
      DECLARE,
      data.declaration,
    );
    expectDeclaration(await inspect(), data, declaration, seeded);
    await runFixture(python, home, "drain");
    const beforeRead = await inspect();
    const listed = await call(home, server.port, "m6-proof-list", frame(data, "admin"), LIST, {
      wct_id: data.wct_id,
      decalage: 0,
      limite: 8,
    });
    const afterRead = await inspect();
    expect(afterRead.tables).toStrictEqual(beforeRead.tables);
    const args = classificationArgs(listed, data, afterRead.proofs[0]);
    const input = JSON.stringify(args);
    const classified = await call(
      home,
      server.port,
      "m6-proof-classify",
      frame(data, "admin", "core-m6-classify-fictif"),
      CLASSIFY,
      args,
    );
    const committed = await inspect();
    expectClassified(committed, classified, args, afterRead, data);
    expect(JSON.stringify(args)).toBe(input);
    expect(calls(committed, DECLARE)).toHaveLength(1);
    expectOrigins(committed, 1);

    // Last business intention: stale source stays UNKNOWN; only this exact retry follows it.
    const stale = structuredClone(args);
    stale.classement_attendu = value(classified).reference;
    (stale.selection as { reference_variance: Row }).reference_variance.empreinte_charge =
      "0".repeat(64);
    const staleInput = JSON.stringify(stale);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const refused = await call(
        home,
        server.port,
        `m6-proof-stale-${attempt}`,
        frame(data, "admin", "core-m6-stale-same-key-fictif"),
        CLASSIFY,
        stale,
        true,
      );
      expect(refused).toMatchObject({
        ok: false,
        erreur: "REJ-M6-CLASSEMENT-SOURCE-PERIMEE",
        issue: "inconnue",
      });
      expect(refused).not.toHaveProperty("resultat");
      expect(JSON.stringify(stale)).toBe(staleInput);
      const after = await inspect();
      expect(after.tables).toStrictEqual(committed.tables);
      expect(after.classifications).toStrictEqual(committed.classifications);
      expect(after.protected).toStrictEqual(committed.protected);
      expect(entries(after, CLASSIFY)).toHaveLength(1);
    }
  }, 170_000);

  it("replays one committed M6 cause classification after lost ACK and refuses withdrawn participant authority", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-core-m6-lost-"));
    tempDirs.push(home);
    const data = JSON.parse(await runFixture(python, home, "prepare")) as Prepared;
    expectPrepared(data);
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const seeded = await inspect();
    const first = await startServer(python, home, 1, true);
    const declaration = await call(
      home,
      first.port,
      "m6-lost-declare",
      frame(data, "employee", "core-m6-lost-declare-fictif"),
      DECLARE,
      data.declaration,
    );
    expectDeclaration(await inspect(), data, declaration, seeded);
    await runFixture(python, home, "drain");
    const beforeRead = await inspect();
    const listed = await call(home, first.port, "m6-lost-list", frame(data, "admin"), LIST, {
      wct_id: data.wct_id,
      decalage: 0,
      limite: 8,
    });
    const beforeClassification = await inspect();
    expect(beforeClassification.tables).toStrictEqual(beforeRead.tables);
    const args = classificationArgs(listed, data, beforeClassification.proofs[0]);
    await runFixture(python, home, "baseline");
    const originalFrame = frame(data, "admin", "core-m6-lost-classify-fictif");
    let transportFailure: unknown;
    try {
      await call(home, first.port, "m6-lost-classify", originalFrame, CLASSIFY, args);
    } catch (error) {
      transportFailure = error;
    }
    expect(transportFailure).toBeInstanceOf(Error);
    expect(transportFailure).not.toBeInstanceOf(McpLeaseCleanupError);
    const lost = await readLost(home);
    expect(lost).toMatchObject({
      generation: 1,
      independent_committed_read_before_headers: true,
      response_body_forwarded_bytes: 0,
      original_headers_forwarded: true,
      handler_events_before_loss: ["entered", "completed"],
    });
    expect(lost.native_response_bytes_buffered).toBeGreaterThan(0);
    expect(lost.native_result).toMatchObject({ ok: true, rejoue: false });
    const committed = await inspect();
    expectClassified(committed, lost.native_result, args, beforeClassification, data);
    expect(value(lost.native_result).reference).toStrictEqual(lost.classification_reference);
    expect(calls(committed, CLASSIFY)).toHaveLength(1);
    expect(committed.claims).toHaveLength(beforeClassification.claims.length + 1);
    await stopChild(first.child);
    await resetSessionMcpRuntimeManagerGeneration();

    const second = await startServer(python, home, 2, false);
    const replay = await call(
      home,
      second.port,
      "m6-replay-classify",
      originalFrame,
      CLASSIFY,
      args,
    );
    expect(replay).toStrictEqual({ ...lost.native_result, rejoue: true });
    const afterReplay = await inspect();
    expect(afterReplay.tables).toStrictEqual(committed.tables);
    expect(afterReplay.classifications).toStrictEqual(committed.classifications);
    expect(afterReplay.claims).toStrictEqual(committed.claims);
    expect(afterReplay.protected).toStrictEqual(committed.protected);
    expect(entries(afterReplay, CLASSIFY)).toHaveLength(1);
    expect(calls(afterReplay, CLASSIFY)).toHaveLength(2);
    expectOrigins(afterReplay, 1);
    expectOrigins(afterReplay, 2);

    // Canonical participant role withdrawal; Nathan owner and device pairing are not revoked.
    await runFixture(python, home, "withdraw-participant");
    const revoked = await inspect();
    expect(revoked.people.nathan).toEqual(["admin", "nathan_owner"]);
    expect(revoked.people[data.admin]).toEqual(["employee"]);
    expect(revoked.people.etienne).toEqual(["employee"]);
    expect(revoked.protected).toStrictEqual(committed.protected);
    // The owner remains genuinely authorized at the same real read-only boundary.
    const ownerRead = await call(
      home,
      second.port,
      "m6-owner-still-authorized",
      { "opsys/personne": "nathan", "opsys/role": "admin" },
      LIST,
      { wct_id: data.wct_id, decalage: 0, limite: 8 },
    );
    expect(ownerRead).toMatchObject({ ok: true, resultat: { accepte: true } });
    expect((await inspect()).tables).toStrictEqual(revoked.tables);
    const refused = await call(
      home,
      second.port,
      "m6-withdrawn-replay",
      originalFrame,
      CLASSIFY,
      args,
      true,
    );
    expect(refused).toMatchObject({
      ok: false,
      erreur: "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE",
      issue: "inconnue",
    });
    expect(refused).not.toHaveProperty("resultat");
    expect(JSON.stringify(refused)).not.toContain(
      String(lost.classification_reference.hash_maillon),
    );
    expect(JSON.stringify(refused)).not.toContain(String(args.motif));
    const final = await inspect();
    expect(final.tables).toStrictEqual(revoked.tables);
    expect(final.classifications).toStrictEqual(committed.classifications);
    expect(final.protected).toStrictEqual(committed.protected);
    expect(final.claims).toStrictEqual(committed.claims);
    expect(entries(final, CLASSIFY)).toHaveLength(1);
    expect(entries(final, DECLARE)).toHaveLength(1);
    expect(calls(final, CLASSIFY)).toHaveLength(3);
  }, 170_000);
});
