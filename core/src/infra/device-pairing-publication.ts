import { createHash } from "node:crypto";
import { resolveGlobalSingleton } from "../shared/global-singleton.js";
import type { OpenClawStateDatabaseReadAdmission } from "../state/openclaw-state-db-async-lifecycle.js";
import {
  registerOpenClawStateDatabaseAsyncResource,
  registerOpenClawStateDatabaseLifecycleListener,
} from "../state/openclaw-state-db-cache.js";
import { resolveOpenClawStateSqlitePath } from "../state/openclaw-state-db.paths.js";
import type {
  DevicePairingBinding,
  DevicePairingBindingFact,
  DevicePairingCommitReceipt,
  OperatorGrantProjection,
} from "./device-pairing-read.types.js";

type Publication = {
  identity: string;
  canonicalPath: string;
  epoch: number;
  revision?: string;
  blocked: boolean;
  mutation?: object;
  complete: boolean;
  rows: Map<string, DevicePairingBinding | null>;
  pending: Set<() => void>;
  operatorRows: Map<string, OperatorGrantProjection>;
  operatorPending: Map<string, object>;
  operatorUnknown: boolean;
};

const publications = resolveGlobalSingleton(
  Symbol.for("openclaw.devicePairingPublications"),
  () => {
    const state = new Map<string, Publication>();
    registerOpenClawStateDatabaseAsyncResource({
      phase: "after-resources",
      async close(identity) {
        for (const [path, publication] of state) {
          if (
            !identity ||
            publication.identity === identity.key ||
            publication.canonicalPath === identity.canonicalPath
          ) {
            state.delete(path);
          }
        }
      },
    });
    registerOpenClawStateDatabaseLifecycleListener((event) => {
      if (event.kind === "opened") {
        return;
      }
      for (const [path, publication] of state) {
        if (path === event.path || publication.identity === event.identity?.key) {
          state.delete(path);
        }
      }
    });
    return state;
  },
);

export function captureDevicePairingPublication(admission: OpenClawStateDatabaseReadAdmission) {
  const path = admission.databasePath;
  const { identity } = admission;
  let publication = publications.get(identity.key) ?? publications.get(identity.canonicalPath);
  if (publication && publication.identity !== identity.key) {
    for (const [alias, current] of publications) {
      if (current === publication) {
        publications.delete(alias);
      }
    }
    publication = undefined;
  }
  if (!publication) {
    publication = {
      identity: identity.key,
      canonicalPath: identity.canonicalPath,
      epoch: 0,
      blocked: false,
      complete: false,
      rows: new Map(),
      pending: new Set(),
      operatorRows: new Map(),
      operatorPending: new Map(),
      operatorUnknown: false,
    };
  }
  publications.set(path, publication);
  publications.set(identity.canonicalPath, publication);
  publications.set(identity.key, publication);
  const captured = publication;
  const epoch = captured.epoch;
  const install = (rows: readonly DevicePairingBindingFact[]) => {
    for (const row of rows) {
      captured.rows.set(row.deviceId, row.binding ? { ...row.binding } : null);
      const prior = captured.operatorRows.get(row.deviceId);
      const next = row.operatorGrant;
      if (!next) {
        captured.operatorRows.delete(row.deviceId);
      } else if (
        !prior ||
        prior.tokenHash !== next.tokenHash ||
        prior.securityHash !== next.securityHash
      ) {
        captured.operatorRows.set(row.deviceId, { ...next });
      }
    }
  };
  return {
    isCurrent: () =>
      publications.get(path) === captured && captured.epoch === epoch && !captured.mutation,
    completeRevision: () =>
      !captured.blocked && captured.complete ? captured.revision : undefined,
    fail() {
      if (publications.get(path) === captured && captured.epoch === epoch) {
        captured.blocked = true;
      }
    },
    publish(
      revision: string,
      rows: readonly DevicePairingBindingFact[] | undefined,
      complete = false,
    ) {
      if (publications.get(path) !== captured || captured.epoch !== epoch || captured.mutation) {
        return false;
      }
      if (!rows) {
        if (captured.revision !== revision || !captured.complete) {
          throw new Error("Pairing publication cannot reuse an unknown revision");
        }
        captured.blocked = false;
        return true;
      }
      if (captured.revision !== revision) {
        captured.epoch++;
      }
      if (complete || captured.revision !== revision) {
        captured.rows.clear();
        captured.complete = false;
        if (!complete) {
          captured.operatorRows.clear();
        }
      }
      if (complete) {
        const ids = new Set(rows.map((row) => row.deviceId));
        for (const id of captured.operatorRows.keys()) {
          if (!ids.has(id)) {
            captured.operatorRows.delete(id);
          }
        }
        captured.operatorUnknown = rows.some((row) => row.operatorGrant === undefined);
      }
      captured.revision = revision;
      install(rows);
      captured.complete ||= complete;
      captured.blocked = false;
      return true;
    },
    beginMutation() {
      captured.epoch++;
      captured.blocked = true;
      const mutation = {};
      captured.mutation = mutation;
      const operatorKeys = new Set<string>();
      return {
        failOperatorFacts() {
          captured.operatorUnknown = true;
          captured.operatorRows.clear();
        },
        stageOperatorChanges(deviceIds: readonly string[]) {
          for (const id of deviceIds) {
            const current = captured.operatorPending.get(id);
            if (current && current !== mutation) {
              throw new Error("Operator grant mutation already pending");
            }
            captured.operatorPending.set(id, mutation);
            operatorKeys.add(id);
          }
        },
        publish(receipt: DevicePairingCommitReceipt) {
          if (publications.get(path) !== captured || captured.mutation !== mutation) {
            return;
          }
          if (receipt.beforeRevision !== captured.revision) {
            captured.complete = false;
            captured.rows.clear();
            captured.operatorRows.clear();
            captured.operatorUnknown = true;
          }
          if (
            receipt.operatorGrantVersion !== 1 ||
            receipt.changed.some((row) => row.operatorGrant === undefined)
          ) {
            // Legacy/unknown operator facts are not authoritative; node facts remain independent.
            captured.operatorRows.clear();
            captured.operatorUnknown = true;
            for (const row of receipt.changed) {
              captured.rows.set(row.deviceId, row.binding ? { ...row.binding } : null);
            }
          } else {
            install(receipt.changed);
          }
          for (const id of operatorKeys) {
            if (captured.operatorPending.get(id) === mutation) {
              captured.operatorPending.delete(id);
            }
          }
          captured.revision = receipt.revision;
          captured.blocked = false;
          captured.mutation = undefined;
          // A reader admitted during this transaction cannot republish its older snapshot.
          captured.epoch++;
        },
        finish(settled: boolean) {
          if (settled && captured.mutation === mutation) {
            for (const id of operatorKeys) {
              if (captured.operatorPending.get(id) === mutation) {
                captured.operatorPending.delete(id);
              }
            }
            captured.mutation = undefined;
            captured.epoch++;
          }
        },
      };
    },
    servicePending(service: () => void) {
      captured.pending.add(service);
      return () => captured.pending.delete(service);
    },
  };
}

/** Unknown facts suppress use without declaring an otherwise live node revoked. */
export function getPublishedPairedDeviceBinding(
  deviceId: string,
  baseDir?: string,
): DevicePairingBinding | null {
  const path = resolveOpenClawStateSqlitePath(
    baseDir ? { ...process.env, OPENCLAW_STATE_DIR: baseDir } : process.env,
  );
  const publication = publications.get(path);
  for (const service of publication?.pending ?? []) {
    service();
  }
  if (
    !publication ||
    publication.blocked ||
    (!publication.complete && !publication.rows.has(deviceId))
  ) {
    throw new Error("Device pairing authority requires a current worker publication");
  }
  const binding = publication.rows.get(deviceId);
  return binding ? { ...binding } : null;
}

/** Capture the exact verified operator grant; unknown or pending facts refuse synchronously. */
export function capturePublishedOperatorGrant(
  deviceId: string,
  token: string,
  expected: OperatorGrantProjection | null,
  baseDir?: string,
): () => boolean {
  const path = resolveOpenClawStateSqlitePath(
    baseDir ? { ...process.env, OPENCLAW_STATE_DIR: baseDir } : process.env,
  );
  const state = publications.get(path);
  for (const service of state?.pending ?? []) {
    service();
  }
  const tokenHash = createHash("sha256").update(token).digest("hex");
  const captured = state?.operatorRows.get(deviceId);
  if (
    !state ||
    state.operatorUnknown ||
    state.operatorPending.has(deviceId) ||
    !captured ||
    !expected ||
    expected.tokenHash !== tokenHash ||
    captured.tokenHash !== tokenHash ||
    captured.securityHash !== expected.securityHash
  ) {
    return () => false;
  }
  return () => {
    for (const service of state.pending) {
      service();
    }
    return (
      publications.get(path) === state &&
      !state.operatorUnknown &&
      !state.operatorPending.has(deviceId) &&
      state.operatorRows.get(deviceId) === captured
    );
  };
}
