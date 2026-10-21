// Sms plugin module owns durable Twilio webhook admission and replay.
import {
  bindIngressLifecycleToReplyOptions,
  createChannelIngressMonitor,
  type ChannelIngressQueue,
} from "openclaw/plugin-sdk/channel-outbound";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { sleepWithAbort } from "openclaw/plugin-sdk/runtime-env";
import { runDetachedWebhookWork } from "openclaw/plugin-sdk/webhook-request-guards";
import { dispatchSmsInboundEvent, type SmsChannelRuntime } from "./inbound.js";
import { getOpsysSmsHostBridge } from "./opsys-host-bridge.js";
import { looksLikeSmsPhoneNumber, normalizeSmsPhoneNumber } from "./phone.js";
import { getSmsRuntime } from "./runtime.js";
import {
  buildTwilioInboundMessage,
  resolveTwilioInboundSender,
  resolveTwilioMessageSid,
} from "./twilio.js";
import type { ResolvedSmsAccount, SmsInboundMessage } from "./types.js";

const SMS_INGRESS_PAYLOAD_VERSION = 2;
const SMS_UNRESOLVED_WAIT_MS = 5_000;
const SMS_SELECTION_UNAVAILABLE = "M1-SMS-RECEPTION-NON-RESOLUE";
const SMS_INGRESS_DRAIN_INTERVAL_MS = 500;

type SmsIngressPayload = unknown;

type SmsCaptureProof = Readonly<{ signature: string; signatureUrl: string }>;
type SmsIngressInput =
  | { kind: "incoming"; form: Record<string, string>; handle?: object }
  | { kind: "gate"; payload: SmsIngressPayload; eventId: string; laneKey: string };

/** Routing classification only. Live authority remains exclusively in the Host. */
function selectedSmsRoute(cfg: OpenClawConfig, accountId: string): boolean {
  const agents = cfg.agents;
  const entries = agents?.entries ? Object.values(agents.entries) : (agents?.list ?? []);
  for (const entry of entries) {
    const marker = entry.opsysRuntimeAdmission;
    if (!marker || !Object.hasOwn(marker, "smsIngress")) {
      continue;
    }
    const ingress = marker.smsIngress;
    // A malformed selection never silently opts an ingress into the legacy parser.
    if (!ingress || ingress.version !== 1 || typeof ingress.accountId !== "string") {
      throw new Error(SMS_SELECTION_UNAVAILABLE);
    }
    if (ingress.accountId === accountId) {
      return true;
    }
  }
  return false;
}
function isStoredForm(value: unknown): value is Record<string, string> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.values(value).every((field) => typeof field === "string")
  );
}
function isLegacyPayload(
  payload: unknown,
): payload is { version: 1; form: Record<string, string> } {
  return (
    payload !== null &&
    typeof payload === "object" &&
    "version" in payload &&
    payload.version === 1 &&
    "form" in payload &&
    isStoredForm(payload.form)
  );
}
function requireSealed(value: unknown): asserts value is SmsIngressPayload {
  if (
    !value ||
    typeof value !== "object" ||
    !("version" in value) ||
    value.version !== 2 ||
    !("form" in value) ||
    !isStoredForm(value.form) ||
    !("capsule" in value)
  ) {
    throw new Error(SMS_SELECTION_UNAVAILABLE);
  }
}

type SmsIngressLifecycle = ReturnType<
  typeof bindIngressLifecycleToReplyOptions
>["turnAdoptionLifecycle"];

export type SmsIngressLog = Partial<Record<"info" | "warn" | "error", (message: string) => void>>;

class SmsIngressPermanentError extends Error {}

function parseSmsIngressForm(
  form: Record<string, string>,
  account: ResolvedSmsAccount,
): SmsInboundMessage {
  const message = buildTwilioInboundMessage(form);
  if (!message) {
    throw new SmsIngressPermanentError("SMS ingress payload is invalid.");
  }
  if (!message.accountSid || message.accountSid !== account.accountSid) {
    throw new SmsIngressPermanentError("SMS ingress payload has an invalid Twilio account.");
  }
  const isRcsRecipient = /^rcs:/iu.test(message.to);
  if (isRcsRecipient) {
    if (!message.body) {
      throw new SmsIngressPermanentError("SMS ingress payload is invalid.");
    }
    if (
      account.messagingServiceSid &&
      message.messagingServiceSid !== account.messagingServiceSid
    ) {
      throw new SmsIngressPermanentError(
        "SMS ingress payload has an invalid Twilio Messaging Service.",
      );
    }
    // Shipped fromNumber-only RCS callbacks use an agent address in `To`, so
    // they cannot be bound to the phone number without a new RCS config contract.
    // MMS support must not change shipped RCS text behavior. Ignore unsupported
    // RCS media fields until the RCS owner defines its media contract.
    const { unavailableMediaCount: _unavailableMediaCount, ...textMessage } = message;
    return { ...textMessage, media: [] };
  }
  if (account.fromNumber) {
    const recipient = normalizeSmsPhoneNumber(message.to);
    if (!looksLikeSmsPhoneNumber(recipient) || recipient !== account.fromNumber) {
      throw new SmsIngressPermanentError("SMS ingress payload has an invalid Twilio recipient.");
    }
  } else if (
    !message.messagingServiceSid ||
    message.messagingServiceSid !== account.messagingServiceSid
  ) {
    throw new SmsIngressPermanentError(
      "SMS ingress payload has an invalid Twilio Messaging Service.",
    );
  }
  return message;
}

export function createSmsIngressSpool(params: {
  cfg: OpenClawConfig;
  account: ResolvedSmsAccount;
  channelRuntime: SmsChannelRuntime;
  queue?: ChannelIngressQueue<SmsIngressPayload>;
  abortSignal?: AbortSignal;
  /** Route retirement fences selected capture/wait without changing legacy durable admission. */
  gateAbortSignal?: AbortSignal;
  log?: SmsIngressLog;
  deliver?: (
    message: SmsInboundMessage,
    lifecycle: SmsIngressLifecycle,
    receivedAt: number,
  ) => Promise<void>;
}) {
  const selected = selectedSmsRoute(params.cfg, params.account.accountId);
  const found = getOpsysSmsHostBridge(params.account.accountId);
  // Snapshot the actual instance-owned callable view; never switch to a replacement mid-route.
  const bridge = found
    ? Object.freeze({ locator: found.locator, invoke: found.invoke })
    : undefined;
  const invoke = (input: unknown) => {
    if (!bridge) {
      throw new Error(SMS_SELECTION_UNAVAILABLE);
    }
    params.abortSignal?.throwIfAborted();
    params.gateAbortSignal?.throwIfAborted();
    return bridge.invoke(bridge.locator, input);
  };
  const queue =
    params.queue ??
    getSmsRuntime().state.openChannelIngressQueue<SmsIngressPayload>({
      accountId: params.account.accountId,
    });
  const deliver =
    params.deliver ??
    (async (message: SmsInboundMessage, lifecycle: SmsIngressLifecycle, receivedAt: number) => {
      await dispatchSmsInboundEvent({
        cfg: params.cfg,
        account: params.account,
        channelRuntime: params.channelRuntime,
        msg: message,
        receivedAt,
        turnAdoptionLifecycle: lifecycle,
        log: params.log,
      });
    });
  const monitor = createChannelIngressMonitor<
    SmsIngressInput,
    SmsIngressPayload,
    SmsIngressPayload
  >({
    queue,
    inspect: (input, context) => {
      if (input.kind === "gate") {
        return { eventId: input.eventId, laneKey: input.laneKey };
      }
      const form = input.form;
      const eventId = resolveTwilioMessageSid(form);
      if (!eventId) {
        if (context.phase === "claim") {
          throw new SmsIngressPermanentError("SMS ingress payload is invalid.");
        }
        throw new Error("SMS webhook is missing MessageSid.");
      }
      const sender = resolveTwilioInboundSender(form);
      return { eventId, laneKey: sender ? `sender:${sender}` : `event:${eventId}` };
    },
    payload: {
      version: SMS_INGRESS_PAYLOAD_VERSION,
      serialize: (input, { receivedAt }) => {
        if (input.kind !== "incoming") {
          throw new Error(SMS_SELECTION_UNAVAILABLE);
        }
        if (!selected) {
          return { version: 1, form: input.form };
        }
        const sealed = invoke({ kind: "encode", handle: input.handle, receivedAt });
        requireSealed(sealed);
        return sealed;
      },
      deserialize: (payload, { claim }) =>
        selected || !isLegacyPayload(payload)
          ? {
              kind: "gate",
              payload,
              eventId: claim.id,
              laneKey: claim.laneKey ?? `event:${claim.id}`,
            }
          : { kind: "incoming", form: payload.form },
      // Version 2 is a RAM codec discriminator, not an additional persisted envelope.
      encode: ({ body }) => body,
      decode: (payload) => ({ version: SMS_INGRESS_PAYLOAD_VERSION, body: payload }),
      createClaimError: (kind) =>
        new SmsIngressPermanentError(
          kind === "invalid-version"
            ? "SMS ingress payload version is invalid."
            : "SMS ingress identity changed after durable admission.",
        ),
    },
    deliver: async (input, lifecycle, event) => {
      if (input.kind === "gate") {
        try {
          await invoke({
            kind: "resolve",
            payload: event.payload,
            id: event.id,
            token: event.claim.token,
            ownerId: event.claim.ownerId,
            receivedAt: event.receivedAt,
          });
        } catch {
          // Unknown includes a missing/revoked carrier. Never reinterpret persisted input.
        }
        // Even GateReceived lacks the native SourceCell in this slice. No inbound effects.
        try {
          await sleepWithAbort(
            SMS_UNRESOLVED_WAIT_MS,
            params.gateAbortSignal
              ? AbortSignal.any([lifecycle.abortSignal, params.gateAbortSignal])
              : lifecycle.abortSignal,
            { ref: false },
          );
        } catch {
          // Abort shortens the wait; cancellation below still owns claim release.
        }
        try {
          await lifecycle.onCancelled?.();
        } catch {
          // The wrapped lifecycle already marked deferred. Do not turn release loss into fail.
        }
        return { kind: "deferred" };
      }
      await deliver(
        parseSmsIngressForm(input.form, params.account),
        bindIngressLifecycleToReplyOptions(lifecycle).turnAdoptionLifecycle,
        event.receivedAt,
      );
      return undefined;
    },
    pollIntervalMs: SMS_INGRESS_DRAIN_INTERVAL_MS,
    // The 1-day / 20k tombstones dominate the retired 10-minute / 10,000-key cache.
    retention: {
      pruneIntervalMs: 0,
      completedTtlMs: 24 * 60 * 60 * 1_000,
      failedMaxEntries: 1_000,
    },
    appendRetryDelaysMs: [0],
    waitForDeliveryIdleBeforeRepump: false,
    // Route replacement must not wait forever for a handler that ignores lifecycle abort.
    // SMS historically disposed immediately; the next route recovers any unsettled claim.
    waitForDeliveryIdleOnStop: false,
    runPumpTask: runDetachedWebhookWork,
    admissionMode: "durable-after-stop",
    drain: {
      deriveLaneKey: (claim) => claim.laneKey ?? `event:${claim.id}`,
      onLog: (message) => params.log?.warn?.(message),
      resolveNonRetryableFailure: (error) =>
        error instanceof SmsIngressPermanentError
          ? { reason: "invalid-payload", message: error.message }
          : null,
    },
    ...(params.abortSignal ? { abortSignal: params.abortSignal } : {}),
    createStoppedError: () => new Error("SMS ingress stopped."),
    onError: (error) =>
      params.log?.error?.(
        `SMS ingress drain failed: ${error instanceof Error ? error.message : String(error)}`,
      ),
  });
  return {
    selected,
    enqueue: async (form: Record<string, string>, proof?: SmsCaptureProof) => {
      let handle: object | undefined;
      if (selected) {
        if (!proof || params.account.dangerouslyDisableSignatureValidation) {
          throw new Error(SMS_SELECTION_UNAVAILABLE);
        }
        const captured = invoke({ kind: "capture", input: { form, ...proof } });
        if (!captured || typeof captured !== "object" || captured instanceof Promise) {
          throw new Error(SMS_SELECTION_UNAVAILABLE);
        }
        handle = captured;
      }
      const admitted = await monitor.admit({ kind: "incoming", form, handle });
      if (admitted.kind === "ignored") {
        throw new Error("SMS webhook admission was unexpectedly ignored.");
      }
      return { kind: admitted.queueResult.kind, duplicate: admitted.queueResult.duplicate };
    },
    start: monitor.start,
    pause: monitor.pause,
    waitForIdle: monitor.waitForIdle,
    stop: monitor.stop,
  };
}
