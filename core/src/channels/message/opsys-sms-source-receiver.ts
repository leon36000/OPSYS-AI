/** Core-private raw comparison owner; no policy, context admission or provider authority. */
import { types } from "node:util";
import { normalizeInboundTextNewlines } from "../../auto-reply/reply/inbound-text.js";
import {
  assertSmsSourceOriginalInput,
  readSmsSourceScope,
  type SmsSourceHandle,
} from "./opsys-sms-source.js";

const ERROR = "REJ-M1-SMS-SOURCE-NON-COURANTE";
const nativeThen = Promise.prototype.then;
const signalAborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted")?.get;
const addListener = EventTarget.prototype.addEventListener;
const removeListener = EventTarget.prototype.removeEventListener;
const textFields = [
  "Body",
  "RawBody",
  "CommandBody",
  "BodyForAgent",
  "BodyForCommands",
  "rawText",
  "agentText",
  "commandText",
] as const;
type Projection = Parameters<typeof assertSmsSourceOriginalInput>[1];
type Input = { source: SmsSourceHandle; projection: Projection };
export type NativeSmsRawSourceReceiver = Readonly<{
  acceptNativeSource(source: SmsSourceHandle): void;
  bindRawInput(source: SmsSourceHandle, raw: unknown, receivedAt: number): void;
  assertRawInput(source: SmsSourceHandle, raw: unknown): void;
  assertInitialTextProjection(raw: unknown, context: unknown): void;
  readRawSource(raw: unknown): SmsSourceHandle;
  dispose(): void;
}>;

/** Native Task construction only. The accept hook is never a bridge/SDK request. */
export function createNativeSmsSourceReceiver(
  owner: Readonly<{
    accountId: string;
    signal: AbortSignal;
    assertCurrent: () => void;
  }>,
): NativeSmsRawSourceReceiver {
  let closed = false;
  const lifetime: { signal?: AbortSignal } = {};
  const accepted = new WeakSet<object>();
  const inputs = new WeakMap<object, Input>();
  const originals = new WeakMap<object, object>();
  const dispose = () => {
    closed = true;
    if (lifetime.signal) {
      removeListener.call(lifetime.signal, "abort", dispose);
    }
  };
  const refuse: () => never = () => {
    dispose();
    throw new Error(ERROR);
  };
  const record = (value: unknown): object => {
    if (value === null || typeof value !== "object" || types.isProxy(value)) {
      refuse();
    }
    const proto = Object.getPrototypeOf(value);
    if (proto !== Object.prototype && proto !== null) {
      refuse();
    }
    return value;
  };
  const data = (value: object, key: string): unknown => {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !("value" in d) || !d.enumerable) {
      refuse();
    }
    return d.value;
  };
  const o = record(owner);
  if (Reflect.ownKeys(o).length !== 3) {
    refuse();
  }
  const accountId = data(o, "accountId");
  const candidateSignal = data(o, "signal");
  const guard = data(o, "assertCurrent");
  if (
    typeof accountId !== "string" ||
    !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(accountId) ||
    ["__proto__", "prototype", "constructor"].includes(accountId) ||
    candidateSignal === null ||
    typeof candidateSignal !== "object" ||
    types.isProxy(candidateSignal) ||
    typeof guard !== "function" ||
    types.isProxy(guard)
  ) {
    refuse();
  }
  try {
    if (signalAborted?.call(candidateSignal) !== false) {
      refuse();
    }
  } catch {
    refuse();
  }
  lifetime.signal = candidateSignal as AbortSignal;
  const current = () => {
    try {
      if (closed || signalAborted?.call(lifetime.signal) !== false) {
        refuse();
      }
      const result: unknown = guard();
      if (types.isPromise(result)) {
        void nativeThen.call(result, undefined, () => undefined);
      }
      if (result !== undefined || closed || signalAborted?.call(lifetime.signal) !== false) {
        refuse();
      }
    } catch {
      refuse();
    }
  };
  addListener.call(lifetime.signal, "abort", dispose, { once: true });
  if (signalAborted?.call(lifetime.signal) !== false) {
    refuse();
  }
  const sourceCurrent = (source: SmsSourceHandle, mustBeAccepted = true) => {
    current();
    if (
      source === null ||
      typeof source !== "object" ||
      (mustBeAccepted && !accepted.has(source))
    ) {
      refuse();
    }
    try {
      if (readSmsSourceScope(source).accountId !== accountId) {
        refuse();
      }
    } catch {
      refuse();
    }
    current();
  };
  const snapshot = (raw: unknown, receivedAt: number): Projection => {
    const input = record(raw);
    const allowed = new Set([
      "accountSid",
      "messageSid",
      "from",
      "to",
      "body",
      "media",
      "unavailableMediaCount",
      "messagingServiceSid",
    ]);
    if (Reflect.ownKeys(input).some((key) => typeof key !== "string" || !allowed.has(key))) {
      refuse();
    }
    const values = ["accountSid", "messageSid", "from", "to", "body"].map((key) =>
      data(input, key),
    );
    if (
      values.some((value) => typeof value !== "string") ||
      !Number.isSafeInteger(receivedAt) ||
      receivedAt < 0
    ) {
      refuse();
    }
    const media = data(input, "media");
    if (
      !Array.isArray(media) ||
      types.isProxy(media) ||
      Object.getPrototypeOf(media) !== Array.prototype
    ) {
      refuse();
    }
    if (
      Object.getOwnPropertyDescriptor(media, "length")?.value !== 0 ||
      Reflect.ownKeys(media).length !== 1
    ) {
      refuse();
    }
    const unavailable = Object.getOwnPropertyDescriptor(input, "unavailableMediaCount");
    if (
      unavailable &&
      (!("value" in unavailable) ||
        !unavailable.enumerable ||
        (unavailable.value !== undefined && unavailable.value !== 0))
    ) {
      refuse();
    }
    const service = Object.getOwnPropertyDescriptor(input, "messagingServiceSid");
    if (
      service &&
      (!("value" in service) ||
        !service.enumerable ||
        (service.value !== undefined && typeof service.value !== "string"))
    ) {
      refuse();
    }
    return Object.freeze({
      accountSid: values[0] as string,
      messageSid: values[1] as string,
      from: values[2] as string,
      to: values[3] as string,
      body: values[4] as string,
      receivedAt,
      mediaCount: 0,
      unavailableMediaCount: 0,
    });
  };
  const compare = (source: SmsSourceHandle, projection: Projection) => {
    sourceCurrent(source);
    try {
      assertSmsSourceOriginalInput(source, projection);
    } catch {
      refuse();
    }
    sourceCurrent(source);
  };
  const read = (raw: unknown, requestedSource?: SmsSourceHandle): Input => {
    current();
    const input = record(raw);
    const saved = inputs.get(input);
    if (!saved || (requestedSource !== undefined && requestedSource !== saved.source)) {
      refuse();
    }
    const fresh = snapshot(input, saved.projection.receivedAt);
    if (
      Object.keys(fresh).some(
        (key) => fresh[key as keyof Projection] !== saved.projection[key as keyof Projection],
      )
    ) {
      refuse();
    }
    compare(saved.source, fresh);
    const after = snapshot(input, saved.projection.receivedAt);
    if (
      Object.keys(after).some(
        (key) => after[key as keyof Projection] !== saved.projection[key as keyof Projection],
      )
    ) {
      refuse();
    }
    return saved;
  };
  return Object.freeze({
    acceptNativeSource(source: SmsSourceHandle) {
      sourceCurrent(source, false);
      accepted.add(source);
    },
    bindRawInput(source: SmsSourceHandle, raw: unknown, receivedAt: number) {
      current();
      const input = record(raw);
      const original = originals.get(source);
      if (
        (original && original !== input) ||
        (inputs.has(input) && inputs.get(input)?.source !== source)
      ) {
        refuse();
      }
      const projection = snapshot(input, receivedAt);
      compare(source, projection);
      const after = snapshot(input, receivedAt);
      if (
        Object.keys(after).some(
          (key) => after[key as keyof Projection] !== projection[key as keyof Projection],
        )
      ) {
        refuse();
      }
      const prior = inputs.get(input);
      if (
        prior &&
        Object.keys(projection).some(
          (key) =>
            projection[key as keyof Projection] !== prior.projection[key as keyof Projection],
        )
      ) {
        refuse();
      }
      originals.set(source, input);
      inputs.set(input, { source, projection });
    },
    assertRawInput(source: SmsSourceHandle, raw: unknown) {
      read(raw, source);
    },
    assertInitialTextProjection(raw: unknown, context: unknown) {
      const saved = read(raw);
      const value = record(context);
      const expected = normalizeInboundTextNewlines(saved.projection.body);
      for (const field of textFields) {
        if (data(value, field) !== expected) {
          refuse();
        }
      }
      read(raw, saved.source);
      const after = record(context);
      for (const field of textFields) {
        if (data(after, field) !== expected) {
          refuse();
        }
      }
    },
    readRawSource(raw: unknown) {
      return read(raw).source;
    },
    dispose,
  });
}
