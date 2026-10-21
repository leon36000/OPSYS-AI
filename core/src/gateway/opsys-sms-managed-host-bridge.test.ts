import { createHmac } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { validateSmsCommand } from "../agents/opsys-runtime-sms-contract.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import { createTaskScopedChannelRuntime } from "../infra/channel-runtime-context.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { createPluginModuleLoader } from "../plugins/loader-module-runtime.js";
import { getPluginInstance } from "../plugins/plugin-instance-scope.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import * as loader from "../plugins/public-surface-loader.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import {
  revokePluginRecord,
  withPluginRegistryPreparationScope,
} from "../plugins/registry-lifecycle.js";
import { stageActivePluginRegistry, resetPluginRuntimeStateForTest } from "../plugins/runtime.js";
import { createChannelRuntimeContextRegistry } from "../plugins/runtime/channel-runtime-contexts.js";
import { createPluginRecord } from "../plugins/status.test-helpers.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import { createOpsysSmsHostAuthority } from "./opsys-sms-host-authority.js";

type Params = Parameters<
  typeof import("./opsys-sms-host-controller.js").createOpsysSmsHostController
>[0];
type Call = Parameters<typeof callOpsysMcpTool>[0];
const TIME = Date.UTC(2026, 9, 10, 12, 0, 0, 123);
const SID = "SM" + "2".repeat(32);
const REFUSED = "REJ-M1-SMS-HOST-SELECTION";
const CAPABILITY = "opsys.sms.host-controller.v1";

const instances: PluginInstance[] = [];
const bindings: Array<{ dispose(): void }> = [];
// All credentials and ACK references here are fictitious RAM fixtures, never SQL/HTTP claims.
function fixture(published = true, physicalRoot?: string) {
  vi.spyOn(loader, "loadBundledPluginPublicArtifactModuleFromCandidatesSync").mockReturnValue({
    verifyTwilioSignature: smsApi.verifyTwilioSignature,
  });
  const rootDir = physicalRoot ?? path.resolve("extensions/sms");
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
  const record = createPluginRecord({
    id: "sms",
    rootDir,
    source: path.join(rootDir, "index.ts"),
    origin: "bundled",
    imported: true,
  });
  registry.plugins.push(record);
  if (physicalRoot) {
    createPluginModuleLoader({
      devSourceRoot: process.cwd(),
      pluginSdkResolution: "source",
      installNativeSdkResolver: false,
    })(record.source, { record, rootDir, registry });
  }
  const instance = physicalRoot
    ? getPluginInstance(record)!
    : new PluginInstance("sms", { record, registry });
  // Explicit lightweight source-loader leaf for nonphysical cases only.
  if (!physicalRoot) {
    instance.bindModuleLoader(
      () => smsApi,
      (p) => [path.join(rootDir, "index.ts"), path.join(rootDir, "api.ts")].includes(p),
    );
  }
  instances.push(instance);
  const observedSlots: unknown[] = [];
  const owner = {
    pluginId: "sms",
    origin: "bundled" as const,
    plugin: instance.wrap(
      createChannelTestPluginBase({
        id: "sms",
        config: {
          listAccountIds: () => {
            observedSlots.push(smsApi.getOpsysSmsHostBridge("default")?.locator);
            return ["default"];
          },
        },
      }),
    ),
    rootDir,
    source: path.join(rootDir, "index.ts"),
    captureReadAuthority,
  };
  registry.channels.push(owner);
  stageActivePluginRegistry(registry, "fictif-managed", "default");
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
    registry,
    record,
    instance,
    observedSlots,
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

async function install(f = fixture()) {
  const module = await import("./opsys-sms-managed-host-bridge.js");
  const binding = module.installOpsysSmsManagedHostBridge({
    ...f.params,
    registry: f.registry,
    accountId: "default",
    stateDir: path.resolve("fictif-no-db"),
    assertCurrent: () => {
      if (!f.authority.isCurrent()) {
        throw new Error("fictif-current-lost");
      }
    },
  });
  bindings.push(binding);
  return { f, binding };
}
afterEach(async () => {
  for (const b of bindings.splice(0).toReversed()) {
    b.dispose();
  }
  for (const instance of instances.splice(0)) {
    await instance.dispose();
  }
  resetPluginRuntimeStateForTest();
  vi.restoreAllMocks();
});
describe("private managed SMS Host installer", () => {
  it("exports the private installer", async () => {
    await expect(import("./opsys-sms-managed-host-bridge.js")).resolves.toHaveProperty(
      "installOpsysSmsManagedHostBridge",
    );
  });
  it("installs an actual controller/adapter in the ordinary managed API slot only", async () => {
    const { f, binding } = await install();
    const api = f.instance.wrap(smsApi);
    const entry = api.getOpsysSmsHostBridge("default");
    expect(entry?.locator).toBe(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    );
    expect(entry?.invoke).toBeTypeOf("function");
    binding.assertCurrent();
    expect(smsApi.getOpsysSmsHostBridge("default")).toBeUndefined();
    binding.dispose();
    expect(api.getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
  });
  it("refuses library fallback before installing or granting a controller", async () => {
    const f = fixture();
    vi.spyOn(loader, "loadPluginPublicArtifactModuleSync").mockReturnValue(smsApi);
    await expect(install(f)).rejects.toThrow(REFUSED);
    expect(smsApi.getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
  });
  it("refuses an API owned by another real same-id instance", async () => {
    const f = fixture();
    const b = new PluginInstance("sms");
    instances.push(b);
    vi.spyOn(loader, "loadPluginPublicArtifactModuleSync").mockReturnValue(b.wrap(smsApi));
    await expect(install(f)).rejects.toThrow(REFUSED);
    expect(f.instance.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
  });
  it("closes sticky on exact owner replacement and retains no borrowed replacement grant", async () => {
    const { f, binding } = await install();
    f.replaceOwner();
    expect(() => binding.assertCurrent()).toThrow(REFUSED);
    expect(f.instance.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
  });
  it("retires its own resources on abort and makes old disposal harmless after reinstall", async () => {
    const f = fixture();
    const first = await install(f);
    const old = f.instance.wrap(smsApi).getOpsysSmsHostBridge("default");
    const second = await install(f);
    const current = f.instance.wrap(smsApi).getOpsysSmsHostBridge("default");
    expect(current?.locator).not.toBe(old?.locator);
    first.binding.dispose();
    expect(f.instance.wrap(smsApi).getOpsysSmsHostBridge("default")?.locator).toBe(
      current?.locator,
    );
    f.signalOwner.abort();
    expect(f.instance.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(() => second.binding.assertCurrent()).toThrow(REFUSED);
  });
  it("cleans controller/adapter even when a managed carrier disposer throws", async () => {
    const f = fixture();
    const source = {
      ...smsApi,
      installOpsysSmsHostBridge: () => ({
        dispose() {
          throw new Error("fictif-secret-cleanup");
        },
      }),
    };
    vi.spyOn(loader, "loadPluginPublicArtifactModuleSync").mockReturnValue(f.instance.wrap(source));
    const { binding } = await install(f);
    expect(() => binding.dispose()).toThrow(REFUSED);
    expect(
      f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
    ).toBeUndefined();
    expect(() => binding.assertCurrent()).toThrow(REFUSED);
  });
  it("retires its carrier when the captured runtime context registry is replaced", async () => {
    const { f, binding } = await install();
    f.replaceRegistry();
    expect(() => binding.assertCurrent()).toThrow(REFUSED);
    expect(f.instance.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
  });
  it("installs into the donor slot across a real double membrane instead of the prepared local slot", async () => {
    const f = fixture();
    const target = createEmptyPluginRegistry();
    const localRecord = createPluginRecord({
      id: "sms",
      origin: "bundled",
      rootDir: f.record.rootDir,
      source: f.record.source,
      imported: true,
    });
    target.plugins.push(localRecord);
    const local = new PluginInstance("sms", { record: localRecord, registry: target });
    instances.push(local);
    local.bindModuleLoader(
      () => smsApi,
      (p) => p === path.join(f.record.rootDir!, "api.ts"),
    );
    const adopted = { ...local.wrap(f.instance.wrap(f.owner)), borrowedRuntimeRecord: f.record };
    target.channels.push(adopted);
    await withPluginRegistryPreparationScope(target, async () => {
      const { installOpsysSmsManagedHostBridge } =
        await import("./opsys-sms-managed-host-bridge.js");
      const binding = installOpsysSmsManagedHostBridge({
        ...f.params,
        owner: adopted,
        getCurrentOwner: () => adopted,
        registry: target,
        accountId: "default",
        stateDir: path.resolve("fictif-no-db"),
        assertCurrent: () => {
          if (!f.authority.isCurrent()) {
            throw new Error("fictif-current-lost");
          }
        },
      });
      bindings.push(binding);
      const donorEntry = f.instance.wrap(smsApi).getOpsysSmsHostBridge("default");
      expect(donorEntry).toBeDefined();
      expect(local.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
      adopted.plugin.config.listAccountIds({});
      expect(f.observedSlots.at(-1)).toBe(donorEntry?.locator);
      binding.assertCurrent();
      binding.dispose();
    });
  });
  it.each(["donor", "outer"] as const)(
    "retires the carrier when its %s owner is revoked without lifecycle shutdown",
    async (revokedOwner) => {
      const f = fixture();
      const target = createEmptyPluginRegistry();
      const localRecord = createPluginRecord({
        id: "sms",
        origin: "bundled",
        rootDir: f.record.rootDir,
        source: f.record.source,
        imported: true,
      });
      target.plugins.push(localRecord);
      const local = new PluginInstance("sms", { record: localRecord, registry: target });
      instances.push(local);
      local.bindModuleLoader(
        () => smsApi,
        (p) => p === path.join(f.record.rootDir!, "api.ts"),
      );
      const adopted = { ...local.wrap(f.instance.wrap(f.owner)), borrowedRuntimeRecord: f.record };
      target.channels.push(adopted);
      await withPluginRegistryPreparationScope(target, async () => {
        const { installOpsysSmsManagedHostBridge } =
          await import("./opsys-sms-managed-host-bridge.js");
        const binding = installOpsysSmsManagedHostBridge({
          ...f.params,
          owner: adopted,
          getCurrentOwner: () => adopted,
          registry: target,
          accountId: "default",
          stateDir: path.resolve("fictif-no-db"),
          assertCurrent: () => {
            if (!f.authority.isCurrent()) {
              throw new Error("fictif-current-lost");
            }
          },
        });
        bindings.push(binding);
        const donorEntry = f.instance.wrap(smsApi).getOpsysSmsHostBridge("default");
        expect(donorEntry).toBeDefined();
        expect(local.wrap(smsApi).getOpsysSmsHostBridge("default")).toBeUndefined();
        const revokedInstance = revokedOwner === "donor" ? f.instance : local;
        const revokedSignal = revokedInstance.lifecycle.signal;
        revokePluginRecord(
          revokedOwner === "donor" ? f.registry : target,
          revokedOwner === "donor" ? f.record : localRecord,
        );
        expect(revokedInstance.acceptingCalls).toBe(true);
        expect(revokedSignal.aborted).toBe(false);
        expect(f.authority.isCurrent()).toBe(true);
        expect(() => binding.assertCurrent()).toThrow(REFUSED);
        expect(
          f.instance.runCleanup(() => smsApi.getOpsysSmsHostBridge("default")),
        ).toBeUndefined();
        expect(
          f.contexts.get({ channelId: "sms", accountId: "default", capability: CAPABILITY }),
        ).toBeUndefined();
        binding.dispose();
      });
    },
  );
  it("rejects a prepared-local API when the exact effective record is borrowed donor", async () => {
    const f = fixture();
    const target = createEmptyPluginRegistry();
    const record = createPluginRecord({
      id: "sms",
      origin: "bundled",
      rootDir: f.record.rootDir,
      source: f.record.source,
      imported: true,
    });
    target.plugins.push(record);
    const local = new PluginInstance("sms", { record, registry: target });
    instances.push(local);
    const adopted = { ...local.wrap(f.instance.wrap(f.owner)), borrowedRuntimeRecord: f.record };
    target.channels.push(adopted);
    vi.spyOn(loader, "loadPluginPublicArtifactModuleSync").mockReturnValue(local.wrap(smsApi));
    await withPluginRegistryPreparationScope(target, async () => {
      const { installOpsysSmsManagedHostBridge } =
        await import("./opsys-sms-managed-host-bridge.js");
      expect(() =>
        installOpsysSmsManagedHostBridge({
          ...f.params,
          owner: adopted,
          getCurrentOwner: () => adopted,
          registry: target,
          accountId: "default",
          stateDir: path.resolve("fictif-no-db"),
          assertCurrent: () => {},
        }),
      ).toThrow(REFUSED);
    });
  });
  it("uses the real public loader with a tiny physical exact-copy carrier fixture", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "fictif-sms-managed-carrier-"));
    try {
      fs.writeFileSync(path.join(root, "package.json"), '{"type":"module"}');
      fs.writeFileSync(path.join(root, "index.ts"), "export default {};\n");
      fs.writeFileSync(
        path.join(root, "api.ts"),
        'export {installOpsysSmsHostBridge,getOpsysSmsHostBridge} from "./carrier.js";\n',
      );
      fs.copyFileSync(
        path.resolve("extensions/sms/src/opsys-host-bridge.ts"),
        path.join(root, "carrier.ts"),
      );
      const f = fixture(true, root);
      const { binding } = await install(f);
      binding.assertCurrent();
      const nativeApi = f.instance.loadModule(path.join(root, "api.ts")) as Pick<
        typeof smsApi,
        "getOpsysSmsHostBridge"
      >;
      expect(nativeApi.getOpsysSmsHostBridge("default")).toBeDefined();
      binding.dispose();
      expect(nativeApi.getOpsysSmsHostBridge("default")).toBeUndefined();
      await f.instance.dispose();
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});
