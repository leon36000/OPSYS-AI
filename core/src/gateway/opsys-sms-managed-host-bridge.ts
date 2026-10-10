/** Private manager installation only; the SMS monitor consumes the carrier separately. */
import { types } from "node:util";
import {
  getPluginInstance,
  getPluginValueInstance,
  runPluginCleanup,
} from "../plugins/plugin-instance-scope.js";
import { loadPluginPublicArtifactModuleSync } from "../plugins/public-surface-loader.js";
import { getPluginRecordRegistry } from "../plugins/registry-lifecycle.js";
import type { PluginRegistry } from "../plugins/registry-types.js";
import { resolvePluginRuntimeRecord } from "../plugins/runtime-context.js";
import { withPluginRuntimeRegistryScope } from "../plugins/runtime/gateway-request-scope.js";
import { OPSYS_SMS_HOST_SELECTION_REFUSED } from "./opsys-sms-host-authority.js";
import { createOpsysSmsHostClaimAdapter } from "./opsys-sms-host-claim-adapter.js";
import { createOpsysSmsHostController } from "./opsys-sms-host-controller.js";

type ControllerParams = Parameters<typeof createOpsysSmsHostController>[0];
type Params = ControllerParams & {
  registry: PluginRegistry;
  accountId: string;
  stateDir: string;
  assertCurrent: () => void;
};
type Entry = Pick<ReturnType<typeof createOpsysSmsHostClaimAdapter>, "locator" | "invoke">;
type SmsApi = {
  installOpsysSmsHostBridge: (accountId: string, entry: Entry) => Readonly<{ dispose: () => void }>;
};
export type OpsysSmsManagedHostBridge = Readonly<{
  assertCurrent: () => void;
  dispose: () => void;
}>;
const nativePromiseThen = Promise.prototype.then;
function requireHost(value: unknown): asserts value {
  if (!value) {
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}
function synchronous(run: () => void) {
  const result: unknown = run();
  if (types.isPromise(result)) {
    void nativePromiseThen.call(result, undefined, () => undefined);
  }
  requireHost(result === undefined);
}

export function installOpsysSmsManagedHostBridge(params: Params): OpsysSmsManagedHostBridge {
  const {
    authority,
    owner,
    getCurrentOwner,
    getRuntimeContexts,
    getCurrentConfig,
    getCurrentCredential,
    signal,
    callTool,
    registry,
    accountId,
    stateDir,
    assertCurrent,
  } = params;
  const facts = {
    plugin: owner.plugin,
    pluginId: owner.pluginId,
    origin: owner.origin,
    rootDir: owner.rootDir,
    source: owner.source,
    captureReadAuthority: owner.captureReadAuthority,
    resolveChannelRuntime: owner.resolveChannelRuntime,
    borrowedRuntimeRecord: owner.borrowedRuntimeRecord,
  };
  let retired = false;
  let controller: ReturnType<typeof createOpsysSmsHostController> | undefined;
  let adapter: ReturnType<typeof createOpsysSmsHostClaimAdapter> | undefined;
  let carrier: Readonly<{ dispose: () => void }> | undefined;
  const dispose = () => {
    if (retired) {
      return;
    }
    retired = true;
    signal.removeEventListener("abort", onAbort);
    const ownCarrier = carrier;
    carrier = undefined;
    try {
      if (ownCarrier) {
        synchronous(() => runPluginCleanup(ownCarrier, () => ownCarrier.dispose()));
      }
    } catch {
      throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
    } finally {
      try {
        adapter?.dispose();
      } finally {
        controller?.dispose();
      }
    }
  };
  const onAbort = () => {
    try {
      dispose();
    } catch {
      /* Private resources are retired even if carrier cleanup fails. */
    }
  };
  try {
    requireHost(
      facts.pluginId === "sms" &&
        facts.plugin.id === "sms" &&
        facts.origin === "bundled" &&
        facts.rootDir,
    );
    const record =
      facts.borrowedRuntimeRecord ??
      withPluginRuntimeRegistryScope(registry, () =>
        resolvePluginRuntimeRecord({ pluginRoot: facts.rootDir!, pluginId: "sms" }),
      );
    requireHost(record && record.id === "sms");
    const effectiveRegistry = getPluginRecordRegistry(registry, record);
    const instance = getPluginInstance(record);
    const outerInstance = getPluginValueInstance(facts.plugin);
    requireHost(
      instance &&
        outerInstance &&
        record.origin === "bundled" &&
        record.rootDir === facts.rootDir &&
        record.source === facts.source,
    );
    const instanceOwner = instance.owner;
    const outerOwner = outerInstance.owner;
    requireHost(instanceOwner && instanceOwner.record === record && outerOwner);
    const recordFacts = {
      id: record.id,
      origin: record.origin,
      source: record.source,
      rootDir: record.rootDir,
    };
    const check = () => {
      try {
        signal.throwIfAborted();
        requireHost(!retired);
        synchronous(assertCurrent);
        requireHost(authority.isCurrent() && getCurrentOwner() === owner);
        requireHost(
          owner.plugin === facts.plugin &&
            owner.pluginId === facts.pluginId &&
            owner.origin === facts.origin &&
            owner.rootDir === facts.rootDir &&
            owner.source === facts.source &&
            owner.captureReadAuthority === facts.captureReadAuthority &&
            owner.resolveChannelRuntime === facts.resolveChannelRuntime &&
            owner.borrowedRuntimeRecord === facts.borrowedRuntimeRecord,
        );
        requireHost(
          record.enabled &&
            record.status === "loaded" &&
            record.id === recordFacts.id &&
            record.origin === recordFacts.origin &&
            record.source === recordFacts.source &&
            record.rootDir === recordFacts.rootDir &&
            getPluginRecordRegistry(registry, record) === effectiveRegistry &&
            effectiveRegistry.plugins.includes(record) &&
            getPluginInstance(record) === instance &&
            instance.owner === instanceOwner &&
            instanceOwner.record === record &&
            !instanceOwner.revoked &&
            outerInstance.owner === outerOwner &&
            !outerOwner.revoked &&
            instance.acceptingCalls &&
            !instance.lifecycle.signal.aborted &&
            outerInstance.acceptingCalls &&
            !outerInstance.lifecycle.signal.aborted &&
            getPluginValueInstance(owner.plugin) === outerInstance,
        );
        requireHost(
          withPluginRuntimeRegistryScope(effectiveRegistry, () =>
            resolvePluginRuntimeRecord({ pluginRoot: recordFacts.rootDir!, pluginId: "sms" }),
          ) === record,
        );
        requireHost(!controller || controller.resolveLocator(controller.locator) === controller);
      } catch {
        try {
          dispose();
        } catch {}
        throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
      }
    };
    check();
    const api = withPluginRuntimeRegistryScope(effectiveRegistry, () =>
      loadPluginPublicArtifactModuleSync<SmsApi>({
        pluginRoot: recordFacts.rootDir!,
        artifactBasename: "api.js",
        origin: "bundled",
        pluginId: "sms",
      }),
    );
    requireHost(
      getPluginValueInstance(api) === instance &&
        typeof api.installOpsysSmsHostBridge === "function",
    );
    const install = api.installOpsysSmsHostBridge;
    controller = createOpsysSmsHostController({
      authority,
      owner,
      getCurrentOwner,
      getRuntimeContexts,
      getCurrentConfig,
      getCurrentCredential,
      signal,
      ...(callTool ? { callTool } : {}),
    });
    adapter = createOpsysSmsHostClaimAdapter({
      controller,
      accountId,
      stateDir,
      signal,
      assertCurrent: check,
    });
    check();
    carrier = Reflect.apply(install, api, [
      accountId,
      Object.freeze({ locator: adapter.locator, invoke: adapter.invoke }),
    ]);
    requireHost(carrier && typeof carrier.dispose === "function");
    signal.addEventListener("abort", onAbort, { once: true });
    check();
    return Object.freeze({
      assertCurrent() {
        check();
      },
      dispose,
    });
  } catch {
    try {
      dispose();
    } catch {}
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}
