import type {
  DeviceBootstrapMutationAdmission,
  DeviceBootstrapOperations,
} from "./device-bootstrap.worker-types.js";
import type {
  DevicePairingCoreAdmissionFacts,
  DevicePairingCoreWorkerOperations,
} from "./device-pairing-core.worker-contract.js";
import type {
  DevicePairingNodeAdmissionFacts,
  DevicePairingNodeWorkerOperations,
} from "./device-pairing-node.worker-contract.js";
import type { SqliteWorkerCommand } from "./sqlite-worker-contract.js";

export type DevicePairingWorkerOperations = DevicePairingCoreWorkerOperations &
  DevicePairingNodeWorkerOperations &
  DeviceBootstrapOperations;
export type DevicePairingMutationCommand = SqliteWorkerCommand<DevicePairingWorkerOperations>;
export type DevicePairingAdmissionFacts =
  | { kind: "operator-grant-protocol-v1" }
  | { kind: "operator-grant-change-v1"; deviceIds: readonly string[] }
  | DevicePairingCoreAdmissionFacts
  | DevicePairingNodeAdmissionFacts
  | DeviceBootstrapMutationAdmission;

export function isDevicePairingMutationCommand(command: {
  type: string;
}): command is DevicePairingMutationCommand {
  return (
    command.type.startsWith("devicePairing.") ||
    command.type.startsWith("node.") ||
    command.type.startsWith("bootstrap.")
  );
}

/** Per-operation protocol negotiation; call before granting the first native admission. */
export function assertOperatorGrantProtocol(
  stage: "open" | "prepare" | "transaction" | "commit",
  facts: unknown,
  negotiated: boolean,
): boolean {
  if (!Array.isArray(facts)) {
    throw new Error("Invalid pairing admission facts");
  }
  const hasMarker = (fact: unknown) =>
    typeof fact === "object" &&
    fact !== null &&
    "kind" in fact &&
    fact.kind === "operator-grant-protocol-v1";
  const isMarker = (fact: unknown) =>
    hasMarker(fact) && !Array.isArray(fact) && Object.keys(fact as object).length === 1;
  if (!negotiated) {
    if (stage !== "transaction" || facts.length !== 1 || !isMarker(facts[0])) {
      throw new Error("Pairing worker operator grant protocol v1 required before commit");
    }
    return true;
  }
  if (stage !== "transaction" && stage !== "commit") {
    throw new Error("Unexpected pairing admission stage");
  }
  if (facts.some(hasMarker)) {
    throw new Error("Pairing worker protocol marker repeated");
  }
  return true;
}
