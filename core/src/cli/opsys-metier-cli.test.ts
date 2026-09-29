// `opsys metier <command>`: the Python engine's CLI launched from `opsys/metier.json` (OPSYS-AI
// PLAN T0.7 lot 2). Nothing here starts a real engine: the launcher is a recording fake, and the
// contract with the installer (the key `commande_cli` that `opsys instance initialiser` writes)
// is checked on the Python side, in `tests/test_instance.py`.
import type { spawnSync } from "node:child_process";
import { constants as osConstants } from "node:os";
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import { OPSYS_METIER_CONFIG_FILENAME } from "../gateway/opsys-metier-config.js";
import {
  formatOpsysMetierMovedMessage,
  OPSYS_METIER_MOVED_EXIT_CODE,
  parseOpsysMetierCliConfig,
  readOpsysMetierCliConfig,
  runOpsysMetierCli,
} from "./opsys-metier-cli.js";

const tempDirs = useAutoCleanupTempDirTracker(afterEach);

const PYTHON = "/instance/logiciel/venv/bin/python";

function writeMetier(dir: string, content: unknown): void {
  fs.writeFileSync(path.join(dir, OPSYS_METIER_CONFIG_FILENAME), JSON.stringify(content));
}

/** A launcher that records its calls and answers like a finished child. */
function fakeLauncher(result: { status?: number | null; signal?: NodeJS.Signals | null; error?: Error } = {}) {
  const calls: Array<{ program: string; args: string[]; options: Record<string, unknown> }> = [];
  const launcher = vi.fn((program: string, args: string[], options: Record<string, unknown>) => {
    calls.push({ program, args, options });
    return { status: 0, signal: null, ...result };
  });
  return { calls, launcher: launcher as unknown as typeof spawnSync };
}

function fakeStderr() {
  const chunks: string[] = [];
  return { chunks, stderr: { write: (text: string) => chunks.push(text) } };
}

describe("parseOpsysMetierCliConfig", () => {
  it("takes the command line the installer wrote, arguments to be appended", () => {
    expect(
      parseOpsysMetierCliConfig({ commande_cli: [PYTHON, "-m", "opsys.cli"], env: { OPSYS_HOME: "/i" } }),
    ).toStrictEqual({
      kind: "ready",
      config: { command: [PYTHON, "-m", "opsys.cli"], env: { OPSYS_HOME: "/i" } },
    });
  });

  it("does not need the supervision to be active: the CLI is independent of the Gateway", () => {
    const result = parseOpsysMetierCliConfig({ actif: false, commande_cli: ["opsys-metier"] });

    expect(result).toStrictEqual({ kind: "ready", config: { command: ["opsys-metier"], env: {} } });
  });

  it("defaults, like the supervisor, to uv in the engine folder when nothing else is said", () => {
    const dossier = tempDirs.make("opsys-metier-cli-engine-");

    expect(parseOpsysMetierCliConfig({ actif: true, dossier })).toStrictEqual({
      kind: "ready",
      config: { command: ["uv", "run", "--project", dossier, "opsys-metier"], env: {} },
    });
  });

  it("refuses a custom server command without a CLI command, and says how to fix it", () => {
    const result = parseOpsysMetierCliConfig({
      actif: true,
      dossier: "/tmp",
      commande: [PYTHON, "-m", "opsys.serveur_mcp", "--http"],
    });

    expect(result).toMatchObject({
      kind: "invalid",
      reason: expect.stringMatching(/commande_cli.*install\.sh/su),
    });
  });

  it.each([
    { title: "an empty list", raw: { commande_cli: [] } },
    { title: "a string", raw: { commande_cli: "opsys-metier" } },
    { title: "a list with a number", raw: { commande_cli: ["python", 3] } },
    { title: "a list with an empty string", raw: { commande_cli: ["python", ""] } },
  ])("refuses commande_cli as $title", ({ raw }) => {
    expect(parseOpsysMetierCliConfig(raw)).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("commande_cli"),
    });
  });

  it.each([
    { title: "nothing to launch the CLI with", raw: {} },
    { title: "a relative engine folder", raw: { dossier: "moteur" } },
    { title: "an engine folder that does not exist", raw: { dossier: "/n/existe/pas/opsys" } },
    { title: "a non-object file", raw: ["commande_cli"] },
  ])("refuses $title instead of inventing a path", ({ raw }) => {
    expect(parseOpsysMetierCliConfig(raw)).toMatchObject({ kind: "invalid" });
  });

  it("refuses an env that would carry the engine token: it lives in the instance .env only", () => {
    const result = parseOpsysMetierCliConfig({
      commande_cli: ["opsys-metier"],
      env: { OPSYS_MCP_JETON: "un-jeton" },
    });

    expect(result).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("OPSYS_MCP_JETON"),
    });
  });

  it("refuses an env that is not a map of strings", () => {
    expect(parseOpsysMetierCliConfig({ commande_cli: ["opsys-metier"], env: { PORT: 8765 } })).toMatchObject({
      kind: "invalid",
    });
  });
});

describe("readOpsysMetierCliConfig", () => {
  it("reads the file in the OPSYS folder", () => {
    const dir = tempDirs.make("opsys-metier-cli-");
    writeMetier(dir, { commande_cli: [PYTHON, "-m", "opsys.cli"] });

    expect(readOpsysMetierCliConfig({ dir })).toStrictEqual({
      kind: "ready",
      config: { command: [PYTHON, "-m", "opsys.cli"], env: {} },
    });
  });

  it("reports the missing file with its path", () => {
    const dir = tempDirs.make("opsys-metier-cli-");

    expect(readOpsysMetierCliConfig({ dir })).toStrictEqual({
      kind: "absent",
      file: path.join(dir, OPSYS_METIER_CONFIG_FILENAME),
    });
  });

  it("refuses a file that is not JSON", () => {
    const dir = tempDirs.make("opsys-metier-cli-");
    fs.writeFileSync(path.join(dir, OPSYS_METIER_CONFIG_FILENAME), "{ commande_cli");

    expect(readOpsysMetierCliConfig({ dir })).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("n'est pas du JSON valide"),
    });
  });

  it("refuses a file that cannot be read", () => {
    const dir = tempDirs.make("opsys-metier-cli-");
    fs.mkdirSync(path.join(dir, OPSYS_METIER_CONFIG_FILENAME));

    expect(readOpsysMetierCliConfig({ dir })).toMatchObject({
      kind: "invalid",
      reason: expect.stringContaining("illisible"),
    });
  });
});

describe("formatOpsysMetierMovedMessage", () => {
  it("names the new spelling with the arguments as typed, and the engine's own executable", () => {
    const message = formatOpsysMetierMovedMessage("personnes", ["creer", "alice.fictive", "--nom", "Alice Fictive"]);

    expect(message).toContain('Utilisez : opsys metier personnes creer alice.fictive --nom "Alice Fictive"');
    expect(message).toContain('opsys-metier personnes creer alice.fictive --nom "Alice Fictive"');
    expect(message).toContain("« personnes » n'est plus une commande de opsys");
  });

  it("quotes what a shell would split, without letting a variable or a quote through", () => {
    const message = formatOpsysMetierMovedMessage("mode", ["m4", "supervise", "--par", 'a "b" $HOME']);

    expect(message).toContain('--par "a \\"b\\" \\$HOME"');
  });
});

describe("runOpsysMetierCli", () => {
  const INSTALLED = { commande_cli: [PYTHON, "-m", "opsys.cli"], env: { OPSYS_HOME: "/instance" } };

  /** A folder holding `metier.json` with `config`, plus a recording launcher and stderr. */
  function setup(config: unknown = INSTALLED) {
    const dir = tempDirs.make("opsys-metier-cli-run-");
    writeMetier(dir, config);
    return { dir, ...fakeStderr(), ...fakeLauncher() };
  }

  /** The same, without any `metier.json`. */
  function setupWithoutFile() {
    return { dir: tempDirs.make("opsys-metier-cli-run-"), ...fakeStderr(), ...fakeLauncher() };
  }

  it("says the new spelling of a retired name, exits 2 and runs nothing", () => {
    const { chunks, stderr, calls, launcher } = setup();

    const code = runOpsysMetierCli(
      { kind: "moved", command: "verifier", args: ["--paliers"] },
      { env: {}, spawnSync: launcher, stderr },
    );

    expect(code).toBe(OPSYS_METIER_MOVED_EXIT_CODE);
    expect(chunks.join("")).toContain("Utilisez : opsys metier verifier --paliers");
    expect(calls).toEqual([]);
  });

  it("launches the engine CLI with the arguments appended and the terminal inherited", () => {
    const { dir, stderr, calls, launcher } = setup();

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["personnes", "creer", "alice.fictive", "--nom", "Alice Fictive"] },
      { env: { HOME: "/home/u", PATH: "/usr/bin" }, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(0);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.program).toBe(PYTHON);
    expect(calls[0]?.args).toEqual(["-m", "opsys.cli", "personnes", "creer", "alice.fictive", "--nom", "Alice Fictive"]);
    expect(calls[0]?.options.stdio).toBe("inherit");
  });

  it("hands the engine its own environment: instance settings yes, the Gateway's variables no", () => {
    const { dir, stderr, calls, launcher } = setup();

    runOpsysMetierCli(
      { kind: "metier", args: ["base", "etat"] },
      {
        env: {
          HOME: "/home/u",
          PATH: "/usr/bin",
          OPSYS_EMBEDDINGS_URL: "http://127.0.0.1:11434/v1",
          OPENCLAW_STATE_DIR: "/home/u/.openclaw-opsys",
          OPENCLAW_GATEWAY_TOKEN: "jeton-de-passerelle-fictif",
          OPENAI_API_KEY: "cle-fictive",
        },
        dir,
        spawnSync: launcher,
        stderr,
      },
    );

    const env = calls[0]?.options.env as Record<string, string>;
    expect(env).toMatchObject({
      HOME: "/home/u",
      PATH: "/usr/bin",
      OPSYS_EMBEDDINGS_URL: "http://127.0.0.1:11434/v1",
      OPSYS_HOME: "/instance", // the default of metier.json
    });
    expect(Object.keys(env).filter((name) => name.startsWith("OPENCLAW_"))).toEqual([]);
    expect(env).not.toHaveProperty("OPENAI_API_KEY");
  });

  it("lets an OPSYS_HOME typed by the operator win over the installed instance", () => {
    const { dir, stderr, calls, launcher } = setup();

    runOpsysMetierCli(
      { kind: "metier", args: ["instance", "restaurer", "export.tar.gz"] },
      { env: { OPSYS_HOME: "/autre/instance" }, dir, spawnSync: launcher, stderr },
    );

    expect((calls[0]?.options.env as Record<string, string>).OPSYS_HOME).toBe("/autre/instance");
  });

  it("makes Python write UTF-8 on Windows only", () => {
    const windows = setup();
    const linux = setup();

    runOpsysMetierCli(
      { kind: "metier", args: ["mode"] },
      { env: {}, dir: windows.dir, platform: "win32", spawnSync: windows.launcher, stderr: windows.stderr },
    );
    runOpsysMetierCli(
      { kind: "metier", args: ["mode"] },
      { env: {}, dir: linux.dir, platform: "linux", spawnSync: linux.launcher, stderr: linux.stderr },
    );

    expect((windows.calls[0]?.options.env as Record<string, string>).PYTHONUTF8).toBe("1");
    expect(linux.calls[0]?.options.env as Record<string, string>).not.toHaveProperty("PYTHONUTF8");
  });

  it("ends with the exit code of the engine", () => {
    const { dir, stderr } = setup();
    const { launcher } = fakeLauncher({ status: 3 });

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["verifier"] },
      { env: {}, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(3);
  });

  it("ends with 128 plus the signal number when the engine was killed", () => {
    const { dir, stderr } = setup();
    const { launcher } = fakeLauncher({ status: null, signal: "SIGTERM" });

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["verifier"] },
      { env: {}, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(128 + osConstants.signals.SIGTERM);
  });

  it("refuses from an agent's exec shell, whatever the command, and launches nothing", () => {
    const { dir, chunks, stderr, calls, launcher } = setup();

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["approbations", "approuver", "demande-1", "--par", "nathan"] },
      { env: { OPENCLAW_SHELL: "exec" }, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(1);
    expect(chunks.join("")).toContain("réservée à l'opérateur");
    expect(calls).toEqual([]);
  });

  it("does not refuse the operator's own local shell of the TUI", () => {
    const { dir, stderr, calls, launcher } = setup();

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["base", "etat"] },
      { env: { OPENCLAW_SHELL: "tui-local" }, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(0);
    expect(calls).toHaveLength(1);
  });

  it("says what to do when the engine was never set up under this core", () => {
    const { dir, chunks, stderr, calls, launcher } = setupWithoutFile();

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["verifier"] },
      { env: {}, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(1);
    expect(chunks.join("")).toContain(path.join(dir, OPSYS_METIER_CONFIG_FILENAME));
    expect(chunks.join("")).toContain("install/install.sh");
    expect(chunks.join("")).toContain("opsys-metier <commande>");
    expect(calls).toEqual([]);
  });

  it("says which key to add to a metier.json written before `opsys metier` existed", () => {
    const { dir, chunks, stderr, calls, launcher } = setup({
      actif: true,
      dossier: "/tmp",
      commande: [PYTHON, "-m", "opsys.serveur_mcp"],
    });

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["verifier"] },
      { env: {}, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(1);
    expect(chunks.join("")).toContain("commande_cli");
    expect(calls).toEqual([]);
  });

  it("ends with 127 and says so when the engine's interpreter is gone", () => {
    const { dir, chunks, stderr } = setup();
    const { launcher } = fakeLauncher({
      error: Object.assign(new Error("spawn ENOENT"), { code: "ENOENT" }),
      status: null,
    });

    const code = runOpsysMetierCli(
      { kind: "metier", args: ["verifier"] },
      { env: {}, dir, spawnSync: launcher, stderr },
    );

    expect(code).toBe(127);
    expect(chunks.join("")).toContain(`impossible de lancer le moteur métier (${PYTHON})`);
    expect(chunks.join("")).toContain("install/install.sh");
  });
});
