import { expect, it } from "vitest";
import { AgentHarnessPreflightError } from "../agents/harness/errors.js";
import { assertCronRuntimeAuthorityCandidate } from "./runtime-authority-admission.js";

const authority = {
  version: 1 as const,
  runtimeId: "codex",
  namespace: "test-capability",
  payload: { marker: "FICTIVE_CAPABILITY_MUST_NOT_APPEAR_IN_ERROR" },
};

it.each([
  {
    name: "recovery blocks a valid matching runtime authority",
    params: {
      authority,
      recoveryRequired: true,
      candidateRuntime: "codex",
      cliExecution: false,
    },
    rejected: true,
  },
  {
    name: "runtime mismatch remains rejected without recovery",
    params: {
      authority,
      candidateRuntime: "other-runtime",
      cliExecution: false,
    },
    rejected: true,
  },
  {
    name: "CLI execution remains rejected with captured authority",
    params: { authority, candidateRuntime: "codex", cliExecution: true },
    rejected: true,
  },
  {
    name: "matching authority passes without recovery",
    params: { authority, candidateRuntime: "codex", cliExecution: false },
    rejected: false,
  },
  {
    name: "legacy candidate without authority remains allowed",
    params: { candidateRuntime: "codex", cliExecution: false },
    rejected: false,
  },
])("$name", ({ params, rejected }) => {
  if (!rejected) {
    expect(() => assertCronRuntimeAuthorityCandidate(params)).not.toThrow();
    return;
  }
  let failure: unknown;
  try {
    assertCronRuntimeAuthorityCandidate(params);
  } catch (error) {
    failure = error;
  }
  expect(failure).toBeInstanceOf(AgentHarnessPreflightError);
  expect((failure as Error).message).not.toContain("FICTIVE_CAPABILITY_MUST_NOT_APPEAR_IN_ERROR");
});
