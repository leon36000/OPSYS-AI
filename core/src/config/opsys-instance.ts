// OPSYS instance layout (T0.7 lot 3): where the core keeps its state and its config file
// when it runs under the `opsys` CLI profile.
//
// Leaf module on purpose (node builtins only): CLI profile projection imports it at process
// start, before any runtime module derives a path from the environment.
//
// Layout, for an account home `H`:
//   H/.opsys/core             canonical state directory of the `opsys` profile;
//   H/.opsys/core/opsys.json  canonical config file (`openclaw.json` is still read, never renamed);
//   H/.openclaw-opsys         where the profile kept its state before this lot (T0.11-b). Doctor moves
//                             it to the canonical directory; until then it stays authoritative, so a
//                             running service and the CLI keep talking about the same state.
import fs from "node:fs";
import path from "node:path";

/** CLI profile the OPSYS installer runs the core under. */
export const OPSYS_PROFILE = "opsys";
/** Instance directory inside the account home; also the default OPSYS_HOME of the business engine. */
export const OPSYS_INSTANCE_DIRNAME = ".opsys";
/** Core state directory inside the instance directory. */
export const OPSYS_CORE_DIRNAME = "core";
/** State directory of the `opsys` profile before T0.7 lot 3 (the generic `.openclaw-<profile>` rule). */
export const OPSYS_LEGACY_PROFILE_DIRNAME = ".openclaw-opsys";
/** Canonical config file name of the `opsys` profile. */
export const OPSYS_CONFIG_FILENAME = "opsys.json";
/** Former config file name: still read when it is the only one, never renamed by Doctor. */
export const OPSYS_LEGACY_CONFIG_FILENAME = "openclaw.json";

/** Whether `profile` names the OPSYS instance profile. Exact match: profile names are case-sensitive paths. */
export function isOpsysProfile(profile: string | null | undefined): boolean {
  return profile?.trim() === OPSYS_PROFILE;
}

/** `H/.opsys/core`. */
export function resolveOpsysCoreStateDir(home: string): string {
  return path.join(home, OPSYS_INSTANCE_DIRNAME, OPSYS_CORE_DIRNAME);
}

/** `H/.openclaw-opsys`. */
export function resolveLegacyOpsysProfileStateDir(home: string): string {
  return path.join(home, OPSYS_LEGACY_PROFILE_DIRNAME);
}

function pathExists(candidate: string): boolean {
  try {
    return fs.existsSync(candidate);
  } catch {
    return false;
  }
}

/**
 * True when `dir` is a directory that holds at least one entry. A directory the process may not read
 * counts as holding state: assuming so never splits or replaces anything.
 */
export function dirHasEntries(dir: string): boolean {
  try {
    return fs.readdirSync(dir).length > 0;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    return code === "EACCES" || code === "EPERM";
  }
}

/**
 * State directory of the `opsys` profile for the account home `home`.
 *
 * The canonical directory, except while only the former profile directory holds state: a state
 * written before this lot is used in place until Doctor moves it, exactly like the `.clawdbot` to
 * `.openclaw` fallback of the default profile. Using the canonical (empty) directory in that window
 * would split the state between the CLI and the service that is still running on the old path.
 */
export function resolveOpsysProfileStateDir(home: string): string {
  const canonical = resolveOpsysCoreStateDir(home);
  if (dirHasEntries(canonical)) {
    return canonical;
  }
  const legacy = resolveLegacyOpsysProfileStateDir(home);
  return dirHasEntries(legacy) ? legacy : canonical;
}

/**
 * Config file of the `opsys` profile in `stateDir`: an existing `opsys.json`, else an existing
 * `openclaw.json` (read in place), else `opsys.json` (a new instance).
 */
export function resolveOpsysConfigPath(stateDir: string): string {
  const canonical = path.join(stateDir, OPSYS_CONFIG_FILENAME);
  if (pathExists(canonical)) {
    return canonical;
  }
  const legacy = path.join(stateDir, OPSYS_LEGACY_CONFIG_FILENAME);
  return pathExists(legacy) ? legacy : canonical;
}
