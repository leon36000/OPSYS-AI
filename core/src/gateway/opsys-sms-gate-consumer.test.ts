import { createHmac } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
// Test-only boundary exception: exercise the existing consumer without adding a public API.
import { createSmsIngressSpool } from "../../extensions/sms/src/ingress-spool.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import { isLiveLocalIngressDrainOwner } from "../channels/message/ingress-claim-owner.js";
import { createChannelIngressQueue } from "../channels/message/ingress-queue.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
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

type Call = Parameters<typeof callOpsysMcpTool>[0];
type SpoolParams = Parameters<typeof createSmsIngressSpool>[0];
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const waitControl = vi.hoisted(() => ({
  calls: [] as Array<{ ms: number; release: () => void }>,
}));
vi.mock("openclaw/plugin-sdk/runtime-env", async (importOriginal) => ({
  ...(await importOriginal<typeof import("openclaw/plugin-sdk/runtime-env")>()),
  sleepWithAbort: (ms: number, signal?: AbortSignal) =>
    new Promise<void>((resolve) => {
      waitControl.calls.push({ ms, release: resolve });
      if (signal?.aborted) {
        resolve();
      } else {
        signal?.addEventListener("abort", () => resolve(), { once: true });
      }
    }),
}));
const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const cleanup of cleanups.splice(0).toReversed()) {
    await cleanup();
  }
  waitControl.calls.length = 0;
  vi.restoreAllMocks();
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
async function fixture() {
  const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "sms-consumer-core-fictif-"));
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
            profileRevision: 7,
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
          url: "https://mcp-fictif.example/runtime/sms-demo",
          headers: { Authorization: "Bearer fictif-consumer-only" },
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
    // Only RPC/ACK is doubled: no network, Python receipt or provider effect is claimed.
    callTool: async (call) => {
      call.beforeRequest?.();
      calls.push(call);
      if (unknown) {
        throw new Error("fictif ACK unavailable");
      }
      return ack(call);
    },
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
          (error) => {
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
    await fs.rm(stateDir, { recursive: true, force: true });
  };
  cleanups.push(cleanup);
  const form = {
    AccountSid: accountSid,
    MessageSid: SID,
    From: "+15145550102",
    To: sms.fromNumber,
    Body: "Québec e\u0301 😀\nexact",
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
async function settle(f: Awaited<ReturnType<typeof fixture>>, waitIndex: number) {
  await vi.waitFor(() => expect(waitControl.calls).toHaveLength(waitIndex + 1));
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
