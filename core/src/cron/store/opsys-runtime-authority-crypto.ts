/** Host-only encryption for the reserved OPSYS cron runtime authority namespace. */
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { resolveConfigPath, resolveStateDir } from "../../config/paths.js";
import { openRootFileSync, readFileDescriptorBoundedSync } from "../../infra/boundary-file-read.js";
import { resolveOpenClawPackageRootSync } from "../../infra/openclaw-root.js";
import { resolveOpenClawStateSqliteDir, resolveOpenClawStateSqlitePath } from "../../state/openclaw-state-db.paths.js";

export const OPSYS_CRON_AUTHORITY_RUNTIME_ID = "openclaw";
export const OPSYS_CRON_AUTHORITY_NAMESPACE = "opsys-cron-authority-v1";
export const OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX = "OPSYS_CRON_AUTHORITY_A256GCM_V1.";
const DOMAIN = "openclaw.cron.runtime-authority";
const VERSION = 1;
const KEY_BYTES = 32;
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const MAX_PLAINTEXT_BYTES = 64 * 1024;
const MAX_ENVELOPE_BYTES = 96 * 1024;
const KEY_ID_PATTERN = /^sha256:[a-f0-9]{64}$/u;

export type OpsysCronAuthorityBinding = Readonly<{
  storeKey: string;
  jobId: string;
  runtimeId: typeof OPSYS_CRON_AUTHORITY_RUNTIME_ID;
  namespace: typeof OPSYS_CRON_AUTHORITY_NAMESPACE;
  inputFingerprint: string;
}>;

type AuthorityEnvelope = Readonly<{
  v: 1;
  domain: typeof DOMAIN;
  alg: "A256GCM";
  keyId: string;
  nonce: string;
  tag: string;
  ciphertext: string;
}>;
type KeyCapture = { ok: true; keyId: string; key: Buffer; path: string } | { ok: false };

function isWithinPath(candidate: string, root: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function findGitRoot(start: string): { root?: string; unavailable: boolean } {
  let current = path.resolve(start);
  while (true) {
    try {
      const gitPath = path.join(current, ".git");
      const gitStat = fs.lstatSync(gitPath);
      if (gitStat.isDirectory() || gitStat.isFile()) {
        return { root: current, unavailable: false };
      }
      return { unavailable: true };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") return { unavailable: true };
      // Continue toward the filesystem root; absent .git markers are ordinary.
    }
    const parent = path.dirname(current);
    if (parent === current) return { unavailable: false };
    current = parent;
  }
}

function canonicalizePossiblyMissingPath(candidate: string): string | undefined {
  let current = path.resolve(candidate);
  const missing: string[] = [];
  while (true) {
    try {
      return path.join(fs.realpathSync(current), ...missing.reverse());
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") return undefined;
      const parent = path.dirname(current);
      if (parent === current) return undefined;
      missing.push(path.basename(current));
      current = parent;
    }
  }
}

function captureHostKey(): KeyCapture {
  const filePath = process.env.OPENCLAW_CRON_AUTHORITY_KEY_FILE;
  if (!filePath || !path.isAbsolute(filePath) || typeof process.geteuid !== "function") {
    return { ok: false };
  }
  let opened: ReturnType<typeof openRootFileSync> | undefined;
  let key: Buffer | undefined;
  try {
    const candidate = path.resolve(filePath);
    const stateDbPath = resolveOpenClawStateSqlitePath();
    const configPath = resolveConfigPath();
    const packageRoot = resolveOpenClawPackageRootSync({ moduleUrl: import.meta.url });
    const git = findGitRoot(process.cwd());
    // The package root works for installed deployments. A source checkout adds
    // its enclosing Git root so package-subtree execution protects the full repo.
    if (!packageRoot || git.unavailable) return { ok: false };
    const protectedRoots = [
      process.cwd(),
      packageRoot,
      ...(git.root ? [git.root] : []),
      path.dirname(configPath),
      resolveStateDir(),
      resolveOpenClawStateSqliteDir(),
      path.dirname(stateDbPath),
    ];
    const realCandidate = canonicalizePossiblyMissingPath(candidate);
    if (!realCandidate) return { ok: false };
    const realProtectedRoots: string[] = [];
    for (const root of protectedRoots) {
      const canonical = canonicalizePossiblyMissingPath(root);
      if (!canonical) return { ok: false };
      realProtectedRoots.push(canonical);
    }
    if (realProtectedRoots.some((root) => isWithinPath(realCandidate, root))) return { ok: false };
    opened = openRootFileSync({
      absolutePath: candidate,
      rootPath: path.dirname(candidate),
      boundaryLabel: "cron authority key directory",
      maxBytes: KEY_BYTES,
      rejectHardlinks: true,
      rejectSymlinks: true,
      allowedType: "file",
    });
    if (!opened.ok) return { ok: false };
    if (realProtectedRoots.some((root) => isWithinPath(opened.path, root))) return { ok: false };
    const stat = opened.stat;
    if (
      !stat.isFile() || stat.nlink !== 1 || stat.uid !== process.geteuid() ||
      ![0o400, 0o600].includes(stat.mode & 0o7777) || stat.size !== KEY_BYTES
    ) return { ok: false };
    key = readFileDescriptorBoundedSync(opened.fd, KEY_BYTES);
    if (key.length !== KEY_BYTES) {
      key.fill(0);
      return { ok: false };
    }
    const keyId = `sha256:${createHash("sha256").update(key).digest("hex")}`;
    const configuredKeyId = process.env.OPENCLAW_CRON_AUTHORITY_KEY_ID;
    if (!KEY_ID_PATTERN.test(configuredKeyId ?? "") || configuredKeyId !== keyId) {
      key.fill(0);
      return { ok: false };
    }
    return { ok: true, keyId, key, path: opened.path };
  } catch {
    key?.fill(0);
    return { ok: false };
  } finally {
    if (opened?.ok) fs.closeSync(opened.fd);
  }
}

// Cached per process/worker after first use, then revalidated on every operation.
// A read-only worker may be ephemeral; this is not Gateway-wide startup capture.
let keyCapture: KeyCapture | undefined;
function getHostKey(): KeyCapture {
  if (!keyCapture) return (keyCapture = captureHostKey());
  if (keyCapture.ok) {
    // Workers are short-lived and may be recreated independently of Gateway.
    // Verify the pinned file identity on every operation so rotation/replacement
    // cannot silently mix key generations within one runtime.
    const current = captureHostKey();
    if (
      !current.ok || current.keyId !== keyCapture.keyId || current.path !== keyCapture.path ||
      process.env.OPENCLAW_CRON_AUTHORITY_KEY_ID !== keyCapture.keyId
    ) {
      keyCapture.key.fill(0);
      keyCapture = { ok: false };
      if (current.ok) current.key.fill(0);
      return keyCapture;
    }
    current.key.fill(0);
  }
  return keyCapture;
}

function aad(binding: OpsysCronAuthorityBinding, keyId: string): Buffer {
  return Buffer.from(JSON.stringify([
    DOMAIN, VERSION, "A256GCM", keyId, binding.storeKey, binding.jobId,
    binding.runtimeId, binding.namespace, binding.inputFingerprint,
  ]), "utf8");
}
function encodeBase64Url(value: Buffer): string {
  return value.toString("base64url");
}
function decodeBase64Url(value: unknown, exactBytes?: number): Buffer | undefined {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/u.test(value)) return undefined;
  const bytes = Buffer.from(value, "base64url");
  if (encodeBase64Url(bytes) !== value || (exactBytes !== undefined && bytes.length !== exactBytes)) {
    return undefined;
  }
  return bytes;
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function isEnvelope(value: unknown): value is AuthorityEnvelope {
  if (!isRecord(value)) return false;
  const requiredKeys = [
    "v", "domain", "alg", "keyId", "nonce", "tag", "ciphertext",
  ];
  return Object.keys(value).length === requiredKeys.length &&
    requiredKeys.every((key) => Object.hasOwn(value, key)) &&
    value.v === VERSION && value.domain === DOMAIN && value.alg === "A256GCM" &&
    typeof value.keyId === "string" && KEY_ID_PATTERN.test(value.keyId) &&
    decodeBase64Url(value.nonce, NONCE_BYTES) !== undefined &&
    decodeBase64Url(value.tag, TAG_BYTES) !== undefined &&
    decodeBase64Url(value.ciphertext) !== undefined;
}

/** Returns undefined when unavailable; callers must refuse new OPSYS authority writes. */
export function sealOpsysCronAuthority(
  binding: OpsysCronAuthorityBinding,
  plaintextJson: string,
): string | undefined {
  const captured = getHostKey();
  if (!captured.ok || Buffer.byteLength(plaintextJson, "utf8") > MAX_PLAINTEXT_BYTES) return undefined;
  try {
    const nonce = randomBytes(NONCE_BYTES);
    const cipher = createCipheriv("aes-256-gcm", captured.key, nonce, { authTagLength: TAG_BYTES });
    cipher.setAAD(aad(binding, captured.keyId));
    const ciphertext = Buffer.concat([cipher.update(plaintextJson, "utf8"), cipher.final()]);
    const envelope: AuthorityEnvelope = {
      v: VERSION,
      domain: DOMAIN,
      alg: "A256GCM",
      keyId: captured.keyId,
      nonce: encodeBase64Url(nonce),
      tag: encodeBase64Url(cipher.getAuthTag()),
      ciphertext: encodeBase64Url(ciphertext),
    };
    const encoded = `${OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX}${encodeBase64Url(Buffer.from(JSON.stringify(envelope), "utf8"))}`;
    return Buffer.byteLength(encoded, "utf8") <= MAX_ENVELOPE_BYTES ? encoded : undefined;
  } catch {
    return undefined;
  }
}

/** Returns undefined for every parse, binding, key, or authentication failure. */
export function openOpsysCronAuthority(
  binding: OpsysCronAuthorityBinding,
  stored: string,
): string | undefined {
  if (!stored.startsWith(OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX) ||
      Buffer.byteLength(stored, "utf8") > MAX_ENVELOPE_BYTES) return undefined;
  const captured = getHostKey();
  if (!captured.ok) return undefined;
  try {
    const encoded = decodeBase64Url(stored.slice(OPSYS_CRON_AUTHORITY_CIPHERTEXT_PREFIX.length));
    if (!encoded) return undefined;
    const value: unknown = JSON.parse(encoded.toString("utf8"));
    if (!isEnvelope(value) || value.keyId !== captured.keyId) return undefined;
    const nonce = decodeBase64Url(value.nonce, NONCE_BYTES);
    const tag = decodeBase64Url(value.tag, TAG_BYTES);
    const ciphertext = decodeBase64Url(value.ciphertext);
    if (!nonce || !tag || !ciphertext) return undefined;
    const decipher = createDecipheriv("aes-256-gcm", captured.key, nonce, { authTagLength: TAG_BYTES });
    decipher.setAAD(aad(binding, captured.keyId));
    decipher.setAuthTag(tag);
    const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
    return Buffer.byteLength(plaintext, "utf8") <= MAX_PLAINTEXT_BYTES ? plaintext : undefined;
  } catch {
    return undefined;
  }
}
