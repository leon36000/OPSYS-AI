import { afterEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createEmptyPluginRegistry } from "./registry.js";
import { startPluginServices, type PluginServicesHandle } from "./services.js";
import { createServiceRegistration } from "./services.test-support.js";
import type { OpenClawPluginServiceContext } from "./types.js";

const mocks = vi.hoisted(() => ({ callTool: vi.fn() }));
vi.mock("../context-engine/opsys-contexte-mcp.js", () => ({
  callOpsysMcpTool: mocks.callTool,
}));

describe("service missed-call host capability", () => {
  const handles = new Set<PluginServicesHandle>();
  afterEach(async () => {
    await Promise.all([...handles].map((handle) => handle.stop()));
    handles.clear();
    vi.resetAllMocks();
  });

  const config = (revision: number): OpenClawConfig =>
    ({
      plugins: {
        entries: {
          "voice-call": {
            config: { enabled: true, missedCallIngress: true, agentId: "opsys-agent-demo" },
          },
        },
      },
      agents: {
        entries: {
          "opsys-agent-demo": {
            opsysRuntimeAdmission: { profileId: "demo", profileRevision: revision },
          },
        },
      },
      mcp: {
        servers: { opsys_runtime_demo: { transport: "http", url: "https://private.invalid" } },
      },
    }) as unknown as OpenClawConfig;
  const importerInput = {
    provider: "twilio" as const,
    eventId: "event-stable",
    callId: "call-stable",
    startedAt: "2026-10-03T12:00:00.000Z",
    from: "+15145550123",
    terminal: "no-answer" as const,
  };

  it("injects only into the opted-in bundled voicecall service", async () => {
    const registry = createEmptyPluginRegistry();
    let bundledContext: OpenClawPluginServiceContext | undefined;
    let workspaceContext: OpenClawPluginServiceContext | undefined;
    registry.services.push(
      createServiceRegistration(
        {
          id: "voicecall",
          hostMissedCallIngress: { version: 1, agentId: "opsys-agent-demo" },
          start(ctx) {
            bundledContext = ctx;
          },
        },
        { pluginId: "voice-call", origin: "bundled" },
      ),
      createServiceRegistration(
        {
          id: "voicecall",
          hostMissedCallIngress: { version: 1, agentId: "opsys-agent-demo" },
          start(ctx) {
            workspaceContext = ctx;
          },
        },
        { pluginId: "voice-call", origin: "workspace" },
      ),
    );
    const handle = await startPluginServices({
      registry,
      config: config(7),
      throwOnStartError: false,
    });
    handles.add(handle);
    expect(bundledContext?.hostMissedCallImporter?.agentId).toBe("opsys-agent-demo");
    expect(workspaceContext?.hostMissedCallImporter).toBeUndefined();
    await handle.stop();
  });

  it("aborts an in-flight import immediately when committed config retires its service", async () => {
    const registry = createEmptyPluginRegistry();
    let context: OpenClawPluginServiceContext | undefined;
    registry.services.push(
      createServiceRegistration(
        {
          id: "voicecall",
          hostMissedCallIngress: { version: 1, agentId: "opsys-agent-demo" },
          reload: {
            configPrefixes: ["plugins.entries.voice-call", "agents.entries", "mcp.servers"],
          },
          start(ctx) {
            context = ctx;
          },
        },
        { pluginId: "voice-call", origin: "bundled" },
      ),
    );
    let entered!: () => void;
    const enteredCall = new Promise<void>((resolve) => {
      entered = resolve;
    });
    mocks.callTool.mockImplementation(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise((_, reject) => {
          entered();
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const handle = await startPluginServices({
      registry,
      config: config(7),
      throwOnStartError: false,
    });
    handles.add(handle);
    const pending = context?.hostMissedCallImporter?.importInboundMissedCall(importerInput);
    await enteredCall;
    const reloading = handle.reload(config(8), new Set(["voicecall"]));
    await expect(pending).rejects.toThrow(/reloading|aborted/u);
    await reloading;
  });

  it("retires the importer synchronously before blocked service cleanup finishes", async () => {
    const registry = createEmptyPluginRegistry();
    let context: OpenClawPluginServiceContext | undefined;
    let finishStop!: () => void;
    const blockedStop = new Promise<void>((resolve) => {
      finishStop = resolve;
    });
    registry.services.push(
      createServiceRegistration(
        {
          id: "voicecall",
          hostMissedCallIngress: { version: 1, agentId: "opsys-agent-demo" },
          start(ctx) {
            context = ctx;
          },
          async stop() {
            await blockedStop;
          },
        },
        { pluginId: "voice-call", origin: "bundled" },
      ),
    );
    let entered!: () => void;
    const enteredCall = new Promise<void>((resolve) => {
      entered = resolve;
    });
    mocks.callTool.mockImplementation(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise((_, reject) => {
          entered();
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const handle = await startPluginServices({
      registry,
      config: config(7),
      throwOnStartError: false,
    });
    handles.add(handle);
    const pending = context?.hostMissedCallImporter?.importInboundMissedCall(importerInput);
    await enteredCall;
    const reload = handle.reload(config(8), new Set(["voicecall"]));
    await expect(pending).rejects.toThrow(/reloading|aborted/u);
    await expect(
      context?.hostMissedCallImporter?.importInboundMissedCall(importerInput),
    ).rejects.toThrow(/service is stopping/u);
    expect(mocks.callTool).toHaveBeenCalledTimes(1);
    // Cleanup is intentionally still blocked: immediate importer revocation precedes stop completion.
    finishStop();
    await reload;
  });

  it("rejects queued C1 startup after C2 commits an opted-out scope", async () => {
    const registry = createEmptyPluginRegistry();
    let entered!: () => void;
    const enteredBlocker = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let release!: () => void;
    const blockerGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const voicecallStart = vi.fn((ctx: OpenClawPluginServiceContext) => {
      const pluginConfig = ctx.config.plugins?.entries?.["voice-call"]?.config as
        | { enabled?: boolean; missedCallIngress?: boolean }
        | undefined;
      // The owner plugin applies its parsed feature config before handing the bridge to runtime.
      if (pluginConfig?.enabled !== false && pluginConfig?.missedCallIngress === true) {
        context = ctx;
      }
    });
    let context: OpenClawPluginServiceContext | undefined;
    registry.services.push(
      createServiceRegistration(
        {
          id: "blocker",
          async start() {
            entered();
            await blockerGate;
          },
        },
        { pluginId: "blocker", origin: "bundled" },
      ),
      createServiceRegistration(
        {
          id: "voicecall",
          hostMissedCallIngress: { version: 1, agentId: "opsys-agent-demo" },
          start: voicecallStart,
        },
        { pluginId: "voice-call", origin: "bundled" },
      ),
    );
    let handle: PluginServicesHandle | undefined;
    const startup = startPluginServices({
      registry,
      config: config(7),
      throwOnStartError: false,
      onHandle(value) {
        handle = value;
      },
    });
    await enteredBlocker;
    const reload = handle?.reload(
      {
        ...config(8),
        plugins: {
          entries: {
            "voice-call": {
              config: { enabled: false, missedCallIngress: false, agentId: "opsys-agent-demo" },
            },
          },
        },
      } as OpenClawConfig,
      new Set(["voicecall"]),
    );
    release();
    await startup;
    await reload;
    expect(voicecallStart).toHaveBeenCalledTimes(1);
    expect(context?.hostMissedCallImporter).toBeUndefined();
    expect(mocks.callTool).not.toHaveBeenCalled();
    if (handle) {
      handles.add(handle);
    }
  });
});
