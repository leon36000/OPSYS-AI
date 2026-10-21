// OPSYS context-engine registration installs the engine under core ownership (PLAN T3.3-suite).
import { createOpsysContextEngine, OPSYS_CONTEXT_ENGINE_ID } from "./opsys-contexte-engine.js";
import { registerContextEngineForOwner } from "./registry.js";

// Registers the OPSYS engine under the core owner. It is only reachable through
// `plugins.slots.contextEngine: "opsys"`; registering it changes nothing for any other selection.
// Refresh is allowed so tests/bootstrap can re-register after module-state resets.
export function registerOpsysContextEngine(): void {
  registerContextEngineForOwner(
    OPSYS_CONTEXT_ENGINE_ID,
    (ctx) => createOpsysContextEngine(ctx.config),
    "core",
    { allowSameOwnerRefresh: true },
  );
}
