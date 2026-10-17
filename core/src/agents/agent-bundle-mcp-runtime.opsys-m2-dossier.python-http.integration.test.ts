import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
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
  peekSessionMcpRuntime,
  releaseSessionMcpRuntime,
} from "./agent-bundle-mcp-manager-api.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import type { SessionMcpRuntime } from "./agent-bundle-mcp-types.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const FIXTURE = resolve(REPO, "core/test/opsys-m2-dossier-fixture.py");
const M2 = "m02-revenue-crm";
const SERVER = "opsys_m2";
const LOOKUP = "m2_trouver_client_de_lead";
const VIEW = "m2_obtenir_client_360";
const LIST = "m2_lister_leads";
const REASSIGN = "m2_reassigner_lead";
const ADMIN = "nathan";
const A = "vendeur-a-core-m2-fictif";
const B = "vendeur-b-core-m2-fictif";
const DEVICE = "tel-admin-core-m2-dossier-fictif";
const T0 = "2026-10-17T12:00:00+00:00";
const MOTIF = "Le vendeur A est en conge, B reprend ce dossier fictif.";
const UNKNOWN_LEAD = "LEAD-INCONNU-CORE-M2-FICTIF";
const UNKNOWN_CLIENT = "CLIENT-INCONNU-CORE-M2-FICTIF";
const PUBLIC_TOKEN = "synthetic-m2-dossier-public-token-2026";
const PRIVATE_TOKEN = "synthetic-m2-dossier-private-token-2026";
const MAX_OUTPUT = 8 * 1024 * 1024;
const children: ChildProcess[] = [];
const closedChildren = new WeakSet<ChildProcess>();
const tempDirs: string[] = [];
const sessionIds: string[] = [];
let releaseContextConfig: (() => Promise<void>) | undefined;

type Row = Record<string, unknown>;
type Lead = {
  lead_id: string;
  label: string;
  courriel: string;
  ville: string;
  client_id: string;
  demande_id: string;
};
type Prepared = { fictif: boolean; leads: Lead[] };
type Native = {
  ok: boolean;
  rejoue?: boolean;
  resultat: { accepte: boolean; resultat?: Row; verdict?: Row };
};
type Handler = { tool: string; arguments_sha256: string; event: string; fictif: boolean };
type Dispatch = { method: string; tool?: string; arguments: Row; meta: Record<string, string> };
type State = {
  fictif: boolean;
  tables: Record<string, string>;
  protected: Record<string, string>;
  people: Record<string, { active: number; roles: string[] }>;
  principal_rows: Row[];
  pieces: Row[];
  events: Row[];
  claims: Row[];
  approvals: Row[];
  handlers: Handler[];
  dispatches: Dispatch[];
  origins: Record<string, { path: string; sha256: string }>;
};
type Held = { runtime: SessionMcpRuntime; activeLeases: () => number };

async function resetManager(): Promise<void> {
  await getSessionMcpRuntimeManagerForTesting().disposeAll();
  Reflect.deleteProperty(globalThis, SESSION_MCP_RUNTIME_MANAGER_KEY);
}

beforeEach(async () => {
  await resetManager();
  releaseContextConfig = await acquireOpsysContextTestConfig();
});

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error(
      "OPSYS_TEST_PYTHON is required for the Python HTTP M2 dossier integration test",
    );
  }
  return python;
}

function pythonEnv(home: string): NodeJS.ProcessEnv {
  const departments = [
    "m01-front-office",
    M2,
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

function ownChild(python: string, home: string, args: string[]): ChildProcess {
  const child = spawn(python, [FIXTURE, ...args], {
    cwd: REPO,
    env: pythonEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  child.once("close", () => closedChildren.add(child));
  return child;
}

async function runFixture(python: string, home: string, command: string): Promise<string> {
  const child = ownChild(python, home, [command]);
  let stdout = "";
  let stderr = "";
  let overflow = false;
  const collect = (append: (chunk: string) => void) => (chunk: string) => {
    if (stdout.length + stderr.length + chunk.length > MAX_OUTPUT) {
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
        reject(new Error(`Python M2 fixture ${command} exceeded its bounded deadline`));
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
  if (overflow || code !== 0) {
    throw new Error(
      `Python M2 fixture ${command} failed (${code}, overflow=${overflow}): ${stderr.slice(-2_000)}`,
    );
  }
  return stdout.trim();
}

async function waitClosed(child: ChildProcess): Promise<boolean> {
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
    }, 2_000);
    child.once("close", onClose);
  });
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (closedChildren.has(child)) {
    return;
  }
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGTERM");
  }
  if (await waitClosed(child)) {
    return;
  }
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
  }
  if (!(await waitClosed(child))) {
    throw new Error(
      "Owned M2 fixture process did not close its stdout/stderr after bounded cleanup",
    );
  }
}

async function startServer(python: string, home: string): Promise<number> {
  const reservation = createServer();
  await new Promise<void>((resolveListen, reject) => {
    reservation.once("error", reject);
    reservation.listen(0, "127.0.0.1", resolveListen);
  });
  const address = reservation.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not allocate M2 loopback port");
  }
  await new Promise<void>((resolveClose, reject) => {
    reservation.close((error) => (error ? reject(error) : resolveClose()));
  });
  const child = ownChild(python, home, ["serve", "--port", String(address.port)]);
  let output = "";
  await new Promise<void>((resolveReady, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`M2 HTTP startup timed out: ${output.slice(-2_000)}`)),
      15_000,
    );
    const onData = (chunk: string) => {
      output = (output + chunk).slice(-65_536);
      if (output.includes("Uvicorn running on")) {
        clearTimeout(timeout);
        resolveReady();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", onData);
    child.stderr?.setEncoding("utf8").on("data", onData);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`M2 HTTP exited during startup (${code}): ${output.slice(-2_000)}`));
    });
  });
  return address.port;
}

function config(port: number): OpenClawConfig {
  return {
    plugins: { enabled: false },
    mcp: {
      servers: {
        [SERVER]: {
          url: `http://127.0.0.1:${port}/mcp/${M2}`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: `http://127.0.0.1:${port}` },
          headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
      },
    },
  };
}

/** Each acquisition surrounds the entire before/change/after case, never an individual read. */
async function withHeldLease<T>(
  params: Parameters<typeof acquireSessionMcpRuntime>[0],
  effect: (held: Held) => Promise<T>,
): Promise<T> {
  const manager = getSessionMcpRuntimeManagerForTesting();
  sessionIds.push(params.sessionId);
  const acquisition = await acquireSessionMcpRuntime(params);
  const { runtime } = acquisition;
  const activeLeases = () => manager.totalActiveLeasesForSession(params.sessionId);
  try {
    if (!runtime.joinCleanup) {
      throw new Error("Production M2 MCP runtime exposes no cleanup ownership");
    }
    expect(activeLeases()).toBe(1);
    return await effect({ runtime, activeLeases });
  } finally {
    await releaseSessionMcpRuntime(acquisition);
    const afterRelease = activeLeases();
    await manager.disposeSession(params.sessionId);
    await runtime.joinCleanup?.();
    expect(afterRelease).toBe(0);
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
      await resetManager();
    }
  }
});

/** Host-authenticated DEVICE frame fixture; Native/Gateway production of it is outside this test. */
function readFrame(person: string): Record<string, string> {
  return { "opsys/personne": person, "opsys/role": "seller" };
}

function adminFrame(key: string): Record<string, string> {
  return {
    "opsys/personne": ADMIN,
    "opsys/role": "admin",
    "opsys/appareil": DEVICE,
    "opsys/idempotencyKey": key,
    "opsys/horodatageAppareil": T0,
  };
}

function envelope(result: CallToolResult): Native {
  const texts = result.content.filter((item) => item.type === "text");
  if (texts.length !== 1 || texts[0].type !== "text") {
    throw new Error("M2 HTTP response requires exactly one native text result");
  }
  const native = JSON.parse(texts[0].text) as Native;
  expect(result.isError, JSON.stringify(native)).toBe(false);
  expect(native.ok, JSON.stringify(native)).toBe(true);
  return native;
}

function row(value: unknown): Row {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Expected a native object, received ${JSON.stringify(value)}`);
  }
  return value as Row;
}

function rows(value: unknown): Row[] {
  if (!Array.isArray(value)) {
    throw new Error(`Expected a native array, received ${JSON.stringify(value)}`);
  }
  return value.map(row);
}

function accepted(native: Native): Row {
  expect(native.resultat, JSON.stringify(native)).toMatchObject({ accepte: true });
  expect(native.resultat).not.toHaveProperty("verdict");
  return row(native.resultat.resultat);
}

function refused(native: Native): Row {
  expect(native.resultat, JSON.stringify(native)).toMatchObject({
    accepte: false,
    verdict: { code: "REJ-LEAD-NON-ASSIGNE" },
  });
  expect(native.resultat).not.toHaveProperty("resultat");
  return row(native.resultat.verdict);
}

function expectPeople(state: State): void {
  expect(state.people).toStrictEqual({
    [ADMIN]: { active: 1, roles: ["admin", "nathan_owner"] },
    [A]: { active: 1, roles: ["seller"] },
    [B]: { active: 1, roles: ["seller"] },
  });
}

function expectHidden(native: Native, hidden: Lead[]): void {
  const body = JSON.stringify(native);
  for (const lead of hidden) {
    for (const secret of [lead.lead_id, lead.client_id, lead.label, lead.courriel]) {
      expect(body).not.toContain(secret);
    }
  }
}

function expectList(native: Native, visible: Lead[], owner: string, segment: string | null): void {
  const page = accepted(native);
  expect(page).toMatchObject({
    filtre: { statut: null, segment },
    total: visible.length,
    decalage: 0,
    affichees: visible.length,
    reste: 0,
    suivant: null,
  });
  const leads = rows(page.leads);
  expect(
    leads
      .map((lead) => lead.lead_id)
      .toSorted((left, right) => String(left).localeCompare(String(right), "en")),
  ).toEqual(visible.map((lead) => lead.lead_id).toSorted());
  for (const lead of leads) {
    expect(lead).toMatchObject({ statut: "qualifie", proprietaire: owner, urgence_declaree: true });
    expect(rows(lead.segments).filter((entry) => entry.segment === "hot_lead")).toStrictEqual([
      {
        segment: "hot_lead",
        regle: "urgence_declaree_lead_ouvert",
        donnee: { urgence_declaree: true, statut: "qualifie" },
      },
    ]);
  }
}

function expectView(native: Native, lead: Lead): void {
  const view = accepted(native);
  expect(view).toMatchObject({
    client_id: lead.client_id,
    contact: { nom: lead.label, courriel: lead.courriel },
  });
  const opportunities = rows(view.opportunites);
  expect(opportunities).toHaveLength(1);
  expect(opportunities[0]).toMatchObject({
    lead_id: lead.lead_id,
    statut: "qualifie",
    ville: lead.ville,
  });
  expect(view.interactions_recentes).toStrictEqual([
    { lead_id: lead.lead_id, auteur: ADMIN, resume: `Note ${lead.label}`, horodatage: T0 },
  ]);
}

function argumentHash(args: Row): string {
  const sorted = Object.fromEntries(
    Object.keys(args)
      .toSorted()
      .map((key) => [key, args[key]]),
  );
  return createHash("sha256").update(JSON.stringify(sorted)).digest("hex");
}

async function expectOrigins(state: State): Promise<void> {
  const modules: Record<string, string> = {
    "opsys.capacites": "src/opsys/capacites.py",
    "opsys.serveur_mcp": "src/opsys/serveur_mcp.py",
  };
  for (const name of ["outils", "acces", "assignation", "clients", "liste_leads", "segments"]) {
    modules[`m2_revenue_crm.${name}`] = `departments/${M2}/src/m2_revenue_crm/${name}.py`;
  }
  expect(Object.keys(state.origins).toSorted()).toEqual(Object.keys(modules).toSorted());
  for (const [name, relative] of Object.entries(modules)) {
    const path = resolve(REPO, relative);
    expect(state.origins[name]).toStrictEqual({
      path,
      sha256: createHash("sha256")
        .update(await readFile(path))
        .digest("hex"),
    });
  }
}

describe("real Python HTTP M2 DEVICE dossier visibility with retained production Core leases", () => {
  it("moves dossier and hot segment visibility from A to B while A retains its witness dossier and all reads remain pure", async () => {
    const python = requiredPython();
    const home = await mkdtemp(resolve(tmpdir(), "opsys-core-m2-dossier-"));
    tempDirs.push(home);
    const prepared = JSON.parse(await runFixture(python, home, "prepare")) as Prepared;
    expect(prepared.fictif).toBe(true);
    expect(prepared.leads).toHaveLength(2);
    const [transfer, witness] = prepared.leads;
    expect(transfer).toMatchObject({
      lead_id: "LEAD-CORE-M2-TRANSFERT-FICTIF",
      label: "TRANSFERT-FICTIF-821",
    });
    expect(witness).toMatchObject({
      lead_id: "LEAD-CORE-M2-TEMOIN-FICTIF",
      label: "TEMOIN-FICTIF-739",
    });
    expect(transfer.client_id).toBeTruthy();
    expect(witness.client_id).toBeTruthy();
    expect(transfer.client_id).not.toBe(witness.client_id);
    const inspect = async () => JSON.parse(await runFixture(python, home, "inspect")) as State;
    const ingested = await inspect();
    expectPeople(ingested);
    expect(ingested.approvals).toHaveLength(2);
    expect(
      ingested.approvals
        .map((approval) => approval.id)
        .toSorted((left, right) => String(left).localeCompare(String(right), "en")),
    ).toEqual(prepared.leads.map((lead) => lead.demande_id).toSorted());
    for (const approval of ingested.approvals) {
      expect(approval).toMatchObject({
        outil: "m2_ingerer_lead",
        statut: "executee",
        decide_par: ADMIN,
        ticket_cible_hash: null,
      });
    }
    const port = await startServer(python, home);
    const cfg = config(port);
    const leaseParams = (person: string) => ({
      sessionId: `core-m2-dossier-${person}`,
      sessionKey: `agent:main:core-m2-dossier-${person}-fictif`,
      workspaceDir: home,
      cfg,
    });
    await withHeldLease(leaseParams(ADMIN), async (admin) => {
      const mutate = async (tool: string, args: Row, key: string) => {
        expect(admin.activeLeases()).toBe(1);
        const native = envelope(
          await withMcpCallMeta(adminFrame(key), () => admin.runtime.callTool(SERVER, tool, args)),
        );
        expect(native.rejoue).toBe(false);
        expect(admin.activeLeases()).toBe(1);
        return accepted(native);
      };
      for (const lead of prepared.leads) {
        await mutate(
          "m2_transitionner_statut",
          {
            lead_id: lead.lead_id,
            statut_cible: "qualifie",
            owner: A,
            horodatage: T0,
            prochaine_action: {
              description: `Appeler ${lead.label}`,
              echeance: "2026-10-20T09:00:00+00:00",
            },
          },
          `qualifier-${lead.lead_id}`,
        );
        await mutate(
          "m2_enregistrer_interaction",
          { lead_id: lead.lead_id, resume: `Note ${lead.label}`, horodatage: T0 },
          `note-${lead.lead_id}`,
        );
      }
      await withHeldLease(leaseParams(A), async (sellerA) => {
        await withHeldLease(leaseParams(B), async (sellerB) => {
          const retainedA = sellerA.runtime;
          const retainedB = sellerB.runtime;
          expect(retainedA).not.toBe(retainedB);
          const assertHeld = () => {
            expect(peekSessionMcpRuntime({ sessionId: leaseParams(A).sessionId })).toBe(retainedA);
            expect(peekSessionMcpRuntime({ sessionId: leaseParams(B).sessionId })).toBe(retainedB);
            for (const held of [admin, sellerA, sellerB]) {
              expect(held.activeLeases()).toBe(1);
            }
          };
          let cursor = await inspect();
          await expectOrigins(cursor);
          expectPeople(cursor);
          const seeded = cursor;
          expect(cursor.claims).toHaveLength(4);
          expect(cursor.approvals).toHaveLength(6);
          expect(cursor.pieces.filter((piece) => piece.type_entree === "reassignation")).toEqual(
            [],
          );
          for (const lead of prepared.leads) {
            const qualifications = cursor.pieces.filter(
              (piece) =>
                piece.lead_id === lead.lead_id && piece.type_entree === "transition_statut",
            );
            expect(qualifications).toHaveLength(1);
            expect(qualifications[0]).toMatchObject({
              statut: "qualifie",
              statut_precedent: "nouveau",
              owner: A,
            });
            const links = cursor.pieces.filter(
              (piece) => piece.lead_id === lead.lead_id && piece.type_entree === "client_associe",
            );
            expect(links).toHaveLength(1);
            expect(links[0]).toMatchObject({ client_id: lead.client_id });
            const notes = cursor.pieces.filter(
              (piece) => piece.lead_id === lead.lead_id && piece.type_entree === "interaction",
            );
            expect(notes).toHaveLength(1);
            expect(notes[0]).toMatchObject({ auteur: ADMIN, resume: `Note ${lead.label}` });
            const events = cursor.events.filter(
              (event) => event.evenement_id === `m2-lead-assigne-${lead.lead_id}`,
            );
            expect(events).toHaveLength(1);
            expect(JSON.parse(String(events[0].charge))).toStrictEqual({
              lead_id: lead.lead_id,
              proprietaire: A,
              horodatage_assignation: T0,
            });
          }
          const read = async (
            held: Held,
            person: string,
            tool: string,
            args: Row,
          ): Promise<Native> => {
            assertHeld();
            const before = cursor;
            const native = envelope(
              await withMcpCallMeta(readFrame(person), () =>
                held.runtime.callTool(SERVER, tool, args),
              ),
            );
            cursor = await inspect();
            assertHeld();
            expectPeople(cursor);
            expect(cursor.tables, `${person} ${tool} must be a pure T0 read`).toStrictEqual(
              before.tables,
            );
            expect(cursor.handlers.slice(0, before.handlers.length)).toStrictEqual(before.handlers);
            expect(cursor.handlers.slice(before.handlers.length)).toStrictEqual([
              { fictif: true, tool, event: "entered", arguments_sha256: argumentHash(args) },
              { fictif: true, tool, event: "completed", arguments_sha256: argumentHash(args) },
            ]);
            const calls = cursor.dispatches
              .slice(before.dispatches.length)
              .filter((dispatch) => dispatch.method === "tools/call");
            expect(calls).toHaveLength(1);
            expect(calls[0]).toMatchObject({ tool, arguments: args, meta: readFrame(person) });
            expect(
              Object.keys(calls[0].meta)
                .filter((key) => key.startsWith("opsys/"))
                .toSorted(),
            ).toEqual(["opsys/personne", "opsys/role"]);
            return native;
          };
          const lookup = (held: Held, person: string, lead: string) =>
            read(held, person, LOOKUP, { lead_id: lead });
          const view = (held: Held, person: string, client: string) =>
            read(held, person, VIEW, { client_id: client });
          const list = (held: Held, person: string, segment: string | null) =>
            read(held, person, LIST, {
              horodatage: T0,
              decalage: 0,
              limite: 8,
              ...(segment ? { segment } : {}),
            });
          // Prime both native transports and the retained views before the canonical change.
          for (const lead of prepared.leads) {
            expect(accepted(await lookup(sellerA, A, lead.lead_id))).toStrictEqual({
              lead_id: lead.lead_id,
              client_id: lead.client_id,
            });
            expectView(await view(sellerA, A, lead.client_id), lead);
          }
          for (const segment of [null, "hot_lead"]) {
            expectList(await list(sellerA, A, segment), [transfer, witness], A, segment);
            const emptyB = await list(sellerB, B, segment);
            expectList(emptyB, [], B, segment);
            expectHidden(emptyB, [transfer, witness]);
          }
          const unknownLeadB = refused(await lookup(sellerB, B, UNKNOWN_LEAD));
          expect(refused(await lookup(sellerB, B, transfer.lead_id))).toStrictEqual(unknownLeadB);
          const unknownClientB = refused(await view(sellerB, B, UNKNOWN_CLIENT));
          expect(refused(await view(sellerB, B, transfer.client_id))).toStrictEqual(unknownClientB);
          const beforeTransfer = cursor;
          const initializations = beforeTransfer.dispatches.filter(
            (dispatch) => dispatch.method === "initialize",
          );
          expect(initializations).toHaveLength(3);
          assertHeld();
          const reassignmentArgs = {
            lead_id: transfer.lead_id,
            nouveau_proprietaire: B,
            motif: MOTIF,
            horodatage: T0,
          };
          const reassigned = await mutate(
            REASSIGN,
            reassignmentArgs,
            "reassigner-core-m2-dossier-fictif",
          );
          expect(reassigned).toMatchObject({
            lead_id: transfer.lead_id,
            rang: 2,
            proprietaire_precedent: A,
            nouveau_proprietaire: B,
            decide_par: ADMIN,
            decide_role: "admin",
            voie: "appareil",
          });
          cursor = await inspect();
          assertHeld();
          expectPeople(cursor);
          expect(cursor.protected).toStrictEqual(beforeTransfer.protected);
          const oldApprovalIds = new Set(beforeTransfer.approvals.map((approval) => approval.id));
          expect(
            cursor.approvals.filter((approval) => oldApprovalIds.has(approval.id)),
          ).toStrictEqual(beforeTransfer.approvals);
          const newApprovals = cursor.approvals.filter(
            (approval) => !oldApprovalIds.has(approval.id),
          );
          expect(newApprovals).toHaveLength(1);
          expect(newApprovals[0]).toMatchObject({
            outil: REASSIGN,
            niveau: "N3",
            statut: "executee",
            decide_par: ADMIN,
            decide_role: "admin",
            ticket_cible_hash: null,
          });
          expect(cursor.claims).toHaveLength(5);
          expect(cursor.claims.filter((claim) => claim.outil !== REASSIGN)).toStrictEqual(
            beforeTransfer.claims,
          );
          const reassignmentClaims = cursor.claims.filter((claim) => claim.outil === REASSIGN);
          expect(reassignmentClaims).toHaveLength(1);
          expect(reassignmentClaims[0]).toMatchObject({
            appareil: DEVICE,
            cle_idempotence: "reassigner-core-m2-dossier-fictif",
            statut: "ok",
            empreinte_arguments: argumentHash(reassignmentArgs),
          });
          expect(JSON.parse(String(reassignmentClaims[0].reponse))).toMatchObject({
            ok: true,
            resultat: { accepte: true, resultat: reassigned },
          });
          expect(
            cursor.principal_rows.slice(0, beforeTransfer.principal_rows.length),
          ).toStrictEqual(beforeTransfer.principal_rows);
          expect(cursor.principal_rows).toHaveLength(beforeTransfer.principal_rows.length + 1);
          const reassignments = cursor.pieces.filter(
            (piece) => piece.type_entree === "reassignation",
          );
          expect(reassignments).toHaveLength(1);
          expect(reassignments[0]).toMatchObject({
            lead_id: transfer.lead_id,
            rang: 2,
            proprietaire_precedent: A,
            nouveau_proprietaire: B,
            decide_par: ADMIN,
            decide_role: "admin",
            voie: "appareil",
            motif: MOTIF,
            horodatage: reassigned.horodatage,
          });
          const oldEvents = new Set(beforeTransfer.events.map((event) => event.evenement_id));
          expect(cursor.events.filter((event) => oldEvents.has(event.evenement_id))).toStrictEqual(
            beforeTransfer.events,
          );
          const newEvents = cursor.events.filter((event) => !oldEvents.has(event.evenement_id));
          expect(newEvents).toHaveLength(1);
          expect(newEvents[0]).toMatchObject({
            evenement_id: `m2-lead-reassigne-2-${transfer.lead_id}`,
            type_evenement: "m2.lead_assigne",
            producteur: M2,
          });
          expect(JSON.parse(String(newEvents[0].charge))).toStrictEqual({
            lead_id: transfer.lead_id,
            proprietaire: B,
            horodatage_assignation: reassigned.horodatage,
            rang: 2,
            proprietaire_precedent: A,
          });
          expect(cursor.handlers.slice(0, beforeTransfer.handlers.length)).toStrictEqual(
            beforeTransfer.handlers,
          );
          expect(cursor.handlers.slice(beforeTransfer.handlers.length)).toStrictEqual([
            {
              fictif: true,
              tool: REASSIGN,
              event: "entered",
              arguments_sha256: argumentHash(reassignmentArgs),
            },
            {
              fictif: true,
              tool: REASSIGN,
              event: "completed",
              arguments_sha256: argumentHash(reassignmentArgs),
            },
          ]);
          const reassignmentCalls = cursor.dispatches
            .slice(beforeTransfer.dispatches.length)
            .filter((dispatch) => dispatch.method === "tools/call");
          expect(reassignmentCalls).toHaveLength(1);
          expect(reassignmentCalls[0]).toMatchObject({
            tool: REASSIGN,
            arguments: reassignmentArgs,
            meta: adminFrame("reassigner-core-m2-dossier-fictif"),
          });
          expect(reassignmentCalls[0].meta).not.toHaveProperty("opsys/cibleTicket");
          // A's old IDs remain known, but neither existence nor dossier content may leak.
          const lostLookup = await lookup(sellerA, A, transfer.lead_id);
          expect(refused(lostLookup)).toStrictEqual(
            refused(await lookup(sellerA, A, UNKNOWN_LEAD)),
          );
          expectHidden(lostLookup, [transfer]);
          const lostView = await view(sellerA, A, transfer.client_id);
          expect(refused(lostView)).toStrictEqual(refused(await view(sellerA, A, UNKNOWN_CLIENT)));
          expectHidden(lostView, [transfer]);
          // A is still a valid seller: the distinct witness dossier continues to work.
          expect(accepted(await lookup(sellerA, A, witness.lead_id))).toStrictEqual({
            lead_id: witness.lead_id,
            client_id: witness.client_id,
          });
          const witnessView = await view(sellerA, A, witness.client_id);
          expectView(witnessView, witness);
          expectHidden(witnessView, [transfer]);
          // The same B runtime that previously refused the target now exposes it legitimately.
          expect(accepted(await lookup(sellerB, B, transfer.lead_id))).toStrictEqual({
            lead_id: transfer.lead_id,
            client_id: transfer.client_id,
          });
          const receivedView = await view(sellerB, B, transfer.client_id);
          expectView(receivedView, transfer);
          expectHidden(receivedView, [witness]);
          expect(refused(await lookup(sellerB, B, witness.lead_id))).toStrictEqual(unknownLeadB);
          expect(refused(await view(sellerB, B, witness.client_id))).toStrictEqual(unknownClientB);
          for (const segment of [null, "hot_lead"]) {
            const pageA = await list(sellerA, A, segment);
            expectList(pageA, [witness], A, segment);
            expectHidden(pageA, [transfer]);
            const pageB = await list(sellerB, B, segment);
            expectList(pageB, [transfer], B, segment);
            expectHidden(pageB, [witness]);
          }
          expect(
            cursor.dispatches.filter((dispatch) => dispatch.method === "initialize"),
          ).toStrictEqual(initializations);
          expectPeople(cursor);
          expect(cursor.protected).toStrictEqual(seeded.protected);
          assertHeld();
        });
      });
    });
  }, 120_000);
});
