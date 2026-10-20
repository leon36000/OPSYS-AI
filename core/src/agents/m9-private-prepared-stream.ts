import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PrivateM9AuditSource } from "../gateway/m9-private-audit-source.js";
import { getModelCompletionTransport } from "../llm/model-runtime-binding.js";
import type { Model } from "../llm/types.js";
import { AsyncWorkScope } from "../shared/async-work-scope.js";
import {
  assertAdmittedRunOperatorAuthority,
  readAdmittedRunOperatorAuthority,
  type AdmittedRunContext,
} from "./admitted-run-context.js";
import {
  closeOpsysRuntimeCompletionCustody,
  consumeOpsysRuntimeCompletionCustody,
  createOpsysRuntimeAdmissionStreamFn,
  createOpsysRuntimeCompletionCustody,
  type OpsysRuntimeCompletionReceipt,
} from "./embedded-agent-runner/opsys-runtime-admission.js";
import type { PrivateM9AdmissionBinding } from "./m9-private-admission-binding.js";
import { withPrivateSingleProviderRequest } from "./private-single-provider-request.js";
import {
  withPreparedSimpleCompletionStream,
  type completeWithPreparedSimpleCompletionModel,
} from "./simple-completion-execution.js";
import type { acquireSimpleCompletionModelForAgent } from "./simple-completion-runtime.js";

type PreparedLease = Extract<
  Awaited<ReturnType<typeof acquireSimpleCompletionModelForAgent>>,
  { model: Model }
>;
type CompletionCustody = ReturnType<typeof createOpsysRuntimeCompletionCustody>;
export type PrivateM9PreparedStreamOptions = {
  prepared: PreparedLease;
  source: PrivateM9AuditSource;
  admission: PrivateM9AdmissionBinding;
  context: AdmittedRunContext;
  config: OpenClawConfig;
  custodyBinding: Parameters<typeof createOpsysRuntimeCompletionCustody>[0];
  route: Parameters<typeof withPrivateSingleProviderRequest>[0]["route"];
  completion: Pick<
    Parameters<typeof completeWithPreparedSimpleCompletionModel>[0],
    "context" | "options"
  >;
};
type PrivateM9PreparedStreamResult = Readonly<{
  payloadJSON: string;
  receipt: OpsysRuntimeCompletionReceipt;
}>;

// These restrictions prevent a duplicate invocation from closing the first owner's resources.
const ownedLeases = new WeakSet<object>();
const ownedAdmissions = new WeakSet<PrivateM9AdmissionBinding>();
const ownedSources = new WeakSet<PrivateM9AuditSource>();
function refuse(reason: string): Error {
  return new Error(`M9_PRIVATE_PREPARED_STREAM_${reason}`);
}
function throwFailures(errors: unknown[]): void {
  // A retained failure may be observed again when its prepared lease is disposed.
  const failures = Array.from(new Set(errors));
  if (failures.length === 1) {
    throw failures[0];
  }
  if (failures.length > 1) {
    throw new AggregateError(failures, "M9_PRIVATE_PREPARED_STREAM_MULTIPLE_FAILURES", {
      cause: failures[0],
    });
  }
}

/** Takes one prepared lease, not acquisition authority. No Gateway registration or native auditor. */
export async function runPrivateM9PreparedStream(
  options: PrivateM9PreparedStreamOptions,
): Promise<PrivateM9PreparedStreamResult> {
  const { prepared, source, admission, context, config, completion } = options;
  // Rejected duplicates do not transfer ownership, including a different lease offered to a spent binding.
  if (ownedLeases.has(prepared) || ownedAdmissions.has(admission) || ownedSources.has(source)) {
    throw refuse("ALREADY_OWNED");
  }
  ownedLeases.add(prepared);
  ownedAdmissions.add(admission);
  ownedSources.add(source);
  let custody: CompletionCustody | undefined;
  let result: PrivateM9PreparedStreamResult | undefined;
  let assertBeforeClose: (() => void) | undefined;
  const errors: unknown[] = [];
  try {
    source.signal.throwIfAborted();
    source.assertSourceCurrent();
    assertAdmittedRunOperatorAuthority(source.operatorAuthority);
    if (readAdmittedRunOperatorAuthority(context) !== source.operatorAuthority) {
      throw refuse("SOURCE_IDENTITY");
    }
    const receipt = admission.claim(context); // Irreversible, before the first await or reservation.
    const signal = completion.options?.signal
      ? AbortSignal.any([source.signal, completion.options.signal])
      : source.signal;
    const assertCurrent = () => {
      signal.throwIfAborted();
      receipt.assertCurrent();
      source.assertSourceCurrent();
      signal.throwIfAborted();
    };
    assertCurrent();
    assertBeforeClose = assertCurrent;
    const binding = options.custodyBinding;
    const entry = config.agents?.entries?.[binding.agentId]?.opsysRuntimeAdmission;
    if (
      binding.runId !== context.operationalRunInstance.runId ||
      binding.candidateIndex !== 0 ||
      binding.streamOrdinals.length !== 1 ||
      binding.streamOrdinals[0] !== 0 ||
      !entry ||
      entry.profileId !== binding.profileId ||
      entry.profileRevision !== binding.profileRevision
    ) {
      throw refuse("PLAN_MISMATCH");
    }
    const transport = getModelCompletionTransport(prepared.model);
    if (
      options.route.sourceApi !== "openai-responses" ||
      (transport &&
        (transport.api !== options.route.sourceApi ||
          transport.provider !== options.route.provider ||
          transport.id !== options.route.modelId)) ||
      (completion.context.tools?.length ?? 0) !== 0 ||
      completion.options?.sessionId !== undefined
    ) {
      throw refuse("UNSUPPORTED_ROUTE_OR_CONTEXT");
    }
    custody = createOpsysRuntimeCompletionCustody({ ...binding, streamOrdinals: [0] });
    const ownedCustody = custody;
    result = await withPrivateSingleProviderRequest(
      { assertCurrent, signal, route: options.route },
      async () => {
        return await withPreparedSimpleCompletionStream(
          {
            model: prepared.model,
            auth: prepared.auth,
            cfg: config,
            context: completion.context,
            options: { ...completion.options, signal },
            assertCurrent,
          },
          async (start, model, streamContext, streamOptions) => {
            const failures = new Set<unknown>();
            const scope = new AsyncWorkScope(failures);
            const streamErrors: unknown[] = [];
            let snapshot: PrivateM9PreparedStreamResult | undefined;
            try {
              snapshot = await scope.track(async () => {
                assertCurrent();
                const guarded = createOpsysRuntimeAdmissionStreamFn({
                  config,
                  agentId: binding.agentId,
                  runId: binding.runId,
                  getCandidateIndex: () => 0,
                  signal,
                  streamFn: start,
                  completionCustody: ownedCustody,
                  beforeProviderDispatch: async (dispatchSignal) => {
                    assertCurrent();
                    dispatchSignal.throwIfAborted();
                  },
                });
                const stream = await guarded(model, streamContext, streamOptions);
                assertCurrent();
                const message = await stream.result();
                assertCurrent();
                const batch = consumeOpsysRuntimeCompletionCustody(ownedCustody);
                if (
                  !batch ||
                  batch.length !== 1 ||
                  batch[0].message !== message ||
                  batch[0].receipt.streamOrdinal !== 0
                ) {
                  throw refuse("ORIGINAL_REQUIRED");
                }
                // No callback or suspension between validated original consumption and its payload copy.
                const payloadJSON = JSON.stringify(batch[0].message);
                if (
                  typeof payloadJSON !== "string" ||
                  Buffer.byteLength(payloadJSON, "utf8") > 65_536
                ) {
                  throw refuse("PAYLOAD_BUDGET");
                }
                assertCurrent();
                return Object.freeze({ payloadJSON, receipt: batch[0].receipt });
              });
            } catch (error) {
              streamErrors.push(error);
            }
            try {
              await scope.drain();
            } catch (error) {
              streamErrors.push(error);
            }
            for (const failure of failures) {
              if (!streamErrors.includes(failure)) {
                streamErrors.push(failure);
              }
            }
            throwFailures(streamErrors);
            assertCurrent();
            if (!snapshot) {
              throw refuse("SNAPSHOT_REQUIRED");
            }
            return snapshot;
          },
        );
      },
    );
    assertCurrent();
  } catch (error) {
    errors.push(error);
  } finally {
    try {
      closeOpsysRuntimeCompletionCustody(custody);
    } catch (error) {
      errors.push(error);
    }
    try {
      await prepared[Symbol.asyncDispose]();
    } catch (error) {
      errors.push(error);
    }
    if (result && errors.length === 0) {
      try {
        assertBeforeClose?.();
      } catch (error) {
        errors.push(error);
      }
    }
    try {
      admission.close();
    } catch (error) {
      errors.push(error);
    }
    try {
      source.close();
    } catch (error) {
      errors.push(error);
    }
  }
  throwFailures(errors);
  if (!result) {
    throw refuse("RESULT_REQUIRED");
  }
  return result;
}
