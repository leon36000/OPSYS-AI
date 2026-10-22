// `opsys metier <command>` and the retired names of the Python engine's CLI (OPSYS-AI PLAN T0.7
// lot 2, docs/research/R14-renommage-core.md decision 3).
//
// Since lot 2 `opsys` is the core. What used to be `opsys <command>` (the Python engine's CLI,
// `src/opsys/cli.py`) is `opsys metier <command>`, and the engine's own executable is
// `opsys-metier`. This module only recognizes those two shapes from the raw argv, so that the
// entry point can answer before Commander, the plugin registry or the config are loaded. It is
// imported by `entry.ts` on every start: keep it free of heavy imports. The launching and the
// messages live in `opsys-metier-cli.ts`, loaded only when one of the shapes matches.
//
// `metier` is deliberately not a Commander command: its arguments belong to the engine
// (`--help`, `--config-dir`, `--par`...), which Commander would parse, rewrite or refuse, and a new
// root command would also have to be declared in the command catalog and the completion tree.
import {
  getCommandArgsWithRootOptions,
  getRootOptionAwareCommandPath,
} from "../infra/cli-root-options.js";

/** Root command that hands the rest of the command line to the Python engine. */
export const OPSYS_METIER_COMMAND = "metier";

/**
 * Subcommands of the engine's CLI before lot 2 (`construireParseur` in `src/opsys/cli.py`).
 * `tests/test_commande_metier.py` compares this list with the engine's parser: a command added
 * to one and not to the other fails there. None of them is a core command, so a typed one can
 * only be an old habit or an old script.
 */
export const OPSYS_METIER_MOVED_COMMANDS: readonly string[] = [
  "departements",
  "verifier",
  "profils",
  "agents-base",
  "approbations",
  "personnes",
  "base",
  "evenements",
  "mode",
  "budgets",
  "services",
  "equipes",
  "meteo",
  "paliers",
  "openclaw",
  "appareils",
  "instance",
  "passerelle",
  "memoire-developpement",
];

export type OpsysMetierInvocation =
  /** `opsys metier <args>`: run the engine's CLI with `args`, untouched. */
  | { kind: "metier"; args: string[] }
  /** `opsys <command> <args>`, the pre-lot-2 spelling: say what to type instead. */
  | { kind: "moved"; command: string; args: string[] };

/**
 * Recognizes `metier` or a retired engine command as the first command of `argv` (root options
 * such as `--log-level` may come before it). Everything after the command is returned as typed.
 * Returns null for any other command line.
 */
export function resolveOpsysMetierInvocation(
  argv: readonly string[],
): OpsysMetierInvocation | null {
  const [primary] = getRootOptionAwareCommandPath(argv, 1);
  if (primary === undefined) {
    return null;
  }
  const isMetier = primary === OPSYS_METIER_COMMAND;
  if (!isMetier && !OPSYS_METIER_MOVED_COMMANDS.includes(primary)) {
    return null;
  }
  const args = getCommandArgsWithRootOptions(argv, {
    commandPath: [primary],
    mode: "command-path",
  });
  if (args === null) {
    return null;
  }
  return isMetier ? { kind: "metier", args } : { kind: "moved", command: primary, args };
}
