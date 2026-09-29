// OPSYS named device roles (OPSYS-AI docs/architecture/IDEMPOTENCE.md §7 bis): resolves the OPSYS
// person/role for a paired device, and whether that role's scope covers a given tool name.
// `resolveOpsysDeviceIdentity` (PLAN T1.4-c5) gives the app the SAME person and role the tool door
// applies, from the same code path: what the app is told it is, is what the door enforces.
//
// Reads two small JSON files OPSYS writes next to `openclaw.json` — `opsys/roles.json` (role name
// -> allowed tool names, `src/opsys/openclaw.py::roles_outils`, and, PLAN T1.4-c6, tool name -> the
// MCP server that carries it, `serveurs_outils`) and `opsys/appareils.json` (device
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

/**
 * `roles.json`: the tools each role may call, and the MCP server carrying each of those tools. Both
 * keys are keyed by the BARE tool name the app sends (`m4_pointer`), the name the department's MCP
 * server knows: the scope check and the server lookup read the same string from the same file.
 */
type RolesFile = {
  roles: Record<string, readonly string[]>;
  serveurs: Record<string, string>;
};

const EMPTY_ROLES_FILE: RolesFile = { roles: {}, serveurs: {} };

const rolesCache = new Map<string, CachedFile<RolesFile>>();
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

function parseServeurs(raw: unknown): Record<string, string> {
  const serveurs = (raw as { serveurs?: unknown } | null)?.serveurs;
  if (!serveurs || typeof serveurs !== "object" || Array.isArray(serveurs)) {
    return {};
  }
  const result: Record<string, string> = {};
  for (const [tool, serveur] of Object.entries(serveurs as Record<string, unknown>)) {
    if (typeof serveur === "string" && serveur) {
      result[tool] = serveur;
    }
  }
  return result;
}

function parseRolesFile(raw: unknown): RolesFile {
  return { roles: parseRoles(raw), serveurs: parseServeurs(raw) };
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

type ResolvedOpsysDevice =
  | {
      ok: true;
      appareil: AppareilEntry;
      rolesFile: RolesFile;
      /** The tool names the device's role declares (a role with an empty list is still a known role). */
      allowedTools: readonly string[];
    }
  | { ok: false; reason: "device_unknown" | "role_unknown" };

/**
 * The one place a device id becomes an OPSYS person and a KNOWN role. An unrecognized device, and a
 * role `roles.json` does not declare, are both a refusal; a role named like an `Object.prototype`
 * member is never read as inherited state. Shared by the tool door and the identity read so the two
 * can never disagree on who a device is.
 */
function resolveOpsysDevice(deviceId: string, opsysDir: string): ResolvedOpsysDevice {
  const appareils = readJsonFileCached(
    path.join(opsysDir, "appareils.json"),
    appareilsCache,
    parseAppareils,
    {},
  );
  const appareil = Object.hasOwn(appareils, deviceId) ? appareils[deviceId] : undefined;
  if (!appareil) {
    return { ok: false, reason: "device_unknown" };
  }
  const rolesFile = readJsonFileCached(
    path.join(opsysDir, "roles.json"),
    rolesCache,
    parseRolesFile,
    EMPTY_ROLES_FILE,
  );
  const allowedTools = Object.hasOwn(rolesFile.roles, appareil.role)
    ? rolesFile.roles[appareil.role]
    : undefined;
  if (!allowedTools) {
    return { ok: false, reason: "role_unknown" };
  }
  return { ok: true, appareil, rolesFile, allowedTools };
}

export type OpsysDeviceAuthorization =
  | {
      ok: true;
      personne: string;
      role: string;
      /** The `mcp.servers` key of the department server that carries `toolName` (PLAN T1.4-c6). */
      serveur: string;
    }
  | {
      ok: false;
      reason: "device_unknown" | "role_unknown" | "tool_out_of_scope" | "server_unknown";
    };

/**
 * Resolves the OPSYS role/person for `deviceId`, whether `toolName` is in that role's scope, and
 * the one MCP server that carries `toolName`. The tool name is the BARE name the app sends: the
 * scope check and the server lookup use the same string, so the name that is authorized is the name
 * that is called (PLAN T1.4-c6). A tool in scope with no server entry is refused, never guessed
 * from the name. `opsysDir` overrides the default `<config dir>/opsys` lookup (tests only;
 * production omits it).
 */
export function authorizeOpsysDeviceTool(
  deviceId: string,
  toolName: string,
  opsysDir: string = defaultOpsysDir(),
): OpsysDeviceAuthorization {
  const device = resolveOpsysDevice(deviceId, opsysDir);
  if (!device.ok) {
    return { ok: false, reason: device.reason };
  }
  if (!device.allowedTools.includes(toolName)) {
    return { ok: false, reason: "tool_out_of_scope" };
  }
  const serveur = Object.hasOwn(device.rolesFile.serveurs, toolName)
    ? device.rolesFile.serveurs[toolName]
    : undefined;
  if (!serveur) {
    return { ok: false, reason: "server_unknown" };
  }
  return { ok: true, personne: device.appareil.personne, role: device.appareil.role, serveur };
}

export type OpsysDeviceIdentity =
  | { ok: true; personne: string; role: string }
  | { ok: false; reason: "device_unknown" | "role_unknown" };

/**
 * The OPSYS person and named role of `deviceId`, as `opsys/appareils.json` carries them (PLAN
 * T1.4-c5). `deviceId` must come from a verified device token, never from a request body. Same
 * refusals as `authorizeOpsysDeviceTool` for the device and its role: a device with no attribution
 * (never attributed, or revoked) and a role `roles.json` does not declare have no identity at all,
 * never a default one.
 */
export function resolveOpsysDeviceIdentity(
  deviceId: string,
  opsysDir: string = defaultOpsysDir(),
): OpsysDeviceIdentity {
  const device = resolveOpsysDevice(deviceId, opsysDir);
  if (!device.ok) {
    return { ok: false, reason: device.reason };
  }
  return { ok: true, personne: device.appareil.personne, role: device.appareil.role };
}

/** Test-only: drop cached file contents so a test's own fixture files are re-read from scratch. */
export function resetOpsysDeviceRolesCacheForTesting(): void {
  rolesCache.clear();
  appareilsCache.clear();
}
