/** Private Host composition; neither a plugin context nor a model tool authority. */
import path from "node:path";
import { types } from "node:util";
import {
  INGRESS_CLAIM_LEASE_MS,
  isLiveLocalIngressDrainOwner,
} from "../channels/message/ingress-claim-owner.js";
import {
  createChannelIngressQueue,
  readOwnNativeSmsClaimOrigin,
  readNativeSmsQueueScope,
  type NativeSmsClaimRef,
  type ChannelIngressQueueClaimIdentityReader,
} from "../channels/message/ingress-queue.js";
import type { GateReceivedBinding } from "../channels/message/opsys-sms-source.js";
import { normalizeAccountId } from "../routing/session-key.js";
import { OPSYS_SMS_HOST_SELECTION_REFUSED } from "./opsys-sms-host-authority.js";
import type { OpsysSmsHostController } from "./opsys-sms-host-controller.js";
import { readSmsReceiptHostDestinationAssertion } from "./opsys-sms-receipt-gate.js";

const UNRESOLVED = Object.freeze({
  status: "unresolved" as const,
  code: "M1-SMS-RECEPTION-NON-RESOLUE",
});
const nativePromiseThen = Promise.prototype.then;
export type OpsysSmsHostClaimAdapter = Readonly<{
  locator: object;
  invoke: (locator: unknown, input: unknown) => unknown;
  dispose: () => void;
}>;
type JoinedOrigin = {
  queueScope: object;
  claim: NativeSmsClaimRef;
  binding: GateReceivedBinding;
  assertCurrent: () => void;
  assertHostDestinationCurrent: () => void;
};
const joinedReceipts = new WeakMap<object, JoinedOrigin>();

/** Private pre-arm lookup. It intentionally requires a live claim and is not a post-adoption API. */
function readCurrentJoinedOrigin(
  result: unknown,
  queue: unknown,
  claim: NativeSmsClaimRef,
): JoinedOrigin | undefined {
  if (result === null || typeof result !== "object") {
    return undefined;
  }
  const joined = joinedReceipts.get(result);
  if (!joined) {
    return undefined;
  }
  try {
    const ref = request(claim, ["id", "token", "ownerId"]);
    requireHost(readNativeSmsQueueScope(queue) === joined.queueScope);
    requireHost(
      ref.id === joined.claim.id &&
        ref.token === joined.claim.token &&
        ref.ownerId === joined.claim.ownerId,
    );
    joined.assertCurrent();
    return joined;
  } catch {
    joinedReceipts.delete(result);
    return undefined;
  }
}

/** Distinct copies/proxies have no entry. Pure-data passthrough is the original, not caller authority. */
export function readJoinedSmsReceiptForNativeSource(
  result: unknown,
  queue: unknown,
  claim: NativeSmsClaimRef,
): GateReceivedBinding | undefined {
  return readCurrentJoinedOrigin(result, queue, claim)?.binding;
}

/** Capture before arm; the returned private closure remains claim-independent after adoption. */
export function readJoinedSmsHostDestinationAssertionForNativeSource(
  result: unknown,
  queue: unknown,
  claim: NativeSmsClaimRef,
): (() => void) | undefined {
  return readCurrentJoinedOrigin(result, queue, claim)?.assertHostDestinationCurrent;
}
type Params = {
  controller: OpsysSmsHostController;
  accountId: string;
  /** Canonical Host state directory, not taken from a plugin request. */
  stateDir: string;
  signal: AbortSignal;
  assertCurrent: () => void;
};
function requireHost(condition: unknown): asserts condition {
  if (!condition) {
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}
function kindOf(value: unknown): unknown {
  if (typeof value !== "object" || value === null || types.isProxy(value)) {
    return undefined;
  }
  const descriptor = Object.getOwnPropertyDescriptor(value, "kind");
  return descriptor?.enumerable && Object.hasOwn(descriptor, "value")
    ? descriptor.value
    : undefined;
}
function request(value: unknown, fields: readonly string[]): Record<string, unknown> {
  requireHost(typeof value === "object" && value !== null && !types.isProxy(value));
  const prototype = Object.getPrototypeOf(value);
  requireHost(prototype === Object.prototype || prototype === null);
  const keys = Reflect.ownKeys(value);
  requireHost(
    keys.length === fields.length &&
      keys.every((key) => typeof key === "string" && fields.includes(key)),
  );
  const data: Record<string, unknown> = Object.create(null);
  for (const key of fields) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    requireHost(descriptor?.enumerable && Object.hasOwn(descriptor, "value"));
    data[key] = descriptor.value;
  }
  return data;
}
function text(value: unknown): asserts value is string {
  requireHost(typeof value === "string" && value.length > 0);
}

export function createOpsysSmsHostClaimAdapter(params: Params): OpsysSmsHostClaimAdapter {
  const { controller, accountId, stateDir, signal, assertCurrent } = params;
  requireHost(typeof accountId === "string" && normalizeAccountId(accountId) === accountId);
  requireHost(typeof stateDir === "string" && path.isAbsolute(stateDir));
  const locator = controller.locator;
  const now = Date.now;
  let disposed = false;
  let reader: ChannelIngressQueueClaimIdentityReader | undefined;
  let preparation: Promise<ChannelIngressQueueClaimIdentityReader | null> | undefined;
  const dispose = () => {
    if (disposed) {
      return;
    }
    disposed = true;
    signal.removeEventListener("abort", dispose);
    const ownedReader = reader;
    reader = undefined;
    ownedReader?.dispose();
  };
  const checkHost = () => {
    try {
      signal.throwIfAborted();
      requireHost(!disposed);
      const result: unknown = assertCurrent();
      if (types.isPromise(result)) {
        // Reject an async guard, but observe native rejection without awaiting/custom then.
        void nativePromiseThen.call(result, undefined, () => undefined);
      }
      requireHost(result === undefined && controller.resolveLocator(locator) === controller);
    } catch {
      dispose();
      throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
    }
  };
  checkHost();
  // Construction is inert: queue creation does not open or migrate SQLite.
  const queue = createChannelIngressQueue({
    channelId: "sms",
    accountId,
    stateDir,
    access: "read-only",
  });
  const prepare = () => {
    preparation ??= (async () => {
      let prepared: ChannelIngressQueueClaimIdentityReader | undefined;
      try {
        checkHost();
        requireHost(queue.prepareClaimIdentityReader);
        prepared = await queue.prepareClaimIdentityReader();
        checkHost();
        reader = prepared;
        return prepared;
      } catch {
        prepared?.dispose();
        return null;
      }
    })();
    return preparation;
  };
  const resolve = async (input: unknown) => {
    try {
      const data = request(input, ["kind", "payload", "id", "token", "ownerId", "receivedAt"]);
      const { id, token, ownerId, receivedAt, payload } = data;
      text(id);
      text(token);
      text(ownerId);
      requireHost(
        Number.isSafeInteger(receivedAt) && typeof receivedAt === "number" && receivedAt >= 0,
      );
      const prepared = await prepare();
      checkHost();
      requireHost(prepared);
      const nativeRef = Object.freeze({ id, token, ownerId });
      const original = readOwnNativeSmsClaimOrigin(queue, nativeRef);
      requireHost(
        original && original.accountId === accountId && original.receivedAt === receivedAt,
      );
      // Parse only the bounded native string, never stringify the supplied plugin payload.
      const originalPayload: unknown = JSON.parse(original.payloadJson);
      // Join the selected queue account to the authentic capsule BEFORE any controller RPC.
      const originalFrame = request(originalPayload, ["version", "form", "capsule"]);
      requireHost(originalFrame.version === 2);
      const originalCapsule = request(originalFrame.capsule, [
        "version",
        "signature_url",
        "signature",
        "compte_id",
        "permission",
        "received_at",
        "commande_sha256",
        "destination_sha256",
      ]);
      requireHost(originalCapsule.compte_id === accountId);
      const assertClaimCurrent = () => {
        checkHost();
        const current = prepared.read({ id, claim: { token } });
        const currentOrigin = readOwnNativeSmsClaimOrigin(queue, nativeRef);
        requireHost(
          currentOrigin &&
            currentOrigin.queueScope === original.queueScope &&
            currentOrigin.payloadJson === original.payloadJson &&
            currentOrigin.receivedAt === original.receivedAt,
        );
        const time = now();
        requireHost(
          current?.id === id &&
            current.token === token &&
            current.ownerId === ownerId &&
            Number.isSafeInteger(time) &&
            current.claimedAt <= time &&
            time - current.claimedAt < INGRESS_CLAIM_LEASE_MS &&
            isLiveLocalIngressDrainOwner(current.ownerId),
        );
      };
      assertClaimCurrent();
      const result = await controller.resolveReceipt(payload, {
        nativeOriginal: Object.freeze({
          payload: originalPayload,
          receivedAt: original.receivedAt,
        }),
        id,
        receivedAt,
        signal,
        assertClaimCurrent,
      });
      assertClaimCurrent();
      if (result.status === "received") {
        const gateDestinationCurrent = readSmsReceiptHostDestinationAssertion(result);
        requireHost(gateDestinationCurrent);
        const assertHostDestinationCurrent = () => {
          checkHost();
          gateDestinationCurrent();
          checkHost();
        };
        const assertJoinedCurrent = () => {
          assertHostDestinationCurrent();
          assertClaimCurrent();
          assertHostDestinationCurrent();
        };
        assertJoinedCurrent();
        // Gate checked both owned V2 projections, including this original destination.
        const frame = request(originalPayload, ["version", "form", "capsule"]);
        const capsule = request(frame.capsule, [
          "version",
          "signature_url",
          "signature",
          "compte_id",
          "permission",
          "received_at",
          "commande_sha256",
          "destination_sha256",
        ]);
        text(capsule.destination_sha256);
        joinedReceipts.set(result, {
          queueScope: original.queueScope,
          claim: nativeRef,
          assertCurrent: assertJoinedCurrent,
          assertHostDestinationCurrent,
          binding: Object.freeze({
            status: "received",
            command: result.command,
            receipt: result.receipt,
            receivedAt: original.receivedAt,
            destinationSha256: capsule.destination_sha256,
          }),
        });
      }
      return result;
    } catch {
      return UNRESOLVED;
    }
  };
  signal.addEventListener("abort", dispose, { once: true });
  checkHost();
  return Object.freeze({
    locator,
    invoke(value: unknown, input: unknown) {
      const kind = kindOf(input);
      try {
        checkHost();
        requireHost(controller.resolveLocator(value) === controller);
        if (kind === "resolve") {
          return resolve(input);
        }
        if (kind === "capture") {
          const data = request(input, ["kind", "input"]);
          return controller.capture(data.input);
        }
        if (kind === "encode") {
          const data = request(input, ["kind", "handle", "receivedAt"]);
          return controller.encodeCaptured(data.handle, data.receivedAt);
        }
        throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
      } catch {
        if (kind !== "capture" && kind !== "encode") {
          return UNRESOLVED;
        }
        throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
      }
    },
    dispose,
  });
}
