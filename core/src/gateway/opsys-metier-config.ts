// Configuration of the OPSYS business-engine supervisor (OPSYS-AI PLAN T0.10).
//
// Read from `<config dir>/opsys/metier.json`, next to the fragments OPSYS already writes there
// (`roles.json`, `appareils.json`, see `opsys-device-roles.ts`). Like them it is deliberately NOT
// part of the Zod-validated `OpenClawConfig`: the root schema is strict, and adding a key would
// also move the generated config baseline of an upstream surface OPSYS does not own.
//
// Supervision is OFF by default: a missing file, or a file without `"actif": true`, changes
// nothing to the Gateway's behavior. Fail-closed once enabled: a malformed value refuses the
// launch and says which key to fix; it is never replaced by an invented default.
//
// File format (keys are French like the other OPSYS fragments):
//   {
//     "actif": true,                      // required, must be exactly true
//     "dossier": "/opt/opsys",            // required, absolute, existing: cwd of the engine
//     "commande": ["uv", "run", ...],     // default: uv run opsys-mcp --http --hote H --port P
//     "hote": "127.0.0.1",                // default 127.0.0.1 (bind address and probe host)
//     "port": 8765,                       // default 8765 (must match a custom "commande")
//     "env": { "OPSYS_HOME": "/var/lib/opsys" },   // extra environment, never the token
//     "delai_pret_ms": 120000,            // wait for the first healthy probe
//     "intervalle_sante_ms": 10000,       // probe period once running
//     "echecs_sante_max": 3,              // consecutive failed probes before a restart
//     "redemarrages_max": 10              // consecutive restarts before giving up
//   }
import fs from "node:fs";
import path from "node:path";
import { asSafeIntegerInRange } from "@openclaw/normalization-core/number-coercion";
import { isRecord, isStringRecord } from "@openclaw/normalization-core/record-coerce";
import { resolveConfigPath } from "../config/paths.js";
import { formatErrorMessage } from "../infra/errors.js";

export const OPSYS_METIER_CONFIG_FILENAME = "metier.json";
/** Env var shared by the engine (`src/opsys/serveur_mcp.py`) and the `mcp.servers` headers. */
export const OPSYS_MCP_TOKEN_ENV = "OPSYS_MCP_JETON";
/** Path of the engine's unauthenticated liveness endpoint (`GET`, no business data). */
export const OPSYS_METIER_HEALTH_PATH = "/sante";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8765;
const DEFAULT_READY_TIMEOUT_MS = 120_000;
const DEFAULT_PROBE_INTERVAL_MS = 10_000;
const DEFAULT_MAX_PROBE_FAILURES = 3;
const DEFAULT_MAX_RESTARTS = 10;
const HOST_PATTERN = /^[A-Za-z0-9.-]+$/u;
const WILDCARD_HOSTS = new Set(["0.0.0.0"]);

export type OpsysMetierConfig = Readonly<{
  cwd: string;
  command: readonly string[];
  healthUrl: string;
  env: Readonly<Record<string, string>>;
  readyTimeoutMs: number;
  probeIntervalMs: number;
  maxProbeFailures: number;
  maxRestarts: number;
}>;

export type OpsysMetierConfigResult =
  /** No `metier.json`: supervision is off. */
  | { kind: "absent" }
  /** The file exists without `"actif": true`: supervision is off. */
  | { kind: "disabled" }
  /** The operator asked for supervision but the file cannot be trusted. */
  | { kind: "invalid"; reason: string }
  | { kind: "enabled"; config: OpsysMetierConfig };

/** The `<config dir>/opsys` directory OPSYS writes its fragments into. */
export function resolveOpsysDir(env: NodeJS.ProcessEnv = process.env): string {
  return path.join(path.dirname(resolveConfigPath(env)), "opsys");
}

function invalid(reason: string): OpsysMetierConfigResult {
  return { kind: "invalid", reason };
}

function isDirectory(target: string): boolean {
  try {
    return fs.statSync(target).isDirectory();
  } catch {
    return false;
  }
}

type OptionalInteger = { ok: true; value: number } | { ok: false };

function readInteger(
  root: Record<string, unknown>,
  key: string,
  fallback: number,
  range: { min: number; max: number },
): OptionalInteger {
  const raw = root[key];
  if (raw === undefined) {
    return { ok: true, value: fallback };
  }
  const value = asSafeIntegerInRange(raw, range);
  return value === undefined ? { ok: false } : { ok: true, value };
}

function rangeText(range: { min: number; max: number }): string {
  return `an integer from ${String(range.min)} to ${String(range.max)}`;
}

/** Validates the parsed JSON of `metier.json`. Exported for tests. */
export function parseOpsysMetierConfig(raw: unknown): OpsysMetierConfigResult {
  if (!isRecord(raw)) {
    return invalid("metier.json must contain a JSON object");
  }
  if (raw.actif !== true) {
    return { kind: "disabled" };
  }
  const cwd = raw.dossier;
  if (typeof cwd !== "string" || !path.isAbsolute(cwd)) {
    return invalid('"dossier" must be the absolute path of the OPSYS engine folder');
  }
  if (!isDirectory(cwd)) {
    return invalid(`"dossier" is not an existing directory: ${cwd}`);
  }
  const host = raw.hote === undefined ? DEFAULT_HOST : raw.hote;
  if (typeof host !== "string" || !HOST_PATTERN.test(host)) {
    return invalid('"hote" must be a host name or IPv4 address');
  }
  const portRange = { min: 1, max: 65_535 };
  const port = readInteger(raw, "port", DEFAULT_PORT, portRange);
  if (!port.ok) {
    return invalid(`"port" must be ${rangeText(portRange)}`);
  }
  let command: readonly string[] = [
    "uv",
    "run",
    "opsys-mcp",
    "--http",
    "--hote",
    host,
    "--port",
    String(port.value),
  ];
  if (raw.commande !== undefined) {
    const custom = raw.commande;
    if (
      !Array.isArray(custom) ||
      custom.length === 0 ||
      !custom.every((part): part is string => typeof part === "string" && part.length > 0)
    ) {
      return invalid('"commande" must be a non-empty list of non-empty strings');
    }
    command = custom;
  }
  let env: Readonly<Record<string, string>> = {};
  const extraEnv = raw.env;
  if (extraEnv !== undefined) {
    if (!isStringRecord(extraEnv)) {
      return invalid('"env" must map variable names to strings');
    }
    if (Object.hasOwn(extraEnv, OPSYS_MCP_TOKEN_ENV)) {
      return invalid(`"env" must not set ${OPSYS_MCP_TOKEN_ENV}: the Gateway owns the engine token`);
    }
    env = extraEnv;
  }
  const readyRange = { min: 1_000, max: 3_600_000 };
  const ready = readInteger(raw, "delai_pret_ms", DEFAULT_READY_TIMEOUT_MS, readyRange);
  if (!ready.ok) {
    return invalid(`"delai_pret_ms" must be ${rangeText(readyRange)}`);
  }
  const intervalRange = { min: 100, max: 600_000 };
  const interval = readInteger(raw, "intervalle_sante_ms", DEFAULT_PROBE_INTERVAL_MS, intervalRange);
  if (!interval.ok) {
    return invalid(`"intervalle_sante_ms" must be ${rangeText(intervalRange)}`);
  }
  const failuresRange = { min: 1, max: 100 };
  const failures = readInteger(raw, "echecs_sante_max", DEFAULT_MAX_PROBE_FAILURES, failuresRange);
  if (!failures.ok) {
    return invalid(`"echecs_sante_max" must be ${rangeText(failuresRange)}`);
  }
  const restartsRange = { min: 0, max: 1_000 };
  const restarts = readInteger(raw, "redemarrages_max", DEFAULT_MAX_RESTARTS, restartsRange);
  if (!restarts.ok) {
    return invalid(`"redemarrages_max" must be ${rangeText(restartsRange)}`);
  }
  const probeHost = WILDCARD_HOSTS.has(host) ? DEFAULT_HOST : host;
  return {
    kind: "enabled",
    config: {
      cwd,
      command,
      healthUrl: `http://${probeHost}:${String(port.value)}${OPSYS_METIER_HEALTH_PATH}`,
      env,
      readyTimeoutMs: ready.value,
      probeIntervalMs: interval.value,
      maxProbeFailures: failures.value,
      maxRestarts: restarts.value,
    },
  };
}

/**
 * Reads `<opsys dir>/metier.json`. `dir` overrides the default lookup (tests only; production
 * omits it). Runs once at Gateway startup, so the synchronous read is deliberate.
 */
export function readOpsysMetierConfig(
  params: { dir?: string; env?: NodeJS.ProcessEnv } = {},
): OpsysMetierConfigResult {
  const file = path.join(params.dir ?? resolveOpsysDir(params.env), OPSYS_METIER_CONFIG_FILENAME);
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return { kind: "absent" };
    }
    return invalid(`cannot read ${file}: ${formatErrorMessage(error)}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return invalid(`${file} is not valid JSON: ${formatErrorMessage(error)}`);
  }
  return parseOpsysMetierConfig(parsed);
}
