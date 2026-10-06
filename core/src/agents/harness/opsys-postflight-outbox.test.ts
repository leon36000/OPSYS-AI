import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, describe, expect, it } from "vitest";
import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import type {
  OpenClawAgentDatabase,
  OpenClawAgentDatabaseOptions,
} from "../../state/openclaw-agent-db-contract.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { cleanupSessionStateForTest } from "../../test-utils/session-state-cleanup.js";
import {
  acknowledgeOpsysPostflightLot,
  beginOpsysPostflightAttempt,
  deriveOpsysPostflightFactKey,
  enqueueOpsysPostflightLots,
  failOpsysPostflightAttempt,
  listDueOpsysPostflightLots,
  listOpsysPostflightLots,
} from "./opsys-postflight-outbox.js";
import { OPSYS_POSTFLIGHT_OUTBOX_TABLE } from "./opsys-postflight-outbox.worker.js";

const dirs: string[] = [];
afterEach(async () => {
  for (const dir of dirs.splice(0)) {
    await cleanupSessionStateForTest({ stateDir: dir });
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function setup(): {
  dir: string;
  options: OpenClawAgentDatabaseOptions;
  database: OpenClawAgentDatabase;
} {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-postflight-outbox-"));
  dirs.push(dir);
  const options = { agentId: "main", env: { OPENCLAW_STATE_DIR: dir } };
  return { dir, options, database: openOpenClawAgentDatabase(options) };
}

function fact(
  sessionId: string,
  callId: string,
  overrides: Partial<{
    outil: string;
    resultat: "ok" | "refus";
    code: string | null;
  }> = {},
) {
  return {
    cle: deriveOpsysPostflightFactKey(sessionId, callId),
    outil: "m10_deposer_faits_candidats",
    resultat: "ok" as const,
    code: null,
    ...overrides,
  };
}

function lot(
  sessionId: string,
  overrides: Partial<{
    affaireId: string;
    departementSource: string;
    profilId: string;
    revision: number;
    engineId: string;
    facts: ReturnType<typeof fact>[];
  }> = {},
) {
  return {
    affaireId: "lead-fictif-1",
    departementSource: "m10-memoire",
    profilId: "m10-agent-fictif",
    revision: 4,
    engineId: "opsys-contexte-engine",
    facts: [fact(sessionId, "tool-call-1")],
    ...overrides,
  };
}

function api(database: OpenClawAgentDatabase, options: OpenClawAgentDatabaseOptions) {
  return { database, options };
}

describe("OPSYS postflight outbox persistence (no dispatch integration)", () => {
  it("stores a closed idempotent lot and reopens it through the agent owner", async () => {
    const first = setup();
    const base = api(first.database, first.options);
    const input = lot("session-a");
    const queued = await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 1_000 });
    expect(queued).toHaveLength(1);
    expect(queued[0]?.created).toBe(true);
    expect(queued[0]?.lot.state).toBe("pending");
    expect(queued[0]?.lot.attemptCount).toBe(0);
    expect(
      (await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 2_000 }))[0]?.created,
    ).toBe(false);
    await expect(
      enqueueOpsysPostflightLots({
        ...base,
        lots: [
          {
            ...input,
            facts: [fact("session-a", "tool-call-1", { resultat: "refus", code: "REJ-FICTIF" })],
          },
        ],
        now: 2_000,
      }),
    ).rejects.toThrow("POSTFLIGHT_CLE_CONTENU_DIVERGENT");
    await expect(
      enqueueOpsysPostflightLots({
        ...base,
        lots: [{ ...input, prompt: "ne doit jamais entrer" } as never],
        now: 2_000,
      }),
    ).rejects.toThrow("POSTFLIGHT_LOT_SCHEMA_REFUSE");

    await cleanupSessionStateForTest({ stateDir: first.dir });
    const reopened = openOpenClawAgentDatabase(first.options);
    const rows = await listOpsysPostflightLots({ ...api(reopened, first.options), now: 3_000 });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.lotKey).toBe(queued[0]?.lot.lotKey);
    expect(rows[0]?.facts).toEqual(input.facts);
  });

  it("uses injected retry times, exact ACK, and persistent needs-review state", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const input = lot("retry-session");
    const lotKey = (await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 10 }))[0]!.lot
      .lotKey;
    let current = await beginOpsysPostflightAttempt({ ...base, lotKey, expected: input, now: 10 });
    expect(current?.attemptCount).toBe(1);
    expect(current?.nextAttemptAt).toBe(60_010);
    expect(await listDueOpsysPostflightLots({ ...base, now: 60_009 })).toEqual([]);
    await expect(
      acknowledgeOpsysPostflightLot({
        ...base,
        lotKey,
        expected: { ...input, engineId: "other-engine" },
        now: 60_009,
      }),
    ).rejects.toThrow("POSTFLIGHT_ACK_CORRESPONDANCE_REFUSE");
    const delays = [
      60_000,
      5 * 60_000,
      15 * 60_000,
      60 * 60_000,
      24 * 60 * 60_000,
      24 * 60 * 60_000,
      24 * 60 * 60_000,
      24 * 60 * 60_000,
    ];
    for (let attempt = 1; attempt < 8; attempt++) {
      const dueAt = current!.nextAttemptAt!;
      current = await beginOpsysPostflightAttempt({ ...base, lotKey, expected: input, now: dueAt });
      expect(current?.attemptCount).toBe(attempt + 1);
      expect(current?.nextAttemptAt).toBe(dueAt + delays[attempt]);
      current = await failOpsysPostflightAttempt({
        ...base,
        lotKey,
        expected: input,
        code: "M10_INDISPONIBLE",
        now: dueAt,
      });
    }
    expect(current?.state).toBe("needs_review");
    expect(current?.attemptCount).toBe(8);
    expect(current?.nextAttemptAt).toBeNull();
    expect((await listOpsysPostflightLots({ ...base, now: current!.updatedAt }))[0]?.state).toBe(
      "needs_review",
    );
    expect(
      await acknowledgeOpsysPostflightLot({
        ...base,
        lotKey,
        expected: input,
        now: current!.updatedAt,
      }),
    ).toBe(true);
    expect(await listOpsysPostflightLots({ ...base, now: current!.updatedAt })).toEqual([]);
  });

  it("ages lots into needs_review after seven days without a timer", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const input = lot("age-session");
    await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 100 });
    const rows = await listOpsysPostflightLots({ ...base, now: 100 + 7 * 24 * 60 * 60 * 1000 });
    expect(rows[0]?.state).toBe("needs_review");
    expect(rows[0]?.needsReviewAt).toBe(100 + 7 * 24 * 60 * 60 * 1000);
    expect(await listDueOpsysPostflightLots({ ...base, now: rows[0]!.needsReviewAt! })).toEqual([]);
  });

  it("enforces both persistent quotas atomically", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const smallLots = Array.from({ length: 256 }, (_, index) => lot(`quota-${index}`));
    expect(await enqueueOpsysPostflightLots({ ...base, lots: smallLots, now: 1 })).toHaveLength(
      256,
    );
    await expect(
      enqueueOpsysPostflightLots({ ...base, lots: [lot("quota-overflow")], now: 2 }),
    ).rejects.toThrow("POSTFLIGHT_QUOTA_LOTS");

    const second = setup();
    const largeLots = Array.from({ length: 256 }, (_unusedLot, lotIndex) =>
      lot(`bytes-${lotIndex}`, {
        facts: Array.from({ length: 20 }, (_, factIndex) =>
          fact(`bytes-${lotIndex}`, `call-${factIndex}`, {
            outil: `m10_${"x".repeat(60)}`,
            code: `C${"c".repeat(79)}`,
          }),
        ),
      }),
    );
    await expect(
      enqueueOpsysPostflightLots({
        ...api(second.database, second.options),
        lots: largeLots,
        now: 1,
      }),
    ).rejects.toThrow("POSTFLIGHT_QUOTA_BYTES");
    expect(
      await listOpsysPostflightLots({ ...api(second.database, second.options), now: 2 }),
    ).toEqual([]);
  });

  it("rejects incompatible owners and stale authorization before persisting a lot", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const input = lot("authorization-session");
    await expect(
      enqueueOpsysPostflightLots({
        database,
        options: { ...options, agentId: "other-agent" },
        lots: [input],
        now: 1,
      }),
    ).rejects.toThrow("POSTFLIGHT_DATABASE_OWNER_MISMATCH");
    await expect(
      enqueueOpsysPostflightLots({
        ...base,
        lots: [input],
        now: 1,
        assertCurrent: () => {
          throw new Error("AUTHORIZATION_REVOKED");
        },
      }),
    ).rejects.toThrow("AUTHORIZATION_REVOKED");
    expect(await listOpsysPostflightLots({ ...base, now: 2 })).toEqual([]);
  });

  it("rejects overlapping fact keys across lots atomically", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const shared = fact("overlap-session", "shared-call");
    const batch = [
      lot("overlap-session-a", { facts: [shared] }),
      lot("overlap-session-b", { facts: [shared, fact("overlap-session", "other-call")] }),
    ];
    await expect(enqueueOpsysPostflightLots({ ...base, lots: batch, now: 1 })).rejects.toThrow(
      "POSTFLIGHT_CLE_DEJA_UTILISEE",
    );
    expect(await listOpsysPostflightLots({ ...base, now: 2 })).toEqual([]);
  });

  it("rejects unknown fact fields without writing", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const malformed = {
      ...lot("extra-fact-field"),
      facts: [{ ...fact("extra-fact-field", "call-1"), texteClient: "private" }],
    };
    await expect(
      enqueueOpsysPostflightLots({ ...base, lots: [malformed as never], now: 1 }),
    ).rejects.toThrow("POSTFLIGHT_FACT_SCHEMA_REFUSE");
    expect(await listOpsysPostflightLots({ ...base, now: 2 })).toEqual([]);
  });

  it("replays the same lot after reversing fact order", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const input = lot("reordered-facts", {
      facts: [fact("reordered-facts", "call-b"), fact("reordered-facts", "call-a")],
    });
    const first = (await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 1 }))[0]!;
    const replay = (
      await enqueueOpsysPostflightLots({
        ...base,
        lots: [{ ...input, facts: input.facts.toReversed() }],
        now: 2,
      })
    )[0]!;
    expect(first.created).toBe(true);
    expect(replay.created).toBe(false);
    expect(replay.lot.lotKey).toBe(first.lot.lotKey);
    expect(await listOpsysPostflightLots({ ...base, now: 3 })).toHaveLength(1);
  });

  it("opens an older owner database without the outbox table and creates it on demand", async () => {
    const first = setup();
    const databasePath = first.database.path;
    await cleanupSessionStateForTest({ stateDir: first.dir });
    const legacy = new DatabaseSync(databasePath);
    legacy.exec(
      `DROP INDEX IF EXISTS idx_agent_opsys_postflight_outbox_due; DROP TABLE IF EXISTS ${OPSYS_POSTFLIGHT_OUTBOX_TABLE};`,
    );
    legacy.close();

    const reopened = openOpenClawAgentDatabase(first.options);
    const base = api(reopened, first.options);
    const input = lot("legacy-owner-db");
    const queued = await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 1 });
    expect(queued[0]?.created).toBe(true);
    expect(await listOpsysPostflightLots({ ...base, now: 2 })).toHaveLength(1);
  });

  it("persists, reopens, and replays canonical v1 and v2 deposit keys exactly", async () => {
    const first = setup();
    const base = api(first.database, first.options);
    const legacyKey = depositKey("session-1", "call_1|fc_abc/def+ghi==");
    const v2Fact = fact("session-v2", "tool-call-v2");
    expect(legacyKey).toMatch(/^tc-[0-9a-f]{40}$/u);
    expect(v2Fact.cle).toMatch(/^tc-[0-9a-f]{64}$/u);
    const input = lot("mixed-key-sizes", {
      facts: [{ cle: legacyKey, outil: "m3_estimer_projet", resultat: "ok", code: null }, v2Fact],
    });

    const queued = await enqueueOpsysPostflightLots({ ...base, lots: [input], now: 1_000 });
    expect(queued[0]?.created).toBe(true);
    await cleanupSessionStateForTest({ stateDir: first.dir });

    const reopened = openOpenClawAgentDatabase(first.options);
    const reopenedBase = api(reopened, first.options);
    const persisted = await listOpsysPostflightLots({ ...reopenedBase, now: 2_000 });
    expect(persisted).toHaveLength(1);
    expect(persisted[0]?.facts.map((item) => item.cle)).toEqual([legacyKey, v2Fact.cle].toSorted());
    const replay = await enqueueOpsysPostflightLots({
      ...reopenedBase,
      lots: [input],
      now: 3_000,
    });
    expect(replay[0]?.created).toBe(false);
    expect(replay[0]?.lot.facts.map((item) => item.cle)).toEqual(
      [legacyKey, v2Fact.cle].toSorted(),
    );

    await expect(
      enqueueOpsysPostflightLots({
        ...reopenedBase,
        lots: [
          {
            ...input,
            facts: [input.facts[0]!, { ...v2Fact, resultat: "refus", code: "REJ-FICTIF" }],
          },
        ],
        now: 4_000,
      }),
    ).rejects.toThrow("POSTFLIGHT_CLE_CONTENU_DIVERGENT");
    expect(await listOpsysPostflightLots({ ...reopenedBase, now: 5_000 })).toHaveLength(1);
  });

  it("refuses malformed key lengths, casing, and prefixes", async () => {
    const { database, options } = setup();
    const base = api(database, options);
    const malformedKeys = [
      `tc-${"a".repeat(41)}`,
      `tc-${"a".repeat(43)}`,
      `tc-${"a".repeat(63)}`,
      `tc-${"a".repeat(65)}`,
      `tc-${"A".repeat(40)}`,
      `TC-${"a".repeat(40)}`,
    ];
    for (const [index, cle] of malformedKeys.entries()) {
      const malformed = lot(`malformed-key-${index}`, {
        facts: [{ cle, outil: "m3_estimer_projet", resultat: "ok", code: null }],
      });
      await expect(
        enqueueOpsysPostflightLots({ ...base, lots: [malformed], now: index + 1 }),
      ).rejects.toThrow("POSTFLIGHT_FACT_VALUE_REFUSE");
    }
    expect(await listOpsysPostflightLots({ ...base, now: 10 })).toEqual([]);
  });
});
