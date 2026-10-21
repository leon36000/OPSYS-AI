import { describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { createHostMissedCallImporterV1 } from "./opsys-runtime-missed-call.js";

const initialConfig = {
  plugins: {
    entries: {
      "voice-call": {
        config: { enabled: true, missedCallIngress: true, agentId: "opsys-agent-demo" },
      },
    },
  },
  agents: {
    entries: {
      "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 7 } },
    },
  },
  mcp: { servers: { opsys_runtime_demo: { transport: "http", url: "https://private.invalid" } } },
} as unknown as OpenClawConfig;
const input = {
  provider: "twilio" as const,
  eventId: "evt-stable",
  callId: "CA-stable",
  startedAt: "2026-10-03T12:00:00.000Z",
  from: "+15145550123",
  terminal: "no-answer" as const,
};

type FakeCall = Parameters<
  NonNullable<Parameters<typeof createHostMissedCallImporterV1>[0]["callTool"]>
>[0];
function fixture(
  options: {
    active?: () => boolean;
    stopSignal?: AbortSignal;
    currentConfig?: () => OpenClawConfig;
    serviceScopeCurrent?: () => boolean;
    callResult?: (params: FakeCall) => Promise<unknown>;
  } = {},
) {
  const lease = createPluginRuntimeCapabilityLease("test service");
  const controller = new AbortController();
  const callTool = vi.fn<(...args: [FakeCall]) => Promise<unknown>>(
    options.callResult ??
      (async () => ({
        ok: true,
        source: "voice-call:twilio",
        call_id: "CA-stable",
        status: "manque",
      })),
  );
  const configGetter = options.currentConfig ?? (() => initialConfig);
  const importer = createHostMissedCallImporterV1({
    config: initialConfig,
    getCurrentConfig: configGetter,
    isServiceScopeCurrent: options.serviceScopeCurrent ?? (() => true),
    isStopping: options.active ? () => !options.active?.() : () => false,
    signal: options.stopSignal ?? controller.signal,
    agentId: "opsys-agent-demo",
    lease,
    callTool,
  });
  return { controller, lease, callTool, importer };
}

describe("host missed-call importer V1", () => {
  it("calls only the fixed private profile route with the exact closed M1 arguments", async () => {
    const { callTool, importer } = fixture();
    await expect(importer(input)).resolves.toEqual({
      ok: true,
      source: "voice-call:twilio",
      call_id: "CA-stable",
      status: "manque",
    });
    expect(callTool).toHaveBeenCalledWith(
      expect.objectContaining({
        server: "opsys_runtime_demo",
        tool: "opsys_runtime_importer_appel_manque",
        args: {
          provider: "twilio",
          event_id: "evt-stable",
          call_id: "CA-stable",
          occurred_at: "2026-10-03T12:00:00.000Z",
          telephone: "+15145550123",
          revision_profil: 7,
        },
      }),
    );
    expect(Object.keys(callTool.mock.calls[0]?.[0].args ?? {}).toSorted()).toEqual([
      "call_id",
      "event_id",
      "occurred_at",
      "provider",
      "revision_profil",
      "telephone",
    ]);
  });

  it("rejects absent or mismatched profile binding before transport", () => {
    const invalid = {
      ...initialConfig,
      agents: {
        entries: {
          "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "other", profileRevision: 7 } },
        },
      },
    } as unknown as OpenClawConfig;
    expect(() =>
      createHostMissedCallImporterV1({
        config: invalid,
        getCurrentConfig: () => invalid,
        isServiceScopeCurrent: () => true,
        isStopping: () => false,
        signal: new AbortController().signal,
        agentId: "opsys-agent-demo",
        lease: createPluginRuntimeCapabilityLease("test service"),
        callTool: vi.fn(),
      }),
    ).toThrow(/profile binding/u);
  });

  it("bounds identifiers and accepts only E.164 numbers with 7 to 15 digits", async () => {
    const { callTool, importer } = fixture();
    await expect(importer({ ...input, from: "+12345" })).rejects.toThrow(
      /invalid versioned input/u,
    );
    await expect(importer({ ...input, from: "+١٢٣٤٥٦٧" })).rejects.toThrow(
      /invalid versioned input/u,
    );
    await expect(importer({ ...input, eventId: "event\nattack" })).rejects.toThrow(
      /invalid versioned input/u,
    );
    await expect(importer({ ...input, eventId: "x".repeat(200) })).resolves.toMatchObject({
      ok: true,
    });
    callTool.mockClear();
    await expect(importer({ ...input, eventId: "x".repeat(201) })).rejects.toThrow(
      /invalid versioned input/u,
    );
    await expect(importer({ ...input, callId: `id\u0085bad` })).rejects.toThrow(
      /invalid versioned input/u,
    );
    await expect(importer({ ...input, callId: "x".repeat(201) })).rejects.toThrow(
      /invalid versioned input/u,
    );
    expect(callTool).not.toHaveBeenCalled();
  });

  it("accepts a 200-character call ID and rejects 201 characters", async () => {
    const { importer, callTool } = fixture({
      callResult: async ({ args }) => ({
        ok: true,
        source: "voice-call:twilio",
        call_id: args.call_id,
        status: "manque",
      }),
    });
    await expect(importer({ ...input, callId: "c".repeat(200) })).resolves.toMatchObject({
      call_id: "c".repeat(200),
    });
    expect(callTool).toHaveBeenCalledTimes(1);
    await expect(importer({ ...input, callId: "c".repeat(201) })).rejects.toThrow(
      /invalid versioned input/u,
    );
    expect(callTool).toHaveBeenCalledTimes(1);
  });

  it("snapshots callback scalars before awaiting transport", async () => {
    let finish: ((value: unknown) => void) | undefined;
    const { importer, callTool } = fixture({
      callResult: async () =>
        await new Promise((resolve) => {
          finish = resolve;
        }),
    });
    const mutable = { ...input };
    const pending = importer(mutable);
    const calledArgs = callTool.mock.calls[0]?.[0].args;
    mutable.callId = "mutated-after-call";
    finish?.({ ok: true, source: "voice-call:twilio", call_id: "CA-stable", status: "manque" });
    await expect(pending).resolves.toMatchObject({ call_id: "CA-stable" });
    expect(calledArgs?.call_id).toBe("CA-stable");
  });

  it("rejects changed live admission before transport and after an in-flight response", async () => {
    let current = initialConfig;
    const callResult = vi.fn(async () => ({
      ok: true,
      source: "voice-call:twilio",
      call_id: "CA-stable",
      status: "manque",
    }));
    const { importer, callTool } = fixture({ currentConfig: () => current, callResult });
    current = {
      ...initialConfig,
      agents: {
        entries: {
          "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 8 } },
        },
      },
    } as unknown as OpenClawConfig;
    await expect(importer(input)).rejects.toThrow(
      /live (?:profile binding|capability scope) changed/u,
    );
    expect(callTool).not.toHaveBeenCalled();

    current = initialConfig;
    let finish: ((value: unknown) => void) | undefined;
    const second = fixture({
      currentConfig: () => current,
      callResult: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    const pending = second.importer(input);
    current = {
      ...initialConfig,
      agents: {
        entries: {
          "opsys-agent-demo": { opsysRuntimeAdmission: { profileId: "demo", profileRevision: 8 } },
        },
      },
    } as unknown as OpenClawConfig;
    finish?.({ ok: true, source: "voice-call:twilio", call_id: "CA-stable", status: "manque" });
    await expect(pending).rejects.toThrow(/live (?:profile binding|capability scope) changed/u);
  });

  it("refuses operation whenever the host's opaque committed scope changes", async () => {
    let scopeCurrent = true;
    const { importer, callTool } = fixture({ serviceScopeCurrent: () => scopeCurrent });
    scopeCurrent = false;
    await expect(importer(input)).rejects.toThrow(/captured service scope changed/u);
    expect(callTool).not.toHaveBeenCalled();
  });

  it("aborts transport as soon as service stop retires its signal", async () => {
    const { importer, controller, callTool } = fixture({
      callResult: ({ signal }) =>
        new Promise((_, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    });
    const pending = importer(input);
    controller.abort(new Error("service stop"));
    await expect(pending).rejects.toThrow("service stop");
    expect(callTool).toHaveBeenCalledTimes(1);
  });

  it("aborts a stalled transport at the eight-second deadline", async () => {
    vi.useFakeTimers();
    try {
      const { importer, callTool } = fixture({
        callResult: ({ signal }) =>
          new Promise((_, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason), { once: true });
          }),
      });
      const pending = importer(input);
      const rejected = expect(pending).rejects.toThrow(/deadline exceeded/u);
      await vi.advanceTimersByTimeAsync(8_000);
      await rejected;
      expect(callTool).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects a non-exact backend acknowledgement", async () => {
    const { importer } = fixture({
      callResult: async () => ({
        ok: true,
        source: "voice-call:twilio",
        call_id: "other",
        status: "manque",
      }),
    });
    await expect(importer(input)).rejects.toThrow(/acknowledgement mismatch/u);
  });
});
