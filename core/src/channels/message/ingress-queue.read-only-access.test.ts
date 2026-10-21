import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
// Read-only ingress listing tests cover access that must not create shared state.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";
import { openNodeSqliteDatabase } from "../../infra/node-sqlite.js";
import { PluginInstance } from "../../plugins/plugin-instance.js";
import { openClawStateDatabaseCache } from "../../state/openclaw-state-db-cache.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../../state/openclaw-state-db.js";
import {
  createChannelIngressQueue,
  readOwnNativeSmsClaimOrigin,
  listChannelIngressQueueAccountIdsReadOnly,
} from "./ingress-queue.js";

describe("read-only listing access", () => {
  it("lists without creating the shared state database", async () => {
    const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-ingress-readonly-"));
    try {
      const sqlitePath = path.join(stateDir, "state", "openclaw.sqlite");
      await expect(fs.access(sqlitePath)).rejects.toThrow();

      const reader = createChannelIngressQueue<{ text: string }>({
        channelId: "line",
        accountId: "default",
        stateDir,
        access: "read-only",
      });
      // The read-only opener never creates, migrates or configures the file, so a
      // caller that runs before it owns the state cannot bring the store into being.
      // Account discovery runs before the inspection facade is even opened, so it is
      // the first thing that could create the store.
      expect(
        await listChannelIngressQueueAccountIdsReadOnly({ channelId: "line", stateDir }),
      ).toEqual([]);
      await expect(fs.access(sqlitePath)).rejects.toThrow();

      expect(await reader.listPending({ limit: "all" })).toEqual([]);
      expect(await reader.listClaims()).toEqual([]);
      expect(await reader.listFailed?.({ limit: "all" })).toEqual([]);
      await expect(fs.access(sqlitePath)).rejects.toThrow();

      // A read-write queue is what actually creates it, and the read-only reader then
      // sees the same rows - so the empty results above are the access mode, not a
      // broken reader.
      await createChannelIngressQueue<{ text: string }>({
        channelId: "line",
        accountId: "default",
        stateDir,
      }).enqueue("evt-1", { text: "hello" });
      await fs.access(sqlitePath);
      closeOpenClawStateDatabaseForTest();

      const after = createChannelIngressQueue<{ text: string }>({
        channelId: "line",
        accountId: "default",
        stateDir,
        access: "read-only",
      });
      expect((await after.listPending({ limit: "all" })).map((row) => row.id)).toEqual(["evt-1"]);
      expect(
        await listChannelIngressQueueAccountIdsReadOnly({ channelId: "line", stateDir }),
      ).toEqual(["default"]);
    } finally {
      closeOpenClawStateDatabaseForTest();
      await fs.rm(stateDir, { recursive: true, force: true });
    }
  });
});

// Every state directory, payload and owner below is a fictitious local test fixture.
function fileState(stateDir: string) {
  const directory = path.join(stateDir, "state");
  return Object.fromEntries(
    readdirSync(directory)
      .toSorted()
      .map((name) => {
        const filename = path.join(directory, name);
        return [
          name,
          {
            size: statSync(filename).size,
            sha256: createHash("sha256").update(readFileSync(filename)).digest("hex"),
          },
        ];
      }),
  );
}

async function withClaimFixture(
  run: (fixture: {
    stateDir: string;
    database: ReturnType<typeof openOpenClawStateDatabase>;
    queue: ReturnType<typeof createChannelIngressQueue<{ fictif: true }>>;
    claim: NonNullable<Awaited<ReturnType<ReturnType<typeof createChannelIngressQueue>["claim"]>>>;
  }) => Promise<void>,
) {
  const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-claim-identity-"));
  try {
    const queue = createChannelIngressQueue<{ fictif: true }>({
      channelId: "sms",
      accountId: "fixture",
      stateDir,
      now: () => 100,
    });
    await queue.enqueue("event-fictif", { fictif: true });
    const claim = await queue.claim("event-fictif", { ownerId: "owner-fictif" });
    if (!claim) {
      throw new Error("Fixture claim missing");
    }
    const database = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } });
    await run({ stateDir, queue, claim, database });
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(stateDir, { recursive: true, force: true });
  }
}

function prepareIdentity(queue: ReturnType<typeof createChannelIngressQueue>) {
  expect(typeof queue.prepareClaimIdentityReader).toBe("function");
  if (!queue.prepareClaimIdentityReader) {
    throw new Error("Identity capability missing");
  }
  return queue.prepareClaimIdentityReader();
}

describe("prepared current claim identity", () => {
  it("does not create absent state or adopt an owner that appears later", async () => {
    const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-claim-absent-"));
    const queue = createChannelIngressQueue({ channelId: "sms", accountId: "fixture", stateDir });
    const reader = await prepareIdentity(queue);
    try {
      const reference = { id: "event-fictif", claim: { token: "token-fictif" } };
      expect(reader.read(reference)).toBeNull();
      expect(await fs.readdir(stateDir)).toEqual([]);
      await queue.enqueue("event-fictif", { fictif: true });
      const claim = await queue.claim("event-fictif");
      expect(claim).not.toBeNull();
      if (claim) {
        expect(reader.read(claim)).toBeNull();
      }
      reader.dispose();
      reader.dispose();
    } finally {
      reader.dispose();
      closeOpenClawStateDatabaseForTest();
      await fs.rm(stateDir, { recursive: true, force: true });
    }
  });

  it("returns only four frozen detached fields synchronously with exact id/token/account", async () => {
    await withClaimFixture(async ({ queue, claim, stateDir }) => {
      const reader = await prepareIdentity(queue);
      const other = await prepareIdentity(
        createChannelIngressQueue({
          channelId: "sms",
          accountId: "other",
          stateDir,
        }),
      );
      try {
        const identity = reader.read(claim);
        expect(identity).toEqual({ id: claim.id, ...claim.claim });
        expect(Object.keys(identity ?? {}).toSorted()).toEqual([
          "claimedAt",
          "id",
          "ownerId",
          "token",
        ]);
        expect(Object.isFrozen(identity)).toBe(true);
        expect(identity).not.toBe(reader.read(claim));
        expect(reader.read({ id: ` ${claim.id}`, claim: claim.claim })).toBeNull();
        expect(reader.read({ id: claim.id, claim: { token: `${claim.claim.token} ` } })).toBeNull();
        expect(other.read(claim)).toBeNull();
        expect(reader.read(claim)).toEqual(identity);
        reader.dispose();
        expect(reader.read(claim)).toBeNull();
      } finally {
        other.dispose();
        reader.dispose();
      }
    });
  });

  it("rejects malformed references without executing accessors or poisoning a valid reader", async () => {
    await withClaimFixture(async ({ queue, claim }) => {
      const reader = await prepareIdentity(queue);
      let accesses = 0;
      try {
        const getter = {
          get id() {
            accesses++;
            return claim.id;
          },
          claim: claim.claim,
        };
        expect(reader.read(getter)).toBeNull();
        const nested = {
          id: claim.id,
          claim: {
            get token() {
              accesses++;
              return claim.claim.token;
            },
          },
        };
        expect(reader.read(nested)).toBeNull();
        expect(accesses).toBe(0);
        expect(reader.read({ id: "", claim: { token: "" } })).toBeNull();
        expect(
          reader.read(Object.assign(Object.create({}), { id: claim.id, claim: claim.claim })),
        ).toBeNull();
        expect(reader.read(claim)).not.toBeNull();
      } finally {
        reader.dispose();
      }
    });
  });

  it.each(["outer", "nested", "revoked"] as const)(
    "rejects a %s Proxy without traps, database effects or loss of the healthy reader",
    async (kind) => {
      await withClaimFixture(async ({ queue, claim, database, stateDir }) => {
        const reader = await prepareIdentity(queue);
        let traps = 0;
        const handler = {
          getPrototypeOf(target: object) {
            traps++;
            return Reflect.getPrototypeOf(target);
          },
          getOwnPropertyDescriptor(target: object, key: PropertyKey) {
            traps++;
            return Reflect.getOwnPropertyDescriptor(target, key);
          },
        };
        const reference = { id: claim.id, claim: { token: claim.claim.token } };
        const revoked = Proxy.revocable(reference, handler);
        revoked.revoke();
        const hostile =
          kind === "outer"
            ? new Proxy(reference, handler)
            : kind === "nested"
              ? { id: claim.id, claim: new Proxy(reference.claim, handler) }
              : revoked.proxy;
        const snapshot = () => {
          // sqlite-allow-raw -- Complete local fixture census independent of the claim projection.
          const tables = database.db
            .prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
            .all();
          return tables.map(({ name }) => {
            if (typeof name !== "string") {
              throw new Error("Invalid table name");
            }
            return [
              name,
              database.db.prepare(`SELECT * FROM "${name.replaceAll('"', '""')}"`).all(),
            ];
          });
        };
        try {
          const before = snapshot();
          const files = fileState(stateDir);
          expect(reader.read(hostile)).toBeNull();
          expect(traps).toBe(0);
          expect(reader.read(claim)).toEqual({ id: claim.id, ...claim.claim });
          expect(snapshot()).toEqual(before);
          expect(fileState(stateDir)).toEqual(files);
        } finally {
          reader.dispose();
        }
      });
    },
  );

  it("does not decode corrupt large payloads or change any tables, rows, attempts or file bytes", async () => {
    await withClaimFixture(async ({ queue, claim, database, stateDir }) => {
      // sqlite-allow-raw -- Test-only corruption of the real durable row, not a reader substitute.
      database.db
        .prepare(
          "UPDATE channel_ingress_events SET payload_json = ?, metadata_json = ? WHERE event_id = ?",
        )
        .run("invalid-json-".repeat(100000), "not-json", claim.id);
      const reader = await prepareIdentity(queue);
      const snapshot = () => {
        // sqlite-allow-raw -- Test census of every real table and its complete rows.
        const names = database.db
          .prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
          .all();
        return names.map(({ name }) => {
          if (typeof name !== "string") {
            throw new Error("Invalid table name");
          }
          return [name, database.db.prepare(`SELECT * FROM "${name.replaceAll('"', '""')}"`).all()];
        });
      };
      try {
        const tables = snapshot();
        const files = fileState(stateDir);
        // sqlite-allow-raw -- Native write counter provides an independent no-write witness.
        const writes = database.db.prepare("SELECT total_changes() AS count").get();
        expect(reader.read(claim)).toEqual({ id: claim.id, ...claim.claim });
        reader.dispose();
        expect(snapshot()).toEqual(tables);
        expect(database.db.prepare("SELECT total_changes() AS count").get()).toEqual(writes);
        expect(fileState(stateDir)).toEqual(files);
        expect(database.db.isOpen).toBe(true);
      } finally {
        reader.dispose();
      }
    });
  });

  it("observes real WAL peer refresh and re-claim instead of a prepared snapshot", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      const peer = openNodeSqliteDatabase(database.path);
      try {
        // sqlite-allow-raw -- Controlled independent writer on the same physical WAL fixture.
        expect(peer.prepare("PRAGMA journal_mode").get()?.journal_mode).toBe("wal");
        expect(reader.read(claim)?.claimedAt).toBe(100);
        peer
          .prepare("UPDATE channel_ingress_events SET claimed_at = ? WHERE event_id = ?")
          .run(200, claim.id);
        expect(reader.read(claim)?.claimedAt).toBe(200);
        peer
          .prepare(
            "UPDATE channel_ingress_events SET claim_token = ?, claim_owner = ?, claimed_at = ? WHERE event_id = ?",
          )
          .run("new-token-fictif", "new-owner-fictif", 300, claim.id);
        expect(reader.read(claim)).toBeNull();
        expect(reader.read({ id: claim.id, claim: { token: "new-token-fictif" } })).toEqual({
          id: claim.id,
          token: "new-token-fictif",
          ownerId: "new-owner-fictif",
          claimedAt: 300,
        });
      } finally {
        reader.dispose();
        peer.close();
      }
    });
  });

  it("refuses a row after a real release and completion", async () => {
    await withClaimFixture(async ({ queue, claim }) => {
      const reader = await prepareIdentity(queue);
      try {
        expect(await queue.release(claim)).toBe(true);
        expect(reader.read(claim)).toBeNull();
        const next = await queue.claim(claim.id);
        expect(next).not.toBeNull();
        if (!next) {
          throw new Error("Re-claim missing");
        }
        expect(reader.read(next)).not.toBeNull();
        expect(await queue.complete(next)).toBe(true);
        expect(reader.read(next)).toBeNull();
      } finally {
        reader.dispose();
      }
    });
  });

  it.each([-1, Number.MAX_SAFE_INTEGER + 1])(
    "closes on malformed claimedAt %s",
    async (claimedAt) => {
      await withClaimFixture(async ({ queue, claim, database }) => {
        const reader = await prepareIdentity(queue);
        try {
          // sqlite-allow-raw -- Inject source corruption into the real claimed row.
          database.db
            .prepare("UPDATE channel_ingress_events SET claimed_at = ? WHERE event_id = ?")
            .run(claimedAt, claim.id);
          expect(reader.read(claim)).toBeNull();
        } finally {
          reader.dispose();
        }
      });
    },
  );

  it("retains the valid claim when the real STRICT schema refuses fractional claimedAt", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      try {
        // sqlite-allow-raw -- The schema itself refuses this impossible stored corruption.
        expect(() =>
          database.db
            .prepare("UPDATE channel_ingress_events SET claimed_at = ? WHERE event_id = ?")
            .run(0.5, claim.id),
        ).toThrow(/REAL value in INTEGER column/);
        expect(reader.read(claim)).toEqual({ id: claim.id, ...claim.claim });
      } finally {
        reader.dispose();
      }
    });
  });

  it("does not reopen an existing physical database whose canonical owner is closed", async () => {
    await withClaimFixture(async ({ queue, claim, stateDir }) => {
      closeOpenClawStateDatabaseForTest();
      const files = fileState(stateDir);
      const reader = await prepareIdentity(queue);
      try {
        expect(reader.read(claim)).toBeNull();
        reader.dispose();
        expect(fileState(stateDir)).toEqual(files);
      } finally {
        reader.dispose();
      }
    });
  });

  it("keeps the original healthy owner when orderly close refuses an active borrower", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      try {
        expect(() => closeOpenClawStateDatabaseForTest()).toThrow(/active native borrowers/);
        expect(database.db.isOpen).toBe(true);
        expect(reader.read(claim)).not.toBeNull();
        reader.dispose();
        closeOpenClawStateDatabaseForTest();
        expect(database.db.isOpen).toBe(false);
      } finally {
        reader.dispose();
      }
    });
  });

  it("joins a real evicted retiring owner on dispose without adopting its successor", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      try {
        expect(openClawStateDatabaseCache.evictCachedOpenClawStateDatabase(database)).toBe(true);
        expect(database.db.isOpen).toBe(true);
        expect(reader.read(claim)).toBeNull();
        reader.dispose();
        expect(database.db.isOpen).toBe(false);
        openOpenClawStateDatabase({ path: database.path });
        expect(reader.read(claim)).toBeNull();
        const successor = await prepareIdentity(queue);
        try {
          expect(successor.read(claim)).not.toBeNull();
        } finally {
          successor.dispose();
        }
      } finally {
        reader.dispose();
      }
    });
  });

  it("closes when the prepared state-directory symlink is retargeted", async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-claim-alias-"));
    const first = path.join(root, "first");
    const second = path.join(root, "second");
    const alias = path.join(root, "alias");
    await fs.mkdir(first);
    await fs.mkdir(second);
    await fs.symlink(first, alias);
    const queue = createChannelIngressQueue({
      channelId: "sms",
      accountId: "fixture",
      stateDir: alias,
    });
    try {
      await queue.enqueue("event-fictif", { fictif: true });
      const claim = await queue.claim("event-fictif");
      if (!claim) {
        throw new Error("Fixture claim missing");
      }
      const reader = await prepareIdentity(queue);
      try {
        expect(reader.read(claim)).not.toBeNull();
        await fs.mkdir(path.join(second, "state"));
        await fs.copyFile(
          path.join(first, "state/openclaw.sqlite"),
          path.join(second, "state/openclaw.sqlite"),
        );
        await fs.unlink(alias);
        await fs.symlink(second, alias);
        expect(reader.read(claim)).toBeNull();
        await fs.unlink(alias);
        await fs.symlink(first, alias);
        expect(reader.read(claim)).toBeNull();
      } finally {
        reader.dispose();
      }
    } finally {
      closeOpenClawStateDatabaseForTest();
      await fs.rm(root, { recursive: true, force: true });
    }
  });

  it("closes permanently while an uncommitted native transaction is active", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      try {
        // sqlite-allow-raw -- Native transaction must never be credited as a committed claim observation.
        database.db.exec("BEGIN");
        expect(reader.read(claim)).toBeNull();
        database.db.exec("ROLLBACK");
        expect(reader.read(claim)).toBeNull();
      } finally {
        if (database.db.isTransaction) {
          database.db.exec("ROLLBACK");
        }
        reader.dispose();
      }
    });
  });

  it("closes on missing or replaced file identity and never re-adopts the old path", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      const hidden = database.path + ".fixture-original";
      try {
        await fs.rename(database.path, hidden);
        expect(reader.read(claim)).toBeNull();
        await fs.rename(hidden, database.path);
        expect(reader.read(claim)).toBeNull();
      } finally {
        reader.dispose();
      }
    });
  });

  it("closes on pathname inode replacement even when the original handle remains live", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const reader = await prepareIdentity(queue);
      const original = database.path + ".fixture-original";
      try {
        await fs.rename(database.path, original);
        await fs.copyFile(original, database.path);
        expect(reader.read(claim)).toBeNull();
        await fs.rm(database.path);
        await fs.rename(original, database.path);
        expect(reader.read(claim)).toBeNull();
      } finally {
        reader.dispose();
      }
    });
  });
});

const originSnapshots: Array<{ tables: number; sha256: string }> = [];
afterAll(() =>
  console.info(
    JSON.stringify({ kind: "OriginalC-native-read-census", snapshots: originSnapshots }),
  ),
);
function originCensus(database: ReturnType<typeof openOpenClawStateDatabase>) {
  // sqlite-allow-raw -- Independent dynamic census; no row values exported.
  const rows = database.db
    .prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
    .all()
    .map(({ name }) => {
      const table = String(name);
      return [
        table,
        database.db.prepare(`SELECT * FROM "${table.replaceAll('"', '""')}"`).all(),
      ] as const;
    });
  originSnapshots.push({
    tables: rows.length,
    sha256: createHash("sha256").update(JSON.stringify(rows)).digest("hex"),
  });
  return {
    tables: rows.length,
    hashes: Object.fromEntries(
      rows.map(([n, r]) => [n, createHash("sha256").update(JSON.stringify(r)).digest("hex")]),
    ),
    changes: database.db.prepare("SELECT total_changes() AS n").get()?.n,
    schema: database.db.prepare("PRAGMA schema_version").get()?.schema_version,
  };
}

describe("private native OriginalC snapshot", () => {
  it("reads exactly eight frozen detached fields from the open canonical claim without writes", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const ref = { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const before = originCensus(database);
      const first = readOwnNativeSmsClaimOrigin(queue, ref);
      expect(first).toMatchObject({
        accountId: "fixture",
        ...ref,
        claimedAt: 100,
        receivedAt: 100,
        payloadJson: '{"fictif":true}',
      });
      expect(Object.keys(first!).toSorted()).toEqual([
        "accountId",
        "claimedAt",
        "id",
        "ownerId",
        "payloadJson",
        "queueScope",
        "receivedAt",
        "token",
      ]);
      expect(Object.isFrozen(first)).toBe(true);
      expect(readOwnNativeSmsClaimOrigin(queue, ref)).not.toBe(first);
      for (const key of ["id", "token", "ownerId"] as const) {
        expect(readOwnNativeSmsClaimOrigin(queue, { ...ref, [key]: "foreign-fictif" })).toBeNull();
      }
      expect(originCensus(database)).toEqual(before);
    });
  });
  it("creates no missing state and reopens no closed canonical owner", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "origin-empty-fictif-"));
    try {
      const queue = createChannelIngressQueue({
        channelId: "sms",
        accountId: "fixture",
        stateDir: directory,
        access: "read-only",
      });
      expect(
        readOwnNativeSmsClaimOrigin(queue, { id: "fictif", token: "fictif", ownerId: "fictif" }),
      ).toBeNull();
      expect(await fs.readdir(directory)).toEqual([]);
    } finally {
      await fs.rm(directory, { recursive: true, force: true });
    }
    await withClaimFixture(async ({ queue, claim, stateDir }) => {
      closeOpenClawStateDatabaseForTest();
      const files = fileState(stateDir);
      expect(
        readOwnNativeSmsClaimOrigin(queue, {
          id: claim.id,
          token: claim.claim.token,
          ownerId: claim.claim.ownerId,
        }),
      ).toBeNull();
      expect(fileState(stateDir)).toEqual(files);
    });
  });
  it("refuses unknown queue and claim proxies without traps", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const ref = { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const before = originCensus(database);
      const trap = vi.fn(() => {
        throw new Error("fictif-trap");
      });
      const handler = {
        get: trap,
        ownKeys: trap,
        getOwnPropertyDescriptor: trap,
        getPrototypeOf: trap,
      };
      expect(readOwnNativeSmsClaimOrigin(new Proxy(queue, handler), ref)).toBeNull();
      expect(readOwnNativeSmsClaimOrigin({ ...queue }, ref)).toBeNull();
      expect(readOwnNativeSmsClaimOrigin(queue, new Proxy(ref, handler))).toBeNull();
      const revoked = Proxy.revocable(ref, handler);
      revoked.revoke();
      expect(readOwnNativeSmsClaimOrigin(queue, revoked.proxy)).toBeNull();
      expect(trap).not.toHaveBeenCalled();
      expect(originCensus(database)).toEqual(before);
    });
  });
  it("uses actual single and double managed views and closes both on owner disposal", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const ref = { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const a = new PluginInstance("origin-inner-fictif");
      const b = new PluginInstance("origin-outer-fictif");
      try {
        const view = a.wrap({ open: () => queue }).open();
        const outer = b.wrap({ open: () => view }).open();
        const before = originCensus(database);
        expect(readOwnNativeSmsClaimOrigin(view, ref)).not.toBeNull();
        expect(readOwnNativeSmsClaimOrigin(outer, ref)).not.toBeNull();
        await a.dispose();
        expect(readOwnNativeSmsClaimOrigin(view, ref)).toBeNull();
        expect(readOwnNativeSmsClaimOrigin(outer, ref)).toBeNull();
        expect(originCensus(database)).toEqual(before);
      } finally {
        await b.dispose();
        await a.dispose();
      }
    });
  });
  it("refuses transactional snapshots and observes real peer replacement of origin", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const ref = { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const before = originCensus(database);
      // sqlite-allow-raw -- Actual transaction, then real WAL peer source alteration.
      database.db.exec("BEGIN");
      expect(readOwnNativeSmsClaimOrigin(queue, ref)).toBeNull();
      database.db.exec("ROLLBACK");
      expect(originCensus(database)).toEqual(before);
      const peer = openNodeSqliteDatabase(database.path);
      try {
        peer
          .prepare(
            "UPDATE channel_ingress_events SET payload_json=?, received_at=? WHERE event_id=?",
          )
          .run('{"fictif":"new"}', 200, claim.id);
        expect(readOwnNativeSmsClaimOrigin(queue, ref)).toMatchObject({
          payloadJson: '{"fictif":"new"}',
          receivedAt: 200,
        });
      } finally {
        peer.close();
      }
    });
  });
  it("bounds actual SQL text by UTF8 bytes, including the exact limit", async () => {
    await withClaimFixture(async ({ queue, claim, database }) => {
      const ref = { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId };
      // sqlite-allow-raw -- Corrupt raw fixture text; reader snapshots raw text, codec validation is upstream.
      database.db
        .prepare("UPDATE channel_ingress_events SET payload_json=? WHERE event_id=?")
        .run("😀".repeat(65536), claim.id);
      let before = originCensus(database);
      expect(readOwnNativeSmsClaimOrigin(queue, ref)?.payloadJson).toHaveLength(131072);
      expect(originCensus(database)).toEqual(before);
      database.db
        .prepare("UPDATE channel_ingress_events SET payload_json=? WHERE event_id=?")
        .run("😀".repeat(65537), claim.id);
      before = originCensus(database);
      expect(readOwnNativeSmsClaimOrigin(queue, ref)).toBeNull();
      expect(originCensus(database)).toEqual(before);
    });
  });
});
