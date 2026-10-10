import { createHash } from "node:crypto";
// Fictitious native SQLite rows; these tests do not claim RPC, SMS or provider delivery.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import * as publications from "../../infra/sqlite-post-commit.js";
import { PluginInstance } from "../../plugins/plugin-instance.js";
import * as stateDatabases from "../../state/openclaw-state-db.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../../state/openclaw-state-db.js";
import * as queues from "./ingress-queue.js";

async function nativeFixture(run: (stateDir: string) => Promise<void>) {
  const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "fictif-native-completion-"));
  try {
    await run(stateDir);
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(stateDir, { recursive: true, force: true });
  }
}

describe("private native completion evidence", () => {
  it("wraps a non-SMS callable without opening a state database", async () => {
    const instance = new PluginInstance("fictif-non-sms");
    const opened = vi.spyOn(stateDatabases, "openOpenClawStateDatabase");
    try {
      const view = instance.wrap({ echo: (value: string) => value });
      expect(view.echo("FICTIF")).toBe("FICTIF");
      expect(opened).not.toHaveBeenCalled();
    } finally {
      opened.mockRestore();
      await instance.dispose();
    }
  });
  it("does not execute malformed reference getters or Proxy traps", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "0".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "0".repeat(32), { ownerId: "fictif-owner" }))!;
      let reads = 0;
      const bad = {
        get id() {
          reads += 1;
          return claim.id;
        },
        token: claim.claim.token,
        ownerId: claim.claim.ownerId,
      };
      expect(queues.prepareOwnNativeCompletion(queue, bad, {}, {})).toBeNull();
      const proxy = new Proxy(
        { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
        {
          getPrototypeOf() {
            reads += 1;
            throw new Error("fictif trap");
          },
        },
      );
      expect(queues.prepareOwnNativeCompletion(queue, proxy, {}, {})).toBeNull();
      expect(reads).toBe(0);
      const readonly = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
        access: "read-only",
      });
      expect(
        queues.prepareOwnNativeCompletion(
          readonly,
          { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
          {},
          {},
        ),
      ).toBeNull();
    });
  });
  it("refuses fake queues and clones even when a real native claim exists", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "1".repeat(32), { fictif: true });
      const claim = await queue.claim("SM" + "1".repeat(32), { ownerId: "fictif-owner" });
      expect(claim).not.toBeNull();
      const ref = { id: claim!.id, token: claim!.claim.token, ownerId: claim!.claim.ownerId };
      expect((await queue.listClaims()).length).toBe(1);
      expect(typeof queues.prepareOwnNativeCompletion).toBe("function");
      expect(queues.prepareOwnNativeCompletion({ ...queue }, ref, {}, {})).toBeNull();
      expect(
        queues.prepareOwnNativeCompletion({ complete: async () => true }, ref, {}, {}),
      ).toBeNull();
      let traps = 0;
      const proxy = new Proxy(queue, {
        get() {
          traps += 1;
          throw new Error("fictif trap");
        },
      });
      expect(queues.prepareOwnNativeCompletion(proxy, ref, {}, {})).toBeNull();
      expect(traps).toBe(0);
      expect((await queue.listClaims()).length).toBe(1);
    });
  });

  it("uses the captured writer and consumes only the same own committed receipt", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "2".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "2".repeat(32), { ownerId: "fictif-owner" }))!;
      const source = {},
        lifecycle = {};
      const permit = queues.prepareOwnNativeCompletion(
        queue,
        {
          id: claim.id,
          token: claim.claim.token,
          ownerId: claim.claim.ownerId,
        },
        source,
        lifecycle,
      );
      expect(permit).not.toBeNull();
      queue.complete = async () => {
        throw new Error("replaceable writer must not run");
      };
      const receipt = await queues.completeOwnNativeClaim(permit!);
      expect(Object.keys(receipt)).toEqual([]);
      expect((await queue.listClaims()).length).toBe(0);
      expect(() =>
        queues.consumeOwnNativeCompletionReceipt(permit!, {}, source, lifecycle),
      ).toThrow();
      expect(() =>
        queues.consumeOwnNativeCompletionReceipt(permit!, receipt, {}, lifecycle),
      ).toThrow();
      expect(() =>
        queues.consumeOwnNativeCompletionReceipt(permit!, receipt, source, {}),
      ).toThrow();
      queues.consumeOwnNativeCompletionReceipt(permit!, receipt, source, lifecycle);
      expect(() =>
        queues.consumeOwnNativeCompletionReceipt(permit!, receipt, source, lifecycle),
      ).toThrow();
      expect((await queue.enqueue(claim.id, { fictif: true })).kind).toBe("completed");
    });
  });

  it("fences a changed SQL owner without changing the legacy token contract", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "3".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "3".repeat(32), { ownerId: "fictif-owner" }))!;
      const permit = queues.prepareOwnNativeCompletion(
        queue,
        {
          id: claim.id,
          token: claim.claim.token,
          ownerId: claim.claim.ownerId,
        },
        {},
        {},
      );
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      db.prepare("UPDATE channel_ingress_events SET claim_owner = ? WHERE event_id = ?").run(
        "fictif-other",
        claim.id,
      );
      await expect(queues.completeOwnNativeClaim(permit!)).rejects.toThrow();
      expect((await queue.listClaims()).length).toBe(1);
      expect(await queue.complete(claim)).toBe(true);
    });
  });

  it("rejects a pre-existing transaction before selected completion writes", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "4".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "4".repeat(32), { ownerId: "fictif-owner" }))!;
      const permit = queues.prepareOwnNativeCompletion(
        queue,
        {
          id: claim.id,
          token: claim.claim.token,
          ownerId: claim.claim.ownerId,
        },
        {},
        {},
      );
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      db.exec("BEGIN IMMEDIATE");
      try {
        await expect(queues.completeOwnNativeClaim(permit!)).rejects.toThrow();
        expect(
          db.prepare("SELECT status FROM channel_ingress_events WHERE event_id = ?").get(claim.id),
        ).toEqual({ status: "claimed" });
      } finally {
        db.exec("ROLLBACK");
      }
    });
  });

  it("rolls the actual private UPDATE back on SQL failure without a receipt", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "6".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "6".repeat(32), { ownerId: "fictif-owner" }))!;
      const permit = queues.prepareOwnNativeCompletion(
        queue,
        { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
        {},
        {},
      );
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      db.exec(
        "CREATE TRIGGER fictif_rollback BEFORE UPDATE OF status ON channel_ingress_events WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'FICTIF rollback'); END",
      );
      const before = createHash("sha256")
        .update(JSON.stringify(db.prepare("SELECT * FROM channel_ingress_events").all()))
        .digest("hex");
      await expect(queues.completeOwnNativeClaim(permit!)).rejects.toThrow();
      const after = createHash("sha256")
        .update(JSON.stringify(db.prepare("SELECT * FROM channel_ingress_events").all()))
        .digest("hex");
      expect(after).toBe(before);
      expect((await queue.listClaims()).length).toBe(1);
    });
  });

  it("never returns a receipt from an awaited write rejected after actual COMMIT", async () => {
    await nativeFixture(async (stateDir) => {
      const queue = queues.createChannelIngressQueue({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      await queue.enqueue("SM" + "7".repeat(32), { fictif: true });
      const claim = (await queue.claim("SM" + "7".repeat(32), { ownerId: "fictif-owner" }))!;
      const permit = queues.prepareOwnNativeCompletion(
        queue,
        { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
        {},
        {},
      );
      const stage = publications.stageSqliteTransactionState;
      const observer = vi
        .spyOn(publications, "stageSqliteTransactionState")
        .mockImplementation((db, state) =>
          stage(db, {
            ...state,
            prepareObservers: () => {
              throw new Error("FICTIF postcommit observer");
            },
          }),
        );
      try {
        await expect(queues.completeOwnNativeClaim(permit!)).rejects.toThrow(
          "FICTIF postcommit observer",
        );
        expect((await queue.enqueue(claim.id, { fictif: true })).kind).toBe("completed");
      } finally {
        observer.mockRestore();
      }
    });
  });
});
