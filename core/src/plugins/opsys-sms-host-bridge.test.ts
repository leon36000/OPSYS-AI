import { afterEach, describe, expect, it, vi } from "vitest";
import * as smsApi from "../../extensions/sms/api.js";
import { createPluginRuntimeStore } from "../plugin-sdk/runtime-store.js";
import { getPluginValueInstance } from "./plugin-instance-scope.js";
import { PluginInstance } from "./plugin-instance.js";

const instances: PluginInstance[] = [];
function managed() {
  const instance = new PluginInstance("sms");
  instances.push(instance);
  return { instance, api: instance.wrap(smsApi) };
}
function entry(label: string) {
  const locator = Object.freeze({});
  const invoke = vi.fn((seen: object, input: unknown) => ({
    label,
    sameLocator: seen === locator,
    input,
  }));
  return Object.freeze({ locator, invoke });
}
afterEach(async () => {
  for (const instance of instances.splice(0)) {
    await instance.dispose();
  }
});

describe("SMS public API Host carrier, not authority", () => {
  it("exports installation and lookup through the documented SMS API", () => {
    expect(smsApi).toHaveProperty("installOpsysSmsHostBridge");
    expect(smsApi).toHaveProperty("getOpsysSmsHostBridge");
  });
  it("leaves the uninstalled named fallback empty", () => {
    const store = createPluginRuntimeStore<unknown>({
      key: "opsys.sms.host.bridge.v1",
      errorMessage: "fictif absent",
    });
    expect(store.tryGetRuntime()).toBeNull();
    expect(smsApi.getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(store.tryGetRuntime()).toBeNull();
    expect(getPluginValueInstance(smsApi)).toBeUndefined();
  });
  it("isolates two real same-id instances and two accounts", () => {
    const a = managed(),
      b = managed(),
      ae = entry("A-default"),
      as = entry("A-support"),
      be = entry("B-default");
    const ad = a.instance.run(() => a.api.installOpsysSmsHostBridge("default", ae));
    const asd = a.instance.run(() => a.api.installOpsysSmsHostBridge("support", as));
    const bd = b.instance.run(() => b.api.installOpsysSmsHostBridge("default", be));
    expect(a.api.getOpsysSmsHostBridge("default")?.locator).toBe(ae.locator);
    expect(a.api.getOpsysSmsHostBridge("support")?.locator).toBe(as.locator);
    expect(b.api.getOpsysSmsHostBridge("default")?.locator).toBe(be.locator);
    expect(b.api.getOpsysSmsHostBridge("support")).toBeUndefined();
    expect(smsApi.getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(getPluginValueInstance(a.api)).toBe(a.instance);
    expect(getPluginValueInstance(b.api)).toBe(b.instance);
    ad.dispose();
    asd.dispose();
    bd.dispose();
  });
  it("preserves the passive locator but returns an owned callable view, also after await", async () => {
    const a = managed(),
      raw = entry("A");
    const dispose = a.api.installOpsysSmsHostBridge("default", raw);
    const seen = await a.instance.run(async () => {
      await Promise.resolve();
      return a.api.getOpsysSmsHostBridge("default");
    });
    expect(seen?.locator).toBe(raw.locator);
    expect(seen?.invoke).not.toBe(raw.invoke);
    expect(getPluginValueInstance(seen!.invoke)).toBe(a.instance);
    const input = Object.freeze({ fictif: true, payload: "opaque" });
    expect(seen?.invoke(seen.locator, input)).toEqual({ label: "A", sameLocator: true, input });
    expect(raw.invoke).toHaveBeenCalledTimes(1);
    expect(raw.invoke.mock.calls[0]?.[1]).toBe(input);
    dispose.dispose();
  });
  it("captures field identities once rather than adopting mutations of the input entry", () => {
    const a = managed(),
      original = entry("original");
    const mutable = { locator: original.locator, invoke: original.invoke };
    const dispose = a.api.installOpsysSmsHostBridge("default", mutable);
    mutable.locator = Object.freeze({});
    mutable.invoke = entry("replacement").invoke;
    const seen = a.api.getOpsysSmsHostBridge("default");
    expect(seen?.locator).toBe(original.locator);
    expect(seen?.invoke(seen.locator, null)).toEqual({
      label: "original",
      sameLocator: true,
      input: null,
    });
    dispose.dispose();
  });
  it("keeps replacement registered when the same entry object is installed twice", () => {
    const a = managed(),
      same = entry("same-object");
    const first = a.api.installOpsysSmsHostBridge("default", same);
    const second = a.api.installOpsysSmsHostBridge("default", same);
    first.dispose();
    first.dispose();
    expect(a.api.getOpsysSmsHostBridge("default")?.locator).toBe(same.locator);
    second.dispose();
    second.dispose();
    expect(a.api.getOpsysSmsHostBridge("default")).toBeUndefined();
  });
  it("keeps the captured owner of a disposer rather than clearing a second instance", () => {
    const a = managed(),
      b = managed(),
      ae = entry("A"),
      be = entry("B");
    // Use a raw disposer so the B frame cannot silently re-enter A through a view.
    const first = a.instance.run(() => smsApi.installOpsysSmsHostBridge("default", ae));
    const second = b.api.installOpsysSmsHostBridge("default", be);
    b.instance.run(() => first.dispose());
    expect(a.api.getOpsysSmsHostBridge("default")).toBeUndefined();
    expect(b.api.getOpsysSmsHostBridge("default")?.locator).toBe(be.locator);
    second.dispose();
  });
  it("closes a retained callable view after its actual instance retires", async () => {
    const a = managed(),
      raw = entry("A");
    a.api.installOpsysSmsHostBridge("default", raw);
    const retained = a.api.getOpsysSmsHostBridge("default");
    await a.instance.dispose();
    expect(() => retained?.invoke(raw.locator, {})).toThrow();
    expect(() => a.api.getOpsysSmsHostBridge("default")).toThrow();
    expect(raw.invoke).not.toHaveBeenCalled();
  });
  it("never overwrites the existing SMS runtime-store slot", () => {
    const a = managed(),
      oldStore = createPluginRuntimeStore<unknown>({
        pluginId: "sms",
        errorMessage: "fictif SMS runtime",
      });
    const sentinel = Object.freeze({ fictif: true, existingRuntime: "unchanged" });
    a.instance.run(() => oldStore.setRuntime(sentinel));
    expect(a.instance.run(() => smsApi.getSmsRuntime())).toBe(sentinel);
    const dispose = a.api.installOpsysSmsHostBridge("default", entry("bridge"));
    expect(a.instance.run(() => smsApi.getSmsRuntime())).toBe(sentinel);
    dispose.dispose();
    expect(a.instance.run(() => smsApi.getSmsRuntime())).toBe(sentinel);
  });
});
