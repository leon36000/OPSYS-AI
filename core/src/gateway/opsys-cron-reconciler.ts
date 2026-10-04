import { createHash, randomBytes } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { resolveCronJobConfigRevision } from "../cron/config-revision.js";
import type { CronServiceContract } from "../cron/service-contract.js";
import type { CronService } from "../cron/service.js";
import type { CronRetirementCapture } from "../cron/store/runtime-retirement-store.js";
import type { CronJob, CronJobCreate } from "../cron/types.js";
import type { OpsysCronPrivateClient } from "./opsys-cron-private-client.js";
import {
  decodeOpsysCronRuntimeDeclaration,
  decodeOpsysCronRuntimeAuthority,
  decodeOpsysCronRuntimeGrant,
  OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE,
  OPSYS_CRON_RUNTIME_AUTHORITY_RUNTIME,
  opsysCronRuntimeDeclarationMatchesJob,
} from "./opsys-cron-runtime-grant.js";

export type OpsysCronHostCronPort = Pick<
  CronServiceContract,
  "list" | "readJob" | "add" | "updateWithPrecondition"
> &
  Pick<
    CronService,
    | "removeWithPrecondition"
    | "listPendingRetirements"
    | "readRetirementProof"
    | "acknowledgeRetirementProof"
  >;
export type OpsysCronPrivateClientPort = Pick<
  OpsysCronPrivateClient,
  "list" | "project" | "prepare" | "acknowledge" | "prepareRetirement" | "acknowledgeRetirement"
>;

export type OpsysCronReconcileResult =
  | { ok: true; changed: number }
  | {
      ok: false;
      reason: "client-unavailable" | "list-incomplete" | "stale-or-invalid" | "recovery-required";
    };

const ALLOWED_STATES = new Set(["a_declarer"]);

/** Drain recoverable DELETEs before the Python intent list, which may already exclude ACKed rows. */
async function drainRetirements(params: {
  cron: OpsysCronHostCronPort;
  client: OpsysCronPrivateClientPort;
  commitGuard: () => void;
  profileId?: string;
}): Promise<OpsysCronReconcileResult> {
  const { cron, client, commitGuard, profileId } = params;
  const pending = await cron.listPendingRetirements(commitGuard, profileId);
  commitGuard();
  if (
    !Number.isSafeInteger(pending.total) ||
    pending.total < pending.items.length ||
    pending.items.length > 16 ||
    pending.items.length !== Math.min(pending.total, 16)
  ) {
    return { ok: false, reason: "list-incomplete" };
  }
  let changed = 0;
  const seen = new Set<string>();
  for (const item of pending.items) {
    if (seen.has(item.receiptId) || (profileId !== undefined && item.profileId !== profileId))
      return { ok: false, reason: "stale-or-invalid" };
    seen.add(item.receiptId);
    const proof = await cron.readRetirementProof(item.receiptId, commitGuard);
    commitGuard();
    if (
      !proof ||
      proof.capture.receiptId !== item.receiptId ||
      proof.capture.profileId !== item.profileId
    )
      return { ok: false, reason: "recovery-required" };
    const grant = decodeOpsysCronRuntimeAuthority(proof.authority, {
      profileId: proof.capture.profileId,
      intentionId: proof.capture.intentionId,
    });
    if (!grant || grant.epoch !== proof.capture.epoch)
      return { ok: false, reason: "recovery-required" };
    const ack = await client.acknowledgeRetirement(grant.profileId, {
      intentionId: grant.intentionId,
      capability: grant.capability,
      epoch: grant.epoch,
      declaration: grant.declaration.wire,
      jobId: proof.jobId,
      nativeRevision: proof.capture.nativeRevision,
      sourceHash: proof.capture.sourceHash,
      receiptId: proof.capture.receiptId,
    });
    commitGuard();
    if (
      ack.intention !== grant.intentionId ||
      ack.receipt_id !== proof.capture.receiptId ||
      ack.source_hash !== proof.capture.sourceHash ||
      ack.epoch !== grant.epoch ||
      ack.job_id !== proof.jobId ||
      ack.etat !== "retiree" ||
      ack.execute !== false
    ) {
      return { ok: false, reason: "stale-or-invalid" };
    }
    await cron.acknowledgeRetirementProof(item.receiptId, proof.capture.sourceHash, commitGuard);
    commitGuard();
    changed += 1;
  }
  return pending.total > pending.items.length
    ? { ok: false, reason: "list-incomplete" }
    : { ok: true, changed };
}

async function retireProjectedJob(params: {
  cron: OpsysCronHostCronPort;
  client: OpsysCronPrivateClientPort;
  profileId: string;
  intentionId: string;
  declarationKey: string;
  commitGuard: () => void;
}): Promise<"absent" | "removed" | "refused"> {
  const { cron, client, profileId, intentionId, declarationKey, commitGuard } = params;
  const matches = (await cron.list({ includeDisabled: true })).filter(
    (job) => job.declarationKey === declarationKey,
  );
  // Absence alone cannot certify DELETE: only a recovered encrypted tombstone can.
  if (matches.length === 0) return "refused";
  if (matches.length !== 1) return "refused";
  let job = await cron.readJob(matches[0]!.id);
  if (!job || job.agentId !== `opsys-agent-${profileId}` || job.declarationKey !== declarationKey)
    return "refused";
  if (job.enabled) {
    const preimage = resolveCronJobConfigRevision(job);
    await cron.updateWithPrecondition(
      job.id,
      { enabled: false },
      (current) => {
        if (!current.enabled || resolveCronJobConfigRevision(current) !== preimage) {
          throw new Error("Cron retirement preimage changed");
        }
      },
      { commitGuard },
    );
    job = await cron.readJob(job.id);
    if (
      !job ||
      job.enabled ||
      job.agentId !== `opsys-agent-${profileId}` ||
      job.declarationKey !== declarationKey
    ) {
      return "refused";
    }
  }
  const authority = decodeOpsysCronRuntimeGrant(job, { profileId, intentionId });
  if (
    !authority ||
    authority.declaration.cron.declarationKey !== declarationKey ||
    authority.declaration.cron.agentId !== `opsys-agent-${profileId}` ||
    !opsysCronRuntimeDeclarationMatchesJob(authority.declaration.cron, job)
  )
    return "refused";
  // This is the current disabled definition. The prior activation ACK remains historical.
  const expectedCronRevision = resolveCronJobConfigRevision(job);
  const preparation = await client.prepareRetirement(profileId, {
    intentionId,
    capability: authority.capability,
    epoch: authority.epoch,
    declaration: authority.declaration.wire,
    jobId: job.id,
    nativeRevision: expectedCronRevision,
  });
  commitGuard();
  if (
    preparation.intention !== intentionId ||
    preparation.epoch !== authority.epoch ||
    preparation.job_id !== job.id ||
    preparation.native_revision !== expectedCronRevision ||
    preparation.declaration_key !== declarationKey ||
    preparation.execute !== false
  )
    return "refused";
  const retirement: CronRetirementCapture = {
    receiptId: preparation.receipt_id,
    sourceHash: preparation.source_hash,
    profileId,
    intentionId,
    epoch: authority.epoch,
    capabilityFingerprint: createHash("sha256")
      .update(Buffer.from(authority.capability, "hex"))
      .digest("hex"),
    declarationHash: preparation.declaration_hash,
    nativeRevision: expectedCronRevision,
  };
  // Recheck the canonical owner immediately before the Cron removal. Python and
  // SQLite do not share a transaction, so the residual cross-owner race remains.
  const live = await client.project(profileId, intentionId);
  commitGuard();
  if (
    live.execute !== false ||
    live.intention !== intentionId ||
    live.etat !== "a_retirer" ||
    live.native !== null ||
    live.declaration_key !== declarationKey
  )
    return "refused";
  const removed = await cron.removeWithPrecondition(
    job.id,
    (current) => {
      const currentAuthority = decodeOpsysCronRuntimeGrant(current, { profileId, intentionId });
      if (
        current.enabled ||
        current.agentId !== `opsys-agent-${profileId}` ||
        current.declarationKey !== declarationKey ||
        resolveCronJobConfigRevision(current) !== expectedCronRevision ||
        !currentAuthority ||
        !isDeepStrictEqual(currentAuthority, authority) ||
        !opsysCronRuntimeDeclarationMatchesJob(authority.declaration.cron, current)
      ) {
        throw new Error("Cron retirement preimage changed");
      }
    },
    { commitGuard, retirement },
  );
  if (!removed.removed || (await cron.readJob(job.id)) !== undefined) return "refused";
  // Recover what the transaction actually stored; never ACK the prepared metadata alone.
  const drained = await drainRetirements({ cron, client, commitGuard, profileId });
  return drained.ok ? "removed" : "refused";
}

async function disarmOwnedJob(
  cron: OpsysCronHostCronPort,
  job: CronJob,
  commitGuard: () => void,
): Promise<void> {
  if (!job.enabled) return;
  const grant = decodeOpsysCronRuntimeGrant(job);
  if (!grant) throw new Error("Cron cleanup authority unavailable");
  const revision = resolveCronJobConfigRevision(job);
  await cron.updateWithPrecondition(
    job.id,
    { enabled: false },
    (current) => {
      if (
        !current.enabled ||
        resolveCronJobConfigRevision(current) !== revision ||
        !isDeepStrictEqual(decodeOpsysCronRuntimeGrant(current), grant)
      ) {
        throw new Error("Cron cleanup definition changed");
      }
    },
    { commitGuard },
  );
  commitGuard();
}

/** Existing system-job convergence calls this even when a profile no longer has an execution binding. */
export async function reconcileOpsysCronRetirements(input: {
  cron: OpsysCronHostCronPort;
  client: OpsysCronPrivateClientPort | undefined;
  configuredProfileIds: ReadonlySet<string>;
  commitGuard: () => void;
}): Promise<OpsysCronReconcileResult> {
  const { cron, client, configuredProfileIds, commitGuard } = input;
  try {
    commitGuard();
    const pending = await cron.listPendingRetirements(commitGuard);
    commitGuard();
    let changed = 0;
    let refusal: OpsysCronReconcileResult | undefined;
    if (pending.total > 0) {
      if (!client) refusal = { ok: false, reason: "client-unavailable" };
      else {
        try {
          const drained = await drainRetirements({ cron, client, commitGuard });
          if (!drained.ok) refusal = drained;
          else changed += drained.changed;
        } catch {
          refusal = { ok: false, reason: "recovery-required" };
        }
      }
    }
    const jobs = await cron.list({ includeDisabled: true });
    commitGuard();
    for (const job of jobs) {
      // Discovery alone is never authority: only the full private runtime grant qualifies.
      const grant = decodeOpsysCronRuntimeGrant(job);
      if (!grant) continue;
      if (!client) {
        await disarmOwnedJob(cron, job, commitGuard);
        refusal = { ok: false, reason: "client-unavailable" };
        continue;
      }
      try {
        const projection = await client.project(grant.profileId, grant.intentionId);
        commitGuard();
        if (projection.intention !== grant.intentionId || projection.execute !== false)
          throw new Error("Cron cleanup source unavailable");
        if (projection.etat === "a_retirer") {
          const retired = await retireProjectedJob({
            cron,
            client,
            profileId: grant.profileId,
            intentionId: grant.intentionId,
            declarationKey: `opsys-profile:${grant.intentionId}`,
            commitGuard,
          });
          if (retired === "removed") changed += 1;
          else refusal = { ok: false, reason: "recovery-required" };
        } else if (!configuredProfileIds.has(grant.profileId)) {
          // Removed/waiting profiles stay disarmed. Cleanup never grants permission to re-enable them.
          await disarmOwnedJob(cron, job, commitGuard);
          refusal = { ok: false, reason: "stale-or-invalid" };
        }
      } catch {
        // A revoked author or an unavailable execution projection cannot leave this private job armed.
        await disarmOwnedJob(cron, job, commitGuard);
        refusal = { ok: false, reason: "recovery-required" };
      }
    }
    return refusal ?? { ok: true, changed };
  } catch {
    return { ok: false, reason: "recovery-required" };
  }
}

/** One profile pass; caller owns the existing serialized system-job convergence and retry. */
export async function reconcileOpsysCronProfile(input: {
  cron: OpsysCronHostCronPort;
  client: OpsysCronPrivateClientPort | undefined;
  profileId: string;
  /** Current config revision; retiring intentions may retain an older live revision. */
  expectedProfileRevision: number;
  allowedProfileIds: ReadonlySet<string>;
  commitGuard: () => void;
  randomBytesImpl?: (size: number) => Buffer;
}): Promise<OpsysCronReconcileResult> {
  const { cron, client, profileId, commitGuard } = input;
  if (!client) return { ok: false, reason: "client-unavailable" };
  if (
    !input.allowedProfileIds.has(profileId) ||
    !Number.isSafeInteger(input.expectedProfileRevision) ||
    input.expectedProfileRevision < 1
  ) {
    return { ok: false, reason: "stale-or-invalid" };
  }
  try {
    commitGuard();
    const recovered = await drainRetirements({ cron, client, commitGuard, profileId });
    if (!recovered.ok) return recovered;
    const listed = await client.list(profileId);
    commitGuard();
    if (
      listed.omis !== 0 ||
      listed.retournes !== listed.items.length ||
      listed.total !== listed.retournes + listed.omis
    ) {
      return { ok: false, reason: "list-incomplete" };
    }
    let changed = recovered.changed;
    for (const item of listed.items) {
      if (!/^[a-f0-9]{64}$/u.test(item.intention_id))
        return { ok: false, reason: "stale-or-invalid" };
      if (item.etat === "a_declarer" && item.revision_profil !== input.expectedProfileRevision) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      const intentionId = item.intention_id;
      const projection = await client.project(profileId, intentionId);
      commitGuard();
      if (projection.execute !== false || projection.intention !== intentionId) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      if (projection.etat === "a_retirer") {
        const declarationKey = `opsys-profile:${intentionId}`;
        if (projection.native !== null || projection.declaration_key !== declarationKey) {
          return { ok: false, reason: "stale-or-invalid" };
        }
        const retired = await retireProjectedJob({
          cron,
          client,
          profileId,
          intentionId,
          declarationKey,
          commitGuard,
        });
        if (retired === "refused") return { ok: false, reason: "stale-or-invalid" };
        if (retired === "removed") changed += 1;
        continue;
      }
      if (projection.native === null) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      if (!ALLOWED_STATES.has(projection.etat)) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      const declaration = decodeOpsysCronRuntimeDeclaration(
        projection.native.params,
        profileId,
        intentionId,
        input.expectedProfileRevision,
      );
      if (!declaration) return { ok: false, reason: "stale-or-invalid" };
      const existing = (await cron.list({ includeDisabled: true })).filter(
        (job) => job.declarationKey === declaration.cron.declarationKey,
      );
      if (existing.length > 1) return { ok: false, reason: "stale-or-invalid" };
      if (existing.length === 1) {
        const job = await cron.readJob(existing[0]!.id);
        if (
          !job ||
          job.declarationKey !== declaration.cron.declarationKey ||
          job.agentId !== declaration.cron.agentId
        ) {
          return { ok: false, reason: "stale-or-invalid" };
        }
        const stored = decodeOpsysCronRuntimeGrant(job, { profileId, intentionId });
        if (
          !stored ||
          !isDeepStrictEqual(stored.declaration.wire, declaration.wire) ||
          !opsysCronRuntimeDeclarationMatchesJob(declaration.cron, job)
        ) {
          return { ok: false, reason: "recovery-required" };
        }
        const enabledTarget = resolveCronJobConfigRevision({ ...job, enabled: true });
        const ack = await client.acknowledge(profileId, {
          intentionId,
          capability: stored.capability,
          epoch: stored.epoch,
          leaseEpoch: stored.leaseEpoch,
          jobId: job.id,
          configRevision: enabledTarget,
          declaration: declaration.wire,
        });
        commitGuard();
        if (ack.execute !== false || ack.etat !== "remise")
          return { ok: false, reason: "stale-or-invalid" };
        if (job.enabled) continue;
        const disabledRevision = resolveCronJobConfigRevision(job);
        await cron.updateWithPrecondition(
          job.id,
          { enabled: true },
          (current) => {
            if (current.enabled || resolveCronJobConfigRevision(current) !== disabledRevision) {
              throw new Error("Cron preimage changed");
            }
          },
          { commitGuard },
        );
        const reread = await cron.readJob(job.id);
        if (!reread || !reread.enabled || resolveCronJobConfigRevision(reread) !== enabledTarget) {
          return { ok: false, reason: "stale-or-invalid" };
        }
        changed += 1;
        continue;
      }
      const capability = (input.randomBytesImpl ?? randomBytes)(32).toString("hex");
      if (!/^[a-f0-9]{64}$/u.test(capability)) return { ok: false, reason: "stale-or-invalid" };
      const fingerprint = createHash("sha256").update(Buffer.from(capability, "hex")).digest("hex");
      const prepared = await client.prepare(profileId, intentionId, {
        capabilityFingerprint: fingerprint,
        declaration: declaration.wire,
        // New human intentions start at owner epoch 0. The owner rejects a
        // retry that would rotate a prepared capability without its secret.
        expectedEpoch: 0,
        expectedNativeRevision: null,
        leaseSeconds: 30,
      });
      commitGuard();
      if (
        prepared.intention !== intentionId ||
        prepared.epoch !== 1 ||
        prepared.lease_epoch < 1 ||
        prepared.etat !== "preparation" ||
        prepared.execute !== false
      ) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      const inputDisabled: CronJobCreate = { ...declaration.cron, enabled: false };
      const added = await cron.add(inputDisabled, {
        enabledExplicit: true,
        commitGuard,
        captureRuntimeAuthority: () => ({
          version: 1,
          runtimeId: OPSYS_CRON_RUNTIME_AUTHORITY_RUNTIME,
          namespace: OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE,
          payload: {
            version: 1,
            profil_id: profileId,
            intention_id: intentionId,
            epoch: prepared.epoch,
            lease_epoch: prepared.lease_epoch,
            capabilite: capability,
            declaration: declaration.wire,
          },
        }),
        matchesExisting: () => {
          // A race after the read must not turn add() into an update and silently
          // replace an existing authority capability.
          throw new Error("declaration appeared during reconciliation");
        },
      });
      const job = await cron.readJob(added.id);
      if (!job || job.enabled) return { ok: false, reason: "stale-or-invalid" };
      const disabledRevision = resolveCronJobConfigRevision(job);
      const enabledTarget = resolveCronJobConfigRevision({ ...job, enabled: true });
      const ack = await client.acknowledge(profileId, {
        intentionId,
        capability,
        epoch: prepared.epoch,
        leaseEpoch: prepared.lease_epoch,
        jobId: job.id,
        configRevision: enabledTarget,
        declaration: declaration.wire,
      });
      commitGuard();
      if (ack.execute !== false || ack.etat !== "remise")
        return { ok: false, reason: "stale-or-invalid" };
      await cron.updateWithPrecondition(
        job.id,
        { enabled: true },
        (current) => {
          if (current.enabled || resolveCronJobConfigRevision(current) !== disabledRevision) {
            throw new Error("Cron preimage changed");
          }
        },
        { commitGuard },
      );
      const reread = await cron.readJob(job.id);
      if (!reread || !reread.enabled || resolveCronJobConfigRevision(reread) !== enabledTarget) {
        return { ok: false, reason: "stale-or-invalid" };
      }
      changed += 1;
    }
    return { ok: true, changed };
  } catch {
    // Do not include bearer, capability, projection or backend error text.
    return { ok: false, reason: "stale-or-invalid" };
  }
}
