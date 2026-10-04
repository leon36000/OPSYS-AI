import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveOpenClawStateSqlitePath } from "../../state/openclaw-state-db.paths.js";
import { captureEnv, deleteTestEnvValue, setTestEnvValue } from "../../test-utils/env.js";
import { withOpenClawTestState } from "../../test-utils/openclaw-test-state.js";
import type { CronStoreFile } from "../types.js";
import { OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX } from "./opsys-runtime-authority-crypto.js";

const KEY_ENV = ["OPENCLAW_CRON_AUTHORITY_KEY_FILE", "OPENCLAW_CRON_AUTHORITY_KEY_ID"] as const;
const envSnapshot = captureEnv([...KEY_ENV]);
const testKeyPaths: string[] = [];

afterEach(async () => {
  envSnapshot.restore();
  vi.resetModules();
  await Promise.all(testKeyPaths.splice(0).map((keyPath) => fs.rm(keyPath, { force: true })));
});

function makeOpsysStore(jobId: string): CronStoreFile {
  const now = Date.now();
  return {
    version: 1,
    jobs: [
      {
        id: jobId,
        name: `Authority ${jobId}`,
        enabled: true,
        createdAtMs: now,
        updatedAtMs: now,
        schedule: { kind: "every", everyMs: 60_000 },
        sessionTarget: "isolated",
        wakeMode: "next-heartbeat",
        owner: { agentId: "main", sessionKey: "agent:main:opsys" },
        payload: { kind: "agentTurn", message: "continue", toolsAllow: ["read", "cron"] },
        scheduledToolPolicy: { version: 1, mode: "trusted" },
        toolsAllowProvenance: { version: 1, source: "final-executable-surface" },
        runtimeAuthority: {
          version: 1,
          runtimeId: "openclaw",
          namespace: "opsys-cron-authority-v1",
          payload: { grant: "sensitive-opsys-payload" },
        },
        state: {},
      },
    ],
  };
}

async function installTestKey(stateRoot: string): Promise<void> {
  const keyPath = path.join(os.tmpdir(), `openclaw-cron-authority-${process.pid}-${Date.now()}`);
  testKeyPaths.push(keyPath);
  const key = randomBytes(32);
  await fs.writeFile(keyPath, key, { mode: 0o600, flag: "wx" });
  await fs.chmod(keyPath, 0o600);
  setTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_FILE", keyPath);
  setTestEnvValue(
    "OPENCLAW_CRON_AUTHORITY_KEY_ID",
    `sha256:${createHash("sha256").update(key).digest("hex")}`,
  );
  // Test keys live outside every state/config/workspace root under test.
  expect(path.resolve(keyPath).startsWith(path.resolve(stateRoot))).toBe(false);
}

async function importStore() {
  vi.resetModules();
  return await import("../store.js");
}

function readAuthorityRow(storeKey: string, jobId: string) {
  const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
  try {
    return db
      .prepare(
        "SELECT authority_json, authority_input_fingerprint, recovery_required FROM cron_job_runtime_authorities WHERE store_key = ? AND job_id = ?",
      )
      .get(storeKey, jobId) as
      | { authority_json: string | null; authority_input_fingerprint: string | null; recovery_required: number }
      | undefined;
  } finally {
    db.close();
  }
}

describe("OPSYS cron authority encrypted SQLite sidecar", () => {
  it("round-trips a reserved authority through the encrypted SQLite row", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-roundtrip-" }, async (state) => {
      await installTestKey(state.root);
      const storePath = state.path("workspace", "cron", "jobs.json");
      const expected = makeOpsysStore("opsys-authority-roundtrip");
      const writer = await importStore();
      await writer.saveCronStore(storePath, expected);

      const { cronStoreKey } = await import("./key.js");
      const row = readAuthorityRow(cronStoreKey(storePath), "opsys-authority-roundtrip");
      expect(row?.authority_json?.startsWith(OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX)).toBe(true);
      expect(row?.recovery_required).toBe(0);

      // A fresh store module instance checks that decoding is not tied to one module cache.
      const reader = await importStore();
      const loaded = (await reader.loadCronStore(storePath)).jobs[0]?.runtimeAuthority;
      expect(loaded).toEqual(expected.jobs[0]?.runtimeAuthority);
      expect(loaded?.payload.grant).toBe("sensitive-opsys-payload");
    });
  });

  it("keeps ciphertext byte-for-byte on key loss and tamper, then replaces only on explicit capture", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-cipher-" }, async (state) => {
      await installTestKey(state.root);
      const storePath = state.path("workspace", "cron", "jobs.json");
      const jobId = "opsys-authority-cipher";
      const source = makeOpsysStore(jobId);
      const store = await importStore();
      await store.saveCronStore(storePath, source);

      const { cronStoreKey } = await import("./key.js");
      const storeKey = cronStoreKey(storePath);
      const encrypted = readAuthorityRow(storeKey, jobId);
      expect(encrypted?.authority_json?.startsWith(OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX)).toBe(true);
      expect(encrypted?.authority_json).not.toContain("sensitive-opsys-payload");
      expect(encrypted?.authority_input_fingerprint).toMatch(/^v1:[a-f0-9]{64}$/u);
      expect(encrypted?.recovery_required).toBe(0);

      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        const parent = db
          .prepare("SELECT job_json FROM cron_jobs WHERE store_key = ? AND job_id = ?")
          .get(storeKey, jobId) as { job_json: string };
        expect(JSON.parse(parent.job_json)).not.toHaveProperty("runtimeAuthority");
        expect(JSON.parse(parent.job_json)).not.toHaveProperty("runtimeAuthorityCiphertextDisposition");
      } finally {
        db.close();
      }

      const restartedStore = await importStore();
      expect((await restartedStore.loadCronStore(storePath)).jobs[0]?.runtimeAuthority).toMatchObject({
        payload: { grant: "sensitive-opsys-payload" },
      });
      expect(
        (await restartedStore.loadCronJobsStoreWithConfigJobsReadOnly(storePath)).store.jobs[0]
          ?.runtimeAuthority,
      ).toMatchObject({ payload: { grant: "sensitive-opsys-payload" } });

      const rollbackDb = new DatabaseSync(resolveOpenClawStateSqlitePath());
      rollbackDb.exec(`
        CREATE TRIGGER reject_opsys_authority_update
        BEFORE UPDATE ON cron_job_runtime_authorities
        BEGIN SELECT RAISE(ABORT, 'authority write rejected'); END;
      `);
      try {
        const changed = structuredClone(source);
        changed.jobs[0]!.description = "must roll back";
        await expect(restartedStore.saveCronStore(storePath, changed)).rejects.toThrow(
          "authority write rejected",
        );
      } finally {
        rollbackDb.exec("DROP TRIGGER reject_opsys_authority_update;");
        rollbackDb.close();
      }
      expect(readAuthorityRow(storeKey, jobId)).toEqual(encrypted);

      // Flip ciphertext bytes while leaving a valid envelope; GCM must reject it without repairing the row.
      const encodedEnvelope = encrypted?.authority_json?.slice(OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX.length);
      if (!encodedEnvelope) throw new Error("encrypted fixture row missing");
      const envelope = JSON.parse(Buffer.from(encodedEnvelope, "base64url").toString("utf8")) as {
        ciphertext: string;
      };
      const ciphertextBytes = Buffer.from(envelope.ciphertext, "base64url");
      ciphertextBytes[0] = ciphertextBytes[0]! ^ 1;
      envelope.ciphertext = ciphertextBytes.toString("base64url");
      const damaged = `${OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX}${Buffer.from(JSON.stringify(envelope)).toString("base64url")}`;
      const tamperDb = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        tamperDb
          .prepare("UPDATE cron_job_runtime_authorities SET authority_json = ? WHERE store_key = ? AND job_id = ?")
          .run(damaged, storeKey, jobId);
      } finally {
        tamperDb.close();
      }
      const brokenBefore = readAuthorityRow(storeKey, jobId);

      const tampered = await restartedStore.loadCronStore(storePath);
      expect(tampered.jobs[0]?.runtimeAuthority).toBeUndefined();
      expect(tampered.jobs[0]?.runtimeAuthorityRecoveryRequired).toBe(true);
      await restartedStore.saveCronStore(storePath, tampered);
      expect(readAuthorityRow(storeKey, jobId)).toEqual(brokenBefore);

      deleteTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_FILE");
      deleteTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_ID");
      const noKeyStore = await importStore();
      const unavailable = await noKeyStore.loadCronStore(storePath);
      expect(unavailable.jobs[0]?.runtimeAuthority).toBeUndefined();
      expect(unavailable.jobs[0]?.runtimeAuthorityRecoveryRequired).toBe(true);
      await noKeyStore.saveCronStore(storePath, unavailable);
      expect(readAuthorityRow(storeKey, jobId)).toEqual(brokenBefore);

      // Returning with the correct host key permits explicit replacement, not implicit replay.
      await installTestKey(state.root);
      const replacementStore = await importStore();
      const replacement = await replacementStore.loadCronStore(storePath);
      const replacementJob = replacement.jobs[0];
      expect(replacementJob?.runtimeAuthority).toBeUndefined();
      expect(replacementJob?.runtimeAuthorityRecoveryRequired).toBe(true);
      if (!replacementJob) throw new Error("test fixture job missing");
      const { reconcileRuntimeAuthority } = await import("../service/jobs-tool-policy.js");
      reconcileRuntimeAuthority({
        job: replacementJob,
        captured: true,
        runtimeAuthority: {
          version: 1,
          runtimeId: "openclaw",
          namespace: "opsys-cron-authority-v1",
          payload: { grant: "explicitly-recaptured" },
        },
        explicitlyMutatesToolsAllow: false,
      });
      await replacementStore.saveCronStore(storePath, replacement);
      const replaced = readAuthorityRow(storeKey, jobId);
      expect(replaced?.authority_json).toMatch(/^OPSYS_CRON_AUTHORITY_A256GCM_V1\./u);
      expect(replaced?.authority_json).not.toBe(damaged);
      expect(replaced?.recovery_required).toBe(0);
      expect((await replacementStore.loadCronStore(storePath)).jobs[0]?.runtimeAuthority).toMatchObject({
        payload: { grant: "explicitly-recaptured" },
      });

      const revoked = await replacementStore.loadCronStore(storePath);
      const revokedJob = revoked.jobs[0];
      if (!revokedJob) throw new Error("test fixture job missing");
      reconcileRuntimeAuthority({
        job: revokedJob,
        captured: false,
        explicitlyMutatesToolsAllow: true,
      });
      await replacementStore.saveCronStore(storePath, revoked);
      expect(readAuthorityRow(storeKey, jobId)).toEqual({
        authority_json: null,
        authority_input_fingerprint: null,
        recovery_required: 1,
      });
      const cleared = await replacementStore.loadCronStore(storePath);
      const clearedJob = cleared.jobs[0];
      if (!clearedJob) throw new Error("test fixture job missing");
      reconcileRuntimeAuthority({
        job: clearedJob,
        captured: true,
        explicitlyMutatesToolsAllow: false,
      });
      await replacementStore.saveCronStore(storePath, cleared);
      expect(readAuthorityRow(storeKey, jobId)).toBeUndefined();
    });
  });

  it("rejects store-key rebinding while preserving the foreign ciphertext and leaves other namespaces opaque", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-rebind-" }, async (state) => {
      await installTestKey(state.root);
      const store = await importStore();
      const { cronStoreKey } = await import("./key.js");
      const jobId = "opsys-authority-rebind";
      const firstPath = state.path("workspace", "one", "jobs.json");
      const secondPath = state.path("workspace", "two", "jobs.json");
      await store.saveCronStore(firstPath, makeOpsysStore(jobId));
      const firstKey = cronStoreKey(firstPath);
      const secondKey = cronStoreKey(secondPath);
      const originalCiphertext = readAuthorityRow(firstKey, jobId)?.authority_json;
      expect(originalCiphertext).toMatch(/^OPSYS_CRON_AUTHORITY_A256GCM_V1\./u);

      await store.saveCronStore(secondPath, makeOpsysStore(jobId));
      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        db.prepare(
          "UPDATE cron_job_runtime_authorities SET authority_json = ? WHERE store_key = ? AND job_id = ?",
        ).run(originalCiphertext, secondKey, jobId);
      } finally {
        db.close();
      }
      const rebound = await store.loadCronStore(secondPath);
      expect(rebound.jobs[0]?.runtimeAuthority).toBeUndefined();
      expect(rebound.jobs[0]?.runtimeAuthorityRecoveryRequired).toBe(true);
      await store.saveCronStore(secondPath, rebound);
      expect(readAuthorityRow(secondKey, jobId)?.authority_json).toBe(originalCiphertext);

      const thirdPath = state.path("workspace", "third-party", "jobs.json");
      const thirdParty = makeOpsysStore("third-party-openclaw");
      thirdParty.jobs[0]!.runtimeAuthority = {
        version: 1,
        runtimeId: "openclaw",
        namespace: "vendor.private-tools",
        payload: { unchanged: "opaque-plaintext-compatible" },
      };
      await store.saveCronStore(thirdPath, thirdParty);
      const thirdKey = cronStoreKey(thirdPath);
      const thirdRow = readAuthorityRow(thirdKey, "third-party-openclaw");
      expect(JSON.parse(thirdRow?.authority_json ?? "null")).toEqual(thirdParty.jobs[0]?.runtimeAuthority);
      expect((await store.loadCronStore(thirdPath)).jobs[0]?.runtimeAuthority).toEqual(
        thirdParty.jobs[0]?.runtimeAuthority,
      );
    });
  });

  it("does not let a stale replacement snapshot overwrite the sidecar; explicit capture does", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-stale-" }, async (state) => {
      await installTestKey(state.root);
      const store = await importStore();
      const { cronStoreKey } = await import("./key.js");
      const { reconcileRuntimeAuthority } = await import("../service/jobs-tool-policy.js");
      const storePath = state.path("workspace", "cron", "jobs.json");
      const jobId = "opsys-authority-stale-snapshot";
      await store.saveCronStore(storePath, makeOpsysStore(jobId));
      const storeKey = cronStoreKey(storePath);
      const stale = await store.loadCronStore(storePath);
      const staleJob = stale.jobs[0];
      if (!staleJob) throw new Error("test fixture job missing");

      const newer = await store.loadCronStore(storePath);
      const newerJob = newer.jobs[0];
      if (!newerJob) throw new Error("test fixture job missing");
      reconcileRuntimeAuthority({
        job: newerJob,
        captured: true,
        runtimeAuthority: {
          version: 1,
          runtimeId: "openclaw",
          namespace: "opsys-cron-authority-v1",
          payload: { grant: "new-current" },
        },
        explicitlyMutatesToolsAllow: false,
      });
      await store.saveCronJobsStore(storePath, newer, { preserveRuntimeState: true });
      const currentRow = readAuthorityRow(storeKey, jobId);

      staleJob.description = "stale doctor snapshot";
      await store.saveCronJobsStore(storePath, stale, { preserveRuntimeState: true });
      expect(readAuthorityRow(storeKey, jobId)).toEqual(currentRow);
      expect((await store.loadCronStore(storePath)).jobs[0]?.runtimeAuthority).toMatchObject({
        payload: { grant: "new-current" },
      });

      reconcileRuntimeAuthority({
        job: staleJob,
        captured: true,
        runtimeAuthority: {
          version: 1,
          runtimeId: "openclaw",
          namespace: "opsys-cron-authority-v1",
          payload: { grant: "intentional-recapture" },
        },
        explicitlyMutatesToolsAllow: false,
      });
      await store.saveCronJobsStore(storePath, stale, { preserveRuntimeState: true });
      expect(readAuthorityRow(storeKey, jobId)?.authority_json).not.toBe(currentRow?.authority_json);
      expect((await store.loadCronStore(storePath)).jobs[0]?.runtimeAuthority).toMatchObject({
        payload: { grant: "intentional-recapture" },
      });

      const db = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        const parent = db
          .prepare("SELECT job_json FROM cron_jobs WHERE store_key = ? AND job_id = ?")
          .get(storeKey, jobId) as { job_json: string };
        const forged = JSON.parse(parent.job_json) as Record<string, unknown>;
        forged.runtimeAuthorityCiphertextDisposition = "clear";
        db.prepare("UPDATE cron_jobs SET job_json = ? WHERE store_key = ? AND job_id = ?")
          .run(JSON.stringify(forged), storeKey, jobId);
      } finally {
        db.close();
      }
      const loaded = await store.loadCronStore(storePath);
      expect(loaded.jobs[0]?.runtimeAuthorityCiphertextDisposition).toBeUndefined();
      await store.saveCronStore(storePath, loaded);
      expect(readAuthorityRow(storeKey, jobId)?.recovery_required).toBe(0);
      expect((await store.loadCronStore(storePath)).jobs[0]?.runtimeAuthority).toMatchObject({
        payload: { grant: "intentional-recapture" },
      });
      const reloadedParent = new DatabaseSync(resolveOpenClawStateSqlitePath());
      try {
        const parent = reloadedParent
          .prepare("SELECT job_json FROM cron_jobs WHERE store_key = ? AND job_id = ?")
          .get(storeKey, jobId) as { job_json: string };
        expect(JSON.parse(parent.job_json)).not.toHaveProperty("runtimeAuthorityCiphertextDisposition");
      } finally {
        reloadedParent.close();
      }
      const { toPublicCronJob } = await import("../public-job.js");
      const publicJob = toPublicCronJob({
        ...loaded.jobs[0]!,
        runtimeAuthorityCiphertextDisposition: "clear",
      });
      expect(publicJob).not.toHaveProperty("runtimeAuthorityCiphertextDisposition");
    });
  });

  it("rejects a key reached through an alias into the protected config root", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-key-alias-" }, async (state) => {
      const key = randomBytes(32);
      const protectedDir = path.dirname(state.configPath);
      const aliasDir = path.join(os.tmpdir(), `cron-authority-alias-${process.pid}-${Date.now()}`);
      const keyName = `test-key-${process.pid}-${Date.now()}`;
      await fs.symlink(protectedDir, aliasDir, "dir");
      await fs.writeFile(path.join(protectedDir, keyName), key, { mode: 0o600, flag: "wx" });
      const protectedKeyPath = path.join(aliasDir, keyName);
      testKeyPaths.push(path.join(protectedDir, keyName));
      testKeyPaths.push(aliasDir);
      setTestEnvValue("OPENCLAW_CRON_AUTHORITY_KEY_FILE", protectedKeyPath);
      setTestEnvValue(
        "OPENCLAW_CRON_AUTHORITY_KEY_ID",
        `sha256:${createHash("sha256").update(key).digest("hex")}`,
      );

      const store = await importStore();
      await expect(store.saveCronStore(state.path("workspace", "cron", "jobs.json"), makeOpsysStore("key-alias")))
        .rejects.toThrow("OPSYS cron runtime authority is unavailable");
    });
  });

  it("uses the owning package root when Gateway starts from an installed non-Git directory", async () => {
    await withOpenClawTestState({ prefix: "cron-authority-installed-cwd-" }, async (state) => {
      const previousCwd = process.cwd();
      try {
        process.chdir(state.root);
        await installTestKey(state.root);
        const store = await importStore();
        const storePath = state.path("workspace", "cron", "jobs.json");
        await store.saveCronStore(storePath, makeOpsysStore("installed-cwd"));
        expect(
          readAuthorityRow((await import("./key.js")).cronStoreKey(storePath), "installed-cwd")
            ?.authority_json,
        ).toMatch(/^OPSYS_CRON_AUTHORITY_A256GCM_V1\./u);
      } finally {
        process.chdir(previousCwd);
      }
    });
  });
});
