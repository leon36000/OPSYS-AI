import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { depositKey } from "../../context-engine/opsys-contexte-depot.js";
import { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import type {
  OpenClawAgentDatabase,
  OpenClawAgentDatabaseOptions,
} from "../../state/openclaw-agent-db-contract.js";
import { openOpenClawAgentDatabase } from "../../state/openclaw-agent-db.js";
import { cleanupSessionStateForTest } from "../../test-utils/session-state-cleanup.js";
import {
  deliverOpsysPostflightLots,
  type OpsysPostflightDeliveryDeps,
  type OpsysPostflightDeliveryProfile,
} from "./opsys-postflight-delivery.js";
import type { OpsysPostflightLot, OpsysPostflightLotInput } from "./opsys-postflight-outbox.js";

const dirs: string[] = [];
afterEach(async () => {
  for (const dir of dirs.splice(0)) {
    await cleanupSessionStateForTest({ stateDir: dir });
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function setupDatabase(): {
  database: OpenClawAgentDatabase;
  options: OpenClawAgentDatabaseOptions;
} {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-postflight-delivery-"));
  dirs.push(dir);
  const options = { agentId: "opsys-agent-demo", env: { OPENCLAW_STATE_DIR: dir } };
  return { database: openOpenClawAgentDatabase(options), options };
}

const profile: OpsysPostflightDeliveryProfile = {
  id: "demo",
  revision: 7,
  departement: "m03-estimation",
};

let lotSerial = 0;

function lot(overrides: Partial<OpsysPostflightLotInput> = {}): OpsysPostflightLot {
  lotSerial += 1;
  const input: OpsysPostflightLotInput = {
    affaireId: "LEAD-2030-000001",
    departementSource: profile.departement,
    profilId: profile.id,
    revision: profile.revision,
    engineId: "opsys",
    facts: [
      {
        cle: depositKey("session-demo", `call-${lotSerial}`),
        outil: "m3_estimer_projet",
        resultat: "ok",
        code: null,
      },
    ],
    ...overrides,
  };
  return {
    ...input,
    lotKey: `postflight-${input.facts.map((fact) => fact.cle).join("-")}`,
    state: "pending",
    attemptCount: 0,
    createdAt: 1_000,
    updatedAt: 1_000,
    nextAttemptAt: 1_000,
    lastAttemptAt: null,
    lastErrorCode: null,
    needsReviewAt: null,
  };
}

function accepted(lotValue: OpsysPostflightLot) {
  return {
    ok: true,
    resultat: {
      accepte: true,
      source: {
        profil_id: lotValue.profilId,
        revision: lotValue.revision,
        departement: lotValue.departementSource,
        engine_id: "opsys",
      },
      affaire_id: lotValue.affaireId,
      cles: lotValue.facts.map((fact) => fact.cle),
      resultat: { ecrits: 1, deja_deposes: 0, lignes: ["row-1"] },
    },
  };
}

function makeStore(rows: readonly OpsysPostflightLot[]) {
  const store = {
    listDue: vi.fn(async () => [...rows]),
    beginAttempt: vi.fn(async (lotKey: string) => {
      const row = rows.find((candidate) => candidate.lotKey === lotKey);
      return row
        ? {
            ...row,
            state: row.attemptCount === 0 ? "pending" : "retry",
            attemptCount: row.attemptCount + 1,
          }
        : undefined;
    }),
    fail: vi.fn(async () => {
      const row = rows[0];
      if (!row) {
        throw new Error("test store has no lot to fail");
      }
      return row;
    }),
    acknowledge: vi.fn(async () => true),
  };
  return store;
}

function params(rows: readonly OpsysPostflightLot[]) {
  const db = setupDatabase();
  const store = makeStore(rows);
  const callTool: typeof callOpsysMcpTool = vi.fn(
    async ({ args }: Parameters<typeof callOpsysMcpTool>[0]) => {
      const lotValue = rows.find(
        (row) =>
          row.affaireId === args.affaire_id &&
          JSON.stringify(row.facts) === JSON.stringify(args.faits),
      );
      return lotValue ? accepted(lotValue) : undefined;
    },
  );
  const deps: OpsysPostflightDeliveryDeps = { store, callTool };
  const call = () =>
    deliverOpsysPostflightLots(
      {
        ...db,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: new AbortController().signal,
        nowMs: () => 20_000,
      },
      deps,
    );
  return {
    call,
    callTool,
    store,
    database: db.database,
    options: db.options,
  };
}

describe("OPSYS postflight delivery", () => {
  it("sends only matching due lots to the profile-bound route and ACKs exact server evidence", async () => {
    const matching = lot();
    const mismatchedProfile = lot({ profilId: "other" });
    const mismatchedRevision = lot({ revision: 6 });
    const mismatchedDepartment = lot({ departementSource: "m04-field-ops" });
    const wrongEngine = lot({ engineId: "other" });
    const { call, callTool, store } = params([
      mismatchedProfile,
      mismatchedRevision,
      mismatchedDepartment,
      wrongEngine,
      matching,
    ]);

    const result = await call();

    expect(result).toMatchObject({ attempted: 1, delivered: 1, failed: 0 });
    expect(callTool).toHaveBeenCalledTimes(1);
    expect(callTool).toHaveBeenCalledWith({
      config: undefined,
      server: "opsys_runtime_demo",
      tool: "opsys_runtime_deposer_faits",
      args: {
        affaire_id: matching.affaireId,
        faits: matching.facts,
        horodatage: "1970-01-01T00:00:20.000+00:00",
        revision_profil: profile.revision,
      },
      timeoutMs: 4_000,
      signal: expect.any(AbortSignal),
    });
    expect(store.acknowledge).toHaveBeenCalledWith(
      matching.lotKey,
      {
        affaireId: matching.affaireId,
        departementSource: matching.departementSource,
        profilId: matching.profilId,
        revision: matching.revision,
        engineId: matching.engineId,
        facts: matching.facts,
      },
      20_000,
    );
    expect(store.fail).not.toHaveBeenCalled();
  });

  it("caps one pass at four remote lots", async () => {
    const lots = Array.from({ length: 6 }, (_unused, index) =>
      lot({
        affaireId: `LEAD-2030-00000${index + 1}`,
        facts: [
          {
            cle: depositKey("session-demo", `call-${index + 1}`),
            outil: "m3_estimer_projet",
            resultat: "ok",
            code: null,
          },
        ],
      }),
    );
    const { call, callTool } = params(lots);

    const result = await call();

    expect(result.attempted).toBe(4);
    expect(callTool).toHaveBeenCalledTimes(4);
  });

  it("refuses a store attempt that returns another lot payload", async () => {
    const row = lot();
    const harness = params([row]);
    const { store, callTool } = harness;
    store.beginAttempt = vi.fn(async () => ({
      ...row,
      lotKey: "postflight-other",
      attemptCount: 1,
    }));

    const result = await harness.call();

    expect(result).toMatchObject({ selected: 1, attempted: 0, failed: 1, delivered: 0 });
    expect(callTool).not.toHaveBeenCalled();
    expect(store.acknowledge).not.toHaveBeenCalled();
  });

  it("retains the lot and records a closed failure code for a timeout", async () => {
    const row = lot();
    const harness = params([row]);
    const { store, database, options } = harness;
    const callTool: typeof callOpsysMcpTool = vi.fn(async () => {
      throw new Error("timeout carrying transport details");
    });

    const result = await deliverOpsysPostflightLots(
      {
        database,
        options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: new AbortController().signal,
        nowMs: () => 30_000,
      },
      { store, callTool },
    );

    expect(result).toMatchObject({ attempted: 1, failed: 1, delivered: 0 });
    expect(store.fail).toHaveBeenCalledWith(
      row.lotKey,
      expect.objectContaining({ affaireId: row.affaireId }),
      "M10-POSTFLIGHT-INDISPONIBLE",
      30_000,
    );
    expect(store.acknowledge).not.toHaveBeenCalled();
  });

  it("does not ACK a response with altered keys or mismatched counts", async () => {
    const row = lot();
    const harness = params([row]);
    const { store, database, options } = harness;
    const callTool: typeof callOpsysMcpTool = vi.fn(async () => {
      const reply = accepted(row);
      reply.resultat.cles = ["tc-0000000000000000000000000000000000000000"];
      reply.resultat.source.revision = 6;
      reply.resultat.resultat.ecrits = 0;
      return reply;
    });

    const result = await deliverOpsysPostflightLots(
      {
        database,
        options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: new AbortController().signal,
        nowMs: () => 40_000,
      },
      { store, callTool },
    );

    expect(result).toMatchObject({ attempted: 1, failed: 1, delivered: 0 });
    expect(store.acknowledge).not.toHaveBeenCalled();
    expect(store.fail).toHaveBeenCalledWith(
      row.lotKey,
      expect.objectContaining({ affaireId: row.affaireId }),
      "M10-POSTFLIGHT-REPONSE-INVALIDE",
      40_000,
    );
  });

  it("does not call M10 after attempt reservation if authority is revoked before dispatch", async () => {
    const row = lot();
    const harness = params([row]);
    const { callTool, store, database, options } = harness;
    let checks = 0;
    const result = await deliverOpsysPostflightLots(
      {
        database,
        options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => {
          checks += 1;
          if (checks === 3) {
            throw new Error("revoked");
          }
        },
        signal: new AbortController().signal,
        nowMs: () => 50_000,
      },
      { store, callTool },
    );

    expect(result).toMatchObject({ attempted: 1, failed: 1, delivered: 0 });
    expect(callTool).not.toHaveBeenCalled();
    expect(store.fail).toHaveBeenCalledWith(
      row.lotKey,
      expect.any(Object),
      "M10-POSTFLIGHT-AUTORITE-REVOQUEE",
      50_000,
    );
  });

  it("does not reserve a due lot when the caller is already aborted", async () => {
    const row = lot();
    const harness = params([row]);
    const { store, callTool, database, options } = harness;
    const controller = new AbortController();
    controller.abort();
    const result = await deliverOpsysPostflightLots(
      {
        database,
        options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: controller.signal,
        nowMs: () => 55_000,
      },
      { store, callTool },
    );

    expect(result).toMatchObject({ selected: 0, attempted: 0, delivered: 0 });
    expect(store.listDue).not.toHaveBeenCalled();
    expect(store.beginAttempt).not.toHaveBeenCalled();
    expect(callTool).not.toHaveBeenCalled();
  });

  it("keeps a lot after local ACK failure so a later M10 idempotent retry can reconcile", async () => {
    const row = lot();
    const harness = params([row]);
    const { store, database, options } = harness;
    store.acknowledge = vi.fn(async () => {
      throw new Error("local ACK write failure");
    });
    const callTool: typeof callOpsysMcpTool = vi.fn(async () => accepted(row));

    const result = await deliverOpsysPostflightLots(
      {
        database,
        options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: new AbortController().signal,
        nowMs: () => 60_000,
      },
      { store, callTool },
    );

    expect(result).toMatchObject({ attempted: 1, delivered: 0, acknowledgementFailures: 1 });
    expect(store.fail).not.toHaveBeenCalled();
    expect(store.acknowledge).toHaveBeenCalledTimes(1);
  });
  it.each<{ name: string; alter: (reply: ReturnType<typeof accepted>) => unknown }>([
    {
      name: "absent counts",
      alter: (reply) => ({ ...reply, resultat: { ...reply.resultat, resultat: { lignes: [] } } }),
    },
    {
      name: "string count",
      alter: (reply) => ({
        ...reply,
        resultat: {
          ...reply.resultat,
          resultat: { ecrits: "1", deja_deposes: 0, lignes: ["row-1"] },
        },
      }),
    },
    {
      name: "negative count",
      alter: (reply) => ({
        ...reply,
        resultat: { ...reply.resultat, resultat: { ecrits: -1, deja_deposes: 2, lignes: [] } },
      }),
    },
    {
      name: "wrong sum",
      alter: (reply) => ({
        ...reply,
        resultat: {
          ...reply.resultat,
          resultat: { ecrits: 1, deja_deposes: 1, lignes: ["row-1"] },
        },
      }),
    },
    {
      name: "wrong row count",
      alter: (reply) => ({
        ...reply,
        resultat: { ...reply.resultat, resultat: { ecrits: 1, deja_deposes: 0, lignes: [] } },
      }),
    },
    {
      name: "another affair",
      alter: (reply) => ({ ...reply, resultat: { ...reply.resultat, affaire_id: "LEAD-OTHER" } }),
    },
    {
      name: "another source",
      alter: (reply) => ({
        ...reply,
        resultat: { ...reply.resultat, source: { ...reply.resultat.source, profil_id: "other" } },
      }),
    },
    {
      name: "another revision",
      alter: (reply) => ({
        ...reply,
        resultat: { ...reply.resultat, source: { ...reply.resultat.source, revision: 6 } },
      }),
    },
    {
      name: "another department",
      alter: (reply) => ({
        ...reply,
        resultat: {
          ...reply.resultat,
          source: { ...reply.resultat.source, departement: "m05-financecore" },
        },
      }),
    },
    {
      name: "another engine",
      alter: (reply) => ({
        ...reply,
        resultat: { ...reply.resultat, source: { ...reply.resultat.source, engine_id: "other" } },
      }),
    },
  ])("retains a lot for invalid ACK: $name", async ({ alter }) => {
    const row = lot();
    const harness = params([row]);
    const result = await deliverOpsysPostflightLots(
      {
        database: harness.database,
        options: harness.options,
        config: undefined,
        timeoutMs: 4_000,
        profile,
        assertCurrent: () => undefined,
        signal: new AbortController().signal,
        nowMs: () => 60_000,
      },
      { store: harness.store, callTool: async () => alter(accepted(row)) },
    );
    expect(result).toMatchObject({ attempted: 1, delivered: 0, failed: 1 });
    expect(harness.store.acknowledge).not.toHaveBeenCalled();
    expect(harness.store.fail).toHaveBeenCalledWith(
      row.lotKey,
      expect.any(Object),
      "M10-POSTFLIGHT-REPONSE-INVALIDE",
      60_000,
    );
  });

  it.each(["abort", "revocation"])(
    "retains a lot if %s happens while awaiting the remote ACK",
    async (mode) => {
      const row = lot();
      const harness = params([row]);
      const controller = new AbortController();
      let current = true;
      const result = await deliverOpsysPostflightLots(
        {
          database: harness.database,
          options: harness.options,
          config: undefined,
          timeoutMs: 4_000,
          profile,
          assertCurrent: () => {
            if (!current) {
              throw new Error("revoked");
            }
          },
          signal: controller.signal,
          nowMs: () => 60_000,
        },
        {
          store: harness.store,
          callTool: async () => {
            if (mode === "abort") {
              controller.abort();
            } else {
              current = false;
            }
            return accepted(row);
          },
        },
      );
      expect(result).toMatchObject({ attempted: 1, delivered: 0, failed: 1 });
      expect(harness.store.acknowledge).not.toHaveBeenCalled();
      expect(harness.store.fail).toHaveBeenCalledWith(
        row.lotKey,
        expect.any(Object),
        mode === "abort" ? "M10-POSTFLIGHT-INTERRUPPU" : "M10-POSTFLIGHT-AUTORITE-REVOQUEE",
        60_000,
      );
    },
  );
});
