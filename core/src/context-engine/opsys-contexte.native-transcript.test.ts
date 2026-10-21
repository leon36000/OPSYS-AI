import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { expect, it, vi } from "vitest";
import {
  createContextEngineLogicalTurnLease,
  selectContextEngineForTranscriptHost,
  type ContextEngineLogicalTurnLease,
} from "../agents/harness/context-engine-logical-turn.js";
import { runAgentHarnessBeforeMessageWriteHook } from "../agents/harness/hook-helpers.js";
import type { OpenClawConfig } from "../config/config.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { PluginRegistryInspectionResources } from "../plugins/registry-inspection-resources.js";
import { retireInspectionInstances } from "../plugins/registry-inspection.test-support.js";
import { withPluginRuntimeRegistryScope } from "../plugins/runtime/gateway-request-scope.js";
import { createUserTurnTranscriptRecorder } from "../sessions/user-turn-transcript.js";
import { AsyncWorkScope } from "../shared/async-work-scope.js";
import {
  evaluateContextEngineHostSupport,
  OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
} from "./host-compat.js";
import { LegacyContextEngine } from "./legacy.js";
import { readOpsysContexteConfig } from "./opsys-contexte-config.js";
import {
  createOpsysContextEngine,
  OpsysContextEngine,
  readDefaultOpsysTranscriptSource,
} from "./opsys-contexte-engine.js";
import { opsysContexteGuardStore } from "./opsys-contexte-garde.js";
import { ENVELOPE_PAQUET, PAQUET_M10 } from "./opsys-contexte.test-support.js";
import {
  getContextEngineRegistration,
  readHostOwnedOpsysTranscript,
  registerContextEngineInRegistry,
  resolveContextEngine,
} from "./registry.js";
import { captureContextEngineRegistryStateForTests } from "./registry.test-support.js";

const nativeOriginMcp = vi.hoisted(() => ({ callTool: vi.fn() }));
vi.mock("./opsys-contexte-mcp.js", () => ({ callOpsysMcpTool: nativeOriginMcp.callTool }));

it("preserves a configured packet origin change on a live native transcript owner", async () => {
  // Entirely fictitious file config and packet fixture; MCP stops at its mocked caller boundary.
  // The default factory receives no injected dependencies or altered engine methods.
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "opsys-native-origin-fictif-"));
  const sessionKey = "agent:opsys-agent-fictif:main";
  let wrapped: Awaited<ReturnType<typeof resolveContextEngine>> | undefined;
  try {
    vi.stubEnv("OPENCLAW_CONFIG_PATH", path.join(root, "openclaw.json"));
    await fs.writeFile(path.join(root, "openclaw.json"), "{}\n");
    await fs.mkdir(path.join(root, "opsys"));
    const originConfig = {
      version: 2,
      actif: true,
      niveaux: { m3_lire_devis: "N0" },
      cibles: {},
      agents: {
        "opsys-agent-fictif": {
          depot: [],
          serveur_contexte: "opsys_context_m03-estimation",
          origine_paquet: "m03-estimation",
        },
      },
    };
    await fs.writeFile(path.join(root, "opsys", "contexte.json"), JSON.stringify(originConfig));
    const settings = readOpsysContexteConfig();
    expect(settings.kind).toBe("enabled");
    if (settings.kind !== "enabled") {
      throw new Error("Fictitious native origin configuration was not admitted");
    }
    expect(settings.config.packetOrigins?.get("opsys-agent-fictif")).toBe("m03-estimation");
    const raw = createOpsysContextEngine(undefined);
    const registry = createEmptyPluginRegistry();
    registerContextEngineInRegistry(registry, "legacy", () => new LegacyContextEngine(), "core");
    registerContextEngineInRegistry(registry, "opsys", () => raw, "core");
    wrapped = await withPluginRuntimeRegistryScope(registry, () =>
      resolveContextEngine({ plugins: { slots: { contextEngine: "opsys" } } }),
    );
    expect(readDefaultOpsysTranscriptSource(raw)).toBe("unaltered");
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    const params = {
      sessionId: "fictif-native-origin",
      sessionKey,
      messages: [{ role: "user" as const, content: "Fictitious origin selection", timestamp: 1 }],
      prompt: "Fictitious request.\naffaire_id: LEAD-001",
      tokenBudget: 100_000,
    };
    nativeOriginMcp.callTool.mockResolvedValueOnce(ENVELOPE_PAQUET);
    const initial = await wrapped.assemble(params);
    expect(initial.systemPromptAddition).not.toContain("contexte d'entreprise indisponible");
    expect(initial.systemPromptAddition).toContain("Toujours confirmer la longueur");
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    originConfig.agents["opsys-agent-fictif"].origine_paquet = "m01-front-office";
    originConfig.agents["opsys-agent-fictif"].serveur_contexte = "opsys_context_m01-front-office";
    await fs.writeFile(path.join(root, "opsys", "contexte.json"), JSON.stringify(originConfig));
    const replacementSettings = readOpsysContexteConfig();
    expect(replacementSettings.kind).toBe("enabled");
    if (replacementSettings.kind !== "enabled") {
      throw new Error("Fictitious replacement packet origin was not admitted");
    }
    expect(replacementSettings.config.packetOrigins?.get("opsys-agent-fictif")).toBe(
      "m01-front-office",
    );
    nativeOriginMcp.callTool.mockResolvedValueOnce(ENVELOPE_PAQUET);
    const foreign = await wrapped.assemble(params);
    expect(foreign.systemPromptAddition).toContain("contexte d'entreprise indisponible");
    expect(foreign.systemPromptAddition).not.toContain("Toujours confirmer la longueur");
    expect(opsysContexteGuardStore.get(sessionKey)?.kind).toBe("unavailable");
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    nativeOriginMcp.callTool.mockResolvedValueOnce({
      ...ENVELOPE_PAQUET,
      resultat: {
        ...PAQUET_M10,
        confidentialite: { ...PAQUET_M10.confidentialite, agent: "m01-front-office" },
      },
    });
    const canonical = await wrapped.assemble(params);
    expect(canonical.systemPromptAddition).not.toContain("contexte d'entreprise indisponible");
    expect(canonical.systemPromptAddition).toContain("Toujours confirmer la longueur");
    expect(canonical.messages).toBe(params.messages);
    expect(opsysContexteGuardStore.get(sessionKey)).toMatchObject({
      kind: "ready",
      affaireId: "LEAD-001",
    });
    expect(nativeOriginMcp.callTool).toHaveBeenCalledTimes(3);
    expect(nativeOriginMcp.callTool).toHaveBeenLastCalledWith(
      expect.objectContaining({ server: "opsys_context_m01-front-office" }),
    );
    expect(readDefaultOpsysTranscriptSource(raw)).toBe("unaltered");
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
  } finally {
    await wrapped?.dispose?.();
    opsysContexteGuardStore.clear();
    nativeOriginMcp.callTool.mockReset();
    vi.unstubAllEnvs();
    await fs.rm(root, { recursive: true, force: true });
  }
});

it("keeps the native OPSYS engine configured for a recorder-backed embedded turn", async () => {
  // Fictitious selection-only fixture: no Session, persisted admission, model or MCP call.
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "opsys-native-transcript-fictif-"));
  const restoreRegistry = captureContextEngineRegistryStateForTests();
  let lease: ContextEngineLogicalTurnLease | undefined;
  try {
    const config: OpenClawConfig = { plugins: { slots: { contextEngine: "opsys" } } };
    const sessionId = "fictif-native-transcript";
    const sessionKey = "agent:opsys-agent-m03-fictif:main";
    const recorder = createUserTurnTranscriptRecorder({
      input: { text: "Fictitious recorder-backed context selection." },
      target: {
        agentId: "opsys-agent-m03-fictif",
        sessionId,
        sessionKey,
        sessionEntry: undefined,
        storePath: path.join(root, "sessions", "sessions.json"),
        cwd: root,
        config,
      },
      beforeMessageWrite: runAgentHarnessBeforeMessageWriteHook,
      errorContext: "native OPSYS transcript selection regression",
    });
    lease = await createContextEngineLogicalTurnLease({
      identity: { runId: "fictif-native-transcript-run", sessionId },
      config,
      agentDir: path.join(root, "agent"),
      workspaceDir: root,
    });
    expect(getContextEngineRegistration("opsys")).toMatchObject({ owner: "core" });
    expect(lease.effectiveEngineId).toBe("opsys");
    expect(lease.degraded).toBe(false);
    expect(recorder.hasPersisted()).toBe(false);
    expect(recorder.getAdmissionReceipt()).toBeUndefined();
    expect(
      evaluateContextEngineHostSupport({
        contextEngineInfo: lease.engine.info,
        operation: "agent-run",
        host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
      }).ok,
    ).toBe(true);

    const selected = selectContextEngineForTranscriptHost({
      lease,
      host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
      operation: "agent-run",
      recorder,
    });

    expect(lease.effectiveEngineId, lease.degradedReason).toBe("opsys");
    expect(selected.mode).toBe("configured");
    expect(lease.degraded).toBe(false);
    expect(recorder.hasPersisted()).toBe(false);
    expect(recorder.getAdmissionReceipt()).toBeUndefined();
  } finally {
    try {
      await lease?.dispose();
    } finally {
      restoreRegistry();
      await fs.rm(root, { recursive: true, force: true });
    }
  }
});

it("does not brand constructors, injected dependencies, subclasses, copies or proxies", () => {
  class Derived extends OpsysContextEngine {}
  const native = createOpsysContextEngine(undefined);
  expect(readDefaultOpsysTranscriptSource(native)).toBe("unaltered");
  for (const foreign of [
    new OpsysContextEngine(undefined),
    new Derived(undefined),
    createOpsysContextEngine(undefined, {}),
    Object.assign({}, native),
    new Proxy(native, {}),
  ]) {
    expect(readDefaultOpsysTranscriptSource(foreign)).toBe("absent");
    expect(readHostOwnedOpsysTranscript(foreign)).toBe("absent");
  }
});

it.each(["method", "info", "commitTurn"] as const)(
  "refuses a default source after %s replacement without accepting fake durable declarations",
  async (change) => {
    const raw = createOpsysContextEngine(undefined);
    const registry = createEmptyPluginRegistry();
    registerContextEngineInRegistry(registry, "legacy", () => new LegacyContextEngine(), "core");
    registerContextEngineInRegistry(registry, "opsys", () => raw, "core");
    const wrapped = await withPluginRuntimeRegistryScope(registry, () =>
      resolveContextEngine({ plugins: { slots: { contextEngine: "opsys" } } }),
    );
    try {
      expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
      if (change === "method") {
        Object.defineProperty(raw, "afterTurn", { value: async () => {}, configurable: true });
      } else if (change === "info") {
        Object.defineProperty(raw, "info", {
          value: {
            ...raw.info,
            transcriptSemantics: {
              currentTurnFence: "before-current-turn-entry-v1",
              turnAdvancementIdempotency: "atomic-idempotent-v1",
            },
          },
          configurable: true,
        });
      } else {
        Object.defineProperty(raw, "commitTurn", { value: async () => {}, configurable: true });
      }
      expect(readDefaultOpsysTranscriptSource(raw)).toBe("altered");
      expect(readHostOwnedOpsysTranscript(wrapped)).toBe("unavailable");
    } finally {
      await wrapped.dispose?.();
    }
  },
);

it.each([
  "ingestBatch",
  "bootstrap",
  "maintain",
  "prepareSubagentSpawn",
  "onSubagentEnded",
] as const)("refuses a default source after adding optional %s", async (method) => {
  const raw = createOpsysContextEngine(undefined);
  const registry = createEmptyPluginRegistry();
  registerContextEngineInRegistry(registry, "legacy", () => new LegacyContextEngine(), "core");
  registerContextEngineInRegistry(registry, "opsys", () => raw, "core");
  const wrapped = await withPluginRuntimeRegistryScope(registry, () =>
    resolveContextEngine({ plugins: { slots: { contextEngine: "opsys" } } }),
  );
  try {
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    expect(Reflect.get(raw, method)).toBeUndefined();
    Object.defineProperty(raw, method, { value: async () => {}, configurable: true });
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("unavailable");
    expect(readDefaultOpsysTranscriptSource(raw)).toBe("altered");
  } finally {
    await wrapped.dispose?.();
  }
});

it.each(["dispose", "info", "lease-dispose"] as const)(
  "revalidates native ownership between selection and begin after %s",
  async (change) => {
    const restore = captureContextEngineRegistryStateForTests();
    const lease = await createContextEngineLogicalTurnLease({
      identity: { runId: "fictif", sessionId: "fictif" },
      config: { plugins: { slots: { contextEngine: "opsys" } } },
      warn: () => {},
    });
    try {
      expect(
        lease.selectForHost({
          host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
          operation: "agent-run",
          requiresDurableCommit: true,
        }).mode,
      ).toBe("configured");
      expect(readHostOwnedOpsysTranscript(lease.engine)).toBe("live");
      if (change === "dispose") {
        await lease.engine.dispose?.();
      } else if (change === "info") {
        Object.defineProperty(lease.engine.info, "transcriptSemantics", {
          value: {
            currentTurnFence: "before-current-turn-entry-v1",
            turnAdvancementIdempotency: "atomic-idempotent-v1",
          },
          configurable: true,
        });
      } else {
        await lease.dispose();
      }
      expect(() => lease.begin()).toThrow(/unavailable|disposed/);
    } finally {
      await lease.dispose();
      restore();
    }
  },
);

it("keeps incompatible hosts degraded and permits healthy native begin", async () => {
  const restore = captureContextEngineRegistryStateForTests();
  const config: OpenClawConfig = { plugins: { slots: { contextEngine: "opsys" } } };
  const good = await createContextEngineLogicalTurnLease({
    identity: { runId: "healthy", sessionId: "fictif" },
    config,
    warn: () => {},
  });
  const bad = await createContextEngineLogicalTurnLease({
    identity: { runId: "unsupported", sessionId: "fictif" },
    config,
    warn: () => {},
  });
  try {
    good.selectForHost({
      host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
      operation: "agent-run",
      requiresDurableCommit: true,
    });
    expect(good.begin().registeredId).toBe("opsys");
    expect(
      bad.selectForHost({
        host: { id: "unsupported", label: "fictitious unsupported host", capabilities: [] },
        operation: "agent-run",
        requiresDurableCommit: true,
      }).mode,
    ).toBe("legacy-degraded");
    expect(bad.begin().registeredId).toBe("legacy");
  } finally {
    await good.dispose();
    await bad.dispose();
    restore();
  }
});

it("retains a claimed native source and rejects its real parent closure", async () => {
  const registry = createEmptyPluginRegistry();
  const resources = new PluginRegistryInspectionResources(retireInspectionInstances);
  resources.attach(registry);
  resources.register("fictif", { id: "fictif-resource", dispose() {} });
  resources.runRegistration("fictif", () => {
    registerContextEngineInRegistry(registry, "legacy", () => new LegacyContextEngine(), "core");
    registerContextEngineInRegistry(
      registry,
      "opsys",
      () => createOpsysContextEngine(undefined),
      "core",
    );
  });
  const parent = new AsyncWorkScope();
  const wrapped = await parent.run(() =>
    withPluginRuntimeRegistryScope(registry, () =>
      resolveContextEngine({ plugins: { slots: { contextEngine: "opsys" } } }),
    ),
  );
  try {
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    await resources.release();
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("live");
    parent.beginClose();
    expect(readHostOwnedOpsysTranscript(wrapped)).toBe("unavailable");
  } finally {
    await wrapped.dispose?.();
    await parent.drain();
    await resources.release();
  }
});

it("rejects a native source after a real guarded failure quarantines its registration", async () => {
  const restore = captureContextEngineRegistryStateForTests();
  const registry = createEmptyPluginRegistry();
  registerContextEngineInRegistry(registry, "legacy", () => new LegacyContextEngine(), "core");
  registerContextEngineInRegistry(
    registry,
    "opsys",
    () => createOpsysContextEngine(undefined),
    "core",
  );
  const config: OpenClawConfig = { plugins: { slots: { contextEngine: "opsys" } } };
  const native = await withPluginRuntimeRegistryScope(registry, () => resolveContextEngine(config));
  class FailingEngine extends LegacyContextEngine {
    override async assemble(): Promise<never> {
      throw new Error("fictitious factory failure");
    }
  }
  registerContextEngineInRegistry(registry, "opsys", () => new FailingEngine(), "core", {
    allowSameOwnerRefresh: true,
  });
  const failing = await withPluginRuntimeRegistryScope(registry, () =>
    resolveContextEngine(config),
  );
  try {
    expect(readHostOwnedOpsysTranscript(native)).toBe("live");
    await withPluginRuntimeRegistryScope(registry, () =>
      failing.assemble({ sessionId: "fictif", messages: [] }),
    );
    expect(readHostOwnedOpsysTranscript(native)).toBe("unavailable");
  } finally {
    await native.dispose?.();
    await failing.dispose?.();
    restore();
  }
});

it("rejects a retained native ingest handle after its logical owner is disposed", async () => {
  const restore = captureContextEngineRegistryStateForTests();
  const lease = await createContextEngineLogicalTurnLease({
    identity: { runId: "fictif-retained-ingest", sessionId: "fictif-retained-ingest" },
    config: { plugins: { slots: { contextEngine: "opsys" } } },
    warn: () => {},
  });
  try {
    const engine = lease.engine;
    const heldIngest = engine.ingest.bind(engine);
    const input = {
      sessionId: "fictif-retained-ingest",
      message: { role: "user", content: "Fictitious no-op ingest lifetime witness.", timestamp: 0 },
    } satisfies Parameters<typeof heldIngest>[0];
    expect(readHostOwnedOpsysTranscript(engine)).toBe("live");
    lease.selectForHost({
      host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
      operation: "agent-run",
      requiresDurableCommit: true,
    });
    expect(lease.begin().registeredId).toBe("opsys");
    // A real default OPSYS method delegates to legacy's no-op. No storage or MCP is involved.
    await expect(heldIngest(input)).resolves.toEqual({ ingested: false });
    await lease.dispose();
    expect(readHostOwnedOpsysTranscript(engine)).toBe("unavailable");
    await expect(Promise.resolve().then(() => heldIngest(input))).rejects.toThrow(
      /disposed|unavailable|closed/i,
    );
  } finally {
    await lease.dispose();
    restore();
  }
});

it("rejects a pending native ingest result when its original wrapper closes before settlement", async () => {
  const restore = captureContextEngineRegistryStateForTests();
  const lease = await createContextEngineLogicalTurnLease({
    identity: { runId: "fictif-pending-ingest", sessionId: "fictif-pending-ingest" },
    config: { plugins: { slots: { contextEngine: "opsys" } } },
    warn: () => {},
  });
  try {
    const engine = lease.engine;
    const heldIngest = engine.ingest.bind(engine);
    lease.selectForHost({
      host: OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST,
      operation: "agent-run",
      requiresDurableCommit: true,
    });
    expect(lease.begin().registeredId).toBe("opsys");
    const input = {
      sessionId: "fictif-pending-ingest",
      message: { role: "user", content: "Fictitious async no-op lifetime witness.", timestamp: 0 },
    } satisfies Parameters<typeof heldIngest>[0];
    await expect(heldIngest(input)).resolves.toEqual({ ingested: false });
    const pending = heldIngest(input);
    // The real default method is async; close synchronously before its return microtask.
    const closing = engine.dispose?.();
    expect(readHostOwnedOpsysTranscript(engine)).toBe("unavailable");
    await expect(pending).rejects.toThrow(/disposed|unavailable|closed/i);
    await closing;
  } finally {
    await lease.dispose();
    restore();
  }
});
