import fs from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";

const hooks = vi.hoisted(() => ({
  connected: undefined as (() => void) | undefined,
  disposed: undefined as (() => void) | undefined,
  cleanup: "closed" as "closed" | "uncertain" | "throw",
  closed: 0,
  pids: [] as number[],
}));
// Only the lifecycle outcome is controllable; connection, wire and child closure stay real.
vi.mock("../agents/mcp-client-lifecycle.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../agents/mcp-client-lifecycle.js")>();
  return {
    ...actual,
    connectMcpClient: async (...args: Parameters<typeof actual.connectMcpClient>) => {
      await actual.connectMcpClient(...args);
      const transport = args[0].transport;
      if ("pid" in transport && typeof transport.pid === "number") {
        hooks.pids.push(transport.pid);
      }
      hooks.connected?.();
    },
    disposeMcpClient: async (...args: Parameters<typeof actual.disposeMcpClient>) => {
      const status = await actual.disposeMcpClient(...args);
      hooks.disposed?.();
      if (status === "closed") {
        hooks.closed++;
      }
      if (hooks.cleanup === "throw") {
        throw new Error("fictif-private-cleanup-error");
      }
      return hooks.cleanup === "uncertain" ? "uncertain" : status;
    },
  };
});
import { readOpsysM9HistoryConfirmation } from "./opsys-contexte-historique-m9.js";

const dirs: string[] = [];
beforeEach(() => {
  hooks.connected = undefined;
  hooks.disposed = undefined;
  hooks.cleanup = "closed";
  hooks.closed = 0;
  hooks.pids = [];
});
afterEach(() => cleanupTempDirs(dirs));

async function fixture(
  text = '{"fictif":true}',
  multipart = false,
  isError?: boolean,
  serverName = "opsys_runtime_fictif",
) {
  const dir = makeTempDir(dirs, "opsys-mcp-guarded-");
  const script = path.join(dir, "server.mjs");
  const journal = path.join(dir, "wire.jsonl");
  await fs.writeFile(journal, "");
  await fs.writeFile(
    script,
    `
import readline from "node:readline";
import fs from "node:fs";
const journal = ${JSON.stringify(journal)};
const text = ${JSON.stringify(text)};
for await (const line of readline.createInterface({ input: process.stdin })) {
  const m = JSON.parse(line);
  fs.appendFileSync(journal, JSON.stringify(m) + "\\n");
  let result;
  if (m.method === "initialize") result = { protocolVersion:m.params.protocolVersion, capabilities:{tools:{}}, serverInfo:{name:"fictif",version:"1"} };
  if (m.method === "tools/call") result = { content: ${multipart ? '[{type:"text",text:text.slice(0,1)},{type:"text",text:text.slice(1)}]' : '[{type:"text",text}]'}${isError === undefined ? "" : `, isError: ${JSON.stringify(isError)}`} };
  if (result) process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:m.id,result}) + "\\n");
}
`,
  );
  const config: OpenClawConfig = {
    plugins: { enabled: false },
    mcp: {
      servers: {
        [serverName]: { command: process.execPath, args: [script] },
      },
    },
  };
  return {
    config,
    wire: async () =>
      (await fs.readFile(journal, "utf8"))
        .split("\n")
        .filter(Boolean)
        .map((s) => JSON.parse(s)),
  };
}

// Fictional retained references only. In particular, Core does not yet issue closing bindings.
function expectedReference() {
  return {
    contextServerName: "opsys_runtime_fictif",
    agentId: "m09-fictif",
    sessionKey: "agent:m09-fictif:fictif",
    affaireId: "affaire-fictive-1",
    ticketHash: "a".repeat(64),
    nativeInstanceId: "00000000-0000-4000-8000-000000000007",
    requestId: "0123456789ab",
    toolName: "m9_ouvrir_suivi_decision",
  };
}

function confirmedEnvelope() {
  return {
    fictif: true,
    ok: true,
    resultat: {
      schema: 1,
      confirme: true,
      instance_id: "00000000-0000-4000-8000-000000000007",
      demande_id: "0123456789ab",
      outil: "m9_ouvrir_suivi_decision",
    },
  };
}

function readerParams(f: Awaited<ReturnType<typeof fixture>>, expected = expectedReference()) {
  return {
    config: f.config,
    expected,
    timeoutMs: 5000,
    signal: new AbortController().signal,
    assertCurrent: () => {},
  };
}

function assertClosedChild() {
  expect(hooks.closed).toBe(1);
  expect(hooks.pids).toHaveLength(1);
  for (const pid of hooks.pids) {
    expect(() => process.kill(pid, 0)).toThrow();
  }
}

describe("private M9 historical confirmation reader", () => {
  // Break: sending a business RPC or omitting/cross-wiring one retained reference.
  it("reads the exact opening reference once and awaits real child closure", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).resolves.toBe(true);
    const calls = (await f.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params).toEqual({
      name: "opsys_contexte_lire_succes_m9",
      arguments: {
        agent_id: "m09-fictif",
        cle_session: "agent:m09-fictif:fictif",
        affaire_id: "affaire-fictive-1",
        empreinte_ticket: "a".repeat(64),
        demande_id: "0123456789ab",
        outil: "m9_ouvrir_suivi_decision",
      },
    });
    assertClosedChild();
  });

  // Symphony842 oracle: identical logical IDs cannot distinguish a substituted configured route.
  it("reads only the retained alternative context server when another can return identical IDs", async () => {
    const a = await fixture(JSON.stringify(confirmedEnvelope()));
    const b = await fixture(
      JSON.stringify(confirmedEnvelope()),
      false,
      undefined,
      "opsys_runtime_alternatif",
    );
    const expected = { ...expectedReference(), contextServerName: "opsys_runtime_alternatif" };
    const config: OpenClawConfig = {
      ...a.config,
      mcp: {
        ...a.config.mcp,
        servers: { ...a.config.mcp?.servers, ...b.config.mcp?.servers },
      },
    };
    await expect(
      readOpsysM9HistoryConfirmation({ ...readerParams(b, expected), config }),
    ).resolves.toBe(true);
    expect((await a.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    const calls = (await b.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params).toEqual({
      name: "opsys_contexte_lire_succes_m9",
      arguments: {
        agent_id: "m09-fictif",
        cle_session: "agent:m09-fictif:fictif",
        affaire_id: "affaire-fictive-1",
        empreinte_ticket: "a".repeat(64),
        demande_id: "0123456789ab",
        outil: "m9_ouvrir_suivi_decision",
      },
    });
    assertClosedChild();
  });

  // Fixture scope only: this is not evidence that Core produces closing ticket metadata.
  it("recognizes a closing confirmation under a synthetic retained closing tuple", async () => {
    const expected = { ...expectedReference(), toolName: "m9_clore_suivi_decision" };
    const envelope = confirmedEnvelope();
    envelope.resultat.outil = "m9_clore_suivi_decision";
    const f = await fixture(JSON.stringify(envelope));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f, expected))).resolves.toBe(true);
    const calls = (await f.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params.arguments.outil).toBe("m9_clore_suivi_decision");
    assertClosedChild();
  });

  // Break: treating an opening confirmation with deliberately aliased IDs as a closing result.
  it("refuses an opening confirmation for a synthetic closing expectation", async () => {
    const expected = { ...expectedReference(), toolName: "m9_clore_suivi_decision" };
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f, expected))).rejects.toThrow(
      "OPSYS M9 history service returned an invalid confirmation",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  // Break: truthiness or a terminal-refusal fallback converts Native's uncertainty into success.
  it("keeps an exact false confirmation unresolved", async () => {
    const envelope = confirmedEnvelope();
    envelope.resultat.confirme = false;
    const f = await fixture(JSON.stringify(envelope));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).resolves.toBe(false);
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  it.each([
    [
      "schema",
      { ...confirmedEnvelope(), resultat: { ...confirmedEnvelope().resultat, schema: 2 } },
    ],
    [
      "instance",
      {
        ...confirmedEnvelope(),
        resultat: {
          ...confirmedEnvelope().resultat,
          instance_id: "00000000-0000-4000-8000-000000000008",
        },
      },
    ],
    [
      "request",
      {
        ...confirmedEnvelope(),
        resultat: { ...confirmedEnvelope().resultat, demande_id: "abcdef012345" },
      },
    ],
    [
      "tool",
      {
        ...confirmedEnvelope(),
        resultat: { ...confirmedEnvelope().resultat, outil: "m9_clore_suivi_decision" },
      },
    ],
    [
      "boolean",
      { ...confirmedEnvelope(), resultat: { ...confirmedEnvelope().resultat, confirme: "true" } },
    ],
    ["outer refusal", { ...confirmedEnvelope(), ok: false }],
    ["missing result", { ok: true }],
    ["non-object result", { ok: true, resultat: true }],
  ])("refuses a nonconcordant %s without accepting its confirmation", async (_label, envelope) => {
    const f = await fixture(JSON.stringify(envelope));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).rejects.toThrow(
      "OPSYS M9 history service returned an invalid confirmation",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  // Break: consulting Native before validating the retained correlation reference.
  it.each([
    ["ticket", { ...expectedReference(), ticketHash: "A".repeat(64) }],
    ["ticket trailing newline", { ...expectedReference(), ticketHash: "a".repeat(64) + "\n" }],
    [
      "instance trailing newline",
      { ...expectedReference(), nativeInstanceId: expectedReference().nativeInstanceId + "\n" },
    ],
    ["request trailing newline", { ...expectedReference(), requestId: "0123456789ab\n" }],
    ["instance", { ...expectedReference(), nativeInstanceId: "not-a-uuid" }],
    ["request", { ...expectedReference(), requestId: "not-a-request" }],
    ["tool", { ...expectedReference(), toolName: "m9_outil_fictif_non_admis" }],
    ["session", { ...expectedReference(), sessionKey: "agent:m08-fictif:fictif" }],
    ["context server", { ...expectedReference(), contextServerName: "" }],
  ])("refuses an invalid retained %s before connecting", async (_label, expected) => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f, expected))).rejects.toThrow(
      "OPSYS M9 history reference is invalid",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    expect(hooks.pids).toHaveLength(0);
    expect(hooks.closed).toBe(0);
  });

  // Symphony841 oracle: response-only tests cannot detect this one-field request splice.
  it("sends the original ticket hash when the caller mutates it during connection", async () => {
    const expected = expectedReference();
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    hooks.connected = () => {
      expected.ticketHash = "b".repeat(64);
    };
    await expect(readOpsysM9HistoryConfirmation(readerParams(f, expected))).resolves.toBe(true);
    const calls = (await f.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params.arguments.empreinte_ticket).toBe("a".repeat(64));
    assertClosedChild();
  });

  // Break: capturing request args but comparing a response against the later mutable reference.
  it("compares the reply with the original request id after caller mutation", async () => {
    const expected = expectedReference();
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    hooks.connected = () => {
      expected.requestId = "abcdef012345";
    };
    await expect(readOpsysM9HistoryConfirmation(readerParams(f, expected))).resolves.toBe(true);
    const calls = (await f.wire()).filter((m) => m.method === "tools/call");
    expect(calls).toHaveLength(1);
    expect(calls[0].params.arguments.demande_id).toBe("0123456789ab");
    assertClosedChild();
  });

  it("refuses a current-owner revocation after connection before any read RPC", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    let current = true;
    hooks.connected = () => {
      current = false;
    };
    await expect(
      readOpsysM9HistoryConfirmation({
        ...readerParams(f),
        assertCurrent: () => {
          if (!current) throw new Error("fictif-owner-revoked");
        },
      }),
    ).rejects.toThrow();
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(0);
    assertClosedChild();
  });

  it("does not accept a confirmation after revocation during awaited cleanup", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    let current = true;
    hooks.disposed = () => {
      current = false;
    };
    await expect(
      readOpsysM9HistoryConfirmation({
        ...readerParams(f),
        assertCurrent: () => {
          if (!current) throw new Error("fictif-owner-revoked");
        },
      }),
    ).rejects.toThrow();
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  // Break: a late params.assertCurrent lookup replaces the guard during cleanup.
  it("retains the original owner assertion when its caller replaces it during cleanup", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    const params = readerParams(f);
    let current = true;
    params.assertCurrent = () => {
      if (!current) throw new Error("fictif-owner-revoked");
    };
    hooks.disposed = () => {
      current = false;
      params.assertCurrent = () => {};
    };
    await expect(readOpsysM9HistoryConfirmation(params)).rejects.toThrow();
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  // Symphony843 oracle: the original callback may stop being synchronous without throwing.
  it("rejects a non-undefined owner assertion result after real cleanup", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    let disposed = false;
    hooks.disposed = () => {
      disposed = true;
    };
    const params = {
      ...readerParams(f),
      assertCurrent: () => {
        return disposed ? true : undefined;
      },
    };
    await expect(readOpsysM9HistoryConfirmation(params)).rejects.toThrow(
      "OPSYS M9 history current authority rejected",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  it("refuses an SDK error before parsing its private invalid JSON", async () => {
    const f = await fixture("fictif-private-not-json", false, true);
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).rejects.toThrow(
      "MCP tool reported an error",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  it("does not accept a response when cleanup is uncertain", async () => {
    const f = await fixture(JSON.stringify(confirmedEnvelope()));
    hooks.cleanup = "uncertain";
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).rejects.toThrow(
      "MCP cleanup is uncertain",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });

  it("rejects decoded text larger than the reader response budget", async () => {
    const envelope = { ...confirmedEnvelope(), paddingFictif: "x".repeat(16384) };
    const f = await fixture(JSON.stringify(envelope));
    await expect(readOpsysM9HistoryConfirmation(readerParams(f))).rejects.toThrow(
      "MCP response boundary rejected",
    );
    expect((await f.wire()).filter((m) => m.method === "tools/call")).toHaveLength(1);
    assertClosedChild();
  });
});
