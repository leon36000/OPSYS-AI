// Profile name validation and normalization helpers for root CLI profile routing.
import path from "node:path";
import { normalizeLowercaseStringOrEmpty } from "@openclaw/normalization-core/string-coerce";
import {
  isOpsysProfile,
  OPSYS_CONFIG_FILENAME,
  OPSYS_LEGACY_CONFIG_FILENAME,
  resolveOpsysConfigPath,
  resolveOpsysProfileStateDir,
} from "../config/opsys-instance.js";
import { resolveRequiredHomeDir } from "../infra/home-dir.js";

const PROFILE_CONFIG_FILENAME = "openclaw.json";

const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/i;

export function isValidProfileName(value: string): boolean {
  if (!value) {
    return false;
  }
  // Keep it path-safe + shell-friendly.
  return PROFILE_NAME_RE.test(value);
}

export function normalizeProfileName(raw?: string | null): string | null {
  const profile = raw?.trim();
  if (!profile) {
    return null;
  }
  if (normalizeLowercaseStringOrEmpty(profile) === "default") {
    return null;
  }
  if (!isValidProfileName(profile)) {
    return null;
  }
  return profile;
}

/** Resolve the canonical home-scoped state root for a validated CLI profile. */
export function resolveProfileStateDir(
  profile: string,
  env: NodeJS.ProcessEnv,
  homedir: () => string,
): string {
  const trimmed = profile.trim();
  if (!isValidProfileName(trimmed)) {
    throw new Error(`Invalid profile name: ${JSON.stringify(profile)}`);
  }
  if (isOpsysProfile(trimmed)) {
    // The OPSYS instance directory holds the state of its profile (`~/.opsys/core`, T0.7 lot 3).
    return resolveOpsysProfileStateDir(resolveRequiredHomeDir(env, homedir));
  }
  const suffix = normalizeLowercaseStringOrEmpty(trimmed) === "default" ? "" : `-${trimmed}`;
  return path.join(resolveRequiredHomeDir(env, homedir), `.openclaw${suffix}`);
}

/**
 * Config file a profile projects for `stateDir`. The `opsys` profile prefers `opsys.json` and keeps
 * reading an existing `openclaw.json`; every other profile keeps `openclaw.json`.
 */
export function resolveProfileConfigPath(profile: string, stateDir: string): string {
  return isOpsysProfile(profile)
    ? resolveOpsysConfigPath(stateDir)
    : path.join(stateDir, PROFILE_CONFIG_FILENAME);
}

/** Every config path that counts as canonical for `profile` in its canonical state directory. */
export function listCanonicalProfileConfigPaths(profile: string, stateDir: string): string[] {
  return isOpsysProfile(profile)
    ? [
        path.join(stateDir, OPSYS_CONFIG_FILENAME),
        path.join(stateDir, OPSYS_LEGACY_CONFIG_FILENAME),
      ]
    : [path.join(stateDir, PROFILE_CONFIG_FILENAME)];
}
