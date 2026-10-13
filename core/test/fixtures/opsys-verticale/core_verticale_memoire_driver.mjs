// Real production Core MCP transport; only isolated fictional input is accepted.
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
let lease;
try {
  lease = await manager.acquireSessionMcpRuntime({
    sessionId: `memoire-fictive-${input.phase}`,
    sessionKey: `agent:${agentId}:main`,
    workspaceDir: input.workspaceDir,
    cfg: {
      plugins: { enabled: false },
      agents: {
        entries: {
          [agentId]: { opsysRuntimeAdmission: { profileId: input.profileId, profileRevision: 2 } },
        },
      },
      mcp: {
        servers: {
          [input.serverName]: {
            url: input.url,
            transport: "streamable-http",
            transportSecurity: { insecureHttpOrigin: new URL(input.url).origin },
            headers: { Authorization: `Bearer ${input.bearer}` },
            connectionTimeoutMs: 5000,
            requestTimeoutMs: 10000,
          },
        },
      },
    },
  });
  if (input.catalog) {
    const catalog = await lease.runtime.listTools(input.serverName);
    console.log(
      `OPSYS_PROOF_JSON:${JSON.stringify({ fictif: true, phase: input.phase, tools: catalog.tools.map((tool) => tool.name) })}`,
    );
  } else {
    const result = await lease.runtime.callTool(input.serverName, input.tool, input.args);
    if (!result.content?.[0] || result.content[0].type !== "text") {
      throw new Error("textual memory envelope required");
    }
    console.log(
      `OPSYS_PROOF_JSON:${JSON.stringify({ fictif: true, phase: input.phase, envelope: JSON.parse(result.content[0].text), isError: result.isError === true })}`,
    );
  }
} catch (error) {
  console.log(
    `OPSYS_PROOF_JSON:${JSON.stringify({ fictif: true, phase: input.phase, exception: String(error) })}`,
  );
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
