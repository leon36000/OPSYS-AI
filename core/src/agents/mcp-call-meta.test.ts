// OPSYS `_meta` ambient context (docs/architecture/IDEMPOTENCE.md §7 in OPSYS-AI): the
// AsyncLocalStorage primitive that carries `_meta` from `/tools/invoke` to the outbound MCP
// `tools/call`, without threading it as a parameter through `AnyAgentTool.execute` or
// `ServerMcpRuntime.callTool`.
import { describe, expect, it } from "vitest";
import {
  assertMcpCallAuthorityCurrent,
  currentMcpCallMeta,
  withMcpCallMeta,
} from "./mcp-call-meta.js";

describe("mcp-call-meta", () => {
  it("keeps a parent's live authority in nested metadata scopes and clears it on exit", async () => {
    let current = true;
    let checks = 0;
    const refusal = new Error("Synthetic parent authority revoked");
    await withMcpCallMeta(
      { synthetic: "outer" },
      async () => {
        await withMcpCallMeta({ synthetic: "inner" }, async () => {
          await Promise.resolve();
          assertMcpCallAuthorityCurrent();
          expect(currentMcpCallMeta()).toStrictEqual({ synthetic: "inner" });
          current = false;
          expect(assertMcpCallAuthorityCurrent).toThrow(refusal);
        });
        expect(currentMcpCallMeta()).toStrictEqual({ synthetic: "outer" });
        expect(assertMcpCallAuthorityCurrent).toThrow(refusal);
      },
      () => {
        checks += 1;
        if (!current) {
          throw refusal;
        }
      },
    );
    expect(checks).toBe(3);
    expect(assertMcpCallAuthorityCurrent).not.toThrow();
    expect(currentMcpCallMeta()).toBeUndefined();
  });

  it("composes a nested guard with its parent instead of replacing the admitted authority", async () => {
    const checks: string[] = [];
    await withMcpCallMeta(
      { synthetic: "outer" },
      () =>
        withMcpCallMeta(
          { synthetic: "inner" },
          async () => {
            assertMcpCallAuthorityCurrent();
          },
          () => checks.push("inner"),
        ),
      () => checks.push("outer"),
    );
    expect(checks).toStrictEqual(["outer", "inner"]);
  });

  it("isolates guards across concurrent async calls", async () => {
    const calls: string[] = [];
    const entered = Promise.withResolvers<void>();
    const release = Promise.withResolvers<void>();
    const blocked = withMcpCallMeta(
      { synthetic: "blocked" },
      async () => {
        entered.resolve();
        await release.promise;
        assertMcpCallAuthorityCurrent();
      },
      () => {
        calls.push("blocked");
        throw new Error("Synthetic refusal");
      },
    );
    const rejection = expect(blocked).rejects.toThrow("Synthetic refusal");
    await entered.promise;
    await withMcpCallMeta(
      { synthetic: "allowed" },
      async () => {
        await Promise.resolve();
        assertMcpCallAuthorityCurrent();
      },
      () => calls.push("allowed"),
    );
    release.resolve();
    await rejection;
    expect(calls).toStrictEqual(["allowed", "blocked"]);
    expect(assertMcpCallAuthorityCurrent).not.toThrow();
  });

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
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
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
        await new Promise((resolve) => {
          setTimeout(resolve, 5);
        });
        return currentMcpCallMeta();
      }),
      (async () => {
        await new Promise((resolve) => {
          setTimeout(resolve, 0);
        });
        return currentMcpCallMeta();
      })(),
    ]);
    expect(inScope).toBe(meta);
    expect(outOfScope).toBeUndefined();
  });
});
