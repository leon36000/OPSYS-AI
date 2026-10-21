/** Passive plugin-local carrier only. The private Host validates all opaque inputs. */
import { createPluginRuntimeStore } from "openclaw/plugin-sdk/runtime-store";

export type OpsysSmsHostBridgeEntry = Readonly<{
  /** Passive frozen locator supplied by the Host; no authority is inferred here. */
  locator: object;
  invoke: (locator: object, input: unknown) => unknown;
}>;
type Registration = { token: symbol; entry: OpsysSmsHostBridgeEntry };
const store = createPluginRuntimeStore<Map<string, Registration>>({
  key: "opsys.sms.host.bridge.v1",
  errorMessage: "SMS Host bridge not installed",
});

export function installOpsysSmsHostBridge(
  accountId: string,
  entry: OpsysSmsHostBridgeEntry,
): Readonly<{ dispose: () => void }> {
  let registrations = store.tryGetRuntime();
  if (!registrations) {
    registrations = new Map();
    store.setRuntime(registrations);
  }
  const { locator, invoke } = entry;
  const token = Symbol("SMS Host bridge registration");
  registrations.set(accountId, { token, entry: Object.freeze({ locator, invoke }) });
  // Retain this owner's map, not whichever instance happens to invoke cleanup later.
  const capturedRegistrations = registrations;
  let disposed = false;
  return Object.freeze({
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      if (capturedRegistrations.get(accountId)?.token === token) {
        capturedRegistrations.delete(accountId);
      }
    },
  });
}

/** Lookup does not initialize a registry or turn a carrier into permission. */
export function getOpsysSmsHostBridge(accountId: string): OpsysSmsHostBridgeEntry | undefined {
  return store.tryGetRuntime()?.get(accountId)?.entry;
}
