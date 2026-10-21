/**
 * OPSYS device door to a department MCP server (PLAN T1.4-c6, docs/architecture/MOBILE.md "Nom d'un
 * outil de l'app au moteur"). Verified over REAL stdio JSON-RPC child processes, the transport the
 * OPSYS department servers use, like `agent-bundle-mcp-runtime.mcp-call-meta.test.ts`: the
 * assertions are on what the servers actually receive and on which servers were ever started.
 *
 * Two fake department servers, `opsys_m2` and `opsys_m4`, both list a tool named `m4_pointer` (the
 * collision a mistake or an attacker would need); each writes a marker file when it starts. The
 * bare name must reach `opsys_m4` and only `opsys_m4`: `opsys_m2` must never even start.
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { withMcpCallMeta } from "./mcp-call-meta.js";
import { readOpsysEnvelope, resolveOpsysDeviceMcpTarget } from "./opsys-device-mcp-target.js";

const tempDirs: string[] = [];

afterEach(() => {
  cleanupTempDirs(tempDirs);
});

/**
 * A minimal stdio MCP server standing in for a department. `tools/call` answers, in one text block,
 * an OPSYS envelope naming the server that answered, the raw tool name it received, its arguments
 * and the `_meta` it saw on the wire (`mode: "not-json"` answers plain text; `mode: "exit-on-list"`
 * dies on `tools/list`, an outage).
 */
function writeDepartmentServer(dir: string): string {
  const serverPath = path.join(dir, "department-server.mjs");
  fs.writeFileSync(
    serverPath,
    `
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
const [label, markerDir, toolNamesJson, mode] = process.argv.slice(2);
fs.writeFileSync(path.join(markerDir, "started-" + label), "1");
const toolNames = JSON.parse(toolNamesJson);
function send(message) {
  process.stdout.write(JSON.stringify(message) + "\\n");
}
async function handle(message) {
  if (message.method === "initialize") {
    send({ jsonrpc: "2.0", id: message.id, result: { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "opsys-" + label, version: "1" } } });
  } else if (message.method === "tools/list") {
    if (mode === "exit-on-list") process.exit(1);
    send({ jsonrpc: "2.0", id: message.id, result: { tools: toolNames.map((name) => ({ name, inputSchema: { type: "object" } })) } });
  } else if (message.method === "tools/call") {
    const envelope = { ok: true, resultat: { serveur: label, outil: message.params.name, args: message.params.arguments ?? {}, meta: message.params._meta ?? null }, rejoue: false };
    const text = mode === "not-json" ? "pas du JSON" : JSON.stringify(envelope);
    send({ jsonrpc: "2.0", id: message.id, result: { content: [{ type: "text", text }] } });
  }
}
for await (const line of readline.createInterface({ input: process.stdin })) void handle(JSON.parse(line));
`,
  );
  return serverPath;
}

type Department = { label: string; tools: string[]; mode?: string };

function setup(departments: Record<string, Department>) {
  const dir = makeTempDir(tempDirs, "opsys-device-mcp-target-");
  const markerDir = makeTempDir(tempDirs, "opsys-device-mcp-markers-");
  const serverPath = writeDepartmentServer(dir);
  const cfg: OpenClawConfig = {
    plugins: { enabled: false },
    mcp: {
      servers: Object.fromEntries(
        Object.entries(departments).map(([serverName, department]) => [
          serverName,
          {
            command: process.execPath,
            args: [
              serverPath,
              department.label,
              markerDir,
              JSON.stringify(department.tools),
              department.mode ?? "ok",
            ],
          },
        ]),
      ),
    },
  };
  return {
    cfg,
    workspaceDir: makeTempDir(tempDirs, "opsys-device-mcp-workspace-"),
    started: (label: string) => fs.existsSync(path.join(markerDir, `started-${label}`)),
  };
}

describe("resolveOpsysDeviceMcpTarget", () => {
  it("calls the BARE tool name on the pinned server only, with the ambient _meta, and returns the OPSYS envelope", async () => {
    const env = setup({
      opsys_m2: { label: "m2", tools: ["m4_pointer", "m2_seul"] },
      opsys_m4: { label: "m4", tools: ["m4_pointer", "m4_lister_interventions"] },
    });
    const meta = {
      "opsys/idempotencyKey": "mut-1",
      "opsys/appareil": "tel-employe-42",
      "opsys/horodatageAppareil": "2026-10-01T04:00:00.000Z",
      "opsys/personne": "jdupont",
      "opsys/role": "employee",
    };

    const resolution = await resolveOpsysDeviceMcpTarget({
      cfg: env.cfg,
      workspaceDir: env.workspaceDir,
      serverName: "opsys_m4",
      toolName: "m4_pointer",
    });

    expect(resolution.kind).toBe("resolved");
    if (resolution.kind !== "resolved") {
      return;
    }
    try {
      const envelope = await withMcpCallMeta(meta, () =>
        resolution.target.call({ intervention_id: "int-1" }),
      );

      // The server that answered is opsys_m4, under the raw tool name, with the _meta on the wire.
      expect(envelope).toEqual({
        ok: true,
        resultat: {
          serveur: "m4",
          outil: "m4_pointer",
          args: { intervention_id: "int-1" },
          meta,
        },
        rejoue: false,
      });
    } finally {
      await resolution.target.dispose();
    }
    expect(env.started("m4")).toBe(true);
    // The other department's server, which lists the same tool name, was never even started.
    expect(env.started("m2")).toBe(false);
  });

  it("does not find a tool that only ANOTHER department server lists", async () => {
    const env = setup({
      opsys_m2: { label: "m2", tools: ["m2_seul"] },
      opsys_m4: { label: "m4", tools: ["m4_pointer"] },
    });

    const resolution = await resolveOpsysDeviceMcpTarget({
      cfg: env.cfg,
      workspaceDir: env.workspaceDir,
      serverName: "opsys_m4",
      toolName: "m2_seul",
    });

    expect(resolution).toEqual({ kind: "not_found" });
    expect(env.started("m2")).toBe(false);
  });

  it("reports a server that is not configured as not found", async () => {
    const env = setup({ opsys_m4: { label: "m4", tools: ["m4_pointer"] } });

    const resolution = await resolveOpsysDeviceMcpTarget({
      cfg: env.cfg,
      workspaceDir: env.workspaceDir,
      serverName: "opsys_m9",
      toolName: "m4_pointer",
    });

    expect(resolution).toEqual({ kind: "not_found" });
    expect(env.started("m4")).toBe(false);
  });

  it("reports a server that cannot answer as unavailable (retryable), not as a missing tool", async () => {
    const env = setup({ opsys_m4: { label: "m4", tools: ["m4_pointer"], mode: "exit-on-list" } });

    const resolution = await resolveOpsysDeviceMcpTarget({
      cfg: env.cfg,
      workspaceDir: env.workspaceDir,
      serverName: "opsys_m4",
      toolName: "m4_pointer",
    });

    expect(resolution).toEqual({ kind: "unavailable" });
  });

  it("rejects an answer that is not an OPSYS envelope instead of inventing a verdict", async () => {
    const env = setup({ opsys_m4: { label: "m4", tools: ["m4_pointer"], mode: "not-json" } });

    const resolution = await resolveOpsysDeviceMcpTarget({
      cfg: env.cfg,
      workspaceDir: env.workspaceDir,
      serverName: "opsys_m4",
      toolName: "m4_pointer",
    });

    expect(resolution.kind).toBe("resolved");
    if (resolution.kind !== "resolved") {
      return;
    }
    try {
      await expect(resolution.target.call({})).rejects.toThrow("not JSON");
    } finally {
      await resolution.target.dispose();
    }
  });
});

describe("readOpsysEnvelope", () => {
  const text = (value: string) => ({ content: [{ type: "text", text: value }] });

  it("reads the envelope out of the single text block", () => {
    expect(readOpsysEnvelope(text('{"ok":true,"resultat":{"a":1},"rejoue":false}'))).toEqual({
      ok: true,
      resultat: { a: 1 },
      rejoue: false,
    });
  });

  it("reads a refusal envelope like any other: the verdict is the server's, not the core's", () => {
    expect(readOpsysEnvelope(text('{"ok":false,"erreur":"refus_metier","details":"x"}'))).toEqual({
      ok: false,
      erreur: "refus_metier",
      details: "x",
    });
  });

  it.each([
    ["no content", {}],
    ["an empty content list", { content: [] }],
    ["two blocks", { content: [{ type: "text", text: "{}" }, { type: "text", text: "{}" }] }],
    ["an image block", { content: [{ type: "image", data: "AA==", mimeType: "image/png" }] }],
    ["text that is not JSON", text("pas du JSON")],
    ["a JSON array", text('[{"ok":true}]')],
    ["a JSON string", text('"ok"')],
    ["an object without a boolean ok", text('{"resultat":{}}')],
    ["an object whose ok is a string", text('{"ok":"true"}')],
  ])("refuses %s", (_label, result) => {
    expect(() => readOpsysEnvelope(result)).toThrow("OPSYS department server");
  });
});
