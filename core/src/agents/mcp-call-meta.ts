// Ambient MCP `_meta` for the OPSYS-owned tool call currently in flight through
// `POST /tools/invoke` (device identity, idempotency key, caller role — OPSYS-AI
// docs/architecture/IDEMPOTENCE.md §7, docs/architecture/MOBILE.md). Host-minted by
// `tools-invoke-shared.ts`, carried by AsyncLocalStorage on the exact pattern of
// `withOperatorToolGatewayAuthority` (./server-plugin-in-process-dispatch.js): never accepted as
// a tool argument a model could forge, omit, or read back, and never threaded as an extra
// parameter through `AnyAgentTool.execute` or `ServerMcpRuntime.callTool`, which stay unchanged.
import { AsyncLocalStorage } from "node:async_hooks";
import { resolveGlobalSingleton } from "../shared/global-singleton.js";

// One storage per process, same pattern as `shared/async-work-scope.ts`: a module loaded twice
// (duplicated build chunks, a reset test module registry) must still share the slot, or the
// `/tools/invoke` side and the MCP runtime side would read two different stores and `_meta`
// would silently never reach the wire.
const mcpCallMetaStorage = resolveGlobalSingleton(
  Symbol.for("opsys.mcpCallMeta"),
  () =>
    new AsyncLocalStorage<{
      meta: Record<string, unknown>;
      assertBeforeEffect?: () => void;
    }>(),
);

/** Runs `run` with `meta` as the ambient MCP `_meta` for any `tools/call` it triggers. */
export async function withMcpCallMeta<T>(
  meta: Record<string, unknown>,
  run: () => Promise<T>,
  assertBeforeEffect?: () => void,
): Promise<T> {
  const inheritedGuard = mcpCallMetaStorage.getStore()?.assertBeforeEffect;
  const guard =
    inheritedGuard && assertBeforeEffect
      ? () => {
          inheritedGuard();
          assertBeforeEffect();
        }
      : (inheritedGuard ?? assertBeforeEffect);
  return await mcpCallMetaStorage.run({ meta, assertBeforeEffect: guard }, run);
}

/** The ambient MCP `_meta` for the tool call in flight, or undefined outside one. */
export function currentMcpCallMeta(): Record<string, unknown> | undefined {
  return mcpCallMetaStorage.getStore()?.meta;
}

/** Host-only synchronous authority fence; never serialized into MCP metadata. */
export function assertMcpCallAuthorityCurrent(): void {
  mcpCallMetaStorage.getStore()?.assertBeforeEffect?.();
}
