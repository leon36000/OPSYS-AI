// Integrated fixture: only ticket/source results and runtime admission are synthetic.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { upsertSessionEntryCore } from "../../config/sessions/session-accessor.js";
import { createUserTurnTranscriptRecorder } from "../../sessions/user-turn-transcript.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { OpsysPostflightCollector } from "./opsys-postflight-collector.js";

export const WIRE_AGENT = "m03-estimation";
export const WIRE_TOOL = "m3_marquer_devis_accepte";
export const WIRE_AFFAIRE = "LEAD-SYNTHETIC-WIRE";
export const WIRE_ARGS = {
  devis_id: "DEV-SYNTHETIC-WIRE",
  approbateur: "personne.synthetic",
  horodatage: "2026-10-05T12:00:00Z",
};

export async function prepareWireCollector(params: {
  root: string;
  sessionId: string;
  sessionKey: string;
  profileId: string;
  revision: number;
}) {
  const storePath = resolve(params.root, "agents", WIRE_AGENT, "sessions", "sessions.json");
  await mkdir(resolve(params.root, "agents", WIRE_AGENT, "sessions"), { recursive: true });
  const target = {
    agentId: WIRE_AGENT,
    cwd: params.root,
    sessionId: params.sessionId,
    sessionKey: params.sessionKey,
    storePath,
  };
  const sessionEntry = await upsertSessionEntryCore(target, {
    sessionId: params.sessionId,
    updatedAt: 1,
  });
  if (!sessionEntry) {
    throw new Error("synthetic department transcript entry absent");
  }
  const recorder = createUserTurnTranscriptRecorder({
    message: { role: "user", content: "fictif: true; isolated wire test", timestamp: 2 },
    target: () => ({ ...target, sessionEntry }),
    updateMode: "none",
  });
  await recorder.persistApproved();
  const receipt = recorder.getAdmissionReceipt();
  if (!receipt || receipt.agentId !== WIRE_AGENT || receipt.sessionId !== params.sessionId) {
    throw new Error("department transcript admission not really persisted");
  }
  const options = { agentId: receipt.agentId, path: receipt.storePath };
  const createCollector = async (runId: string) => {
    const collector = new OpsysPostflightCollector({
      runId,
      sessionId: params.sessionId,
      sessionKey: params.sessionKey,
      agentId: WIRE_AGENT,
      recorder,
      depositTools: [WIRE_TOOL],
      assertCurrent: () => undefined,
    });
    // The transcript receipt above is actual; this model/provider admission remains synthetic.
    collector.recordRuntimeAdmission({
      runId,
      agentId: WIRE_AGENT,
      profileId: params.profileId,
      profileRevision: params.revision,
      departement: WIRE_AGENT,
      attemptId: `${runId}-attempt`,
      cycleId: `${runId}-cycle`,
    });
    await collector.prepareBeforeProviderDispatch();
    return collector;
  };
  return {
    options,
    database: openOpenClawAgentDatabase(options),
    createCollector,
  };
}

/** A real stdio MCP peer reads actual SQLite before returning a synthetic business result. */
export async function writeSyntheticWireServers(params: {
  root: string;
  databasePath: string;
  factKey: string;
  outcome: "known" | "disconnect";
}) {
  const logPath = resolve(params.root, "synthetic-source-observations.jsonl");
  const sourcePath = resolve(params.root, "synthetic-source.mjs");
  const contextPath = resolve(params.root, "synthetic-ticket.mjs");
  const serve = String.raw`
import fs from "node:fs";
import readline from "node:readline";
import { DatabaseSync } from "node:sqlite";
const source = process.env.OPSYS_FIXTURE_KIND === "source";
for await (const line of readline.createInterface({ input: process.stdin })) {
  const m = JSON.parse(line);
  let result;
  if (m.method === "initialize") result = {
    protocolVersion: m.params.protocolVersion, capabilities: { tools: {} },
    serverInfo: { name: "synthetic-postflight-wire", version: "1" }
  };
  if (m.method === "tools/list") result = { tools: [{
    name: source ? "${WIRE_TOOL}" : "opsys_contexte_creer_ticket_cible",
    inputSchema: { type: "object", additionalProperties: true }
  }] };
  if (m.method === "tools/call") {
    if (source) {
      const db = new DatabaseSync(process.env.OPSYS_FIXTURE_DATABASE, { readOnly: true });
      const intents = db.prepare("SELECT fact_key, state FROM opsys_postflight_intents WHERE fact_key = ?")
        .all(process.env.OPSYS_FIXTURE_KEY);
      const pendingLots = db.prepare("SELECT COUNT(*) AS count FROM opsys_postflight_outbox").get().count;
      db.close();
      fs.appendFileSync(process.env.OPSYS_FIXTURE_OBSERVATIONS, JSON.stringify({ fictif: true, intents, pendingLots }) + "\n");
      if (process.env.OPSYS_FIXTURE_OUTCOME === "disconnect") process.exit(0);
      result = { content: [{ type: "text", text: JSON.stringify({ ok: true, resultat: { fictif: true } }) }] };
    } else result = { content: [{ type: "text", text: JSON.stringify({
      ok: true, resultat: { ticket: "synthetic-wire-ticket-not-a-credential",
        expire_le: new Date(Date.now() + 120000).toISOString() }
    }) }] };
  }
  if (result) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: m.id, result }) + "\n");
}
`;
  await writeFile(sourcePath, serve, { mode: 0o600 });
  await writeFile(contextPath, serve, { mode: 0o600 });
  return {
    servers: {
      opsys_m3: {
        command: process.execPath,
        args: [sourcePath],
        env: {
          OPSYS_FIXTURE_KIND: "source",
          OPSYS_FIXTURE_DATABASE: params.databasePath,
          OPSYS_FIXTURE_KEY: params.factKey,
          OPSYS_FIXTURE_OUTCOME: params.outcome,
          OPSYS_FIXTURE_OBSERVATIONS: logPath,
        },
      },
      "opsys_context_m03-estimation": {
        command: process.execPath,
        args: [contextPath],
        env: { OPSYS_FIXTURE_KIND: "ticket" },
      },
    },
    readObservations: async (): Promise<unknown[]> => {
      const content = await readFile(logPath, "utf8").catch(() => "");
      return content
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line));
    },
  };
}
