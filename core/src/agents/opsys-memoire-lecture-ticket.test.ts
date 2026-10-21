import { describe, expect, it, vi } from "vitest";
import type { OpsysContexteConfigResult } from "../context-engine/opsys-contexte-config.js";
import {
  createOpsysMemoireLectureMeta,
  parseOpsysMemoirePolicy,
} from "./opsys-memoire-lecture-ticket.js";

const NOW = Date.parse("2026-10-02T10:00:00Z");
const SESSION = "agent:m01-front-office:webchat:direct:fictif-A";
const SIGNAL = new AbortController().signal;
function policy(mode: "global" | "client_session" = "client_session") {
  return {
    version: 1,
    departements: { "m01-front-office": mode },
    agents: { "m01-front-office": { departement: "m01-front-office", mode } },
    procedures_globales: ["procedures"],
  };
}
function deps(mode: "global" | "client_session" = "client_session") {
  const context: OpsysContexteConfigResult = {
    kind: "enabled",
    config: {
      server: "opsys_m10",
      packetTool: "m10_paquet_contexte_affaire",
      depositTool: "m10_deposer_faits_candidats",
      affaireTool: "m10_affaire_de_la_session",
      timeoutMs: 4000,
      agents: new Map([["m01-front-office", []]]),
      affaireFromSession: new Set(["m01-front-office"]),
      contextServers: new Map([["m01-front-office", "opsys_context_m01-front-office"]]),
      levels: new Map(),
      targets: new Map(),
    },
  };
  return {
    readPolicy: () => policy(mode),
    readContext: () => context,
    nowMs: () => NOW,
    callTool: vi.fn().mockResolvedValue({
      ok: true,
      resultat: {
        ticket: "ticket-fictif-opaque",
        expire_le: new Date(NOW + 120000).toISOString(),
      },
    }),
  };
}
const call = {
  config: undefined,
  serverName: "opsys_m1",
  toolName: "opsys_memoire_rechercher",
  toolParams: { requete: "préférence fictive" },
  sessionKey: SESSION,
  signal: SIGNAL,
};

describe("OPSYS server memory read authority", () => {
  it.each(["cycle", "bigint", "toJSON-array"])(
    "refuses %s final arguments before contacting the private issuer",
    async (kind) => {
      const fixture = deps();
      const args: Record<string, unknown> = { requete: "préférence fictive" };
      if (kind === "cycle") {
        args.self = args;
      } else if (kind === "bigint") {
        args.extra = 1n;
      } else {
        args.toJSON = () => [];
      }
      await expect(
        createOpsysMemoireLectureMeta({ ...call, toolParams: args }, fixture),
      ).rejects.toThrow(kind === "toJSON-array" ? /JSON object/ : /not serializable/);
      expect(fixture.callTool).not.toHaveBeenCalled();
    },
  );
  it("seals the final argument snapshot using the actual session, without model-nominated case or client", async () => {
    const fixture = deps();
    const args = { requete: "préférence fictive", k: 3 };
    const result = await createOpsysMemoireLectureMeta({ ...call, toolParams: args }, fixture);
    args.k = 8;
    expect(fixture.callTool).toHaveBeenCalledWith({
      config: undefined,
      server: "opsys_context_m01-front-office",
      tool: "opsys_contexte_creer_ticket_memoire",
      args: {
        agent_id: "m01-front-office",
        cle_session: SESSION,
        arguments: { requete: "préférence fictive", k: 3 },
      },
      timeoutMs: 4000,
      signal: SIGNAL,
    });
    expect(result).toStrictEqual({
      arguments: { requete: "préférence fictive", k: 3 },
      meta: { "opsys/memoireLectureTicket": "ticket-fictif-opaque" },
    });
  });
  it("keeps an explicitly global department read without a client grant", async () => {
    const fixture = deps("global");
    const args = { requete: "préférence", sujet: "client:B-fictif" };
    expect(
      await createOpsysMemoireLectureMeta({ ...call, toolParams: args }, fixture),
    ).toStrictEqual({ arguments: args, meta: {} });
    expect(fixture.callTool).not.toHaveBeenCalled();
  });
  it("keeps the separate procedure-only SQL gate without requiring a case", async () => {
    const fixture = deps();
    expect(
      await createOpsysMemoireLectureMeta(
        { ...call, toolParams: { requete: "procédure", portees: ["procedures"] } },
        fixture,
      ),
    ).toMatchObject({ meta: {} });
    expect(fixture.callTool).not.toHaveBeenCalled();
  });
  it.each([undefined, {}, { ...policy(), version: 0 }, { ...policy(), agents: {} }])(
    "refuses absent or unclassified policy before contacting the issuer",
    async (raw) => {
      const fixture = { ...deps(), readPolicy: () => raw };
      await expect(createOpsysMemoireLectureMeta(call, fixture)).rejects.toThrow(
        /OPSYS memory refused/,
      );
      expect(fixture.callTool).not.toHaveBeenCalled();
    },
  );
  it.each([undefined, "agent:autre:direct:fictif-A", "main"])(
    "refuses an absent or unrelated session %s",
    async (sessionKey) => {
      const fixture = deps();
      await expect(
        createOpsysMemoireLectureMeta({ ...call, sessionKey }, fixture),
      ).rejects.toThrow();
      expect(fixture.callTool).not.toHaveBeenCalled();
    },
  );
  it("refuses a mismatched business server", async () => {
    const fixture = deps();
    await expect(
      createOpsysMemoireLectureMeta({ ...call, serverName: "opsys_m2" }, fixture),
    ).rejects.toThrow(/mismatch/);
    expect(fixture.callTool).not.toHaveBeenCalled();
  });
  it("refuses a client policy with no private context route", async () => {
    const fixture = {
      ...deps(),
      readContext: (): OpsysContexteConfigResult => ({ kind: "absent" }),
    };
    await expect(createOpsysMemoireLectureMeta(call, fixture)).rejects.toThrow(
      /authority is unavailable/,
    );
    expect(fixture.callTool).not.toHaveBeenCalled();
  });
  it.each([
    { ok: false },
    { ok: true, resultat: { ticket: "fictif", expire_le: new Date(NOW).toISOString() } },
    { ok: true, resultat: { ticket: "fictif", expire_le: new Date(NOW + 126000).toISOString() } },
  ])("refuses invalid or expired grants", async (response) => {
    const fixture = deps();
    fixture.callTool.mockResolvedValue(response);
    await expect(createOpsysMemoireLectureMeta(call, fixture)).rejects.toThrow(
      /invalid or expired/,
    );
  });
  it("does not issue a read grant for one of the existing nine mutations", async () => {
    const fixture = deps();
    expect(
      await createOpsysMemoireLectureMeta(
        { ...call, toolName: "m2_transitionner_statut" },
        fixture,
      ),
    ).toBeUndefined();
    expect(fixture.callTool).not.toHaveBeenCalled();
  });
  it.each([
    { ...policy(), departements: { "m01-front-office": [] } },
    { ...policy(), agents: { "m01-front-office": { departement: [], mode: "client_session" } } },
  ])("refuses malformed classification values", (raw) => {
    expect(() => parseOpsysMemoirePolicy(raw)).toThrow(/OPSYS memory refused/);
  });
});
