import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireOpsysContextTestConfig } from "../../test/helpers/opsys-context-test-config.js";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import { resolveOpsysDir } from "../gateway/opsys-metier-config.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { SESSION_MCP_RUNTIME_MANAGER_KEY } from "./agent-bundle-mcp-runtime-shared.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";

const SESSION = "agent:m02-revenue-crm:webchat:direct:fictif-A";
const TOOL = "opsys_memoire_rechercher";
const ARGUMENTS = { requete: "préférence fictive" };
const tempDirs: string[] = [];
let release: (() => Promise<void>) | undefined;
async function reset() {
  await getSessionMcpRuntimeManagerForTesting().disposeAll();
  delete (globalThis as Record<PropertyKey, unknown>)[SESSION_MCP_RUNTIME_MANAGER_KEY];
}
beforeEach(async () => {
  await reset();
  release = await acquireOpsysContextTestConfig();
});
afterEach(async () => {
  await reset();
  cleanupTempDirs(tempDirs);
  await fs.rm(path.join(resolveOpsysDir(), "memoire-autorites.json"), { force: true });
  await release?.();
});
async function policy(mode = "client_session") {
  await fs.writeFile(
    path.join(resolveOpsysDir(), "memoire-autorites.json"),
    JSON.stringify({
      version: 1,
      departements: { "m02-revenue-crm": mode },
      agents: { "m02-revenue-crm": { departement: "m02-revenue-crm", mode } },
      procedures_globales: ["procedures"],
    }),
    { mode: 0o600 },
  );
}
async function server(root: string, name: string, tool: string, answer: Record<string, unknown>) {
  const script = path.join(root, name + ".mjs");
  const log = path.join(root, name + ".jsonl");
  await fs.writeFile(
    script,
    `import fs from 'node:fs'; import readline from 'node:readline';
    for await (const line of readline.createInterface({input: process.stdin})) {
      const m=JSON.parse(line); let result;
      if(m.method==='initialize') result={protocolVersion:m.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:${JSON.stringify(name)},version:'1'}};
      if(m.method==='tools/list') result={tools:[{name:${JSON.stringify(tool)},inputSchema:{type:'object',additionalProperties:true}}]};
      if(m.method==='tools/call'){fs.appendFileSync(process.env.PROBE_CALLS,JSON.stringify(m.params)+'\\n');result={content:[{type:'text',text:${JSON.stringify(JSON.stringify(answer))}}]};}
      if(result) process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\\n');
    }`,
    { mode: 0o600 },
  );
  return { command: process.execPath, args: [script], env: { PROBE_CALLS: log } };
}
async function setup(
  response = {
    ok: true,
    resultat: {
      ticket: "opaque-fictif-R33",
      expire_le: new Date(Date.now() + 120000).toISOString(),
    },
  },
) {
  const root = makeTempDir(tempDirs, "opsys-memory-wire-fictif-");
  const business = await server(root, "opsys_m2", TOOL, { ok: true, resultat: { resultats: [] } });
  const issuer = await server(
    root,
    "opsys_context_m02-revenue-crm",
    "opsys_contexte_creer_ticket_memoire",
    response,
  );
  const runtime = await getOrCreateSessionMcpRuntime({
    sessionId: "opsys-memory-fictif",
    sessionKey: SESSION,
    workspaceDir: root,
    cfg: {
      plugins: { enabled: false },
      mcp: { servers: { opsys_m2: business, "opsys_context_m02-revenue-crm": issuer } },
    },
  });
  return { root, runtime };
}
async function calls(root: string, name: string): Promise<Record<string, unknown>[]> {
  return (await fs.readFile(path.join(root, name + ".jsonl"), "utf8").catch(() => ""))
    .split("\n")
    .filter(Boolean)
    .map((s) => JSON.parse(s));
}
describe("OPSYS memory authority on native final MCP transport", () => {
  it("replaces caller metadata with the private grant and keeps the final argument snapshot", async () => {
    await policy();
    const { root, runtime } = await setup();
    const result = await withMcpCallMeta(
      { "opsys/memoireLectureTicket": "caller-forged-fictif" },
      () => runtime.callTool("opsys_m2", TOOL, ARGUMENTS),
    );
    const business = await calls(root, "opsys_m2");
    expect(await calls(root, "opsys_context_m02-revenue-crm")).toHaveLength(1);
    expect(business).toHaveLength(1);
    expect(business[0]).toStrictEqual({
      name: TOOL,
      arguments: ARGUMENTS,
      _meta: { "opsys/memoireLectureTicket": "opaque-fictif-R33" },
    });
    expect(JSON.stringify(result)).not.toContain("opaque-fictif-R33");
  });
  it("refuses a missing classification before private issuance or business dispatch", async () => {
    const { root, runtime } = await setup();
    await expect(runtime.callTool("opsys_m2", TOOL, ARGUMENTS)).rejects.toThrow();
    expect(await calls(root, "opsys_m2")).toHaveLength(0);
    expect(await calls(root, "opsys_context_m02-revenue-crm")).toHaveLength(0);
  });
  it("does not replace an issuer refusal with a global read", async () => {
    await policy();
    const { root, runtime } = await setup({ ok: false, resultat: { ticket: "", expire_le: "" } });
    await expect(runtime.callTool("opsys_m2", TOOL, ARGUMENTS)).rejects.toThrow(/read authority/);
    expect(await calls(root, "opsys_m2")).toHaveLength(0);
    expect(await calls(root, "opsys_context_m02-revenue-crm")).toHaveLength(1);
  });
  it("preserves explicitly global department reads and strips any caller ticket", async () => {
    await policy("global");
    const { root, runtime } = await setup();
    await withMcpCallMeta({ "opsys/memoireLectureTicket": "caller-forged-fictif" }, () =>
      runtime.callTool("opsys_m2", TOOL, { ...ARGUMENTS, sujet: "client:B-fictif" }),
    );
    expect(await calls(root, "opsys_context_m02-revenue-crm")).toHaveLength(0);
    expect((await calls(root, "opsys_m2"))[0]).toStrictEqual({
      name: TOOL,
      arguments: { ...ARGUMENTS, sujet: "client:B-fictif" },
    });
  });
  it("keeps memory closed for the authenticated device envelope", async () => {
    await policy();
    const { root, runtime } = await setup();
    await expect(
      withMcpCallMeta(
        {
          "opsys/idempotencyKey": "fictif-R33",
          "opsys/appareil": "fictif-appareil",
          "opsys/horodatageAppareil": "2026-10-02T10:00:00Z",
          "opsys/personne": "fictif-admin",
          "opsys/role": "admin",
        },
        () => runtime.callTool("opsys_m2", TOOL, ARGUMENTS),
      ),
    ).rejects.toThrow(/catalogue is closed/);
    expect(await calls(root, "opsys_m2")).toHaveLength(0);
    expect(await calls(root, "opsys_context_m02-revenue-crm")).toHaveLength(0);
  });
});
