// OPSYS context engine configuration (OPSYS-AI PLAN T3.3-suite): `opsys/contexte.json` is off by
// default and fail-closed once enabled.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import {
  OPSYS_CONTEXTE_CONFIG_FILENAME,
  parseOpsysContexteConfig,
  readOpsysContexteConfig,
} from "./opsys-contexte-config.js";

const tempDirs = useAutoCleanupTempDirTracker(afterEach);

function writeConfig(dir: string, content: string): void {
  fs.writeFileSync(path.join(dir, OPSYS_CONTEXTE_CONFIG_FILENAME), content);
}

const M3 = {
  "m03-estimation": {
    depot: ["m3_estimer_projet"],
    serveur_contexte: "opsys_context_m03-estimation",
  },
};
// Levels N of the OPSYS tools, as `openclaw.py` generates them: required once the engine is active.
const NIVEAUX = { m3_estimer_projet: "N3", m3_lire_devis: "N0" };
const CIBLES = {
  m3_estimer_projet: { type: "affaire", chemin: ["contrat", "lead_id"], identite: "lead" },
};

describe("readOpsysContexteConfig", () => {
  it("is off when there is no contexte.json", () => {
    const dir = tempDirs.make("opsys-contexte-config-");

    expect(readOpsysContexteConfig({ dir })).toStrictEqual({ kind: "absent" });
  });

  it("is off when the OPSYS folder does not exist yet", () => {
    const dir = path.join(tempDirs.make("opsys-contexte-config-"), "missing");

    expect(readOpsysContexteConfig({ dir })).toStrictEqual({ kind: "absent" });
  });

  it("reads the enabled configuration from the file", () => {
    const dir = tempDirs.make("opsys-contexte-config-");
    writeConfig(
      dir,
      JSON.stringify({ version: 2, actif: true, agents: M3, niveaux: NIVEAUX, cibles: CIBLES }),
    );

    const result = readOpsysContexteConfig({ dir });

    expect(result).toMatchObject({
      kind: "enabled",
      config: { server: "opsys_m10", timeoutMs: 4_000 },
    });
  });

  it("requires regenerating an old active fragment instead of using its shared M10 identity", () => {
    const dir = tempDirs.make("opsys-contexte-config-");
    writeConfig(dir, JSON.stringify({ actif: true, agents: M3, niveaux: NIVEAUX }));

    expect(readOpsysContexteConfig({ dir })).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("régénérer avec `opsys metier openclaw configurer`"),
    });
  });

  it("refuses a file that is not JSON instead of guessing the operator's intent", () => {
    const dir = tempDirs.make("opsys-contexte-config-");
    writeConfig(dir, "{ actif: true");

    const result = readOpsysContexteConfig({ dir });

    expect(result).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("not valid JSON"),
    });
  });

  it("refuses a file that cannot be read", () => {
    const dir = tempDirs.make("opsys-contexte-config-");
    fs.mkdirSync(path.join(dir, OPSYS_CONTEXTE_CONFIG_FILENAME));

    const result = readOpsysContexteConfig({ dir });

    expect(result).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("cannot read"),
    });
  });
});

describe("parseOpsysContexteConfig", () => {
  it.each([
    { title: "an empty object", raw: {} },
    { title: "actif false", raw: { actif: false, agents: M3 } },
    { title: "actif as a string", raw: { actif: "true", agents: M3 } },
    { title: "actif as a number", raw: { actif: 1, agents: M3 } },
  ])("stays off for $title", ({ raw }) => {
    expect(parseOpsysContexteConfig(raw)).toStrictEqual({ kind: "disabled" });
  });

  it("applies the documented defaults to a minimal enabled configuration", () => {
    const result = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      agents: M3,
      niveaux: NIVEAUX,
      cibles: CIBLES,
    });

    expect(result).toStrictEqual({
      kind: "enabled",
      config: {
        server: "opsys_m10",
        packetTool: "m10_paquet_contexte_affaire",
        depositTool: "m10_deposer_faits_candidats",
        affaireTool: "m10_affaire_de_la_session",
        timeoutMs: 4_000,
        agents: new Map([["m03-estimation", ["m3_estimer_projet"]]]),
        affaireFromSession: new Set(),
        contextServers: new Map([["m03-estimation", "opsys_context_m03-estimation"]]),
        levels: new Map([
          ["m3_estimer_projet", "N3"],
          ["m3_lire_devis", "N0"],
        ]),
        targets: new Map([
          [
            "m3_estimer_projet",
            { kind: "affaire", path: ["contrat", "lead_id"], identity: "lead" },
          ],
        ]),
      },
    });
  });

  it("keeps custom names, delay and per-agent deposit tools as given", () => {
    const result = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      serveur: "opsys_memoire",
      outil_paquet: "m10_paquet_contexte_affaire",
      outil_depot: "m10_deposer_faits_candidats",
      outil_affaire: "m10_affaire_de_la_session",
      delai_ms: 1_500,
      agents: {
        "m03-estimation": {
          depot: ["m3_estimer_projet", "m3_estimer_projet", "m3_qualifier_photos"],
          serveur_contexte: "opsys_context_m03-estimation",
        },
        "m04-field-ops": { serveur_contexte: "opsys_context_m04-field-ops" },
      },
      niveaux: NIVEAUX,
      cibles: CIBLES,
    });

    expect(result).toStrictEqual({
      kind: "enabled",
      config: {
        server: "opsys_memoire",
        packetTool: "m10_paquet_contexte_affaire",
        depositTool: "m10_deposer_faits_candidats",
        affaireTool: "m10_affaire_de_la_session",
        timeoutMs: 1_500,
        agents: new Map([
          ["m03-estimation", ["m3_estimer_projet", "m3_qualifier_photos"]],
          ["m04-field-ops", []],
        ]),
        affaireFromSession: new Set(),
        contextServers: new Map([
          ["m03-estimation", "opsys_context_m03-estimation"],
          ["m04-field-ops", "opsys_context_m04-field-ops"],
        ]),
        levels: new Map([
          ["m3_estimer_projet", "N3"],
          ["m3_lire_devis", "N0"],
        ]),
        targets: new Map([
          [
            "m3_estimer_projet",
            { kind: "affaire", path: ["contrat", "lead_id"], identity: "lead" },
          ],
        ]),
      },
    });
  });

  it.each([
    { title: "a JSON array", raw: [], reason: "must contain a JSON object" },
    { title: "no agents", raw: { actif: true }, reason: '"agents"' },
    { title: "an empty agents map", raw: { actif: true, agents: {} }, reason: '"agents"' },
    {
      title: "agents as a list",
      raw: { actif: true, agents: ["m03-estimation"] },
      reason: '"agents"',
    },
    {
      title: "an agent id that is not an id",
      raw: { actif: true, agents: { "m03 estimation": {} } },
      reason: "invalid agent id",
    },
    {
      title: "agent settings that are not an object",
      raw: { actif: true, agents: { "m03-estimation": ["m3_estimer_projet"] } },
      reason: '"agents.m03-estimation" must be an object',
    },
    {
      title: "a deposit list that is not a list",
      raw: { actif: true, agents: { "m03-estimation": { depot: "m3_estimer_projet" } } },
      reason: ".depot",
    },
    {
      title: "a deposit tool that is not a department tool",
      raw: { actif: true, agents: { "m03-estimation": { depot: ["opsys_etat_budget"] } } },
      reason: ".depot",
    },
    {
      title: "a server name with a slash",
      raw: { actif: true, serveur: "opsys/m10", agents: M3 },
      reason: '"serveur"',
    },
    {
      title: "a packet tool that is not a department tool",
      raw: { actif: true, outil_paquet: "lire tout", agents: M3 },
      reason: '"outil_paquet"',
    },
    {
      title: "a deposit tool that is not a department tool",
      raw: { actif: true, outil_depot: 7, agents: M3 },
      reason: '"outil_depot"',
    },
    {
      title: "a delay below the floor",
      raw: { actif: true, delai_ms: 10, agents: M3 },
      reason: '"delai_ms"',
    },
    {
      title: "a delay above the cap",
      raw: { actif: true, delai_ms: 60_000, agents: M3 },
      reason: '"delai_ms"',
    },
    {
      title: "a fractional delay",
      raw: { actif: true, delai_ms: 1_000.5, agents: M3 },
      reason: '"delai_ms"',
    },
  ])("is invalid, and says which key to fix, for $title", ({ raw, reason }) => {
    expect(parseOpsysContexteConfig(raw)).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining(reason),
    });
  });
});

describe("parseOpsysContexteConfig: where the case comes from, and the levels of the tools", () => {
  it("takes the case from the request for an agent that does not say otherwise, and from the session when told", () => {
    const result = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      agents: {
        "m03-estimation": {
          depot: ["m3_estimer_projet"],
          serveur_contexte: "opsys_context_m03-estimation",
        },
        "m04-field-ops": { affaire: "demande", serveur_contexte: "opsys_context_m04-field-ops" },
        "m01-front-office": {
          affaire: "session",
          serveur_contexte: "opsys_context_m01-front-office",
        },
      },
      niveaux: NIVEAUX,
      cibles: CIBLES,
    });

    expect(result).toMatchObject({ kind: "enabled" });
    if (result.kind === "enabled") {
      expect([...result.config.affaireFromSession]).toStrictEqual(["m01-front-office"]);
      expect(result.config.affaireTool).toBe("m10_affaire_de_la_session");
    }
  });

  it("keeps the levels exactly as OPSYS generated them", () => {
    const result = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      agents: M3,
      niveaux: {
        m3_estimer_projet: "N3",
        m4_notifier_client_completion: "N4",
        m5_enregistrer_mouvement: "N5",
        m4_pointer: "N2",
      },
      cibles: {
        m3_estimer_projet: CIBLES.m3_estimer_projet,
        m4_notifier_client_completion: { type: "inconnue" },
        m5_enregistrer_mouvement: { type: "globale" },
      },
    });

    expect(result).toMatchObject({ kind: "enabled" });
    if (result.kind === "enabled") {
      expect(Object.fromEntries(result.config.levels)).toStrictEqual({
        m3_estimer_projet: "N3",
        m4_notifier_client_completion: "N4",
        m5_enregistrer_mouvement: "N5",
        m4_pointer: "N2",
      });
    }
  });

  it("accepts an explicit ticket target only for the approved M2/M3 case mutations", () => {
    const ticketTools = [
      "m2_transitionner_statut",
      "m2_reassigner_lead",
      "m2_enregistrer_interaction",
      "m2_preparer_relance",
      "m2_enregistrer_consentement_contact",
      "m2_marquer_chantier_termine",
      "m3_marquer_devis_accepte",
      "m3_demander_envoi_devis",
      "m3_creer_devis",
    ];
    const levels = Object.fromEntries([
      ...ticketTools.map((tool) => [tool, "N3"]),
      ["m4_outil_non_declare", "N3"],
    ]);
    const targets = Object.fromEntries([
      ...ticketTools.map((tool) => [tool, { type: "ticket" }]),
      ["m4_outil_non_declare", { type: "inconnue" }],
    ]);
    const valid = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      agents: M3,
      niveaux: levels,
      cibles: targets,
    });
    expect(valid.kind).toBe("enabled");
    if (valid.kind === "enabled") {
      for (const tool of ticketTools) {
        expect(valid.config.targets.get(tool)).toStrictEqual({ kind: "ticket" });
      }
      expect(valid.config.targets.get("m4_outil_non_declare")).toStrictEqual({ kind: "unknown" });
    }
    const invalid = parseOpsysContexteConfig({
      version: 2,
      actif: true,
      agents: M3,
      niveaux: { m4_outil_non_declare: "N3" },
      cibles: { m4_outil_non_declare: { type: "ticket" } },
    });
    expect(invalid).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("cannot use the ticket target contract"),
    });
  });

  it.each([
    {
      title: "an agent whose case source is not one of the two",
      raw: { actif: true, agents: { "m03-estimation": { affaire: "texte" } }, niveaux: NIVEAUX },
      reason: '"agents.m03-estimation.affaire"',
    },
    {
      title: "an agent whose case source is not text",
      raw: { actif: true, agents: { "m03-estimation": { affaire: true } }, niveaux: NIVEAUX },
      reason: '"agents.m03-estimation.affaire"',
    },
    {
      title: "a session-reading tool that is not a department tool",
      raw: { actif: true, outil_affaire: "lire l'affaire", agents: M3, niveaux: NIVEAUX },
      reason: '"outil_affaire"',
    },
    { title: "no levels", raw: { actif: true, agents: M3 }, reason: '"niveaux"' },
    {
      title: "an empty levels map",
      raw: { actif: true, agents: M3, niveaux: {} },
      reason: '"niveaux"',
    },
    {
      title: "levels as a list",
      raw: { actif: true, agents: M3, niveaux: ["N3"] },
      reason: '"niveaux"',
    },
    {
      title: "a level that is not N0 to N5",
      raw: { actif: true, agents: M3, niveaux: { m3_estimer_projet: "N6" } },
      reason: "bad entry",
    },
    {
      title: "a level in lower case",
      raw: { actif: true, agents: M3, niveaux: { m3_estimer_projet: "n3" } },
      reason: "bad entry",
    },
    {
      title: "a level that is not text",
      raw: { actif: true, agents: M3, niveaux: { m3_estimer_projet: 3 } },
      reason: "bad entry",
    },
    {
      title: "a tool name that is not an OPSYS department tool",
      raw: { actif: true, agents: M3, niveaux: { "lire tout": "N0" } },
      reason: "bad entry",
    },
  ])("is invalid, and says which key to fix, for $title", ({ raw, reason }) => {
    expect(parseOpsysContexteConfig(raw)).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining(reason),
    });
  });

  it("says to regenerate the file when the levels are missing, as an old contexte.json has none", () => {
    expect(parseOpsysContexteConfig({ actif: true, agents: M3 })).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("opsys metier openclaw configurer"),
    });
  });
});
