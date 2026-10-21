// OPSYS context engine registration (OPSYS-AI PLAN T3.3-suite): registered by the same initialization
// as the legacy engine, selected only by `plugins.slots.contextEngine`, never by default.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ensureContextEnginesInitialized } from "./init.js";
import { OPSYS_CONTEXT_ENGINE_ID } from "./opsys-contexte-engine.js";
import { getContextEngineRegistration, resolveContextEngine } from "./registry.js";
import { captureContextEngineRegistryStateForTests } from "./registry.test-support.js";

let restoreContextEngineRegistry: () => void;

beforeAll(() => {
  restoreContextEngineRegistry = captureContextEngineRegistryStateForTests();
});

afterAll(() => {
  restoreContextEngineRegistry();
});

describe("OPSYS context engine registration", () => {
  it("registers under core ownership next to the legacy engine, and does so idempotently", () => {
    ensureContextEnginesInitialized();
    ensureContextEnginesInitialized();

    expect(getContextEngineRegistration(OPSYS_CONTEXT_ENGINE_ID)).toMatchObject({
      owner: "core",
      lifecycle: "runtime",
    });
    expect(getContextEngineRegistration("legacy")).toMatchObject({ owner: "core" });
  });

  it("leaves the default selection untouched: without the slot, the legacy engine runs", async () => {
    ensureContextEnginesInitialized();

    const engine = await resolveContextEngine({});

    expect(engine.info.id).toBe("legacy");
  });

  it("is selected by plugins.slots.contextEngine and by nothing else", async () => {
    ensureContextEnginesInitialized();

    const engine = await resolveContextEngine({
      plugins: { slots: { contextEngine: OPSYS_CONTEXT_ENGINE_ID } },
    });

    expect(engine.info.id).toBe(OPSYS_CONTEXT_ENGINE_ID);
    expect(engine.info.ownsCompaction).toBe(false);
  });
});
