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
  resetOpsysDeviceRolesCacheForTesting,
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
