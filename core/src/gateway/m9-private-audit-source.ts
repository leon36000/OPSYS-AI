import {
  assertAdmittedRunOperatorAuthority,
  type AdmittedRunOperatorAuthority,
} from "../agents/admitted-run-context.js";
import { resolveGatewayOperatorRoleActor } from "./operator-role-policy.js";
import { captureGatewayOperatorRunAuthority } from "./operator-run-authority.js";
import { readGatewayRequestMutationAuthority } from "./server-methods/session-mutation-guards.js";
import type { GatewayRequestHandlerOptions } from "./server-methods/shared-types.js";

const M9_AUDIT_DRAFT_METHOD = "opsys.m9.auditDraft";
const OPERATOR_ADMIN_SCOPE = "operator.admin";

type PrivateM9AuditSourceCode =
  | "METHOD_REQUIRED"
  | "DIRECT_OPERATOR_REQUIRED"
  | "FRESH_SOURCE_REQUIRED"
  | "WORKER_REQUIRED"
  | "WORKER_NOT_CURRENT"
  | "CAPTURE_REQUIRED"
  | "CAPTURE_FAILED"
  | "BRANDED_AUTHORITY_REQUIRED"
  | "ADMIN_REQUIRED"
  | "SIGNAL_REQUIRED"
  | "SOURCE_REVOKED"
  | "CLOSED"
  | "CLOSE_FAILED";

/** Original operator source retained by the private audit draft; never an M9 purpose or grant. */
export type PrivateM9AuditSource = Readonly<{
  operatorAuthority: AdmittedRunOperatorAuthority;
  assertSourceCurrent: () => void;
  signal: AbortSignal;
  close: () => void;
}>;

function refusal(code: PrivateM9AuditSourceCode, cause?: unknown): Error {
  const message = `M9_PRIVATE_AUDIT_SOURCE_${code}`;
  return cause === undefined ? new Error(message) : new Error(message, { cause });
}

function closeFailure(primaryError: unknown, cleanupError: unknown): AggregateError {
  return new AggregateError([primaryError, cleanupError], "M9_PRIVATE_AUDIT_SOURCE_CLOSE_FAILED", {
    cause: cleanupError,
  });
}

/**
 * Admits only a fresh direct operator worker request, then retains its canonical source.
 * The worker proof is initial transport admission; accepted lifetime follows the captured source.
 */
export function capturePrivateM9AuditSource(
  options: GatewayRequestHandlerOptions,
): PrivateM9AuditSource {
  if (options.req?.method !== M9_AUDIT_DRAFT_METHOD) {
    throw refusal("METHOD_REQUIRED");
  }
  const client = options.client;
  if (
    !client?.connect ||
    client.connect.role !== "operator" ||
    client.internal?.syntheticClient ||
    resolveGatewayOperatorRoleActor(client)?.kind !== "operator"
  ) {
    throw refusal("DIRECT_OPERATOR_REQUIRED");
  }
  if (
    client.internal?.operatorRunAuthority !== undefined ||
    client.internal?.agentRuntimeIdentity !== undefined
  ) {
    throw refusal("FRESH_SOURCE_REQUIRED");
  }
  const worker = readGatewayRequestMutationAuthority(options);
  if (worker.family !== "worker" || typeof worker.assertWorkerCurrent !== "function") {
    throw refusal("WORKER_REQUIRED");
  }
  try {
    // Initial admission only: tentative fencing must not reach the accepted source later.
    worker.assertCurrent();
  } catch (error) {
    throw refusal("WORKER_NOT_CURRENT", error);
  }

  let captured: ReturnType<typeof captureGatewayOperatorRunAuthority>;
  try {
    captured = captureGatewayOperatorRunAuthority(options);
  } catch (error) {
    throw refusal("CAPTURE_FAILED", error);
  }
  if (!captured) {
    throw refusal("CAPTURE_REQUIRED");
  }
  const { authority, release } = captured;
  try {
    try {
      assertAdmittedRunOperatorAuthority(authority);
    } catch (error) {
      throw refusal("BRANDED_AUTHORITY_REQUIRED", error);
    }
    if (!authority.scopes.includes(OPERATOR_ADMIN_SCOPE)) {
      throw refusal("ADMIN_REQUIRED");
    }
    const sourceSignal = authority.signal;
    if (!(sourceSignal instanceof AbortSignal)) {
      throw refusal("SIGNAL_REQUIRED");
    }
    try {
      sourceSignal.throwIfAborted();
      authority.assertCurrent();
      sourceSignal.throwIfAborted();
    } catch (error) {
      throw refusal("SOURCE_REVOKED", error);
    }
    return retainAcceptedSource(authority, sourceSignal, release);
  } catch (primaryError) {
    try {
      release();
    } catch (cleanupError) {
      throw closeFailure(primaryError, cleanupError);
    }
    throw primaryError;
  }
}

// Closes over the captured authority only; request options, worker and socket are not retained.
function retainAcceptedSource(
  authority: AdmittedRunOperatorAuthority,
  sourceSignal: AbortSignal,
  release: () => void,
): PrivateM9AuditSource {
  const closeController = new AbortController();
  let state: "open" | "closed" | "revoked" = "open";
  let revocationReason: unknown;
  let released = false;
  let deferredCleanupError: { error: unknown } | undefined;

  const releaseInitialHold = () => {
    if (released) {
      return;
    }
    released = true;
    sourceSignal.removeEventListener("abort", onSourceAbort);
    release();
  };
  const latch = (next: "closed" | "revoked", reason: unknown) => {
    if (state !== "open") {
      return;
    }
    state = next;
    revocationReason = reason;
    closeController.abort(
      next === "closed" ? refusal("CLOSED") : refusal("SOURCE_REVOKED", reason),
    );
    releaseInitialHold();
  };
  // Listener failures are reported by the next close/assert, never as unhandled events.
  function onSourceAbort(): void {
    try {
      latch("revoked", sourceSignal.reason);
    } catch (cleanupError) {
      deferredCleanupError ??= { error: cleanupError };
    }
  }
  const takeDeferredCleanupError = () => {
    const pending = deferredCleanupError;
    deferredCleanupError = undefined;
    return pending;
  };

  sourceSignal.addEventListener("abort", onSourceAbort, { once: true });

  const assertSourceCurrent = () => {
    if (state !== "open") {
      const primaryError =
        state === "closed" ? refusal("CLOSED") : refusal("SOURCE_REVOKED", revocationReason);
      const pending = takeDeferredCleanupError();
      throw pending ? closeFailure(primaryError, pending.error) : primaryError;
    }
    try {
      sourceSignal.throwIfAborted();
      authority.assertCurrent();
      sourceSignal.throwIfAborted();
    } catch (error) {
      const primaryError = refusal("SOURCE_REVOKED", error);
      try {
        latch("revoked", error);
      } catch (cleanupError) {
        throw closeFailure(primaryError, cleanupError);
      }
      const pending = takeDeferredCleanupError();
      throw pending ? closeFailure(primaryError, pending.error) : primaryError;
    }
    // A synchronous source check can close this local owner while retaining another hold.
    if (state !== "open") {
      const primaryError =
        state === "closed" ? refusal("CLOSED") : refusal("SOURCE_REVOKED", revocationReason);
      const pending = takeDeferredCleanupError();
      throw pending ? closeFailure(primaryError, pending.error) : primaryError;
    }
  };
  const close = () => {
    if (state === "open") {
      try {
        latch("closed", undefined);
      } catch (cleanupError) {
        throw refusal("CLOSE_FAILED", cleanupError);
      }
      return;
    }
    const pending = takeDeferredCleanupError();
    if (pending) {
      throw refusal("CLOSE_FAILED", pending.error);
    }
  };

  return Object.freeze({
    operatorAuthority: authority,
    assertSourceCurrent,
    signal: AbortSignal.any([sourceSignal, closeController.signal]),
    close,
  });
}
