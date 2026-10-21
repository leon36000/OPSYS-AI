// Passive transcript guards; registry.ts alone owns wrapper/source association.
import { PluginInvocationScope } from "../plugins/plugin-invocation-scope.js";
import {
  inheritRuntimeCompactionDelegate,
  markRuntimeCompactionDelegate,
} from "./compaction-watchdog.js";
import { contextEngineAbortSignal, isContextEngineAbortRejection } from "./context-engine-abort.js";
import { readDefaultOpsysTranscriptSource } from "./opsys-contexte-engine.js";
import { projectContextEngineHostParams } from "./registry-contract.js";
import type { ContextEngineFactoryResources } from "./registry.resources.js";
import type { ContextEngine } from "./types.js";

type TranscriptState = "absent" | "live" | "unavailable";
type GuardedContextEngineMethod = (...args: never[]) => unknown;
type GuardedContextEngineMethodName = Exclude<keyof ContextEngine, "info" | "dispose">;

export function readHostOwnedTranscriptState(params: {
  candidate: boolean;
  nativeSource: ContextEngine;
  inheritedTranscript?: () => TranscriptState;
  source?: ContextEngineFactoryResources;
  factoryInvocation: unknown;
  isClosed: () => boolean;
}): TranscriptState {
  if (!params.candidate) {
    return "absent";
  }
  if (
    params.isClosed() ||
    readDefaultOpsysTranscriptSource(params.nativeSource) !== "unaltered" ||
    (params.inheritedTranscript && params.inheritedTranscript() !== "live") ||
    params.source?.work.isClosing
  ) {
    return "unavailable";
  }
  try {
    const { source, factoryInvocation } = params;
    if (source) {
      // Captured inside source.run at construction; never consult a current registry.
      if (!(factoryInvocation instanceof PluginInvocationScope)) {
        return "unavailable";
      }
      source.context(() => source.work.run(() => factoryInvocation.run(() => undefined)));
    }
    return "live";
  } catch {
    return "unavailable";
  }
}

function assertTranscriptLive(read: () => TranscriptState): void {
  const state = read();
  if (state !== "absent" && state !== "live") {
    throw new Error("host-owned OPSYS transcript composition is unavailable");
  }
}

function guardTranscriptInvocation<Args extends unknown[]>(
  candidate: boolean,
  read: () => TranscriptState,
  invoke: (...args: Args) => unknown,
): (...args: Args) => unknown {
  if (!candidate) {
    return invoke;
  }
  return async (...args) => {
    assertTranscriptLive(read);
    let result: unknown;
    try {
      result = await invoke(...args);
    } catch (error) {
      assertTranscriptLive(read);
      throw error;
    }
    // A retained async call cannot return success after its original owner closes.
    assertTranscriptLive(read);
    return result;
  };
}

function projectTranscriptInvocation(
  candidate: boolean,
  engine: ContextEngine,
  methodName: GuardedContextEngineMethodName,
  method: (...args: never[]) => unknown,
  params: Record<string, unknown>,
): () => unknown {
  const nativeProjected = candidate
    ? projectContextEngineHostParams(engine, methodName, params)
    : undefined;
  return () =>
    Reflect.apply(method, engine, [
      candidate ? nativeProjected : projectContextEngineHostParams(engine, methodName, params),
    ]);
}

function inheritCompactionWatchdogOwnership(
  property: PropertyKey,
  source: GuardedContextEngineMethod,
  wrapped: GuardedContextEngineMethod,
): GuardedContextEngineMethod {
  if (property !== "compact") {
    return wrapped;
  }
  // SAFETY: the compact property narrows both functions to the ContextEngine compact contract.
  const compact = source as ContextEngine["compact"];
  // SAFETY: guarded compact wrappers preserve the source method's single-parameter contract.
  const wrappedCompact = wrapped as ContextEngine["compact"];
  return inheritRuntimeCompactionDelegate(compact, wrappedCompact);
}

export function guardResolvedTranscriptMethod(params: {
  engine: ContextEngine;
  method: (params: Record<string, unknown>) => unknown;
  methodName: GuardedContextEngineMethodName;
  candidate: boolean;
  read: () => TranscriptState;
  isQuarantined: () => boolean;
  invokeFallback?: (params: Record<string, unknown>) => Promise<unknown>;
  recordFailure: (error: unknown) => void;
}): GuardedContextEngineMethod {
  const { engine, method, methodName, candidate, read, isQuarantined } = params;
  const assertLive = () => assertTranscriptLive(read);
  const guard = <Args extends unknown[]>(invoke: (...args: Args) => unknown) =>
    guardTranscriptInvocation(candidate, read, invoke);
  const preserveWatchdog = (invoke: GuardedContextEngineMethod) =>
    inheritCompactionWatchdogOwnership(methodName, method, invoke);
  if (!params.invokeFallback) {
    const invoke = (methodParams: Record<string, unknown>) => {
      const projected = projectContextEngineHostParams(engine, methodName, methodParams);
      assertLive();
      return method.call(engine, projected);
    };
    return preserveWatchdog(guard(invoke));
  }
  const invokeFallback = async (methodParams: Record<string, unknown>) => {
    contextEngineAbortSignal(methodParams);
    assertLive();
    return await params.invokeFallback!(methodParams);
  };
  if (isQuarantined()) {
    return methodName === "compact"
      ? markRuntimeCompactionDelegate(guard(invokeFallback) as ContextEngine["compact"])
      : guard(invokeFallback);
  }
  const invoke = async (methodParams: Record<string, unknown>) => {
    const abortSignal = contextEngineAbortSignal(methodParams);
    assertLive();
    if (isQuarantined()) {
      return await invokeFallback(methodParams);
    }
    const invokeMethod = projectTranscriptInvocation(
      candidate,
      engine,
      methodName,
      method,
      methodParams,
    );
    assertLive();
    try {
      return await invokeMethod();
    } catch (error) {
      // An expired lifetime must never enter quarantine or fallback recovery.
      assertLive();
      if (isContextEngineAbortRejection(error, abortSignal)) {
        throw error;
      }
      params.recordFailure(error);
      if (methodName === "compact" || methodName === "prepareSubagentSpawn") {
        throw error;
      }
      return await invokeFallback(methodParams).catch(() => {
        throw error;
      });
    }
  };
  return preserveWatchdog(guard(invoke));
}
