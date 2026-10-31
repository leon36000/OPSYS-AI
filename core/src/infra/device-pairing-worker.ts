import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { reserveWorkerEnvironmentNativePublication } from "../gateway/worker-environments/store-native-publication.js";
import { sessionChanges } from "../sessions/session-row-changes.js";
import { resolveGlobalSingleton } from "../shared/global-singleton.js";
import { captureOpenClawStateWorkerContext } from "../state/openclaw-state-worker-context.js";
import { runOpenClawStateWorkerOperation } from "../state/openclaw-state-worker-store.js";
import { invalidatePairedCardRendererCache } from "./device-pairing-card-renderer.js";
import { withDevicePairingLock } from "./device-pairing-lock.js";
import { captureDevicePairingPublication } from "./device-pairing-publication.js";
import type {
  DevicePairingBindingFact,
  DevicePairingCommitReceipt,
  OperatorGrantProjection,
} from "./device-pairing-read.types.js";
import { listDevicePairingStoreRecordsReadOnly } from "./device-pairing-store-readonly.js";
import { assertOperatorGrantProtocol } from "./device-pairing-worker-contract.js";
import type {
  DevicePairingAdmissionFacts,
  DevicePairingWorkerOperations,
} from "./device-pairing-worker-contract.js";
import type { PairedDevice } from "./device-pairing.types.js";
import {
  createSqliteWorkerOperationAdmission,
  type SqliteWorkerOperationAdmission,
} from "./sqlite-worker-operation-admission.js";

export const DevicePairingAuthorityRefusedError = resolveGlobalSingleton(
  Symbol.for("openclaw.devicePairingAuthorityRefusedError"),
  () =>
    class extends Error {
      constructor(message = "Device pairing authority changed") {
        super(message);
      }
    },
);

// The broker owns this private channel; domain kernels supply the discriminated facts.
function isOperatorGrantChange(
  value: unknown,
): value is Extract<DevicePairingAdmissionFacts, { kind: "operator-grant-change-v1" }> {
  return (
    isRecord(value) &&
    value.kind === "operator-grant-change-v1" &&
    Array.isArray(value.deviceIds) &&
    value.deviceIds.every((id) => typeof id === "string" && id.length > 0 && id === id.trim())
  );
}

function admissionFacts(value: unknown): DevicePairingAdmissionFacts[] {
  if (
    !Array.isArray(value) ||
    !value.every(
      (entry) =>
        isRecord(entry) &&
        typeof entry.kind === "string" &&
        (entry.kind !== "operator-grant-change-v1" || isOperatorGrantChange(entry)),
    )
  ) {
    throw new Error("Invalid pairing admission facts");
  }
  // Existing domain facts retain their prior private broker contract; the new v1 fact is validated above.
  return value as DevicePairingAdmissionFacts[];
}

function isVersionedChangedFact(
  value: unknown,
): value is DevicePairingBindingFact & { operatorGrant: OperatorGrantProjection | null } {
  if (!isRecord(value) || typeof value.deviceId !== "string") {
    return false;
  }
  const grant = value.operatorGrant;
  if (
    grant !== null &&
    (!isRecord(grant) ||
      typeof grant.tokenHash !== "string" ||
      !/^[0-9a-f]{64}$/.test(grant.tokenHash) ||
      typeof grant.securityHash !== "string" ||
      !/^[0-9a-f]{64}$/.test(grant.securityHash))
  ) {
    return false;
  }
  const binding = value.binding;
  return (
    binding === null ||
    (isRecord(binding) &&
      typeof binding.identity === "string" &&
      (binding.generation === undefined || typeof binding.generation === "string"))
  );
}

function commitReceipt(value: unknown): DevicePairingCommitReceipt {
  if (
    !isRecord(value) ||
    value.kind !== "devicePairing" ||
    value.operatorGrantVersion !== 1 ||
    typeof value.beforeRevision !== "string" ||
    typeof value.revision !== "string" ||
    !Array.isArray(value.changed) ||
    !value.changed.every(isVersionedChangedFact)
  ) {
    throw new Error("Invalid pairing commit receipt");
  }
  let tokensReplaced: DevicePairingCommitReceipt["tokensReplaced"];
  if (value.tokensReplaced !== undefined) {
    const replaced = value.tokensReplaced;
    if (
      !isRecord(replaced) ||
      typeof replaced.deviceId !== "string" ||
      !Array.isArray(replaced.roles) ||
      !replaced.roles.every((role) => typeof role === "string")
    ) {
      throw new Error("Invalid pairing token replacement receipt");
    }
    tokensReplaced = { deviceId: replaced.deviceId, roles: replaced.roles };
  }
  let workerEnvironment: DevicePairingCommitReceipt["workerEnvironment"];
  if (value.workerEnvironment !== undefined) {
    const environment = value.workerEnvironment;
    if (
      !isRecord(environment) ||
      typeof environment.environmentId !== "string" ||
      typeof environment.nodeDeviceId !== "string" ||
      typeof environment.updatedAtMs !== "number"
    ) {
      throw new Error("Invalid pairing worker-environment receipt");
    }
    workerEnvironment = {
      environmentId: environment.environmentId,
      nodeDeviceId: environment.nodeDeviceId,
      updatedAtMs: environment.updatedAtMs,
    };
  }
  return {
    kind: "devicePairing",
    operatorGrantVersion: 1,
    beforeRevision: value.beforeRevision,
    revision: value.revision,
    ...(tokensReplaced ? { tokensReplaced } : {}),
    ...(workerEnvironment ? { workerEnvironment } : {}),
    changed: value.changed.map((entry) => ({
      deviceId: entry.deviceId,
      operatorGrant: entry.operatorGrant === null ? null : { ...entry.operatorGrant },
      binding:
        entry.binding === null
          ? null
          : {
              identity: entry.binding.identity,
              ...(entry.binding.generation === undefined
                ? {}
                : { generation: entry.binding.generation }),
            },
    })),
  };
}

export function executeDevicePairingMutation<Key extends keyof DevicePairingWorkerOperations>(
  command: { type: Key; input: DevicePairingWorkerOperations[Key]["input"] },
  options: {
    baseDir?: string;
    assertCurrent?: () => void;
    admit?: (facts: DevicePairingAdmissionFacts) => void;
    onTokensReplaced?: (deviceId: string, roles: readonly string[]) => void;
  } = {},
): Promise<DevicePairingWorkerOperations[Key]["output"]> {
  const context = captureOpenClawStateWorkerContext(
    options.baseDir ? { env: { ...process.env, OPENCLAW_STATE_DIR: options.baseDir } } : {},
  );
  const captured = structuredClone(command);
  return withDevicePairingLock(async () => {
    context.admission.assertCurrent();
    options.assertCurrent?.();
    const publication = captureDevicePairingPublication(context.admission);
    const mutation = publication.beginMutation();
    // Reserve known sensitive targets even if a legacy worker omits the v1 fact.
    // Pure verification/last-use and unrelated node-token writes never stage an operator key.
    const requested: { type: string; input: unknown } = captured;
    if (isRecord(requested.input) && typeof requested.input.deviceId === "string") {
      const id = requested.input.deviceId.trim();
      const role =
        typeof requested.input.role === "string" ? requested.input.role.trim() : undefined;
      const sensitiveToken =
        [
          "devicePairing.rotateToken",
          "devicePairing.revokeToken",
          "devicePairing.ensureToken",
        ].includes(requested.type) && role === "operator";
      const sensitiveRemoval =
        requested.type === "devicePairing.remove" ||
        (requested.type === "devicePairing.removeRole" && role === "operator");
      const sensitiveMetadata =
        requested.type === "devicePairing.updateMetadata" &&
        isRecord(requested.input.patch) &&
        ("clientId" in requested.input.patch || "clientMode" in requested.input.patch);
      if (id && (sensitiveToken || sensitiveRemoval || sensitiveMetadata)) {
        mutation.stageOperatorChanges([id]);
      }
    }
    let admission: SqliteWorkerOperationAdmission | undefined;
    let published = false;
    let publishEnvironment: ReturnType<typeof reserveWorkerEnvironmentNativePublication>;
    const install = () => {
      const committed = admission?.committed;
      if (committed && !published) {
        let receipt: DevicePairingCommitReceipt;
        try {
          receipt = commitReceipt(committed.facts);
        } catch (error) {
          mutation.failOperatorFacts();
          throw error;
        }
        const environment = receipt.workerEnvironment;
        let environmentPublished = false;
        if (environment && publishEnvironment) {
          context.admission.assertCurrent();
          environmentPublished = publishEnvironment(environment.environmentId, {
            nodeDeviceId: environment.nodeDeviceId,
            updatedAtMs: environment.updatedAtMs,
          });
        }
        mutation.publish(receipt);
        invalidatePairedCardRendererCache();
        // A callback can throw or read publication recursively; the commit is already installed.
        published = true;
        if (environmentPublished) {
          sessionChanges.emit({ all: true, scope: "worker-environments" });
        }
        if (receipt.tokensReplaced) {
          options.onTokensReplaced?.(receipt.tokensReplaced.deviceId, receipt.tokensReplaced.roles);
        }
      }
    };
    const removeService = publication.servicePending(install);
    try {
      return await runOpenClawStateWorkerOperation(
        context,
        async (scope) => {
          try {
            return await scope.execute(captured);
          } finally {
            install();
          }
        },
        {
          assertCurrent: options.assertCurrent,
          createAdmission: () => {
            let committed = false;
            let operatorProtocolNegotiated = false;
            admission = createSqliteWorkerOperationAdmission((request, grant) => {
              if (committed || (request.stage !== "transaction" && request.stage !== "commit")) {
                throw new Error("Pairing admission requested out of order");
              }
              context.admission.assertCurrent();
              options.assertCurrent?.();
              const firstProtocolRequest = !operatorProtocolNegotiated;
              operatorProtocolNegotiated = assertOperatorGrantProtocol(
                request.stage,
                request.facts,
                operatorProtocolNegotiated,
              );
              for (const facts of admissionFacts(request.facts)) {
                if (firstProtocolRequest && facts.kind === "operator-grant-protocol-v1") {
                  continue;
                }
                if (facts.kind === "operator-grant-change-v1") {
                  if (!isOperatorGrantChange(facts)) {
                    throw new Error("Invalid operator grant change facts");
                  }
                  mutation.stageOperatorChanges(facts.deviceIds);
                } else {
                  if (facts.kind === "pairing-approval" && facts.pending.deviceId) {
                    mutation.stageOperatorChanges([facts.pending.deviceId]);
                  }
                  if (facts.kind === "pairing-prune") {
                    mutation.stageOperatorChanges(facts.deviceIds);
                  }
                  options.admit?.(facts);
                }
              }
              if (request.stage === "commit" && captured.type === "bootstrap.consume") {
                publishEnvironment = reserveWorkerEnvironmentNativePublication(
                  context.admission.identity,
                );
              }
              if (!grant()) {
                throw new DevicePairingAuthorityRefusedError();
              }
              committed = request.stage === "commit";
            });
            return { admission, nativeLocations: [context.admission.databasePath] };
          },
        },
      );
    } finally {
      try {
        install();
      } finally {
        mutation.finish(!admission || admission.settlement?.kind === "completed");
        removeService();
      }
    }
  });
}

/** Start the privileged effect in the same interval that publishes its pairing facts. */
export async function withCurrentDevicePairingSnapshot<T>(
  baseDir: string | undefined,
  prepare: (paired: readonly PairedDevice[]) => { start: () => T | Promise<T> } | undefined,
): Promise<T | undefined> {
  const begun = await withDevicePairingLock(async () => {
    const { paired } = await listDevicePairingStoreRecordsReadOnly(baseDir, true);
    const action = prepare(paired);
    return { value: action?.start() };
  });
  return begun.value;
}
