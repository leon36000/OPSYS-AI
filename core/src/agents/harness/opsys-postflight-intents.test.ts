import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, describe, expect, it } from "vitest";
import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { cleanupSessionStateForTest } from "../../test-utils/session-state-cleanup.js";
import {
  completeOpsysPostflightIntent,
  listOpsysPostflightIntents,
  observeOpsysM9ApprovalPending,
  reserveOpsysPostflightIntent,
} from "./opsys-postflight-outbox.js";
import { bindSqliteWorkerBackend } from "./opsys-postflight-outbox.worker.js";

const dirs: string[] = [];
afterEach(async () => {
  for (const dir of dirs.splice(0)) {
    await cleanupSessionStateForTest({ stateDir: dir });
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function intent(index = 0) {
  return {
    factKey: depositKey("intent-session", `call-${index}`),
    affaireId: "LEAD-INTENT",
    departementSource: "m03-estimation",
    profilId: "profile-m03",
    revision: 7,
    engineId: "opsys" as const,
    outil: "m3_creer_devis",
    serverName: "opsys_m3",
    ownerKey: "a".repeat(64),
  };
}

function fact(input = intent()) {
  return { cle: input.factKey, outil: input.outil, resultat: "ok" as const, code: null };
}

function m9Intent(index = 0) {
  return {
    ...intent(index),
    departementSource: "m09-strategic-intelligence",
    profilId: "m9-fictif",
    outil: "m9_ouvrir_suivi_decision",
    serverName: "opsys_m9",
  };
}

function local() {
  const database = new DatabaseSync(":memory:");
  let denyCommit = false;
  const backend = bindSqliteWorkerBackend(undefined, {
    databasePath: ":memory:",
    database,
    admit(stage) {
      if (stage === "commit" && denyCommit) {
        throw new Error("SYNTHETIC_COMMIT_REVOKED");
      }
    },
  });
  return {
    database,
    backend,
    deny: () => {
      denyCommit = true;
    },
    allow: () => {
      denyCommit = false;
    },
  };
}

describe("OPSYS durable intent owner", () => {
  it("fences a fresh related M9 opening after reopen and preserves unrelated affairs", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-m9-unknown-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    await reserveOpsysPostflightIntent({ database, options, intent: m9Intent(), now: 1 });
    await cleanupSessionStateForTest({ stateDir: dir });
    expect(database.db.isOpen).toBe(false);
    const reopened = openOpenClawAgentDatabase(options);
    const before = await listOpsysPostflightIntents({ database: reopened, options, now: 2 });
    await expect(
      reserveOpsysPostflightIntent({
        database: reopened,
        options,
        intent: { ...m9Intent(1), ownerKey: "b".repeat(64) },
        now: 3,
      }),
    ).rejects.toThrow("POSTFLIGHT_UNRESOLVED_INTENT");
    expect(await listOpsysPostflightIntents({ database: reopened, options, now: 4 })).toEqual(
      before,
    );
    await expect(
      reserveOpsysPostflightIntent({
        database: reopened,
        options,
        intent: { ...m9Intent(2), affaireId: "LEAD-UNRELATED-FICTIF" },
        now: 5,
      }),
    ).resolves.toMatchObject({ affaireId: "LEAD-UNRELATED-FICTIF" });
  });

  it("persists an exact M9 pending receipt without a fact and permits a new proposal after reopen", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-m9-pending-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    await reserveOpsysPostflightIntent({ database, options, intent: m9Intent(), now: 1 });
    const observation = {
      database,
      options,
      expected: m9Intent(),
      requestId: "abcdef123456",
      now: 2,
    };
    const known = await observeOpsysM9ApprovalPending(observation);
    expect(await observeOpsysM9ApprovalPending({ ...observation, now: 3 })).toEqual(known);
    await cleanupSessionStateForTest({ stateDir: dir });
    const reopened = openOpenClawAgentDatabase(options);
    expect(await listOpsysPostflightIntents({ database: reopened, options, now: 4 })).toEqual([
      {
        ...m9Intent(),
        state: "uncertain",
        createdAt: 1,
        approvalPendingRequestId: "abcdef123456",
      },
    ]);
    await expect(
      reserveOpsysPostflightIntent({ database: reopened, options, intent: m9Intent(), now: 5 }),
    ).rejects.toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
    await expect(
      reserveOpsysPostflightIntent({ database: reopened, options, intent: m9Intent(1), now: 6 }),
    ).resolves.toMatchObject({ factKey: m9Intent(1).factKey });
    expect(reopened.db.prepare("SELECT COUNT(*) AS n FROM opsys_postflight_outbox").get()?.n).toBe(
      0,
    );
    await expect(
      reserveOpsysPostflightIntent({ database: reopened, options, intent: m9Intent(2), now: 7 }),
    ).rejects.toThrow("POSTFLIGHT_UNRESOLVED_INTENT");
  });

  it("retains the M9 fence on mismatched, malformed, or rolled-back pending observations", () => {
    const s = local();
    try {
      s.backend.execute({ type: "reserveIntent", input: { intent: m9Intent(), now: 1 } });
      const pending = { expected: m9Intent(), requestId: "abcdef123456", now: 2 };
      const before = s.backend.execute({ type: "listIntents", input: { now: 2 } });
      expect(() =>
        s.backend.execute({
          type: "observeM9ApprovalPending",
          input: {
            ...pending,
            expected: { ...m9Intent(), ownerKey: "b".repeat(64) },
          },
        }),
      ).toThrow("POSTFLIGHT_INTENT_MISMATCH");
      expect(() =>
        s.backend.execute({
          type: "observeM9ApprovalPending",
          input: {
            ...pending,
            requestId: "not-a-native-request",
          },
        }),
      ).toThrow("POSTFLIGHT_APPROVAL_OBSERVATION_REFUSE");
      s.deny();
      expect(() => s.backend.execute({ type: "observeM9ApprovalPending", input: pending })).toThrow(
        "SYNTHETIC_COMMIT_REVOKED",
      );
      s.allow();
      expect(s.backend.execute({ type: "listIntents", input: { now: 3 } })).toEqual(before);
      expect(() =>
        s.backend.execute({ type: "reserveIntent", input: { intent: m9Intent(1), now: 4 } }),
      ).toThrow("POSTFLIGHT_UNRESOLVED_INTENT");
      s.backend.execute({ type: "observeM9ApprovalPending", input: pending });
      expect(() =>
        s.backend.execute({
          type: "observeM9ApprovalPending",
          input: {
            ...pending,
            requestId: "fedcba654321",
          },
        }),
      ).toThrow("POSTFLIGHT_INTENT_MISMATCH");
    } finally {
      s.database.close();
    }
  });

  it("admits only one of two racing fresh M9 openings for the same affair", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-m9-race-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    const results = await Promise.allSettled(
      [0, 1].map((index) =>
        reserveOpsysPostflightIntent({ database, options, intent: m9Intent(index), now: 1 }),
      ),
    );
    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    const failed = results.find((result) => result.status === "rejected");
    expect(failed?.status === "rejected" && String(failed.reason)).toContain(
      "POSTFLIGHT_UNRESOLVED_INTENT",
    );
    expect(await listOpsysPostflightIntents({ database, options, now: 2 })).toHaveLength(1);
  });

  it("persists uncertainty across a real owner close and reopen without inventing a fact", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-intent-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    await reserveOpsysPostflightIntent({ database, options, intent: intent(), now: 100 });
    await cleanupSessionStateForTest({ stateDir: dir });
    const reopened = openOpenClawAgentDatabase(options);
    const rows = await listOpsysPostflightIntents({
      database: reopened,
      options,
      now: 100 + 30 * 86_400_000,
    });
    expect(rows).toEqual([{ ...intent(), state: "uncertain", createdAt: 100 }]);
    await expect(
      reserveOpsysPostflightIntent({ database: reopened, options, intent: intent(), now: 200 }),
    ).rejects.toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
  });

  it("converts exactly one known outcome atomically and permits only exact capture replay", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-intent-complete-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    const base = { database, options };
    await reserveOpsysPostflightIntent({ ...base, intent: intent(), now: 1 });
    const lot = await completeOpsysPostflightIntent({
      ...base,
      expected: intent(),
      fact: fact(),
      now: 2,
    });
    expect(lot.facts).toEqual([fact()]);
    expect(lot.affaireId).toBe("LEAD-INTENT");
    expect(await listOpsysPostflightIntents({ ...base, now: 3 })).toEqual([]);
    expect(
      await completeOpsysPostflightIntent({ ...base, expected: intent(), fact: fact(), now: 4 }),
    ).toEqual(lot);
    await expect(
      reserveOpsysPostflightIntent({ ...base, intent: intent(), now: 5 }),
    ).rejects.toThrow("POSTFLIGHT_CLE_DEJA_UTILISEE");
  });

  it("rolls back conversion when final write admission is lost", () => {
    const s = local();
    try {
      s.backend.execute({ type: "reserveIntent", input: { intent: intent(), now: 1 } });
      s.deny();
      expect(() =>
        s.backend.execute({
          type: "completeIntent",
          input: { expected: intent(), fact: fact(), now: 2 },
        }),
      ).toThrow("SYNTHETIC_COMMIT_REVOKED");
      s.allow();
      expect(s.backend.execute({ type: "listIntents", input: { now: 3 } })).toHaveLength(1);
      expect(s.backend.execute({ type: "list", input: { now: 3 } })).toEqual([]);
      s.backend.assertSettled?.();
    } finally {
      s.database.close();
    }
  });

  it("refuses divergent ownership, target and observed fact without releasing the reservation", () => {
    const s = local();
    try {
      s.backend.execute({ type: "reserveIntent", input: { intent: intent(), now: 1 } });
      for (const expected of [
        { ...intent(), ownerKey: "b".repeat(64) },
        { ...intent(), affaireId: "OTHER" },
        { ...intent(), revision: 8 },
      ]) {
        expect(() =>
          s.backend.execute({ type: "completeIntent", input: { expected, fact: fact(), now: 2 } }),
        ).toThrow("POSTFLIGHT_INTENT_MISMATCH");
      }
      expect(() =>
        s.backend.execute({
          type: "completeIntent",
          input: { expected: intent(), fact: { ...fact(), outil: "m3_autre" }, now: 2 },
        }),
      ).toThrow("POSTFLIGHT_INTENT_MISMATCH");
      expect(s.backend.execute({ type: "listIntents", input: { now: 3 } })).toHaveLength(1);
      expect(s.backend.execute({ type: "list", input: { now: 3 } })).toEqual([]);
    } finally {
      s.database.close();
    }
  });

  it("shares the existing 256 slots across intentions and observed lots", () => {
    const s = local();
    try {
      for (let i = 0; i < 256; i++) {
        s.backend.execute({ type: "reserveIntent", input: { intent: intent(i), now: 1 } });
      }
      expect(() =>
        s.backend.execute({ type: "reserveIntent", input: { intent: intent(256), now: 2 } }),
      ).toThrow("POSTFLIGHT_QUOTA_LOTS");
      const one = s.backend.execute({
        type: "completeIntent",
        input: { expected: intent(), fact: fact(), now: 2 },
      });
      expect(one).toMatchObject({ facts: [fact()] });
      expect(s.backend.execute({ type: "listIntents", input: { now: 3 } })).toHaveLength(255);
      expect(() =>
        s.backend.execute({
          type: "enqueue",
          input: {
            lots: [
              {
                affaireId: "LEAD-INTENT",
                departementSource: "m03-estimation",
                profilId: "profile-m03",
                revision: 7,
                engineId: "opsys",
                facts: [fact(intent(256))],
              },
            ],
            now: 3,
          },
        }),
      ).toThrow("POSTFLIGHT_QUOTA_LOTS");
    } finally {
      s.database.close();
    }
  });

  it("refuses ordinary enqueue on a reserved key instead of bypassing intent conversion", () => {
    const s = local();
    try {
      s.backend.execute({ type: "reserveIntent", input: { intent: intent(), now: 1 } });
      expect(() =>
        s.backend.execute({
          type: "enqueue",
          input: {
            lots: [
              {
                affaireId: "LEAD-INTENT",
                departementSource: "m03-estimation",
                profilId: "profile-m03",
                revision: 7,
                engineId: "opsys",
                facts: [fact()],
              },
            ],
            now: 2,
          },
        }),
      ).toThrow("POSTFLIGHT_INTENT_ALREADY_RESERVED");
      expect(s.backend.execute({ type: "list", input: { now: 3 } })).toEqual([]);
    } finally {
      s.database.close();
    }
  });

  it("reserves the future byte budget jointly before the 256 row limit", () => {
    const s = local();
    try {
      for (let i = 0; i < 200; i++) {
        s.backend.execute({ type: "reserveIntent", input: { intent: intent(i), now: 1 } });
      }
      const lots = Array.from({ length: 50 }, (_, i) => ({
        affaireId: "LEAD-BYTES",
        departementSource: "m03-estimation",
        profilId: "profile-m03",
        revision: 7,
        engineId: "opsys",
        facts: Array.from({ length: 20 }, (_unusedFact, j) => ({
          cle: depositKey(`bytes-${i}`, `fact-${j}`),
          outil: `m10_${"x".repeat(60)}`,
          resultat: "refus" as const,
          code: "C".repeat(80),
        })),
      }));
      const serializedBytes = lots.reduce(
        (sum, item) =>
          sum +
          Buffer.byteLength(
            JSON.stringify({
              affaire_id: item.affaireId,
              departement_source: item.departementSource,
              profil_id: item.profilId,
              revision: item.revision,
              engine_id: item.engineId,
              faits: item.facts,
            }),
            "utf8",
          ),
        0,
      );
      expect(200 * 4096 + serializedBytes).toBeGreaterThan(1024 * 1024);
      expect(200 + lots.length).toBeLessThanOrEqual(256);
      expect(() => s.backend.execute({ type: "enqueue", input: { lots, now: 2 } })).toThrow(
        "POSTFLIGHT_QUOTA_BYTES",
      );
      expect(s.backend.execute({ type: "list", input: { now: 3 } })).toEqual([]);
      expect(s.backend.execute({ type: "listIntents", input: { now: 3 } })).toHaveLength(200);
    } finally {
      s.database.close();
    }
  });

  it("admits a wide closed intent with capacity for its longest known outcome", () => {
    const s = local();
    try {
      const widest = {
        ...intent(),
        affaireId: "A".repeat(64) + "~opp~" + "B".repeat(128),
        profilId: "P".repeat(64),
        revision: 2_147_483_647,
        departementSource: "m03-" + "d".repeat(1100),
      };
      s.backend.execute({ type: "reserveIntent", input: { intent: widest, now: 1 } });
      expect(
        s.backend.execute({
          type: "completeIntent",
          input: {
            expected: widest,
            fact: { ...fact(widest), resultat: "refus", code: "C".repeat(80) },
            now: 2,
          },
        }),
      ).toMatchObject({ facts: [{ resultat: "refus", code: "C".repeat(80) }] });
      expect(() =>
        s.backend.execute({
          type: "reserveIntent",
          input: {
            intent: { ...intent(999), departementSource: "m03-" + "d".repeat(2048) },
            now: 3,
          },
        }),
      ).toThrow("POSTFLIGHT_INTENT_VALUE_REFUSE");
    } finally {
      s.database.close();
    }
  });

  it("serializes competing durable owners and commits exactly one reservation", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-intent-race-"));
    dirs.push(dir);
    const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
    const database = openOpenClawAgentDatabase(options);
    const outcomes = await Promise.allSettled([
      reserveOpsysPostflightIntent({ database, options, intent: intent(), now: 1 }),
      reserveOpsysPostflightIntent({
        database,
        options,
        intent: { ...intent(), ownerKey: "b".repeat(64) },
        now: 1,
      }),
    ]);
    expect(outcomes.filter((row) => row.status === "fulfilled")).toHaveLength(1);
    expect(outcomes.filter((row) => row.status === "rejected")).toHaveLength(1);
    expect(await listOpsysPostflightIntents({ database, options, now: 2 })).toHaveLength(1);
  });

  it("rejects extra secret fields and noncanonical opaque ownership", () => {
    const s = local();
    try {
      expect(() =>
        s.backend.execute({
          type: "reserveIntent",
          input: { intent: { ...intent(), ticket: "synthetic-forbidden" } as never, now: 1 },
        }),
      ).toThrow("POSTFLIGHT_INTENT_SCHEMA_REFUSE");
      expect(() =>
        s.backend.execute({
          type: "reserveIntent",
          input: { intent: { ...intent(), ownerKey: "raw-client-name" }, now: 1 },
        }),
      ).toThrow("POSTFLIGHT_INTENT_VALUE_REFUSE");
      expect(s.backend.execute({ type: "listIntents", input: { now: 2 } })).toEqual([]);
    } finally {
      s.database.close();
    }
  });
});
