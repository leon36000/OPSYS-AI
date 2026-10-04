import { describe, expect, it, vi } from "vitest";
import type { NormalizedEvent } from "./types.js";
import { VoiceCallWebhookServer } from "./webhook.js";

type Importer = NonNullable<ConstructorParameters<typeof VoiceCallWebhookServer>[7]>;

function harness(options: { enabled?: boolean; importer?: Importer; call?: unknown } = {}) {
  const manager = {
    getCallFromMemoryOrStore: vi.fn(
      async () =>
        options.call ?? {
          direction: "inbound",
          providerCallId: "CA-stable",
          from: "+15145550123",
          startedAt: Date.parse("2026-10-03T12:00:00.000Z"),
          answeredAt: undefined,
        },
    ),
  };
  const subject = Object.create(VoiceCallWebhookServer.prototype) as {
    config: { enabled: boolean; missedCallIngress: boolean; provider: "twilio" };
    manager: typeof manager;
    provider: { name: "twilio" };
    hostMissedCallImporter?: Importer;
    importVerifiedMissedCalls(events: NormalizedEvent[]): Promise<void>;
  };
  subject.config = {
    enabled: true,
    missedCallIngress: options.enabled ?? true,
    provider: "twilio",
  };
  subject.manager = manager;
  subject.provider = { name: "twilio" };
  subject.hostMissedCallImporter = options.importer;
  return { subject, manager };
}

const missed: NormalizedEvent = {
  id: "random-event-uuid",
  dedupeKey: "verified-provider-event-key",
  type: "call.ended",
  reason: "no-answer",
  callId: "CA-stable",
  providerCallId: "CA-stable",
  timestamp: Date.parse("2026-10-03T12:00:20.000Z"),
  direction: "inbound",
  from: "+15145550123",
};

describe("voice-call missed-call ingress", () => {
  it("uses the verified dedupe key and persisted call start time", async () => {
    const importInboundMissedCall = vi.fn(async () => ({
      ok: true as const,
      source: "voice-call:twilio" as const,
      call_id: "CA-stable",
      status: "manque" as const,
    }));
    const importer = { agentId: "opsys-agent-demo", importInboundMissedCall };
    const { subject, manager } = harness({ importer });
    await subject.importVerifiedMissedCalls([missed]);
    expect(manager.getCallFromMemoryOrStore).toHaveBeenCalledWith("CA-stable");
    expect(importInboundMissedCall).toHaveBeenCalledWith({
      provider: "twilio",
      eventId: "verified-provider-event-key",
      callId: "CA-stable",
      startedAt: "2026-10-03T12:00:00.000Z",
      from: "+15145550123",
      terminal: "no-answer",
    });
  });

  it("never imports answered, outgoing, or unsupported terminal events", async () => {
    const importInboundMissedCall = vi.fn(async () => ({
      ok: true as const,
      source: "voice-call:twilio" as const,
      call_id: "CA-stable",
      status: "manque" as const,
    }));
    const importer = { agentId: "opsys-agent-demo", importInboundMissedCall };
    const { subject } = harness({
      importer,
      call: {
        direction: "inbound",
        providerCallId: "CA-stable",
        from: "+15145550123",
        startedAt: 1,
        answeredAt: 0,
      },
    });
    await subject.importVerifiedMissedCalls([missed]);
    await subject.importVerifiedMissedCalls([{ ...missed, direction: "outbound" }]);
    await subject.importVerifiedMissedCalls([{ ...missed, reason: "voicemail" }]);
    expect(importInboundMissedCall).not.toHaveBeenCalled();
  });

  it("fails closed if enabled without the host capability", async () => {
    const { subject } = harness({ enabled: true });
    await expect(subject.importVerifiedMissedCalls([missed])).rejects.toThrow(
      /without a host capability/u,
    );
  });

  it("does nothing while the feature is disabled", async () => {
    const importInboundMissedCall = vi.fn(async () => ({
      ok: true as const,
      source: "voice-call:twilio" as const,
      call_id: "CA-stable",
      status: "manque" as const,
    }));
    const importer = { agentId: "opsys-agent-demo", importInboundMissedCall };
    const { subject, manager } = harness({ enabled: false, importer });
    await subject.importVerifiedMissedCalls([missed]);
    expect(manager.getCallFromMemoryOrStore).not.toHaveBeenCalled();
    expect(importInboundMissedCall).not.toHaveBeenCalled();
  });
});
