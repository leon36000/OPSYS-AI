/** Covers two retained Core SecretRef targets independently of pruned upstream docs. */
import { describe, expect, it } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { resolveSecretRefValues } from "./resolve.js";
import { collectCoreConfigAssignments } from "./runtime-config-collectors-core.js";
import { applyResolvedAssignments, createResolverContext } from "./runtime-shared.js";
import { getCoreSecretTargetRegistry } from "./target-registry-data.js";

const targetIds = ["cron.webhookToken", "gateway.auth.token"];
function fixture(): OpenClawConfig {
  return {
    gateway: {
      auth: { mode: "token", token: { source: "env", provider: "default", id: "QA_CORE_GATEWAY" } },
    },
    cron: { webhookToken: { source: "env", provider: "default", id: "QA_CORE_CRON" } },
  };
}
function collect(env: NodeJS.ProcessEnv) {
  const sourceConfig = fixture();
  const config = structuredClone(sourceConfig);
  const context = createResolverContext({ sourceConfig, env, manifestRegistry: { plugins: [] } });
  collectCoreConfigAssignments({ config, context, defaults: undefined });
  expect(context.assignments.map((entry) => entry.path).toSorted()).toEqual(targetIds);
  return { sourceConfig, config, context };
}

describe("QA retained Core SecretRef coverage", () => {
  it("admits exactly the fixed nonempty Core target subset", () => {
    const registry = getCoreSecretTargetRegistry();
    expect(registry.length > 0).toBe(true);
    const admitted = registry.filter((entry) => targetIds.includes(entry.id));
    expect(admitted.map((entry) => entry.id).toSorted()).toEqual(targetIds);
    expect(
      admitted.every(
        (entry) => entry.configFile === "openclaw.json" && entry.secretShape === "secret_input",
      ),
    ).toBe(true);
  });
  it("collects and materializes two real Core env assignments", async () => {
    const run = collect({
      QA_CORE_GATEWAY: "qa-fictif-core-gateway",
      QA_CORE_CRON: "qa-fictif-core-cron",
    });
    const resolved = await resolveSecretRefValues(
      run.context.assignments.map((entry) => entry.ref),
      { config: run.sourceConfig, env: run.context.env, cache: run.context.cache },
    );
    expect(resolved.size).toBe(2);
    applyResolvedAssignments({ assignments: run.context.assignments, resolved });
    const materialized =
      run.config.gateway?.auth?.token === "qa-fictif-core-gateway" &&
      run.config.cron?.webhookToken === "qa-fictif-core-cron";
    expect(materialized).toBe(true);
    expect(run.sourceConfig).toEqual(fixture());
  });
  it("refuses missing QA env before applying any assignment", async () => {
    const run = collect({ QA_CORE_CRON: "qa-fictif-core-cron" });
    expect(
      run.context.assignments.find((entry) => entry.path === "gateway.auth.token"),
    ).toMatchObject({ requiredForGateway: true, disposition: "fail-closed" });
    await expect(
      resolveSecretRefValues(
        run.context.assignments.map((entry) => entry.ref),
        { config: run.sourceConfig, env: run.context.env, cache: run.context.cache },
      ),
    ).rejects.toMatchObject({ code: "SECRET_REF_NOT_FOUND" });
    expect(run.config).toEqual(fixture());
  });
});
