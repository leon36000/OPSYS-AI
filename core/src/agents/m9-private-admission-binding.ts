import { isPromiseLike } from "@openclaw/normalization-core/promise-like";
import {
  prepareAgentRunAdmission,
  resolveAdmittedRunActiveAssertion,
  type AdmittedRunContext,
  type PreparedAgentRunAdmission,
} from "./admitted-run-context.js";

export type PrivateM9AdmissionReceipt = Readonly<{
  context: AdmittedRunContext;
  assertCurrent: () => void;
}>;

export type PrivateM9AdmissionBinding = Readonly<{
  admit: PreparedAgentRunAdmission["admit"];
  claim: (context: AdmittedRunContext) => PrivateM9AdmissionReceipt;
  close: () => void;
}>;

type PrivateM9AdmissionOptions = Omit<
  Parameters<typeof prepareAgentRunAdmission>[0],
  "onAdmitted"
> & { signal: AbortSignal };

function refuse(reason: string): Error {
  return new Error(`M9_PRIVATE_ADMISSION_${reason}`);
}

/** Private lifetime restriction only; it neither issues authority nor dispatches work. */
export function preparePrivateM9AdmissionBinding(
  options: PrivateM9AdmissionOptions,
): PrivateM9AdmissionBinding {
  const { signal, assertSourceCurrent: sourceAssertion, ...admissionOptions } = options;
  let closed = false;
  let spent = false;
  let capturedContext: AdmittedRunContext | undefined;
  let admission: Promise<AdmittedRunContext> | undefined;
  let ready: { context: AdmittedRunContext; assertActive: () => void } | undefined;

  const prepared = prepareAgentRunAdmission({
    ...admissionOptions,
    assertSourceCurrent: () => {
      signal.throwIfAborted();
      const result: unknown = sourceAssertion?.();
      if (isPromiseLike(result)) {
        // Observe rejection without accepting asynchronous authority or hiding refusal.
        void Promise.resolve(result).catch(() => undefined);
        throw new TypeError("M9_PRIVATE_ADMISSION_ASYNC_SOURCE_ASSERTION");
      }
      signal.throwIfAborted();
    },
    // Canonical admission binds the live context before this synchronous store-only seam.
    onAdmitted: (context) => {
      capturedContext = context;
    },
  });

  const close = () => {
    if (closed) {
      return;
    }
    closed = true;
    capturedContext = undefined;
    ready = undefined;
    prepared.close();
  };

  const terminate = (error: unknown): never => {
    try {
      close();
    } catch (cleanupError) {
      throw new AggregateError([error, cleanupError], "M9_PRIVATE_ADMISSION_CLOSE_FAILED", {
        cause: cleanupError,
      });
    }
    throw error;
  };

  const assertSource = () => {
    if (closed) {
      throw refuse("CLOSED");
    }
    try {
      signal.throwIfAborted();
      prepared.assertSourceCurrent();
      signal.throwIfAborted();
      if (closed) {
        throw refuse("CLOSED");
      }
    } catch (error) {
      terminate(error);
    }
  };

  const assertContext = (context: AdmittedRunContext) => {
    try {
      assertSource();
      const current = ready;
      if (!current || context !== current.context) {
        throw refuse("EXACT_SETTLED_CONTEXT_REQUIRED");
      }
      signal.throwIfAborted();
      current.assertActive();
      signal.throwIfAborted();
      if (closed || ready !== current) {
        throw refuse("CLOSED");
      }
    } catch (error) {
      terminate(error);
    }
  };

  return Object.freeze({
    admit: (
      runtimeKind: Parameters<PreparedAgentRunAdmission["admit"]>[0],
      runtimeInstanceId?: string,
    ) => {
      try {
        assertSource();
        if (admission) {
          return admission;
        }
        admission = prepared.admit(runtimeKind, runtimeInstanceId).then(
          (context) => {
            try {
              assertSource();
              if (context !== capturedContext) {
                throw refuse("ADMITTED_CONTEXT_MISMATCH");
              }
              signal.throwIfAborted();
              const assertActive = resolveAdmittedRunActiveAssertion(context, signal);
              signal.throwIfAborted();
              if (closed) {
                throw refuse("CLOSED");
              }
              if (!assertActive) {
                throw refuse("ACTIVE_CONTEXT_REQUIRED");
              }
              ready = { context, assertActive };
              assertContext(context);
              return context;
            } catch (error) {
              return terminate(error);
            }
          },
          (error: unknown) => terminate(error),
        );
        // Keep an abandoned owned rejection observed; callers still receive the rejected promise.
        void admission.catch(() => undefined);
        return admission;
      } catch (error) {
        try {
          terminate(error);
        } catch (failure) {
          return Promise.reject(failure);
        }
      }
    },
    claim: (context: AdmittedRunContext) => {
      if (spent) {
        const current = ready;
        if (!current) {
          return terminate(refuse("CLOSED"));
        }
        assertContext(current.context);
        // A duplicate cannot invalidate the first owner's still-live result drainage.
        throw refuse("ALREADY_CLAIMED");
      }
      assertContext(context);
      spent = true;
      return Object.freeze({ context, assertCurrent: () => assertContext(context) });
    },
    close,
  });
}
