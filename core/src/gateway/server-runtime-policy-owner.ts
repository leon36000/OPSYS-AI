// Private Core owners. These handles are not SDK or Gateway permissions.
import { types } from "node:util";
import {
  getRuntimeConfigPublicationReceipt,
  isRuntimeConfigPublicationReceiptCurrent,
  readRuntimeConfigPublicationConfig,
  type RuntimeConfigPublicationReceipt,
} from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import {
  readSecretsRuntimeActivationLineage,
  readSecretsRuntimeActivationReceipt,
} from "../secrets/runtime-state.js";
import {
  SharedGatewaySessionGenerationState,
  type SharedGatewaySessionGenerationOwnership,
} from "./server-shared-auth-generation.js";

export type NativePolicyOwner = Readonly<object>;
export type NativeTransitionTicket = Readonly<object>;
export type NativeServingRead = Readonly<object>;
type Bucket = {
  state: SharedGatewaySessionGenerationState;
  owner?: NativePolicyOwner;
  epoch: object;
  pending: Set<NativeTransitionTicket>;
};
type Serving = {
  config: OpenClawConfig;
  receipt: RuntimeConfigPublicationReceipt;
  ownership: SharedGatewaySessionGenerationOwnership;
};
type Owner = {
  bucket: Bucket;
  signal: AbortSignal;
  settled: () => boolean;
  closed: boolean;
  serving?: Serving;
};
type Ticket = { bucket: Bucket; owner?: NativePolicyOwner; active: boolean };
type Read = { owner: NativePolicyOwner; epoch: object; serving: Serving };
const buckets = new WeakMap<SharedGatewaySessionGenerationState, Bucket>();
const owners = new WeakMap<NativePolicyOwner, Owner>();
const tickets = new WeakMap<NativeTransitionTicket, Ticket>();
const reads = new WeakMap<NativeServingRead, Read>();

function bucketFor(state: SharedGatewaySessionGenerationState | NativePolicyOwner): Bucket {
  if (types.isProxy(state) || !(state instanceof SharedGatewaySessionGenerationState)) {
    throw new Error("NATIVE-SERVING-NOT-CURRENT");
  }
  // The intrinsic uses private fields, rejecting structural substitutes.
  SharedGatewaySessionGenerationState.prototype.capture.call(state);
  let bucket = buckets.get(state);
  if (!bucket) {
    bucket = { state, epoch: {}, pending: new Set() };
    buckets.set(state, bucket);
  }
  return bucket;
}

function currentOwner(handle: NativePolicyOwner): Owner | undefined {
  const owner = owners.get(handle);
  if (!owner || owner.closed || owner.signal.aborted || owner.bucket.owner !== handle) {
    return undefined;
  }
  return owner;
}

function currentServing(owner: Owner): Serving | undefined {
  const serving = owner.serving;
  if (
    !serving ||
    !SharedGatewaySessionGenerationState.prototype.owns.call(
      owner.bucket.state,
      serving.ownership,
    ) ||
    !isRuntimeConfigPublicationReceiptCurrent(serving.receipt) ||
    readRuntimeConfigPublicationConfig(serving.receipt) !== serving.config ||
    readSecretsRuntimeActivationLineage(serving.receipt)?.publishedConfig !== serving.config ||
    !SharedGatewaySessionGenerationState.prototype.owns.call(owner.bucket.state, serving.ownership)
  ) {
    return undefined;
  }
  return serving;
}

export function createManagedPolicyOwner(
  state: SharedGatewaySessionGenerationState,
  signal: AbortSignal,
  settled: () => boolean,
): NativePolicyOwner {
  const bucket = bucketFor(state);
  if (bucket.owner) {
    closeNativeOwner(bucket.owner);
  }
  const handle = Object.freeze({});
  owners.set(handle, { bucket, signal, settled, closed: signal.aborted });
  bucket.owner = handle;
  bucket.epoch = {};
  return handle;
}

export function findOwner(
  state: SharedGatewaySessionGenerationState,
): NativePolicyOwner | undefined {
  const handle = buckets.get(state)?.owner;
  return handle && currentOwner(handle) ? handle : undefined;
}

export function reserveNativeTransition(
  stateOrOwner: SharedGatewaySessionGenerationState | NativePolicyOwner,
): NativeTransitionTicket {
  const owner = owners.get(stateOrOwner);
  const bucket = owner?.bucket ?? bucketFor(stateOrOwner);
  const handle = Object.freeze({});
  bucket.epoch = {};
  tickets.set(handle, {
    bucket,
    owner: owner ? stateOrOwner : bucket.owner,
    active: true,
  });
  bucket.pending.add(handle);
  return handle;
}

export function finishNativeTransition(handle: NativeTransitionTicket): void {
  const ticket = tickets.get(handle);
  if (!ticket?.active) {
    return;
  }
  ticket.active = false;
  ticket.bucket.pending.delete(handle);
}

export function closeNativeOwner(handle: NativePolicyOwner): void {
  const owner = owners.get(handle);
  if (!owner || owner.closed) {
    return;
  }
  owner.closed = true;
  owner.bucket.epoch = {};
}

export function recordNativeServingCommit(
  handle: NativePolicyOwner,
  origin: OpenClawConfig,
  ticketHandle: NativeTransitionTicket,
  ownership: SharedGatewaySessionGenerationOwnership,
): boolean {
  const owner = currentOwner(handle);
  const ticket = tickets.get(ticketHandle);
  if (
    !owner ||
    !ticket?.active ||
    ticket.owner !== handle ||
    ticket.bucket !== owner.bucket ||
    !owner.bucket.pending.has(ticketHandle) ||
    types.isProxy(ownership)
  ) {
    return false;
  }
  const native = SharedGatewaySessionGenerationState.prototype.capture.call(owner.bucket.state);
  if (
    ownership.revision !== native.revision ||
    ownership.generation !== native.generation ||
    ownership.previousGeneration !== native.previousGeneration
  ) {
    return false;
  }
  const receipt =
    readSecretsRuntimeActivationReceipt(origin) ?? getRuntimeConfigPublicationReceipt(origin);
  const lineage = receipt && readSecretsRuntimeActivationLineage(receipt);
  if (
    !receipt ||
    !lineage ||
    (origin !== lineage.originalConfig && origin !== lineage.publishedConfig) ||
    readRuntimeConfigPublicationConfig(receipt) !== lineage.publishedConfig ||
    !isRuntimeConfigPublicationReceiptCurrent(receipt) ||
    !SharedGatewaySessionGenerationState.prototype.owns.call(owner.bucket.state, native) ||
    !currentOwner(handle) ||
    !ticket.active ||
    ticket.owner !== handle ||
    !owner.bucket.pending.has(ticketHandle)
  ) {
    return false;
  }
  // The argument above checks congruence only. Retain the intrinsic native
  // capture, never a caller tuple, as the private last-use generation fence.
  owner.serving = { config: lineage.publishedConfig, receipt, ownership: Object.freeze(native) };
  return true;
}

export function readNativeServingConfig(handle: NativePolicyOwner): OpenClawConfig | undefined {
  const owner = currentOwner(handle);
  return owner && currentServing(owner)?.config;
}

function readable(handle: NativePolicyOwner): Owner | undefined {
  const owner = currentOwner(handle);
  if (!owner || owner.bucket.pending.size > 0 || !owner.settled() || !currentOwner(handle)) {
    return undefined;
  }
  return owner.bucket.pending.size === 0 ? owner : undefined;
}

export function captureNativeServingRead(handle: NativePolicyOwner): NativeServingRead | undefined {
  const owner = readable(handle);
  const serving = owner && currentServing(owner);
  if (!owner || !serving) {
    return undefined;
  }
  const epoch = owner.bucket.epoch;
  if (
    !readable(handle) ||
    currentServing(owner) !== serving ||
    owner.bucket.epoch !== epoch ||
    !currentOwner(handle)
  ) {
    return undefined;
  }
  const read = Object.freeze({});
  reads.set(read, { owner: handle, epoch, serving });
  return read;
}

export function assertNativeServingRead(handle: NativeServingRead | undefined): void {
  const read = handle && reads.get(handle);
  const owner = read && readable(read.owner);
  if (
    !read ||
    !owner ||
    read.epoch !== owner.bucket.epoch ||
    currentServing(owner) !== read.serving ||
    !readable(read.owner) ||
    currentServing(owner) !== read.serving ||
    read.epoch !== owner.bucket.epoch ||
    !currentOwner(read.owner)
  ) {
    throw new Error("NATIVE-SERVING-NOT-CURRENT");
  }
}
