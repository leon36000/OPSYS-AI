import { AsyncLocalStorage } from "node:async_hooks";
import { isPromiseLike } from "@openclaw/normalization-core/promise-like";
import { captureGuardedFetchRequestAuthority } from "../infra/net/fetch-request-authority.js";
import type { Model } from "../llm/types.js";
import { resolveGlobalSingleton } from "../shared/global-singleton.js";

type PrivateProviderRequestRoute = {
  provider: string;
  modelId: string;
  sourceApi: string;
  url: string;
};

export type PrivateProviderRequestFence = {
  readonly signal: AbortSignal;
  validateFetch: (model: Model, url: string, init?: RequestInit) => void;
  claim: () => void;
};

const owner = resolveGlobalSingleton(Symbol.for("opsys.privateSingleProviderRequest"), () => ({
  scope: new AsyncLocalStorage<PrivateProviderRequestFence>(),
  issued: new WeakSet<PrivateProviderRequestFence>(),
}));

function refuse(reason: string): Error {
  return new Error(`M9_SINGLE_PROVIDER_REQUEST_${reason}`);
}

/** Capture both construction and invocation scope; never replace a retained restriction. */
export function capturePrivateProviderRequestFence(
  bound?: PrivateProviderRequestFence,
): PrivateProviderRequestFence | undefined {
  const current = owner.scope.getStore();
  if ((bound && !owner.issued.has(bound)) || (current && !owner.issued.has(current))) {
    throw refuse("UNKNOWN_FENCE");
  }
  if (bound && current && bound !== current) {
    throw refuse("SCOPE_CONFLICT");
  }
  return bound ?? current;
}

/** Restriction only. The caller still owns admission, source authority, result and drainage. */
export async function withPrivateSingleProviderRequest<T>(
  options: {
    assertCurrent: () => void;
    signal: AbortSignal;
    route: PrivateProviderRequestRoute;
  },
  run: () => Promise<T>,
): Promise<T> {
  if (owner.scope.getStore()) {
    throw refuse("NESTED_SCOPE");
  }
  const signal = options.signal;
  const assertSource = options.assertCurrent;
  const inherited = captureGuardedFetchRequestAuthority();
  const route = Object.freeze({ ...options.route });
  if ([route.provider, route.modelId, route.sourceApi].some((value) => !value)) {
    throw refuse("UNSUPPORTED_ROUTE");
  }
  let endpoint: string;
  try {
    const parsed = new URL(route.url);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
      throw refuse("UNSUPPORTED_ROUTE");
    }
    endpoint = parsed.href;
  } catch {
    throw refuse("UNSUPPORTED_ROUTE");
  }
  let active = true;
  let terminal = false;
  let claimed = false;
  const assertCurrent = () => {
    if (!active || terminal) {
      throw refuse("CLOSED");
    }
    try {
      signal.throwIfAborted();
      inherited?.();
      const result: unknown = assertSource();
      if (isPromiseLike(result)) {
        void Promise.resolve(result).catch(() => undefined);
        throw new TypeError("M9_SINGLE_PROVIDER_REQUEST_ASYNC_AUTHORITY");
      }
      signal.throwIfAborted();
    } catch (error) {
      terminal = true;
      throw error;
    }
  };
  const fence: PrivateProviderRequestFence = Object.freeze({
    signal,
    validateFetch(model: Model, url: string, init?: RequestInit) {
      assertCurrent();
      let requestUrl: string;
      try {
        requestUrl = new URL(url).href;
      } catch {
        terminal = true;
        throw refuse("UNSUPPORTED_REQUEST");
      }
      if (
        model.provider !== route.provider ||
        model.id !== route.modelId ||
        model.api !== route.sourceApi ||
        requestUrl !== endpoint ||
        init?.method?.toUpperCase() !== "POST" ||
        typeof init?.body !== "string"
      ) {
        terminal = true;
        throw refuse("ROUTE_MISMATCH");
      }
    },
    claim() {
      assertCurrent();
      if (claimed) {
        throw refuse("ALREADY_CLAIMED");
      }
      claimed = true;
    },
  });
  owner.issued.add(fence);
  try {
    assertCurrent();
    return await owner.scope.run(fence, run);
  } finally {
    active = false;
  }
}
