import { createHash } from "node:crypto";
import { getEventListeners } from "node:events";
// Fictitious GateReceived/C/P/receipt fixtures with actual native SQLite claims.
// No RPC, Host manager, ContextAdmission consumer, HMAC or provider qualification.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { DatabaseSync } from "node:sqlite";
import { describe, expect, it, vi } from "vitest";
import { validateSmsCommand } from "../../agents/opsys-runtime-sms-contract.js";
import * as publications from "../../infra/sqlite-post-commit.js";
import { PluginInstance } from "../../plugins/plugin-instance.js";
import { createEmptyPluginRegistry } from "../../plugins/registry-empty.js";
import { createPluginRecord } from "../../plugins/status.test-helpers.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../../state/openclaw-state-db.js";
import type { ChannelIngressDispatchLifecycle } from "./ingress-drain-lifecycle.js";
import { createChannelIngressDrain } from "./ingress-drain.js";
import {
  createChannelIngressQueue,
  completeOwnNativeClaim,
  type ChannelIngressQueue,
} from "./ingress-queue.js";
import * as cells from "./opsys-sms-source.js";

const SID = "SM" + "5".repeat(32);
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
function binding(accountId = "default") {
  const command = validateSmsCommand(
    {
      version: 1,
      commande: {
        canal: "sms",
        provider: "twilio",
        compte_id: accountId,
        account_sid: "AC" + "1".repeat(32),
        message_sid: SID,
        expediteur: "+15145550101",
        destinataire: "+15145550102",
        recu_le: new Date(TIME).toISOString(),
        texte: "SMS FICTIF",
        session_key: "agent:opsys-agent-demo:sms:direct:+15145550101",
        agent_id: "opsys-agent-demo",
        preuve_sha256: "a".repeat(64),
      },
      permission: {
        profil_id: "demo",
        revision_profil: 1,
        outil_m1: "opsys_m1__m1_recevoir_message_canal",
      },
    },
    "opsys_runtime_recevoir_sms",
  );
  return {
    status: "received" as const,
    command,
    receivedAt: TIME,
    destinationSha256: "b".repeat(64),
    receipt: {
      source: "sms:twilio",
      compte_id: accountId,
      account_sid: command.commande.account_sid,
      message_sid: SID,
      agent_id: "opsys-agent-demo",
      session_key: command.commande.session_key,
      signal_id: "sms:" + SID,
      signal_ligne_id: "c".repeat(64),
      decision: "DEMANDER_PRECISIONS" as const,
      lead_ligne_id: null,
      transfert_id: null,
    },
  };
}
const SCOPE = Object.freeze({
  agentId: "opsys-agent-demo",
  sessionKey: "agent:opsys-agent-demo:sms:direct:+15145550101",
  accountId: "default",
  sender: "+15145550101",
  messageSid: SID,
});

async function fixture(run: (stateDir: string) => Promise<void>) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "fictif-sms-source-"));
  try {
    await run(dir);
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(dir, { recursive: true, force: true });
  }
}

async function arm(
  queue: ChannelIngressQueue<{ fictif: boolean }>,
  options: {
    host?: () => void;
    claimCurrent?: () => void;
    controller?: AbortController;
    preAdoptionController?: AbortController;
  } = {},
) {
  await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
  const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
  const ref = { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId };
  const preAdoptionController = options.preAdoptionController ?? new AbortController();
  const lifecycleOwner = {};
  const lifecycle = cells.registerNativeSmsClaimLifecycle(
    queue,
    ref,
    lifecycleOwner,
    preAdoptionController.signal,
  )!;
  const controller = options.controller ?? new AbortController();
  const source = cells.armNativeSmsSource({
    queue,
    claim: ref,
    received: binding(),
    scope: SCOPE,
    assertHostAndRouteCurrent: options.host ?? (() => {}),
    assertClaimCurrent: options.claimCurrent ?? (() => {}),
    signal: controller.signal,
  });
  const permit = cells.readNativeSmsCompletionPermit(lifecycle)!;
  return { claim, lifecycle, lifecycleOwner, source, permit, controller, preAdoptionController };
}

function census(db: DatabaseSync) {
  const hashes: Record<string, string> = {};
  for (const row of db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all()) {
    const name = String(row.name);
    hashes[name] = createHash("sha256")
      .update(
        JSON.stringify(
          db
            .prepare('SELECT * FROM "' + name.replaceAll('"', '""') + '"')
            .all()
            .map((record) => JSON.stringify(record))
            .toSorted(),
        ),
      )
      .digest("hex");
  }
  return hashes;
}

async function selectedDrain(
  stateDir: string,
  options: {
    kind?: "deferred" | "completed";
    host?: () => void;
    log?: (message: string) => void;
    controller?: AbortController;
  } = {},
) {
  const queue = createChannelIngressQueue<{ fictif: boolean }>({
    channelId: "sms",
    accountId: "default",
    stateDir,
  });
  await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
  const controller = options.controller ?? new AbortController();
  let source!: object;
  let lifecycle!: ChannelIngressDispatchLifecycle;
  const drain = createChannelIngressDrain({
    queue,
    onLog: options.log,
    dispatchClaimedEvent: (claim, current) => {
      lifecycle = current;
      source = cells.armNativeSmsSource({
        queue,
        claim: { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
        received: binding(),
        scope: SCOPE,
        assertHostAndRouteCurrent: options.host ?? (() => {}),
        assertClaimCurrent: () => {},
        signal: controller.signal,
      });
      return { kind: options.kind ?? "deferred" };
    },
  });
  await drain.drainOnce();
  await drain.waitForIdle();
  return {
    queue,
    drain,
    controller,
    get source() {
      return source;
    },
    get lifecycle() {
      return lifecycle;
    },
  };
}

describe("private SMS Source prebind and own adoption", () => {
  it.each(
    (["inner", "outer"] as const).flatMap((side) =>
      (["revoked", "disposed", "aborted", "replaced"] as const).map((loss) => ({ side, loss })),
    ),
  )(
    "refuses $side $loss view owner before SQL and keeps that loss terminal",
    async ({ side, loss }) => {
      await fixture(async (stateDir) => {
        const native = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        const registry = createEmptyPluginRegistry();
        const a = createPluginRecord({ id: "fictif-first" }),
          b = createPluginRecord({ id: "fictif-second" });
        registry.plugins.push(a, b);
        const first = new PluginInstance(a.id, { record: a, registry });
        const second = new PluginInstance(b.id, { record: b, registry });
        const queue = second.wrap({ open: () => first.wrap({ open: () => native }).open() }).open();
        try {
          const current = await arm(queue);
          const selected = side === "inner" ? first : second;
          const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
          const before = census(db);
          if (loss === "revoked") {
            selected.owner!.revoked = true;
          }
          if (loss === "disposed") {
            await selected.dispose();
          }
          if (loss === "aborted") {
            selected.controller.abort();
          }
          if (loss === "replaced") {
            selected.owner!.instance = undefined;
          }
          await expect(completeOwnNativeClaim(current.permit)).rejects.toThrow();
          expect(() => cells.readSmsSourceScope(current.source)).toThrow();
          expect(() => cells.readSmsSourceAssertion(current.source)()).toThrow();
          expect(census(db)).toEqual(before);
          if (loss === "revoked") {
            selected.owner!.revoked = false;
          }
          if (loss === "replaced") {
            selected.owner!.instance = selected;
          }
          await expect(completeOwnNativeClaim(current.permit)).rejects.toThrow();
          expect(census(db)).toEqual(before);
        } finally {
          await second.dispose();
          await first.dispose();
        }
      });
    },
  );

  it.each(["inner", "outer"])(
    "closes an ADOPTED assertion when the %s owner is retired without reading a claim",
    async (side) => {
      await fixture(async (stateDir) => {
        const native = createChannelIngressQueue({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        await native.enqueue(SID, { fictif: true }, { receivedAt: TIME });
        const first = new PluginInstance("fictif-first"),
          second = new PluginInstance("fictif-second");
        const queue = second.wrap({ open: () => first.wrap({ open: () => native }).open() }).open();
        let source!: object;
        let lifecycle!: ChannelIngressDispatchLifecycle;
        const drain = createChannelIngressDrain({
          queue,
          dispatchClaimedEvent: (claim, current) => {
            lifecycle = current;
            source = cells.armNativeSmsSource({
              queue,
              claim: { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId },
              received: binding(),
              scope: SCOPE,
              assertHostAndRouteCurrent: () => {},
              assertClaimCurrent: () => {},
              signal: current.abortSignal,
            });
            return { kind: "deferred" };
          },
        });
        try {
          await drain.drainOnce();
          await drain.waitForIdle();
          await lifecycle.onAdopted();
          const assertion = cells.readSmsSourceAssertion(source);
          assertion();
          const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
          const before = census(db);
          await (side === "inner" ? first : second).dispose();
          expect(() => assertion()).toThrow();
          expect(() => cells.readSmsSourceScope(source)).toThrow();
          expect(census(db)).toEqual(before);
        } finally {
          drain.dispose();
          await second.dispose();
          await first.dispose();
        }
      });
    },
  );

  it.each([1, 2])(
    "retains native queue identity through %i actual PluginInstance membranes",
    async (layers) => {
      await fixture(async (stateDir) => {
        const native = createChannelIngressQueue({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        await native.enqueue(SID, { fictif: true }, { receivedAt: TIME });
        const first = new PluginInstance("fictif-sms-first");
        const second = new PluginInstance("fictif-sms-second");
        const one = first.wrap({ open: () => native }).open();
        const queue = layers === 1 ? one : second.wrap({ open: () => one }).open();
        let source: object | undefined;
        let failure: unknown;
        let lifecycle!: ChannelIngressDispatchLifecycle;
        const drain = createChannelIngressDrain({
          queue,
          dispatchClaimedEvent: (claim, current) => {
            lifecycle = current;
            try {
              source = cells.armNativeSmsSource({
                queue,
                claim: { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
                received: binding(),
                scope: SCOPE,
                assertHostAndRouteCurrent: () => {},
                assertClaimCurrent: () => {},
                signal: current.abortSignal,
              });
            } catch (error) {
              failure = error;
            }
            return { kind: "deferred" };
          },
        });
        try {
          await drain.drainOnce();
          await drain.waitForIdle();
          expect(failure).toBeUndefined();
          expect(source).toBeDefined();
          await lifecycle.onAdopted();
          expect(cells.readSmsSourceScope(source)).toEqual(SCOPE);
          cells.readSmsSourceAssertion(source)();
        } finally {
          drain.dispose();
          await second.dispose();
          await first.dispose();
        }
      });
    },
  );

  it("does not let an ADOPTED assertion pass after Host guard disposes reentrantly", async () => {
    await fixture(async (stateDir) => {
      let reenter = () => {};
      const selected = await selectedDrain(stateDir, { host: () => reenter() });
      try {
        await selected.lifecycle.onAdopted();
        const assertion = cells.readSmsSourceAssertion(selected.source);
        reenter = () => cells.disposeSmsSource(selected.source);
        expect(() => assertion()).toThrow();
        expect(() => cells.readSmsSourceScope(selected.source)).toThrow();
      } finally {
        selected.drain.dispose();
      }
    });
  });

  it("does not return ARMED scope after claim guard disposes reentrantly", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue<{ fictif: boolean }>({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      let reenter = () => {};
      const current = await arm(queue, { claimCurrent: () => reenter() });
      reenter = () => cells.disposeSmsSource(current.source);
      expect(() => cells.readSmsSourceScope(current.source)).toThrow();
      expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
    });
  });

  it.each(["unknown", "foreign_receipt", "command_hash", "time", "decision", "getter"])(
    "rejects %s Gate binding without changing any native table",
    async (which) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        await queue.enqueue(SID, { fictif: true });
        const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
        const ref = { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId };
        expect(
          cells.registerNativeSmsClaimLifecycle(queue, ref, {}, new AbortController().signal),
        ).toBeDefined();
        const original = binding();
        let received: unknown = original;
        let getters = 0;
        if (which === "unknown") {
          received = { ...original, status: "unknown" };
        }
        if (which === "foreign_receipt") {
          received = {
            ...original,
            receipt: { ...original.receipt, message_sid: "SM" + "6".repeat(32) },
          };
        }
        if (which === "command_hash") {
          received = {
            ...original,
            command: { ...original.command, commande_sha256: "d".repeat(64) },
          };
        }
        if (which === "time") {
          received = { ...original, receivedAt: TIME + 1 };
        }
        if (which === "decision") {
          received = { ...original, receipt: { ...original.receipt, decision: "NONE" } };
        }
        if (which === "getter") {
          received = {
            ...original,
            get receipt() {
              getters += 1;
              return original.receipt;
            },
          };
        }
        const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
        const before = census(db);
        expect(() =>
          Reflect.apply(cells.armNativeSmsSource, undefined, [
            {
              queue,
              claim: ref,
              received,
              scope: SCOPE,
              assertHostAndRouteCurrent: () => {},
              assertClaimCurrent: () => {},
              signal: new AbortController().signal,
            },
          ]),
        ).toThrow();
        expect(getters).toBe(0);
        expect(census(db)).toEqual(before);
      });
    },
  );

  it("coalesces reentrant adoption during the real UPDATE and changes exactly one native table", async () => {
    await fixture(async (stateDir) => {
      const selected = await selectedDrain(stateDir);
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      let completions = 0;
      let joined: Promise<void> | undefined;
      db.function("fictif_adopt_reentrant", () => {
        completions += 1;
        joined = selected.lifecycle.onAdopted();
        expect(() => cells.readSmsSourceAssertion(selected.source)()).toThrow();
        return 0;
      });
      db.exec(
        "CREATE TRIGGER fictif_observe BEFORE UPDATE OF status ON channel_ingress_events WHEN NEW.status='completed' BEGIN SELECT fictif_adopt_reentrant(); END",
      );
      const before = census(db);
      try {
        const first = selected.lifecycle.onAdopted();
        await first;
        expect(joined).toBe(first);
        await joined;
        await selected.lifecycle.onAdopted();
        expect(completions).toBe(1);
        cells.readSmsSourceAssertion(selected.source)();
        const after = census(db);
        expect(Object.keys(after)).toEqual(Object.keys(before));
        expect(Object.keys(before).filter((name) => before[name] !== after[name])).toEqual([
          "channel_ingress_events",
        ]);
        console.info(
          "native-source-census",
          Object.keys(before).length,
          "tables; changed exactly channel_ingress_events",
        );
      } finally {
        selected.drain.dispose();
      }
    });
  });

  it("does not adopt when its await joins a pending real release", async () => {
    await fixture(async (stateDir) => {
      const selected = await selectedDrain(stateDir);
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      let unblock!: () => void;
      const waiting = new Promise<void>((resolve) => {
        unblock = resolve;
      });
      const release = selected.queue.release;
      selected.queue.release = async (...args) => {
        await waiting;
        return release(...args);
      };
      let completions = 0;
      db.function("fictif_complete", () => {
        completions += 1;
        return 0;
      });
      db.exec(
        "CREATE TRIGGER fictif_observe BEFORE UPDATE OF status ON channel_ingress_events WHEN NEW.status='completed' BEGIN SELECT fictif_complete(); END",
      );
      try {
        const cancellation = selected.lifecycle.onCancelled!();
        const adoption = selected.lifecycle.onAdopted();
        const rejected = expect(adoption).rejects.toThrow("reclaimed");
        unblock();
        await cancellation;
        await rejected;
        expect(selected.lifecycle.onAdopted()).toBe(adoption);
        await expect(adoption).rejects.toThrow("reclaimed");
        expect(completions).toBe(0);
        expect((await selected.queue.listPending())[0]?.payload).toEqual({ fictif: true });
        expect(() => cells.readSmsSourceScope(selected.source)).toThrow();
      } finally {
        unblock();
        selected.drain.dispose();
      }
    });
  });

  it("adopts through the default completed result only after the same native writer succeeds", async () => {
    await fixture(async (stateDir) => {
      const selected = await selectedDrain(stateDir, { kind: "completed" });
      try {
        expect((await selected.queue.enqueue(SID, { fictif: true })).kind).toBe("completed");
        expect(cells.readSmsSourceScope(selected.source)).toEqual(SCOPE);
        cells.readSmsSourceAssertion(selected.source)();
        await selected.lifecycle.onAdopted();
      } finally {
        selected.drain.dispose();
      }
    });
  });

  it("does not promote Source when own completion rejects after actual SQL COMMIT", async () => {
    await fixture(async (stateDir) => {
      const selected = await selectedDrain(stateDir);
      const stage = publications.stageSqliteTransactionState;
      const observer = vi
        .spyOn(publications, "stageSqliteTransactionState")
        .mockImplementation((db, state) =>
          stage(db, {
            ...state,
            prepareObservers: () => {
              throw new Error("FICTIF observer failure");
            },
          }),
        );
      try {
        const first = selected.lifecycle.onAdopted();
        await expect(first).rejects.toThrow();
        expect((await selected.queue.enqueue(SID, { fictif: true })).kind).toBe("completed");
        expect(selected.lifecycle.onAdopted()).toBe(first);
        await expect(first).rejects.toThrow();
        expect(() => cells.readSmsSourceScope(selected.source)).toThrow();
        expect(() => cells.readSmsSourceAssertion(selected.source)()).toThrow();
      } finally {
        observer.mockRestore();
        selected.drain.dispose();
      }
    });
  });

  it("checks current Host again on retry and holds the unchanged claim after loss", async () => {
    await fixture(async (stateDir) => {
      let live = true;
      let retries = 0;
      const selected = await selectedDrain(stateDir, {
        host: () => {
          if (!live) {
            throw new Error("FICTIF stale Host");
          }
        },
        log: (message) => {
          if (message.startsWith("completion retry")) {
            live = false;
            retries += 1;
          }
        },
      });
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      db.exec(
        "CREATE TRIGGER fictif_rollback BEFORE UPDATE OF status ON channel_ingress_events WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'FICTIF retry'); END",
      );
      const before = census(db);
      try {
        const adoption = selected.lifecycle.onAdopted();
        await expect(adoption).rejects.toThrow();
        expect(retries).toBe(1);
        expect(census(db)).toEqual(before);
        expect((await selected.queue.listClaims())[0]?.payload).toEqual({ fictif: true });
        expect(selected.lifecycle.onAdopted()).toBe(adoption);
        expect(() => cells.readSmsSourceScope(selected.source)).toThrow();
      } finally {
        selected.drain.dispose();
      }
    });
  });

  it.each(["dispose", "abort"])(
    "revokes a captured native permit on %s before SQL",
    async (method) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        const current = await arm(queue);
        const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
        const before = db
          .prepare("SELECT status,payload_json,claim_token,claim_owner FROM channel_ingress_events")
          .all();
        if (method === "dispose") {
          cells.disposeSmsSource(current.source);
        } else {
          current.controller.abort();
        }
        await expect(completeOwnNativeClaim(current.permit)).rejects.toThrow();
        expect(
          db
            .prepare(
              "SELECT status,payload_json,claim_token,claim_owner FROM channel_ingress_events",
            )
            .all(),
        ).toEqual(before);
        expect(() => cells.readSmsSourceScope(current.source)).toThrow();
      });
    },
  );

  it.each(["host", "claim"])(
    "rechecks the captured %s authority at use after the permit was read",
    async (which) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        let current = true;
        const guard = () => {
          if (!current) {
            throw new Error("FICTIF stale authority");
          }
        };
        const armed = await arm(
          queue,
          which === "host" ? { host: guard } : { claimCurrent: guard },
        );
        current = false;
        await expect(completeOwnNativeClaim(armed.permit)).rejects.toThrow();
        expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
        expect(() => cells.readSmsSourceScope(armed.source)).toThrow();
      });
    },
  );

  it("rejects a consistent command/receipt/scope B against the private native account A", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
      await queue.enqueue(SID, { fictif: true });
      const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
      const ref = { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const lifecycle = cells.registerNativeSmsClaimLifecycle(
        queue,
        ref,
        {},
        new AbortController().signal,
      )!;
      expect(lifecycle).toBeDefined();
      expect(() =>
        cells.armNativeSmsSource({
          queue,
          claim: ref,
          received: binding("other"),
          scope: { ...SCOPE, accountId: "other" },
          assertHostAndRouteCurrent: () => {},
          assertClaimCurrent: () => {},
          signal: new AbortController().signal,
        }),
      ).toThrow();
      expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
    });
  });

  it("rechecks revocation after the native clock callback and before SQL", async () => {
    await fixture(async (stateDir) => {
      let reenter = () => {};
      const queue = createChannelIngressQueue<{ fictif: boolean }>({
        channelId: "sms",
        accountId: "default",
        stateDir,
        now: () => {
          reenter();
          return TIME;
        },
      });
      const armed = await arm(queue);
      reenter = () => cells.disposeSmsSource(armed.source);
      await expect(completeOwnNativeClaim(armed.permit)).rejects.toThrow();
      reenter = () => {};
      expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
    });
  });

  it("allows current ARMED scope but grants only after its native own awaited commit", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
      await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
      const source = await import("./opsys-sms-source.js");
      const reader = await queue.prepareClaimIdentityReader!();
      let handle!: object;
      let original!: { token: string; ownerId: string };
      let lifecycle!: Parameters<
        Parameters<typeof createChannelIngressDrain>[0]["dispatchClaimedEvent"]
      >[1];
      const host = vi.fn();
      const claimCheck = vi.fn(() => {
        const current = reader.read({ id: SID, claim: { token: original.token } });
        expect(current?.token).toBe(original.token);
        expect(current?.ownerId).toBe(original.ownerId);
      });
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (claim, current) => {
          lifecycle = current;
          original = { token: claim.claim.token, ownerId: claim.claim.ownerId };
          handle = source.armNativeSmsSource({
            queue,
            claim: { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
            received: binding(),
            scope: SCOPE,
            assertHostAndRouteCurrent: host,
            assertClaimCurrent: claimCheck,
            signal: current.abortSignal,
          });
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const scope = source.readSmsSourceScope(handle);
        const assertion = source.readSmsSourceAssertion(handle);
        expect(scope).toEqual(SCOPE);
        expect(source.readSmsSourceScope(handle)).toBe(scope);
        expect(source.readSmsSourceAssertion(handle)).toBe(assertion);
        expect(() => assertion()).toThrow();
        queue.complete = async () => {
          throw new Error("fake property must not become native evidence");
        };
        await lifecycle.onAdopted();
        const checks = claimCheck.mock.calls.length;
        expect((await queue.listClaims()).length).toBe(0);
        expect(source.readSmsSourceScope(handle)).toBe(scope);
        assertion();
        expect(claimCheck.mock.calls.length).toBe(checks);
        await lifecycle.onAdopted();
        source.disposeSmsSource(handle);
        expect(() => source.readSmsSourceScope(handle)).toThrow();
        expect(() => assertion()).toThrow();
      } finally {
        reader.dispose();
        drain.dispose();
      }
    });
  });

  it("cannot arm a Source from a clone even while the real SQLite claim is current", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
      await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
      const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
      const source = await import("./opsys-sms-source.js");
      const fake = { ...queue, complete: async () => true };
      const lifecycle = {};
      expect(
        source.registerNativeSmsClaimLifecycle(
          fake,
          { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId },
          lifecycle,
          new AbortController().signal,
        ),
      ).toBeUndefined();
      expect(() =>
        source.armNativeSmsSource({
          queue: fake,
          claim: { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId },
          received: binding(),
          scope: SCOPE,
          assertHostAndRouteCurrent: () => {},
          assertClaimCurrent: () => {},
          signal: new AbortController().signal,
        }),
      ).toThrow();
      expect((await queue.listClaims()).length).toBe(1);
    });
  });
});

describe("native pre-adoption signal is separate from Host authority", () => {
  it.each(["missing", "invalid", "fake_brand", "proxy", "aborted"])(
    "refuses %s registration without listeners or native table changes",
    async (kind) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
        const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
        const ref = { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId };
        const controller = new AbortController();
        let traps = 0;
        const signals: Record<string, unknown> = {
          missing: undefined,
          invalid: {},
          fake_brand: Object.create(AbortSignal.prototype),
          proxy: new Proxy(controller.signal, {
            get: () => {
              traps += 1;
              return undefined;
            },
            getPrototypeOf: () => {
              traps += 1;
              return null;
            },
          }),
          aborted: controller.signal,
        };
        if (kind === "aborted") {
          controller.abort();
        }
        const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
        const before = census(db);
        expect(
          Reflect.apply(cells.registerNativeSmsClaimLifecycle, undefined, [
            queue,
            ref,
            {},
            signals[kind],
          ]),
        ).toBeUndefined();
        expect(getEventListeners(controller.signal, "abort")).toHaveLength(0);
        expect(traps).toBe(0);
        expect(census(db)).toEqual(before);
        expect(() =>
          cells.armNativeSmsSource({
            queue,
            claim: ref,
            received: binding(),
            scope: SCOPE,
            assertHostAndRouteCurrent: () => {},
            assertClaimCurrent: () => {},
            signal: new AbortController().signal,
          }),
        ).toThrow("REJ-M1-SMS-SOURCE-NON-COURANTE");
      });
    },
  );

  it("closes a registered lifecycle before arm and removes its native listener", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
      await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
      const claim = (await queue.claim(SID, { ownerId: "fictif-owner" }))!;
      const ref = { id: SID, token: claim.claim.token, ownerId: claim.claim.ownerId };
      const pre = new AbortController();
      const lifecycle = cells.registerNativeSmsClaimLifecycle(queue, ref, {}, pre.signal)!;
      expect(lifecycle).toBeDefined();
      expect(getEventListeners(pre.signal, "abort")).toHaveLength(1);
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      const before = census(db);
      pre.abort();
      expect(getEventListeners(pre.signal, "abort")).toHaveLength(0);
      expect(cells.registerNativeSmsClaimLifecycle(queue, ref, {}, pre.signal)).toBeUndefined();
      expect(() =>
        cells.armNativeSmsSource({
          queue,
          claim: ref,
          received: binding(),
          scope: SCOPE,
          assertHostAndRouteCurrent: () => {},
          assertClaimCurrent: () => {},
          signal: new AbortController().signal,
        }),
      ).toThrow("REJ-M1-SMS-SOURCE-NON-COURANTE");
      expect(() => cells.readNativeSmsCompletionPermit(lifecycle)).toThrow();
      cells.retireNativeSmsClaimLifecycle(lifecycle);
      expect(census(db)).toEqual(before);
    });
  });

  it.each(["host", "claim"])(
    "rechecks native abort from the %s guard before returning scope",
    async (kind) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        const pre = new AbortController();
        let revoke = false;
        const guard = () => {
          if (revoke) {
            pre.abort();
          }
        };
        const current = await arm(queue, {
          preAdoptionController: pre,
          ...(kind === "host" ? { host: guard } : { claimCurrent: guard }),
        });
        const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
        const before = census(db);
        revoke = true;
        expect(() => cells.readSmsSourceScope(current.source)).toThrow(
          "REJ-M1-SMS-SOURCE-NON-COURANTE",
        );
        expect(current.controller.signal.aborted).toBe(false);
        expect(() => cells.readNativeSmsCompletionPermit(current.lifecycle)).toThrow();
        await expect(completeOwnNativeClaim(current.permit)).rejects.toThrow();
        expect(getEventListeners(pre.signal, "abort")).toHaveLength(0);
        expect(census(db)).toEqual(before);
      });
    },
  );

  it("rechecks native abort from the actual completion clock before SQL", async () => {
    await fixture(async (stateDir) => {
      const pre = new AbortController();
      let revoke = false;
      const queue = createChannelIngressQueue<{ fictif: boolean }>({
        channelId: "sms",
        accountId: "default",
        stateDir,
        now: () => {
          if (revoke) {
            pre.abort();
          }
          return TIME;
        },
      });
      const current = await arm(queue, { preAdoptionController: pre });
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      const before = census(db);
      revoke = true;
      await expect(completeOwnNativeClaim(current.permit)).rejects.toThrow();
      expect(current.controller.signal.aborted).toBe(false);
      expect(census(db)).toEqual(before);
      expect(() => cells.readSmsSourceScope(current.source)).toThrow();
    });
  });

  it("detaches only the native signal after real adoption and still obeys Host abort", async () => {
    await fixture(async (stateDir) => {
      const selected = await selectedDrain(stateDir);
      try {
        const assertion = cells.readSmsSourceAssertion(selected.source);
        expect(getEventListeners(selected.lifecycle.abortSignal, "abort")).toHaveLength(1);
        await selected.lifecycle.onAdopted();
        expect((await selected.queue.listClaims()).length).toBe(0);
        expect(getEventListeners(selected.lifecycle.abortSignal, "abort")).toHaveLength(0);
        // Native drain disposal is allowed after durable, confirmed adoption.
        selected.drain.dispose();
        expect(cells.readSmsSourceScope(selected.source)).toEqual(SCOPE);
        expect(cells.readSmsSourceAssertion(selected.source)).toBe(assertion);
        assertion();
        selected.controller.abort();
        expect(() => assertion()).toThrow("REJ-M1-SMS-SOURCE-NON-COURANTE");
      } finally {
        selected.drain.dispose();
      }
    });
  });

  it("ignores native abort only after consuming its own real commit receipt", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue<{ fictif: boolean }>({
        channelId: "sms",
        accountId: "default",
        stateDir,
      });
      const current = await arm(queue);
      const assertion = cells.readSmsSourceAssertion(current.source);
      const receipt = await completeOwnNativeClaim(current.permit);
      cells.confirmOwnNativeCompletion(current.lifecycle, receipt, current.lifecycleOwner);
      expect((await queue.listClaims()).length).toBe(0);
      current.preAdoptionController.abort();
      expect(current.preAdoptionController.signal.aborted).toBe(true);
      expect(getEventListeners(current.preAdoptionController.signal, "abort")).toHaveLength(0);
      expect(cells.readSmsSourceScope(current.source)).toEqual(SCOPE);
      assertion();
      current.controller.abort();
      expect(() => assertion()).toThrow("REJ-M1-SMS-SOURCE-NON-COURANTE");
      cells.retireNativeSmsClaimLifecycle(current.lifecycle);
    });
  });

  it.each(["after_commit", "after_consume"])(
    "keeps Source refused on native abort %s without denying the real SQL commit",
    async (when) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        const pre = new AbortController();
        let committed = false,
          confirmationChecks = 0;
        const current = await arm(queue, {
          preAdoptionController: pre,
          host: () => {
            if (committed && ++confirmationChecks === 2) {
              pre.abort();
            }
          },
        });
        const stage = publications.stageSqliteTransactionState;
        const observer = vi
          .spyOn(publications, "stageSqliteTransactionState")
          .mockImplementation((db, state) =>
            stage(db, {
              ...state,
              prepareObservers: () => {
                state.prepareObservers?.();
                committed = true;
                if (when === "after_commit") {
                  pre.abort();
                }
              },
            }),
          );
        try {
          const receipt = await completeOwnNativeClaim(current.permit);
          expect(committed).toBe(true);
          expect(() =>
            cells.confirmOwnNativeCompletion(current.lifecycle, receipt, current.lifecycleOwner),
          ).toThrow();
          expect((await queue.enqueue(SID, { fictif: true })).kind).toBe("completed");
          expect(() => cells.readSmsSourceScope(current.source)).toThrow();
          expect(() => cells.readSmsSourceAssertion(current.source)()).toThrow();
          expect(current.controller.signal.aborted).toBe(false);
          if (when === "after_consume") {
            expect(confirmationChecks).toBe(2);
          }
        } finally {
          observer.mockRestore();
          cells.retireNativeSmsClaimLifecycle(current.lifecycle);
        }
      });
    },
  );

  it("never falls back to legacy completion after a real failed arm", async () => {
    await fixture(async (stateDir) => {
      const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
      await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
      const db = openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } }).db;
      let before!: ReturnType<typeof census>;
      let lifecycle!: ChannelIngressDispatchLifecycle;
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (claim, current) => {
          lifecycle = current;
          before = census(db);
          expect(() =>
            cells.armNativeSmsSource({
              queue,
              claim: { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
              received: { ...binding(), receivedAt: TIME + 1 },
              scope: SCOPE,
              assertHostAndRouteCurrent: () => {},
              assertClaimCurrent: () => {},
              signal: new AbortController().signal,
            }),
          ).toThrow("REJ-M1-SMS-SOURCE-NON-COURANTE");
          return { kind: "completed" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        await expect(lifecycle.onAdopted()).rejects.toThrow();
        expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
        expect(census(db)).toEqual(before);
      } finally {
        drain.dispose();
      }
    });
  });

  it.each([false, true])(
    "preserves late completed legacy only when never armed: selected=%s",
    async (selected) => {
      await fixture(async (stateDir) => {
        const queue = createChannelIngressQueue<{ fictif: boolean }>({
          channelId: "sms",
          accountId: "default",
          stateDir,
        });
        await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
        const parent = new AbortController(),
          host = new AbortController();
        let unblock!: () => void;
        const waiting = new Promise<void>((resolve) => {
          unblock = resolve;
        });
        let source: object | undefined;
        let lifecycle!: ChannelIngressDispatchLifecycle;
        const drain = createChannelIngressDrain({
          queue,
          abortSignal: parent.signal,
          dispatchClaimedEvent: async (claim, current) => {
            lifecycle = current;
            if (selected) {
              source = cells.armNativeSmsSource({
                queue,
                claim: { id: claim.id, token: claim.claim.token, ownerId: claim.claim.ownerId },
                received: binding(),
                scope: SCOPE,
                assertHostAndRouteCurrent: () => {},
                assertClaimCurrent: () => {},
                signal: host.signal,
              });
            }
            await waiting;
            return { kind: "completed" };
          },
        });
        try {
          await drain.drainOnce();
          parent.abort();
          expect(lifecycle.abortSignal.aborted).toBe(true);
          expect(host.signal.aborted).toBe(false);
          unblock();
          await drain.waitForIdle();
          if (selected) {
            expect((await queue.listClaims())[0]?.payload).toEqual({ fictif: true });
            expect(() => cells.readSmsSourceScope(source)).toThrow();
            await expect(lifecycle.onAdopted()).rejects.toThrow();
          } else {
            expect((await queue.enqueue(SID, { fictif: true })).kind).toBe("completed");
          }
        } finally {
          unblock();
          drain.dispose();
        }
      });
    },
  );
});
