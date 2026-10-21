import { createHash, createHmac } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import {
  createIngressDrainOwnerId,
  registerLiveIngressDrainInstance,
  deregisterLiveIngressDrainInstance,
  INGRESS_CLAIM_LEASE_MS,
} from "../channels/message/ingress-claim-owner.js";
import * as queues from "../channels/message/ingress-queue.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import { createTaskScopedChannelRuntime } from "../infra/channel-runtime-context.js";
import { openNodeSqliteDatabase } from "../infra/node-sqlite.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import * as loader from "../plugins/public-surface-loader.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { createChannelRuntimeContextRegistry } from "../plugins/runtime/channel-runtime-contexts.js";
import {
  closeOpenClawStateDatabaseForTest,
  openOpenClawStateDatabase,
} from "../state/openclaw-state-db.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import { createOpsysSmsHostAuthority } from "./opsys-sms-host-authority.js";
import {
  readJoinedSmsReceiptForNativeSource,
  readJoinedSmsHostDestinationAssertionForNativeSource,
} from "./opsys-sms-host-claim-adapter.js";

type Params = Parameters<
  typeof import("./opsys-sms-host-controller.js").createOpsysSmsHostController
>[0];
type Call = Parameters<typeof callOpsysMcpTool>[0];
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const REFUSED = "REJ-M1-SMS-HOST-SELECTION";
const UNRESOLVED = { status: "unresolved", code: "M1-SMS-RECEPTION-NON-RESOLUE" };

// All credentials and ACK references here are fictitious RAM fixtures, never SQL/HTTP claims.
function fixture(published = true) {
  vi.spyOn(loader, "loadBundledPluginPublicArtifactModuleFromCandidatesSync").mockReturnValue({
    verifyTwilioSignature: smsApi.verifyTwilioSignature,
  });
  const rootDir = path.resolve("extensions/sms");
  const accountSid = "AC" + "1".repeat(32);
  const sms = {
    enabled: true,
    accountSid,
    authToken: "controller-hmac-fictif",
    fromNumber: "+15145550101",
    publicWebhookUrl: "https://sms-fictif.example/webhooks/sms",
    dangerouslyDisableSignatureValidation: false,
  };
  const account = { accountId: "default", ...sms, dangerouslyDisableSignatureValidation: false };
  const marker = {
    profileId: "sms-demo",
    profileRevision: 7,
    smsIngress: { version: 1 as const, accountId: "default", accountSid },
  };
  const cfg: OpenClawConfig = {
    channels: { sms },
    agents: { list: [{ id: "opsys-agent-sms-demo", opsysRuntimeAdmission: marker }] },
    bindings: [
      { agentId: "opsys-agent-sms-demo", match: { channel: "sms", accountId: "default" } },
    ],
    mcp: {
      servers: {
        "opsys_runtime_sms-demo": {
          transport: "streamable-http",
          url: "https://mcp-fictif.example/runtime/sms-demo",
          headers: { Authorization: "Bearer fictif-controller-only" },
        },
      },
    },
  };
  let liveGrant = true,
    lifetime = true,
    task = published;
  const grant = vi.fn(() => liveGrant);
  const captureReadAuthority = vi.fn(() => grant);
  const registry = createEmptyPluginRegistry();
  const owner = {
    pluginId: "sms",
    origin: "bundled" as const,
    plugin: createChannelTestPluginBase({ id: "sms" }),
    rootDir,
    source: path.join(rootDir, "index.ts"),
    captureReadAuthority,
  };
  registry.channels.push(owner);
  let currentOwner = owner;
  const signalOwner = new AbortController();
  const capabilityLease = createPluginRuntimeCapabilityLease("fictitious controller owner");
  const registration = getLoadedChannelPluginEntryById("sms", registry);
  if (!registration) {
    throw new Error("Missing fixture registration");
  }
  const authority = createOpsysSmsHostAuthority({
    cfg,
    getRuntimeConfig: () => cfg,
    channelId: "sms",
    accountId: "default",
    account,
    registration,
    getCurrentRegistration: () => getLoadedChannelPluginEntryById("sms", registry),
    abortSignal: signalOwner.signal,
    capabilityLease,
    isCurrentLifetime: () => lifetime,
    isCurrentTask: () => task,
  });
  if (!authority) {
    throw new Error("Missing fixture authority");
  }
  if (published) {
    expect(authority.publish()).toBe(true);
  }
  const base = { runtimeContexts: createChannelRuntimeContextRegistry() };
  const scoped = createTaskScopedChannelRuntime({ channelRuntime: base });
  const contexts = scoped.channelRuntime!.runtimeContexts;
  let currentContexts = contexts,
    credential = account.authToken;
  const calls: Call[] = [];
  let respond: (call: Call) => Promise<unknown> = async (call) => ack(call);
  const params: Params = {
    authority,
    owner,
    getCurrentOwner: () => currentOwner,
    getRuntimeContexts: () => currentContexts,
    getCurrentConfig: () => cfg,
    getCurrentCredential: () => credential,
    signal: signalOwner.signal,
    callTool: async (call) => {
      call.beforeRequest?.();
      calls.push(call);
      return respond(call);
    },
  };
  const form = {
    AccountSid: accountSid,
    MessageSid: SID,
    From: "+15145550102",
    To: sms.fromNumber,
    Body: "Québec e\u0301 😀",
    NumMedia: "0",
  };
  const signature = createHmac("sha1", account.authToken)
    .update(
      sms.publicWebhookUrl +
        Object.keys(form)
          .toSorted()
          .map((k) => k + form[k as keyof typeof form])
          .join(""),
    )
    .digest("base64");
  return {
    params,
    owner,
    contexts,
    scoped,
    cfg,
    account,
    marker,
    calls,
    captureReadAuthority,
    authority,
    signalOwner,
    input: { form, signature, signatureUrl: sms.publicWebhookUrl },
    claimContext: {
      id: SID,
      receivedAt: TIME,
      signal: signalOwner.signal,
      assertClaimCurrent: () => {},
    },
    respond: (fn: typeof respond) => {
      respond = fn;
    },
    replaceOwner: () => {
      currentOwner = { ...owner };
    },
    replaceRegistry: () => {
      currentContexts = { ...contexts };
    },
    loseLifetime: () => {
      lifetime = false;
    },
    loseTask: () => {
      task = false;
    },
    loseGrant: () => {
      liveGrant = false;
    },
    changeCredential: () => {
      credential = "new-fictif";
    },
  };
}
function ack(call: Call, absent = false) {
  const operation =
    call.tool === "opsys_runtime_lire_reception_sms"
      ? "opsys_runtime_lire_reception_sms"
      : "opsys_runtime_recevoir_sms";
  const c = validateSmsCommand(call.args, operation);
  return {
    version: 1,
    operation: operation === "opsys_runtime_lire_reception_sms" ? "lire" : "recevoir",
    ok: true,
    etat: absent ? "absent" : "recu",
    intention_id: c.intention_id,
    commande_sha256: c.commande_sha256,
    arguments_sha256: c.arguments_sha256,
    permission: { ...c.permission },
    recu: absent
      ? null
      : {
          source: "sms:twilio",
          compte_id: c.commande.compte_id,
          account_sid: c.commande.account_sid,
          message_sid: c.commande.message_sid,
          agent_id: c.commande.agent_id,
          session_key: c.commande.session_key,
          signal_id: "sms:" + SID,
          signal_ligne_id: "a".repeat(64),
          decision: "DEMANDER_PRECISIONS",
          lead_ligne_id: null,
          transfert_id: null,
        },
  };
}

const cleanups: Array<() => void | Promise<void>> = [];
afterEach(async () => {
  for (const cleanup of cleanups.splice(0).toReversed()) {
    await cleanup();
  }
  closeOpenClawStateDatabaseForTest();
  vi.restoreAllMocks();
});
async function make(withClaim = true, queueAccountId = "default") {
  // Import the missing adapter first: RED must be product absence, before any DB setup.
  const { createOpsysSmsHostClaimAdapter } = await import("./opsys-sms-host-claim-adapter.js");
  const { createOpsysSmsHostController } = await import("./opsys-sms-host-controller.js");
  const f = fixture();
  const controller = createOpsysSmsHostController(f.params);
  const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "sms-host-claim-fictif-"));
  cleanups.push(async () => {
    closeOpenClawStateDatabaseForTest();
    await fs.rm(stateDir, { recursive: true, force: true });
  });
  cleanups.push(() => {
    controller.dispose();
    f.authority.revoke();
    f.scoped.dispose();
  });
  const ownerId = createIngressDrainOwnerId();
  registerLiveIngressDrainInstance(ownerId);
  cleanups.push(() => deregisterLiveIngressDrainInstance(ownerId));
  const clock = vi.spyOn(Date, "now").mockReturnValue(TIME);
  const queue = queues.createChannelIngressQueue<unknown>({
    channelId: "sms",
    accountId: queueAccountId,
    stateDir,
  });
  const current = vi.fn(() => {
    if (!f.authority.isCurrent()) {
      throw new Error("fictif stopped");
    }
  });
  const adapter = createOpsysSmsHostClaimAdapter({
    controller,
    accountId: queueAccountId,
    stateDir,
    signal: f.signalOwner.signal,
    assertCurrent: current,
  });
  cleanups.push(() => adapter.dispose());
  const handle = adapter.invoke(adapter.locator, { kind: "capture", input: f.input });
  const payload = adapter.invoke(adapter.locator, { kind: "encode", handle, receivedAt: TIME });
  if (withClaim) {
    await queue.enqueue(SID, payload, { receivedAt: TIME });
  }
  const claim = withClaim ? await queue.claim(SID, { ownerId }) : null;
  const request = {
    kind: "resolve",
    payload,
    id: SID,
    token: claim?.claim.token ?? "fictif-missing",
    ownerId,
    receivedAt: TIME,
  };
  const database = () => openOpenClawStateDatabase({ env: { OPENCLAW_STATE_DIR: stateDir } });
  return {
    ...f,
    adapter,
    controller,
    queue,
    claim,
    request,
    stateDir,
    ownerId,
    clock,
    current,
    database,
  };
}
const censusEvidence: Array<{ tables: number; hashes: Record<string, string> }> = [];
afterAll(() => {
  if (censusEvidence.length) {
    console.info(
      JSON.stringify({
        kind: "fictitious-local-native-census",
        snapshots: censusEvidence.length,
        tableCounts: censusEvidence.map((v) => v.tables),
        snapshotHashes: censusEvidence.map((v) =>
          createHash("sha256").update(JSON.stringify(v.hashes)).digest("hex"),
        ),
      }),
    );
  }
});
function census(database: ReturnType<typeof openOpenClawStateDatabase>) {
  // sqlite-allow-raw -- Independent census of every native local table and complete row.
  const names = database.db
    .prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
    .all();
  const rows = names.map((row) => {
    const name = String(row.name);
    return [
      name,
      database.db.prepare(`SELECT * FROM "${name.replaceAll('"', '""')}"`).all(),
    ] as const;
  });
  censusEvidence.push({
    tables: rows.length,
    hashes: Object.fromEntries(
      rows.map(([name, all]) => [
        name,
        createHash("sha256").update(JSON.stringify(all)).digest("hex"),
      ]),
    ),
  });
  return rows;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("private Host SMS native CLAIM adapter", () => {
  it("exports the private factory", async () => {
    await expect(import("./opsys-sms-host-claim-adapter.js")).resolves.toHaveProperty(
      "createOpsysSmsHostClaimAdapter",
    );
  });
  it("uses real HMAC/controller and current native CLAIM, with no writes to any native table", async () => {
    const f = await make();
    const before = census(f.database());
    const result = await f.adapter.invoke(f.adapter.locator, f.request);
    expect(result).toMatchObject({ status: "received", receipt: { message_sid: SID } });
    expect(f.calls.map((c) => c.tool)).toEqual(["opsys_runtime_lire_reception_sms"]);
    expect(census(f.database())).toEqual(before);
  });
  it("retains READ-absent then RECEIVE with the exact original capsule, timestamp and intent", async () => {
    const f = await make();
    f.respond(async (call) => ack(call, call.tool === "opsys_runtime_lire_reception_sms"));
    const before = census(f.database());
    const result = await f.adapter.invoke(f.adapter.locator, f.request);
    expect(result).toMatchObject({ status: "received" });
    expect(f.calls.map((c) => c.tool)).toEqual([
      "opsys_runtime_lire_reception_sms",
      "opsys_runtime_recevoir_sms",
    ]);
    expect(f.calls[1]?.args).toEqual(f.calls[0]?.args);
    expect(census(f.database())).toEqual(before);
  });
  it.each(["token", "ownerId", "id"] as const)(
    "refuses wrong %s without invoking RPC",
    async (key) => {
      const f = await make();
      const before = census(f.database());
      expect(
        await f.adapter.invoke(f.adapter.locator, { ...f.request, [key]: "fictif-foreign" }),
      ).toEqual(UNRESOLVED);
      expect(f.calls).toEqual([]);
      expect(census(f.database())).toEqual(before);
    },
  );
  it("uses only its selected native account queue", async () => {
    const f = await make(false);
    const other = queues.createChannelIngressQueue({
      channelId: "sms",
      accountId: "other",
      stateDir: f.stateDir,
    });
    await other.enqueue(SID, f.request.payload, { receivedAt: TIME });
    const claim = await other.claim(SID, { ownerId: f.ownerId });
    expect(claim).not.toBeNull();
    expect(
      await f.adapter.invoke(f.adapter.locator, { ...f.request, token: claim!.claim.token }),
    ).toEqual(UNRESOLVED);
    expect(f.calls).toEqual([]);
  });
  it("lazy missing reader does not create state or silently adopt a later native owner", async () => {
    const f = await make(false);
    expect(await fs.readdir(f.stateDir)).toEqual([]);
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(await fs.readdir(f.stateDir)).toEqual([]);
    await f.queue.enqueue(SID, f.request.payload, { receivedAt: TIME });
    const claim = await f.queue.claim(SID, { ownerId: f.ownerId });
    expect(
      await f.adapter.invoke(f.adapter.locator, { ...f.request, token: claim!.claim.token }),
    ).toEqual(UNRESOLVED);
    expect(f.calls).toEqual([]);
  });
  it("does not require original claimedAt equality when native refresh advances the lease", async () => {
    const f = await make();
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toMatchObject({
      status: "received",
    });
    f.clock.mockReturnValue(TIME + INGRESS_CLAIM_LEASE_MS - 1);
    expect(
      await f.queue.refreshClaim?.(f.claim!, { refreshedAt: TIME + INGRESS_CLAIM_LEASE_MS - 1 }),
    ).toBe(true);
    f.clock.mockReturnValue(TIME + INGRESS_CLAIM_LEASE_MS + 1);
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toMatchObject({
      status: "received",
    });
  });
  it.each(["expired", "future", "local-drain-dead"] as const)(
    "refuses %s native owner state",
    async (mode) => {
      const f = await make();
      if (mode === "expired") {
        f.clock.mockReturnValue(TIME + INGRESS_CLAIM_LEASE_MS);
      }
      if (mode === "future") {
        f.clock.mockReturnValue(TIME - 1);
      }
      if (mode === "local-drain-dead") {
        deregisterLiveIngressDrainInstance(f.ownerId);
      }
      expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
      expect(f.calls).toEqual([]);
    },
  );
  it("sees actual peer WAL reclaim after awaited RPC and sends no new RECEIVE", async () => {
    const f = await make();
    const peer = openNodeSqliteDatabase(path.join(f.stateDir, "state/openclaw.sqlite"));
    cleanups.push(() => peer.close());
    f.respond(async (call) => {
      await Promise.resolve();
      // sqlite-allow-raw -- Real peer reclaim fault at the precise awaited RPC boundary.
      peer
        .prepare("UPDATE channel_ingress_events SET claim_token=? WHERE event_id=?")
        .run("fictif-reclaimed", SID);
      return ack(call, true);
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls).toHaveLength(1);
  });
  it("rechecks beforeRequest after an await inside actual Gate transport callback", async () => {
    const f = await make();
    f.respond(async (call) => {
      f.loseLifetime();
      call.beforeRequest?.();
      return ack(call);
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(() => f.adapter.invoke(f.adapter.locator, { kind: "capture", input: f.input })).toThrow(
      REFUSED,
    );
  });
  it("closes after dispose idempotently", async () => {
    const f = await make();
    f.adapter.dispose();
    f.adapter.dispose();
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(() =>
      f.adapter.invoke(f.adapter.locator, { kind: "encode", handle: {}, receivedAt: TIME }),
    ).toThrow(REFUSED);
  });
  it("closes when the captured Host callback refuses without leaking its raw error", async () => {
    const f = await make();
    f.current.mockImplementation(() => {
      throw new Error("fictif raw secret must not escape");
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls).toEqual([]);
  });
  it.each(["locator", "payload", "time"] as const)(
    "refuses altered %s while preserving the original intention",
    async (mode) => {
      const f = await make();
      const locator = mode === "locator" ? Object.freeze({}) : f.adapter.locator;
      const request = {
        ...f.request,
        ...(mode === "payload" ? { payload: {} } : {}),
        ...(mode === "time" ? { receivedAt: TIME + 1 } : {}),
      };
      expect(await f.adapter.invoke(locator, request)).toEqual(UNRESOLVED);
      expect(f.calls).toEqual([]);
      expect(await f.adapter.invoke(f.adapter.locator, f.request)).toMatchObject({
        status: "received",
      });
    },
  );
  it.each(["extra", "getter", "proxy", "nestedproxy", "prototype"] as const)(
    "refuses hostile %s before any trap/getter executes",
    async (mode) => {
      const f = await make();
      const trap = vi.fn(() => {
        throw new Error("must not execute");
      });
      let request: unknown = f.request;
      if (mode === "extra") {
        request = { ...f.request, assertClaimCurrent: trap };
      }
      if (mode === "getter") {
        request = Object.defineProperty({ ...f.request }, "payload", {
          enumerable: true,
          get: trap,
        });
      }
      if (mode === "proxy") {
        request = new Proxy(f.request, { ownKeys: trap, getPrototypeOf: trap, get: trap });
      }
      if (mode === "nestedproxy") {
        request = {
          ...f.request,
          payload: new Proxy({}, { ownKeys: trap, getPrototypeOf: trap, get: trap }),
        };
      }
      if (mode === "prototype") {
        request = Object.assign(Object.create({}), f.request);
      }
      expect(await f.adapter.invoke(f.adapter.locator, request)).toEqual(UNRESOLVED);
      expect(trap).not.toHaveBeenCalled();
      expect(f.calls).toEqual([]);
      expect(await f.adapter.invoke(f.adapter.locator, f.request)).toMatchObject({
        status: "received",
      });
    },
  );

  it("rechecks host abort after awaited RPC and never accepts that stale ACK", async () => {
    const f = await make();
    f.respond(async (call) => {
      await Promise.resolve();
      f.signalOwner.abort();
      return ack(call);
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls).toHaveLength(1);
  });
  it("refuses a lost native database owner after awaited RPC", async () => {
    const f = await make();
    f.respond(async (call) => {
      await Promise.resolve();
      closeOpenClawStateDatabaseForTest();
      return ack(call);
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls).toHaveLength(1);
  });
  it.each(["capture", "encode"] as const)(
    "%s refusals are constants with no extra callable input executed",
    async (kind) => {
      const f = await make();
      const getter = vi.fn(() => {
        throw new Error("fictif-no-leak");
      });
      const input =
        kind === "capture"
          ? { kind, input: f.input, queue: getter }
          : { kind, handle: {}, receivedAt: TIME, signal: getter };
      expect(() => f.adapter.invoke(f.adapter.locator, input)).toThrow(REFUSED);
      expect(getter).not.toHaveBeenCalled();
      const nested =
        kind === "capture"
          ? { kind, input: Object.defineProperty({}, "form", { enumerable: true, get: getter }) }
          : { kind, handle: {}, receivedAt: -1 };
      expect(() => f.adapter.invoke(f.adapter.locator, nested)).toThrow(REFUSED);
      expect(getter).not.toHaveBeenCalled();
    },
  );

  it("memoizes a real reader preparation and disposes a late result after retirement", async () => {
    const f = await make();
    const actualFactory = queues.createChannelIngressQueue;
    const prepared = deferred<void>();
    const readerDisposed = vi.fn();
    let count = 0;
    vi.spyOn(queues, "createChannelIngressQueue").mockImplementation((options) => {
      const q = actualFactory(options);
      const actualPrepare = q.prepareClaimIdentityReader!;
      return {
        ...q,
        prepareClaimIdentityReader: async () => {
          count++;
          const reader = await actualPrepare();
          await prepared.promise;
          return {
            read: reader.read,
            dispose() {
              readerDisposed();
              reader.dispose();
            },
          };
        },
      };
    });
    const { createOpsysSmsHostClaimAdapter } = await import("./opsys-sms-host-claim-adapter.js");
    const adapter = createOpsysSmsHostClaimAdapter({
      controller: f.controller,
      accountId: "default",
      stateDir: f.stateDir,
      signal: f.signalOwner.signal,
      assertCurrent: f.current,
    });
    cleanups.push(() => adapter.dispose());
    const a = adapter.invoke(adapter.locator, f.request);
    const b = adapter.invoke(adapter.locator, f.request);
    adapter.dispose();
    prepared.resolve();
    expect(await a).toEqual(UNRESOLVED);
    expect(await b).toEqual(UNRESOLVED);
    expect(count).toBe(1);
    expect(readerDisposed).toHaveBeenCalledTimes(1);
    expect(f.calls).toEqual([]);
  });
});

it("refuses another genuinely signed body for the exact native stored claim before any RPC", async () => {
  const f = await make();
  const changedForm = { ...f.input.form, Body: f.input.form.Body + " autre contenu fictif" };
  const signed = createHmac("sha1", f.account.authToken)
    .update(
      f.input.signatureUrl +
        Object.keys(changedForm)
          .toSorted()
          .map((key) => key + changedForm[key as keyof typeof changedForm])
          .join(""),
    )
    .digest("base64");
  const changedHandle = f.adapter.invoke(f.adapter.locator, {
    kind: "capture",
    input: { form: changedForm, signature: signed, signatureUrl: f.input.signatureUrl },
  });
  const changedPayload = f.adapter.invoke(f.adapter.locator, {
    kind: "encode",
    handle: changedHandle,
    receivedAt: TIME,
  });
  // Both capsules are produced by the actual capture owner, not a fabricated bad signature.
  expect(changedPayload).toEqual(expect.objectContaining({ version: 2 }));
  expect(changedPayload).not.toEqual(f.request.payload);
  expect(f.calls).toEqual([]);
  const db = f.database();
  const before = census(db);
  const changed = await f.adapter.invoke(f.adapter.locator, {
    ...f.request,
    payload: changedPayload,
  });
  expect(changed).toEqual(UNRESOLVED);
  expect(f.calls).toEqual([]);
  expect(census(db)).toEqual(before);
});

it("refuses real controller default-A composed with native adapter/queue B before any RPC", async () => {
  // Deliberately inconsistent trusted Core composition, not an established public manager route.
  const f = await make(true, "foreign");
  const before = census(f.database());
  expect(f.authority.isCurrent()).toBe(true);
  expect(f.request.payload).toMatchObject({ version: 2, capsule: { compte_id: "default" } });
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  expect(result).toEqual(UNRESOLVED);
  expect(f.calls).toEqual([]);
  expect(census(f.database())).toEqual(before);
});

function nativeRef(f: Awaited<ReturnType<typeof make>>) {
  return { id: SID, token: f.request.token, ownerId: f.ownerId };
}
it("joins only the exact received object, with original native command/receipt/destination", async () => {
  const f = await make();
  const before = census(f.database());
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  const binding = readJoinedSmsReceiptForNativeSource(result, f.queue, nativeRef(f));
  expect(binding).toMatchObject({
    command: {
      commande: { compte_id: "default", message_sid: SID, recu_le: "2026-10-10T12:00:00.123Z" },
    },
    receipt: { message_sid: SID },
    destinationSha256: expect.stringMatching(/^[0-9a-f]{64}$/),
  });
  const guard = readJoinedSmsHostDestinationAssertionForNativeSource(result, f.queue, nativeRef(f));
  expect(typeof guard).toBe("function");
  guard!();
  guard!();
  expect(readJoinedSmsHostDestinationAssertionForNativeSource(result, f.queue, nativeRef(f))).toBe(
    guard,
  );
  expect(f.calls).toHaveLength(1);
  expect(census(f.database())).toEqual(before);
});
it("recognizes pure-data passthrough only as original and rejects distinct copied/proxy objects or foreign tuple", async () => {
  const f = await make();
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  const trap = vi.fn();
  const instance = new PluginInstance("received-view-fictif");
  try {
    const passthrough = instance.wrap(result);
    expect(Object.is(passthrough, result)).toBe(true);
    expect(readJoinedSmsReceiptForNativeSource(passthrough, f.queue, nativeRef(f))).toBeDefined();
    for (const copy of [
      { ...(result as object) },
      new Proxy(result as object, { get: trap, ownKeys: trap }),
      instance.wrap({ ...(result as object) }),
    ]) {
      expect(readJoinedSmsReceiptForNativeSource(copy, f.queue, nativeRef(f))).toBeUndefined();
    }
    expect(trap).not.toHaveBeenCalled();
    expect(
      readJoinedSmsReceiptForNativeSource(result, f.queue, {
        ...nativeRef(f),
        token: "foreign-fictif",
      }),
    ).toBeUndefined();
    expect(readJoinedSmsReceiptForNativeSource(result, f.queue, nativeRef(f))).toBeUndefined();
  } finally {
    await instance.dispose();
  }
});
it("retains a claim-independent Host/destination closure but pre-arm lookup still needs the claim", async () => {
  const f = await make();
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  const guard = readJoinedSmsHostDestinationAssertionForNativeSource(result, f.queue, nativeRef(f));
  expect(guard).toBeDefined();
  const before = census(f.database());
  // sqlite-allow-raw -- Isolated lookup loss, NOT a native completion/adoption proof.
  f.database()
    .db.prepare("UPDATE channel_ingress_events SET claim_token=? WHERE event_id=?")
    .run("reclaimed-fictif", SID);
  expect(readJoinedSmsReceiptForNativeSource(result, f.queue, nativeRef(f))).toBeUndefined();
  expect(() => guard!()).not.toThrow();
  const after = census(f.database());
  guard!();
  expect(census(f.database())).toEqual(after);
  expect(f.calls).toHaveLength(1);
  expect(after).not.toEqual(before);
});
it("closes on actual MCP URL retarget, even when Host authority stays current, without recapturing baseline", async () => {
  const f = await make();
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  const guard = readJoinedSmsHostDestinationAssertionForNativeSource(
    result,
    f.queue,
    nativeRef(f),
  )!;
  const before = census(f.database());
  const server = f.cfg.mcp!.servers!["opsys_runtime_sms-demo"];
  const original = server.url;
  server.url = "https://different-fictif.example/runtime/sms-demo";
  expect(f.authority.isCurrent()).toBe(true);
  expect(() => guard()).toThrow();
  expect(readJoinedSmsReceiptForNativeSource(result, f.queue, nativeRef(f))).toBeUndefined();
  server.url = original;
  expect(() => guard()).toThrow();
  expect(f.calls).toHaveLength(1);
  expect(census(f.database())).toEqual(before);
});
it.each(["payload", "time", "invalidjson"] as const)(
  "rechecks original %s during T0 await and sends no RECEIVE",
  async (mode) => {
    const f = await make();
    f.respond(async (call) => {
      await Promise.resolve();
      // sqlite-allow-raw -- Actual native row mutation at the awaited fake-RPC boundary.
      const db = f.database().db;
      if (mode === "time") {
        db.prepare("UPDATE channel_ingress_events SET received_at=? WHERE event_id=?").run(
          TIME + 1,
          SID,
        );
      } else {
        db.prepare("UPDATE channel_ingress_events SET payload_json=? WHERE event_id=?").run(
          mode === "invalidjson" ? "{" : "{}",
          SID,
        );
      }
      return ack(call, true);
    });
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls.map((c) => c.tool)).toEqual(["opsys_runtime_lire_reception_sms"]);
  },
);
it.each(["invalidjson", "oversize"] as const)(
  "refuses stored %s before RPC and changes no table",
  async (mode) => {
    const f = await make();
    // sqlite-allow-raw -- Actual stored corruption, not a reader substitute.
    f.database()
      .db.prepare("UPDATE channel_ingress_events SET payload_json=? WHERE event_id=?")
      .run(mode === "invalidjson" ? "{" : "x".repeat(262145), SID);
    const before = census(f.database());
    expect(await f.adapter.invoke(f.adapter.locator, f.request)).toEqual(UNRESOLVED);
    expect(f.calls).toEqual([]);
    expect(census(f.database())).toEqual(before);
  },
);
it("held destination callback closes on adapter disposal without SQL or extra RPC", async () => {
  const f = await make();
  const result = await f.adapter.invoke(f.adapter.locator, f.request);
  const guard = readJoinedSmsHostDestinationAssertionForNativeSource(
    result,
    f.queue,
    nativeRef(f),
  )!;
  const before = census(f.database());
  f.adapter.dispose();
  expect(() => guard()).toThrow();
  expect(readJoinedSmsReceiptForNativeSource(result, f.queue, nativeRef(f))).toBeUndefined();
  expect(f.calls).toHaveLength(1);
  expect(census(f.database())).toEqual(before);
});
