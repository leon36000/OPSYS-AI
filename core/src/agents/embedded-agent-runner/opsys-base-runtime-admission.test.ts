import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { makeProviderModelFixture } from "../test-helpers/provider-model-fixture.js";
import {
  createOpsysRuntimeAdmissionStreamFn,
  opsysRuntimeCompactionRefusal,
  requiresOpsysRuntimeAdmission,
} from "./opsys-runtime-admission.js";

const legacy: OpenClawConfig = {
  agents: {
    entries: {
      "m02-revenue-crm": { opsysIsolation: { exec: "sandbox-required" } },
      "generic-sandbox": { opsysIsolation: { exec: "sandbox-required" } },
    },
  },
};

describe("OPSYS department admission migration", () => {
  it("requires admission for an already exported department before it is reprovisioned", () => {
    expect(requiresOpsysRuntimeAdmission(legacy, "m02-revenue-crm")).toBe(true);
    expect(opsysRuntimeCompactionRefusal(legacy, "m02-revenue-crm")).toContain(
      "cannot use generic compaction",
    );
    expect(requiresOpsysRuntimeAdmission(legacy, "generic-sandbox")).toBe(false);
    expect(requiresOpsysRuntimeAdmission(undefined, "m02-revenue-crm")).toBe(false);
  });

  it("refuses a missing durable binding before the provider is dispatched", async () => {
    const provider = vi.fn<StreamFn>();
    const guarded = createOpsysRuntimeAdmissionStreamFn({
      config: legacy,
      agentId: "m02-revenue-crm",
      runId: "qa-department-migration",
      getCandidateIndex: () => 0,
      streamFn: provider,
    });
    const model = makeProviderModelFixture({
      id: "qa-no-provider",
      provider: "openai",
      api: "openai-completions",
      baseUrl: "https://qa.invalid",
      contextWindow: 64,
      maxTokens: 16,
    });
    await expect(guarded(model, { messages: [] })).rejects.toThrow(
      "OPSYS runtime admission is required but missing for agent m02-revenue-crm",
    );
    expect(provider).not.toHaveBeenCalled();
  });
});
