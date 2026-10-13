// Qualification of the existing production MCP runtime, no mocked transport or handler.
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const input = JSON.parse(await readFile(process.argv[2], "utf8"));
const root = process.env.OPSYS_QUALIFICATION_REPO;
if (!root || input.fictif !== true) {
  throw new Error("isolated fictional fixture required");
}
const manager = await import(
  pathToFileURL(`${root}/core/src/agents/agent-bundle-mcp-manager-api.ts`).href
);
const state = await import(pathToFileURL(`${root}/core/src/state/openclaw-state-db.ts`).href);
const agentId = `opsys-agent-${input.profileId}`;
const cfg = {
  plugins: { enabled: false },
  agents: {
    entries: {
      [agentId]: {
        opsysRuntimeAdmission: {
          profileId: input.profileId,
          profileRevision: input.profileRevision,
        },
      },
    },
  },
  mcp: {
    servers: {
      opsys_m8: {
        url: `${input.baseUrl}/mcp/m08-analytics`,
        transport: "streamable-http",
        transportSecurity: { insecureHttpOrigin: new URL(input.baseUrl).origin },
        headers: { Authorization: `Bearer ${input.bearer}` },
        connectionTimeoutMs: 5000,
        requestTimeoutMs: 10000,
      },
      [`opsys_runtime_${input.profileId}`]: {
        url: `${input.baseUrl}/mcp/runtime/${input.profileId}`,
        transport: "streamable-http",
        transportSecurity: { insecureHttpOrigin: new URL(input.baseUrl).origin },
        headers: { Authorization: `Bearer ${input.privateBearer}` },
        connectionTimeoutMs: 5000,
        requestTimeoutMs: 10000,
      },
    },
  },
};
let lease;
try {
  lease = await manager.acquireSessionMcpRuntime({
    sessionId: `verticale-fictive-${input.phase}`,
    sessionKey: `agent:${agentId}:main`,
    workspaceDir: input.workspaceDir,
    cfg,
  });
  if (input.providerMode) {
    const admission = await import(
      pathToFileURL(`${root}/core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts`).href
    );
    const models = await import(
      pathToFileURL(`${root}/core/src/agents/test-helpers/provider-model-fixture.ts`).href
    );
    const usage = await import(
      pathToFileURL(`${root}/core/src/agents/test-helpers/usage-fixtures.ts`).href
    );
    let providerCalls = 0;
    const streamFn = admission.createOpsysRuntimeAdmissionStreamFn({
      config: cfg,
      agentId,
      runId: input.runId,
      getCandidateIndex: () => 0,
      streamFn: async () => {
        providerCalls += 1;
        if (input.providerMode === "unknown") {
          throw new Error("résultat fournisseur fictif inconnu");
        }
        return {
          result: async () => ({
            role: "assistant",
            content: [],
            api: "openai-completions",
            provider: "openai",
            model: "qualification-fictive",
            usage: { ...usage.createZeroUsageFixture(), output: 3, totalTokens: 3 },
            stopReason: "stop",
            timestamp: 1,
          }),
          async *[Symbol.asyncIterator]() {},
        };
      },
    });
    let tokens;
    let refusal;
    try {
      const stream = await streamFn(
        models.makeProviderModelFixture({
          id: "qualification-fictive",
          provider: "openai",
          api: "openai-completions",
          baseUrl: "https://fournisseur-fictif.test/v1",
          contextWindow: 64,
          maxTokens: 16,
        }),
        { messages: [] },
      );
      tokens = (await stream.result()).usage?.totalTokens;
    } catch (error) {
      refusal = String(error);
    }
    console.log(
      `OPSYS_PROOF_JSON:${JSON.stringify({ fictif: true, phase: input.phase, providerCalls, tokens, refusal })}`,
    );
  } else {
    const response = await lease.runtime.callTool("opsys_m8", "m8_lire_mesures_chantier", {
      wct_id: input.wctId,
    });
    if (!response.content?.[0] || response.content[0].type !== "text") {
      throw new Error("textual business envelope required");
    }
    const envelope = JSON.parse(response.content[0].text);
    console.log(
      `OPSYS_PROOF_JSON:${JSON.stringify({ fictif: true, phase: input.phase, envelope, isError: response.isError === true })}`,
    );
  }
} finally {
  try {
    if (lease) {
      await manager.releaseSessionMcpRuntime(lease);
    }
  } finally {
    try {
      await manager.disposeAllSessionMcpRuntimes();
    } finally {
      await state.closeOpenClawStateDatabaseAsync();
    }
  }
}
