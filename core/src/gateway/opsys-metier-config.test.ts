// OPSYS business-engine supervisor configuration (OPSYS-AI PLAN T0.10): `opsys/metier.json` is
// off by default and fail-closed once enabled.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import {
  OPSYS_METIER_CONFIG_FILENAME,
  parseOpsysMetierConfig,
  readOpsysMetierConfig,
} from "./opsys-metier-config.js";

const tempDirs = useAutoCleanupTempDirTracker(afterEach);

function writeConfig(dir: string, content: string): void {
  fs.writeFileSync(path.join(dir, OPSYS_METIER_CONFIG_FILENAME), content);
}

describe("readOpsysMetierConfig", () => {
  it("is off when there is no metier.json", () => {
    const dir = tempDirs.make("opsys-metier-config-");

    expect(readOpsysMetierConfig({ dir })).toStrictEqual({ kind: "absent" });
  });

  it("is off when the OPSYS folder does not exist yet", () => {
    const dir = path.join(tempDirs.make("opsys-metier-config-"), "missing");

    expect(readOpsysMetierConfig({ dir })).toStrictEqual({ kind: "absent" });
  });

  it("reads the enabled configuration from the file", () => {
    const dir = tempDirs.make("opsys-metier-config-");
    const engineDir = tempDirs.make("opsys-metier-engine-");
    writeConfig(dir, JSON.stringify({ actif: true, dossier: engineDir }));

    const result = readOpsysMetierConfig({ dir });

    expect(result).toMatchObject({ kind: "enabled", config: { cwd: engineDir } });
  });

  it("refuses a file that is not JSON instead of guessing the operator's intent", () => {
    const dir = tempDirs.make("opsys-metier-config-");
    writeConfig(dir, "{ actif: true");

    const result = readOpsysMetierConfig({ dir });

    expect(result).toMatchObject({ kind: "invalid", reason: expect.stringContaining("not valid JSON") });
  });

  it("refuses a file that cannot be read", () => {
    const dir = tempDirs.make("opsys-metier-config-");
    fs.mkdirSync(path.join(dir, OPSYS_METIER_CONFIG_FILENAME));

    const result = readOpsysMetierConfig({ dir });

    expect(result).toMatchObject({ kind: "invalid", reason: expect.stringContaining("cannot read") });
  });
});

describe("parseOpsysMetierConfig", () => {
  it.each([
    { title: "an empty object", raw: {} },
    { title: "actif false", raw: { actif: false } },
    { title: "actif as a string", raw: { actif: "true" } },
    { title: "actif as a number", raw: { actif: 1 } },
  ])("stays off for $title", ({ raw }) => {
    expect(parseOpsysMetierConfig(raw)).toStrictEqual({ kind: "disabled" });
  });

  it("applies documented defaults to a minimal enabled configuration", () => {
    const dossier = tempDirs.make("opsys-metier-engine-");

    const result = parseOpsysMetierConfig({ actif: true, dossier });

    expect(result).toStrictEqual({
      kind: "enabled",
      config: {
        cwd: dossier,
        command: ["uv", "run", "opsys-mcp", "--http", "--hote", "127.0.0.1", "--port", "8765"],
        healthUrl: "http://127.0.0.1:8765/sante",
        env: {},
        readyTimeoutMs: 120_000,
        probeIntervalMs: 10_000,
        maxProbeFailures: 3,
        maxRestarts: 10,
      },
    });
  });

  it("builds the command and probes the loopback when the engine binds every interface", () => {
    const dossier = tempDirs.make("opsys-metier-engine-");

    const result = parseOpsysMetierConfig({ actif: true, dossier, hote: "0.0.0.0", port: 9000 });

    expect(result).toMatchObject({
      kind: "enabled",
      config: {
        command: ["uv", "run", "opsys-mcp", "--http", "--hote", "0.0.0.0", "--port", "9000"],
        healthUrl: "http://127.0.0.1:9000/sante",
      },
    });
  });

  it("keeps a custom command, environment and timings as given", () => {
    const dossier = tempDirs.make("opsys-metier-engine-");

    const result = parseOpsysMetierConfig({
      actif: true,
      dossier,
      commande: ["/opt/opsys/.venv/bin/opsys-mcp", "--http", "--port", "9100"],
      hote: "localhost",
      port: 9100,
      env: { OPSYS_HOME: "/var/lib/opsys" },
      delai_pret_ms: 30_000,
      intervalle_sante_ms: 2_000,
      echecs_sante_max: 5,
      redemarrages_max: 0,
    });

    expect(result).toStrictEqual({
      kind: "enabled",
      config: {
        cwd: dossier,
        command: ["/opt/opsys/.venv/bin/opsys-mcp", "--http", "--port", "9100"],
        healthUrl: "http://localhost:9100/sante",
        env: { OPSYS_HOME: "/var/lib/opsys" },
        readyTimeoutMs: 30_000,
        probeIntervalMs: 2_000,
        maxProbeFailures: 5,
        maxRestarts: 0,
      },
    });
  });

  it.each([
    { title: "a JSON array", build: () => [], reason: "must contain a JSON object" },
    { title: "a missing folder", build: () => ({ actif: true }), reason: '"dossier"' },
    {
      title: "a relative folder",
      build: () => ({ actif: true, dossier: "opsys" }),
      reason: '"dossier"',
    },
    {
      title: "a folder that does not exist",
      build: (dossier: string) => ({ actif: true, dossier: path.join(dossier, "absent") }),
      reason: "not an existing directory",
    },
    {
      title: "a host with a path",
      build: (dossier: string) => ({ actif: true, dossier, hote: "127.0.0.1/mcp" }),
      reason: '"hote"',
    },
    {
      title: "a numeric host",
      build: (dossier: string) => ({ actif: true, dossier, hote: 127 }),
      reason: '"hote"',
    },
    {
      title: "port 0",
      build: (dossier: string) => ({ actif: true, dossier, port: 0 }),
      reason: '"port"',
    },
    {
      title: "a port above 65535",
      build: (dossier: string) => ({ actif: true, dossier, port: 70_000 }),
      reason: '"port"',
    },
    {
      title: "a port given as a string",
      build: (dossier: string) => ({ actif: true, dossier, port: "8765" }),
      reason: '"port"',
    },
    {
      title: "an empty command",
      build: (dossier: string) => ({ actif: true, dossier, commande: [] }),
      reason: '"commande"',
    },
    {
      title: "a command with an empty word",
      build: (dossier: string) => ({ actif: true, dossier, commande: ["uv", ""] }),
      reason: '"commande"',
    },
    {
      title: "a command given as one string",
      build: (dossier: string) => ({ actif: true, dossier, commande: "uv run opsys-mcp" }),
      reason: '"commande"',
    },
    {
      title: "a non-string environment value",
      build: (dossier: string) => ({ actif: true, dossier, env: { OPSYS_HOME: 1 } }),
      reason: '"env"',
    },
    {
      title: "an environment that sets the engine token",
      build: (dossier: string) => ({ actif: true, dossier, env: { OPSYS_MCP_JETON: "x" } }),
      reason: "must not set OPSYS_MCP_JETON",
    },
    {
      title: "a ready delay below one second",
      build: (dossier: string) => ({ actif: true, dossier, delai_pret_ms: 10 }),
      reason: '"delai_pret_ms"',
    },
    {
      title: "a probe interval below 100 ms",
      build: (dossier: string) => ({ actif: true, dossier, intervalle_sante_ms: 5 }),
      reason: '"intervalle_sante_ms"',
    },
    {
      title: "zero tolerated probe failures",
      build: (dossier: string) => ({ actif: true, dossier, echecs_sante_max: 0 }),
      reason: '"echecs_sante_max"',
    },
    {
      title: "a negative restart limit",
      build: (dossier: string) => ({ actif: true, dossier, redemarrages_max: -1 }),
      reason: '"redemarrages_max"',
    },
  ])("refuses $title and names what to fix", ({ build, reason }) => {
    const dossier = tempDirs.make("opsys-metier-engine-");

    const result = parseOpsysMetierConfig(build(dossier));

    expect(result).toMatchObject({ kind: "invalid", reason: expect.stringContaining(reason) });
  });
});
