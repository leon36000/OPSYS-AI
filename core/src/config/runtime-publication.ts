import { isDeepStrictEqual } from "node:util";
import { sha256Base64Url } from "../infra/crypto-digest.js";
import { isDeeplyFrozenPlainData } from "../shared/immutable-data.js";
import { getConfigResolutionFacts, serializeConfigResolutionFacts } from "./resolution-facts.js";
import type { OpenClawConfig } from "./types.openclaw.js";

const publicationBrand: unique symbol = Symbol("runtime-config-publication");
export type RuntimeConfigPublicationReceipt = Readonly<{ [publicationBrand]: true }>;
export type RuntimePublicationMetadata = {
  revision: number;
  fingerprint: string;
  sourceFingerprint: string | null;
  updatedAtMs: number;
};
export type RuntimePublicationState = Readonly<{
  config: OpenClawConfig | null;
  sourceConfig: OpenClawConfig | null;
  metadata: RuntimePublicationMetadata | null;
  generation: number;
}>;
type PublicationRecord = RuntimePublicationState & {
  metadataValues: RuntimePublicationMetadata;
  fingerprint: string;
  sourceFingerprint: string | null;
  sourceOnlyOrigin: RuntimeConfigPublicationReceipt | null;
  revoked: boolean;
};

/** A private owner uses one instance; other instances confer no canonical authority. */
export function createRuntimePublicationTracker(
  readCurrent: () => RuntimePublicationState,
  fingerprint: (config: OpenClawConfig) => string,
) {
  const records = new WeakMap<object, PublicationRecord>();
  let currentReceipt: RuntimeConfigPublicationReceipt | null = null;

  const isCurrent = (receipt: unknown): boolean => {
    if (receipt === null || typeof receipt !== "object") {
      return false;
    }
    const record = records.get(receipt);
    if (!record || record.revoked || !record.config) {
      return false;
    }
    const owns = () => {
      const state = readCurrent();
      return (
        receipt === currentReceipt &&
        record.generation === state.generation &&
        record.config === state.config &&
        record.sourceConfig === state.sourceConfig &&
        record.metadata === state.metadata
      );
    };
    try {
      if (
        owns() &&
        isDeepStrictEqual(record.metadata, record.metadataValues) &&
        record.fingerprint === fingerprint(record.config) &&
        record.sourceFingerprint ===
          (record.sourceConfig ? fingerprint(record.sourceConfig) : null) &&
        owns()
      ) {
        return true;
      }
    } catch {
      // Observed invalid publication contents cannot be restored by a later read.
    }
    record.revoked = true;
    return false;
  };

  return Object.freeze({
    publish(predecessor: RuntimeConfigPublicationReceipt | null = null) {
      const state = readCurrent();
      if (!state.config || !state.metadata) {
        throw new Error("RUNTIME-PUBLICATION-UNAVAILABLE");
      }
      const previous = predecessor ? records.get(predecessor) : undefined;
      const sourceOnlyOrigin =
        previous &&
        !previous.revoked &&
        predecessor === currentReceipt &&
        previous.config === state.config &&
        previous.generation + 1 === state.generation
          ? (previous.sourceOnlyOrigin ?? predecessor)
          : null;
      const receipt: RuntimeConfigPublicationReceipt = Object.freeze({ [publicationBrand]: true });
      records.set(receipt, {
        ...state,
        metadataValues: { ...state.metadata },
        fingerprint: fingerprint(state.config),
        sourceFingerprint: state.sourceConfig ? fingerprint(state.sourceConfig) : null,
        sourceOnlyOrigin,
        revoked: false,
      });
      currentReceipt = receipt;
      return receipt;
    },
    reset() {
      currentReceipt = null;
    },
    readReceipt(config: OpenClawConfig) {
      return config === readCurrent().config && isCurrent(currentReceipt) ? currentReceipt : null;
    },
    isCurrent,
    readConfig(receipt: unknown) {
      return isCurrent(receipt) && receipt !== null && typeof receipt === "object"
        ? (records.get(receipt)?.config ?? null)
        : null;
    },
    readSourceOnlyOrigin(receipt: unknown) {
      return receipt !== null && typeof receipt === "object"
        ? (records.get(receipt)?.sourceOnlyOrigin ?? null)
        : null;
    },
  });
}

export function stableConfigStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableConfigStringify(entry)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).toSorted();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${stableConfigStringify(record[key])}`)
    .join(",")}}`;
}

// Diagnostic callers stop at their raw revision; this owner accepts config objects.
// Only immutable identities share hashes across reads.
const immutableConfigHashes = new WeakMap<OpenClawConfig, string>();

export function hashRuntimeConfigValue(value: OpenClawConfig): string {
  const immutable = isDeeplyFrozenPlainData(value);
  const cached = immutable ? immutableConfigHashes.get(value) : undefined;
  if (cached !== undefined) {
    return cached;
  }
  const fingerprint = sha256Base64Url(stableConfigStringify(value));
  if (immutable) {
    immutableConfigHashes.set(value, fingerprint);
  }
  return fingerprint;
}

/** The native publisher owns revision advancement; this helper only calculates its metadata. */
export function createRuntimePublicationMetadata(
  config: OpenClawConfig,
  sourceConfig: OpenClawConfig | undefined,
  revision: number,
): RuntimePublicationMetadata {
  return {
    revision,
    fingerprint: hashRuntimeConfigValue(config),
    sourceFingerprint: sourceConfig ? hashRuntimeConfigValue(sourceConfig) : null,
    updatedAtMs: Date.now(),
  };
}

export function configSnapshotsMatch(left: OpenClawConfig, right: OpenClawConfig): boolean {
  if (left === right) {
    return true;
  }
  // Fresh reads allocate new facts. Compare their complete provenance, not object identity
  // or just JSON config bytes: same-byte values can name different authored SecretRefs.
  if (
    getConfigResolutionFacts(left) !== getConfigResolutionFacts(right) &&
    !isDeepStrictEqual(serializeConfigResolutionFacts(left), serializeConfigResolutionFacts(right))
  ) {
    return false;
  }
  try {
    return stableConfigStringify(left) === stableConfigStringify(right);
  } catch {
    return false;
  }
}
