import { ChildProcess, spawn } from "node:child_process";
import { createHash, createHmac } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import tls from "node:tls";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
// Test-only boundary exception: exercise the existing consumer without adding a public API.
import { createSmsIngressSpool } from "../../extensions/sms/src/ingress-spool.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import { isLiveLocalIngressDrainOwner } from "../channels/message/ingress-claim-owner.js";
import { createChannelIngressQueue } from "../channels/message/ingress-queue.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import * as contexteMcp from "../context-engine/opsys-contexte-mcp.js";
import { createTaskScopedChannelRuntime } from "../infra/channel-runtime-context.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import * as loader from "../plugins/public-surface-loader.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { createChannelRuntimeContextRegistry } from "../plugins/runtime/channel-runtime-contexts.js";
import { closeOpenClawStateDatabaseForTest } from "../state/openclaw-state-db.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import { createOpsysSmsHostAuthority } from "./opsys-sms-host-authority.js";
import {
  readJoinedSmsReceiptForNativeSource,
  readJoinedSmsHostDestinationAssertionForNativeSource,
  createOpsysSmsHostClaimAdapter,
} from "./opsys-sms-host-claim-adapter.js";
import { createOpsysSmsHostController } from "./opsys-sms-host-controller.js";
import type { SmsIngressCapturePayloadV2 } from "./opsys-sms-ingress-capture.js";

type Call = Parameters<typeof contexteMcp.callOpsysMcpTool>[0];
type SpoolParams = Parameters<typeof createSmsIngressSpool>[0];
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const waitControl = vi.hoisted(() => ({
  calls: [] as Array<{ ms: number; release: () => void }>,
  listeners: new Set<() => void>(),
}));
vi.mock("openclaw/plugin-sdk/runtime-env", async (importOriginal) => ({
  ...(await importOriginal<typeof import("openclaw/plugin-sdk/runtime-env")>()),
  sleepWithAbort: (ms: number, signal?: AbortSignal) =>
    new Promise<void>((resolve) => {
      waitControl.calls.push({ ms, release: resolve });
      for (const listener of Array.from(waitControl.listeners)) {
        listener();
      }
      if (signal?.aborted) {
        resolve();
      } else {
        signal?.addEventListener("abort", () => resolve(), { once: true });
      }
    }),
}));
const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  // Every cleanup runs, so a Core failure cannot leave an owned Native child behind.
  const failures: unknown[] = [];
  for (const cleanup of cleanups.splice(0).toReversed()) {
    try {
      await cleanup();
    } catch (error) {
      failures.push(error);
    }
  }
  waitControl.calls.length = 0;
  waitControl.listeners.clear();
  vi.restoreAllMocks();
  if (failures.length > 0) {
    throw failures[0];
  }
});
function ack(call: Call) {
  const validated = validateSmsCommand(call.args, "opsys_runtime_lire_reception_sms");
  const c = validated.commande;
  return {
    version: 1,
    operation: "lire",
    ok: true,
    etat: "recu",
    intention_id: validated.intention_id,
    commande_sha256: validated.commande_sha256,
    arguments_sha256: validated.arguments_sha256,
    permission: { ...validated.permission },
    recu: {
      source: "sms:twilio",
      compte_id: c.compte_id,
      account_sid: c.account_sid,
      message_sid: c.message_sid,
      agent_id: c.agent_id,
      session_key: c.session_key,
      signal_id: "sms:" + SID,
      signal_ligne_id: "a".repeat(64),
      decision: "DEMANDER_PRECISIONS",
      lead_ligne_id: null,
      transfert_id: null,
    },
  };
}
type NativeTarget = { url: string; token: string; profileRevision: number };
async function fixture(options: { native?: NativeTarget; stateDir?: string; body?: string } = {}) {
  const stateDir =
    options.stateDir ?? (await fs.mkdtemp(path.join(os.tmpdir(), "sms-consumer-core-fictif-")));
  const instance = new PluginInstance("sms");
  // Actual HMAC implementation; only the source-loader leaf and configured grant are injected.
  vi.spyOn(loader, "loadBundledPluginPublicArtifactModuleFromCandidatesSync").mockReturnValue({
    verifyTwilioSignature: smsApi.verifyTwilioSignature,
  });
  const clock = vi.spyOn(Date, "now").mockReturnValue(TIME);
  const accountSid = "AC" + "1".repeat(32);
  const sms = {
    enabled: true,
    accountSid,
    authToken: "fictif-consumer-hmac-only",
    fromNumber: "+15145550101",
    publicWebhookUrl: "https://sms-fictif.example/webhooks/sms",
    dangerouslyDisableSignatureValidation: false,
  };
  const account: SpoolParams["account"] = {
    accountId: "default",
    ...sms,
    messagingServiceSid: "",
    defaultTo: "",
    webhookPath: "/webhooks/sms",
    dmPolicy: "pairing",
    allowFrom: [],
    textChunkLimit: 1500,
  };
  const cfg: OpenClawConfig = {
    channels: { sms },
    agents: {
      list: [
        {
          id: "opsys-agent-sms-demo",
          opsysRuntimeAdmission: {
            profileId: "sms-demo",
            profileRevision: options.native?.profileRevision ?? 7,
            smsIngress: { version: 1, accountId: "default", accountSid },
          },
        },
      ],
    },
    bindings: [
      { agentId: "opsys-agent-sms-demo", match: { channel: "sms", accountId: "default" } },
    ],
    mcp: {
      servers: {
        "opsys_runtime_sms-demo": {
          transport: "streamable-http",
          url: options.native?.url ?? "https://mcp-fictif.example/runtime/sms-demo",
          headers: { Authorization: `Bearer ${options.native?.token ?? "fictif-consumer-only"}` },
        },
      },
    },
  };
  const registry = createEmptyPluginRegistry();
  const rootDir = path.resolve("extensions/sms");
  const owner = {
    pluginId: "sms",
    origin: "bundled" as const,
    rootDir,
    source: path.join(rootDir, "index.ts"),
    plugin: instance.wrap(createChannelTestPluginBase({ id: "sms" })),
    captureReadAuthority: () => () => true,
  };
  registry.channels.push(owner);
  const registration = getLoadedChannelPluginEntryById("sms", registry)!;
  const signal = new AbortController();
  const authority = createOpsysSmsHostAuthority({
    cfg,
    getRuntimeConfig: () => cfg,
    channelId: "sms",
    accountId: "default",
    account,
    registration,
    getCurrentRegistration: () => getLoadedChannelPluginEntryById("sms", registry),
    abortSignal: signal.signal,
    capabilityLease: createPluginRuntimeCapabilityLease("fictitious consumer owner"),
    isCurrentLifetime: () => true,
    isCurrentTask: () => true,
  })!;
  expect(authority.publish()).toBe(true);
  const scoped = createTaskScopedChannelRuntime({
    channelRuntime: { runtimeContexts: createChannelRuntimeContextRegistry() },
  });
  const calls: Call[] = [];
  let unknown = false;
  const controller = createOpsysSmsHostController({
    authority,
    owner,
    getCurrentOwner: () => owner,
    getRuntimeContexts: () => scoped.channelRuntime!.runtimeContexts,
    getCurrentConfig: () => cfg,
    getCurrentCredential: () => account.authToken,
    signal: signal.signal,
    // Native mode passes no callTool: the controller loads its default real MCP caller.
    ...(options.native
      ? {}
      : {
          // Only RPC/ACK is doubled: no network, Python receipt or provider effect is claimed.
          callTool: async (call: Call) => {
            call.beforeRequest?.();
            calls.push(call);
            if (unknown) {
              throw new Error("fictif ACK unavailable");
            }
            return ack(call);
          },
        }),
  });
  const adapter = createOpsysSmsHostClaimAdapter({
    controller,
    stateDir,
    accountId: "default",
    signal: signal.signal,
    assertCurrent: () => {
      if (!authority.isCurrent()) {
        throw new Error("fictif retired");
      }
    },
  });
  const api = instance.wrap(smsApi);
  const resolutions: unknown[] = [];
  const rejectedResolutions: unknown[] = [];
  const carrier = api.installOpsysSmsHostBridge("default", {
    locator: adapter.locator,
    // Transparent result observation: invoke, arguments and returned Promise remain real.
    invoke(locator, input) {
      const result = adapter.invoke(locator, input);
      if (
        typeof input === "object" &&
        input !== null &&
        "kind" in input &&
        input.kind === "resolve"
      ) {
        void Promise.resolve(result).then(
          (value) => {
            resolutions.push(value);
          },
          (error: unknown) => {
            rejectedResolutions.push(error);
          },
        );
      }
      return result;
    },
  });
  expect(api.getOpsysSmsHostBridge("default")?.locator).toBe(adapter.locator);
  expect(smsApi.getOpsysSmsHostBridge("default")).toBeUndefined();
  const queue = createChannelIngressQueue<unknown>({
    channelId: "sms",
    accountId: "default",
    stateDir,
  });
  const complete = vi.spyOn(queue, "complete");
  const fail = vi.spyOn(queue, "fail");
  const release = vi.spyOn(queue, "release");
  const inbound = vi.fn<NonNullable<SpoolParams["deliver"]>>(async () => undefined);
  // The real instance invocation captures its own slot before the durable pump runs.
  const spool = instance.wrap(() =>
    createSmsIngressSpool({
      cfg,
      account,
      queue,
      channelRuntime: {} as SpoolParams["channelRuntime"],
      deliver: inbound,
    }),
  )();
  let closed = false;
  const cleanup = async () => {
    if (closed) {
      return;
    }
    closed = true;
    waitControl.calls.forEach((w) => w.release());
    await spool.stop();
    carrier.dispose();
    adapter.dispose();
    controller.dispose();
    authority.revoke();
    scoped.dispose();
    await instance.dispose();
    closeOpenClawStateDatabaseForTest();
    if (!options.stateDir) {
      await fs.rm(stateDir, { recursive: true, force: true });
    }
  };
  cleanups.push(cleanup);
  const form = {
    AccountSid: accountSid,
    MessageSid: SID,
    From: "+15145550102",
    To: sms.fromNumber,
    Body: options.body ?? "Québec e\u0301 😀\nexact",
    NumMedia: "0",
  };
  const signature = createHmac("sha1", sms.authToken)
    .update(
      sms.publicWebhookUrl +
        Object.keys(form)
          .toSorted()
          .map((k) => k + form[k as keyof typeof form])
          .join(""),
    )
    .digest("base64");
  return {
    queue,
    spool,
    form,
    proof: { signature, signatureUrl: sms.publicWebhookUrl },
    calls,
    clock,
    complete,
    fail,
    release,
    inbound,
    authority,
    cleanup,
    resolutions,
    rejectedResolutions,
    setUnknown: () => {
      unknown = true;
    },
  };
}
async function settle(
  f: Awaited<ReturnType<typeof fixture>>,
  waitIndex: number,
  deferred: () => Promise<unknown> = () =>
    vi.waitFor(() => expect(waitControl.calls).toHaveLength(waitIndex + 1)),
) {
  await deferred();
  expect(waitControl.calls[waitIndex]?.ms).toBe(5000);
  expect(f.release).not.toHaveBeenCalled();
  const [claim] = await f.queue.listClaims();
  expect(claim?.claim.token).toBeTruthy();
  expect(isLiveLocalIngressDrainOwner(claim!.claim.ownerId)).toBe(true);
  const received = f.resolutions.find(
    (v) => typeof v === "object" && v !== null && "status" in v && v.status === "received",
  );
  if (received) {
    const ref = { id: claim!.id, token: claim!.claim.token, ownerId: claim!.claim.ownerId };
    expect(readJoinedSmsReceiptForNativeSource(received, f.queue, ref)).toBeDefined();
    expect(
      readJoinedSmsHostDestinationAssertionForNativeSource(received, f.queue, ref),
    ).toBeDefined();
  }
  const paused = f.spool.pause();
  waitControl.calls[waitIndex]!.release();
  await paused;
  await f.spool.waitForIdle();
  expect(f.release).toHaveBeenCalledOnce();
  expect(f.release.mock.calls[0]?.[0]).toMatchObject({ id: SID, claim: claim!.claim });
  expect(f.release.mock.calls[0]?.[1]).toMatchObject({ recordAttempt: false });
  expect(f.complete).not.toHaveBeenCalled();
  expect(f.fail).not.toHaveBeenCalled();
  expect(f.inbound).not.toHaveBeenCalled();
}
describe("real instance SMS consumer to private Host Gate", () => {
  it("seals at monitor admission time and checks the native claim through the real Gate before deferral", async () => {
    const f = await fixture();
    await f.spool.enqueue(f.form, f.proof);
    const [before] = await f.queue.listPending();
    const sealed = before!.payload as SmsIngressCapturePayloadV2;
    expect(sealed).toMatchObject({
      version: 2,
      form: f.form,
      capsule: {
        received_at: TIME,
        permission: { profil_id: "sms-demo", revision_profil: 7 },
      },
    });
    expect(before!.receivedAt).toBe(TIME);
    f.clock.mockReturnValue(TIME + 100);
    f.spool.start();
    await settle(f, 0);
    expect(f.resolutions).toEqual([expect.objectContaining({ status: "received" })]);
    expect(f.rejectedResolutions).toEqual([]);
    expect(f.calls).toHaveLength(1);
    expect(f.calls[0]!.tool).toBe("opsys_runtime_lire_reception_sms");
    const command = validateSmsCommand(f.calls[0]!.args, "opsys_runtime_lire_reception_sms");
    expect(command.commande.recu_le).toBe(new Date(TIME).toISOString());
    expect(command.commande.texte).toBe(f.form.Body);
    expect(command.commande_sha256).toBe(sealed.capsule.commande_sha256);
    expect(command.permission).toEqual(sealed.capsule.permission);
    expect((await f.queue.listPending())[0]).toMatchObject({
      id: SID,
      payload: sealed,
      receivedAt: TIME,
      attempts: before!.attempts,
      laneKey: before!.laneKey,
    });
  });
  it("retains unknown, revoked and selected legacy entries without changing the original capsule or entering inbound", async () => {
    for (const mode of ["unknown", "revoked", "legacy"] as const) {
      const f = await fixture();
      try {
        if (mode === "legacy") {
          await f.queue.enqueue(
            SID,
            { version: 1, form: f.form },
            { receivedAt: TIME, laneKey: "sender:+15145550102" },
          );
        } else {
          await f.spool.enqueue(f.form, f.proof);
        }
        const [before] = await f.queue.listPending();
        if (mode === "unknown") {
          f.setUnknown();
        }
        if (mode === "revoked") {
          f.authority.revoke();
        }
        const waitIndex = waitControl.calls.length;
        f.spool.start();
        await settle(f, waitIndex);
        expect(f.resolutions).toEqual([
          { status: "unresolved", code: "M1-SMS-RECEPTION-NON-RESOLUE" },
        ]);
        expect(f.rejectedResolutions).toEqual([]);
        expect(f.calls).toHaveLength(mode === "unknown" ? 1 : 0);
        expect((await f.queue.listPending())[0]).toMatchObject({
          id: before!.id,
          payload: before!.payload,
          receivedAt: before!.receivedAt,
          attempts: before!.attempts,
          laneKey: before!.laneKey,
        });
      } finally {
        await f.cleanup();
      }
    }
  });
});

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const NATIVE_FIXTURE = path.join(REPO, "core/test/opsys-sms-native-fixture.py");
const NATIVE_PROFILE = "sms-demo";
const NATIVE_PRIVATE_TOKEN = "fictif-sms-native-private-token-2026";
const NATIVE_PUBLIC_TOKEN = "fictif-sms-native-public-token-2026";
const NATIVE_DEPARTMENTS = [
  "m01-front-office",
  "m02-revenue-crm",
  "m03-estimation",
  "m04-field-ops",
  "m05-financecore",
  "m06-material-control",
  "m07-marketing",
  "m08-analytics",
  "m09-strategic-intelligence",
  "m10-memoire",
];
const READ = "opsys_runtime_lire_reception_sms";
const RECEIVE = "opsys_runtime_recevoir_sms";
const LEAD_BODY = "Bonjour, mes gouttières fuient à Laval.";
const UNRESOLVED = { status: "unresolved", code: "M1-SMS-RECEPTION-NON-RESOLUE" };
const CLEANUP_UNCERTAIN = "MCP cleanup is uncertain";
// Technical bounds only: every oracle waits for an owned event, process state or spool deferral.
const NATIVE_STEP_DEADLINE_MS = 30_000;
const NATIVE_OUTPUT_BYTES = 1024 * 1024;

type NativeEvent = Readonly<Record<string, unknown>> & { readonly event: string };
type NativeChild = {
  child: ChildProcess;
  closed: boolean;
  events: NativeEvent[];
  stderr: Buffer[];
  bytes: number;
  pending: Buffer;
  listeners: Set<() => void>;
  failure?: Error;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the real Native M1 SMS composition");
  }
  return python;
}

function nativeEnv(home: string): NodeJS.ProcessEnv {
  // Closed environment: no inherited credentials, database URL or HOME override.
  return {
    OPSYS_HOME: home,
    TMPDIR: home,
    OPSYS_DEPARTMENTS: path.join(REPO, "departments"),
    OPSYS_CONTEXT_MCP_JETON: NATIVE_PRIVATE_TOKEN,
    OPSYS_MCP_JETON: NATIVE_PUBLIC_TOKEN,
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    PYTHONPATH: [
      path.join(REPO, "src"),
      ...NATIVE_DEPARTMENTS.map((name) => path.join(REPO, "departments", name, "src")),
    ].join(path.delimiter),
    LANG: "C.UTF-8",
    TZ: "UTC",
  };
}

function nativeDiagnostic(owned: NativeChild): string {
  return Buffer.concat(owned.stderr).toString("utf8").slice(-2_000);
}

function startNative(python: string, home: string, args: string[]): NativeChild {
  const child = spawn(python, [NATIVE_FIXTURE, ...args], {
    cwd: REPO,
    env: nativeEnv(home),
    stdio: ["ignore", "pipe", "pipe"],
  });
  const owned: NativeChild = {
    child,
    closed: false,
    events: [],
    stderr: [],
    bytes: 0,
    pending: Buffer.alloc(0),
    listeners: new Set(),
  };
  const notify = () => {
    for (const listener of Array.from(owned.listeners)) {
      listener();
    }
  };
  const fail = (error: Error) => {
    owned.failure ??= error;
    child.kill("SIGKILL");
    notify();
  };
  const bounded = (chunk: Buffer) => {
    owned.bytes += chunk.length;
    if (owned.bytes > NATIVE_OUTPUT_BYTES) {
      fail(new Error("fictive Native fixture output exceeded its byte bound"));
      return false;
    }
    return true;
  };
  // stdout is the fixture's JSON-lines protocol; a partial line is kept until its newline arrives.
  child.stdout?.on("data", (chunk: Buffer) => {
    if (!bounded(chunk)) {
      return;
    }
    let buffer = Buffer.concat([owned.pending, chunk]);
    for (let end = buffer.indexOf(0x0a); end >= 0; end = buffer.indexOf(0x0a)) {
      const line = buffer.subarray(0, end).toString("utf8");
      buffer = buffer.subarray(end + 1);
      let value: unknown;
      try {
        value = JSON.parse(line);
      } catch {
        value = undefined;
      }
      if (!isRecord(value) || typeof value.event !== "string" || value.fictif !== true) {
        fail(new Error("fictive Native fixture wrote a non-protocol stdout line"));
        return;
      }
      owned.events.push({ ...value, event: value.event });
    }
    owned.pending = buffer;
    notify();
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    if (bounded(chunk)) {
      owned.stderr.push(chunk);
    }
  });
  child.once("error", () => fail(new Error("fictive Native fixture could not start")));
  // "close" follows both process exit and EOF on its stdio pipes.
  child.once("close", () => {
    owned.closed = true;
    notify();
  });
  return owned;
}

function waitNative<T>(owned: NativeChild, select: () => T | undefined, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const detach = () => {
      clearTimeout(timer);
      owned.listeners.delete(check);
    };
    const failed = (error: Error) => {
      detach();
      reject(new Error(`${label}: ${error.message}\n${nativeDiagnostic(owned)}`));
    };
    const check = () => {
      if (owned.failure) {
        failed(owned.failure);
        return;
      }
      const value = select();
      if (value !== undefined) {
        detach();
        resolve(value);
      } else if (owned.closed) {
        failed(new Error("Native fixture closed first"));
      }
    };
    const timer = setTimeout(
      () => failed(new Error("technical deadline exceeded")),
      NATIVE_STEP_DEADLINE_MS,
    );
    owned.listeners.add(check);
    check();
  });
}

function waitClosed(owned: NativeChild, ms: number): Promise<boolean> {
  return new Promise((resolve) => {
    const done = (closed: boolean) => {
      clearTimeout(timer);
      owned.listeners.delete(check);
      resolve(closed);
    };
    const check = () => {
      if (owned.closed) {
        done(true);
      }
    };
    const timer = setTimeout(() => done(false), ms);
    owned.listeners.add(check);
    check();
  });
}

async function stopNative(owned: NativeChild): Promise<void> {
  for (const [signal, ms] of [
    ["SIGTERM", 5_000],
    ["SIGKILL", 2_000],
  ] as const) {
    if (owned.closed) {
      break;
    }
    owned.child.kill(signal);
    await waitClosed(owned, ms);
  }
  if (!owned.closed) {
    throw new Error("owned fictive Native process survived bounded TERM and KILL");
  }
  if (owned.failure) {
    throw owned.failure;
  }
}

it.each(["wait", "cleanup"])(
  "propagates a late Native fixture failure during %s",
  async (operation) => {
    // No OS child is spawned: exercise our lifetime owner with an already closed failed child.
    const owned: NativeChild = {
      child: new ChildProcess(),
      closed: true,
      events: [{ event: "ready" }],
      stderr: [],
      bytes: 0,
      pending: Buffer.alloc(0),
      listeners: new Set(),
      failure: new Error("fictive late Native fixture failure"),
    };
    const result =
      operation === "wait"
        ? waitNative(owned, () => owned.events[0], "late Native failure")
        : stopNative(owned);
    await expect(result).rejects.toThrow("fictive late Native fixture failure");
    expect(owned.listeners.size).toBe(0);
  },
);

async function runNative(python: string, home: string, args: string[]): Promise<NativeEvent> {
  const owned = startNative(python, home, args);
  try {
    const closed = await waitClosed(owned, NATIVE_STEP_DEADLINE_MS);
    const [event] = owned.events;
    if (
      !closed ||
      owned.failure ||
      owned.child.exitCode !== 0 ||
      owned.events.length !== 1 ||
      owned.pending.length > 0 ||
      !event
    ) {
      throw new Error(`fictive Native ${args[0]} failed\n${nativeDiagnostic(owned)}`);
    }
    return event;
  } finally {
    await stopNative(owned);
  }
}

function trustNativeCa(caPem: string): () => void {
  // Test-process trust for one fictive per-run CA; the Gate's HTTPS policy is unchanged.
  const previous = tls.getCACertificates("default");
  tls.setDefaultCACertificates([...previous, caPem]);
  return () => tls.setDefaultCACertificates(previous);
}

/** Independent expectation of the Gate's destination binding for this exact loopback target. */
function destinationSha256(url: string): string {
  const hash = createHash("sha256").update("opsys:m1:sms:destination:v1:", "ascii");
  for (const value of [`opsys_runtime_${NATIVE_PROFILE}`, "streamable-http", new URL(url).href]) {
    const bytes = Buffer.from(value, "utf8");
    hash.update(String(bytes.length) + ":", "ascii").update(bytes);
  }
  return hash.digest("hex");
}

function tableDigests(state: NativeEvent): Map<string, string> {
  if (!isRecord(state.tables)) {
    throw new Error("fictive Native census is invalid");
  }
  return new Map(
    Object.entries(state.tables).map(([name, table]) => {
      if (!isRecord(table) || typeof table.sha256 !== "string") {
        throw new Error("fictive Native census is invalid");
      }
      return [name, table.sha256];
    }),
  );
}

function changedTables(before: NativeEvent, after: NativeEvent): string[] {
  const initial = tableDigests(before);
  const final = tableDigests(after);
  expect([...final.keys()]).toEqual([...initial.keys()]);
  return [...initial.keys()].filter((name) => initial.get(name) !== final.get(name)).toSorted();
}

async function nativeComposition(options: { loseReceiveOnce?: boolean } = {}) {
  const python = requiredPython();
  const home = await fs.mkdtemp(path.join(os.tmpdir(), "sms-native-composition-fictif-"));
  const owned: NativeChild[] = [];
  cleanups.push(async () => {
    if (owned.some((child) => !child.closed)) {
      throw new Error("fictive Native child still open; temporary state preserved for diagnosis");
    }
    await fs.rm(home, { recursive: true, force: true });
  });
  expect(await runNative(python, home, ["prepare"])).toMatchObject({
    event: "prepared",
    profile_id: NATIVE_PROFILE,
    revision: 2,
    actif: true,
    compte_id: "default",
    account_sid: "AC" + "1".repeat(32),
  });
  const server = startNative(python, home, [
    "serve",
    ...(options.loseReceiveOnce ? ["--lose-receive-once"] : []),
  ]);
  owned.push(server);
  cleanups.push(async () => await stopNative(server));
  const ready = await waitNative(
    server,
    () => server.events.find((event) => event.event === "ready"),
    "fictive Native readiness",
  );
  const { port, ca_pem: caPem } = ready;
  if (
    typeof port !== "number" ||
    !Number.isSafeInteger(port) ||
    port <= 0 ||
    port > 65_535 ||
    typeof caPem !== "string"
  ) {
    throw new Error("fictive Native readiness is invalid");
  }
  expect(ready.lose_receive_once).toBe(options.loseReceiveOnce === true);
  const restoreCa = trustNativeCa(caPem);
  cleanups.push(async () => restoreCa());
  const target: NativeTarget = {
    url: `https://127.0.0.1:${port}/mcp/runtime/${NATIVE_PROFILE}`,
    token: NATIVE_PRIVATE_TOKEN,
    profileRevision: 2,
  };
  return {
    server,
    target,
    events: (predicate: (event: NativeEvent) => boolean, count: number, label: string) =>
      waitNative(
        server,
        () => {
          const matched = server.events.filter(predicate);
          return matched.length >= count ? matched : undefined;
        },
        label,
      ),
    toolRequests: () =>
      server.events.filter((event) => event.event === "request" && event.method === "tools/call"),
    toolResponses: () =>
      server.events.filter((event) => event.event === "response" && event.method === "tools/call"),
    inspect: async () => {
      const state = await runNative(python, home, ["inspect"]);
      expect(state.event).toBe("inspected");
      return state;
    },
    disable: async (revision: number) =>
      await runNative(python, home, ["disable", "--revision", String(revision)]),
  };
}

const isDelete = (event: NativeEvent) => event.event === "http" && event.method === "DELETE";

async function coreStateDir(): Promise<string> {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "sms-native-core-fictif-"));
  cleanups.push(async () => await fs.rm(directory, { recursive: true, force: true }));
  return directory;
}

function nextWait(index: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const detach = () => {
      clearTimeout(timer);
      waitControl.listeners.delete(check);
    };
    const check = () => {
      if (waitControl.calls.length > index) {
        detach();
        resolve();
      }
    };
    const timer = setTimeout(() => {
      detach();
      reject(new Error("fictive SMS spool deferral missed its technical deadline"));
    }, NATIVE_STEP_DEADLINE_MS);
    waitControl.listeners.add(check);
    check();
  });
}

function observeCaller() {
  // Transparent spy: the controller still gets no callTool; the original export runs unchanged.
  const caller = vi.spyOn(contexteMcp, "callOpsysMcpTool");
  return {
    clear: () => caller.mockClear(),
    trace: () =>
      caller.mock.calls.map(([call], index) => ({
        tool: call.tool,
        settled: caller.mock.settledResults[index],
      })),
  };
}

/** Classifies the caller's wrapped cause; cleanup uncertainty would have replaced it entirely. */
function transportOutcome(error: unknown): string | undefined {
  const cause = error instanceof Error ? error.cause : undefined;
  if (!(cause instanceof Error)) {
    return undefined;
  }
  if (cause.name === "AbortError") {
    return "deadline";
  }
  const code: unknown = Reflect.get(cause, "code");
  return code === -32001 ? "request-timeout" : code === -32000 ? "connection-closed" : undefined;
}

function receivedResolution(value: unknown) {
  if (
    !isRecord(value) ||
    value.status !== "received" ||
    !isRecord(value.command) ||
    !isRecord(value.receipt)
  ) {
    throw new Error("expected one received Gate resolution");
  }
  const command = validateSmsCommand(
    { version: 1, commande: value.command.commande, permission: value.command.permission },
    RECEIVE,
  );
  return { command, receipt: value.receipt };
}

describe("real Native M1 SMS receipt behind the Core Gate consumer", () => {
  it("receives over loopback TLS with the default caller, binds the exact receipt and stays deferred", async () => {
    const native = await nativeComposition();
    const before = await native.inspect();
    expect(before).toMatchObject({
      receipts: [],
      signals: 0,
      leads: 0,
      events: [],
      profile: { id: NATIVE_PROFILE, revision: 2, actif: true, supprime: false },
    });
    const caller = observeCaller();
    const f = await fixture({ native: native.target, body: LEAD_BODY });
    await f.spool.enqueue(f.form, f.proof);
    const [sealed] = await f.queue.listPending();
    const capsule = (sealed!.payload as SmsIngressCapturePayloadV2).capsule;
    expect(capsule).toMatchObject({
      received_at: TIME,
      compte_id: "default",
      permission: { profil_id: NATIVE_PROFILE, revision_profil: 2 },
      destination_sha256: destinationSha256(native.target.url),
    });
    f.clock.mockReturnValue(TIME + 100);
    f.spool.start();
    await settle(f, 0, () => nextWait(0));
    expect(f.rejectedResolutions).toEqual([]);
    expect(f.resolutions).toHaveLength(1);
    const { command, receipt } = receivedResolution(f.resolutions[0]);
    expect(command.commande).toMatchObject({
      compte_id: "default",
      account_sid: f.form.AccountSid,
      message_sid: SID,
      expediteur: f.form.From,
      destinataire: f.form.To,
      recu_le: new Date(TIME).toISOString(),
      texte: LEAD_BODY,
      agent_id: `opsys-agent-${NATIVE_PROFILE}`,
      session_key: `agent:opsys-agent-${NATIVE_PROFILE}:sms:direct:${f.form.From}`,
    });
    expect(command.permission).toEqual({
      profil_id: NATIVE_PROFILE,
      revision_profil: 2,
      outil_m1: "opsys_m1__m1_recevoir_message_canal",
    });
    expect(command.commande_sha256).toBe(capsule.commande_sha256);
    expect(receipt).toMatchObject({
      source: "sms:twilio",
      signal_id: "sms:" + SID,
      decision: "TRANSMETTRE_M2",
      lead_ligne_id: expect.stringMatching(/^[0-9a-f]{64}$/u),
      transfert_id: null,
    });
    expect(caller.trace()).toEqual([
      {
        tool: READ,
        settled: {
          type: "fulfilled",
          value: expect.objectContaining({
            operation: "lire",
            ok: true,
            etat: "absent",
            recu: null,
          }),
        },
      },
      {
        tool: RECEIVE,
        settled: {
          type: "fulfilled",
          value: expect.objectContaining({
            operation: "recevoir",
            ok: true,
            etat: "recu",
            intention_id: command.intention_id,
            arguments_sha256: command.arguments_sha256,
            recu: receipt,
          }),
        },
      },
    ]);
    const deletes = await native.events(isDelete, 2, "Native cleanup of both MCP sessions");
    expect(deletes.map((event) => event.status)).toEqual([200, 200]);
    const requests = native.toolRequests();
    expect(requests.map((event) => [event.name, event.selected_for_loss])).toEqual([
      [READ, false],
      [RECEIVE, false],
    ]);
    expect(new Set(deletes.map((event) => event.session))).toEqual(
      new Set(requests.map((event) => event.session)),
    );
    expect(native.toolResponses()).toEqual([
      expect.objectContaining({
        name: READ,
        status: 200,
        tool: { is_error: false, native: expect.objectContaining({ etat: "absent" }) },
      }),
      expect.objectContaining({
        name: RECEIVE,
        status: 200,
        tool: { is_error: false, native: expect.objectContaining({ etat: "recu", recu: receipt }) },
      }),
    ]);
    expect(
      native.server.events.filter((e) => e.event === "response_lost" || e.event === "loss_refused"),
    ).toEqual([]);
    const after = await native.inspect();
    expect(changedTables(before, after)).toEqual(["evenements_sortants", "registres_maillons"]);
    expect(after).toMatchObject({
      signals: 1,
      leads: 1,
      events: ["m1.lead_qualifie"],
      profile: { id: NATIVE_PROFILE, revision: 2, actif: true, supprime: false },
    });
    expect(after.receipts).toEqual([
      {
        horodatage: command.commande.recu_le,
        intention_id: command.intention_id,
        commande_sha256: command.commande_sha256,
        arguments_sha256: command.arguments_sha256,
        permission: command.permission,
        recu: receipt,
      },
    ]);
    expect((await f.queue.listPending())[0]).toMatchObject({
      id: SID,
      payload: sealed!.payload,
      receivedAt: TIME,
      attempts: sealed!.attempts,
      laneKey: sealed!.laneKey,
    });
    expect(f.authority.isCurrent()).toBe(true);
  }, 120_000);

  it("loses only the committed RECEIVE result over TCP, then a reopened Core READs that receipt without a second RECEIVE", async () => {
    const native = await nativeComposition({ loseReceiveOnce: true });
    const before = await native.inspect();
    const caller = observeCaller();
    const stateDir = await coreStateDir();
    const first = await fixture({ native: native.target, stateDir, body: LEAD_BODY });
    await first.spool.enqueue(first.form, first.proof);
    const [sealed] = await first.queue.listPending();
    first.clock.mockReturnValue(TIME + 100);
    first.spool.start();
    await settle(first, 0, () => nextWait(0));
    expect(first.resolutions).toEqual([UNRESOLVED]);
    expect(first.rejectedResolutions).toEqual([]);
    expect(first.authority.isCurrent()).toBe(true);

    const [lost] = await native.events(
      (event) => event.event === "response_lost" || event.event === "loss_refused",
      1,
      "selected RECEIVE response loss",
    );
    expect(lost).toMatchObject({
      event: "response_lost",
      tool: RECEIVE,
      status: 200,
      content_type: "text/event-stream",
      committed_independent_read: true,
      headers_forwarded: true,
      body_bytes_forwarded: 0,
      body_sha256: expect.stringMatching(/^[0-9a-f]{64}$/u),
    });
    expect(lost!.body_bytes_suppressed).toEqual(expect.any(Number));
    expect(Number(lost!.body_bytes_suppressed)).toBeGreaterThan(0);
    // Only the actual RECEIVE request id was selected; its real ACK was suppressed, not rebuilt.
    const requests = native.toolRequests();
    expect(requests.map((event) => [event.name, event.selected_for_loss])).toEqual([
      [READ, false],
      [RECEIVE, true],
    ]);
    expect(lost).toMatchObject({ rpc_id: requests[1]!.id, session: requests[1]!.session });
    const capsule = (sealed!.payload as SmsIngressCapturePayloadV2).capsule;
    const lostAck = lost!.ack;
    if (!isRecord(lostAck)) {
      throw new Error("the suppressed native RECEIVE ACK was not traced");
    }
    expect(lostAck).toMatchObject({
      version: 1,
      operation: "recevoir",
      ok: true,
      etat: "recu",
      commande_sha256: capsule.commande_sha256,
      permission: capsule.permission,
      recu: { decision: "TRANSMETTRE_M2", signal_id: "sms:" + SID },
    });
    expect(lost!.committed_events).toEqual(["m1.lead_qualifie"]);
    // No Native ACK for RECEIVE crossed the wire: neither the receipt nor a known M1-SMS-INCONNU.
    expect(native.toolResponses().map((event) => event.name)).toEqual([READ]);
    // The Core caller saw a transport failure after confirmed cleanup, not an uncertain disposal.
    const firstTrace = caller.trace();
    expect(firstTrace.map(({ tool }) => tool)).toEqual([READ, RECEIVE]);
    expect(firstTrace[0]!.settled).toEqual({
      type: "fulfilled",
      value: expect.objectContaining({ operation: "lire", ok: true, etat: "absent", recu: null }),
    });
    const failure = firstTrace[1]!.settled;
    expect(failure?.type).toBe("rejected");
    const failureError: unknown = failure?.value;
    expect(failureError).toBeInstanceOf(contexteMcp.OpsysContexteMcpError);
    expect(failureError instanceof Error ? failureError.message : "").not.toBe(CLEANUP_UNCERTAIN);
    expect(["deadline", "request-timeout", "connection-closed"]).toContain(
      transportOutcome(failureError),
    );
    const firstDeletes = await native.events(isDelete, 2, "Native cleanup after the lost result");
    expect(firstDeletes.map((event) => [event.session, event.status])).toEqual([
      [requests[0]!.session, 200],
      [lost!.session, 200],
    ]);

    const committed = await native.inspect();
    expect(changedTables(before, committed)).toEqual(["evenements_sortants", "registres_maillons"]);
    expect(committed).toMatchObject({ signals: 1, leads: 1, events: ["m1.lead_qualifie"] });
    expect(committed.receipts).toEqual([lost!.committed_receipt]);
    expect((await first.queue.listPending())[0]).toMatchObject({
      id: SID,
      payload: sealed!.payload,
      receivedAt: TIME,
      attempts: sealed!.attempts,
      laneKey: sealed!.laneKey,
    });

    // Clean Core close and reopen of the same queue database; Native keeps port and SQLite file.
    await first.cleanup();
    caller.clear();
    const reopened = await fixture({ native: native.target, stateDir, body: LEAD_BODY });
    expect((await reopened.queue.listPending())[0]).toMatchObject({
      id: SID,
      payload: sealed!.payload,
      receivedAt: TIME,
      attempts: sealed!.attempts,
      laneKey: sealed!.laneKey,
    });
    reopened.clock.mockReturnValue(TIME + 200);
    const waitIndex = waitControl.calls.length;
    reopened.spool.start();
    await settle(reopened, waitIndex, () => nextWait(waitIndex));
    expect(reopened.rejectedResolutions).toEqual([]);
    expect(reopened.resolutions).toHaveLength(1);
    const { command, receipt } = receivedResolution(reopened.resolutions[0]);
    expect(receipt).toEqual(lostAck.recu);
    expect(lostAck.intention_id).toBe(command.intention_id);
    expect(command.commande.recu_le).toBe(new Date(TIME).toISOString());
    expect(command.commande_sha256).toBe(capsule.commande_sha256);
    expect(command.permission).toEqual(capsule.permission);
    expect(caller.trace()).toEqual([
      {
        tool: READ,
        settled: {
          type: "fulfilled",
          value: expect.objectContaining({
            operation: "lire",
            ok: true,
            etat: "recu",
            recu: receipt,
          }),
        },
      },
    ]);
    await native.events(isDelete, 3, "Native cleanup after the recovery READ");
    expect(native.toolRequests().map((event) => event.name)).toEqual([READ, RECEIVE, READ]);
    expect(await native.inspect()).toEqual(committed);
    expect(reopened.authority.isCurrent()).toBe(true);
  }, 120_000);

  it("keeps the Core owner current when Native refuses a disabled profile on READ after a positive control", async () => {
    const native = await nativeComposition();
    const caller = observeCaller();
    const stateDir = await coreStateDir();
    const accepted = await fixture({ native: native.target, stateDir, body: LEAD_BODY });
    await accepted.spool.enqueue(accepted.form, accepted.proof);
    const [sealed] = await accepted.queue.listPending();
    accepted.clock.mockReturnValue(TIME + 100);
    accepted.spool.start();
    await settle(accepted, 0, () => nextWait(0));
    expect(accepted.resolutions).toHaveLength(1);
    const control = receivedResolution(accepted.resolutions[0]);
    expect(caller.trace().map(({ tool, settled }) => [tool, settled?.type])).toEqual([
      [READ, "fulfilled"],
      [RECEIVE, "fulfilled"],
    ]);
    await accepted.cleanup();
    await native.events(isDelete, 2, "Native cleanup after the positive control");

    expect(await native.disable(2)).toMatchObject({
      event: "disabled",
      profile_id: NATIVE_PROFILE,
      revision: 3,
      actif: false,
    });
    const disabled = await native.inspect();
    expect(disabled).toMatchObject({
      profile: { id: NATIVE_PROFILE, revision: 3, actif: false, supprime: false },
      signals: 1,
      leads: 1,
    });
    expect(disabled.receipts).toEqual([expect.objectContaining({ recu: control.receipt })]);

    caller.clear();
    const owner = await fixture({ native: native.target, stateDir, body: LEAD_BODY });
    expect(owner.authority.isCurrent()).toBe(true);
    owner.clock.mockReturnValue(TIME + 200);
    const waitIndex = waitControl.calls.length;
    owner.spool.start();
    await settle(owner, waitIndex, () => nextWait(waitIndex));
    expect(owner.resolutions).toEqual([UNRESOLVED]);
    expect(owner.rejectedResolutions).toEqual([]);
    // Core's live owner, claim and destination checks passed: the READ reached Native.
    expect(owner.authority.isCurrent()).toBe(true);
    const refusal = {
      version: 1,
      operation: "lire",
      ok: false,
      etat: "revision_perimee",
      code: "REJ-M1-SMS-REVISION-PERIMEE",
    };
    expect(caller.trace()).toEqual([
      { tool: READ, settled: { type: "fulfilled", value: refusal } },
    ]);
    await native.events(isDelete, 3, "Native cleanup after the refused READ");
    expect(native.toolRequests().map((event) => event.name)).toEqual([READ, RECEIVE, READ]);
    expect(native.toolResponses().at(-1)).toMatchObject({
      name: READ,
      status: 200,
      tool: { is_error: true, native: refusal },
    });
    expect(await native.inspect()).toEqual(disabled);
    expect((await owner.queue.listPending())[0]).toMatchObject({
      id: SID,
      payload: sealed!.payload,
      receivedAt: TIME,
      attempts: sealed!.attempts,
      laneKey: sealed!.laneKey,
    });
  }, 120_000);
});
