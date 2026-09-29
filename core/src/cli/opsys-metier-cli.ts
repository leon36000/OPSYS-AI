// `opsys metier <command>`: the OPSYS business engine's CLI under the core's command (OPSYS-AI
// PLAN T0.7 lot 2, docs/research/R14-renommage-core.md decision 3).
//
// The engine is the Python package (`src/opsys/cli.py`). The core does not guess where it lives:
// it reads what the installer wrote for the supervisor (`<config dir>/opsys/metier.json`, the file
// `opsys-metier-config.ts` documents) and launches the engine CLI the way that file says.
//   - `commande_cli` (a list of strings) is the command line to which the arguments are appended,
//     e.g. `["/home/u/.local/share/opsys/venv/bin/python", "-m", "opsys.cli"]`. `opsys instance
//     initialiser` writes it, next to `commande` (the MCP server the supervisor launches).
//   - without `commande_cli`, and without a custom `commande` either, the default mirrors the
//     supervisor's (`uv run opsys-mcp` in `dossier`): `uv run --project <dossier> opsys-metier`.
//   - a custom `commande` with no `commande_cli` is refused: that file predates `opsys metier`,
//     and guessing another command line would run the engine from a place nobody chose.
// The child inherits the terminal (`stdio: "inherit"`): prompts such as the password of
// `personnes mot-de-passe` work, and its exit code is ours. It runs in the caller's working
// directory, so relative paths (`--depuis equipes.yaml`, `--sortie export.tar.gz`) mean what the
// operator typed.
//
// Nothing here loads the core's config or plugins: it must answer even when the Gateway's own
// configuration is broken, because repairing the instance is what several engine commands are for.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { isRecord, isStringRecord } from "@openclaw/normalization-core/record-coerce";
import { resolveStateDir } from "../config/paths.js";
import {
  OPSYS_METIER_CONFIG_FILENAME,
  OPSYS_MCP_TOKEN_ENV,
  resolveOpsysDir,
} from "../gateway/opsys-metier-config.js";
import { buildOpsysMetierCliEnv } from "../gateway/opsys-metier-env.js";
import { loadGlobalRuntimeDotEnvFiles } from "../infra/dotenv.js";
import { hasErrnoCode } from "../infra/errno.js";
import { formatErrorMessage } from "../infra/errors.js";
import { OPSYS_METIER_COMMAND, type OpsysMetierInvocation } from "./opsys-metier-argv.js";
import { resolveSubprocessExitCode } from "./subprocess-exit-code.js";

/** Key of `metier.json`: command line of the engine's CLI (arguments are appended to it). */
export const OPSYS_METIER_CLI_COMMAND_KEY = "commande_cli";
/** Exit code of a retired spelling: a usage error, so a script that still uses it fails loudly. */
export const OPSYS_METIER_MOVED_EXIT_CODE = 2;
/** Exit code when the command is refused from an agent's shell. */
export const OPSYS_METIER_REFUSED_EXIT_CODE = 1;
/** Exit code when the engine cannot be launched (shell convention for "command not found"). */
export const OPSYS_METIER_NOT_FOUND_EXIT_CODE = 127;

export type OpsysMetierCliConfig = Readonly<{
  command: readonly string[];
  env: Readonly<Record<string, string>>;
}>;

export type OpsysMetierCliConfigResult =
  | { kind: "ready"; config: OpsysMetierCliConfig }
  /** No `metier.json`: the engine was never set up under this core. */
  | { kind: "absent"; file: string }
  | { kind: "invalid"; reason: string };

function isDirectory(target: string): boolean {
  try {
    return fs.statSync(target).isDirectory();
  } catch {
    return false;
  }
}

/** Validates the parsed JSON of `metier.json` for the engine's CLI. Exported for tests. */
export function parseOpsysMetierCliConfig(raw: unknown): OpsysMetierCliConfigResult {
  const invalid = (reason: string): OpsysMetierCliConfigResult => ({ kind: "invalid", reason });
  if (!isRecord(raw)) {
    return invalid("metier.json doit contenir un objet JSON.");
  }
  let env: Readonly<Record<string, string>> = {};
  const extraEnv = raw.env;
  if (extraEnv !== undefined) {
    if (!isStringRecord(extraEnv)) {
      return invalid("« env » doit associer des noms de variables à des chaînes.");
    }
    if (Object.hasOwn(extraEnv, OPSYS_MCP_TOKEN_ENV)) {
      return invalid(
        `« env » ne doit pas poser ${OPSYS_MCP_TOKEN_ENV} : le jeton du moteur n'est pas dans ce fichier.`,
      );
    }
    env = extraEnv;
  }
  const custom = raw[OPSYS_METIER_CLI_COMMAND_KEY];
  if (custom !== undefined) {
    if (
      !Array.isArray(custom) ||
      custom.length === 0 ||
      !custom.every((part): part is string => typeof part === "string" && part.length > 0)
    ) {
      return invalid(
        `« ${OPSYS_METIER_CLI_COMMAND_KEY} » doit être une liste non vide de chaînes non vides.`,
      );
    }
    return { kind: "ready", config: { command: custom, env } };
  }
  if (raw.commande !== undefined) {
    return invalid(
      `metier.json ne dit pas comment lancer la CLI du moteur (clé « ${OPSYS_METIER_CLI_COMMAND_KEY} »). ` +
        "Relancez install/install.sh (c'est aussi la mise à jour) : il l'ajoute.",
    );
  }
  const folder = raw.dossier;
  if (typeof folder !== "string" || !path.isAbsolute(folder) || !isDirectory(folder)) {
    return invalid(
      `metier.json ne dit pas comment lancer la CLI du moteur : ni « ${OPSYS_METIER_CLI_COMMAND_KEY} », ` +
        "ni « dossier » (chemin absolu d'un dossier existant, pour la commande par défaut).",
    );
  }
  return {
    kind: "ready",
    config: { command: ["uv", "run", "--project", folder, "opsys-metier"], env },
  };
}

/**
 * Reads `<opsys dir>/metier.json`. `dir` overrides the default lookup (tests only). Unlike the
 * supervisor's reader, `"actif": true` is not required: the CLI does not depend on the Gateway
 * supervising the engine.
 */
export function readOpsysMetierCliConfig(
  params: { dir?: string; env?: NodeJS.ProcessEnv } = {},
): OpsysMetierCliConfigResult {
  const file = path.join(params.dir ?? resolveOpsysDir(params.env), OPSYS_METIER_CONFIG_FILENAME);
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch (error) {
    if (hasErrnoCode(error, "ENOENT")) {
      return { kind: "absent", file };
    }
    return { kind: "invalid", reason: `${file} est illisible : ${formatErrorMessage(error)}` };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return {
      kind: "invalid",
      reason: `${file} n'est pas du JSON valide : ${formatErrorMessage(error)}`,
    };
  }
  return parseOpsysMetierCliConfig(parsed);
}

function quoteForHint(arg: string): string {
  return /^[A-Za-z0-9_@%+=:,./-]+$/u.test(arg) ? arg : `"${arg.replace(/(["\\$`])/gu, "\\$1")}"`;
}

/** What to say to someone who typed the pre-lot-2 spelling `opsys <command> <args>`. */
export function formatOpsysMetierMovedMessage(command: string, args: readonly string[]): string {
  const rest = [command, ...args].map(quoteForHint).join(" ");
  return [
    `opsys : « ${command} » n'est plus une commande de opsys. Depuis que « opsys » est la commande du core,`,
    "celles du moteur métier sont sous « opsys metier ».",
    `Utilisez : opsys ${OPSYS_METIER_COMMAND} ${rest}`,
    `(Avec le moteur seul, sans le core, par exemple dans un conteneur Docker : opsys-metier ${rest})`,
    "",
  ].join("\n");
}

/** Seams for tests. Production passes none of them. */
export type OpsysMetierRunDeps = {
  /** Environment the engine's is derived from. Defaults to `process.env`, with the instance `.env` loaded. */
  env?: NodeJS.ProcessEnv;
  platform?: NodeJS.Platform;
  /** Folder holding `metier.json`. Defaults to `<config dir>/opsys`. */
  dir?: string;
  spawnSync?: typeof spawnSync;
  stderr?: { write: (text: string) => unknown };
};

/**
 * Runs an invocation recognized by `resolveOpsysMetierInvocation` and returns the exit code the
 * process must end with. Never throws for an expected refusal: each one prints what to do.
 */
export function runOpsysMetierCli(
  invocation: OpsysMetierInvocation,
  deps: OpsysMetierRunDeps = {},
): number {
  const stderr = deps.stderr ?? process.stderr;
  if (invocation.kind === "moved") {
    stderr.write(formatOpsysMetierMovedMessage(invocation.command, invocation.args));
    return OPSYS_METIER_MOVED_EXIT_CODE;
  }
  if (!deps.env) {
    // The engine reads the instance settings the way the Gateway and every other command do:
    // `<state dir>/.env`, first value wins, so anything the caller already exported stays.
    loadGlobalRuntimeDotEnvFiles({
      quiet: true,
      stateEnvPath: path.join(resolveStateDir(process.env), ".env"),
    });
  }
  const env = deps.env ?? process.env;
  // The engine's CLI holds human decisions (approvals, people, autonomy modes): an agent's exec
  // shell gets the same refusal whatever the exec policy allows, as for the other operator-only
  // commands (`OPENCLAW_SHELL` is set by the exec runtime).
  if (env.OPENCLAW_SHELL === "exec") {
    stderr.write(
      "opsys metier : commande réservée à l'opérateur, refusée depuis le shell d'un agent (OPENCLAW_SHELL=exec).\n",
    );
    return OPSYS_METIER_REFUSED_EXIT_CODE;
  }
  const loaded = readOpsysMetierCliConfig({ dir: deps.dir, env });
  if (loaded.kind === "absent") {
    stderr.write(
      `opsys metier : le moteur métier n'est pas configuré pour ce core (${loaded.file} est absent).\n` +
        "Lancez install/install.sh, qui le prépare. Avec le moteur seul (Docker, développement) : opsys-metier <commande>.\n",
    );
    return OPSYS_METIER_REFUSED_EXIT_CODE;
  }
  if (loaded.kind === "invalid") {
    stderr.write(`opsys metier : ${loaded.reason}\n`);
    return OPSYS_METIER_REFUSED_EXIT_CODE;
  }
  const [program, ...programArgs] = loaded.config.command;
  if (program === undefined) {
    stderr.write("opsys metier : la commande du moteur est vide.\n");
    return OPSYS_METIER_REFUSED_EXIT_CODE;
  }
  const result = (deps.spawnSync ?? spawnSync)(program, [...programArgs, ...invocation.args], {
    stdio: "inherit",
    env: buildOpsysMetierCliEnv({
      base: env,
      extra: loaded.config.env,
      platform: deps.platform,
    }),
  });
  if (result.error) {
    const missing = hasErrnoCode(result.error, "ENOENT");
    stderr.write(
      `opsys metier : impossible de lancer le moteur métier (${program}) : ${
        missing ? "introuvable. Relancez install/install.sh." : formatErrorMessage(result.error)
      }\n`,
    );
    return missing ? OPSYS_METIER_NOT_FOUND_EXIT_CODE : OPSYS_METIER_REFUSED_EXIT_CODE;
  }
  return resolveSubprocessExitCode(result.status, result.signal);
}
