// Covers the Doctor migration of the OPSYS instance state: ~/.openclaw-opsys (installs made since T0.11-b)
// moves to ~/.opsys/core, safely: moved never copied, nothing overwritten, a link left behind, checked,
// and re-runnable.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempDirSync, withTestDir } from "../test-helpers/temp-dir.js";
import {
  migrateLegacyOpsysStateDir,
  resolveOpsysLegacyStateMigrationPaths,
  type OpsysStateMoveDeps,
} from "./state-migrations.opsys-instance.js";
import {
  autoMigrateLegacyStateDir,
  resetAutoMigrateLegacyStateDirForTest,
  resolvePendingLegacyStateDirMigrationPaths,
} from "./state-migrations.state-dir.js";

const DIR_LINK_TYPE = process.platform === "win32" ? "junction" : "dir";
const ENV_FILE = "OPSYS_MCP_JETON=fictif-0123456789abcdef\n";

type Instance = {
  home: string;
  legacy: string;
  canonical: string;
  env: NodeJS.ProcessEnv;
  homedir: () => string;
};

function instanceIn(home: string, active: "canonical" | "legacy"): Instance {
  const legacy = path.join(home, ".openclaw-opsys");
  const canonical = path.join(home, ".opsys", "core");
  return {
    home,
    legacy,
    canonical,
    env: {
      OPENCLAW_PROFILE: "opsys",
      OPENCLAW_STATE_DIR: active === "canonical" ? canonical : legacy,
    },
    homedir: () => home,
  };
}

function withInstance(
  run: (instance: Instance) => void,
  active: "canonical" | "legacy" = "canonical",
) {
  withTempDirSync({ prefix: "opsys-state-migration-" }, (home) => {
    run(instanceIn(home, active));
  });
}

/** A state shaped like the one the installer writes: secrets, config, engine supervisor settings. */
function seedState(dir: string, secret = ENV_FILE): void {
  fs.mkdirSync(path.join(dir, "opsys"), { recursive: true });
  fs.writeFileSync(path.join(dir, ".env"), secret, "utf8");
  fs.writeFileSync(path.join(dir, "openclaw.json"), '{"gateway":{"port":18789}}\n', "utf8");
  fs.writeFileSync(path.join(dir, "opsys", "metier.json"), '{"actif":true}\n', "utf8");
}

function snapshotOf(dir: string, prefix = ""): Record<string, string> {
  const files: Record<string, string> = {};
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const relative = path.join(prefix, entry.name);
    if (entry.isDirectory()) {
      Object.assign(files, snapshotOf(path.join(dir, entry.name), relative));
    } else {
      files[relative] = fs.readFileSync(path.join(dir, entry.name), "utf8");
    }
  }
  return files;
}

function realDeps(overrides: Partial<OpsysStateMoveDeps> = {}): OpsysStateMoveDeps {
  return {
    rename: (from, to) => fs.renameSync(from, to),
    symlink: (target, linkPath, type) => fs.symlinkSync(target, linkPath, type),
    platform: "linux",
    ...overrides,
  };
}

describe("OPSYS state migration: the move", () => {
  it("moves the former state, links the former path and keeps every file", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const before = snapshotOf(legacy);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.warnings).toEqual([]);
      expect(result.changes).toEqual([
        `State dir: ${legacy} → ${canonical} (former path now linked)`,
      ]);
      expect(result.notices).toHaveLength(1);
      expect(result.notices[0]).toContain("gateway install --force");
      expect(snapshotOf(canonical)).toEqual(before);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(true);
      expect(fs.realpathSync(legacy)).toBe(fs.realpathSync(canonical));
      expect(fs.readFileSync(path.join(legacy, ".env"), "utf8")).toBe(ENV_FILE); // an old service still finds it
    });
  });

  it("keeps a config file named openclaw.json as it is: the installed service names that file", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);

      migrateLegacyOpsysStateDir({ env, homedir });

      expect(fs.existsSync(path.join(canonical, "openclaw.json"))).toBe(true);
      expect(fs.existsSync(path.join(canonical, "opsys.json"))).toBe(false);
    });
  });

  it("can be run again: a second run finds nothing to do", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      migrateLegacyOpsysStateDir({ env, homedir });
      const after = snapshotOf(canonical);

      const again = migrateLegacyOpsysStateDir({ env, homedir });

      expect(again).toEqual({ changes: [], warnings: [], notices: [] });
      expect(snapshotOf(canonical)).toEqual(after);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(true);
    });
  });

  it("works from the former directory too: a process that still names it (an old service) is migrated", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.changes).toHaveLength(1);
      expect(fs.readFileSync(path.join(canonical, ".env"), "utf8")).toBe(ENV_FILE);
    }, "legacy");
  });

  it("creates the instance directory privately when it does not exist yet", () => {
    withInstance(({ home, legacy, env, homedir }) => {
      seedState(legacy);

      migrateLegacyOpsysStateDir({ env, homedir });

      if (process.platform !== "win32") {
        expect(fs.statSync(path.join(home, ".opsys")).mode & 0o077).toBe(0);
      }
    });
  });

  it("replaces an empty canonical directory: it holds nothing to lose", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      fs.mkdirSync(canonical, { recursive: true });
      seedState(legacy);
      const before = snapshotOf(legacy);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.warnings).toEqual([]);
      expect(snapshotOf(canonical)).toEqual(before);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(true);
    });
  });

  it("links an empty former directory to an existing canonical state", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(canonical);
      fs.mkdirSync(legacy);
      const before = snapshotOf(canonical);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.warnings).toEqual([]);
      expect(result.changes).toEqual([
        `State dir: ${legacy} → ${canonical} (empty former path now linked)`,
      ]);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(true);
      expect(snapshotOf(canonical)).toEqual(before);
    });
  });
});

describe("OPSYS state migration: what it leaves alone", () => {
  it("does nothing on a new poste", () => {
    withInstance(({ home, env, homedir }) => {
      expect(resolveOpsysLegacyStateMigrationPaths({ env, homedir })).toBeUndefined();

      expect(migrateLegacyOpsysStateDir({ env, homedir })).toEqual({
        changes: [],
        warnings: [],
        notices: [],
      });
      expect(fs.existsSync(path.join(home, ".opsys"))).toBe(false);
    });
  });

  it("leaves an empty former directory alone when there is no state to link it to", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      fs.mkdirSync(legacy);

      expect(resolveOpsysLegacyStateMigrationPaths({ env, homedir })).toBeUndefined();
      expect(migrateLegacyOpsysStateDir({ env, homedir }).changes).toEqual([]);
      expect(fs.lstatSync(legacy).isDirectory()).toBe(true);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("applies to the opsys profile and to its own state directories only", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const other = [
        { ...env, OPENCLAW_PROFILE: "work" },
        { ...env, OPENCLAW_PROFILE: "Opsys" },
        { ...env, OPENCLAW_PROFILE: undefined },
        { ...env, OPENCLAW_STATE_DIR: path.join(path.dirname(legacy), "elsewhere") },
        { ...env, OPENCLAW_STATE_DIR: undefined },
      ];

      for (const candidate of other) {
        expect(resolveOpsysLegacyStateMigrationPaths({ env: candidate, homedir })).toBeUndefined();
        expect(migrateLegacyOpsysStateDir({ env: candidate, homedir }).changes).toEqual([]);
      }
      expect(fs.lstatSync(legacy).isDirectory()).toBe(true);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("stops when both locations hold state: nothing moved, merged or deleted, and it says what to do", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy, "OPSYS_MCP_JETON=ancien-fictif-0123456789abcdef\n");
      seedState(canonical, "OPSYS_MCP_JETON=nouveau-fictif-0123456789abcdef\n");
      const legacyBefore = snapshotOf(legacy);
      const canonicalBefore = snapshotOf(canonical);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.changes).toEqual([]);
      expect(result.warnings).toHaveLength(1);
      const [warning] = result.warnings;
      expect(warning).toContain(legacy);
      expect(warning).toContain(canonical);
      expect(warning).toContain("Nothing was moved, merged or deleted");
      expect(warning).toContain(`${legacy}.old`);
      expect(warning).toContain(`${canonical}.old`);
      expect(warning).toContain("human decision");
      expect(warning).not.toContain("fictif-0123456789abcdef"); // never a secret in a message
      expect(snapshotOf(legacy)).toEqual(legacyBefore);
      expect(snapshotOf(canonical)).toEqual(canonicalBefore);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(false);
      expect(resolveOpsysLegacyStateMigrationPaths({ env, homedir })).toEqual({
        source: legacy,
        target: canonical,
      });
    });
  });

  it("refuses a former path that is a link to somewhere else", () => {
    withInstance(({ home, legacy, canonical, env, homedir }) => {
      const elsewhere = path.join(home, "on-another-disk");
      seedState(elsewhere);
      fs.symlinkSync(elsewhere, legacy, DIR_LINK_TYPE);
      const before = snapshotOf(elsewhere);

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.changes).toEqual([]);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("symbolic link");
      expect(result.warnings[0]).toContain(elsewhere);
      expect(snapshotOf(elsewhere)).toEqual(before);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("refuses a former path that is not a directory", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      fs.writeFileSync(legacy, "not a directory", "utf8");

      const result = migrateLegacyOpsysStateDir({ env, homedir });

      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("is not a directory");
      expect(fs.readFileSync(legacy, "utf8")).toBe("not a directory");
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });
});

describe("OPSYS state migration: failures leave the state where it was", () => {
  it("changes nothing when the move fails, and says how to move it by hand", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const before = snapshotOf(legacy);
      const deps = realDeps({
        rename: () => {
          throw Object.assign(new Error("cross-device link not permitted"), { code: "EXDEV" });
        },
      });

      const result = migrateLegacyOpsysStateDir({ env, homedir }, deps);

      expect(result.changes).toEqual([]);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("cross-device link not permitted");
      expect(result.warnings[0]).toContain("Nothing was copied or deleted");
      expect(result.warnings[0]).toContain("stop the Gateway service");
      expect(snapshotOf(legacy)).toEqual(before);
      expect(fs.lstatSync(legacy).isDirectory()).toBe(true);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("moves the state back when the moved tree lacks something the former one held", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const deps = realDeps({
        rename: (from, to) => {
          fs.renameSync(from, to);
          if (to === canonical) {
            fs.rmSync(path.join(to, ".env")); // what a faulty filesystem move would look like
          }
        },
      });

      const result = migrateLegacyOpsysStateDir({ env, homedir }, deps);

      expect(result.changes).toEqual([]);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("rolled back");
      expect(fs.lstatSync(legacy).isDirectory()).toBe(true);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(false);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("moves the state back when the former path cannot be linked", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const before = snapshotOf(legacy);
      const deps = realDeps({
        symlink: () => {
          throw new Error("EPERM: operation not permitted");
        },
      });

      const result = migrateLegacyOpsysStateDir({ env, homedir }, deps);

      expect(result.changes).toEqual([]);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("rolled back");
      expect(result.warnings[0]).toContain("failed to link the former path");
      expect(snapshotOf(legacy)).toEqual(before);
      expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(false);
      expect(fs.existsSync(canonical)).toBe(false);
    });
  });

  it("reports a rollback that fails too, and where the state now is", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      let renames = 0;
      const deps = realDeps({
        rename: (from, to) => {
          renames += 1;
          if (renames > 1) {
            throw new Error("EBUSY: resource busy");
          }
          fs.renameSync(from, to);
        },
        symlink: () => {
          throw new Error("EPERM: operation not permitted");
        },
      });

      const result = migrateLegacyOpsysStateDir({ env, homedir }, deps);

      expect(result.changes).toEqual([`State dir: ${legacy} → ${canonical}`]);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain("the rollback failed");
      expect(result.warnings[0]).toContain(canonical);
      expect(result.warnings[0]).toContain("gateway install --force");
      expect(fs.readFileSync(path.join(canonical, ".env"), "utf8")).toBe(ENV_FILE);
    });
  });

  it("falls back to a junction when a directory symlink is not allowed on Windows", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);
      const types: string[] = [];
      const deps = realDeps({
        platform: "win32",
        symlink: (target, linkPath, type) => {
          types.push(type);
          if (type === "dir") {
            throw new Error("EPERM: operation not permitted");
          }
          fs.symlinkSync(target, linkPath, "junction");
        },
      });

      const result = migrateLegacyOpsysStateDir({ env, homedir }, deps);

      expect(types).toEqual(["dir", "junction"]);
      expect(result.warnings).toEqual([]);
      expect(result.changes).toHaveLength(1);
      expect(fs.realpathSync(legacy)).toBe(fs.realpathSync(canonical));
    });
  });
});

describe("OPSYS state migration through the Doctor entry points", () => {
  it("reports the pair to move, then nothing once it is moved", () => {
    withInstance(({ legacy, canonical, env, homedir }) => {
      seedState(legacy);

      expect(resolvePendingLegacyStateDirMigrationPaths({ env, homedir })).toEqual({
        source: legacy,
        target: canonical,
      });

      migrateLegacyOpsysStateDir({ env, homedir });

      expect(resolvePendingLegacyStateDirMigrationPaths({ env, homedir })).toBeUndefined();
    });
  });

  it("still ignores every other explicit state root", () => {
    withInstance(({ legacy, env, homedir }) => {
      seedState(legacy);

      expect(
        resolvePendingLegacyStateDirMigrationPaths({
          env: { OPENCLAW_STATE_DIR: env.OPENCLAW_STATE_DIR },
          homedir,
        }),
      ).toBeUndefined();
    });
  });

  it("autoMigrateLegacyStateDir moves the former state of the opsys profile", async () => {
    resetAutoMigrateLegacyStateDirForTest();
    try {
      await withTestDir({ prefix: "opsys-state-migration-" }, async (home) => {
        const { legacy, canonical, env, homedir } = instanceIn(home, "canonical");
        seedState(legacy);

        const result = await autoMigrateLegacyStateDir({ env, homedir });

        expect(result.migrated).toBe(true);
        expect(result.skipped).toBe(false);
        expect(result.changes).toContain(
          `State dir: ${legacy} → ${canonical} (former path now linked)`,
        );
        expect(result.warnings).toEqual([]);
        expect(result.notices?.join("\n")).toContain("gateway install --force");
        expect(fs.readFileSync(path.join(canonical, ".env"), "utf8")).toBe(ENV_FILE);
        expect(fs.lstatSync(legacy).isSymbolicLink()).toBe(true);
      });
    } finally {
      resetAutoMigrateLegacyStateDirForTest();
    }
  });
});
