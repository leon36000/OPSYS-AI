import { deferSqlitePostCommitPublication } from "../../infra/sqlite-post-commit.js";
import {
  deferSqliteWorkerCommitReceipt,
  requestSqliteWorkerOperationAdmission,
} from "../../infra/sqlite-worker-operation-admission.js";
import { getSqliteWorkerStateContext } from "../../infra/sqlite-worker-state-context.js";
import type { OpenClawStateDatabase } from "../../state/openclaw-state-db-contract.js";
import { runOpenClawStateWriteTransaction } from "../../state/openclaw-state-db.js";
import type { CronStoreFile } from "../types.js";
import { recordCronRetirementBeforeDelete } from "./runtime-retirement-store.js";
import { serializeCronSaveError } from "./save-error.js";
import type { CronStoreSaveWorkerOperations } from "./save-worker.types.js";
import { saveCronStoreChangesInDatabase, saveCronStoreInDatabase } from "./save.kernel.js";
import type { CronStoreTransactionHooks } from "./transaction-hooks.types.js";

type SaveCommand = {
  [Key in keyof CronStoreSaveWorkerOperations]: {
    type: Key;
    input: CronStoreSaveWorkerOperations[Key]["input"];
  };
}[keyof CronStoreSaveWorkerOperations];

export function executeCronStoreSaveCommand(command: SaveCommand, database: OpenClawStateDatabase) {
  let committed = false;
  try {
    const result = runOpenClawStateWriteTransaction(
      ({ db }) => {
        let value: CronStoreFile | undefined;
        if (command.type === "cron.saveChanges") {
          const retirement = command.input.retirement;
          let transactionHooks: CronStoreTransactionHooks | undefined;
          if (retirement) {
            requestSqliteWorkerOperationAdmission({ stage: "transaction", facts: undefined });
            const before = command.input.changes.previousById.get(retirement.jobId);
            if (
              !before ||
              !command.input.changes.changedIds.has(retirement.jobId) ||
              command.input.changes.nextById.has(retirement.jobId)
            ) {
              throw new Error("Cron retirement mutation differs from its captured DELETE.");
            }
            // This hook and every SQLite access are constructed on the owning worker.
            transactionHooks = {
              beforeWrite: (db) => {
                recordCronRetirementBeforeDelete(
                  db,
                  command.input.storeKey,
                  before,
                  retirement.capture,
                  retirement.removedAtMs,
                );
                return undefined;
              },
              afterWrite: (db) => {
                deferSqliteWorkerCommitReceipt(db, {
                  kind: "cron.retirement",
                  nonce: retirement.nonce,
                  receiptId: retirement.capture.receiptId,
                  jobId: retirement.jobId,
                });
                requestSqliteWorkerOperationAdmission({ stage: "commit", facts: undefined });
                return undefined;
              },
            };
          }
          value = saveCronStoreChangesInDatabase(
            db,
            command.input.storeKey,
            command.input.storeKey,
            command.input.changes,
            command.input.options,
            transactionHooks,
          );
        } else {
          saveCronStoreInDatabase(
            database,
            command.input.storeKey,
            command.input.store,
            command.input.options,
          );
        }
        deferSqlitePostCommitPublication(db, () => {
          committed = true;
        });
        return value;
      },
      { database, env: getSqliteWorkerStateContext().environment },
      command.type === "cron.saveChanges" ? { operationLabel: "cron.config-mutation" } : undefined,
    );
    return { ok: true as const, value: result, committed };
  } catch (error) {
    return {
      ok: false as const,
      error: serializeCronSaveError(error, command.input.storeKey),
      committed,
    };
  }
}
