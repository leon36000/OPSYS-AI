import { describe, expect, it } from "vitest";
import { createMcpServerToolDenyMatcher, isToolAllowedByPolicyName } from "./tool-policy-match.js";

describe("OPSYS private runtime MCP namespace policy", () => {
  it("keeps runtime reservation and reconciliation tools out of model discovery and calls", () => {
    const policy = { deny: ["opsys_runtime_*__*"] };
    const denyServer = createMcpServerToolDenyMatcher(policy.deny);
    for (const name of [
      "opsys_runtime_m03-estimateur__opsys_runtime_reserver",
      "opsys_runtime_m03-estimateur__opsys_runtime_concilier",
      "opsys_runtime_m03-estimateur__opsys_runtime_liberer_avant_dispatch",
      "opsys_runtime_m03-estimateur__opsys_runtime_verifier_outil",
    ]) {
      expect(isToolAllowedByPolicyName(name, policy)).toBe(false);
      expect(denyServer(name.slice(0, name.indexOf("__")))).toBe(true);
    }
    expect(isToolAllowedByPolicyName("opsys_m3__m3_estimer_projet", policy)).toBe(true);
  });
});
