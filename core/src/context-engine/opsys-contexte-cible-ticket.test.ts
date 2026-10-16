import { describe, expect, it, vi } from "vitest";
import { createOpsysCibleTicketMeta } from "./opsys-contexte-cible-ticket.js";
import type { OpsysContexteConfigResult } from "./opsys-contexte-config.js";
import { OpsysContexteGuardStore, type OpsysGuardState } from "./opsys-contexte-garde.js";
import { CONFIG_M3 } from "./opsys-contexte.test-support.js";

const NOW = Date.parse("2026-09-30T12:00:00.000Z");
const SESSION = "agent:m03-estimation:main";
const TOOL = "m3_marquer_devis_accepte";
const INPUT = {
  devis_id: "DEV-001",
  approbateur: "personne.1",
  horodatage: "2026-09-30T12:00:00Z",
};

function config(overrides: Partial<typeof CONFIG_M3> = {}): OpsysContexteConfigResult {
  return {
    kind: "enabled",
    config: {
      ...CONFIG_M3,
      agents: new Map([["m03-estimation", [TOOL]]]),
      levels: new Map([...CONFIG_M3.levels, [TOOL, "N5"]]),
      targets: new Map([...CONFIG_M3.targets, [TOOL, { kind: "ticket" }]]),
      ...overrides,
    },
  };
}

function ready(affaireId = "LEAD-001", nbOuverts = 0, atMs = NOW): OpsysGuardState {
  return { kind: "ready", affaireId, nbOuverts, atMs };
}

function setup(
  overrides: {
    config?: OpsysContexteConfigResult;
    state?: OpsysGuardState;
    serverName?: string;
    toolName?: string;
    sessionKey?: string;
    response?: unknown;
  } = {},
) {
  const guardStore = new OpsysContexteGuardStore();
  guardStore.set(
    overrides.sessionKey ?? SESSION,
    Object.hasOwn(overrides, "state") ? overrides.state! : ready(),
  );
  const callTool = vi.fn().mockResolvedValue(
    overrides.response ?? {
      ok: true,
      resultat: {
        ticket: "opaque-ticket-secret",
        expire_le: new Date(NOW + 120_000).toISOString(),
      },
    },
  );
  const params = {
    cfg: undefined,
    serverName: overrides.serverName ?? "opsys_m3",
    toolName: overrides.toolName ?? TOOL,
    toolParams: INPUT,
    sessionKey: overrides.sessionKey ?? SESSION,
    signal: new AbortController().signal,
  };
  const deps = {
    readConfig: () => overrides.config ?? config(),
    guardStore,
    callTool,
    nowMs: () => NOW,
  };
  return { params, deps, callTool };
}

describe("createOpsysCibleTicketMeta", () => {
  it("issues an origin-bound ticket for exact final params and returns only the private _meta field", async () => {
    const { params, deps, callTool } = setup();
    const onIssued = vi.fn();

    const meta = await createOpsysCibleTicketMeta({ ...params, onIssued }, deps);

    expect(callTool).toHaveBeenCalledOnce();
    expect(callTool).toHaveBeenCalledWith(
      expect.objectContaining({
        server: "opsys_context_m03-estimation",
        tool: "opsys_contexte_creer_ticket_cible",
        args: {
          agent_id: "m03-estimation",
          cle_session: SESSION,
          affaire_id: "LEAD-001",
          origine_affaire: "demande",
          outil: TOOL,
          arguments: INPUT,
        },
      }),
    );
    expect(meta).toStrictEqual({
      arguments: INPUT,
      meta: { "opsys/cibleTicket": "opaque-ticket-secret" },
    });
    expect(onIssued).toHaveBeenCalledExactlyOnceWith({
      agentId: "m03-estimation",
      sessionKey: SESSION,
      affaireId: "LEAD-001",
      serverName: "opsys_m3",
      toolName: TOOL,
    });
    expect(JSON.stringify(onIssued.mock.calls)).not.toContain("opaque-ticket-secret");
  });

  it("marks session-linked cases as session origin", async () => {
    const { params, deps, callTool } = setup({
      config: config({ affaireFromSession: new Set(["m03-estimation"]) }),
    });

    await createOpsysCibleTicketMeta(params, deps);

    expect(callTool.mock.calls[0]?.[0].args).toMatchObject({ origine_affaire: "session" });
  });

  it.each([
    ["wrong department server", { serverName: "opsys_m2" }],
    ["unknown session", { sessionKey: "main" }],
    ["main agent", { sessionKey: "agent:main:main" }],
    ["agent without an active M10 profile", { sessionKey: "agent:m02-revenue-crm:main" }],
    ["no ready M10 context", { state: undefined }],
    ["stale M10 context", { state: ready("LEAD-001", 0, NOW - 15 * 60 * 1_000 - 1) }],
    ["critical signal", { state: ready("LEAD-001", 1) }],
  ])("refuses %s before asking for a ticket", async (_label, overrides) => {
    const { params, deps, callTool } = setup(overrides);

    await expect(createOpsysCibleTicketMeta(params, deps)).rejects.toThrow();
    expect(callTool).not.toHaveBeenCalled();
  });

  it.each([
    ["disabled config", { kind: "disabled" }],
    ["invalid config", { kind: "invalid", reason: "broken" }],
  ] as const)("fails closed for %s", async (_label, contextConfig) => {
    const { params, deps, callTool } = setup({ config: contextConfig });

    await expect(createOpsysCibleTicketMeta(params, deps)).rejects.toThrow();
    expect(callTool).not.toHaveBeenCalled();
  });

  it("fails closed when the private server or ticket tool response is unavailable or malformed", async () => {
    const noServer = setup({ config: config({ contextServers: new Map() }) });
    await expect(createOpsysCibleTicketMeta(noServer.params, noServer.deps)).rejects.toThrow();
    expect(noServer.callTool).not.toHaveBeenCalled();

    const malformed = setup({
      response: { ok: true, resultat: { ticket: "", expire_le: "invalid" } },
    });
    const onIssued = vi.fn();
    await expect(
      createOpsysCibleTicketMeta({ ...malformed.params, onIssued }, malformed.deps),
    ).rejects.toThrow();
    expect(onIssued).not.toHaveBeenCalled();

    const expired = setup({
      response: {
        ok: true,
        resultat: { ticket: "opaque-ticket", expire_le: new Date(NOW - 1).toISOString() },
      },
    });
    await expect(createOpsysCibleTicketMeta(expired.params, expired.deps)).rejects.toThrow();
  });

  it.each(["m3_outil_non_declare", "m9_outil_non_declare", "m9_preparer_suivi_decision"])(
    "does not mint a ticket for undeclared mutation or readonly tool %s",
    async (toolName) => {
      const { params, deps, callTool } = setup({ toolName });

      await expect(createOpsysCibleTicketMeta(params, deps)).resolves.toBeUndefined();
      expect(callTool).not.toHaveBeenCalled();
    },
  );

  it.each(["opsys_m9", "opsys_m3"])(
    "routes the exact M9 opening only to its canonical server, received %s",
    async (serverName) => {
      const agentId = "m09-strategic-intelligence";
      const sessionKey = `agent:${agentId}:webchat:direct:suivi-fictif`;
      const toolName = "m9_ouvrir_suivi_decision";
      const { params, deps, callTool } = setup({
        serverName,
        toolName,
        sessionKey,
        config: config({
          agents: new Map([[agentId, []]]),
          affaireFromSession: new Set([agentId]),
          contextServers: new Map([[agentId, "opsys_context_m09-strategic-intelligence"]]),
          levels: new Map([[toolName, "N3"]]),
          targets: new Map([[toolName, { kind: "ticket" }]]),
        }),
      });
      const argumentsM9 = {
        evenement_id: "alerte-m8-fictive",
        empreinte_source: "0".repeat(64),
        action: "Analyser les causes de durée du chantier fictif",
        responsable_id: "responsable-fictif",
        echeance: "2026-10-20T09:00:00-04:00",
      };
      if (serverName !== "opsys_m9") {
        await expect(
          createOpsysCibleTicketMeta({ ...params, toolParams: argumentsM9 }, deps),
        ).rejects.toThrow(/tool\/server mismatch/);
        expect(callTool).not.toHaveBeenCalled();
        return;
      }
      await expect(
        createOpsysCibleTicketMeta({ ...params, toolParams: argumentsM9 }, deps),
      ).resolves.toStrictEqual({
        arguments: argumentsM9,
        meta: { "opsys/cibleTicket": "opaque-ticket-secret" },
      });
      expect(callTool).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({
          server: "opsys_context_m09-strategic-intelligence",
          tool: "opsys_contexte_creer_ticket_cible",
          args: {
            agent_id: agentId,
            cle_session: sessionKey,
            affaire_id: "LEAD-001",
            origine_affaire: "session",
            outil: toolName,
            arguments: argumentsM9,
          },
        }),
      );
    },
  );

  it("issues an N3 creation ticket for the exact M10 lead-bound draft args without changing them", async () => {
    const toolName = "m3_creer_devis";
    const businessArgs = {
      devis_id: "DEV-FICTIF-C02",
      lead_id: "LEAD-001",
      chantier_id: null,
      lignes: [],
      taux_marge: "0.20",
      horodatage: "2026-10-02T12:00:00+00:00",
    };
    const before = JSON.stringify(businessArgs);
    const activeConfig = config({
      agents: new Map([["m03-estimation", [toolName]]]),
      levels: new Map([...CONFIG_M3.levels, [toolName, "N3"]]),
      targets: new Map([...CONFIG_M3.targets, [toolName, { kind: "ticket" }]]),
    });
    const { params, deps, callTool } = setup({ config: activeConfig });
    params.toolName = toolName;
    params.toolParams = businessArgs;

    const meta = await createOpsysCibleTicketMeta(params, deps);

    expect(callTool).toHaveBeenCalledOnce();
    expect(callTool).toHaveBeenCalledWith(
      expect.objectContaining({
        server: "opsys_context_m03-estimation",
        tool: "opsys_contexte_creer_ticket_cible",
        args: {
          agent_id: "m03-estimation",
          cle_session: SESSION,
          affaire_id: "LEAD-001",
          origine_affaire: "demande",
          outil: toolName,
          arguments: businessArgs,
        },
      }),
    );
    expect(meta).toStrictEqual({
      arguments: businessArgs,
      meta: { "opsys/cibleTicket": "opaque-ticket-secret" },
    });
    expect(JSON.stringify(businessArgs)).toBe(before);
  });
});
