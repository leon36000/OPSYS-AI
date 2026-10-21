/** Live, host-only owner validation immediately before each OPSYS provider stream. */
import { isDeepStrictEqual } from "node:util";
import { resolveCronJobConfigRevision } from "../cron/config-revision.js";
import type { CronServiceContract } from "../cron/service-contract.js";
import type { CronJob } from "../cron/types.js";
import type { OpsysCronPrivateClient } from "./opsys-cron-private-client.js";
import {
  decodeOpsysCronRuntimeGrant,
  opsysCronRuntimeDeclarationMatchesJob,
  OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE,
} from "./opsys-cron-runtime-grant.js";

/**
 * Returns undefined for ordinary jobs. Reserved OPSYS authority fails closed without
 * a current configured profile or private owner client. Call once per provider candidate.
 */
export function createOpsysCronLiveAuthorityValidator(params: {
  cron: Pick<CronServiceContract, "readJob">;
  job: CronJob;
  profileId?: string;
  getProfileId?: () => string | undefined;
  profileRevision?: number;
  getProfileRevision?: () => number | undefined;
  getClient: () => OpsysCronPrivateClient | undefined;
}): ((signal: AbortSignal) => Promise<void>) | undefined {
  const initialProfileId = params.profileId;
  const initialProfileRevision = params.profileRevision;
  const currentProfileId = () => (params.getProfileId ? params.getProfileId() : initialProfileId);
  const currentProfileRevision = () =>
    params.getProfileRevision ? params.getProfileRevision() : initialProfileRevision;
  const storedAuthority = Reflect.get(params.job, "runtimeAuthority");
  const reserved =
    Reflect.get(params.job, "runtimeAuthorityRecoveryRequired") === true ||
    params.job.declarationKey?.startsWith("opsys-profile:") === true ||
    (typeof storedAuthority === "object" &&
      storedAuthority !== null &&
      Reflect.get(storedAuthority, "namespace") === OPSYS_CRON_RUNTIME_AUTHORITY_NAMESPACE);
  if (!reserved && !initialProfileId) return undefined;
  if (
    !initialProfileId ||
    !Number.isSafeInteger(initialProfileRevision) ||
    (initialProfileRevision ?? 0) < 1 ||
    params.job.enabled !== true
  ) {
    throw new Error("OPSYS scheduled job is not enabled for its configured profile");
  }
  const initial = decodeOpsysCronRuntimeGrant(params.job, { profileId: initialProfileId });
  if (
    !initial ||
    initial.profileRevision !== initialProfileRevision ||
    !opsysCronRuntimeDeclarationMatchesJob(initial.declaration.cron, params.job)
  ) {
    throw new Error("OPSYS scheduled authority is unavailable or inconsistent");
  }
  const revision = resolveCronJobConfigRevision(params.job);
  if (!revision.startsWith("sha256:")) throw new Error("OPSYS scheduled job revision is invalid");
  return async (signal) => {
    const assertLiveProfile = (): void => {
      if (
        currentProfileId() !== initialProfileId ||
        currentProfileRevision() !== initialProfileRevision
      ) {
        throw new Error("OPSYS runtime profile changed during owner validation");
      }
    };
    signal.throwIfAborted();
    assertLiveProfile();
    const live = await params.cron.readJob(params.job.id);
    signal.throwIfAborted();
    assertLiveProfile();
    if (
      !live ||
      live.enabled !== true ||
      live.id !== params.job.id ||
      resolveCronJobConfigRevision(live) !== revision
    ) {
      throw new Error("OPSYS scheduled job changed before provider dispatch");
    }
    const current = decodeOpsysCronRuntimeGrant(live, { profileId: initialProfileId });
    if (
      !current ||
      current.profileRevision !== initialProfileRevision ||
      !opsysCronRuntimeDeclarationMatchesJob(current.declaration.cron, live) ||
      !isDeepStrictEqual(current, initial)
    ) {
      throw new Error("OPSYS scheduled authority changed before provider dispatch");
    }
    const client = params.getClient();
    if (!client) throw new Error("OPSYS cron owner is unavailable");
    await client.validate(
      initialProfileId,
      {
        intentionId: current.intentionId,
        capability: current.capability,
        epoch: current.epoch,
        jobId: live.id,
        configRevision: revision,
        declaration: current.declaration.wire,
      },
      { signal },
    );
    signal.throwIfAborted();
    assertLiveProfile();
    if (params.getClient() !== client) {
      throw new Error("OPSYS runtime authority was withdrawn during owner validation");
    }
    const afterValidation = await params.cron.readJob(params.job.id);
    signal.throwIfAborted();
    assertLiveProfile();
    if (
      params.getClient() !== client ||
      !afterValidation ||
      afterValidation.enabled !== true ||
      afterValidation.id !== params.job.id ||
      resolveCronJobConfigRevision(afterValidation) !== revision
    ) {
      throw new Error("OPSYS scheduled job changed during owner validation");
    }
    const after = decodeOpsysCronRuntimeGrant(afterValidation, { profileId: initialProfileId });
    if (
      !after ||
      after.profileRevision !== initialProfileRevision ||
      !opsysCronRuntimeDeclarationMatchesJob(after.declaration.cron, afterValidation) ||
      !isDeepStrictEqual(after, initial)
    ) {
      throw new Error("OPSYS scheduled authority changed during owner validation");
    }
  };
}
