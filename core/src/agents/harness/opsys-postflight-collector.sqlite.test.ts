import { describe, expect, it } from "vitest";
import { upsertSessionEntryCore } from "../../config/sessions/session-accessor.js";
import { resolveSessionTranscriptDatabasePath } from "../../config/sessions/session-accessor.transcript-target.js";
import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import { createUserTurnTranscriptRecorder } from "../../sessions/user-turn-transcript.js";
import { createSqliteTranscriptTarget } from "../../sessions/user-turn-transcript.test-support.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { withOpenClawTestState } from "../../test-utils/openclaw-test-state.js";
import { cleanupSessionStateForTest } from "../../test-utils/session-state-cleanup.js";
import { buildAfterTurnRuntimeContext } from "../embedded-agent-runner/run/attempt-prompt-helpers.js";
import { OpsysPostflightCollector } from "./opsys-postflight-collector.js";
import { listOpsysPostflightLots, listOpsysPostflightIntents } from "./opsys-postflight-outbox.js";

describe("OPSYS postflight collector SQLite join", () => {
  it("uses the persisted transcript receipt to store a known fact in SQLite", async () => {
    await withOpenClawTestState({ label: "opsys-postflight-collector-sqlite" }, async (state) => {
      const sessionId = "collector-canonical-receipt";
      const sessionKey = `agent:main:${sessionId}`;
      const target = createSqliteTranscriptTarget({
        dir: state.stateDir,
        sessionId,
        sessionKey,
      });
      const sessionEntry = await upsertSessionEntryCore(target, { sessionId, updatedAt: 1 });
      if (!sessionEntry) {
        throw new Error("expected persisted session entry");
      }
      const recorder = createUserTurnTranscriptRecorder({
        message: { role: "user", content: "authorized test input", timestamp: 2 },
        target: () => ({ ...target, sessionEntry }),
        updateMode: "none",
      });
      const admitted = await recorder.persistApproved();
      expect(admitted).toBeDefined();
      const transcriptReceipt = recorder.getAdmissionReceipt();
      expect(transcriptReceipt?.storePath).toBe(
        resolveSessionTranscriptDatabasePath({
          agentId: target.agentId,
          sessionId: target.sessionId,
          sessionKey: target.sessionKey,
          storePath: target.storePath,
        }),
      );

      const collector = new OpsysPostflightCollector({
        runId: "run-sqlite",
        sessionId,
        sessionKey,
        agentId: "main",
        recorder,
        depositTools: ["m3_creer_devis"],
        assertCurrent: () => undefined,
      });
      collector.recordRuntimeAdmission({
        runId: "run-sqlite",
        agentId: "main",
        profileId: "profile-test",
        profileRevision: 1,
        departement: "m03-estimation",
        attemptId: "attempt-sqlite",
        cycleId: "cycle-sqlite",
      });
      await collector.prepareBeforeProviderDispatch();
      const observer = collector.beginToolCall({
        toolCallId: "mcp-sqlite-call",
        toolName: "m3_creer_devis",
        serverName: "opsys_m3",
      });
      expect(observer).toBeDefined();
      await observer?.assertBeforeEffect({
        agentId: "main",
        sessionKey,
        affaireId: "LEAD-SQLITE-1",
        serverName: "opsys_m3",
        toolName: "m3_creer_devis",
      });
      const reservationReceipt = recorder.getAdmissionReceipt();
      if (!reservationReceipt) {
        throw new Error("expected canonical reservation receipt");
      }
      const reservedOptions = {
        agentId: reservationReceipt.agentId,
        path: reservationReceipt.storePath,
      };
      const reservedDatabase = openOpenClawAgentDatabase(reservedOptions);
      expect(
        await listOpsysPostflightIntents({
          database: reservedDatabase,
          options: reservedOptions,
          now: Date.now(),
        }),
      ).toMatchObject([{ state: "uncertain", affaireId: "LEAD-SQLITE-1" }]);
      expect(
        await listOpsysPostflightLots({
          database: reservedDatabase,
          options: reservedOptions,
          now: Date.now(),
        }),
      ).toEqual([]);
      await observer?.observe(
        {
          agentId: "main",
          sessionKey,
          affaireId: "LEAD-SQLITE-1",
          serverName: "opsys_m3",
          toolName: "m3_creer_devis",
        },
        {
          content: [
            {
              type: "text",
              text: JSON.stringify({ ok: true, resultat: { devis_id: "DEV-SQLITE-1" } }),
            },
          ],
        },
        { authorityCurrent: true },
      );

      const hostContext = buildAfterTurnRuntimeContext({
        attempt: {
          sessionId,
          sessionKey,
          config: {},
          provider: "openai",
          modelId: "synthetic-model",
          thinkLevel: "off",
          reasoningLevel: "on",
          skillsSnapshot: undefined,
          opsysPostflightCollector: collector,
        },
        workspaceDir: state.stateDir,
        agentDir: state.stateDir,
        activeAgentId: "main",
      });
      expect(hostContext.opsysDeferredPostflight).toEqual({
        sessionId,
        sessionKey,
        agentId: "main",
        factKeys: [depositKey(sessionId, "mcp-sqlite-call")],
      });

      const receipt = recorder.getAdmissionReceipt();
      if (!receipt) {
        throw new Error("expected canonical transcript receipt");
      }
      const options = { agentId: receipt.agentId, path: receipt.storePath };
      const database = openOpenClawAgentDatabase(options);
      const lots = await listOpsysPostflightLots({ database, options, now: Date.now() });
      expect(lots).toHaveLength(1);
      expect(lots[0]).toMatchObject({
        affaireId: "LEAD-SQLITE-1",
        departementSource: "m03-estimation",
        facts: [{ outil: "m3_creer_devis", resultat: "ok" }],
      });
      expect(lots[0]?.facts[0]?.cle).toBe(depositKey(sessionId, "mcp-sqlite-call"));

      const replayCollector = new OpsysPostflightCollector({
        runId: "run-exact-replay",
        sessionId,
        sessionKey,
        agentId: "main",
        recorder,
        depositTools: ["m3_creer_devis"],
        assertCurrent: () => undefined,
      });
      replayCollector.recordRuntimeAdmission({
        runId: "run-exact-replay",
        agentId: "main",
        profileId: "profile-test",
        profileRevision: 1,
        departement: "m03-estimation",
        attemptId: "attempt-exact-replay",
        cycleId: "cycle-exact-replay",
      });
      await replayCollector.prepareBeforeProviderDispatch();
      const exactReplay = replayCollector.beginToolCall({
        toolCallId: "mcp-sqlite-call",
        toolName: "m3_creer_devis",
        serverName: "opsys_m3",
      });
      await expect(
        exactReplay?.assertBeforeEffect({
          agentId: "main",
          sessionKey,
          affaireId: "LEAD-SQLITE-1",
          serverName: "opsys_m3",
          toolName: "m3_creer_devis",
        }),
      ).rejects.toThrow("POSTFLIGHT_CLE_DEJA_UTILISEE");
      // A completed source call is never re-executed merely because another collector exists.
      expect(await replayCollector.flushPending()).toMatchObject({ remaining: 0, failures: 1 });
      expect(await listOpsysPostflightIntents({ database, options, now: Date.now() })).toEqual([]);
      const finalLots = await listOpsysPostflightLots({ database, options, now: Date.now() });
      expect(finalLots).toHaveLength(1);
      expect(finalLots[0]?.facts).toMatchObject([{ resultat: "ok" }]);
      await cleanupSessionStateForTest({ stateDir: state.stateDir });
      const reopened = openOpenClawAgentDatabase(options);
      const persisted = await listOpsysPostflightLots({
        database: reopened,
        options,
        now: Date.now(),
      });
      expect(persisted).toEqual(finalLots);
    });
  });
});
