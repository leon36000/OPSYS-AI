/** Private Cron owner operations. No Gateway/RPC serialization of recovered authority. */
import type { SqliteWorkerCommand } from "../../infra/sqlite-worker-contract.js";
import { requestSqliteWorkerOperationAdmission } from "../../infra/sqlite-worker-operation-admission.js";
import { getSqliteWorkerStateContext } from "../../infra/sqlite-worker-state-context.js";
import {
  runOpenClawStateWriteTransaction,
  type OpenClawStateDatabase,
} from "../../state/openclaw-state-db.js";
import {
  acknowledgeCronRetirementProof,
  listPendingCronRetirements,
  readCronRetirementProof,
  type CronRetirementProof,
  type PendingCronRetirements,
} from "./runtime-retirement-store.js";

export type CronRetirementWorkerOperations = {
  "cron.retirementList": {
    input: { storeKey: string; profileId?: string };
    output: PendingCronRetirements;
  };
  "cron.retirementRead": {
    input: { storeKey: string; receiptId: string };
    output: CronRetirementProof | undefined;
  };
  "cron.retirementAcknowledge": {
    input: { storeKey: string; receiptId: string; sourceHash: string; nowMs: number };
    output: void;
  };
};

export function executeCronRetirementCommand(
  command: SqliteWorkerCommand<CronRetirementWorkerOperations>,
  database: OpenClawStateDatabase,
): CronRetirementWorkerOperations[keyof CronRetirementWorkerOperations]["output"] {
  switch (command.type) {
    case "cron.retirementList":
      return listPendingCronRetirements(
        database.db,
        command.input.storeKey,
        command.input.profileId,
      );
    case "cron.retirementRead":
      return readCronRetirementProof(database.db, command.input.storeKey, command.input.receiptId);
    case "cron.retirementAcknowledge":
      return runOpenClawStateWriteTransaction(
        ({ db }) => {
          requestSqliteWorkerOperationAdmission({ stage: "transaction", facts: undefined });
          acknowledgeCronRetirementProof(
            db,
            command.input.storeKey,
            command.input.receiptId,
            command.input.sourceHash,
            command.input.nowMs,
          );
          // The retained host revalidates once after the SQL write, immediately before COMMIT.
          requestSqliteWorkerOperationAdmission({ stage: "commit", facts: undefined });
        },
        { database, path: database.path, env: getSqliteWorkerStateContext().environment },
        { operationLabel: "cron.retirement.acknowledge" },
      );
  }
}
