// Preuve que la greffe du garde de contexte bloque réellement (OPSYS-AI PLAN T3.3-suite-b,
// ADR-0010, décision 4). Le garde seul est testé dans
// `src/context-engine/opsys-contexte-garde.test.ts`. Ici, on passe par la VRAIE
// `runBeforeToolCallHook`, sans aucun mock de module :
//   - un vrai `opsys/contexte.json`, écrit dans un dossier temporaire que `OPENCLAW_CONFIG_PATH`
//     désigne (le dossier que `readOpsysContexteConfig` résout en production) ;
//   - le vrai magasin d'état du garde (`opsysContexteGuardStore`), que le moteur remplit en
//     production ;
//   - l'horloge du garde est `Date.now` : on ne fige que `Date`.
// Chaque cas « laisse passer » porte un contrôle refusé dans les mêmes conditions. Si la
// configuration n'était pas lue, tout passerait et le test ne prouverait rien.
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import { OPSYS_CONTEXTE_CONFIG_FILENAME } from "../context-engine/opsys-contexte-config.js";
import {
  checkOpsysContexteToolCall,
  OPSYS_GUARD_MAX_AGE_MS,
  opsysContexteGuardStore,
  type OpsysGuardState,
} from "../context-engine/opsys-contexte-garde.js";
import {
  initializeGlobalHookRunner,
  resetGlobalHookRunner,
} from "../plugins/hook-runner-global.js";
import { addTestHook } from "../plugins/hooks.test-fixtures.js";
import { createEmptyPluginRegistry } from "../plugins/registry-empty.js";
import { setActivePluginRegistry } from "../plugins/runtime.js";
import type { PluginHookBeforeToolCallResult, PluginHookRegistration } from "../plugins/types.js";
import { runBeforeToolCallHook } from "./agent-tools.before-tool-call.js";
import type { HookOutcome } from "./agent-tools.before-tool-call.types.js";

const tempDirs = useAutoCleanupTempDirTracker(afterEach);

const NOW = Date.parse("2026-09-28T10:15:00.000+00:00");
const AGENT = "m03-estimation";
const SESSION = `agent:${AGENT}:main`;
const OTHER_SESSION = `agent:${AGENT}:autre-session`;
const TOOL_N3 = "opsys_m3__m3_estimer_projet";
const PARAMS = { fictif: true, lead_id: "LEAD-001" };
const LAISSE_PASSER = { blocked: false, params: PARAMS };

// Ce que `openclaw.py` génère : les niveaux N0 à N5 des outils OPSYS et l'agent que le moteur sert.
const CONTEXTE_ACTIF = {
  fictif: true,
  actif: true,
  agents: { [AGENT]: { depot: ["m3_estimer_projet"] } },
  niveaux: {
    m3_estimer_projet: "N3",
    m3_lire_devis: "N0",
    m4_proposer_cedule: "N1",
    m10_deposer_faits_candidats: "N2",
    m4_notifier_client_completion: "N4",
    m5_enregistrer_mouvement: "N5",
  },
};

function ready(nbOuverts: number, atMs = NOW): OpsysGuardState {
  return { kind: "ready", affaireId: "LEAD-001", nbOuverts, atMs };
}

function unavailable(reason: string, atMs = NOW): OpsysGuardState {
  return { kind: "unavailable", reason, atMs };
}

function requireVeto(outcome: HookOutcome) {
  if (!outcome.blocked || outcome.kind !== "veto") {
    throw new Error(`un veto était attendu, reçu : ${JSON.stringify(outcome)}`);
  }
  return outcome;
}

function registerBeforeToolCallHook(handler: () => PluginHookBeforeToolCallResult | undefined) {
  const registry = createEmptyPluginRegistry();
  addTestHook({
    registry,
    pluginId: "plugin-de-test",
    hookName: "before_tool_call",
    handler: handler as PluginHookRegistration["handler"],
  });
  setActivePluginRegistry(registry);
  initializeGlobalHookRunner(registry);
}

describe("greffe OPSYS de runBeforeToolCallHook : garde de contexte des outils N3 et plus", () => {
  let configRoot = "";

  function writeContexte(content: unknown): void {
    const opsysDir = path.join(configRoot, "opsys");
    fs.mkdirSync(opsysDir, { recursive: true });
    fs.writeFileSync(path.join(opsysDir, OPSYS_CONTEXTE_CONFIG_FILENAME), JSON.stringify(content));
  }

  function callTool(
    overrides: { toolName?: string; sessionKey?: string; agentId?: string } = {},
  ): Promise<HookOutcome> {
    return runBeforeToolCallHook({
      toolName: overrides.toolName ?? TOOL_N3,
      params: PARAMS,
      ctx: {
        sessionKey: overrides.sessionKey ?? SESSION,
        agentId: overrides.agentId ?? AGENT,
      },
    });
  }

  beforeEach(() => {
    configRoot = tempDirs.make("opsys-greffe-garde-");
    vi.stubEnv("OPENCLAW_CONFIG_PATH", path.join(configRoot, "openclaw.json"));
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    opsysContexteGuardStore.clear();
    resetGlobalHookRunner();
    setActivePluginRegistry(createEmptyPluginRegistry());
  });

  afterEach(() => {
    opsysContexteGuardStore.clear();
    resetGlobalHookRunner();
    setActivePluginRegistry(createEmptyPluginRegistry());
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  describe("contexte.json actif, outil N3 de l'agent servi", () => {
    beforeEach(() => {
      writeContexte(CONTEXTE_ACTIF);
    });

    it("refuse sans état enregistré pour la session, avec le message du garde", async () => {
      const veto = requireVeto(await callTool());

      expect(veto.reason).toContain("Action bloquée");
      expect(veto.reason).toContain("n'a pas été évalué pour ce tour");
      expect(veto.reason).toContain("Réessaie quand il est disponible");
      expect(veto.params).toBe(PARAMS);
      // Le message du veto est celui du garde, mot pour mot.
      const decision = checkOpsysContexteToolCall({
        toolName: TOOL_N3,
        sessionKey: SESSION,
        agentId: AGENT,
      });
      expect(decision).toStrictEqual({ block: true, reason: veto.reason });
    });

    it.each([
      { title: "nom vu par le modèle", toolName: "opsys_m3__m3_estimer_projet" },
      { title: "nom nu", toolName: "m3_estimer_projet" },
      { title: "nom en majuscules (normalisé)", toolName: "OPSYS_M3__M3_ESTIMER_PROJET" },
    ])("refuse l'outil N3 sous son $title", async ({ toolName }) => {
      const veto = requireVeto(await callTool({ toolName }));

      expect(veto.reason).toContain("Action bloquée");
    });

    it.each([
      { toolName: "opsys_m4__m4_notifier_client_completion", level: "N4" },
      { toolName: "opsys_m5__m5_enregistrer_mouvement", level: "N5" },
    ])("refuse aussi l'outil $toolName (niveau $level) sans état", async ({ toolName }) => {
      const veto = requireVeto(await callTool({ toolName }));

      expect(veto.reason).toContain("Action bloquée");
    });

    it("laisse passer quand l'état est récent et sans signal ouvert", async () => {
      opsysContexteGuardStore.set(SESSION, ready(0));

      expect(await callTool()).toStrictEqual(LAISSE_PASSER);

      // Contrôle : sans l'état, le même appel est refusé.
      opsysContexteGuardStore.clear();
      expect(requireVeto(await callTool()).reason).toContain("Action bloquée");
    });

    it("refuse tant qu'un signal critique est ouvert, puis laisse passer une fois pris en compte", async () => {
      opsysContexteGuardStore.set(SESSION, ready(2));

      const veto = requireVeto(await callTool());

      expect(veto.reason).toContain("2 signal(aux) critique(s) OUVERT(S)");
      expect(veto.reason).toContain("LEAD-001");
      expect(veto.reason).toContain("m10_prendre_en_compte_signal");
      expect(veto.reason).toContain("Tu ne peux pas le faire à sa place");

      opsysContexteGuardStore.set(SESSION, ready(0));
      expect(await callTool()).toStrictEqual(LAISSE_PASSER);
    });

    it("refuse quand le contexte était indisponible, et dit pourquoi", async () => {
      opsysContexteGuardStore.set(
        SESSION,
        unavailable("moteur métier injoignable ou trop lent (ECONNREFUSED)"),
      );

      const veto = requireVeto(await callTool());

      expect(veto.reason).toContain("indisponible");
      expect(veto.reason).toContain("moteur métier injoignable ou trop lent (ECONNREFUSED)");
      expect(veto.reason).toContain("Ne contourne pas ce blocage");
    });

    it("refuse un état périmé (plus de 15 minutes), et pas une milliseconde avant", async () => {
      expect(OPSYS_GUARD_MAX_AGE_MS).toBe(15 * 60 * 1_000);
      opsysContexteGuardStore.set(SESSION, ready(0));

      vi.setSystemTime(NOW + OPSYS_GUARD_MAX_AGE_MS);
      expect(await callTool()).toStrictEqual(LAISSE_PASSER);

      vi.setSystemTime(NOW + OPSYS_GUARD_MAX_AGE_MS + 1);
      const veto = requireVeto(await callTool());
      expect(veto.reason).toContain("périmée");
    });

    it("ne lit que l'état de la session de l'appel", async () => {
      opsysContexteGuardStore.set(OTHER_SESSION, ready(0));

      const veto = requireVeto(await callTool());

      expect(veto.reason).toContain("n'a pas été évalué");
      expect(await callTool({ sessionKey: OTHER_SESSION })).toStrictEqual(LAISSE_PASSER);
    });
  });

  describe("ce que le garde ne touche jamais", () => {
    beforeEach(() => {
      writeContexte(CONTEXTE_ACTIF);
    });

    it.each(["read", "exec", "memory_search", "autre_serveur__lire_fichier"])(
      "laisse passer l'outil %s, qui n'est pas un outil OPSYS, avec ou sans contexte utilisable",
      async (toolName) => {
        // Contrôle : dans les mêmes conditions, l'outil OPSYS N3 est refusé.
        expect(requireVeto(await callTool()).reason).toContain("Action bloquée");

        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
        opsysContexteGuardStore.set(SESSION, unavailable("moteur injoignable"));
        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
        opsysContexteGuardStore.set(SESSION, ready(3));
        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
      },
    );

    it.each([
      { toolName: "opsys_m3__m3_lire_devis", level: "N0" },
      { toolName: "opsys_m4__m4_proposer_cedule", level: "N1" },
      { toolName: "opsys_m10__m10_deposer_faits_candidats", level: "N2" },
    ])(
      "laisse passer l'outil $toolName (niveau $level), avec ou sans contexte utilisable",
      async ({ toolName }) => {
        // Contrôle : dans les mêmes conditions, l'outil OPSYS N3 est refusé.
        expect(requireVeto(await callTool()).reason).toContain("Action bloquée");

        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
        opsysContexteGuardStore.set(SESSION, unavailable("moteur injoignable"));
        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
        opsysContexteGuardStore.set(SESSION, ready(3));
        expect(await callTool({ toolName })).toStrictEqual(LAISSE_PASSER);
      },
    );

    it("laisse passer un agent que la configuration ne nomme pas", async () => {
      // Contrôle : l'agent servi, lui, est refusé dans les mêmes conditions.
      expect(requireVeto(await callTool()).reason).toContain("Action bloquée");

      const outcome = await callTool({
        sessionKey: "agent:m01-front-office:main",
        agentId: "m01-front-office",
      });

      expect(outcome).toStrictEqual(LAISSE_PASSER);
    });
  });

  describe("sans contexte.json actif : rien ne change", () => {
    it("laisse tout passer sans contexte.json, et refuse dès que le fichier est actif", async () => {
      expect(await callTool()).toStrictEqual(LAISSE_PASSER);
      expect(await callTool({ toolName: "opsys_m5__m5_enregistrer_mouvement" })).toStrictEqual(
        LAISSE_PASSER,
      );

      // Contrôle : le même appel, sans état, est refusé une fois le fichier écrit.
      writeContexte(CONTEXTE_ACTIF);
      expect(requireVeto(await callTool()).reason).toContain("Action bloquée");
    });

    it("laisse tout passer si contexte.json n'est pas actif, et refuse dès qu'il l'est", async () => {
      writeContexte({ ...CONTEXTE_ACTIF, actif: false });
      expect(await callTool()).toStrictEqual(LAISSE_PASSER);

      // Contrôle : le même appel, sans état, est refusé une fois le fichier actif.
      writeContexte(CONTEXTE_ACTIF);
      expect(requireVeto(await callTool()).reason).toContain("Action bloquée");
    });
  });

  describe("place du garde dans la chaîne before_tool_call", () => {
    beforeEach(() => {
      writeContexte(CONTEXTE_ACTIF);
    });

    it("refuse avant les hooks de plugin : un hook qui laisserait passer n'est pas appelé", async () => {
      const handler = vi.fn<() => PluginHookBeforeToolCallResult | undefined>();
      registerBeforeToolCallHook(handler);

      const veto = requireVeto(await callTool());

      expect(veto.reason).toContain("Action bloquée");
      expect(handler).not.toHaveBeenCalled();
    });

    it("garde satisfait, la chaîne continue : le hook de plugin est appelé et garde son mot", async () => {
      opsysContexteGuardStore.set(SESSION, ready(0));
      const handler = vi.fn<() => PluginHookBeforeToolCallResult | undefined>();
      handler.mockReturnValue({ block: true, blockReason: "refus du plugin de test" });
      registerBeforeToolCallHook(handler);

      const outcome = await callTool();

      expect(outcome).toMatchObject({
        blocked: true,
        kind: "veto",
        deniedReason: "plugin-before-tool-call",
        reason: "refus du plugin de test",
      });
      expect(handler).toHaveBeenCalledOnce();
    });
  });
});
