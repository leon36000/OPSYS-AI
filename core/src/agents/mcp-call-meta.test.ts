// OPSYS `_meta` ambient context (docs/architecture/IDEMPOTENCE.md §7 in OPSYS-AI): the
// AsyncLocalStorage primitive that carries `_meta` from `/tools/invoke` to the outbound MCP
// `tools/call`, without threading it as a parameter through `AnyAgentTool.execute` or
// `ServerMcpRuntime.callTool`.
import { describe, expect, it } from "vitest";
import { currentMcpCallMeta, withMcpCallMeta } from "./mcp-call-meta.js";

describe("mcp-call-meta", () => {
  it("is undefined outside any withMcpCallMeta scope", () => {
    expect(currentMcpCallMeta()).toBeUndefined();
  });

  it("exposes the meta object for the duration of the wrapped call", async () => {
    const meta = { "opsys/idempotencyKey": "k-1", "opsys/appareil": "tel-1" };
    const seen = await withMcpCallMeta(meta, async () => currentMcpCallMeta());
    expect(seen).toBe(meta);
    expect(currentMcpCallMeta()).toBeUndefined();
  });

  it("propagates across intermediate async hops (await, microtasks) inside the scope", async () => {
    const meta = { "opsys/role": "employee" };
    const seen = await withMcpCallMeta(meta, async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return currentMcpCallMeta();
    });
    expect(seen).toEqual(meta);
  });

  it("restores the previous scope after a nested call returns, never leaking inward or outward", async () => {
    const outer = { "opsys/idempotencyKey": "outer" };
    const inner = { "opsys/idempotencyKey": "inner" };
    const seenDuringInner = await withMcpCallMeta(outer, async () => {
      const nested = await withMcpCallMeta(inner, async () => currentMcpCallMeta());
      return { nested, afterNested: currentMcpCallMeta() };
    });
    expect(seenDuringInner.nested).toBe(inner);
    expect(seenDuringInner.afterNested).toBe(outer);
    expect(currentMcpCallMeta()).toBeUndefined();
  });

  it("clears the scope even when the wrapped call throws", async () => {
    await expect(
      withMcpCallMeta({ "opsys/idempotencyKey": "boom" }, async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    expect(currentMcpCallMeta()).toBeUndefined();
  });

  it("does not leak into a concurrent, unrelated async call", async () => {
    const meta = { "opsys/idempotencyKey": "concurrent" };
    const [inScope, outOfScope] = await Promise.all([
      withMcpCallMeta(meta, async () => {
        await new Promise((resolve) => setTimeout(resolve, 5));
        return currentMcpCallMeta();
      }),
      (async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
        return currentMcpCallMeta();
      })(),
    ]);
    expect(inScope).toBe(meta);
    expect(outOfScope).toBeUndefined();
  });
});
