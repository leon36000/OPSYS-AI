import { AgentHarnessPreflightError } from "../agents/harness/errors.js";
import type { CronRuntimeAuthority } from "./runtime-authority.js";

/** Rejects a candidate before provider dispatch when private cron authority needs recovery. */
export function assertCronRuntimeAuthorityCandidate(params: {
  authority?: CronRuntimeAuthority;
  recoveryRequired?: boolean;
  candidateRuntime: string;
  cliExecution: boolean;
}): void {
  if (params.recoveryRequired) {
    throw new AgentHarnessPreflightError(
      "This automation's private runtime authority is absent or invalid and must be restored or explicitly replaced before it can run.",
    );
  }
  const authority = params.authority;
  if (!authority) {
    return;
  }
  if (params.candidateRuntime !== authority.runtimeId || params.cliExecution) {
    throw new AgentHarnessPreflightError(
      `This automation carries ${authority.namespace} authority captured for the ${authority.runtimeId} runtime, but the selected execution runtime is ${params.candidateRuntime}. Restore that runtime and auth profile, or explicitly replace the automation's toolsAllow cap from an authenticated creator turn.`,
    );
  }
}
