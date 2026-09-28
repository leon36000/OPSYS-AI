// OPSYS named device roles (OPSYS-AI docs/architecture/IDEMPOTENCE.md §7 bis): resolves the OPSYS
// person/role for a paired device, and whether that role's scope covers a given tool name.
//
// Reads two small JSON files OPSYS writes next to `openclaw.json` — `opsys/roles.json` (role name
// -> allowed tool names, `src/opsys/openclaw.py::roles_outils`) and `opsys/appareils.json` (device
// id -> {personne, role}, `src/opsys/openclaw.py::ecrire_appareils`, from the `appareils` table,
// ADR-0009 §5) — GENERATED, never hand-written in the core. They are read directly from disk,
// deliberately NOT through `$include`/the Zod-validated `OpenClawConfig` tree: the root schema is
// strict (`OpenClawSchemaShape`, `config/zod-schema.root-shape.ts`), so an unrecognized top-level
// key would either be rejected outright or silently stripped depending on the exact schema used —
// neither of which this module can afford to depend on. `automatisations.sh` already establishes
// the precedent of an OPSYS-written sidecar file the config tree never includes.
//
// Fail-closed throughout: a missing or unreadable fragment is treated as empty (denies every
// device-scoped call, never grants one), and an unrecognized device, an unrecognized role, or a
// tool outside the role's declared list are all a refusal — never an implicit full-access grant.
// This mirrors R12 §6's concern almost verbatim: without named roles, a device token would carry
// the same reach as the shared operator secret.
import fs from "node:fs";
import path from "node:path";
import { resolveConfigPath } from "../config/paths.js";

type AppareilEntry = { personne: string; role: string };

// `mtimeMs` alone can alias on a coarse-grained filesystem clock when a fragment is rewritten
// twice in quick succession (a pairing approved, then immediately revoked); `size` rarely matches
// by coincidence when the content actually changed, so the pair together is a much more reliable,
// still essentially free, staleness check.
type CachedFile<T> = { mtimeMs: number; size: number; value: T };

const rolesCache = new Map<string, CachedFile<Record<string, readonly string[]>>>();
const appareilsCache = new Map<string, CachedFile<Record<string, AppareilEntry>>>();

/** The `<config dir>/opsys` directory OPSYS writes its fragments into, from the loaded config path. */
function defaultOpsysDir(): string {
  return path.join(path.dirname(resolveConfigPath()), "opsys");
}

function readJsonFileCached<T>(
  filePath: string,
  cache: Map<string, CachedFile<T>>,
  parse: (raw: unknown) => T,
  empty: T,
): T {
  let stat: fs.Stats;
  try {
    stat = fs.statSync(filePath);
  } catch {
    cache.delete(filePath);
    return empty;
  }
  const cached = cache.get(filePath);
  if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
    return cached.value;
  }
  let value = empty;
  try {
    value = parse(JSON.parse(fs.readFileSync(filePath, "utf8")));
  } catch {
    // Malformed JSON, or a shape parse() rejects: fail-closed (empty), never a thrown error that
    // would take down /tools/invoke for callers that carry no OPSYS device identity at all.
    value = empty;
  }
  cache.set(filePath, { mtimeMs: stat.mtimeMs, size: stat.size, value });
  return value;
}

function parseRoles(raw: unknown): Record<string, readonly string[]> {
  const roles = (raw as { roles?: unknown } | null)?.roles;
  if (!roles || typeof roles !== "object" || Array.isArray(roles)) {
    return {};
  }
  const result: Record<string, readonly string[]> = {};
  for (const [role, tools] of Object.entries(roles as Record<string, unknown>)) {
    if (Array.isArray(tools) && tools.every((tool) => typeof tool === "string")) {
      result[role] = tools;
    }
  }
  return result;
}

function parseAppareils(raw: unknown): Record<string, AppareilEntry> {
  const appareils = (raw as { appareils?: unknown } | null)?.appareils;
  if (!appareils || typeof appareils !== "object" || Array.isArray(appareils)) {
    return {};
  }
  const result: Record<string, AppareilEntry> = {};
  for (const [deviceId, entry] of Object.entries(appareils as Record<string, unknown>)) {
    const personne = (entry as { personne?: unknown } | null)?.personne;
    const role = (entry as { role?: unknown } | null)?.role;
    if (typeof personne === "string" && personne && typeof role === "string" && role) {
      result[deviceId] = { personne, role };
    }
  }
  return result;
}

export type OpsysDeviceAuthorization =
  | { ok: true; personne: string; role: string }
  | { ok: false; reason: "device_unknown" | "role_unknown" | "tool_out_of_scope" };

/**
 * Resolves the OPSYS role/person for `deviceId` and whether `toolName` is in that role's scope.
 * `opsysDir` overrides the default `<config dir>/opsys` lookup (tests only; production omits it).
 */
export function authorizeOpsysDeviceTool(
  deviceId: string,
  toolName: string,
  opsysDir: string = defaultOpsysDir(),
): OpsysDeviceAuthorization {
  const appareils = readJsonFileCached(
    path.join(opsysDir, "appareils.json"),
    appareilsCache,
    parseAppareils,
    {},
  );
  const appareil = appareils[deviceId];
  if (!appareil) {
    return { ok: false, reason: "device_unknown" };
  }
  const roles = readJsonFileCached(path.join(opsysDir, "roles.json"), rolesCache, parseRoles, {});
  const allowedTools = roles[appareil.role];
  if (!allowedTools) {
    return { ok: false, reason: "role_unknown" };
  }
  if (!allowedTools.includes(toolName)) {
    return { ok: false, reason: "tool_out_of_scope" };
  }
  return { ok: true, personne: appareil.personne, role: appareil.role };
}

/** Test-only: drop cached file contents so a test's own fixture files are re-read from scratch. */
export function resetOpsysDeviceRolesCacheForTesting(): void {
  rolesCache.clear();
  appareilsCache.clear();
}
