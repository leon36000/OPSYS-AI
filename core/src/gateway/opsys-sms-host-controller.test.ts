import { createHmac } from "node:crypto";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import { createTaskScopedChannelRuntime } from "../infra/channel-runtime-context.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import * as loader from "../plugins/public-surface-loader.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { createChannelRuntimeContextRegistry } from "../plugins/runtime/channel-runtime-contexts.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import { createOpsysSmsHostAuthority } from "./opsys-sms-host-authority.js";

type Params = Parameters<
  typeof import("./opsys-sms-host-controller.js").createOpsysSmsHostController
>[0];
type Call = Parameters<typeof callOpsysMcpTool>[0];
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const REFUSED = "REJ-M1-SMS-HOST-SELECTION";
const UNRESOLVED = { status: "unresolved", code: "M1-SMS-RECEPTION-NON-RESOLUE" };
const CAPABILITY = "opsys.sms.host-controller.v1";

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
async function create(f = fixture()) {
  const module = await import("./opsys-sms-host-controller.js");
  return module.createOpsysSmsHostController(f.params);
}
afterEach(() => vi.restoreAllMocks());

describe("private Host SMS controller", () => {
  it("exports the real standalone constructor", async () => {
    await expect(import("./opsys-sms-host-controller.js")).resolves.toHaveProperty(
      "createOpsysSmsHostController",
    );
  });
  it("registers a passive locator and resolves only its own canonical live value", async () => {
    const f = fixture(),
      controller = await create(f);
    expect(Object.isFrozen(controller.locator)).toBe(true);
    expect(Reflect.ownKeys(controller.locator)).toEqual([]);
    expect(f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY })).toBe(
      controller.locator,
    );
    expect(controller.resolveLocator(controller.locator)).toBe(controller);
    expect(f.captureReadAuthority).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(controller)).not.toContain("controller-hmac-fictif");
    expect(JSON.stringify(controller)).not.toContain("Authorization");
    controller.dispose();
  });
  it("refuses foreign, cloned and revoked Proxy locators with zero traps without poisoning its locator", async () => {
    const f = fixture(),
      c = await create(f),
      other = await create(fixture());
    const trap = vi.fn(() => {
      throw new Error("fictif proxy trap must not execute");
    });
    const proxy = new Proxy(c.locator, { get: trap, ownKeys: trap });
    const revoked = Proxy.revocable(c.locator, {});
    revoked.revoke();
    for (const input of [
      other.locator,
      { ...c.locator },
      proxy,
      revoked.proxy,
      { resolveLocator: c.resolveLocator },
    ]) {
      expect(c.resolveLocator(input)).toBeNull();
    }
    expect(trap).not.toHaveBeenCalled();
    expect(c.resolveLocator(c.locator)).toBe(c);
    c.dispose();
    other.dispose();
  });
  it("preserves passive locator identity through a real managed PluginInstance view", async () => {
    const f = fixture(),
      c = await create(f);
    const instance = new PluginInstance("sms");
    const view = instance.wrap({ readLocator: () => c.locator });
    expect(instance.run(() => view.readLocator())).toBe(c.locator);
    expect(c.resolveLocator(instance.run(() => view.readLocator()))).toBe(c);
    c.dispose();
    await instance.dispose();
  });
  it.each([
    "owner",
    "registry",
    "source",
    "callback",
    "grant",
    "lifetime",
    "task",
    "P",
    "credential",
    "abort",
  ])("closes sticky after %s changes", async (kind) => {
    const f = fixture(),
      c = await create(f);
    if (kind === "owner") {
      f.replaceOwner();
    }
    if (kind === "registry") {
      f.replaceRegistry();
    }
    if (kind === "source") {
      f.owner.source = path.join(f.owner.rootDir, "other.ts");
    }
    if (kind === "callback") {
      Object.assign(f.owner, { captureReadAuthority: () => () => true });
    }
    if (kind === "grant") {
      f.loseGrant();
    }
    if (kind === "lifetime") {
      f.loseLifetime();
    }
    if (kind === "task") {
      f.loseTask();
    }
    if (kind === "P") {
      f.marker.profileRevision++;
    }
    if (kind === "credential") {
      f.changeCredential();
    }
    if (kind === "abort") {
      f.signalOwner.abort();
    }
    expect(c.resolveLocator(c.locator)).toBeNull();
    expect(() => c.capture(f.input)).toThrow(REFUSED);
    expect(await c.resolveReceipt({}, f.claimContext)).toEqual(UNRESOLVED);
    expect(f.calls).toHaveLength(0);
    c.dispose();
  });
  it("captures callbacks rather than borrowing a replacement getter", async () => {
    const f = fixture(),
      c = await create(f);
    f.replaceOwner();
    f.params.getCurrentOwner = () => f.owner;
    expect(c.resolveLocator(c.locator)).toBeNull();
    c.dispose();
  });
  it("maps a private owner callback fault to the constant without exposing details", async () => {
    const f = fixture();
    f.params.getCurrentOwner = () => {
      throw new Error("private-fictif-callback-detail");
    };
    await expect(create(f)).rejects.toThrow(REFUSED);
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
  });
  it("does not erase a replacement context when its old lease is disposed", async () => {
    const f = fixture(),
      c = await create(f),
      replacement = Object.freeze({});
    const lease = f.contexts.register({
      channelId: "sms",
      accountId: "default",
      capability: CAPABILITY,
      context: replacement,
    });
    expect(c.resolveLocator(c.locator)).toBeNull();
    c.dispose();
    c.dispose();
    expect(f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY })).toBe(
      replacement,
    );
    lease.dispose();
  });
  it("disposes its own registration when the real task scope is disposed", async () => {
    const f = fixture(),
      c = await create(f);
    f.scoped.dispose();
    expect(c.resolveLocator(c.locator)).toBeNull();
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
    c.dispose();
  });
  it("requires an already published authority and does not fall back to legacy", async () => {
    const f = fixture(false);
    await expect(create(f)).rejects.toThrow(REFUSED);
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
  });
  it("captures real HMAC and follows strict absent READ then RECEIVE with the same frozen args", async () => {
    const f = fixture(),
      c = await create(f);
    f.respond(async (call) => ack(call, call.tool === "opsys_runtime_lire_reception_sms"));
    const handle = c.capture(f.input),
      payload = c.encodeCaptured(handle, TIME);
    expect((await c.resolveReceipt(payload, f.claimContext)).status).toBe("received");
    expect(f.calls.map((call) => call.tool)).toEqual([
      "opsys_runtime_lire_reception_sms",
      "opsys_runtime_recevoir_sms",
    ]);
    expect(f.calls[0].args).toEqual(f.calls[1].args);
    c.dispose();
  });
  it("retains unknown and recovers lost receiving ACK by READ without a second receive", async () => {
    const f = fixture(),
      c = await create(f);
    let stored = false;
    f.respond(async (call) => {
      if (call.tool === "opsys_runtime_recevoir_sms") {
        stored = true;
        throw new Error("fictif lost ACK");
      }
      return ack(call, !stored);
    });
    const payload = c.encodeCaptured(c.capture(f.input), TIME);
    expect(await c.resolveReceipt(payload, f.claimContext)).toEqual(UNRESOLVED);
    expect((await c.resolveReceipt(payload, f.claimContext)).status).toBe("received");
    expect(f.calls.map((call) => call.tool)).toEqual([
      "opsys_runtime_lire_reception_sms",
      "opsys_runtime_recevoir_sms",
      "opsys_runtime_lire_reception_sms",
    ]);
    c.dispose();
  });
  it("refuses owner withdrawal after an RPC await without claiming received", async () => {
    const f = fixture(),
      c = await create(f);
    f.respond(async (call) => {
      await Promise.resolve();
      f.replaceOwner();
      return ack(call);
    });
    const payload = c.encodeCaptured(c.capture(f.input), TIME);
    expect(await c.resolveReceipt(payload, f.claimContext)).toEqual(UNRESOLVED);
    expect(c.resolveLocator(c.locator)).toBeNull();
    expect(f.calls).toHaveLength(1);
    c.dispose();
  });
});
