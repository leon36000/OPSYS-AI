import { createHash } from "node:crypto";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import { describe, expect, it, vi } from "vitest";
import { resolveCronJobConfigRevision } from "../cron/config-revision.js";
import { normalizeCronRuntimeAuthority } from "../cron/runtime-authority.js";
import { createTrustedCronScheduledToolPolicy } from "../cron/scheduled-tool-policy.js";
import type { CronServiceContract } from "../cron/service-contract.js";
import type { CronService } from "../cron/service.js";
import type { CronRetirementProof } from "../cron/store/runtime-retirement-store.js";
import type { CronJob, CronJobCreate } from "../cron/types.js";
import type { CronDeclaration, OpsysCronPrivateClient } from "./opsys-cron-private-client.js";
import {
  reconcileOpsysCronProfile,
  reconcileOpsysCronRetirements,
  type OpsysCronHostCronPort,
  type OpsysCronPrivateClientPort,
} from "./opsys-cron-reconciler.js";
import { decodeOpsysCronRuntimeGrant } from "./opsys-cron-runtime-grant.js";

const PROFILE = "finance";
const PROFILE_REVISION = 7;
const FUSEAU = "UTC";
const TRIGGER_HASH = createHash("sha256")
  .update(JSON.stringify({ expression: "0 9 * * *", type: "cron" }), "utf8")
  .digest("hex");
// This is the canonical SHA-256 preimage in agents_declencheurs.demander:
// sort_keys JSON of {instance, profil, revision, cron, fuseau}.
const INTENTION_ID = createHash("sha256")
  .update(
    JSON.stringify({
      cron: TRIGGER_HASH,
      fuseau: FUSEAU,
      instance: "fixture-instance",
      profil: PROFILE,
      revision: PROFILE_REVISION,
    }),
    "utf8",
  )
  .digest("hex");
const DECLARATION_KEY = `opsys-profile:${INTENTION_ID}`;
const SECRET = "31".repeat(32);

function isTestRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pythonNativeDeclaration(): CronJobCreate & CronDeclaration {
  // Exact field names and values emitted by agents_declencheurs._declaration.
  return {
    name: `OPSYS profil ${PROFILE}`,
    declarationKey: DECLARATION_KEY,
    agentId: `opsys-agent-${PROFILE}`,
    sessionTarget: "isolated",
    wakeMode: "now",
    schedule: { kind: "cron", expr: "0 9 * * *", tz: FUSEAU },
    payload: {
      kind: "agentTurn",
      message: `Exécute le mandat interne canonique du profil ${PROFILE}, révision ${PROFILE_REVISION}.`,
      timeoutSeconds: 120,
      toolsAllow: ["notes__read"],
    },
    delivery: { mode: "none" },
  };
}

function cronJob(
  input: CronJobCreate,
  id: string,
  enabled = input.enabled === true,
): CronJob & { runtimeAuthority?: unknown } {
  const now = 1_800_000_000_000;
  return {
    id,
    name: input.name,
    declarationKey: input.declarationKey,
    agentId: input.agentId,
    enabled,
    createdAtMs: now,
    updatedAtMs: now,
    schedule: { ...input.schedule, ...(input.schedule.kind === "cron" ? { staggerMs: 0 } : {}) },
    sessionTarget: input.sessionTarget,
    wakeMode: input.wakeMode,
    payload: structuredClone(input.payload),
    delivery: structuredClone(input.delivery),
    state: {},
    scheduledToolPolicy: createTrustedCronScheduledToolPolicy(),
  };
}

function opsysAuthority() {
  return {
    version: 1,
    runtimeId: "openclaw",
    namespace: "opsys-cron-authority-v1",
    payload: {
      version: 1,
      profil_id: PROFILE,
      intention_id: INTENTION_ID,
      epoch: 1,
      lease_epoch: 1,
      capabilite: SECRET,
      declaration: pythonNativeDeclaration(),
    },
  };
}

function makeCronMock(seed: CronJob[] = []) {
  const jobs = new Map<string, CronJob & { runtimeAuthority?: unknown }>(
    seed.map((job) => [job.id, job]),
  );
  const events: string[] = [];
  const proofs = new Map<string, CronRetirementProof>();
  const acknowledged = new Set<string>();
  let nextId = 1;
  const api = {
    list: vi.fn(async (options?: { includeDisabled?: boolean }) =>
      [...jobs.values()].filter((job) => options?.includeDisabled || job.enabled),
    ),
    readJob: vi.fn(async (id: string) => jobs.get(id)),
    add: vi.fn(
      async (input: CronJobCreate, options?: Parameters<CronServiceContract["add"]>[1]) => {
        options?.commitGuard?.();
        const existing = [...jobs.values()].filter(
          (job) =>
            job.declarationKey === input.declarationKey &&
            (options?.matchesExisting?.(job) ?? true),
        );
        if (existing.length > 1) throw new Error("ambiguous declaration key");
        if (existing.length === 1) throw new Error("test mock refuses add-as-update");
        const authority = options?.captureRuntimeAuthority?.();
        if (!authority) throw new Error("private authority capture missing");
        const job = cronJob(input, `cron-${nextId++}`);
        job.runtimeAuthority = authority;
        jobs.set(job.id, job);
        events.push("add-disabled");
        return job;
      },
    ),
    updateWithPrecondition: vi.fn(
      async (
        id: string,
        patch: Parameters<CronServiceContract["updateWithPrecondition"]>[1],
        precondition: Parameters<CronServiceContract["updateWithPrecondition"]>[2],
        options?: Parameters<CronServiceContract["updateWithPrecondition"]>[3],
      ) => {
        const current = jobs.get(id);
        if (!current) throw new Error("missing job");
        await precondition(current, 1_800_000_000_001);
        options?.commitGuard?.();
        events.push(patch.enabled === false ? "disable" : "cas-enable");
        const updated = { ...current, ...patch, updatedAtMs: current.updatedAtMs + 1 };
        jobs.set(id, updated);
        return updated;
      },
    ),
    removeWithPrecondition: vi.fn(
      async (
        id: string,
        precondition: Parameters<CronService["removeWithPrecondition"]>[1],
        options?: Parameters<CronService["removeWithPrecondition"]>[2],
      ) => {
        const current = jobs.get(id);
        if (!current) return { ok: true as const, removed: false };
        await precondition(current, 1_800_000_000_001);
        options?.commitGuard?.();
        if (options?.retirement) {
          const authority = normalizeCronRuntimeAuthority(current.runtimeAuthority);
          if (!authority) throw new Error("missing native authority");
          proofs.set(options.retirement.receiptId, {
            version: 1,
            purpose: "opsys-cron-retirement",
            capture: options.retirement,
            jobId: id,
            removedAtMs: 1_800_000_000_001,
            authority,
          });
        }
        events.push("remove");
        return { ok: true as const, removed: jobs.delete(id) };
      },
    ),
    listPendingRetirements: vi.fn(async (guard: () => void, profileId?: string) => {
      guard();
      const items = [...proofs.values()]
        .filter(
          (proof) =>
            !acknowledged.has(proof.capture.receiptId) &&
            (profileId === undefined || proof.capture.profileId === profileId),
        )
        .map((proof) => ({
          receiptId: proof.capture.receiptId,
          profileId: proof.capture.profileId,
        }));
      return { total: items.length, items: items.slice(0, 16) };
    }),
    readRetirementProof: vi.fn(async (id: string, guard: () => void) => {
      guard();
      const proof = proofs.get(id);
      if (proof && jobs.has(proof.jobId)) throw new Error("job still exists");
      return proof;
    }),
    acknowledgeRetirementProof: vi.fn(async (id: string, hash: string, guard: () => void) => {
      guard();
      if (proofs.get(id)?.capture.sourceHash !== hash) throw new Error("wrong source");
      acknowledged.add(id);
    }),
  } satisfies OpsysCronHostCronPort;
  return { api, jobs, events, proofs, acknowledged };
}

function makeOwner(options?: {
  omitted?: number;
  returned?: number;
  retiring?: boolean;
  changeOnReproject?: boolean;
  failFirstAck?: boolean;
}) {
  let projects = 0;
  let retired = false;
  let ackFailures = options?.failFirstAck === true ? 1 : 0;
  const returned = options?.returned ?? 1;
  const omitted = options?.omitted ?? 0;
  const list = vi.fn(async () =>
    retired
      ? { total: 0, retournes: 0, omis: 0, items: [] }
      : {
          total: returned + omitted,
          retournes: returned,
          omis: omitted,
          items: Array.from({ length: returned }, (_, index) => ({
            intention_id: index === 0 ? INTENTION_ID : String(index).padStart(64, "0"),
            etat: options?.retiring ? ("a_retirer" as const) : ("a_declarer" as const),
            revision_profil: PROFILE_REVISION,
            fuseau: FUSEAU,
          })),
        },
  );
  const project = vi.fn(async (_profile: string, intentionId: string) => {
    const declarationKey = `opsys-profile:${intentionId}`;
    const declaration = { ...pythonNativeDeclaration(), declarationKey };
    projects += 1;
    const changed = options?.changeOnReproject === true && projects > 1;
    const retiring = options?.retiring === true && !changed;
    return retiring
      ? {
          intention: intentionId,
          etat: "a_retirer" as const,
          execute: false as const,
          native: null,
          declaration_key: declarationKey,
          reconciliation: "rechercher_id_natif_puis_retirer" as const,
        }
      : {
          intention: intentionId,
          etat: "a_declarer" as const,
          execute: false as const,
          native: { method: "cron.add" as const, params: declaration },
        };
  });
  const prepare = vi.fn(
    async (
      _profile: string,
      intention: string,
      input: Parameters<OpsysCronPrivateClient["prepare"]>[2],
    ) => ({
      intention,
      epoch: 1,
      lease_epoch: 1,
      etat: "preparation" as const,
      job_id: null,
      config_revision: null,
      execute: false as const,
      lease_until: "2026-10-03T00:00:30+00:00",
      revision_native_attendue: input.expectedNativeRevision,
      native: { method: "cron.add" as const, params: input.declaration },
    }),
  );
  const acknowledge = vi.fn(
    async (_profile: string, input: Parameters<OpsysCronPrivateClient["acknowledge"]>[1]) => {
      if (ackFailures > 0) {
        ackFailures -= 1;
        throw new Error("simulated owner timeout after durable Core capture");
      }
      return {
        intention: input.intentionId,
        epoch: input.epoch,
        lease_epoch: input.leaseEpoch,
        etat: "remise" as const,
        job_id: input.jobId,
        config_revision: input.configRevision,
        execute: false as const,
      };
    },
  );
  const prepareRetirement = vi.fn<OpsysCronPrivateClientPort["prepareRetirement"]>(
    async (_profile, input) => {
      const proof = {
        version: 1 as const,
        intention: input.intentionId,
        source_hash: "c".repeat(64),
        epoch: input.epoch,
        job_id: input.jobId,
        native_revision: input.nativeRevision,
        declaration_hash: createHash("sha256")
          .update(stableStringify(input.declaration))
          .digest("hex"),
        declaration_key: `opsys-profile:${input.intentionId}`,
      };
      return {
        ...proof,
        receipt_id: createHash("sha256").update(stableStringify(proof)).digest("hex"),
        execute: false,
      };
    },
  );
  const acknowledgeRetirement = vi.fn<OpsysCronPrivateClientPort["acknowledgeRetirement"]>(
    async (_profile, input) => {
      retired = true;
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
  );
  const client = {
    list,
    project,
    prepare,
    acknowledge,
    prepareRetirement,
    acknowledgeRetirement,
  } satisfies OpsysCronPrivateClientPort;
  return {
    client,
    list,
    project,
    prepare,
    acknowledge,
    prepareRetirement,
    acknowledgeRetirement,
  };
}

function reconcile(
  cron: OpsysCronHostCronPort,
  client: OpsysCronPrivateClientPort,
  secret = SECRET,
  expectedProfileRevision = PROFILE_REVISION,
) {
  return reconcileOpsysCronProfile({
    cron,
    client,
    profileId: PROFILE,
    expectedProfileRevision,
    allowedProfileIds: new Set([PROFILE]),
    commitGuard: vi.fn(),
    randomBytesImpl: () => Buffer.from(secret, "hex"),
  });
}

describe("OPSYS cron host reconciler", () => {
  it("uses Python's intention-derived key and creates disabled, ACKs target SHA, then CAS-enables", async () => {
    expect(DECLARATION_KEY).toBe(`opsys-profile:${INTENTION_ID}`);
    const cron = makeCronMock();
    const owner = makeOwner();

    const result = await reconcile(cron.api, owner.client);

    expect(result).toEqual({ ok: true, changed: 1 });
    expect(cron.events).toEqual(["add-disabled", "cas-enable"]);
    expect(owner.prepare).toHaveBeenCalledOnce();
    expect(owner.prepare.mock.calls[0]?.[2]).toMatchObject({
      capabilityFingerprint: createHash("sha256").update(Buffer.from(SECRET, "hex")).digest("hex"),
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
      declaration: pythonNativeDeclaration(),
    });
    const stored = [...cron.jobs.values()][0]!;
    expect(stored.enabled).toBe(true);
    const sidecar = stored.runtimeAuthority;
    const sidecarPayload =
      isTestRecord(sidecar) && isTestRecord(sidecar.payload) ? sidecar.payload : {};
    expect(Object.keys(sidecarPayload).toSorted()).toEqual([
      "capabilite",
      "declaration",
      "epoch",
      "intention_id",
      "lease_epoch",
      "profil_id",
      "version",
    ]);
    expect(sidecarPayload).toMatchObject({
      version: 1,
      profil_id: PROFILE,
      intention_id: INTENTION_ID,
      capabilite: SECRET,
      declaration: pythonNativeDeclaration(),
    });
    expect(
      decodeOpsysCronRuntimeGrant(stored, { profileId: PROFILE, intentionId: INTENTION_ID }),
    ).toMatchObject({
      capability: SECRET,
      epoch: 1,
      leaseEpoch: 1,
      profileId: PROFILE,
      intentionId: INTENTION_ID,
      profileRevision: PROFILE_REVISION,
    });
    expect(
      decodeOpsysCronRuntimeGrant(stored, { profileId: "other", intentionId: INTENTION_ID }),
    ).toBeUndefined();
    const ack = owner.acknowledge.mock.calls[0]?.[1];
    expect(ack?.configRevision).toBe(resolveCronJobConfigRevision({ ...stored, enabled: true }));
  });

  it("rejects the obsolete profile-scoped key before preparation or native mutation", async () => {
    const cron = makeCronMock();
    const owner = makeOwner();
    owner.project.mockImplementation(async () => ({
      intention: INTENTION_ID,
      etat: "a_declarer",
      execute: false,
      native: {
        method: "cron.add",
        params: { ...pythonNativeDeclaration(), declarationKey: `opsys-profile:${PROFILE}` },
      },
    }));

    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect(owner.prepare).not.toHaveBeenCalled();
    expect(cron.api.add).not.toHaveBeenCalled();
  });

  it("rejects an a_declarer item from an older profile revision before projection", async () => {
    const cron = makeCronMock();
    const owner = makeOwner();

    expect(await reconcile(cron.api, owner.client, SECRET, PROFILE_REVISION + 1)).toEqual({
      ok: false,
      reason: "stale-or-invalid",
    });
    expect(owner.project).not.toHaveBeenCalled();
    expect(owner.prepare).not.toHaveBeenCalled();
    expect(cron.api.add).not.toHaveBeenCalled();
  });

  it("recovers a durable disabled capture after ACK loss without a second add or capability rotation", async () => {
    const cron = makeCronMock();
    const owner = makeOwner({ failFirstAck: true });
    const randomBytesImpl = vi.fn(() => Buffer.from(SECRET, "hex"));
    const run = () =>
      reconcileOpsysCronProfile({
        cron: cron.api,
        client: owner.client,
        profileId: PROFILE,
        expectedProfileRevision: PROFILE_REVISION,
        allowedProfileIds: new Set([PROFILE]),
        commitGuard: vi.fn(),
        randomBytesImpl,
      });

    expect((await run()).ok).toBe(false);
    expect([...cron.jobs.values()][0]?.enabled).toBe(false);
    expect(cron.events).toEqual(["add-disabled"]);
    expect((await run()).ok).toBe(true);
    expect(cron.events).toEqual(["add-disabled", "cas-enable"]);
    expect(randomBytesImpl).toHaveBeenCalledOnce();
    expect(owner.prepare).toHaveBeenCalledOnce();
    expect(owner.acknowledge).toHaveBeenCalledTimes(2);
    expect(owner.acknowledge.mock.calls[0]?.[1].capability).toBe(SECRET);
    expect(owner.acknowledge.mock.calls[1]?.[1].capability).toBe(SECRET);
  });

  it("does not replay a durable capability after its canonical job config has drifted", async () => {
    const cron = makeCronMock();
    const owner = makeOwner({ failFirstAck: true });
    const run = () => reconcile(cron.api, owner.client);

    expect((await run()).ok).toBe(false);
    const job = [...cron.jobs.values()][0]!;
    cron.jobs.set(job.id, { ...job, description: "changed outside the owner projection" });
    expect(await run()).toEqual({ ok: false, reason: "recovery-required" });
    expect(cron.events).toEqual(["add-disabled"]);
    expect(owner.prepare).toHaveBeenCalledOnce();
    expect(owner.acknowledge).toHaveBeenCalledOnce();
    expect([...cron.jobs.values()][0]?.enabled).toBe(false);
  });

  it("rejects a sidecar outside the exact seven-field positive-epoch schema", async () => {
    for (const corrupt of [
      (payload: Record<string, unknown>) => ({ ...payload, epoch: 0 }),
      (payload: Record<string, unknown>) => ({ ...payload, unexpected: true }),
      (payload: Record<string, unknown>) => ({ ...payload, profil_id: "Finance" }),
    ]) {
      const cron = makeCronMock();
      const owner = makeOwner({ failFirstAck: true });
      expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
      const job = [...cron.jobs.values()][0]!;
      const authority = job.runtimeAuthority;
      if (isTestRecord(authority) && isTestRecord(authority.payload)) {
        const payload = authority.payload;
        job.runtimeAuthority = { ...authority, payload: corrupt(payload) };
      }
      cron.jobs.set(job.id, job);
      expect(await reconcile(cron.api, owner.client)).toEqual({
        ok: false,
        reason: "recovery-required",
      });
      expect(owner.acknowledge).toHaveBeenCalledOnce();
      expect([...cron.jobs.values()][0]?.enabled).toBe(false);
    }
  });

  it("disables by native CAS, revalidates live retirement, then removes the exact intention job", async () => {
    const initial = cronJob({ ...pythonNativeDeclaration(), enabled: true }, "retire-job", true);
    initial.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([initial]);
    const owner = makeOwner({ retiring: true });

    const result = await reconcile(cron.api, owner.client, SECRET, PROFILE_REVISION + 1);

    expect(result).toEqual({ ok: true, changed: 1 });
    expect(cron.events).toEqual(["disable", "remove"]);
    expect(owner.project).toHaveBeenCalledTimes(2);
    expect(cron.jobs.size).toBe(0);
  });

  it("leaves a retired job disabled when the owner source changes before removal", async () => {
    const initial = cronJob({ ...pythonNativeDeclaration(), enabled: true }, "retire-race", true);
    initial.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([initial]);
    const owner = makeOwner({ retiring: true, changeOnReproject: true });

    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect(cron.events).toEqual(["disable"]);
    expect([...cron.jobs.values()][0]?.enabled).toBe(false);
    expect(cron.api.removeWithPrecondition).not.toHaveBeenCalled();
  });

  it("refuses retirement when runtime grant changes during owner revalidation at the same config SHA", async () => {
    const initial = cronJob(
      { ...pythonNativeDeclaration(), enabled: false },
      "retire-grant-race",
      false,
    );
    initial.runtimeAuthority = opsysAuthority();
    const initialRevision = resolveCronJobConfigRevision(initial);
    const cron = makeCronMock([initial]);
    const owner = makeOwner({ retiring: true });
    let projectCount = 0;
    owner.project.mockImplementation(async () => {
      projectCount += 1;
      if (projectCount === 2) {
        const current = cron.jobs.get(initial.id)!;
        const grant = opsysAuthority();
        grant.payload.capabilite = "42".repeat(32);
        cron.jobs.set(initial.id, { ...current, runtimeAuthority: grant });
      }
      return {
        intention: INTENTION_ID,
        etat: "a_retirer",
        execute: false,
        native: null,
        declaration_key: DECLARATION_KEY,
        reconciliation: "rechercher_id_natif_puis_retirer",
      };
    });

    expect(await reconcile(cron.api, owner.client)).toEqual({
      ok: false,
      reason: "stale-or-invalid",
    });
    expect(resolveCronJobConfigRevision(cron.jobs.get(initial.id)!)).toBe(initialRevision);
    expect(cron.api.removeWithPrecondition).toHaveBeenCalledOnce();
    expect(cron.events).toEqual([]);
    expect(cron.jobs.has(initial.id)).toBe(true);
  });

  it("reconciles all sixteen owner intentions without truncating the profile", async () => {
    const cron = makeCronMock();
    const owner = makeOwner({ returned: 16 });

    expect(await reconcile(cron.api, owner.client)).toEqual({ ok: true, changed: 16 });
    expect(owner.project).toHaveBeenCalledTimes(16);
    expect(owner.prepare).toHaveBeenCalledTimes(16);
    expect(owner.acknowledge).toHaveBeenCalledTimes(16);
    expect(cron.api.add).toHaveBeenCalledTimes(16);
    expect(cron.api.updateWithPrecondition).toHaveBeenCalledTimes(16);
    expect(cron.jobs.size).toBe(16);
    expect(new Set([...cron.jobs.values()].map((job) => job.declarationKey)).size).toBe(16);
    expect([...cron.jobs.values()].every((job) => job.enabled)).toBe(true);
    expect(cron.api.removeWithPrecondition).not.toHaveBeenCalled();
  });

  it("still refuses incomplete owner responses and performs no native writes", async () => {
    const cron = makeCronMock();
    const owner = makeOwner({ returned: 10, omitted: 6 });

    expect(await reconcile(cron.api, owner.client)).toEqual({
      ok: false,
      reason: "list-incomplete",
    });
    expect(owner.project).not.toHaveBeenCalled();
    expect(owner.prepare).not.toHaveBeenCalled();
    expect(cron.api.add).not.toHaveBeenCalled();
    expect(cron.api.removeWithPrecondition).not.toHaveBeenCalled();
  });

  it("preserves the disabled preimage if a concurrent config edit wins before the CAS", async () => {
    const cron = makeCronMock();
    const owner = makeOwner();
    owner.acknowledge.mockImplementation(async (_profile, input) => {
      const job = [...cron.jobs.values()][0];
      if (job) cron.jobs.set(job.id, { ...job, description: "concurrent edit" });
      return {
        intention: input.intentionId,
        epoch: input.epoch,
        lease_epoch: input.leaseEpoch,
        etat: "remise" as const,
        job_id: input.jobId,
        config_revision: input.configRevision,
        execute: false as const,
      };
    });

    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect([...cron.jobs.values()][0]?.enabled).toBe(false);
    expect(cron.events).toEqual(["add-disabled"]);
  });
});

// Fictif: true. Port models here are explicit; real SQLite/AES are exercised by the native file.
describe("OPSYS terminal cleanup convergence", () => {
  it("drains a committed DELETE after Python ACK loss before reading terminal intents", async () => {
    const job = cronJob({ ...pythonNativeDeclaration(), enabled: true }, "crash-retirement", true);
    job.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([job]);
    const owner = makeOwner({ retiring: true });
    const acknowledge = owner.acknowledgeRetirement.getMockImplementation();
    if (!acknowledge) throw new Error("cleanup fixture missing");
    owner.acknowledgeRetirement.mockImplementationOnce(async (...args) => {
      await acknowledge(...args); // Simulate committed Python ACK whose HTTP response was lost.
      throw new Error("lost ACK response fictif");
    });
    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect(cron.jobs.size).toBe(0);
    expect(cron.proofs.size).toBe(1);
    expect(cron.acknowledged.size).toBe(0);
    const receiptId = [...cron.proofs.keys()][0]!;
    owner.list.mockImplementation(async () => {
      expect(cron.acknowledged.has(receiptId)).toBe(true);
      return { total: 0, retournes: 0, omis: 0, items: [] };
    });
    expect(await reconcile(cron.api, owner.client)).toEqual({ ok: true, changed: 1 });
    expect(cron.api.removeWithPrecondition).toHaveBeenCalledOnce();
    expect(owner.acknowledgeRetirement).toHaveBeenCalledTimes(2);
    expect(cron.acknowledged.has(receiptId)).toBe(true);
    expect(cron.proofs.size).toBe(1); // History survives the terminal ACK.
  });

  it("retires a source-bound private job even after its execution profile leaves current config", async () => {
    const job = cronJob(
      { ...pythonNativeDeclaration(), enabled: true },
      "removed-profile-retirement",
      true,
    );
    job.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([job]);
    const owner = makeOwner({ retiring: true });
    expect(
      await reconcileOpsysCronRetirements({
        cron: cron.api,
        client: owner.client,
        configuredProfileIds: new Set(),
        commitGuard: () => {},
      }),
    ).toEqual({ ok: true, changed: 1 });
    expect(cron.events).toEqual(["disable", "remove"]);
    expect(owner.prepareRetirement).toHaveBeenCalledOnce();
    expect(owner.acknowledgeRetirement).toHaveBeenCalledOnce();
    expect(owner.list).not.toHaveBeenCalled();
    expect(cron.api.add).not.toHaveBeenCalled();
  });

  it("keeps an execution-revoked or waiting profile disarmed without inventing a terminal source", async () => {
    const job = cronJob({ ...pythonNativeDeclaration(), enabled: true }, "revoked-profile", true);
    job.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([job]);
    const owner = makeOwner();
    owner.project.mockRejectedValue(new Error("former actor lost rights fictif"));
    expect(
      (
        await reconcileOpsysCronRetirements({
          cron: cron.api,
          client: owner.client,
          configuredProfileIds: new Set(),
          commitGuard: () => {},
        })
      ).ok,
    ).toBe(false);
    expect(cron.jobs.get(job.id)?.enabled).toBe(false);
    expect(cron.api.removeWithPrecondition).not.toHaveBeenCalled();
    expect(cron.api.add).not.toHaveBeenCalled();
    expect(owner.acknowledgeRetirement).not.toHaveBeenCalled();
  });

  it("does not treat an absent native job without a tombstone as an ACK of deletion", async () => {
    const cron = makeCronMock();
    const owner = makeOwner({ retiring: true });
    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect(owner.prepareRetirement).not.toHaveBeenCalled();
    expect(owner.acknowledgeRetirement).not.toHaveBeenCalled();
    expect(cron.proofs.size).toBe(0);
  });

  it("refuses a divergent private ACK and leaves the committed native receipt pending", async () => {
    const job = cronJob(
      { ...pythonNativeDeclaration(), enabled: true },
      "bad-ack-retirement",
      true,
    );
    job.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([job]);
    const owner = makeOwner({ retiring: true });
    const acknowledge = owner.acknowledgeRetirement.getMockImplementation();
    if (!acknowledge) throw new Error("cleanup fixture missing");
    owner.acknowledgeRetirement.mockImplementation(async (...args) => ({
      ...(await acknowledge(...args)),
      receipt_id: "d".repeat(64),
    }));
    expect((await reconcile(cron.api, owner.client)).ok).toBe(false);
    expect(cron.jobs.size).toBe(0);
    expect(cron.proofs.size).toBe(1);
    expect(cron.api.acknowledgeRetirementProof).not.toHaveBeenCalled();
  });

  it("leaves recovery pending when current operator is withdrawn after the Python ACK", async () => {
    const job = cronJob(
      { ...pythonNativeDeclaration(), enabled: true },
      "operator-race-retirement",
      true,
    );
    job.runtimeAuthority = opsysAuthority();
    const cron = makeCronMock([job]);
    const owner = makeOwner({ retiring: true });
    let live = true;
    const acknowledge = owner.acknowledgeRetirement.getMockImplementation();
    if (!acknowledge) throw new Error("cleanup fixture missing");
    owner.acknowledgeRetirement.mockImplementationOnce(async (...args) => {
      const reply = await acknowledge(...args);
      live = false;
      return reply;
    });
    expect(
      (
        await reconcileOpsysCronRetirements({
          cron: cron.api,
          client: owner.client,
          configuredProfileIds: new Set(),
          commitGuard: () => {
            if (!live) throw new Error("operator withdrawn");
          },
        })
      ).ok,
    ).toBe(false);
    expect(cron.jobs.size).toBe(0);
    expect(cron.acknowledged.size).toBe(0);
    live = true;
    expect(
      (
        await reconcileOpsysCronRetirements({
          cron: cron.api,
          client: owner.client,
          configuredProfileIds: new Set(),
          commitGuard: () => {
            if (!live) throw new Error("operator withdrawn");
          },
        })
      ).ok,
    ).toBe(true);
    expect(cron.api.removeWithPrecondition).toHaveBeenCalledOnce();
    expect(cron.acknowledged.size).toBe(1);
  });
});
