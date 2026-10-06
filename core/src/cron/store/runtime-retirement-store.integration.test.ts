import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import * as operationAdmission from "../../infra/sqlite-worker-operation-admission.js";
import { resolveOpenClawStateSqlitePath } from "../../state/openclaw-state-db.paths.js";
import * as stateWorker from "../../state/openclaw-state-worker-store.js";
import { captureEnv, setTestEnvValue } from "../../test-utils/env.js";
import { resolveCronJobConfigRevision } from "../config-revision.js";
import { createCronMutationCompletion } from "../mutation-completion.js";
import { CronService } from "../service.js";
import { createCronStoreHarness } from "../service.test-harness.js";
import type { CronJobCreate } from "../types.js";
import { cronStoreKey } from "./key.js";
import {
  acknowledgeCronRetirementProof,
  readCronRetirementProof,
  listPendingCronRetirementIds,
  type CronRetirementCapture,
} from "./runtime-retirement-store.js";
import * as retirementStore from "./runtime-retirement-store.js";

// Fictif: true. Real CronService/SQLite/AES, no scheduler/provider or Python server.
const PROFILE = "estimation";
const INTENTION = "a".repeat(64);
const CAPABILITY = "42".repeat(32);
const CAP_HASH = createHash("sha256").update(Buffer.from(CAPABILITY, "hex")).digest("hex");
const { makeStorePath } = createCronStoreHarness({ prefix: "cron-retirement-native-" });
const env = captureEnv(["OPENCLAW_CRON_AUTHORITY_KEY_FILE", "OPENCLAW_CRON_AUTHORITY_KEY_ID"]);
let keyDirectory: string;

beforeAll(async () => {
  keyDirectory = await fs.mkdtemp(path.join(os.tmpdir(), "cron-retirement-key-"));
  await fs.chmod(keyDirectory, 0o700);
  const keyPath = path.join(keyDirectory, "authority.key");
  const key = randomBytes(32);
  await fs.writeFile(keyPath, key, { mode: 0o600, flag: "wx" });
  setTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_FILE", keyPath);
  setTestEnvValue(
    "OPENCLAW_CRON_AUTHORITY_KEY_ID",
    `sha256:${createHash("sha256").update(key).digest("hex")}`,
  );
});
afterAll(async () => {
  env.restore();
  if (keyDirectory) {
    await fs.rm(keyDirectory, { recursive: true, force: true });
  }
});

function declaration(): CronJobCreate {
  return {
    name: `OPSYS profil ${PROFILE}`,
    declarationKey: `opsys-profile:${INTENTION}`,
    agentId: `opsys-agent-${PROFILE}`,
    sessionTarget: "isolated",
    wakeMode: "now",
    schedule: { kind: "cron", expr: "0 9 * * *", tz: "UTC" },
    payload: {
      kind: "agentTurn",
      message: `Exécute le mandat interne canonique du profil ${PROFILE}, révision 7.`,
      timeoutSeconds: 120,
      toolsAllow: ["opsys_m3__m3_lire_devis"],
    },
    delivery: { mode: "none" },
  };
}

async function fixture(cronEnabled = false) {
  const { storePath } = await makeStorePath();
  const services: CronService[] = [];
  const create = () => {
    // Every fixture job is disabled: the true flag exercises persistence, never a timer/provider run.
    const service = new CronService({
      storePath,
      cronEnabled,
      nowMs: () => 1_800_000_000_000,
      log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
      enqueueSystemEvent: () => {
        throw new Error("unexpected scheduler");
      },
      requestHeartbeat: () => {
        throw new Error("unexpected scheduler");
      },
      runIsolatedAgentJob: () => Promise.reject(new Error("unexpected provider")),
    });
    services.push(service);
    return service;
  };
  const service = create();
  const wire = declaration();
  const added = await service.add(
    { ...wire, enabled: false },
    {
      commitGuard: () => {},
      captureRuntimeAuthority: () => ({
        version: 1,
        runtimeId: "openclaw",
        namespace: "opsys-cron-authority-v1",
        payload: {
          version: 1,
          profil_id: PROFILE,
          intention_id: INTENTION,
          epoch: 1,
          lease_epoch: 1,
          capabilite: CAPABILITY,
          declaration: wire,
        },
      }),
    },
  );
  const job = await service.readJob(added.id);
  if (!job) {
    throw new Error("expected committed native fixture job");
  }
  const capture: CronRetirementCapture = {
    receiptId: "b".repeat(64),
    sourceHash: "c".repeat(64),
    profileId: PROFILE,
    intentionId: INTENTION,
    epoch: 1,
    capabilityFingerprint: CAP_HASH,
    declarationHash: createHash("sha256").update(stableStringify(wire), "utf8").digest("hex"),
    nativeRevision: resolveCronJobConfigRevision(job),
  };
  return {
    service,
    create,
    job,
    capture,
    partition: cronStoreKey(storePath),
    stop: async () => {
      for (const owner of services) {
        owner.stop();
      }
      await Promise.all(services.map((owner) => owner.stopAndDrain?.() ?? Promise.resolve()));
    },
  };
}

describe("Cron retirement durable encrypted owner", () => {
  it("recovers the capability after DELETE/restart and retains one acknowledged encrypted receipt", async () => {
    const item = await fixture();
    try {
      const removed = await item.service.removeWithPrecondition(
        item.job.id,
        (current) => {
          expect(current.enabled).toBe(false);
          expect(resolveCronJobConfigRevision(current)).toBe(item.capture.nativeRevision);
        },
        { commitGuard: () => {}, retirement: item.capture },
      );
      expect(removed.removed).toBe(true);
      const reopened = item.create();
      expect(await reopened.readJob(item.job.id)).toBeUndefined();
      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        expect(listPendingCronRetirementIds(db, item.partition, PROFILE)).toEqual([
          item.capture.receiptId,
        ]);
        const proof = readCronRetirementProof(db, item.partition, item.capture.receiptId);
        expect(proof?.purpose).toBe("opsys-cron-retirement");
        expect(proof?.authority.payload.capabilite).toBe(CAPABILITY);
        const row = db
          .prepare(
            "SELECT ciphertext FROM cron_job_runtime_retirements WHERE store_key=? AND receipt_id=?",
          )
          .get(item.partition, item.capture.receiptId);
        expect(typeof row?.ciphertext).toBe("string");
        expect(String(row?.ciphertext)).not.toContain(CAPABILITY);
        expect(
          db
            .prepare("SELECT count(*) AS n FROM cron_job_runtime_authorities WHERE job_id=?")
            .get(item.job.id)?.n,
        ).toBe(0);
        // Python ACK is simulated here; the Python HTTP companion checks its authority/receipt.
        db.exec("BEGIN IMMEDIATE");
        acknowledgeCronRetirementProof(
          db,
          item.partition,
          item.capture.receiptId,
          item.capture.sourceHash,
          1_800_000_000_001,
        );
        db.exec("COMMIT");
        expect(listPendingCronRetirementIds(db, item.partition, PROFILE)).toEqual([]);
        expect(
          readCronRetirementProof(db, item.partition, item.capture.receiptId)?.capture,
        ).toEqual(item.capture);
      } finally {
        db.close();
      }
    } finally {
      await item.stop();
    }
  });

  it("acknowledges on the worker with one admission pair and preserves the encrypted receipt on replay", async () => {
    const item = await fixture();
    try {
      await item.service.removeWithPrecondition(item.job.id, () => {}, {
        retirement: item.capture,
        commitGuard: () => {},
      });
      const stages: string[] = [];
      const realAdmission = operationAdmission.createSqliteWorkerOperationAdmission;
      const admissionSpy = vi
        .spyOn(operationAdmission, "createSqliteWorkerOperationAdmission")
        .mockImplementation((admit, attachment) =>
          realAdmission((request, grant) => {
            stages.push(request.stage);
            admit(request, grant);
          }, attachment),
        );
      const mainSql = vi
        .spyOn(retirementStore, "acknowledgeCronRetirementProof")
        .mockImplementation(() => {
          throw new Error("main-thread retirement ACK SQL must not run");
        });
      try {
        await item.service.acknowledgeRetirementProof(
          item.capture.receiptId,
          item.capture.sourceHash,
          () => {},
        );
        await item.service.acknowledgeRetirementProof(
          item.capture.receiptId,
          item.capture.sourceHash,
          () => {},
        );
        expect(stages).toEqual(["transaction", "commit", "transaction", "commit"]);
        expect(mainSql).not.toHaveBeenCalled();
      } finally {
        admissionSpy.mockRestore();
        mainSql.mockRestore();
      }
      expect(await item.service.listPendingRetirements(() => {}, PROFILE)).toEqual({
        total: 0,
        items: [],
      });
      expect(
        (await item.service.readRetirementProof(item.capture.receiptId, () => {}))?.capture,
      ).toEqual(item.capture);
      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        const row = db
          .prepare(
            "SELECT count(*) AS n, min(acknowledged_at_ms) AS ack " +
              "FROM cron_job_runtime_retirements WHERE store_key=? AND receipt_id=?",
          )
          .get(item.partition, item.capture.receiptId);
        expect(row).toMatchObject({ n: 1, ack: 1_800_000_000_000 });
      } finally {
        db.close();
      }
    } finally {
      await item.stop();
    }
  });

  it.each(["transaction", "commit"])(
    "rolls back terminal ACK when the operator is withdrawn at %s admission",
    async (refusalStage) => {
      const item = await fixture();
      try {
        await item.service.removeWithPrecondition(item.job.id, () => {}, {
          retirement: item.capture,
          commitGuard: () => {},
        });
        const stages: string[] = [];
        let live = true;
        const realAdmission = operationAdmission.createSqliteWorkerOperationAdmission;
        const admissionSpy = vi
          .spyOn(operationAdmission, "createSqliteWorkerOperationAdmission")
          .mockImplementation((admit, attachment) =>
            realAdmission((request, grant) => {
              stages.push(request.stage);
              if (request.stage === refusalStage) {
                live = false;
              }
              admit(request, grant);
            }, attachment),
          );
        try {
          await expect(
            item.service.acknowledgeRetirementProof(
              item.capture.receiptId,
              item.capture.sourceHash,
              () => {
                if (!live) {
                  throw new Error("ACK operator withdrawn fictif");
                }
              },
            ),
          ).rejects.toThrow("ACK operator withdrawn fictif");
          expect(stages).toEqual(
            refusalStage === "transaction" ? ["transaction"] : ["transaction", "commit"],
          );
        } finally {
          admissionSpy.mockRestore();
        }
        expect(await item.service.listPendingRetirements(() => {}, PROFILE)).toEqual({
          total: 1,
          items: [{ receiptId: item.capture.receiptId, profileId: PROFILE }],
        });
        expect(await item.service.readJob(item.job.id)).toBeUndefined();
        const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
        try {
          expect(
            db
              .prepare(
                "SELECT acknowledged_at_ms FROM cron_job_runtime_retirements WHERE store_key=? AND receipt_id=?",
              )
              .get(item.partition, item.capture.receiptId)?.acknowledged_at_ms,
          ).toBeNull();
        } finally {
          db.close();
        }
        await item.service.acknowledgeRetirementProof(
          item.capture.receiptId,
          item.capture.sourceHash,
          () => {},
        );
        expect((await item.service.listPendingRetirements(() => {}, PROFILE)).total).toBe(0);
      } finally {
        await item.stop();
      }
    },
  );

  it("refuses another human-source fingerprint before ACK commit and retains the exact proof", async () => {
    const item = await fixture();
    try {
      await item.service.removeWithPrecondition(item.job.id, () => {}, {
        retirement: item.capture,
        commitGuard: () => {},
      });
      const stages: string[] = [];
      const realAdmission = operationAdmission.createSqliteWorkerOperationAdmission;
      const admissionSpy = vi
        .spyOn(operationAdmission, "createSqliteWorkerOperationAdmission")
        .mockImplementation((admit, attachment) =>
          realAdmission((request, grant) => {
            stages.push(request.stage);
            admit(request, grant);
          }, attachment),
        );
      try {
        await expect(
          item.service.acknowledgeRetirementProof(item.capture.receiptId, "d".repeat(64), () => {}),
        ).rejects.toThrow("Cron retirement proof refused");
        expect(stages).toEqual(["transaction"]);
      } finally {
        admissionSpy.mockRestore();
      }
      expect((await item.service.listPendingRetirements(() => {}, PROFILE)).total).toBe(1);
      expect(
        (await item.service.readRetirementProof(item.capture.receiptId, () => {}))?.capture,
      ).toEqual(item.capture);
    } finally {
      await item.stop();
    }
  });

  it.each([false, true])(
    "invalidates the service view after a committed DELETE result is lost, scheduler flag=%s",
    async (cronEnabled) => {
      const item = await fixture(cronEnabled);
      const failure = new Error("synthetic committed retirement result lost");
      const realOperation = stateWorker.runOpenClawStateWorkerOperation;
      let deletes = 0;
      const replySpy = vi
        .spyOn(stateWorker, "runOpenClawStateWorkerOperation")
        .mockImplementation((context, operation, options) =>
          realOperation(
            context,
            async (scope) =>
              await operation({
                execute: async (command, executeOptions) => {
                  const result = await scope.execute(command, executeOptions);
                  if (command.type === "cron.saveChanges") {
                    // The real worker committed and emitted its private receipt; withhold only its result.
                    deletes += 1;
                    throw failure;
                  }
                  return result;
                },
              }),
            options,
          ),
        );
      try {
        try {
          const completion = createCronMutationCompletion("cron.remove");
          if (!completion) {
            throw new Error("missing native mutation completion owner");
          }
          await expect(
            completion.run(
              async () =>
                await item.service.removeWithPrecondition(item.job.id, () => {}, {
                  retirement: item.capture,
                  commitGuard: () => {},
                }),
            ),
          ).rejects.toBe(failure);
          expect(completion.isCommitted()).toBe(true);
          expect(deletes).toBe(1);
        } finally {
          replySpy.mockRestore();
        }
        const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
        try {
          expect(
            db
              .prepare("SELECT count(*) AS n FROM cron_jobs WHERE store_key=? AND job_id=?")
              .get(item.partition, item.job.id)?.n,
          ).toBe(0);
        } finally {
          db.close();
        }
        // Publication invalidates the restored snapshot; public reads reload, never replay DELETE.
        expect(await item.service.readJob(item.job.id)).toBeUndefined();
        expect(await item.create().readJob(item.job.id)).toBeUndefined();
        expect(
          (await item.service.readRetirementProof(item.capture.receiptId, () => {}))?.capture,
        ).toEqual(item.capture);
        expect((await item.service.listPendingRetirements(() => {}, PROFILE)).total).toBe(1);
        expect(deletes).toBe(1);
      } finally {
        await item.stop();
      }
    },
  );

  it("rolls back both the tombstone and DELETE when the live guard is withdrawn inside SQL", async () => {
    const item = await fixture();
    let live = true;
    const stages: string[] = [];
    const realAdmission = operationAdmission.createSqliteWorkerOperationAdmission;
    const admissionSpy = vi
      .spyOn(operationAdmission, "createSqliteWorkerOperationAdmission")
      .mockImplementation((admit, attachment) =>
        realAdmission((request, grant) => {
          if (request.stage === "transaction" || request.stage === "commit") {
            stages.push(request.stage);
          }
          // Withdraw the operator after the worker's row writes, before the native commit.
          if (request.stage === "commit") {
            live = false;
          }
          admit(request, grant);
        }, attachment),
      );
    try {
      await expect(
        item.service.removeWithPrecondition(item.job.id, () => {}, {
          retirement: item.capture,
          commitGuard: () => {
            if (!live) {
              throw new Error("operator withdrawn fictif");
            }
          },
        }),
      ).rejects.toMatchObject({
        name: "SqliteWorkerError",
        code: "closed",
        message: "SQLite transaction admission was refused",
      });
      expect(stages).toEqual(["transaction", "commit"]);
      expect(await item.service.readJob(item.job.id)).toBeDefined();
      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        expect(readCronRetirementProof(db, item.partition, item.capture.receiptId)).toBeUndefined();
      } finally {
        db.close();
      }
    } finally {
      admissionSpy.mockRestore();
      await item.stop();
    }
  });

  it.each([false, true])(
    "records the tombstone on the native worker without main SQL, scheduler flag=%s",
    async (cronEnabled) => {
      const item = await fixture(cronEnabled);
      const mainSql = vi
        .spyOn(retirementStore, "recordCronRetirementBeforeDelete")
        .mockImplementation(() => {
          throw new Error("main-thread retirement SQL must not run");
        });
      try {
        const completion = createCronMutationCompletion("cron.remove");
        if (!completion) {
          throw new Error("missing native mutation completion owner");
        }
        const result = await completion.run(
          async () =>
            await item.service.removeWithPrecondition(item.job.id, () => {}, {
              retirement: item.capture,
              commitGuard: () => {},
            }),
        );
        expect(result.removed).toBe(true);
        expect(completion.isCommitted()).toBe(true);
        expect(mainSql).not.toHaveBeenCalled();
        expect(await item.service.readJob(item.job.id)).toBeUndefined();
        const proof = await item.service.readRetirementProof(item.capture.receiptId, () => {});
        expect(proof?.capture).toEqual(item.capture);
        expect(proof?.authority.payload.capabilite).toBe(CAPABILITY);
      } finally {
        mainSql.mockRestore();
        await item.stop();
      }
    },
  );

  it("refuses a changed job preimage and retains the native authority without a tombstone", async () => {
    const item = await fixture();
    try {
      await item.service.updateWithPrecondition(
        item.job.id,
        { description: "concurrent edit fictive" },
        () => {},
      );
      await expect(
        item.service.removeWithPrecondition(item.job.id, () => {}, {
          commitGuard: () => {},
          retirement: item.capture,
        }),
      ).rejects.toThrow("Cron retirement proof refused");
      expect(await item.service.readJob(item.job.id)).toBeDefined();
      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        expect(readCronRetirementProof(db, item.partition, item.capture.receiptId)).toBeUndefined();
      } finally {
        db.close();
      }
    } finally {
      await item.stop();
    }
  });
});
