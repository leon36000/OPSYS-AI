/** Private Host composition only; manager/SMS wiring and model adoption are separate. */
import path from "node:path";
import type { ChannelRuntimeContextRegistry } from "../channels/plugins/channel-runtime-surface.types.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../context-engine/opsys-contexte-mcp.js";
import type { PluginRegistry } from "../plugins/registry-types.js";
import {
  OPSYS_SMS_HOST_SELECTION_REFUSED,
  type OpsysSmsHostAuthority,
} from "./opsys-sms-host-authority.js";
import {
  createOpsysSmsIngressCapture,
  type OpsysSmsIngressCapture,
} from "./opsys-sms-ingress-capture.js";
import { createOpsysSmsReceiptGate } from "./opsys-sms-receipt-gate.js";

const CAPABILITY = "opsys.sms.host-controller.v1";
const UNRESOLVED = Object.freeze({
  status: "unresolved" as const,
  code: "M1-SMS-RECEPTION-NON-RESOLUE",
});
type Owner = PluginRegistry["channels"][number];
type ReceiptGate = ReturnType<typeof createOpsysSmsReceiptGate>;
export type OpsysSmsHostController = Readonly<{
  locator: object;
  resolveLocator: (value: unknown) => OpsysSmsHostController | null;
  capture: OpsysSmsIngressCapture["capture"];
  encodeCaptured: ReceiptGate["encodeCaptured"];
  resolveReceipt: ReceiptGate["resolveReceipt"];
  dispose: () => void;
}>;
export type CreateOpsysSmsHostControllerParams = {
  authority: OpsysSmsHostAuthority;
  owner: Owner;
  getCurrentOwner: () => Owner | undefined;
  /** Captured trusted Host getter, never a plugin-supplied structural registry. */
  getRuntimeContexts: () => ChannelRuntimeContextRegistry;
  getCurrentConfig: () => OpenClawConfig;
  getCurrentCredential: () => string;
  signal: AbortSignal;
  callTool?: typeof callOpsysMcpTool;
};
const controllers = new WeakMap<object, OpsysSmsHostController>();
function requireHost(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}

export function createOpsysSmsHostController(
  params: CreateOpsysSmsHostControllerParams,
): OpsysSmsHostController {
  // Copy callback identities before any asynchronous work can occur.
  const {
    authority,
    owner,
    getCurrentOwner,
    getRuntimeContexts,
    getCurrentConfig,
    getCurrentCredential,
    signal,
    callTool,
  } = params;
  const locator = Object.freeze({});
  let retired = false;
  let registered = false;
  let lease: { dispose: () => void } | undefined;
  const dispose = () => {
    if (retired) {
      return;
    }
    retired = true;
    controllers.delete(locator);
    signal.removeEventListener("abort", dispose);
    const ownLease = lease;
    lease = undefined;
    try {
      ownLease?.dispose();
    } catch {
      // Retirement stays closed even if a trusted Host cleanup fails.
    }
  };
  try {
    const { plugin, pluginId, origin, rootDir, source, captureReadAuthority } = owner;
    requireHost(plugin.id === "sms" && pluginId === "sms" && origin === "bundled");
    requireHost(typeof rootDir === "string" && path.isAbsolute(rootDir));
    requireHost(
      typeof source === "string" && source.length > 0 && typeof captureReadAuthority === "function",
    );
    const contexts = getRuntimeContexts();
    const register = contexts.register;
    const get = contexts.get;
    requireHost(typeof register === "function" && typeof get === "function");
    const credential = getCurrentCredential();
    requireHost(typeof credential === "string" && credential.length > 0);
    const selection = authority.captureSelection();
    const key = Object.freeze({
      channelId: "sms",
      accountId: selection.accountId,
      capability: CAPABILITY,
    });
    const assertCurrent = () => {
      try {
        signal.throwIfAborted();
        requireHost(!retired && getCurrentOwner() === owner && authority.isCurrent());
        requireHost(
          owner.plugin === plugin &&
            owner.pluginId === pluginId &&
            owner.origin === origin &&
            owner.rootDir === rootDir &&
            owner.source === source &&
            owner.captureReadAuthority === captureReadAuthority,
        );
        requireHost(
          getRuntimeContexts() === contexts &&
            contexts.get === get &&
            contexts.register === register,
        );
        requireHost(getCurrentCredential() === credential);
        requireHost(!registered || Reflect.apply(get, contexts, [key]) === locator);
      } catch {
        dispose();
        throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
      }
    };
    assertCurrent();
    const capture = createOpsysSmsIngressCapture({
      owner: { id: "sms", origin: "bundled", rootDir, source },
      selection,
      assertCurrent,
      getCurrentCredential,
    });
    const gate = createOpsysSmsReceiptGate({
      capture,
      profileId: selection.permission.profil_id,
      getCurrentConfig,
      assertCurrent,
      signal,
      ...(callTool ? { callTool } : {}),
    });
    const controller: OpsysSmsHostController = Object.freeze({
      locator,
      resolveLocator(value: unknown) {
        // WeakMap lookup executes no Proxy traps, including for revoked proxies.
        if (
          typeof value !== "object" ||
          value === null ||
          value !== locator ||
          controllers.get(value) !== controller
        ) {
          return null;
        }
        try {
          assertCurrent();
          return controller;
        } catch {
          return null;
        }
      },
      capture(input: unknown) {
        try {
          assertCurrent();
          return capture.capture(input);
        } catch {
          throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
        }
      },
      encodeCaptured(handle: unknown, receivedAt: number) {
        try {
          assertCurrent();
          return gate.encodeCaptured(handle, receivedAt);
        } catch {
          throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
        }
      },
      async resolveReceipt(
        payload: unknown,
        context: Parameters<ReceiptGate["resolveReceipt"]>[1],
      ) {
        try {
          assertCurrent();
          const result = await gate.resolveReceipt(payload, context);
          assertCurrent();
          return result;
        } catch {
          return UNRESOLVED;
        }
      },
      dispose,
    });
    // Register only the passive locator; callable controller and credential stay private.
    lease = Reflect.apply(register, contexts, [{ ...key, context: locator, abortSignal: signal }]);
    registered = true;
    signal.addEventListener("abort", dispose, { once: true });
    assertCurrent();
    controllers.set(locator, controller);
    return controller;
  } catch {
    dispose();
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}
