// OPSYS named device roles (docs/architecture/IDEMPOTENCE.md §7 bis in OPSYS-AI): resolving a
// paired device's role, tool scope and the MCP server carrying the tool (PLAN T1.4-c6) from the two
// sidecar fragments OPSYS generates (`src/opsys/openclaw.py::roles_outils`/`serveurs_outils`/
// `ecrire_appareils`), read directly from disk.
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanupTempDirs, makeTempDir } from "../../test/helpers/temp-dir.js";
import {
  authorizeOpsysDeviceTool,
  authorizeOpsysDeviceToolFresh,
  resetOpsysDeviceRolesCacheForTesting,
  resolveOpsysDeviceIdentity,
} from "./opsys-device-roles.js";

const tempDirs: string[] = [];

function writeFragments(
  dir: string,
  fragments: { roles?: unknown; appareils?: unknown },
): void {
  fs.mkdirSync(dir, { recursive: true });
  if (fragments.roles !== undefined) {
    fs.writeFileSync(path.join(dir, "roles.json"), JSON.stringify(fragments.roles));
  }
  if (fragments.appareils !== undefined) {
    fs.writeFileSync(path.join(dir, "appareils.json"), JSON.stringify(fragments.appareils));
  }
}

function makeTempDirWithServers(serveurs: unknown): string {
  const dir = makeTempDir(tempDirs, "opsys-device-roles-serveurs-");
  writeFragments(dir, {
    roles: {
      roles: { employee: ["m4_pointer_entree", "m4_vide", "toString"] },
      serveurs,
    },
    appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
  });
  return dir;
}

beforeEach(() => {
  resetOpsysDeviceRolesCacheForTesting();
});

afterEach(() => {
  cleanupTempDirs(tempDirs);
});

describe("authorizeOpsysDeviceTool", () => {
  it("authorizes a tool that is in the device's role scope", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: {
        roles: { employee: ["m4_pointer_entree", "m6_soumettre_materiaux"] },
        serveurs: { m4_pointer_entree: "opsys_m4", m6_soumettre_materiaux: "opsys_m6" },
      },
      appareils: { appareils: { "tel-employe-42": { personne: "jdupont", role: "employee" } } },
    });

    const result = authorizeOpsysDeviceTool("tel-employe-42", "m4_pointer_entree", dir);

    // The server that carries the tool comes back with the authorization, keyed by the same bare
    // name the scope was checked on (PLAN T1.4-c6): the name authorized is the name called.
    expect(result).toEqual({ ok: true, personne: "jdupont", role: "employee", serveur: "opsys_m4" });
    expect(authorizeOpsysDeviceTool("tel-employe-42", "m6_soumettre_materiaux", dir)).toEqual({
      ok: true,
      personne: "jdupont",
      role: "employee",
      serveur: "opsys_m6",
    });
  });

  it("refuses closed a tool that is in the role's scope but has no server entry — never guessing the server from the name", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] }, serveurs: { m6_autre_outil: "opsys_m6" } },
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
    });

    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "server_unknown",
    });
  });

  it("refuses closed when roles.json has no serveurs key at all (a fragment from before T1.4-c6)", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] } },
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
    });

    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "server_unknown",
    });
  });

  it("ignores a server entry that is not a non-empty string, and never reads an inherited object key", () => {
    const dir = makeTempDirWithServers({ m4_pointer_entree: 42, m4_vide: "" });

    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "server_unknown",
    });
    expect(authorizeOpsysDeviceTool("tel-1", "m4_vide", dir)).toEqual({
      ok: false,
      reason: "server_unknown",
    });
    // `toString` is in the role's list here on purpose: the server lookup must not answer with the
    // inherited `Object.prototype.toString`, only with an entry the file itself declares.
    expect(authorizeOpsysDeviceTool("tel-1", "toString", dir)).toEqual({
      ok: false,
      reason: "server_unknown",
    });
  });

  it("does not let a role named like an Object.prototype member read inherited state", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] }, serveurs: { m4_pointer_entree: "opsys_m4" } },
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "constructor" } } },
    });

    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "role_unknown",
    });
  });

  it("refuses closed when the device is not paired at all", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] } },
      appareils: { appareils: {} },
    });

    const result = authorizeOpsysDeviceTool("tel-inconnu", "m4_pointer_entree", dir);

    expect(result).toEqual({ ok: false, reason: "device_unknown" });
  });

  it("refuses closed when the paired role has no entry in roles.json", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] } },
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "orphan_role" } } },
    });

    const result = authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir);

    expect(result).toEqual({ ok: false, reason: "role_unknown" });
  });

  it("refuses closed when the tool is outside the role's declared scope", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] } },
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
    });

    const result = authorizeOpsysDeviceTool("tel-1", "m5_emettre_facture", dir);

    expect(result).toEqual({ ok: false, reason: "tool_out_of_scope" });
  });

  it("refuses closed when the fragments are missing entirely (fresh install, no pairing yet)", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-empty-");

    const result = authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir);

    expect(result).toEqual({ ok: false, reason: "device_unknown" });
  });

  it("refuses closed when a fragment is malformed JSON, without throwing", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "roles.json"), "{not valid json");
    fs.writeFileSync(
      path.join(dir, "appareils.json"),
      JSON.stringify({ appareils: { "tel-1": { personne: "jdupont", role: "employee" } } }),
    );

    expect(() => authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).not.toThrow();
    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "role_unknown",
    });
  });

  it("re-reads a fragment after it changes on disk (pairing approved, then revoked)", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-roles-");
    writeFragments(dir, {
      roles: { roles: { employee: ["m4_pointer_entree"] }, serveurs: { m4_pointer_entree: "opsys_m4" } },
      appareils: { appareils: {} },
    });
    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "device_unknown",
    });

    writeFragments(dir, {
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
    });
    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: true,
      personne: "jdupont",
      role: "employee",
      serveur: "opsys_m4",
    });

    writeFragments(dir, { appareils: { appareils: {} } });
    expect(authorizeOpsysDeviceTool("tel-1", "m4_pointer_entree", dir)).toEqual({
      ok: false,
      reason: "device_unknown",
    });
  });
});

describe("resolveOpsysDeviceIdentity (PLAN T1.4-c5)", () => {
  function writeAttribution(dir: string, appareils: Record<string, unknown>): void {
    writeFragments(dir, {
      roles: {
        roles: { employee: ["m4_pointer_entree"], seller: [], admin: ["m4_pointer_entree"] },
        serveurs: { m4_pointer_entree: "opsys_m4" },
      },
      appareils: { appareils },
    });
  }

  it("gives the person and the named role the fragments attribute to the device", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, {
      "tel-employe-42": { personne: "jdupont", role: "employee" },
      "tel-admin-1": { personne: "nathan_owner", role: "admin" },
    });

    expect(resolveOpsysDeviceIdentity("tel-employe-42", dir)).toEqual({
      ok: true,
      personne: "jdupont",
      role: "employee",
    });
    expect(resolveOpsysDeviceIdentity("tel-admin-1", dir)).toEqual({
      ok: true,
      personne: "nathan_owner",
      role: "admin",
    });
  });

  it("tells the app the same person and role the tool door applies — one code path, never two answers", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, { "tel-employe-42": { personne: "jdupont", role: "employee" } });

    const identity = resolveOpsysDeviceIdentity("tel-employe-42", dir);
    const authorization = authorizeOpsysDeviceTool("tel-employe-42", "m4_pointer_entree", dir);

    expect(identity.ok && authorization.ok).toBe(true);
    if (identity.ok && authorization.ok) {
      expect(authorization.personne).toBe(identity.personne);
      expect(authorization.role).toBe(identity.role);
    }
  });

  it("knows a role that declares no tool at all: an empty scope is a known role, not a missing one", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, { "tel-vendeur-7": { personne: "mtremblay", role: "seller" } });

    expect(resolveOpsysDeviceIdentity("tel-vendeur-7", dir)).toEqual({
      ok: true,
      personne: "mtremblay",
      role: "seller",
    });
  });

  it("gives no identity to a device with no attribution (never attributed, or revoked)", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, { "tel-employe-42": { personne: "jdupont", role: "employee" } });

    expect(resolveOpsysDeviceIdentity("tel-inconnu", dir)).toEqual({
      ok: false,
      reason: "device_unknown",
    });
  });

  it("never reads an inherited Object.prototype member as a device, for the identity or the tool door", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, { "tel-employe-42": { personne: "jdupont", role: "employee" } });

    for (const deviceId of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(resolveOpsysDeviceIdentity(deviceId, dir), deviceId).toEqual({
        ok: false,
        reason: "device_unknown",
      });
      expect(authorizeOpsysDeviceTool(deviceId, "m4_pointer_entree", dir), deviceId).toEqual({
        ok: false,
        reason: "device_unknown",
      });
    }
  });

  it("gives no identity for a role roles.json does not declare, nor for one named like an Object.prototype member", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, {
      "tel-1": { personne: "jdupont", role: "orphan_role" },
      "tel-2": { personne: "jdupont", role: "constructor" },
    });

    expect(resolveOpsysDeviceIdentity("tel-1", dir)).toEqual({ ok: false, reason: "role_unknown" });
    expect(resolveOpsysDeviceIdentity("tel-2", dir)).toEqual({ ok: false, reason: "role_unknown" });
  });

  it("ignores an entry without a non-empty person and role, so it never yields a half identity", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, {
      "tel-sans-personne": { role: "employee" },
      "tel-personne-vide": { personne: "", role: "employee" },
      "tel-sans-role": { personne: "jdupont" },
      "tel-role-numerique": { personne: "jdupont", role: 3 },
    });

    for (const deviceId of ["tel-sans-personne", "tel-personne-vide", "tel-sans-role", "tel-role-numerique"]) {
      expect(resolveOpsysDeviceIdentity(deviceId, dir), deviceId).toEqual({
        ok: false,
        reason: "device_unknown",
      });
    }
  });

  it("gives no identity when the fragments are missing or malformed, and never throws", () => {
    const missing = makeTempDir(tempDirs, "opsys-device-identity-empty-");
    expect(resolveOpsysDeviceIdentity("tel-1", missing)).toEqual({
      ok: false,
      reason: "device_unknown",
    });

    const malformed = makeTempDir(tempDirs, "opsys-device-identity-bad-");
    fs.writeFileSync(path.join(malformed, "roles.json"), "{not valid json");
    fs.writeFileSync(
      path.join(malformed, "appareils.json"),
      JSON.stringify({ appareils: { "tel-1": { personne: "jdupont", role: "employee" } } }),
    );
    expect(() => resolveOpsysDeviceIdentity("tel-1", malformed)).not.toThrow();
    expect(resolveOpsysDeviceIdentity("tel-1", malformed)).toEqual({
      ok: false,
      reason: "role_unknown",
    });
  });

  it("follows the attribution on disk: attributed, re-attributed to another person, then revoked", () => {
    const dir = makeTempDir(tempDirs, "opsys-device-identity-");
    writeAttribution(dir, {});
    expect(resolveOpsysDeviceIdentity("tel-1", dir)).toEqual({ ok: false, reason: "device_unknown" });

    writeFragments(dir, {
      appareils: { appareils: { "tel-1": { personne: "jdupont", role: "employee" } } },
    });
    expect(resolveOpsysDeviceIdentity("tel-1", dir)).toEqual({
      ok: true,
      personne: "jdupont",
      role: "employee",
    });

    // Each rewrite changes the file size on purpose: the cache keys on mtime AND size, and a coarse
    // filesystem clock could alias two same-size rewrites made within one tick.
    writeFragments(dir, {
      appareils: { appareils: { "tel-1": { personne: "mtremblay", role: "admin" } } },
    });
    expect(resolveOpsysDeviceIdentity("tel-1", dir)).toEqual({
      ok: true,
      personne: "mtremblay",
      role: "admin",
    });

    writeFragments(dir, { appareils: { appareils: {} } });
    expect(resolveOpsysDeviceIdentity("tel-1", dir)).toEqual({ ok: false, reason: "device_unknown" });
  });
});

describe("fresh named photo authority", () => {
  it("does not reuse same-size, same-mtime attribution or scope fragments", () => {
    const dir = makeTempDir(tempDirs, "opsys-photo-fresh-");
    const tool = "m6_lire_preuves_pertes_wct_appareil";
    writeFragments(dir, {
      roles: { roles: { admin: [tool] }, serveurs: { [tool]: "opsys_m6" } },
      appareils: { appareils: { "tel-1": { personne: "alice", role: "admin" } } },
    });
    const file = path.join(dir, "appareils.json");
    const rolesFile = path.join(dir, "roles.json");
    fs.utimesSync(file, 1000, 1000);
    fs.utimesSync(rolesFile, 1000, 1000);
    const stat = fs.statSync(file);
    expect(authorizeOpsysDeviceTool("tel-1", tool, dir).ok).toBe(true);
    fs.writeFileSync(
      file,
      JSON.stringify({ appareils: { "tel-1": { personne: "other", role: "admin" } } }),
    );
    fs.utimesSync(file, stat.atime, stat.mtime);
    expect(fs.statSync(file).mtimeMs).toBe(stat.mtimeMs);
    expect(fs.statSync(file).size).toBe(stat.size);
    expect(authorizeOpsysDeviceTool("tel-1", tool, dir)).toMatchObject({ personne: "alice" });
    const fresh = authorizeOpsysDeviceToolFresh;
    expect(fresh("tel-1", tool, dir)).toEqual({
      ok: true,
      personne: "other",
      role: "admin",
      serveur: "opsys_m6",
    });
    fs.writeFileSync(
      path.join(dir, "roles.json"),
      JSON.stringify({
        roles: { admin: [tool.replace("appareil", "appareiX")] },
        serveurs: { [tool]: "opsys_m6" },
      }),
    );
    fs.utimesSync(rolesFile, 1000, 1000);
    expect(authorizeOpsysDeviceTool("tel-1", tool, dir).ok).toBe(true);
    expect(fresh("tel-1", tool, dir)).toEqual({ ok: false, reason: "tool_out_of_scope" });
  });
});
