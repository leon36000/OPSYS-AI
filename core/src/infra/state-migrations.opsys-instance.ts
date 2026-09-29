// Doctor migration of the OPSYS instance state (T0.7 lot 3): the state that the `opsys` profile kept in
// `~/.openclaw-opsys` (installs made since T0.11-b) moves to `~/.opsys/core`.
//
// Same contract as the `.clawdbot` to `.openclaw` move in `state-migrations.state-dir.ts`, whose entry
// points call this module:
// - the state is MOVED (one atomic rename inside the same filesystem), never copied: two copies are the
//   split state this migration exists to prevent, and deleting the former copy would be a human decision;
// - nothing is overwritten and nothing is merged: when both locations hold state, the migration stops
//   and says what to do;
// - a link is left at the former path, so an installed service whose definition still names it keeps
//   working until the service is reinstalled;
// - the moved tree is checked before the link is created; a failed check moves it back;
// - it can be run again at any point: every interrupted outcome is either "nothing changed" or "moved".
//
// The config file name is untouched: an existing `openclaw.json` moves with the directory and is still
// read there (`resolveOpsysConfigPath`), because the installed service definition names that file.
import fs from "node:fs";
import path from "node:path";
import {
  dirHasEntries,
  isOpsysProfile,
  resolveLegacyOpsysProfileStateDir,
  resolveOpsysCoreStateDir,
} from "../config/opsys-instance.js";
import { resolveRequiredHomeDir, resolveUserPath } from "./home-dir.js";

export type OpsysStateMigrationPaths = { source: string; target: string };

export type OpsysStateMigrationResult = {
  changes: string[];
  warnings: string[];
  notices: string[];
};

/** File-system operations that can fail half-way; injectable so the failure paths are testable. */
export type OpsysStateMoveDeps = {
  rename: (from: string, to: string) => void;
  symlink: (target: string, linkPath: string, type: "dir" | "junction") => void;
  platform: NodeJS.Platform;
};

const DEFAULT_DEPS: OpsysStateMoveDeps = {
  rename: (from, to) => fs.renameSync(from, to),
  symlink: (target, linkPath, type) => fs.symlinkSync(target, linkPath, type),
  platform: process.platform,
};

type Classification =
  | { kind: "none" }
  | { kind: "retire-empty-source" }
  | { kind: "move"; replaceEmptyTarget: boolean }
  | { kind: "conflict" }
  | { kind: "unsupported"; reason: string };

function lstatIfPresent(filePath: string): fs.Stats | null {
  try {
    return fs.lstatSync(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

function describeLink(linkPath: string): string {
  try {
    return path.resolve(path.dirname(linkPath), fs.readlinkSync(linkPath));
  } catch {
    return "an unreadable target";
  }
}

/** Whether the link at `linkPath` leads to `expected`: same real directory, or same recorded target. */
function linkPointsTo(linkPath: string, expected: string): boolean {
  try {
    return fs.realpathSync.native(linkPath) === fs.realpathSync.native(expected);
  } catch {
    // A dangling link, or a target that does not exist yet: compare what the link records.
    return describeLink(linkPath) === path.resolve(expected);
  }
}

function classify(source: string, target: string): Classification {
  const sourceStat = lstatIfPresent(source);
  if (!sourceStat) {
    return { kind: "none" };
  }
  if (sourceStat.isSymbolicLink()) {
    return linkPointsTo(source, target)
      ? { kind: "none" }
      : { kind: "unsupported", reason: `${source} is a symbolic link to ${describeLink(source)}` };
  }
  if (!sourceStat.isDirectory()) {
    return { kind: "unsupported", reason: `${source} is not a directory` };
  }
  const sourceHasEntries = dirHasEntries(source);
  const targetStat = lstatIfPresent(target);
  if (!targetStat) {
    return sourceHasEntries ? { kind: "move", replaceEmptyTarget: false } : { kind: "none" };
  }
  if (!targetStat.isDirectory() && !targetStat.isSymbolicLink()) {
    return { kind: "conflict" };
  }
  if (!sourceHasEntries) {
    return { kind: "retire-empty-source" };
  }
  if (targetStat.isDirectory() && !dirHasEntries(target)) {
    return { kind: "move", replaceEmptyTarget: true };
  }
  return { kind: "conflict" };
}

/**
 * The `{ source, target }` pair Doctor still has to reconcile, or undefined. It applies only to a process
 * running the `opsys` profile whose state directory is the canonical directory or the former one.
 */
export function resolveOpsysLegacyStateMigrationPaths(params: {
  env: NodeJS.ProcessEnv;
  homedir: () => string;
}): OpsysStateMigrationPaths | undefined {
  const { env } = params;
  if (!isOpsysProfile(env.OPENCLAW_PROFILE)) {
    return undefined;
  }
  const activeStateDir = env.OPENCLAW_STATE_DIR?.trim();
  if (!activeStateDir) {
    return undefined;
  }
  const home = resolveRequiredHomeDir(env, params.homedir);
  const target = resolveOpsysCoreStateDir(home);
  const source = resolveLegacyOpsysProfileStateDir(home);
  const active = resolveUserPath(activeStateDir, env, params.homedir);
  if (active !== path.resolve(target) && active !== path.resolve(source)) {
    return undefined;
  }
  try {
    return classify(source, target).kind === "none" ? undefined : { source, target };
  } catch {
    // Not inspectable: keep it pending so the migration itself reports why.
    return { source, target };
  }
}

function manualMoveAdvice(source: string, target: string): string {
  return (
    `To move it by hand: stop the Gateway service, rename ${source} to ${target} ` +
    "(the target must not exist), then re-run `opsys doctor`."
  );
}

function conflictMessage(source: string, target: string): string {
  return (
    `OPSYS state dir migration skipped: both ${source} (former location) and ${target} hold state. ` +
    "Nothing was moved, merged or deleted. Stop the Gateway service, keep one of the two, then re-run " +
    `\`opsys doctor\`: to keep the new state, rename ${source} to ${source}.old; to keep the former ` +
    `state, rename ${target} to ${target}.old. The folder set aside holds secrets in clear text: ` +
    "deleting it is a human decision."
  );
}

/** Top-level names the moved tree must still hold; a Gateway may add entries meanwhile, never remove them. */
function movedTreeIsIntact(source: string, target: string, namesBefore: readonly string[]): boolean {
  try {
    if (lstatIfPresent(source)) {
      return false;
    }
    const namesAfter = new Set(fs.readdirSync(target));
    return namesBefore.every((name) => namesAfter.has(name));
  } catch {
    return false;
  }
}

function linkFormerPath(source: string, target: string, deps: OpsysStateMoveDeps): void {
  try {
    deps.symlink(target, source, "dir");
  } catch (error) {
    if (deps.platform !== "win32") {
      throw error;
    }
    // A directory symlink needs a privilege on Windows; a junction does not.
    deps.symlink(target, source, "junction");
  }
}

const SERVICE_NOTICE =
  "The installed Gateway service still names the former state path; it works through the link. " +
  "Reinstall it (`opsys gateway install --force`, or re-run the installer) to point it at the new one.";

function moveState(
  source: string,
  target: string,
  replaceEmptyTarget: boolean,
  deps: OpsysStateMoveDeps,
): OpsysStateMigrationResult {
  const result: OpsysStateMigrationResult = { changes: [], warnings: [], notices: [] };
  let namesBefore: string[];
  try {
    namesBefore = fs.readdirSync(source);
    fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
    if (replaceEmptyTarget) {
      // rmdir only removes an empty directory: a state that appeared meanwhile makes it fail, and stays.
      fs.rmdirSync(target);
    }
    deps.rename(source, target);
  } catch (error) {
    result.warnings.push(
      `OPSYS state dir migration failed (${source} → ${target}): ${String(error)}. Nothing was ` +
        "copied or deleted. If the Gateway service is running, stop it first (Windows keeps its " +
        `files open). ${manualMoveAdvice(source, target)}`,
    );
    return result;
  }

  if (!movedTreeIsIntact(source, target, namesBefore)) {
    try {
      if (lstatIfPresent(source)) {
        throw new Error(`${source} exists again`);
      }
      deps.rename(target, source);
      result.warnings.push(
        `OPSYS state dir migration rolled back (${target} did not hold what ${source} held): the state is back in ${source}.`,
      );
    } catch (rollbackError) {
      result.warnings.push(
        `OPSYS state dir moved to ${target} but the check failed and the rollback failed: ${String(rollbackError)}. ` +
          `Inspect ${target} before starting the Gateway.`,
      );
    }
    return result;
  }

  try {
    linkFormerPath(source, target, deps);
  } catch (error) {
    try {
      deps.rename(target, source);
      result.warnings.push(
        `OPSYS state dir migration rolled back (failed to link the former path ${source}): ${String(error)}.`,
      );
    } catch (rollbackError) {
      result.warnings.push(
        `OPSYS state dir moved to ${target} but the former path ${source} could not be linked (${String(error)}) ` +
          `and the rollback failed (${String(rollbackError)}). The state now lives in ${target}: ` +
          "reinstall the service (`opsys gateway install --force`) so it stops naming the former path.",
      );
      result.changes.push(`State dir: ${source} → ${target}`);
    }
    return result;
  }
  result.changes.push(`State dir: ${source} → ${target} (former path now linked)`);
  result.notices.push(SERVICE_NOTICE);
  return result;
}

function retireEmptySource(
  source: string,
  target: string,
  deps: OpsysStateMoveDeps,
): OpsysStateMigrationResult {
  const result: OpsysStateMigrationResult = { changes: [], warnings: [], notices: [] };
  // Empty residue holds no state to merge. Link it so an old client cannot recreate a split state.
  try {
    fs.rmdirSync(source);
  } catch (error) {
    result.warnings.push(
      `Failed to remove the empty former OPSYS state dir ${source}: ${String(error)}. It holds no state; remove it by hand.`,
    );
    return result;
  }
  try {
    linkFormerPath(source, target, deps);
    result.changes.push(`State dir: ${source} → ${target} (empty former path now linked)`);
  } catch (error) {
    result.warnings.push(
      `The empty former OPSYS state dir ${source} was removed but could not be replaced by a link to ${target} ` +
        `(${String(error)}). It held no state. If an installed service still names it, reinstall the service ` +
        "(`opsys gateway install --force`).",
    );
  }
  return result;
}

/**
 * Moves the former `opsys` profile state to the canonical instance directory when Doctor must.
 * Never throws: every refusal or failure comes back as a warning that says what to do.
 */
export function migrateLegacyOpsysStateDir(
  params: { env: NodeJS.ProcessEnv; homedir: () => string },
  deps: OpsysStateMoveDeps = DEFAULT_DEPS,
): OpsysStateMigrationResult {
  const paths = resolveOpsysLegacyStateMigrationPaths(params);
  if (!paths) {
    return { changes: [], warnings: [], notices: [] };
  }
  const { source, target } = paths;
  try {
    const plan = classify(source, target);
    switch (plan.kind) {
      case "none":
        return { changes: [], warnings: [], notices: [] };
      case "unsupported":
        return {
          changes: [],
          warnings: [
            `OPSYS state dir migration skipped: ${plan.reason}. Nothing was changed. ${manualMoveAdvice(source, target)}`,
          ],
          notices: [],
        };
      case "conflict":
        return { changes: [], warnings: [conflictMessage(source, target)], notices: [] };
      case "retire-empty-source":
        return retireEmptySource(source, target, deps);
      case "move":
        return moveState(source, target, plan.replaceEmptyTarget, deps);
    }
  } catch (error) {
    return {
      changes: [],
      warnings: [
        `OPSYS state dir migration skipped: ${source} could not be inspected (${String(error)}). Nothing was changed.`,
      ],
      notices: [],
    };
  }
}
