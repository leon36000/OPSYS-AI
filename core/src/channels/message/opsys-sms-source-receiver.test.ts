// Fictitious binding/C/receipt with real native SQLite claims and completion.
// Comparison to this binding is not durable OriginalC, RPC or model permission.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { DatabaseSync } from "node:sqlite";
import { expect, it, vi } from "vitest";
import { validateSmsCommand } from "../../agents/opsys-runtime-sms-contract.js";
import { finalizeInboundContext } from "../../auto-reply/reply/inbound-context.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../../state/openclaw-state-db.js";
import { createChannelIngressQueue, completeOwnNativeClaim } from "./ingress-queue.js";
import { createNativeSmsSourceReceiver } from "./opsys-sms-source-receiver.js";
import * as source from "./opsys-sms-source.js";

const ERROR = "REJ-M1-SMS-SOURCE-NON-COURANTE";
const SID = "SM" + "6".repeat(32);
const TIME = Date.UTC(2026, 9, 10, 17, 2, 0, 321);
const ACCOUNT = "AC" + "2".repeat(32);
const FROM = "+15145550101";
const TO = "+15145550102";
function message(body = "Texte fictif 😀\r\nligne\rfin\\n  ") {
  return { accountSid: ACCOUNT, messageSid: SID, from: FROM, to: TO, body, media: [] };
}
function context(body: string) {
  return finalizeInboundContext({ Body: body, RawBody: body, CommandBody: body });
}
function census(db: DatabaseSync) {
  return Object.fromEntries(
    db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
      .all()
      .map((row) => {
        const name = String(row.name);
        const rows = db
          .prepare('SELECT * FROM "' + name.replaceAll('"', '""') + '"')
          .all()
          .map((r) => JSON.stringify(r))
          .toSorted();
        return [
          name,
          {
            count: rows.length,
            sha256: createHash("sha256").update(JSON.stringify(rows)).digest("hex"),
          },
        ];
      }),
  );
}
async function fixture(
  run: (f: Awaited<ReturnType<typeof arm>>) => Promise<void> | void,
  body?: string,
) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "fictif-sms-receiver-"));
  try {
    await run(await arm(dir, body));
  } finally {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(dir, { recursive: true, force: true });
  }
}
async function arm(stateDir: string, body = message().body) {
  const queue = createChannelIngressQueue({ channelId: "sms", accountId: "default", stateDir });
  await queue.enqueue(SID, { fictif: true }, { receivedAt: TIME });
  const claimed = (await queue.claim(SID, { ownerId: "fictif-receiver-owner" }))!;
  const claim = { id: SID, token: claimed.claim.token, ownerId: claimed.claim.ownerId };
  const pre = new AbortController();
  const host = new AbortController();
  const lifecycleOwner = Object.freeze({});
  const lifecycle = source.registerNativeSmsClaimLifecycle(
    queue,
    claim,
    lifecycleOwner,
    pre.signal,
  )!;
  const command = validateSmsCommand(
    {
      version: 1,
      commande: {
        canal: "sms",
        provider: "twilio",
        compte_id: "default",
        account_sid: ACCOUNT,
        message_sid: SID,
        expediteur: FROM,
        destinataire: TO,
        recu_le: new Date(TIME).toISOString(),
        texte: body,
        session_key: `agent:opsys-agent-demo:sms:direct:${FROM}`,
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
  const handle = source.armNativeSmsSource({
    queue,
    claim,
    received: {
      status: "received",
      command,
      receivedAt: TIME,
      destinationSha256: "b".repeat(64),
      receipt: {
        source: "sms:twilio",
        compte_id: "default",
        account_sid: ACCOUNT,
        message_sid: SID,
        agent_id: "opsys-agent-demo",
        session_key: command.commande.session_key,
        signal_id: "sms:" + SID,
        signal_ligne_id: "c".repeat(64),
        decision: "DEMANDER_PRECISIONS",
        lead_ligne_id: null,
        transfert_id: null,
      },
    },
    scope: {
      accountId: "default",
      agentId: "opsys-agent-demo",
      sessionKey: command.commande.session_key,
      sender: FROM,
      messageSid: SID,
    },
    assertHostAndRouteCurrent: () => host.signal.throwIfAborted(),
    assertClaimCurrent: () => {},
    signal: host.signal,
  });
  const raw = message(body);
  const receiver = createNativeSmsSourceReceiver({
    accountId: "default",
    signal: host.signal,
    assertCurrent: () => {},
  });
  receiver.acceptNativeSource(handle);
  const db = openOpenClawStateDatabase({ stateDir }).db;
  return { queue, claim, lifecycle, lifecycleOwner, handle, raw, receiver, db, pre, host, command };
}

it("compares original text and the real finalizer without writing any table or admitting ARMED", async () => {
  await fixture((f) => {
    const before = census(f.db);
    f.receiver.bindRawInput(f.handle, f.raw, TIME);
    f.receiver.assertRawInput(f.handle, f.raw);
    f.receiver.assertInitialTextProjection(f.raw, context(f.raw.body));
    expect(f.receiver.readRawSource(f.raw)).toBe(f.handle);
    expect(() => source.readSmsSourceAssertion(f.handle)()).toThrow(ERROR);
    expect(census(f.db)).toEqual(before);
  });
});
it.each(["accountSid", "messageSid", "from", "to", "body"] as const)(
  "rejects raw %s substitution and restoration stays refused",
  async (field) => {
    await fixture((f) => {
      const before = census(f.db);
      f.receiver.bindRawInput(f.handle, f.raw, TIME);
      const original = f.raw[field];
      f.raw[field] = original + "X";
      expect(() => f.receiver.assertRawInput(f.handle, f.raw)).toThrow(ERROR);
      f.raw[field] = original;
      expect(() => f.receiver.assertRawInput(f.handle, f.raw)).toThrow(ERROR);
      expect(census(f.db)).toEqual(before);
    });
  },
);
it.each([
  "Body",
  "RawBody",
  "CommandBody",
  "BodyForAgent",
  "BodyForCommands",
  "rawText",
  "agentText",
  "commandText",
] as const)("rejects initial projection %s alone", async (field) => {
  await fixture((f) => {
    f.receiver.bindRawInput(f.handle, f.raw, TIME);
    const ctx = context(f.raw.body);
    const original = ctx[field];
    ctx[field] = original + "X";
    expect(() => f.receiver.assertInitialTextProjection(f.raw, ctx)).toThrow(ERROR);
    ctx[field] = original;
    expect(() => f.receiver.assertInitialTextProjection(f.raw, ctx)).toThrow(ERROR);
  });
});
it.each(["  texte  ", "a\r\nb\rc\\n", "é é 😀\u00a0", "/status"])(
  "preserves binding text %j and grants no command permission",
  async (body) => {
    await fixture((f) => {
      f.receiver.bindRawInput(f.handle, f.raw, TIME);
      f.receiver.assertInitialTextProjection(f.raw, context(body));
      expect(f.raw.body).toBe(body);
      expect(() => source.readSmsSourceAssertion(f.handle)()).toThrow(ERROR);
    }, body);
  },
);
it.each(["clone", "proxy"] as const)("refuses %s raw without traps or SQL", async (kind) => {
  await fixture((f) => {
    f.receiver.bindRawInput(f.handle, f.raw, TIME);
    const trap = vi.fn(() => {
      throw new Error("fictif-private-canary");
    });
    const raw =
      kind === "clone"
        ? { ...f.raw }
        : new Proxy(f.raw, {
            get: trap,
            ownKeys: trap,
            getOwnPropertyDescriptor: trap,
            getPrototypeOf: trap,
          });
    const before = census(f.db);
    expect(() => f.receiver.assertRawInput(f.handle, raw)).toThrow(ERROR);
    expect(trap).not.toHaveBeenCalled();
    expect(census(f.db)).toEqual(before);
  });
});
it("rejects a getter without evaluating it", async () => {
  await fixture((f) => {
    const getter = vi.fn(() => "fictif-private-canary");
    Object.defineProperty(f.raw, "body", { get: getter, enumerable: true });
    const before = census(f.db);
    expect(() => f.receiver.bindRawInput(f.handle, f.raw, TIME)).toThrow(ERROR);
    expect(getter).not.toHaveBeenCalled();
    expect(census(f.db)).toEqual(before);
  });
});
it.each(["clone", "proxy", "unknown"] as const)(
  "recognizes only the exact Source WeakMap brand: %s",
  async (kind) => {
    await fixture((f) => {
      const trap = vi.fn(() => {
        throw new Error("fictif-private-canary");
      });
      const fake =
        kind === "proxy"
          ? new Proxy(f.handle, { get: trap, ownKeys: trap, getPrototypeOf: trap })
          : kind === "clone"
            ? { ...f.handle }
            : {};
      const before = census(f.db);
      expect(() => f.receiver.acceptNativeSource(fake)).toThrow(ERROR);
      expect(trap).not.toHaveBeenCalled();
      expect(census(f.db)).toEqual(before);
    });
  },
);
it.each(["pre", "host", "dispose"] as const)(
  "refuses %s closure and keeps tables unchanged",
  async (loss) => {
    await fixture((f) => {
      f.receiver.bindRawInput(f.handle, f.raw, TIME);
      const before = census(f.db);
      if (loss === "pre") {
        f.pre.abort();
      } else if (loss === "host") {
        f.host.abort();
      } else {
        f.receiver.dispose();
      }
      expect(() => f.receiver.assertRawInput(f.handle, f.raw)).toThrow(ERROR);
      expect(census(f.db)).toEqual(before);
    });
  },
);
it("keeps the actual ADOPTED Source after native COMMIT/own await while retaining Host revocation", async () => {
  await fixture(async (f) => {
    f.receiver.bindRawInput(f.handle, f.raw, TIME);
    const permit = source.readNativeSmsCompletionPermit(f.lifecycle)!;
    const receipt = await completeOwnNativeClaim(permit);
    source.confirmOwnNativeCompletion(f.lifecycle, receipt, f.lifecycleOwner);
    expect(await f.queue.listClaims()).toHaveLength(0);
    const before = census(f.db);
    f.pre.abort();
    f.receiver.assertRawInput(f.handle, f.raw);
    source.readSmsSourceAssertion(f.handle)();
    expect(census(f.db)).toEqual(before);
    f.host.abort();
    expect(() => f.receiver.assertRawInput(f.handle, f.raw)).toThrow(ERROR);
    expect(census(f.db)).toEqual(before);
  });
});
it.each([
  false,
  Promise.resolve(),
  {
    // eslint-disable-next-line unicorn/no-thenable -- Deliberately malformed native guard result.
    then: () => {
      throw new Error("fictif-canary");
    },
  },
])("refuses nonundefined guards without asynchronous permission", async (result) => {
  await fixture((f) => {
    const guard = () => result;
    const receiver = createNativeSmsSourceReceiver({
      accountId: "default",
      signal: f.host.signal,
      assertCurrent: guard,
    });
    expect(() => receiver.acceptNativeSource(f.handle)).toThrow(ERROR);
  });
});
it("rechecks signal after a reentrant native callback", async () => {
  await fixture((f) => {
    const receiver = createNativeSmsSourceReceiver({
      accountId: "default",
      signal: f.host.signal,
      assertCurrent: () => {
        f.host.abort();
      },
    });
    expect(() => receiver.acceptNativeSource(f.handle)).toThrow(ERROR);
  });
});
it.each(["raw", "context"] as const)(
  "refuses %s mutation at every observed native callback boundary",
  async (target) => {
    await fixture((f) => {
      let attacks = 0;
      for (let position = 1; position <= 16; position += 1) {
        f.raw.body = message().body;
        const ctx = context(f.raw.body);
        let checking = false;
        let calls = 0;
        let fired = false;
        const receiver = createNativeSmsSourceReceiver({
          accountId: "default",
          signal: f.host.signal,
          assertCurrent: () => {
            if (checking && ++calls === position) {
              fired = true;
              attacks += 1;
              if (target === "raw") {
                f.raw.body += " changed";
              } else {
                ctx.Body += " changed";
              }
            }
          },
        });
        receiver.acceptNativeSource(f.handle);
        receiver.bindRawInput(f.handle, f.raw, TIME);
        checking = true;
        let error: unknown;
        try {
          receiver.assertInitialTextProjection(f.raw, ctx);
        } catch (caught) {
          error = caught;
        }
        if (fired) {
          expect(error).toBeInstanceOf(Error);
          expect((error as Error).message).toBe(ERROR);
        } else {
          expect(error).toBeUndefined();
        }
        receiver.dispose();
      }
      expect(attacks).toBeGreaterThan(0);
    });
  },
);
it("keeps the actual canonical codec refusal for whitespace-only SMS", async () => {
  await fixture((f) => {
    const before = census(f.db);
    expect(() =>
      validateSmsCommand(
        {
          version: 1,
          commande: { ...f.command.commande, texte: "  " },
          permission: f.command.permission,
        },
        "opsys_runtime_recevoir_sms",
      ),
    ).toThrow("REJ-M1-SMS-COMMANDE-INVALIDE");
    expect(census(f.db)).toEqual(before);
  });
});
it("rejects constructor getter, proxy guard and unbranded signal without invoking them", async () => {
  await fixture((f) => {
    const trap = vi.fn(() => {
      throw new Error("fictif-private-canary");
    });
    const getterOwner = {
      accountId: "default",
      signal: f.host.signal,
      get assertCurrent() {
        return trap();
      },
    };
    const proxyGuard = new Proxy(() => {}, { apply: trap });
    const before = census(f.db);
    expect(() => createNativeSmsSourceReceiver(getterOwner)).toThrow(ERROR);
    expect(() =>
      createNativeSmsSourceReceiver({
        accountId: "default",
        signal: f.host.signal,
        assertCurrent: proxyGuard,
      }),
    ).toThrow(ERROR);
    expect(() =>
      createNativeSmsSourceReceiver({
        accountId: "default",
        signal: Object.create(AbortSignal.prototype),
        assertCurrent: () => {},
      }),
    ).toThrow(ERROR);
    expect(trap).not.toHaveBeenCalled();
    expect(census(f.db)).toEqual(before);
  });
});
it("does not read a thenable getter returned by the native guard", async () => {
  await fixture((f) => {
    const then = vi.fn(() => {
      throw new Error("fictif-private-canary");
    });
    const receiver = createNativeSmsSourceReceiver({
      accountId: "default",
      signal: f.host.signal,
      // eslint-disable-next-line unicorn/no-thenable -- Verify the adversarial getter is never evaluated.
      assertCurrent: () => Object.defineProperty({}, "then", { get: then }),
    });
    expect(() => receiver.acceptNativeSource(f.handle)).toThrow(ERROR);
    expect(then).not.toHaveBeenCalled();
  });
});
it("rejects wrong account, wrong original time and media without changing the claim", async () => {
  await fixture((f) => {
    const before = census(f.db);
    const foreign = createNativeSmsSourceReceiver({
      accountId: "other",
      signal: f.host.signal,
      assertCurrent: () => {},
    });
    expect(() => foreign.acceptNativeSource(f.handle)).toThrow(ERROR);
    expect(() => f.receiver.bindRawInput(f.handle, f.raw, TIME + 1)).toThrow(ERROR);
    const second = createNativeSmsSourceReceiver({
      accountId: "default",
      signal: f.host.signal,
      assertCurrent: () => {},
    });
    second.acceptNativeSource(f.handle);
    expect(() =>
      second.bindRawInput(f.handle, { ...f.raw, unavailableMediaCount: 1 }, TIME),
    ).toThrow(ERROR);
    expect(census(f.db)).toEqual(before);
  });
});
