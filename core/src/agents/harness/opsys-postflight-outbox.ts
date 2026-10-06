import { cloneEnvWithPlatformSemantics } from "../../config/config-env-vars.js";
import { resolveStateDir } from "../../config/state-dir.js";
import { runtimeProcessEntrypoints } from "../../infra/runtime-process-entrypoints.js";
import { resolveRuntimeWorkerUrl } from "../../infra/runtime-worker-url.js";
import type {
  OpenClawAgentDatabase,
  OpenClawAgentDatabaseOptions,
} from "../../state/openclaw-agent-db-contract.js";
import { resolveOpenClawAgentSqlitePath } from "../../state/openclaw-agent-db.paths.js";
import { captureOpenClawAgentDatabaseExecution } from "../../state/openclaw-agent-execution.js";
import { openOpenClawAgentSqliteWorkerStore } from "../../state/openclaw-agent-worker-store.js";
import { runOpenClawAgentWriteAdmission } from "../../state/openclaw-agent-write-admission.js";
import {
  deriveOpsysPostflightFactKey,
  type OpsysPostflightIntent,
  type OpsysPostflightIntentInput,
  type OpsysPostflightFact,
  type OpsysPostflightLot,
  type OpsysPostflightLotInput,
  type OpsysPostflightOutboxOperations,
} from "./opsys-postflight-outbox.worker.js";

export { deriveOpsysPostflightFactKey };
export type {
  OpsysPostflightFact,
  OpsysPostflightLot,
  OpsysPostflightLotInput,
  OpsysPostflightIntent,
  OpsysPostflightIntentInput,
};

async function execute<T extends keyof OpsysPostflightOutboxOperations>(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  command: { type: T; input: OpsysPostflightOutboxOperations[T]["input"] };
  assertCurrent?: () => void;
}): Promise<OpsysPostflightOutboxOperations[T]["output"]> {
  const { database, options } = params;
  const env = cloneEnvWithPlatformSemantics(options.env ?? process.env);
  env.OPENCLAW_STATE_DIR = resolveStateDir(env);
  const effectiveOptions = {
    ...options,
    env,
    path: resolveOpenClawAgentSqlitePath({ ...options, env }),
  };
  if (database.agentId !== options.agentId || database.path !== effectiveOptions.path) {
    throw new Error("POSTFLIGHT_DATABASE_OWNER_MISMATCH");
  }
  const execution = captureOpenClawAgentDatabaseExecution(effectiveOptions);
  const assertCurrent = () => {
    execution.assertCurrent();
    params.assertCurrent?.();
  };
  try {
    return await runOpenClawAgentWriteAdmission<OpsysPostflightOutboxOperations[T]["output"]>(
      effectiveOptions,
      async () => {
        assertCurrent();
        const worker = await openOpenClawAgentSqliteWorkerStore<OpsysPostflightOutboxOperations>(
          effectiveOptions,
          database.db,
          {
            moduleUrl: resolveRuntimeWorkerUrl(runtimeProcessEntrypoints.opsysPostflightOutbox),
            input: undefined,
          },
        );
        try {
          return await worker.run((scope) => scope.execute(params.command), assertCurrent);
        } finally {
          await worker.close();
        }
      },
      true,
    );
  } finally {
    await execution.release();
  }
}

/** Persists a closed envelope only; this does not authenticate its provenance or send it to M10. */
export function enqueueOpsysPostflightLots(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  lots: readonly OpsysPostflightLotInput[];
  now: number;
  assertCurrent?: () => void;
}): Promise<Array<{ lot: OpsysPostflightLot; created: boolean }>> {
  return execute({
    ...params,
    command: { type: "enqueue", input: { lots: params.lots, now: params.now } },
  });
}

export function listOpsysPostflightLots(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightLot[]> {
  return execute({ ...params, command: { type: "list", input: { now: params.now } } });
}

export function listDueOpsysPostflightLots(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightLot[]> {
  return execute({ ...params, command: { type: "listDue", input: { now: params.now } } });
}

export function beginOpsysPostflightAttempt(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  lotKey: string;
  expected: OpsysPostflightLotInput;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightLot | undefined> {
  return execute({
    ...params,
    command: {
      type: "beginAttempt",
      input: { lotKey: params.lotKey, expected: params.expected, now: params.now },
    },
  });
}

/** Deletes only an exact acknowledged correspondence; a mismatch retains the durable lot. */
export function acknowledgeOpsysPostflightLot(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  lotKey: string;
  expected: OpsysPostflightLotInput;
  now: number;
  assertCurrent?: () => void;
}): Promise<boolean> {
  return execute({
    ...params,
    command: {
      type: "acknowledge",
      input: { lotKey: params.lotKey, expected: params.expected, now: params.now },
    },
  });
}

export function failOpsysPostflightAttempt(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  lotKey: string;
  expected: OpsysPostflightLotInput;
  code: string;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightLot> {
  return execute({
    ...params,
    command: {
      type: "recordFailure",
      input: {
        lotKey: params.lotKey,
        expected: params.expected,
        code: params.code,
        now: params.now,
      },
    },
  });
}

/** Reserve durable uncertainty and future capacity before the source RPC; no source replay. */
export function reserveOpsysPostflightIntent(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  intent: OpsysPostflightIntentInput;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightIntent> {
  return execute({
    ...params,
    command: { type: "reserveIntent", input: { intent: params.intent, now: params.now } },
  });
}

export function listOpsysPostflightIntents(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightIntent[]> {
  return execute({ ...params, command: { type: "listIntents", input: { now: params.now } } });
}

/** Convert only an exact observed outcome under the same canonical transaction. */
export function completeOpsysPostflightIntent(params: {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
  expected: OpsysPostflightIntentInput;
  fact: OpsysPostflightFact;
  now: number;
  assertCurrent?: () => void;
}): Promise<OpsysPostflightLot> {
  return execute({
    ...params,
    command: {
      type: "completeIntent",
      input: { expected: params.expected, fact: params.fact, now: params.now },
    },
  });
}
