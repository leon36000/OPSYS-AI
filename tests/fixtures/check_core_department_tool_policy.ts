// Cross-language contract: consume real Python-generated fragments through Core's owners.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { OpenClawConfig } from "../../core/src/config/types.openclaw.js";
import { AgentsSchema } from "../../core/src/config/zod-schema.agents.js";
import { setPluginToolMeta } from "../../core/src/plugins/tool-metadata.js";
import { resolveConversationCapabilityProfile } from "../../core/src/agents/conversation-capability-profile.js";
import { projectConversationToolNames } from "../../core/src/agents/conversation-tool-policy-pipeline.js";
import { applyFinalEffectiveToolPolicy } from "../../core/src/agents/embedded-agent-runner/effective-tool-policy.js";
import { resolveSandboxToolPolicyForAgent } from "../../core/src/agents/sandbox/tool-policy.js";
import type { AnyAgentTool } from "../../core/src/agents/tools/common.js";

type Input = {
  config: OpenClawConfig;
  names: { public: string; internal: string; custom: string; other_custom: string };
};

const input: Input = JSON.parse(readFileSync(process.argv[2], "utf8"));
AgentsSchema.parse(input.config.agents);
const coreNames = ["read", "exec", "message", "sessions_send"];
const names = [
  ...Object.values(input.names),
  "opsys_context_m01-front-office__probe",
  "opsys_runtime_m01-front-office__probe",
];
const results: Array<Record<string, unknown>> = [];

function project(agentId: string, config = input.config) {
  const sandbox = resolveSandboxToolPolicyForAgent(config, agentId);
  const profile = resolveConversationCapabilityProfile({
    config,
    agentId,
    sessionKey: `agent:${agentId}:fictitious-policy-regression`,
    sandboxToolPolicy: sandbox,
  });
  const bundledTools = names.map((name): AnyAgentTool => {
    const tool = {
      name, label: name, description: name,
      parameters: { type: "object" as const, properties: {} },
      execute: async () => { throw new Error("Policy tests must never execute tools"); },
    };
    const separator = name.indexOf("__");
    const server = name.slice(0, separator);
    setPluginToolMeta(tool, {
      pluginId: "bundle-mcp", optional: false,
      mcp: { serverName: server, safeServerName: server, toolName: name.slice(separator + 2), operation: "tool" },
    });
    return tool;
  });
  const filters: Array<Record<string, unknown>> = [];
  const bundled = applyFinalEffectiveToolPolicy({
    bundledTools, config, conversationCapabilityProfile: profile, warn: () => {},
    onFilter: ({ step, before, after }) => filters.push({
      label: step.label, before: before.map((tool) => tool.name), after: after.map((tool) => tool.name),
    }),
  });
  const core = projectConversationToolNames({ capabilityProfile: profile, toolNames: coreNames, warn: () => {} });
  return { tools: [...core, ...bundled.map((tool) => tool.name)].sort(), filters, sandbox };
}

function check(label: string, agentId: string, expected: string[], config = input.config) {
  const actual = project(agentId, config);
  let error: string | undefined;
  try { assert.deepEqual(actual.tools, [...expected].sort()); }
  catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
  results.push({ label, agentId, expected: [...expected].sort(), ...actual, success: error === undefined, error });
}

check("public-own-MCP-only", "m01-front-office", [input.names.public]);
check("internal-Core-and-own-MCP", "m02-revenue-crm", ["read", "exec", "sessions_send", input.names.internal]);
check("custom-exact-tool", "opsys-agent-m03-limite", [input.names.custom]);
check("empty-profile-denies-everything", "opsys-agent-m03-sans-outils", []);
const operatorDenied = structuredClone(input.config);
operatorDenied.tools = { ...operatorDenied.tools, deny: [...(operatorDenied.tools?.deny ?? []), input.names.public] };
check("operator-deny-stays-authoritative", "m01-front-office", [], operatorDenied);
const success = results.every((result) => result.success);
console.log(JSON.stringify({ state: "CORE_POLICY_CONTRACT_ENDED", success, results, tool_executions: 0, model_calls: 0 }));
process.exitCode = success ? 0 : 1;
