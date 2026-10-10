/** Private Task classification; this requirement grants no Source or model admission. */
import { types } from "node:util";
import { ownDataValue } from "../channels/message-access/admission-evidence-scope-key.js";
import {
  bindRequiredSmsTaskContext,
  isRequiredSmsTaskContextCurrent,
} from "../channels/message-access/admission-evidence.js";
import { assertChannelTurnDispatchCurrent } from "../channels/turn/execution.js";
import {
  OPSYS_SMS_HOST_SELECTION_REFUSED,
  type OpsysSmsHostAuthority,
} from "../gateway/opsys-sms-host-authority.js";
import type { PluginRuntimeChannel } from "../plugins/runtime/types-channel.js";

const nativePromiseThen = Promise.prototype.then;

type ScopeOwner = Readonly<object>;
export type CreateOpsysSmsRequiredTaskRuntimeParams = Readonly<{
  runtime: PluginRuntimeChannel;
  authority: OpsysSmsHostAuthority;
  accountId: string;
  lifetime: object;
  abortSignal: AbortSignal;
  assertCurrent: () => void;
}>;

/** Prepared/inert: captures original native references, does NOT invoke current/publication. */
export function createOpsysSmsRequiredTaskRuntime(
  params: CreateOpsysSmsRequiredTaskRuntimeParams,
): Readonly<{
  runtime: PluginRuntimeChannel;
  dispose: () => void;
}> {
  let closed = false;
  const dispose = () => {
    closed = true;
  };
  const refuse = (): never => {
    dispose();
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  };
  const passiveRecord = (value: unknown): object => {
    if (value === null || typeof value !== "object" || types.isProxy(value)) {
      refuse();
    }
    return value;
  };
  const requireDataRecord = (value: unknown): object => {
    const record = passiveRecord(value);
    for (const key of Reflect.ownKeys(record)) {
      const descriptor = Object.getOwnPropertyDescriptor(record, key);
      if (!descriptor || !("value" in descriptor)) {
        refuse();
      }
    }
    return record;
  };
  // Copy only data descriptors. Never evaluate a getter while preparing native callbacks.
  const dataCopy = <T extends object>(value: T): T => {
    passiveRecord(value);
    const copy: T = Object.create(Object.getPrototypeOf(value));
    for (const key of Reflect.ownKeys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !("value" in descriptor)) {
        refuse();
      }
      Object.defineProperty(copy, key, {
        value: descriptor.value,
        enumerable: descriptor.enumerable,
        configurable: true,
        writable: true,
      });
    }
    return copy;
  };
  const runtime = params.runtime;
  const authority = params.authority;
  const { accountId, lifetime, abortSignal, assertCurrent } = params;
  const owner: ScopeOwner = Object.freeze({});
  const runtimeCopy = dataCopy(runtime);
  const originalInbound = runtimeCopy.inbound;
  const originalTurn = runtimeCopy.turn;
  const inboundCopy = dataCopy(originalInbound);
  const authorityCopy = dataCopy(authority);
  const isCurrent = authorityCopy.isCurrent;
  const captureSelection = authorityCopy.captureSelection;
  const methods = {
    buildContext: inboundCopy.buildContext,
    run: inboundCopy.run,
    runPreparedReply: inboundCopy.runPreparedReply,
    dispatch: inboundCopy.dispatch,
    dispatchReply: inboundCopy.dispatchReply,
  };
  if (
    originalInbound !== originalTurn ||
    !lifetime ||
    types.isProxy(lifetime) ||
    typeof isCurrent !== "function" ||
    typeof captureSelection !== "function" ||
    typeof assertCurrent !== "function" ||
    Object.values(methods).some((fn) => typeof fn !== "function")
  ) {
    refuse();
  }
  let selection: ReturnType<OpsysSmsHostAuthority["captureSelection"]> | undefined;
  const originalCurrent = () => {
    if (
      closed ||
      abortSignal.aborted ||
      ownDataValue(runtime, "inbound") !== originalInbound ||
      ownDataValue(runtime, "turn") !== originalTurn ||
      ownDataValue(authority, "isCurrent") !== isCurrent ||
      ownDataValue(authority, "captureSelection") !== captureSelection ||
      !isCurrent()
    ) {
      refuse();
    }
    for (const key of Object.keys(methods) as Array<keyof typeof methods>) {
      if (ownDataValue(originalInbound, key) !== methods[key]) {
        refuse();
      }
    }
    const original = captureSelection();
    if (original.accountId !== accountId || (selection && selection !== original)) {
      refuse();
    }
    selection ??= original;
    if (closed || abortSignal.aborted) {
      refuse();
    }
  };
  const current = () => {
    try {
      // A predecessor must fail before a callback that can update account runtime state.
      originalCurrent();
      assertChannelTurnDispatchCurrent(assertCurrent);
      originalCurrent();
    } catch {
      refuse();
    }
  };
  const validatePublicScope = (value: unknown) => {
    const input = passiveRecord(value);
    // Validation only. Classification comes from captured native Task, never these public labels.
    if (
      ownDataValue(input, "channel") !== "sms" ||
      ownDataValue(input, "accountId") !== accountId
    ) {
      refuse();
    }
  };
  const stamp = (context: unknown) => {
    current();
    const value = requireDataRecord(context);
    bindRequiredSmsTaskContext(value, owner);
    return value;
  };
  const assertContext = (context: unknown) => {
    current();
    if (!isRequiredSmsTaskContextCurrent(passiveRecord(context), owner)) {
      refuse();
    }
    // This checks classification/scope ONLY. Source, OriginalC/body and provider admission
    // are deliberately separate Root leases, not permission inferred from this requirement.
  };
  const compose = (prior: unknown, context?: unknown) => () => {
    current();
    if (context !== undefined) {
      assertContext(context);
    }
    if (prior !== undefined) {
      if (typeof prior !== "function") {
        refuse();
      }
      try {
        assertChannelTurnDispatchCurrent(prior);
      } catch {
        refuse();
      }
      current();
      if (context !== undefined) {
        assertContext(context);
      }
    }
  };
  // Native Proxy<T> retains the actual overloaded/generic method type; no blind cast from
  // ChannelRuntimeSurface's [key:string]:unknown. Its apply argv are deliberately unknown.
  const wrap = <T extends Function>(fn: T, invoke: (args: unknown[]) => unknown): T =>
    new Proxy(fn, { apply: (_target, _receiver, args: unknown[]) => invoke(args) });
  const mapResult = (result: unknown, after: (value: unknown) => unknown): unknown =>
    types.isPromise(result)
      ? nativePromiseThen.call(result, (value: unknown) => {
          current();
          return after(value);
        })
      : after(result);
  const prepareDispatch = (value: unknown) => {
    const input = dataCopy(passiveRecord(value));
    validatePublicScope(input);
    const context = ownDataValue(input, "ctxPayload");
    stamp(context); // fake/prepared context becomes required by this private owner, not legacy
    return {
      ...input,
      assertDispatchCurrent: compose(ownDataValue(input, "assertDispatchCurrent"), context),
    };
  };
  const wrapped: PluginRuntimeChannel["inbound"] = {
    ...inboundCopy,
    buildContext: wrap(methods.buildContext, (args) => {
      current();
      validatePublicScope(args[0]);
      const input = dataCopy(passiveRecord(args[0]));
      for (const key of ["sender", "conversation", "route", "reply", "message"]) {
        const nested = ownDataValue(input, key);
        if (nested !== undefined) {
          Object.defineProperty(input, key, { value: dataCopy(passiveRecord(nested)) });
        }
      }
      return mapResult(
        Reflect.apply(methods.buildContext, originalInbound, [input, ...args.slice(1)]),
        stamp,
      );
    }),
    run: wrap(methods.run, (args) => {
      current();
      validatePublicScope(args[0]);
      const input = dataCopy(passiveRecord(args[0]));
      const adapter = dataCopy(passiveRecord(ownDataValue(input, "adapter")));
      const resolve = ownDataValue(adapter, "resolveTurn"); // captured BEFORE callback/await
      if (typeof resolve !== "function") {
        refuse();
      }
      const resolveTurn = wrap(resolve, (resolveArgs) => {
        current();
        return mapResult(Reflect.apply(resolve, adapter, resolveArgs), prepareDispatch);
      });
      return Reflect.apply(methods.run, originalInbound, [
        {
          ...input,
          adapter: { ...adapter, resolveTurn },
          assertDispatchCurrent: compose(ownDataValue(input, "assertDispatchCurrent")),
        },
        ...args.slice(1),
      ]);
    }),
    runPreparedReply: wrap(methods.runPreparedReply, (args) => {
      current();
      return Reflect.apply(methods.runPreparedReply, originalInbound, [
        prepareDispatch(args[0]),
        ...args.slice(1),
      ]);
    }),
    dispatch: wrap(methods.dispatch, (args) => {
      current();
      return Reflect.apply(methods.dispatch, originalInbound, [
        prepareDispatch(args[0]),
        ...args.slice(1),
      ]);
    }),
    dispatchReply: wrap(methods.dispatchReply, (args) => {
      current();
      return Reflect.apply(methods.dispatchReply, originalInbound, [
        prepareDispatch(args[0]),
        ...args.slice(1),
      ]);
    }),
  };
  Object.freeze(wrapped);
  return Object.freeze({
    runtime: Object.freeze({ ...runtimeCopy, inbound: wrapped, turn: wrapped }),
    dispose,
  });
}
