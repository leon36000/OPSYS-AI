/** Private facade for the reconciler: the worker owns all retirement SQLite reads/writes. */
import { createSqliteWorkerWriteAdmission } from "../../infra/sqlite-worker-store.js";
import { captureOpenClawStateWorkerContext } from "../../state/openclaw-state-worker-context.js";
import { runOpenClawStateWorkerOperation } from "../../state/openclaw-state-worker-store.js";
import { cronStoreKey } from "../store/key.js";
import type {
  CronRetirementProof,
  PendingCronRetirements,
} from "../store/runtime-retirement-store.js";
import { locked } from "./locked.js";
import type { CronServiceState } from "./state.js";

export async function listPending(
  state: CronServiceState,
  commitGuard: () => void,
  profileId?: string,
): Promise<PendingCronRetirements> {
  return await locked(state, async () => {
    commitGuard();
    const storeKey = cronStoreKey(state.deps.storePath);
    const result = await runOpenClawStateWorkerOperation(
      captureOpenClawStateWorkerContext(),
      async (scope) =>
        await scope.execute({ type: "cron.retirementList", input: { storeKey, profileId } }),
      { existingOnly: true, assertCurrent: commitGuard },
    );
    commitGuard();
    return result ?? { total: 0, items: [] };
  });
}

export async function readProof(
  state: CronServiceState,
  receiptId: string,
  commitGuard: () => void,
): Promise<CronRetirementProof | undefined> {
  return await locked(state, async () => {
    commitGuard();
    const storeKey = cronStoreKey(state.deps.storePath);
    const result = await runOpenClawStateWorkerOperation(
      captureOpenClawStateWorkerContext(),
      async (scope) =>
        await scope.execute({ type: "cron.retirementRead", input: { storeKey, receiptId } }),
      { existingOnly: true, assertCurrent: commitGuard },
    );
    commitGuard();
    return result;
  });
}

export async function acknowledge(
  state: CronServiceState,
  receiptId: string,
  sourceHash: string,
  commitGuard: () => void,
): Promise<void> {
  return await locked(state, async () => {
    commitGuard();
    const input = {
      storeKey: cronStoreKey(state.deps.storePath),
      receiptId,
      sourceHash,
      nowMs: state.deps.nowMs(),
    };
    const context = captureOpenClawStateWorkerContext();
    const assertCurrent = () => {
      context.admission.assertCurrent();
      commitGuard();
    };
    await runOpenClawStateWorkerOperation(
      context,
      async (scope) => await scope.execute({ type: "cron.retirementAcknowledge", input }),
      {
        requireStateLifecycle: true,
        assertCurrent,
        createAdmission: createSqliteWorkerWriteAdmission(assertCurrent, [
          context.admission.databasePath,
        ]),
      },
    );
    commitGuard();
  });
}
