import { describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { AgentEntrySchema } from "../config/zod-schema.agent-runtime.js";
import {
  createOpsysCfoGrantTicketMeta,
  OPSYS_CFO_MCP_SERVER,
  type OpsysCfoGrantTicketDeps,
} from "./opsys-cfo-grant-ticket.js";

const NOW = Date.parse("2026-10-01T12:00:00.000Z");
const AGENT_ID = "opsys-agent-m5-cfo-agent";
const PROFILE_ID = "m5-cfo-agent";
const SESSION = `agent:${AGENT_ID}:main`;
const TOOL = "m5_preparer_dossier_decision_cfo";
const ARGS = { question_posee: "Prévoir les liquidités", aujourd_hui: "2026-10-01" };
const TICKET = "synthetic-cfo-grant-ticket-opaque";

function config(
  overrides: { profileId?: string; profileRevision?: number; legacy?: boolean } = {},
): OpenClawConfig {
  const binding: { profileId: string; profileRevision?: number } = {
    profileId: overrides.profileId ?? PROFILE_ID,
  };
  if (!overrides.legacy) binding.profileRevision = overrides.profileRevision ?? 4;
  return { agents: { entries: { [AGENT_ID]: { opsysRuntimeAdmission: binding } } } };
}

function deps(
  overrides: { response?: unknown; callTool?: OpsysCfoGrantTicketDeps["callTool"] } = {},
) {
  return {
    nowMs: () => NOW,
    callTool:
      overrides.callTool ??
      vi.fn().mockResolvedValue({
        ok: true,
        resultat: { ticket: TICKET, expire_le: new Date(NOW + 90_000).toISOString() },
      }),
  } satisfies OpsysCfoGrantTicketDeps;
}

const SIGNAL = new AbortController().signal;

describe("OPSYS CFO grant ticket client", () => {
  it.each(["m5_preparer_dossier_decision_cfo", "m5_preparer_decision_capital"])(
    "issues a profile-revision-bound private ticket before %s",
    async (toolName) => {
      const fixture = deps();
      const issuer = vi.mocked(fixture.callTool!);
      const result = await createOpsysCfoGrantTicketMeta(
        {
          config: config(),
          serverName: OPSYS_CFO_MCP_SERVER,
          toolName,
          toolParams: ARGS,
          sessionKey: SESSION,
          signal: SIGNAL,
        },
        fixture,
      );

      expect(issuer).toHaveBeenCalledWith({
        config: config(),
        server: "opsys_runtime_m5-cfo-agent",
        tool: "opsys_runtime_cfo_ticket",
        args: { outil: toolName, arguments: ARGS, revision_profil: 4 },
        timeoutMs: 10_000,
        signal: SIGNAL,
      });
      expect(result).toStrictEqual({
        arguments: ARGS,
        meta: { "opsys/cfoGrantTicket": TICKET },
      });
    },
  );

  it("does not issue for any tool outside the two CFO read tools", async () => {
    const fixture = deps({ callTool: vi.fn() });
    await expect(
      createOpsysCfoGrantTicketMeta(
        {
          config: undefined,
          serverName: "opsys_m5",
          toolName: "m5_enregistrer_paiement_facture",
          toolParams: {},
          sessionKey: undefined,
          signal: SIGNAL,
        },
        fixture,
      ),
    ).resolves.toBeUndefined();
    expect(fixture.callTool).not.toHaveBeenCalled();
  });

  it("requires the exact M5 business server before contacting the issuer", async () => {
    const fixture = deps({ callTool: vi.fn() });
    await expect(
      createOpsysCfoGrantTicketMeta(
        {
          config: config(),
          serverName: "opsys_other",
          toolName: TOOL,
          toolParams: ARGS,
          sessionKey: SESSION,
          signal: SIGNAL,
        },
        fixture,
      ),
    ).rejects.toThrow(/tool\/server mismatch/);
    expect(fixture.callTool).not.toHaveBeenCalled();
  });

  it.each([
    ["legacy profileId-only configuration", { legacy: true }],
    ["profile binding mismatch", { profileId: "some-other-profile" }],
  ])("refuses %s before requesting a ticket", async (_label, override) => {
    const fixture = deps({ callTool: vi.fn() });
    await expect(
      createOpsysCfoGrantTicketMeta(
        {
          config: config(override),
          serverName: OPSYS_CFO_MCP_SERVER,
          toolName: TOOL,
          toolParams: ARGS,
          sessionKey: SESSION,
          signal: SIGNAL,
        },
        fixture,
      ),
    ).rejects.toThrow(/profile revision is unavailable/);
    expect(fixture.callTool).not.toHaveBeenCalled();
  });

  it("refuses a human or non-OPSYS agent session instead of minting a profile ticket", async () => {
    const fixture = deps({ callTool: vi.fn() });
    await expect(
      createOpsysCfoGrantTicketMeta(
        {
          config: config(),
          serverName: OPSYS_CFO_MCP_SERVER,
          toolName: TOOL,
          toolParams: ARGS,
          sessionKey: "agent:main:main",
          signal: SIGNAL,
        },
        fixture,
      ),
    ).rejects.toThrow(/finance agent profile is required/);
    expect(fixture.callTool).not.toHaveBeenCalled();
  });

  it.each([
    ["absent", { ok: false, erreur: "refus_metier" }],
    ["expired", { ok: true, resultat: { ticket: TICKET, expire_le: new Date(NOW).toISOString() } }],
    [
      "overlong",
      { ok: true, resultat: { ticket: TICKET, expire_le: new Date(NOW + 96_000).toISOString() } },
    ],
  ])("refuses an %s issuer ticket", async (_label, response) => {
    const fixture = deps({ callTool: vi.fn().mockResolvedValue(response) });
    await expect(
      createOpsysCfoGrantTicketMeta(
        {
          config: config(),
          serverName: OPSYS_CFO_MCP_SERVER,
          toolName: TOOL,
          toolParams: ARGS,
          sessionKey: SESSION,
          signal: SIGNAL,
        },
        fixture,
      ),
    ).rejects.toThrow(/invalid or expired ticket/);
  });

  it("accepts legacy admission profile IDs but requires a positive optional persisted revision", () => {
    expect(
      AgentEntrySchema.safeParse({ id: AGENT_ID, opsysRuntimeAdmission: { profileId: PROFILE_ID } })
        .success,
    ).toBe(true);
    expect(
      AgentEntrySchema.safeParse({
        id: AGENT_ID,
        opsysRuntimeAdmission: { profileId: PROFILE_ID, profileRevision: 4 },
      }).success,
    ).toBe(true);
    expect(
      AgentEntrySchema.safeParse({
        id: AGENT_ID,
        opsysRuntimeAdmission: { profileId: PROFILE_ID, profileRevision: 0 },
      }).success,
    ).toBe(false);
  });
});
