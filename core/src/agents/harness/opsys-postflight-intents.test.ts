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
