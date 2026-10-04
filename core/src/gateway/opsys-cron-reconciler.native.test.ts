import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { resolveCronJobConfigRevision } from "../cron/config-revision.js";
import { CronService } from "../cron/service.js";
import { createCronStoreHarness } from "../cron/service.test-harness.js";
import { cronStoreKey } from "../cron/store/key.js";
import { OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX } from "../cron/store/opsys-runtime-authority-crypto.js";
import type { CronJob } from "../cron/types.js";
import { resolveOpenClawStateSqlitePath } from "../state/openclaw-state-db.paths.js";
import { captureEnv, setTestEnvValue } from "../test-utils/env.js";
import { OpsysCronPrivateClientError, type CronDeclaration } from "./opsys-cron-private-client.js";
import {
  type OpsysCronPrivateClientPort,
  reconcileOpsysCronProfile,
  reconcileOpsysCronRetirements,
} from "./opsys-cron-reconciler.js";
import { decodeOpsysCronRuntimeGrant } from "./opsys-cron-runtime-grant.js";

// All identities, tools and grants below are synthetic (fictif: true).
// Only the Python private-client port is mocked: CronService and SQLite are real.
const PROFILE = "estimation";
const PROFILE_REVISION = 7;
const FUSEAU = "UTC";
const CRON_EXPRESSION = "0 * * * *";
const TRIGGER_HASH = createHash("sha256")
  .update(JSON.stringify({ expression: CRON_EXPRESSION, type: "cron" }), "utf8")
  .digest("hex");
const INTENTION_ID = createHash("sha256")
  .update(
    JSON.stringify({
      cron: TRIGGER_HASH,
      fuseau: FUSEAU,
      instance: "fixture-native-instance",
      profil: PROFILE,
      revision: PROFILE_REVISION,
    }),
    "utf8",
  )
  .digest("hex");
const CAPABILITY = "31".repeat(32);
const KEY_ENV = ["OPENCLAW_CRON_AUTHORITY_KEY_FILE", "OPENCLAW_CRON_AUTHORITY_KEY_ID"] as const;

function declaration(): CronDeclaration {
  return {
    name: `OPSYS profil ${PROFILE}`,
    declarationKey: `opsys-profile:${INTENTION_ID}`,
    agentId: `opsys-agent-${PROFILE}`,
    sessionTarget: "isolated",
    wakeMode: "now",
    schedule: { kind: "cron", expr: CRON_EXPRESSION, tz: FUSEAU },
    payload: {
      kind: "agentTurn",
      message: `Exécute le mandat interne canonique du profil ${PROFILE}, révision ${PROFILE_REVISION}.`,
      timeoutSeconds: 120,
      toolsAllow: ["opsys_m3__m3_lire_devis"],
    },
    delivery: { mode: "none" },
  };
}

// One stable external key for this suite; use the same native module owners as
// withOpenClawTestState rather than rebuilding their coordinator after it opens.
const { makeStorePath } = createCronStoreHarness({ prefix: "opsys-cron-native-" });
const keyEnv = captureEnv([...KEY_ENV]);
let keyDir: string;
let keyPath: string;
beforeAll(async () => {
  keyDir = await fs.mkdtemp(path.join(os.tmpdir(), "opsys-cron-native-key-"));
  keyPath = path.join(keyDir, "authority.key");
  await fs.chmod(keyDir, 0o700);
  const key = randomBytes(32);
  await fs.writeFile(keyPath, key, { mode: 0o600, flag: "wx" });
  await fs.chmod(keyPath, 0o600);
  setTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_FILE", keyPath);
  setTestEnvValue(
    "OPENCLAW_CRON_AUTHORITY_KEY_ID",
    `sha256:${createHash("sha256").update(key).digest("hex")}`,
  );
});
afterAll(async () => {
  keyEnv.restore();
  if (keyDir) await fs.rm(keyDir, { recursive: true, force: true });
});

type NativeFixture = {
  createService: () => CronService;
  reconcile: typeof reconcileOpsysCronProfile;
  decodeGrant: typeof decodeOpsysCronRuntimeGrant;
  readPersisted: (jobId: string) => {
    jobJson: string;
    authorityJson: string;
    recoveryRequired: number;
    count: number;
  };
  ciphertextPrefix: string;
};

async function withNativeFixture(run: (fixture: NativeFixture) => Promise<void>): Promise<void> {
  const store = await makeStorePath();
  const storePath = store.storePath;
  const caseRoot = path.dirname(path.dirname(storePath));
  const services: CronService[] = [];
  const enqueueSystemEvent = vi.fn(() => {
    throw new Error("unexpected scheduler dispatch");
  });
  const requestHeartbeat = vi.fn(() => {
    throw new Error("unexpected scheduler heartbeat");
  });
  const runIsolatedAgentJob = vi.fn(() =>
    Promise.reject(new Error("unexpected provider dispatch")),
  );
  try {
    expect(path.relative(caseRoot, keyPath)).toMatch(/^\.\.(?:\/|\\)/u);
    expect(path.relative(process.cwd(), keyPath)).toMatch(/^\.\.(?:\/|\\)/u);
    const keyStat = await fs.lstat(keyPath);
    expect(keyStat.isFile()).toBe(true);
    expect(keyStat.isSymbolicLink()).toBe(false);
    expect(keyStat.nlink).toBe(1);
    expect(keyStat.mode & 0o777).toBe(0o600);
    if (typeof process.geteuid !== "function") {
      throw new Error("native authority fixture requires a POSIX effective UID");
    }
    expect(keyStat.uid).toBe(process.geteuid());
    const partition = cronStoreKey(storePath);
    const createService = () => {
      const service = new CronService({
        storePath,
        cronEnabled: false,
        nowMs: () => 1_800_000_000_000,
        log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
        enqueueSystemEvent,
        requestHeartbeat,
        runIsolatedAgentJob,
      });
      services.push(service);
      // Deliberately do not call start(): there is no scheduler or provider.
      return service;
    };
    await run({
      createService,
      reconcile: reconcileOpsysCronProfile,
      decodeGrant: decodeOpsysCronRuntimeGrant,
      ciphertextPrefix: OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX,
      readPersisted: (jobId) => {
        const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
        try {
          const row = db
            .prepare(
              "SELECT j.job_json, a.authority_json, a.recovery_required FROM cron_jobs j " +
                "JOIN cron_job_runtime_authorities a ON a.store_key = j.store_key AND a.job_id = j.job_id " +
                "WHERE j.store_key = ? AND j.job_id = ?",
            )
            .get(partition, jobId);
          const count = db
            .prepare("SELECT COUNT(*) AS count FROM cron_jobs WHERE store_key = ?")
            .get(partition);
          if (
            !row ||
            typeof row.job_json !== "string" ||
            typeof row.authority_json !== "string" ||
            typeof row.recovery_required !== "number" ||
            !count ||
            typeof count.count !== "number"
          ) {
            throw new Error("native encrypted SQLite fixture row is missing");
          }
          return {
            jobJson: row.job_json,
            authorityJson: row.authority_json,
            recoveryRequired: row.recovery_required,
            count: count.count,
          };
        } finally {
          db.close();
        }
      },
    });
  } finally {
    for (const service of services) service.stop();
    expect(enqueueSystemEvent).not.toHaveBeenCalled();
    expect(requestHeartbeat).not.toHaveBeenCalled();
    expect(runIsolatedAgentJob).not.toHaveBeenCalled();
    await store.cleanup();
  }
}

function makePythonOwner(
  getService: () => CronService,
  options: { loseFirstAck?: boolean; revokedAtAck?: boolean } = {},
) {
  const nativeDeclaration = declaration();
  const observations: { enabled: boolean; target: string; capability: string; jobId: string }[] =
    [];
  const listImpl: OpsysCronPrivateClientPort["list"] = async (profileId) => {
    expect(profileId).toBe(PROFILE);
    return {
      total: 1,
      retournes: 1,
      omis: 0,
      items: [
        {
          intention_id: INTENTION_ID,
          etat: "a_declarer",
          revision_profil: PROFILE_REVISION,
          fuseau: FUSEAU,
        },
      ],
    };
  };
  const projectImpl: OpsysCronPrivateClientPort["project"] = async (profileId, intentionId) => {
    expect(profileId).toBe(PROFILE);
    expect(intentionId).toBe(INTENTION_ID);
    return {
      intention: INTENTION_ID,
      etat: "a_declarer",
      execute: false,
      native: { method: "cron.add", params: nativeDeclaration },
    };
  };
  const prepareImpl: OpsysCronPrivateClientPort["prepare"] = async (
    profileId,
    intentionId,
    input,
  ) => {
    expect(profileId).toBe(PROFILE);
    expect(intentionId).toBe(INTENTION_ID);
    expect(input).toEqual({
      capabilityFingerprint: createHash("sha256")
        .update(Buffer.from(CAPABILITY, "hex"))
        .digest("hex"),
      declaration: nativeDeclaration,
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
    });
    return {
      intention: intentionId,
      epoch: 1,
      lease_epoch: 1,
      etat: "preparation",
      job_id: null,
      config_revision: null,
      execute: false,
      lease_until: "2027-01-15T08:00:30+00:00",
      revision_native_attendue: null,
      native: { method: "cron.add", params: input.declaration },
    };
  };
  const acknowledgeImpl: OpsysCronPrivateClientPort["acknowledge"] = async (profileId, input) => {
    expect(profileId).toBe(PROFILE);
    expect(input.intentionId).toBe(INTENTION_ID);
    expect(input.capability).toBe(CAPABILITY);
    expect(input.epoch).toBe(1);
    expect(input.leaseEpoch).toBe(1);
    expect(input.declaration).toEqual(nativeDeclaration);
    const job = await getService().readJob(input.jobId);
    if (!job) throw new Error("ACK arrived before the native job was durable");
    const target = resolveCronJobConfigRevision({ ...job, enabled: true });
    observations.push({
      enabled: job.enabled,
      target,
      capability: input.capability,
      jobId: job.id,
    });
    expect(input.configRevision).toBe(target);
    if (options.revokedAtAck) throw new OpsysCronPrivateClientError("refused");
    if (options.loseFirstAck && observations.length === 1)
      throw new OpsysCronPrivateClientError("unavailable");
    return {
      intention: input.intentionId,
      epoch: input.epoch,
      lease_epoch: input.leaseEpoch,
      etat: "remise",
      job_id: input.jobId,
      config_revision: input.configRevision,
      execute: false,
    };
  };
  const list = vi.fn(listImpl);
  const project = vi.fn(projectImpl);
  const prepare = vi.fn(prepareImpl);
  const acknowledge = vi.fn(acknowledgeImpl);
  const client: OpsysCronPrivateClientPort = {
    list,
    project,
    prepare,
    acknowledge,
    prepareRetirement: async () => {
      throw new Error("unexpected cleanup in creation fixture");
    },
    acknowledgeRetirement: async () => {
      throw new Error("unexpected cleanup in creation fixture");
    },
  };
  return { client, prepare, acknowledge, observations };
}

async function onlyJob(cron: CronService): Promise<CronJob> {
  const jobs = await cron.list({ includeDisabled: true });
  expect(jobs).toHaveLength(1);
  const job = jobs[0];
  if (!job) throw new Error("native fixture job missing");
  return job;
}

function runPass(
  fixture: NativeFixture,
  cron: CronService,
  client: OpsysCronPrivateClientPort,
  entropy: (size: number) => Buffer,
) {
  return fixture.reconcile({
    cron,
    client,
    profileId: PROFILE,
    expectedProfileRevision: PROFILE_REVISION,
    allowedProfileIds: new Set([PROFILE]),
    commitGuard: () => {},
    randomBytesImpl: entropy,
  });
}

describe("OPSYS reconciler with the native CronService and encrypted SQLite", () => {
  it("creates disabled, ACKs the actual enabled-target SHA, CAS-enables and reopens without add or rotation", async () => {
    await withNativeFixture(async (fixture) => {
      let cron = fixture.createService();
      const owner = makePythonOwner(() => cron);
      const entropy = vi.fn((_size: number) => Buffer.from(CAPABILITY, "hex"));
      const add = vi.spyOn(cron, "add");
      const enable = vi.spyOn(cron, "updateWithPrecondition");
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({ ok: true, changed: 1 });
      const created = await onlyJob(cron);
      expect(add).toHaveBeenCalledOnce();
      expect(add.mock.calls[0]?.[0].enabled).toBe(false);
      expect(owner.observations).toEqual([
        {
          enabled: false,
          target: resolveCronJobConfigRevision(created),
          capability: CAPABILITY,
          jobId: created.id,
        },
      ]);
      expect(enable).toHaveBeenCalledOnce();
      expect(enable.mock.calls[0]?.[1]).toEqual({ enabled: true });
      expect(created.enabled).toBe(true);
      expect(created.schedule).toEqual({
        kind: "cron",
        expr: CRON_EXPRESSION,
        tz: FUSEAU,
        staggerMs: 5 * 60 * 1000,
      });
      expect(created.payload).toEqual(declaration().payload);
      expect(created.delivery).toEqual({ mode: "none" });
      // Keep the real derived policy; never strip metadata to satisfy a matcher.
      expect(created.scheduledToolPolicy).toEqual({ version: 1, mode: "trusted" });
      const persisted = fixture.readPersisted(created.id);
      expect(persisted.count).toBe(1);
      expect(persisted.recoveryRequired).toBe(0);
      expect(persisted.authorityJson.startsWith(fixture.ciphertextPrefix)).toBe(true);
      expect(persisted.authorityJson).not.toContain(CAPABILITY);
      expect(persisted.jobJson).not.toContain(CAPABILITY);
      expect(JSON.parse(persisted.jobJson)).not.toHaveProperty("runtimeAuthority");
      cron.stop();
      cron = fixture.createService();
      const restartedAdd = vi.spyOn(cron, "add");
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({ ok: true, changed: 0 });
      const reopened = await onlyJob(cron);
      expect(reopened.id).toBe(created.id);
      expect(reopened.enabled).toBe(true);
      expect(
        fixture.decodeGrant(reopened, { profileId: PROFILE, intentionId: INTENTION_ID }),
      ).toMatchObject({
        capability: CAPABILITY,
        epoch: 1,
        leaseEpoch: 1,
        profileRevision: PROFILE_REVISION,
      });
      expect(restartedAdd).not.toHaveBeenCalled();
      expect(owner.prepare).toHaveBeenCalledOnce();
      expect(owner.acknowledge).toHaveBeenCalledTimes(2);
      expect(entropy).toHaveBeenCalledOnce();
      expect(fixture.readPersisted(reopened.id).count).toBe(1);
    });
  });

  it("recovers an ACK loss from the disabled encrypted row after a new service instance", async () => {
    await withNativeFixture(async (fixture) => {
      let cron = fixture.createService();
      const owner = makePythonOwner(() => cron, { loseFirstAck: true });
      const entropy = vi.fn((_size: number) => Buffer.from(CAPABILITY, "hex"));
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({
        ok: false,
        reason: "stale-or-invalid",
      });
      const captured = await onlyJob(cron);
      expect(captured.enabled).toBe(false);
      expect(
        fixture.readPersisted(captured.id).authorityJson.startsWith(fixture.ciphertextPrefix),
      ).toBe(true);
      cron.stop();
      cron = fixture.createService();
      const add = vi.spyOn(cron, "add");
      const enable = vi.spyOn(cron, "updateWithPrecondition");
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({ ok: true, changed: 1 });
      const recovered = await onlyJob(cron);
      expect(recovered.id).toBe(captured.id);
      expect(recovered.enabled).toBe(true);
      expect(owner.observations).toEqual([
        {
          enabled: false,
          target: resolveCronJobConfigRevision(recovered),
          capability: CAPABILITY,
          jobId: captured.id,
        },
        {
          enabled: false,
          target: resolveCronJobConfigRevision(recovered),
          capability: CAPABILITY,
          jobId: captured.id,
        },
      ]);
      expect(
        fixture.decodeGrant(recovered, { profileId: PROFILE, intentionId: INTENTION_ID })
          ?.capability,
      ).toBe(CAPABILITY);
      expect(add).not.toHaveBeenCalled();
      expect(enable).toHaveBeenCalledOnce();
      expect(owner.prepare).toHaveBeenCalledOnce();
      expect(owner.acknowledge).toHaveBeenCalledTimes(2);
      expect(entropy).toHaveBeenCalledOnce();
      expect(fixture.readPersisted(recovered.id).count).toBe(1);
    });
  });

  it("keeps the native job disabled when the Python owner refuses ACK, including after reopen", async () => {
    await withNativeFixture(async (fixture) => {
      let cron = fixture.createService();
      const owner = makePythonOwner(() => cron, { revokedAtAck: true });
      const entropy = vi.fn((_size: number) => Buffer.from(CAPABILITY, "hex"));
      const firstEnable = vi.spyOn(cron, "updateWithPrecondition");
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({
        ok: false,
        reason: "stale-or-invalid",
      });
      const captured = await onlyJob(cron);
      expect(captured.enabled).toBe(false);
      expect(firstEnable).not.toHaveBeenCalled();
      const persisted = fixture.readPersisted(captured.id);
      cron.stop();
      cron = fixture.createService();
      const add = vi.spyOn(cron, "add");
      const enable = vi.spyOn(cron, "updateWithPrecondition");
      expect(await runPass(fixture, cron, owner.client, entropy)).toEqual({
        ok: false,
        reason: "stale-or-invalid",
      });
      const reopened = await onlyJob(cron);
      expect(reopened.id).toBe(captured.id);
      expect(reopened.enabled).toBe(false);
      expect(owner.acknowledge).toHaveBeenCalledTimes(2);
      expect(owner.prepare).toHaveBeenCalledOnce();
      expect(entropy).toHaveBeenCalledOnce();
      expect(add).not.toHaveBeenCalled();
      expect(enable).not.toHaveBeenCalled();
      expect(fixture.readPersisted(reopened.id)).toEqual(persisted);
    });
  });
});

function makeCleanupOwner(getService: () => CronService) {
  // Fictif: true. Python is the only modeled collaborator; Core/CAS/SQLite/AES remain real.
  const base = makePythonOwner(getService);
  let retirementRequested = false;
  let terminal = false;
  let loseNextAck = false;
  let denyExecutionProjection = false;
  const preparations: Parameters<OpsysCronPrivateClientPort["prepareRetirement"]>[1][] = [];
  const receipts: string[] = [];
  const client: OpsysCronPrivateClientPort = {
    ...base.client,
    list: async (profileId) => {
      if (terminal) {
        expect((await getService().listPendingRetirements(() => {})).total).toBe(0);
        return { total: 0, retournes: 0, omis: 0, items: [] };
      }
      return await base.client.list(profileId);
    },
    project: async (profileId, intentionId) => {
      if (denyExecutionProjection) throw new OpsysCronPrivateClientError("refused");
      if (!retirementRequested) return await base.client.project(profileId, intentionId);
      return {
        intention: INTENTION_ID,
        etat: "a_retirer",
        execute: false,
        native: null,
        declaration_key: `opsys-profile:${INTENTION_ID}`,
        reconciliation: "rechercher_id_natif_puis_retirer",
      };
    },
    prepareRetirement: async (profileId, input) => {
      expect(profileId).toBe(PROFILE);
      expect(retirementRequested).toBe(true);
      expect(input.intentionId).toBe(INTENTION_ID);
      expect(input.capability).toBe(CAPABILITY);
      const job = await getService().readJob(input.jobId);
      expect(job?.enabled).toBe(false);
      if (!job) throw new Error("preparation after native DELETE is forbidden");
      expect(input.nativeRevision).toBe(resolveCronJobConfigRevision(job));
      preparations.push(input);
      const proof = {
        version: 1 as const,
        intention: INTENTION_ID,
        source_hash: "c".repeat(64),
        epoch: input.epoch,
        job_id: input.jobId,
        native_revision: input.nativeRevision,
        declaration_hash: createHash("sha256")
          .update(stableStringify(input.declaration))
          .digest("hex"),
        declaration_key: `opsys-profile:${INTENTION_ID}`,
      };
      return {
        ...proof,
        receipt_id: createHash("sha256").update(stableStringify(proof)).digest("hex"),
        execute: false,
      };
    },
    acknowledgeRetirement: async (profileId, input) => {
      expect(profileId).toBe(PROFILE);
      expect(await getService().readJob(input.jobId)).toBeUndefined();
      const durable = await getService().readRetirementProof(input.receiptId, () => {});
      expect(durable?.capture.sourceHash).toBe(input.sourceHash);
      expect(durable?.capture.nativeRevision).toBe(input.nativeRevision);
      expect(durable?.authority.payload.capabilite).toBe(input.capability);
      terminal = true; // Modeled Python transaction commits before the simulated lost reply.
      receipts.push(input.receiptId);
      if (loseNextAck) {
        loseNextAck = false;
        throw new OpsysCronPrivateClientError("unavailable");
      }
      return {
        intention: input.intentionId,
        receipt_id: input.receiptId,
        source_hash: input.sourceHash,
        epoch: input.epoch,
        job_id: input.jobId,
        etat: "retiree",
        execute: false,
      };
    },
  };
  return {
    client,
    base,
    preparations,
    receipts,
    retire: () => {
      retirementRequested = true;
    },
    loseAck: () => {
      loseNextAck = true;
    },
    denyProjection: () => {
      denyExecutionProjection = true;
    },
  };
}

describe("OPSYS native terminal retirement pipeline", () => {
  it("keeps the old activation ACK distinct from the actual disabled CAS and preserves the encrypted terminal proof", async () => {
    await withNativeFixture(async (fixture) => {
      const cron = fixture.createService();
      const owner = makeCleanupOwner(() => cron);
      expect(
        (await runPass(fixture, cron, owner.client, () => Buffer.from(CAPABILITY, "hex"))).ok,
      ).toBe(true);
      const enabled = await onlyJob(cron);
      const oldAck = resolveCronJobConfigRevision(enabled);
      owner.retire();
      expect(
        await reconcileOpsysCronRetirements({
          cron,
          client: owner.client,
          configuredProfileIds: new Set(),
          commitGuard: () => {},
        }),
      ).toEqual({ ok: true, changed: 1 });
      expect(owner.base.observations[0]?.target).toBe(oldAck);
      expect(owner.preparations[0]?.nativeRevision).toBe(
        resolveCronJobConfigRevision({ ...enabled, enabled: false }),
      );
      expect(owner.preparations[0]?.nativeRevision).not.toBe(oldAck);
      expect(await cron.readJob(enabled.id)).toBeUndefined();
      expect((await cron.listPendingRetirements(() => {})).total).toBe(0);
      const receiptId = owner.receipts[0];
      if (!receiptId) throw new Error("private terminal receipt missing");
      const proof = await cron.readRetirementProof(receiptId, () => {});
      expect(proof?.jobId).toBe(enabled.id);
      expect(proof?.authority.payload.capabilite).toBe(CAPABILITY);
      expect(proof?.capture.nativeRevision).toBe(owner.preparations[0]?.nativeRevision);
    });
  });

  it("recovers DELETE plus lost Python ACK after restart without a second add/remove or execution projection", async () => {
    await withNativeFixture(async (fixture) => {
      let cron = fixture.createService();
      const owner = makeCleanupOwner(() => cron);
      expect(
        (await runPass(fixture, cron, owner.client, () => Buffer.from(CAPABILITY, "hex"))).ok,
      ).toBe(true);
      const created = await onlyJob(cron);
      owner.retire();
      owner.loseAck();
      const remove = vi.spyOn(cron, "removeWithPrecondition");
      expect(
        (
          await reconcileOpsysCronRetirements({
            cron,
            client: owner.client,
            configuredProfileIds: new Set(),
            commitGuard: () => {},
          })
        ).ok,
      ).toBe(false);
      expect(await cron.readJob(created.id)).toBeUndefined();
      expect((await cron.listPendingRetirements(() => {})).total).toBe(1);
      expect(remove).toHaveBeenCalledOnce();
      cron.stop();
      cron = fixture.createService();
      const secondAdd = vi.spyOn(cron, "add");
      const secondRemove = vi.spyOn(cron, "removeWithPrecondition");
      owner.denyProjection(); // A terminal retry uses the tombstone, never a live execution mandate.
      expect(
        await reconcileOpsysCronRetirements({
          cron,
          client: owner.client,
          configuredProfileIds: new Set(),
          commitGuard: () => {},
        }),
      ).toEqual({ ok: true, changed: 1 });
      expect((await cron.listPendingRetirements(() => {})).total).toBe(0);
      expect(owner.receipts).toHaveLength(2);
      expect(owner.receipts[0]).toBe(owner.receipts[1]);
      expect(secondAdd).not.toHaveBeenCalled();
      expect(secondRemove).not.toHaveBeenCalled();
      // Profile pass reads the modeled terminal list only after the native pending receipt was drained.
      expect(
        await runPass(fixture, cron, owner.client, () => {
          throw new Error("unexpected new capability after terminal cleanup");
        }),
      ).toEqual({ ok: true, changed: 0 });
    });
  });

  it("keeps a waiting/revoked execution profile disabled when no human retirement source can be projected", async () => {
    await withNativeFixture(async (fixture) => {
      const cron = fixture.createService();
      const owner = makeCleanupOwner(() => cron);
      expect(
        (await runPass(fixture, cron, owner.client, () => Buffer.from(CAPABILITY, "hex"))).ok,
      ).toBe(true);
      const created = await onlyJob(cron);
      owner.denyProjection();
      expect(
        (
          await reconcileOpsysCronRetirements({
            cron,
            client: owner.client,
            configuredProfileIds: new Set(),
            commitGuard: () => {},
          })
        ).ok,
      ).toBe(false);
      expect((await cron.readJob(created.id))?.enabled).toBe(false);
      expect((await cron.listPendingRetirements(() => {})).total).toBe(0);
      expect(owner.receipts).toEqual([]);
      expect(owner.preparations).toEqual([]);
    });
  });
});
