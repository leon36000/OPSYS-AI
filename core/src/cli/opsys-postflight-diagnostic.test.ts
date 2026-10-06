import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { Command } from "commander";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bindSqliteWorkerBackend,
  readOpsysPostflightDiagnosticSnapshot,
} from "../agents/harness/opsys-postflight-outbox.worker.js";
import { depositKey } from "../context-engine/opsys-contexte-depot.js";
import { openOpenClawAgentDatabase } from "../state/openclaw-agent-db.js";
import { cleanupSessionStateForTest } from "../test-utils/session-state-cleanup.js";
import { inspectOpsysPostflightDiagnostic } from "./opsys-postflight-diagnostic.js";
import { registerDatabaseCommand } from "./program/register.database.js";

const dirs: string[] = [];
afterEach(async () => {
  for (const dir of dirs.splice(0)) {
    await cleanupSessionStateForTest({ stateDir: dir });
    fs.rmSync(dir, { recursive: true, force: true });
  }
  vi.restoreAllMocks();
});

function options(agentId = "m03-estimation") {
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-diagnostic-fictif-"));
  dirs.push(stateDir);
  return { agentId, env: { OPENCLAW_STATE_DIR: stateDir } };
}

function fixture() {
  const opts = options();
  const database = openOpenClawAgentDatabase(opts);
  const worker = bindSqliteWorkerBackend(undefined, {
    database: database.db,
    databasePath: database.path,
    admit: () => {}, // Synthetic fixture writer; the diagnostic does not use write admission.
  });
  const intent = (index = 0) => ({
    factKey: depositKey("diagnostic-fictif", `call-${index}`),
    affaireId: "FICTIF-DIAGNOSTIC",
    departementSource: "m03-estimation",
    profilId: "profil-fictif",
    revision: 2,
    engineId: "opsys" as const,
    outil: "m3_creer_devis",
    serverName: "opsys_m3",
    ownerKey: "a".repeat(64),
  });
  const lot = (index = 0) => ({
    affaireId: "FICTIF-DIAGNOSTIC",
    departementSource: "m03-estimation",
    profilId: "profil-fictif",
    revision: 2,
    engineId: "opsys",
    facts: [
      {
        cle: depositKey("diagnostic-fictif", `lot-${index}`),
        outil: "m3_creer_devis",
        resultat: "ok" as const,
        code: null,
      },
    ],
  });
  return { opts, database, worker, intent, lot };
}

describe("operator postflight diagnostic with real SQLite", () => {
  it("does not create a missing database or report a fictitious empty queue", () => {
    const opts = options();
    expect(inspectOpsysPostflightDiagnostic({ ...opts, now: 100 })).toEqual({
      status: "unavailable",
      agentId: opts.agentId,
      reason: "database-missing",
      readOnly: true,
      sourceReplayAllowed: false,
    });
    expect(fs.readdirSync(opts.env.OPENCLAW_STATE_DIR)).toEqual([]);
  });

  it.each(["", "MAIN", " main ", "../main", "m03/estimation", "a".repeat(65)])(
    "refuses non-canonical explicit agent %j without defaulting or touching storage",
    (agentId) => {
      const opts = options(agentId);
      expect(inspectOpsysPostflightDiagnostic({ ...opts, now: 100 })).toMatchObject({
        status: "unavailable",
        reason: "agent-id-invalid",
        agentId: null,
      });
      expect(fs.readdirSync(opts.env.OPENCLAW_STATE_DIR)).toEqual([]);
    },
  );

  it("refuses agent shell invocation before observing a database", () => {
    const opts = options();
    expect(
      inspectOpsysPostflightDiagnostic({
        ...opts,
        env: { ...opts.env, OPENCLAW_SHELL: "exec" },
        now: 100,
      }),
    ).toMatchObject({ status: "unavailable", reason: "operator-only" });
    expect(fs.readdirSync(opts.env.OPENCLAW_STATE_DIR)).toEqual([]);
  });

  it("returns closed metadata, mixed states and capacity without mutating rows or exposing owner lineage", async () => {
    const s = fixture();
    s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 10 } });
    s.worker.execute({ type: "enqueue", input: { lots: [s.lot()], now: 20 } });
    const [retry] = s.worker.execute({ type: "enqueue", input: { lots: [s.lot(1)], now: 30 } });
    s.worker.execute({
      type: "beginAttempt",
      input: { lotKey: retry.lot.lotKey, expected: s.lot(1), now: 40 },
    });
    s.worker.execute({
      type: "recordFailure",
      input: { lotKey: retry.lot.lotKey, expected: s.lot(1), code: "HTTP_503", now: 41 },
    });
    await cleanupSessionStateForTest({ stateDir: s.opts.env.OPENCLAW_STATE_DIR });
    const before = fs.readFileSync(s.database.path);
    const result = inspectOpsysPostflightDiagnostic({ ...s.opts, now: 100 });
    expect(result).toMatchObject({
      status: "available",
      agentId: s.opts.agentId,
      readOnly: true,
      sourceReplayAllowed: false,
      counts: { uncertain: 1, pending: 1, retry: 1, reviewRequired: 0, due: 1 },
      capacity: { occupiedSlots: 3, freeSlots: 253 },
    });
    if (result.status !== "available") {
      throw new Error("expected available diagnostic");
    }
    expect(result.uncertainIntents).toEqual([
      {
        affaireId: "FICTIF-DIAGNOSTIC",
        departementSource: "m03-estimation",
        profilId: "profil-fictif",
        revision: 2,
        outil: "m3_creer_devis",
        createdAt: 10,
      },
    ]);
    expect(result.lots).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ state: "pending", dueForDelivery: true }),
        expect.objectContaining({
          state: "retry",
          attemptCount: 1,
          dueForDelivery: false,
          lastErrorCode: "HTTP_503",
        }),
      ]),
    );
    expect(JSON.stringify(result)).not.toContain(s.intent().ownerKey);
    expect(JSON.stringify(result)).not.toContain("ownerKey");
    expect(JSON.stringify(result)).not.toContain(s.intent().factKey);
    expect(JSON.stringify(result)).not.toContain(retry.lot.lotKey);
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 100 })).toEqual(result);
    expect(fs.readFileSync(s.database.path)).toEqual(before);
  });

  it("reports review age without advancing durable states or clearing uncertainty", () => {
    const s = fixture();
    s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 1 } });
    s.worker.execute({ type: "enqueue", input: { lots: [s.lot()], now: 1 } });
    const result = inspectOpsysPostflightDiagnostic({ ...s.opts, now: 30 * 86_400_000 });
    expect(result).toMatchObject({
      status: "available",
      counts: { uncertain: 1, pending: 1, due: 0, reviewRequired: 1 },
      lots: [{ state: "pending", reviewRequired: true, dueForDelivery: false }],
    });
    expect(s.worker.execute({ type: "listIntents", input: { now: 30 * 86_400_000 } })).toHaveLength(
      1,
    );
    expect(s.database.db.prepare("SELECT state FROM opsys_postflight_outbox").get()).toMatchObject({
      state: "pending",
    });
  });

  it("distinguishes available empty queues from absent additive tables without migrating", () => {
    const s = fixture();
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "available",
      counts: { uncertain: 0, pending: 0, retry: 0, due: 0 },
      capacity: { freeSlots: 256 },
    });
    s.database.db.exec("DROP TABLE opsys_postflight_intents");
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "tables-missing",
    });
    expect(() => s.database.db.prepare("SELECT * FROM opsys_postflight_intents")).toThrow();
  });

  it("refuses a copied database with the wrong canonical owner", async () => {
    const s = fixture();
    await cleanupSessionStateForTest({ stateDir: s.opts.env.OPENCLAW_STATE_DIR });
    const destination = path.join(
      s.opts.env.OPENCLAW_STATE_DIR,
      "agents",
      "main",
      "agent",
      "openclaw-agent.sqlite",
    );
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(s.database.path, destination);
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, agentId: "main", now: 10 })).toMatchObject(
      { status: "unavailable", reason: "read-refused" },
    );
  });

  it("refuses invalid intent metadata without returning a partial trustworthy queue", () => {
    const s = fixture();
    s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 1 } });
    s.database.db.prepare("UPDATE opsys_postflight_intents SET payload_json = ?").run("{}");
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "read-refused",
    });
    expect(
      s.database.db.prepare("SELECT count(*) AS n FROM opsys_postflight_intents").get(),
    ).toMatchObject({ n: 1 });
  });

  it("reports a completely reserved quota without claiming free capacity", () => {
    const s = fixture();
    for (let i = 0; i < 256; i += 1) {
      s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(i), now: 1 } });
    }
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "available",
      counts: { uncertain: 256 },
      capacity: { freeSlots: 0, reservedBytes: 1_048_576, freeBytes: 0 },
    });
  });

  it("refuses an oversized outbox before decoding its payload", () => {
    const s = fixture();
    s.worker.execute({ type: "enqueue", input: { lots: [s.lot()], now: 1 } });
    s.database.db.exec("PRAGMA ignore_check_constraints = ON");
    s.database.db
      .prepare("UPDATE opsys_postflight_outbox SET payload_json = ?")
      .run(JSON.stringify({ fictif: true, padding: "x".repeat(1_048_576) }));
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "read-refused",
    });
  });

  it("refuses a corrupt scheduling timestamp without guessing eligibility", () => {
    const s = fixture();
    s.worker.execute({ type: "enqueue", input: { lots: [s.lot()], now: 1 } });
    s.database.db.exec(
      "PRAGMA ignore_check_constraints = ON; UPDATE opsys_postflight_outbox SET next_attempt_at = -1",
    );
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "read-refused",
    });
  });

  it("does not initialize an existing SQLite file with no agent schema", () => {
    const opts = options();
    const file = path.join(
      opts.env.OPENCLAW_STATE_DIR,
      "agents",
      opts.agentId,
      "agent",
      "openclaw-agent.sqlite",
    );
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const raw = new DatabaseSync(file);
    raw.exec("PRAGMA user_version = 23; CREATE TABLE fixture_fictive (id INTEGER)");
    raw.close();
    const before = fs.readFileSync(file);
    expect(inspectOpsysPostflightDiagnostic({ ...opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "schema-missing",
    });
    expect(fs.readFileSync(file)).toEqual(before);
  });

  it("keeps both completely absent additive tables absent", () => {
    const s = fixture();
    s.database.db.exec("DROP TABLE opsys_postflight_intents; DROP TABLE opsys_postflight_outbox");
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "tables-missing",
    });
    expect(() => s.database.db.prepare("SELECT * FROM opsys_postflight_outbox")).toThrow();
    expect(() => s.database.db.prepare("SELECT * FROM opsys_postflight_intents")).toThrow();
  });

  it("reads one snapshot when a real WAL writer appends after the first schema read", () => {
    const s = fixture();
    const reader = new DatabaseSync(s.database.path, { readOnly: true });
    const prepare = reader.prepare.bind(reader);
    let appended = false;
    vi.spyOn(reader, "prepare").mockImplementation((query) => {
      const statement = prepare(query);
      if (query.includes('"sqlite_schema"')) {
        const all = statement.all.bind(statement);
        vi.spyOn(statement, "all").mockImplementation((...args) => {
          const rows = all(...args);
          if (!appended) {
            appended = true;
            s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 1 } });
          }
          return rows;
        });
        const iterate = statement.iterate.bind(statement);
        vi.spyOn(statement, "iterate").mockImplementation(function* (...args) {
          yield* iterate(...args);
          if (!appended) {
            appended = true;
            s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 1 } });
          }
        });
      }
      return statement;
    });
    try {
      expect(readOpsysPostflightDiagnosticSnapshot(reader, 10)).toMatchObject({
        status: "available",
        snapshot: { counts: { uncertain: 0 }, capacity: { occupiedSlots: 0 } },
      });
      expect(appended).toBe(true);
      expect(reader.isTransaction).toBe(false);
      expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
        status: "available",
        counts: { uncertain: 1 },
        capacity: { occupiedSlots: 1 },
      });
    } finally {
      reader.close();
    }
  });

  it("refuses excess rows before allocating their closed payloads", () => {
    const s = fixture();
    for (let i = 0; i < 256; i += 1) {
      s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(i), now: 1 } });
    }
    s.database.db
      .prepare(
        "INSERT INTO opsys_postflight_intents SELECT ?, payload_json, state, created_at FROM opsys_postflight_intents LIMIT 1",
      )
      .run(s.intent(256).factKey);
    expect(inspectOpsysPostflightDiagnostic({ ...s.opts, now: 10 })).toMatchObject({
      status: "unavailable",
      reason: "read-refused",
    });
    expect(
      s.database.db.prepare("SELECT count(*) AS n FROM opsys_postflight_intents").get(),
    ).toMatchObject({ n: 257 });
  });

  it("runs the actual registered CLI action and JSON output against the selected real database", async () => {
    const s = fixture();
    s.worker.execute({ type: "reserveIntent", input: { intent: s.intent(), now: 1 } });
    const savedState = process.env.OPENCLAW_STATE_DIR;
    const savedShell = process.env.OPENCLAW_SHELL;
    process.env.OPENCLAW_STATE_DIR = s.opts.env.OPENCLAW_STATE_DIR;
    delete process.env.OPENCLAW_SHELL;
    const chunks: string[] = [];
    const stdout = vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
      chunks.push(String(chunk));
      return true;
    });
    try {
      const cli = new Command();
      registerDatabaseCommand(cli);
      await cli.parseAsync(["database", "postflight", "--agent-id", s.opts.agentId, "--json"], {
        from: "user",
      });
      const result = JSON.parse(chunks.join(""));
      expect(result).toMatchObject({
        status: "available",
        agentId: "m03-estimation",
        readOnly: true,
        sourceReplayAllowed: false,
        counts: { uncertain: 1 },
      });
      expect(result.uncertainIntents[0]).toMatchObject({
        affaireId: "FICTIF-DIAGNOSTIC",
        outil: "m3_creer_devis",
      });
      expect(chunks.join("")).not.toContain(s.intent().ownerKey);
    } finally {
      stdout.mockRestore();
      if (savedState === undefined) {
        delete process.env.OPENCLAW_STATE_DIR;
      } else {
        process.env.OPENCLAW_STATE_DIR = savedState;
      }
      if (savedShell === undefined) {
        delete process.env.OPENCLAW_SHELL;
      } else {
        process.env.OPENCLAW_SHELL = savedShell;
      }
    }
  });
});
