import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { callOpsysMcpTool } from "../../context-engine/opsys-contexte-mcp.js";
import { verifyOpsysRuntimeToolCall } from "./opsys-runtime-admission.js";

const mocks = vi.hoisted(() => ({ callOpsysMcpTool: vi.fn<typeof callOpsysMcpTool>() }));
vi.mock("../../context-engine/opsys-contexte-mcp.js", () => mocks);
const config: OpenClawConfig = {
  agents: {
    entries: {
      "m03-estimation": {
        opsysIsolation: { exec: "sandbox-required" },
        opsysRuntimeAdmission: { profileId: "base-m03-estimation", profileRevision: 2 },
      },
    },
  },
};
const commonNames = [
  "opsys_lire_artefact",
  "opsys_etat_budget",
  "opsys_demandes_approbation",
  "opsys_memoire_rechercher",
  "opsys_memoire_ajouter",
  "opsys_memoire_oublier",
];

describe("OPSYS exact shared MCP capability preflight", () => {
  beforeEach(() => {
    mocks.callOpsysMcpTool.mockReset();
  });

  it.each(commonNames)("revalidates %s through the private SQL permission route", async (name) => {
    mocks.callOpsysMcpTool.mockResolvedValue({
      ok: true,
      resultat: { autorise: true, revision_profil: 2 },
    });
    await verifyOpsysRuntimeToolCall({
      config,
      agentId: "m03-estimation",
      toolName: `opsys_m3__${name}`,
    });
    expect(mocks.callOpsysMcpTool).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        server: "opsys_runtime_base-m03-estimation",
        tool: "opsys_runtime_verifier_outil",
        args: { outil: `opsys_m3__${name}`, revision_profil: 2 },
      }),
    );
  });

  it("rejects a stale positive SQL response", async () => {
    mocks.callOpsysMcpTool.mockResolvedValue({
      ok: true,
      resultat: { autorise: true, revision_profil: 1 },
    });
    await expect(
      verifyOpsysRuntimeToolCall({
        config,
        agentId: "m03-estimation",
        toolName: "opsys_m3__opsys_etat_budget",
      }),
    ).rejects.toThrow("permission could not be verified");
  });

  it("does not reinterpret native Core memory or exec tools as departmental MCP tools", async () => {
    for (const name of ["memory_search", "memory_get", "read", "exec", "opsys_m3__opsys_invente"]) {
      await verifyOpsysRuntimeToolCall({ config, agentId: "m03-estimation", toolName: name });
    }
    expect(mocks.callOpsysMcpTool).not.toHaveBeenCalled();
  });
});
