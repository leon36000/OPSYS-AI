import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { expect, it } from "vitest";
import { AgentHarnessPreflightError } from "../agents/harness/errors.js";
import { assertCronRuntimeAuthorityCandidate } from "../cron/runtime-authority-admission.js";
import {
  loadCronRuntimeAuthorities,
  replaceCronRuntimeAuthorityRows,
} from "../cron/store/runtime-authority-store.js";
import type { CronStoredJob } from "../cron/types.js";
import { extractSqliteTableSchema } from "../infra/sqlite-schema-sql.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../state/openclaw-state-db.js";
import { OPENCLAW_STATE_SCHEMA_SQL } from "../state/openclaw-state-schema.js";
import {
  dumpGitBackupDatabase,
  parseGitBackupManifest,
  restoreGitBackupDirectory,
} from "./git-backup-codec.js";

it("omits terminal cleanup ciphertext from secret-excluded Git dumps and preserves full operator backups", async () => {
  // Fictif: true. Tests the export policy, not AES validity or permission to perform cleanup.
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-cron-retirement-"));
  const sourcePath = path.join(root, "source.sqlite");
  const marker = "PRIVATE_RETIREMENT_CIPHERTEXT_FICTIF";
  try {
    const database = openOpenClawStateDatabase({ path: sourcePath }).db;
    database.exec(
      extractSqliteTableSchema(OPENCLAW_STATE_SCHEMA_SQL, "cron_job_runtime_retirements"),
    );
    database
      .prepare(`INSERT INTO cron_job_runtime_retirements
      (store_key,receipt_id,job_id,profile_id,intention_id,epoch,source_hash,input_fingerprint,ciphertext,removed_at_ms)
      VALUES (?,?,?,?,?,?,?,?,?,?)`)
      .run(
        "global",
        "a".repeat(64),
        "deleted-job-fictif",
        "estimation",
        "b".repeat(64),
        1,
        "c".repeat(64),
        "retirement-v1:fictif",
        marker,
        1,
      );
    closeOpenClawStateDatabaseForTest();
    const redacted = path.join(root, "redacted");
    const safeManifest = await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: redacted,
      identity: { role: "global" },
      excludeSecrets: true,
    });
    expect(safeManifest.excludedTables).toContain("cron_job_runtime_retirements");
    expect(safeManifest.tables).not.toHaveProperty("cron_job_runtime_retirements");
    expect(await fs.readFile(path.join(redacted, "schema.sql"), "utf8")).not.toContain(
      "cron_job_runtime_retirements",
    );
    await expect(
      fs.stat(path.join(redacted, "tables/cron_job_runtime_retirements.jsonl")),
    ).rejects.toMatchObject({ code: "ENOENT" });
    const full = path.join(root, "full");
    const operatorManifest = await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: full,
      identity: { role: "global" },
      excludeSecrets: false,
    });
    expect(operatorManifest.tables).toHaveProperty("cron_job_runtime_retirements");
    expect(
      await fs.readFile(path.join(full, "tables/cron_job_runtime_retirements.jsonl"), "utf8"),
    ).toContain(marker);
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("parses legacy Git backup manifests without redactedTables", () => {
  const manifest = parseGitBackupManifest(
    JSON.stringify({
      schemaVersion: 1,
      identity: { role: "global" },
      userVersion: 1,
      excludedTables: [],
      tables: {},
    }),
    "legacy-fixture",
  );
  expect(manifest.redactedTables).toEqual([]);
});

it("omits decryption keys from secret-excluded snapshots and preserves them in full backups", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-encryption-key-redaction-"));
  const sourcePath = path.join(root, "source.sqlite");
  const redactedPath = path.join(root, "redacted");
  const fullPath = path.join(root, "full");
  const keyMarker = "PRIVATE_OBLIGATION_AES_KEY_MARKER";
  const encryptedMarker = "PRIVATE_OBLIGATION_CIPHERTEXT_MARKER";
  const database = openOpenClawStateDatabase({ path: sourcePath }).db;
  try {
    database.exec(`
      CREATE TABLE cles_chiffrement (
        portee TEXT NOT NULL,
        identifiant TEXT NOT NULL,
        cle TEXT NOT NULL,
        cree_le TEXT NOT NULL,
        PRIMARY KEY (portee, identifiant)
      ) STRICT;
      CREATE TABLE registres_maillons (
        departement TEXT NOT NULL,
        registre TEXT NOT NULL,
        rang INTEGER NOT NULL,
        maillon TEXT NOT NULL,
        cree_le TEXT NOT NULL,
        PRIMARY KEY (departement, registre, rang)
      ) STRICT;
    `);
    database
      .prepare(
        "INSERT INTO cles_chiffrement (portee, identifiant, cle, cree_le) VALUES (?, ?, ?, ?)",
      )
      .run("m05/obligations-paies-das", "a".repeat(32), keyMarker, "2026-10-03T00:00:00+00:00");
    database
      .prepare(
        "INSERT INTO registres_maillons (departement, registre, rang, maillon, cree_le) VALUES (?, ?, ?, ?, ?)",
      )
      .run(
        "m05-financecore",
        "obligations_paies_das_privees",
        0,
        JSON.stringify({ schema: 1, ciphertext: encryptedMarker }),
        "2026-10-03T00:00:00+00:00",
      );
    closeOpenClawStateDatabaseForTest();

    const redactedManifest = await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: redactedPath,
      identity: { role: "global" },
      excludeSecrets: true,
    });
    expect(redactedManifest.excludedTables).toContain("cles_chiffrement");
    expect(redactedManifest.tables).not.toHaveProperty("cles_chiffrement");
    const redactedSchema = await fs.readFile(path.join(redactedPath, "schema.sql"), "utf8");
    const redactedManifestJson = await fs.readFile(
      path.join(redactedPath, "manifest.json"),
      "utf8",
    );
    const redactedEnvelope = await fs.readFile(
      path.join(redactedPath, "tables/registres_maillons.jsonl"),
      "utf8",
    );
    expect(redactedSchema).not.toContain("cles_chiffrement");
    expect(redactedManifestJson).not.toContain(keyMarker);
    expect(redactedEnvelope).not.toContain(keyMarker);
    expect(redactedEnvelope).toContain(encryptedMarker);

    const fullManifest = await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: fullPath,
      identity: { role: "global" },
      excludeSecrets: false,
    });
    expect(fullManifest.excludedTables).not.toContain("cles_chiffrement");
    expect(fullManifest.tables).toHaveProperty("cles_chiffrement");
    const fullKeys = await fs.readFile(
      path.join(fullPath, "tables/cles_chiffrement.jsonl"),
      "utf8",
    );
    const fullEnvelope = await fs.readFile(
      path.join(fullPath, "tables/registres_maillons.jsonl"),
      "utf8",
    );
    expect(fullKeys).toContain(keyMarker);
    expect(fullEnvelope).toContain(encryptedMarker);
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("preserves NUL-bearing TEXT, storage classes, and source key order", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-text-"));
  const sourcePath = path.join(root, "source.sqlite");
  const outputPath = path.join(root, "dump");
  const targetPath = path.join(root, "restored.sqlite");
  const keys = ["\0leading", "\nline", " space", "shared\0left", "shared\0right", "雪🦀\0尾"];
  const values = ["text\0suffix", "", null, 9_007_199_254_740_993n, Buffer.from([0, 255]), 1.25];
  const byteQuery =
    'SELECT hex("key") AS key, typeof(value) AS type, hex(value) AS bytes FROM text_values ORDER BY "key"';
  try {
    const source = openOpenClawStateDatabase({ path: sourcePath });
    source.db.exec('CREATE TABLE text_values ("key" TEXT PRIMARY KEY, value ANY) STRICT');
    const insert = source.db.prepare('INSERT INTO text_values ("key", value) VALUES (?, ?)');
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      insert.run(keys[index]!, values[index]!);
    }
    const expectedBytes = source.db.prepare(byteQuery).all();
    closeOpenClawStateDatabaseForTest();

    await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath,
      identity: { role: "global" },
    });
    const content = await fs.readFile(path.join(outputPath, "tables/text_values.jsonl"), "utf8");
    expect(
      content
        .trimEnd()
        .split("\n")
        .map((line) => JSON.parse(line)),
    ).toEqual([
      { key: keys[0], value: "text\0suffix" },
      { key: keys[1], value: "" },
      { key: keys[2], value: null },
      { key: keys[3], value: { $int: "9007199254740993" } },
      { key: keys[4], value: { $hex: "00ff" } },
      { key: keys[5], value: 1.25 },
    ]);
    const restored = await restoreGitBackupDirectory({
      sourcePath: outputPath,
      targetPath,
      expectedIdentity: { role: "global" },
    });
    expect(restored.tables.every((table) => table.ok)).toBe(true);
    const database = new DatabaseSync(targetPath, { readOnly: true });
    try {
      expect(database.prepare(byteQuery).all()).toEqual(expectedBytes);
    } finally {
      database.close();
    }
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("redacts private cron runtime authorities only from secret-excluded Git snapshots", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-cron-authority-"));
  const sourcePath = path.join(root, "source.sqlite");
  const redactedPath = path.join(root, "redacted");
  const operatorPath = path.join(root, "operator");
  const restoredPath = path.join(root, "restored.sqlite");
  const marker = "CRON_CAPABILITY_FICTIVE_MARKER";
  const quarantineMarker = "QUARANTINED_CRON_RAW_JOB_MARKER";
  const publicDiagnosticMarker = "PUBLIC_DIAGNOSTIC_MARKER";
  const database = openOpenClawStateDatabase({ path: sourcePath }).db;
  try {
    const insertJob = database.prepare(`
      INSERT INTO cron_jobs
        (store_key, job_id, name, enabled, payload_kind, job_json, updated_at)
      VALUES (?, ?, ?, ?, 'agentTurn', ?, 1)
    `);
    insertJob.run("global", "job-fictif", "fictif", 1, '{"id":"job-fictif","enabled":true}');
    insertJob.run("global", "job-legacy", "legacy", 1, '{"id":"job-legacy","enabled":true}');
    database
      .prepare(
        "INSERT INTO diagnostic_events (scope, event_key, payload_json, created_at, sequence) VALUES (?, ?, ?, ?, ?)",
      )
      .run(
        "cron.quarantine:global",
        "quarantine-fictif",
        JSON.stringify({ raw: quarantineMarker }),
        1,
        1,
      );
    database
      .prepare(
        "INSERT INTO diagnostic_events (scope, event_key, payload_json, created_at, sequence) VALUES (?, ?, ?, ?, ?)",
      )
      .run(
        "audit.public",
        "public-fictif",
        JSON.stringify({ message: publicDiagnosticMarker }),
        2,
        1,
      );
    replaceCronRuntimeAuthorityRows({
      db: database,
      storeKey: "global",
      jobs: [
        {
          id: "job-fictif",
          name: "job-fictif",
          enabled: true,
          createdAtMs: 1,
          updatedAtMs: 1,
          schedule: { kind: "every", everyMs: 60_000 },
          sessionTarget: "isolated",
          wakeMode: "now",
          payload: { kind: "agentTurn", message: "fictif", toolsAllow: ["read"] },
          state: {},
          runtimeAuthority: {
            version: 1,
            runtimeId: "codex",
            namespace: "fictive-capability",
            payload: { capability: marker },
          },
        },
      ],
    });
    expect(
      database
        .prepare("SELECT authority_json FROM cron_job_runtime_authorities WHERE job_id = ?")
        .get("job-fictif"),
    ).toMatchObject({ authority_json: expect.stringContaining(marker) });
    closeOpenClawStateDatabaseForTest();

    await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: redactedPath,
      identity: { role: "global" },
      excludeSecrets: true,
    });
    const redactedManifest = JSON.parse(
      await fs.readFile(path.join(redactedPath, "manifest.json"), "utf8"),
    ) as {
      excludedTables: string[];
      redactedTables: string[];
      tables: Record<string, unknown>;
    };
    expect(redactedManifest.excludedTables).not.toContain("cron_job_runtime_authorities");
    expect(redactedManifest.redactedTables).toContain("cron_job_runtime_authorities");
    expect(redactedManifest.redactedTables).toContain("cron_jobs");
    expect(redactedManifest.redactedTables).toContain("diagnostic_events");
    expect(redactedManifest.tables).toHaveProperty("cron_job_runtime_authorities");
    const projectedAuthority = JSON.parse(
      await fs.readFile(
        path.join(redactedPath, "tables/cron_job_runtime_authorities.jsonl"),
        "utf8",
      ),
    ) as Record<string, unknown>;
    expect(projectedAuthority).toMatchObject({
      authority_json: null,
      authority_input_fingerprint: null,
      recovery_required: 1,
    });
    expect(await fs.readFile(path.join(redactedPath, "schema.sql"), "utf8")).toContain(
      "cron_job_runtime_authorities",
    );
    const redactedFiles = await Promise.all(
      [
        "manifest.json",
        "schema.sql",
        "tables/cron_jobs.jsonl",
        "tables/cron_job_runtime_authorities.jsonl",
        "tables/diagnostic_events.jsonl",
      ].map((file) => fs.readFile(path.join(redactedPath, file), "utf8")),
    );
    expect(redactedFiles.join("\n")).not.toContain(marker);
    expect(redactedFiles.join("\n")).not.toContain(quarantineMarker);
    expect(redactedFiles.join("\n")).toContain(publicDiagnosticMarker);
    const projectedDiagnostics = redactedFiles[4]!
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line) as { scope: string; payload_json: string });
    expect(projectedDiagnostics).toHaveLength(1);
    expect(projectedDiagnostics[0]?.scope).toBe("audit.public");
    expect(projectedDiagnostics[0]?.payload_json).toContain(publicDiagnosticMarker);
    const projectedJobs = redactedFiles[2]!
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line) as { job_id: string; enabled: number; job_json: string });
    expect(projectedJobs.find((job) => job.job_id === "job-fictif")).toMatchObject({ enabled: 0 });
    expect(
      JSON.parse(projectedJobs.find((job) => job.job_id === "job-fictif")!.job_json),
    ).toMatchObject({ enabled: false });
    expect(projectedJobs.find((job) => job.job_id === "job-legacy")).toMatchObject({ enabled: 1 });
    expect(
      JSON.parse(projectedJobs.find((job) => job.job_id === "job-legacy")!.job_json),
    ).toMatchObject({ enabled: true });
    const active = new DatabaseSync(sourcePath, { readOnly: true });
    try {
      expect(
        active
          .prepare("SELECT authority_json FROM cron_job_runtime_authorities WHERE job_id = ?")
          .get("job-fictif"),
      ).toMatchObject({ authority_json: expect.stringContaining(marker) });
      expect(
        active.prepare("SELECT enabled FROM cron_jobs WHERE job_id = ?").get("job-fictif"),
      ).toEqual({ enabled: 1 });
      expect(
        active.prepare("SELECT enabled FROM cron_jobs WHERE job_id = ?").get("job-legacy"),
      ).toEqual({ enabled: 1 });
      expect(
        active
          .prepare(
            "SELECT payload_json FROM diagnostic_events WHERE scope LIKE 'cron.quarantine:%'",
          )
          .get(),
      ).toMatchObject({ payload_json: expect.stringContaining(quarantineMarker) });
      expect(
        active
          .prepare("SELECT payload_json FROM diagnostic_events WHERE scope = ?")
          .get("audit.public"),
      ).toMatchObject({ payload_json: expect.stringContaining(publicDiagnosticMarker) });
    } finally {
      active.close();
    }
    await restoreGitBackupDirectory({
      sourcePath: redactedPath,
      targetPath: restoredPath,
      expectedIdentity: { role: "global" },
    });
    const restored = new DatabaseSync(restoredPath, { readOnly: true });
    try {
      expect(
        restored
          .prepare("SELECT enabled, job_json FROM cron_jobs WHERE job_id = ?")
          .get("job-fictif"),
      ).toMatchObject({ enabled: 0, job_json: expect.stringContaining('"enabled":false') });
      expect(
        restored
          .prepare("SELECT enabled, job_json FROM cron_jobs WHERE job_id = ?")
          .get("job-legacy"),
      ).toMatchObject({ enabled: 1, job_json: expect.stringContaining('"enabled":true') });
      expect(
        restored
          .prepare(
            "SELECT authority_json, authority_input_fingerprint, recovery_required FROM cron_job_runtime_authorities WHERE job_id = ?",
          )
          .get("job-fictif"),
      ).toEqual({
        authority_json: null,
        authority_input_fingerprint: null,
        recovery_required: 1,
      });
    } finally {
      restored.close();
    }

    // Even if an operator re-enables a restored row, the persisted recovery marker
    // must stop authority admission before any provider can be selected.
    const reactivated = new DatabaseSync(restoredPath);
    try {
      reactivated
        .prepare("UPDATE cron_jobs SET enabled = 1, job_json = ? WHERE job_id = ?")
        .run('{"id":"job-fictif","enabled":true}', "job-fictif");
      const recoveredJob: CronStoredJob = {
        id: "job-fictif",
        name: "job-fictif",
        enabled: true,
        createdAtMs: 1,
        updatedAtMs: 1,
        schedule: { kind: "every", everyMs: 60_000 },
        sessionTarget: "isolated",
        wakeMode: "now",
        payload: { kind: "agentTurn", message: "fictif" },
        state: {},
      };
      loadCronRuntimeAuthorities({ db: reactivated, storeKey: "global", jobs: [recoveredJob] });
      expect(recoveredJob.runtimeAuthorityRecoveryRequired).toBe(true);
      expect(() =>
        assertCronRuntimeAuthorityCandidate({
          authority: recoveredJob.runtimeAuthority,
          recoveryRequired: recoveredJob.runtimeAuthorityRecoveryRequired === true,
          candidateRuntime: "codex",
          cliExecution: false,
        }),
      ).toThrow(AgentHarnessPreflightError);
      expect(recoveredJob.runtimeAuthority).toBeUndefined();
    } finally {
      reactivated.close();
    }

    await dumpGitBackupDatabase({
      snapshotPath: sourcePath,
      outputPath: operatorPath,
      identity: { role: "global" },
      excludeSecrets: false,
    });
    const operatorManifest = JSON.parse(
      await fs.readFile(path.join(operatorPath, "manifest.json"), "utf8"),
    ) as { excludedTables: string[]; redactedTables: string[]; tables: Record<string, unknown> };
    expect(operatorManifest.excludedTables).not.toContain("cron_job_runtime_authorities");
    expect(operatorManifest.redactedTables).not.toContain("cron_job_runtime_authorities");
    expect(operatorManifest.redactedTables).not.toContain("diagnostic_events");
    expect(operatorManifest.tables).toHaveProperty("cron_job_runtime_authorities");
    expect(
      await fs.readFile(
        path.join(operatorPath, "tables/cron_job_runtime_authorities.jsonl"),
        "utf8",
      ),
    ).toContain(marker);
    expect(await fs.readFile(path.join(operatorPath, "tables/cron_jobs.jsonl"), "utf8")).toContain(
      '"enabled":1',
    );
    expect(
      await fs.readFile(path.join(operatorPath, "tables/diagnostic_events.jsonl"), "utf8"),
    ).toContain(quarantineMarker);
  } finally {
    if (database.isOpen) {
      database.close();
    }
    closeOpenClawStateDatabaseForTest();
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("fails closed when a secret-redacted cron job has malformed job JSON", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-malformed-cron-job-"));
  const sourcePath = path.join(root, "source.sqlite");
  const outputPath = path.join(root, "redacted");
  const database = new DatabaseSync(sourcePath);
  try {
    database.exec(`
      CREATE TABLE cron_jobs (
        store_key TEXT NOT NULL,
        job_id TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        job_json TEXT NOT NULL,
        PRIMARY KEY (store_key, job_id)
      ) STRICT;
      CREATE TABLE cron_job_runtime_authorities (
        store_key TEXT NOT NULL,
        job_id TEXT NOT NULL,
        authority_json TEXT,
        authority_input_fingerprint TEXT,
        recovery_required INTEGER NOT NULL,
        PRIMARY KEY (store_key, job_id)
      ) STRICT;
      INSERT INTO cron_jobs VALUES ('global', 'job-fictif', 1, '{malformed');
      INSERT INTO cron_job_runtime_authorities VALUES ('global', 'job-fictif', NULL, NULL, 1);
    `);
    database.close();

    await expect(
      dumpGitBackupDatabase({
        snapshotPath: sourcePath,
        outputPath,
        identity: { role: "global" },
        excludeSecrets: true,
      }),
    ).rejects.toThrow("cannot inspect cron job JSON");
  } finally {
    if (database.isOpen) {
      database.close();
    }
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("refuses redacted backups containing legacy embedded cron authority", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-legacy-cron-authority-"));
  const sourcePath = path.join(root, "source.sqlite");
  const outputPath = path.join(root, "redacted");
  const marker = "LEGACY_CRON_SECRET_MARKER";
  const database = new DatabaseSync(sourcePath);
  try {
    database.exec(`
      CREATE TABLE cron_jobs (
        store_key TEXT NOT NULL,
        job_id TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        job_json TEXT NOT NULL,
        PRIMARY KEY (store_key, job_id)
      ) STRICT;
    `);
    database.prepare("INSERT INTO cron_jobs VALUES ('global', 'legacy-fictif', 1, ?)").run(
      JSON.stringify({
        id: "legacy-fictif",
        enabled: true,
        runtimeAuthority: { version: 1, payload: marker },
      }),
    );
    database.close();

    let failure: unknown;
    try {
      await dumpGitBackupDatabase({
        snapshotPath: sourcePath,
        outputPath,
        identity: { role: "global" },
        excludeSecrets: true,
      });
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toContain("embedded private cron authority");
    expect((failure as Error).message).not.toContain(marker);
    const readTree = async (directory: string): Promise<string[]> => {
      const entries = await fs.readdir(directory, { withFileTypes: true });
      const nested = await Promise.all(
        entries.map(async (entry) => {
          const entryPath = path.join(directory, entry.name);
          return entry.isDirectory() ? readTree(entryPath) : [await fs.readFile(entryPath, "utf8")];
        }),
      );
      return nested.flat();
    };
    expect((await readTree(outputPath)).join("\n")).not.toContain(marker);
    await expect(fs.readFile(path.join(outputPath, "manifest.json"), "utf8")).rejects.toThrow();
    const source = new DatabaseSync(sourcePath, { readOnly: true });
    try {
      expect(
        source.prepare("SELECT job_json FROM cron_jobs WHERE job_id = ?").get("legacy-fictif"),
      ).toMatchObject({ job_json: expect.stringContaining(marker) });
    } finally {
      source.close();
    }
  } finally {
    if (database.isOpen) {
      database.close();
    }
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("fails closed on a diagnostic event with a non-text scope", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "git-backup-diagnostic-scope-"));
  const sourcePath = path.join(root, "source.sqlite");
  const outputPath = path.join(root, "redacted");
  const database = new DatabaseSync(sourcePath);
  try {
    database.exec(`
      CREATE TABLE diagnostic_events (
        scope ANY NOT NULL,
        event_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        sequence INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (scope, event_key)
      ) STRICT;
      INSERT INTO diagnostic_events (scope, event_key, payload_json, created_at)
      VALUES (42, 'malformed-scope', '{}', 1);
    `);
    database.close();

    await expect(
      dumpGitBackupDatabase({
        snapshotPath: sourcePath,
        outputPath,
        identity: { role: "global" },
        excludeSecrets: true,
      }),
    ).rejects.toThrow("cannot classify a diagnostic event scope");
    await expect(fs.readFile(path.join(outputPath, "manifest.json"), "utf8")).rejects.toThrow();
  } finally {
    if (database.isOpen) {
      database.close();
    }
    await fs.rm(root, { recursive: true, force: true });
  }
});
