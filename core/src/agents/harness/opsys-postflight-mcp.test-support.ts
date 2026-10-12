// Integrated fixture: only ticket/source results and runtime admission are synthetic.
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { upsertSessionEntryCore } from "../../config/sessions/session-accessor.js";
import type { McpServerConfig } from "../../config/types.mcp.js";
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

async function listenWireHttp(server: Server): Promise<string> {
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolveListen();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("wire HTTP origin absent");
  }
  return `http://127.0.0.1:${address.port}`;
}

async function closeWireHttp(server: Server): Promise<void> {
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
    server.closeAllConnections();
  });
}

/** Real HTTP SDK boundary, with synthetic effect observed against the real intent ledger. */
async function startWireHttpSource(params: {
  databasePath: string;
  factKey: string;
  logPath: string;
  outcome: "http-known" | "redirect307" | "redirect308";
}) {
  let sourceCalls = 0;
  let destinationCalls = 0;
  const destination = createServer((_request, response) => {
    destinationCalls += 1;
    response.writeHead(500);
    response.end();
  });
  const destinationOrigin = await listenWireHttp(destination);
  const source = createServer((request, response) => {
    const handle = async () => {
      if (request.method === "GET") {
        response.writeHead(405);
        response.end();
        return;
      }
      if (request.method === "DELETE") {
        response.writeHead(204);
        response.end();
        return;
      }
      const chunks: Buffer[] = [];
      for await (const chunk of request) {
        chunks.push(Buffer.from(chunk));
      }
      const message: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!message || typeof message !== "object" || !("method" in message)) {
        throw new Error("wire JSON-RPC method absent");
      }
      let result: unknown;
      if (message.method === "initialize") {
        result = {
          protocolVersion: "2025-06-18",
          capabilities: { tools: {} },
          serverInfo: { name: "synthetic-http-postflight", version: "1" },
        };
      } else if (message.method === "tools/list") {
        result = {
          tools: [{ name: WIRE_TOOL, inputSchema: { type: "object", additionalProperties: true } }],
        };
      } else if (message.method === "tools/call") {
        sourceCalls += 1;
        const database = new DatabaseSync(params.databasePath, { readOnly: true });
        try {
          const intents = database
            .prepare("SELECT fact_key, state FROM opsys_postflight_intents WHERE fact_key = ?")
            .all(params.factKey);
          const pendingLots = database
            .prepare("SELECT COUNT(*) AS count FROM opsys_postflight_outbox")
            .get()?.count;
          await appendFile(
            params.logPath,
            JSON.stringify({ fictif: true, intents, pendingLots }) + "\n",
          );
        } finally {
          database.close();
        }
        if (params.outcome !== "http-known") {
          response.writeHead(params.outcome === "redirect307" ? 307 : 308, {
            location: `${destinationOrigin}/mcp`,
          });
          response.end();
          return;
        }
        result = {
          content: [
            { type: "text", text: JSON.stringify({ ok: true, resultat: { fictif: true } }) },
          ],
        };
      }
      if (result === undefined) {
        response.writeHead(202);
        response.end();
        return;
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({ jsonrpc: "2.0", id: "id" in message ? message.id : null, result }),
      );
    };
    void handle().catch(() => {
      response.writeHead(500);
      response.end();
    });
  });
  let origin: string;
  try {
    origin = await listenWireHttp(source);
  } catch (error) {
    await closeWireHttp(destination);
    throw error;
  }
  const config: McpServerConfig = {
    url: `${origin}/mcp`,
    transport: "streamable-http",
    transportSecurity: { insecureHttpOrigin: origin },
  };
  return {
    config,
    counts: () => ({ sourceCalls, destinationCalls }),
    close: async () => {
      await closeWireHttp(source);
      await closeWireHttp(destination);
    },
  };
}

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
  outcome: "known" | "disconnect" | "http-known" | "redirect307" | "redirect308";
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
  const http =
    params.outcome === "known" || params.outcome === "disconnect"
      ? undefined
      : await startWireHttpSource({ ...params, logPath, outcome: params.outcome });
  return {
    servers: {
      opsys_m3: http?.config ?? {
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
    close: async () => {
      await http?.close();
    },
    httpCounts: () => http?.counts(),
    readObservations: async (): Promise<unknown[]> => {
      const content = await readFile(logPath, "utf8").catch(() => "");
      return content
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line));
    },
  };
}
